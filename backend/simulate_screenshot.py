"""
Screenshot Simulator — exercise the full app pipeline without a live game.

We have no canned TFT screenshots in the repo, and capturing real frames needs
the game running. This tool *synthesizes* a realistic board frame by compositing
the real champion portrait templates onto the board at their hex positions, then
runs the actual detector → coach pipeline on it. That proves the end-to-end loop
(frame → detected GameState → CoachingAdvice) works with deterministic input.

It can build a board from a named comp in the TFT Academy cache, or from an
explicit "Name:stars@boardIndex" list.

Usage:
    # Synthesize the "Big Bang Meepsie" comp and run detection + coaching
    python backend/simulate_screenshot.py --comp set-17-the-big-bang-meepsie

    # Explicit units
    python backend/simulate_screenshot.py --units "Meepsie:3@13,Pyke:3@23,Vex:1@0"

Outputs (under backend/_debug/):
    sim_frame.png         the synthesized screenshot fed to the detector
    sim_overlay.png       that frame with ROI boxes + detections drawn on it
    sim_state.json        the detected GameState
"""

from __future__ import annotations
import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import cv2
import numpy as np

from config import GAME_RESOLUTION, GameROIs, BOARD_HEX_GRID
from detector import Detector, TemplateStore
from coach import Coach
from game_state import GamePhase

logger = logging.getLogger("simulate")

DEBUG_DIR = Path(__file__).parent / "_debug"


# ── Realism ───────────────────────────────────────────────────────────────────

@dataclass
class Realism:
    """
    Knobs for degrading a synthesized frame toward what real capture looks like.

    The flat-template board is trivially matchable (~1.0 confidence). Real frames
    have textured backgrounds, scaled/jittered portraits, lighting variation, item
    icons and star pips overlapping the portrait, and sensor noise. Dialing these
    up lets the accuracy harness measure how robust template matching actually is
    and tune CHAMPION_MATCH_THRESHOLD against data instead of a guess.
    """
    bg_texture: bool = False       # colored, noisy board background vs flat gray
    scale_jitter: float = 0.0      # portrait resized by ±this fraction
    pos_jitter: int = 0            # portrait shifted by ±this many pixels
    brightness: float = 0.0        # lighting variation strength (0..1)
    noise_sigma: float = 0.0       # gaussian sensor noise stddev (0..~25)
    star_pips: bool = False        # draw star pips above the portrait
    hp_bars: bool = False          # draw a unit HP bar under the portrait

    @classmethod
    def preset(cls, name: str) -> "Realism":
        name = name.lower()
        if name in ("none", "flat", "off"):
            return cls()
        if name == "light":
            return cls(bg_texture=True, scale_jitter=0.06, pos_jitter=4,
                       brightness=0.15, noise_sigma=6.0, star_pips=True, hp_bars=True)
        if name == "heavy":
            return cls(bg_texture=True, scale_jitter=0.14, pos_jitter=10,
                       brightness=0.30, noise_sigma=16.0, star_pips=True, hp_bars=True)
        raise ValueError(f"unknown realism preset: {name!r}")

    @property
    def is_flat(self) -> bool:
        return self == Realism()


PRESET_ORDER = ["none", "light", "heavy"]
REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = REPO_ROOT / "assets" / "tftacademy_cache.json"
BOARD_COLS = 7  # boardIndex = row * BOARD_COLS + col


# ── Board construction ────────────────────────────────────────────────────────

def _hex_by_board_index(idx: int):
    """Map a TFT Academy boardIndex (0-27) to a HexPosition."""
    row, col = divmod(idx, BOARD_COLS)
    for hexp in BOARD_HEX_GRID:
        if hexp.row == row and hexp.col == col:
            return hexp
    return None


def star_map(units: list[dict]) -> dict[tuple[int, int], int]:
    """Map (board_row, board_col) → star level for a unit list.

    The CV pipeline can't read star pips yet, so callers use this to stamp the
    intended star levels onto detected champions before running the coach.
    """
    out: dict[tuple[int, int], int] = {}
    for u in units:
        hexp = _hex_by_board_index(u["boardIndex"])
        if hexp is not None:
            out[(hexp.row, hexp.col)] = u.get("stars", 1)
    return out


def _board_background(bw: int, bh: int, rng: np.random.Generator) -> np.ndarray:
    """A muted, slightly-textured board background (vs the flat-gray default)."""
    # Vertical gradient in a desaturated teal/brown range, plus low-freq blotches,
    # to approximate the TFT board without being so saturated that every empty hex
    # trips the detector's saturation-based "is this hex occupied?" heuristic.
    top = np.array([70, 75, 70], dtype=np.float32)
    bottom = np.array([45, 55, 60], dtype=np.float32)
    ramp = np.linspace(0, 1, bh, dtype=np.float32)[:, None, None]
    bg = (top * (1 - ramp) + bottom * ramp)
    bg = np.broadcast_to(bg, (bh, bw, 3)).copy()
    blotch = rng.normal(0, 8, (bh // 16, bw // 16, 3)).astype(np.float32)
    blotch = cv2.resize(blotch, (bw, bh), interpolation=cv2.INTER_CUBIC)
    bg = np.clip(bg + blotch, 0, 255)
    return bg.astype(np.uint8)


def _draw_star_pips(frame, x, y, w, stars: int) -> None:
    """Draw `stars` little markers centered above a portrait at (x, y) width w."""
    color = {1: (180, 200, 210), 2: (140, 200, 240), 3: (60, 200, 240)}.get(stars,
            (180, 200, 210))
    cx = x + w // 2
    for i in range(stars):
        px = cx + (i - (stars - 1) / 2) * 12
        cv2.circle(frame, (int(px), max(y - 6, 1)), 4, color, -1, cv2.LINE_AA)


def _draw_hp_bar(frame, x, y2, w, rng) -> None:
    """Draw a unit HP bar just under a portrait spanning (x, x+w) at row y2."""
    frac = float(rng.uniform(0.3, 1.0))
    by = min(y2 + 2, frame.shape[0] - 4)
    cv2.rectangle(frame, (x, by), (x + w, by + 3), (30, 30, 30), -1)
    cv2.rectangle(frame, (x, by), (x + int(w * frac), by + 3), (80, 220, 90), -1)


def synthesize_frame(
    units: list[dict],
    templates: TemplateStore,
    realism: "Realism | None" = None,
    seed: int | None = None,
) -> np.ndarray:
    """
    Build a synthesized TFT frame and composite each unit's real portrait onto its
    hex. With `realism=None` (default) the board is flat gray and portraits are
    pasted pixel-exact, so matching hits ~1.0 — good for driving the frontend. Pass
    a `Realism` to inject background texture, scale/position jitter, lighting, star
    pips, HP bars, and sensor noise so the accuracy harness can stress the matcher.
    """
    realism = realism or Realism()
    rng = np.random.default_rng(seed)
    w, h = GAME_RESOLUTION.width, GAME_RESOLUTION.height

    # Gray 100: equal RGB keeps empty hexes at ~0 saturation (read as empty) and is
    # bright enough that the augment-overlay check (mean < 80) never trips.
    frame = np.full((h, w, 3), 100, dtype=np.uint8)

    rois = GameROIs()
    bx, by, bw, bh = rois.board.to_pixels(w, h)
    if realism.bg_texture:
        frame[by:by + bh, bx:bx + bw] = _board_background(bw, bh, rng)

    placed = []
    for unit in units:
        name = unit["name"]
        template = templates.champion_templates.get(name)
        if template is None:
            logger.warning(f"No template for {name!r}; skipping")
            continue
        hexp = _hex_by_board_index(unit["boardIndex"])
        if hexp is None:
            logger.warning(f"boardIndex {unit['boardIndex']} out of range; skipping")
            continue

        cx = int(hexp.cx * bw)
        cy = int(hexp.cy * bh)
        r = int(hexp.radius * bw)
        base_w = base_h = 2 * r

        # Scale + position jitter, clipped to the board.
        sw_, sh_ = base_w, base_h
        if realism.scale_jitter:
            s = 1.0 + float(rng.uniform(-realism.scale_jitter, realism.scale_jitter))
            sw_, sh_ = max(8, int(base_w * s)), max(8, int(base_h * s))
        dx = dy = 0
        if realism.pos_jitter:
            dx = int(rng.integers(-realism.pos_jitter, realism.pos_jitter + 1))
            dy = int(rng.integers(-realism.pos_jitter, realism.pos_jitter + 1))

        portrait = cv2.resize(template, (sw_, sh_))
        if realism.brightness:
            alpha = 1.0 + float(rng.uniform(-realism.brightness, realism.brightness))
            beta = float(rng.uniform(-30, 30)) * realism.brightness
            portrait = cv2.convertScaleAbs(portrait, alpha=alpha, beta=beta)

        px = cx - sw_ // 2 + dx
        py = cy - sh_ // 2 + dy
        x1, y1 = max(0, px), max(0, py)
        x2, y2 = min(bw, px + sw_), min(bh, py + sh_)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = portrait[y1 - py:y2 - py, x1 - px:x2 - px]
        frame[by + y1:by + y2, bx + x1:bx + x2] = crop

        if realism.star_pips:
            _draw_star_pips(frame, bx + x1, by + y1, x2 - x1, unit.get("stars", 1))
        if realism.hp_bars:
            _draw_hp_bar(frame, bx + x1, by + y2, x2 - x1, rng)
        placed.append((name, hexp.row, hexp.col))

    # Give the stage ROI some non-blank content so _detect_phase doesn't bail to
    # NOT_IN_GAME (it treats a low-variance stage region as "not in a game").
    sx, sy, sw, sh = rois.stage.to_pixels(w, h)
    cv2.rectangle(frame, (sx, sy), (sx + sw, sy + sh), (20, 20, 20), -1)
    cv2.putText(frame, "3-5", (sx + 8, sy + sh - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (240, 240, 240), 2, cv2.LINE_AA)

    if realism.noise_sigma:
        noise = rng.normal(0, realism.noise_sigma, frame.shape)
        frame = np.clip(frame.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    logger.info(f"Synthesized frame with {len(placed)} units placed "
                f"(realism: {'flat' if realism.is_flat else realism})")
    for name, row, col in placed:
        logger.debug(f"    {name:<16} @ row{row} col{col}")
    return frame


def units_from_comp(slug: str) -> tuple[list[dict], str]:
    """Pull a comp's final-board units from the TFT Academy cache."""
    data = json.loads(CACHE_PATH.read_text())
    comp = next((c for c in data["comps"] if c["slug"] == slug), None)
    if comp is None:
        slugs = ", ".join(c["slug"] for c in data["comps"][:8])
        sys.exit(f"Comp {slug!r} not in cache. Try one of: {slugs}, …")
    units = []
    for u in comp.get("detail", {}).get("units") or []:
        if u.get("boardIndex") is None:
            continue
        units.append({"name": u["name"], "stars": u.get("stars", 1),
                      "boardIndex": u["boardIndex"]})
    return units, comp["name"]


def units_from_spec(spec: str) -> tuple[list[dict], str]:
    """Parse 'Name:stars@idx,Name:stars@idx' into unit dicts."""
    units = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        name_part, _, idx = chunk.partition("@")
        name, _, stars = name_part.partition(":")
        units.append({
            "name": name.strip(),
            "stars": int(stars) if stars else 1,
            "boardIndex": int(idx),
        })
    return units, "custom board"


# ── Reporting ─────────────────────────────────────────────────────────────────

def draw_overlay(frame: np.ndarray, state) -> np.ndarray:
    """Draw the board ROI and every detected champion's hex + name."""
    out = frame.copy()
    h, w = out.shape[:2]
    rois = GameROIs()
    bx, by, bw, bh = rois.board.to_pixels(w, h)
    cv2.rectangle(out, (bx, by), (bx + bw, by + bh), (0, 255, 0), 2)

    for champ in state.board_champions:
        hexp = next((p for p in BOARD_HEX_GRID
                     if p.row == champ.board_row and p.col == champ.board_col), None)
        if hexp is None:
            continue
        cx = bx + int(hexp.cx * bw)
        cy = by + int(hexp.cy * bh)
        cv2.circle(out, (cx, cy), 50, (0, 200, 255), 2)
        cv2.putText(out, f"{champ.name} {champ.confidence:.2f}",
                    (cx - 48, cy - 54), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 200, 255), 1, cv2.LINE_AA)
    return out


def report(state, advice) -> None:
    print("\n" + "=" * 64)
    print("  SIMULATED DETECTION")
    print("=" * 64)
    print(f"  phase        : {state.phase}  (conf {state.phase_confidence:.2f})")
    print(f"  detect time  : {state.detection_ms:.1f} ms")
    board = sorted(state.board_champions, key=lambda c: (c.board_row, c.board_col))
    print(f"  board champs ({len(board)}):")
    for c in board:
        print(f"      {c.name:<16} @({c.board_row},{c.board_col})  conf {c.confidence:.3f}")
    syn = [f"{s.name} {s.count}" for s in state.active_synergies if s.is_active]
    print(f"  synergies    : {syn or '—'}")
    print("\n" + "-" * 64)
    print("  COACH ADVICE")
    print("-" * 64)
    print(f"  board power  : {advice.board_power}  {advice.board_power_breakdown}")
    tips = getattr(advice, "tips", None) or []
    if tips:
        print("  tips:")
        for t in tips:
            msg = getattr(t, "message", t)
            print(f"      • {msg}")
    cd = getattr(advice, "comp_direction", None)
    if cd:
        print(f"  comp direction: {cd}")
    print("=" * 64)


def main() -> int:
    ap = argparse.ArgumentParser(description="Synthesize a frame and run the pipeline")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--comp", help="comp slug from the TFT Academy cache")
    src.add_argument("--units", help="'Name:stars@idx,...' explicit board")
    ap.add_argument("--realism", choices=PRESET_ORDER, default="none",
                    help="degrade the synthetic frame toward real capture")
    ap.add_argument("--seed", type=int, default=0, help="RNG seed for realism")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    DEBUG_DIR.mkdir(exist_ok=True)

    units, label = (units_from_comp(args.comp) if args.comp
                    else units_from_spec(args.units))
    print(f"Building board for: {label}")

    templates = TemplateStore()
    templates.load()

    frame = synthesize_frame(units, templates,
                             realism=Realism.preset(args.realism), seed=args.seed)
    cv2.imwrite(str(DEBUG_DIR / "sim_frame.png"), frame)

    detector = Detector(templates)
    state = detector.detect(frame)
    # Tag star levels onto detected champs from our intended board so the coach's
    # power math reflects the comp (the CV pipeline can't read star pips yet).
    star_by_pos = {(u_hex.row, u_hex.col): u["stars"]
                   for u in units
                   if (u_hex := _hex_by_board_index(u["boardIndex"])) is not None}
    for champ in state.board_champions:
        champ.star_level = star_by_pos.get((champ.board_row, champ.board_col), 1)

    coach = Coach()
    advice = coach.analyze(state)

    cv2.imwrite(str(DEBUG_DIR / "sim_overlay.png"), draw_overlay(frame, state))
    (DEBUG_DIR / "sim_state.json").write_text(
        json.dumps(state.to_frontend_json(), indent=2, default=str))

    report(state, advice)
    logger.info(f"Wrote sim_frame.png, sim_overlay.png, sim_state.json to {DEBUG_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
