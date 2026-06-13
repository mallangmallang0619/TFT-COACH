"""
Detection Harness — run the CV pipeline against a single frame and inspect it.

This is a developer tool for validating detector.py outside the live capture
loop. It runs the full Detector on one image and reports exactly what the
pipeline produced, plus saves an annotated overlay so you can eyeball whether
the configured ROIs actually line up with the game UI.

Usage:
    # Against a saved screenshot (the normal case)
    python backend/run_detection.py --image path/to/tft_screenshot.png

    # Grab one frame from the screen right now (TFT must be visible)
    python backend/run_detection.py --capture

    # No frame available — just render the ROI geometry on a blank canvas
    python backend/run_detection.py --rois-only

Outputs (under backend/_debug/):
    detection_overlay.png   frame with every ROI box + hex grid drawn on it
    roi_<name>.png          the cropped pixels each ROI actually sees
    state.json              the full detected GameState
"""

from __future__ import annotations
import argparse
import json
import logging
import sys
from pathlib import Path

# Make the sibling backend modules importable (mirrors main.py).
sys.path.insert(0, str(Path(__file__).parent))

import cv2
import numpy as np

from config import GAME_RESOLUTION, GameROIs, BOARD_HEX_GRID, CHAMPION_MATCH_THRESHOLD
from detector import Detector, TemplateStore

logger = logging.getLogger("run_detection")

DEBUG_DIR = Path(__file__).parent / "_debug"


# ── Frame acquisition ─────────────────────────────────────────────────────────

def load_frame(args) -> np.ndarray:
    """Resolve the frame to run on, from --image / --capture / synthetic."""
    if args.image:
        path = Path(args.image)
        if not path.exists():
            sys.exit(f"Image not found: {path}")
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if frame is None:
            sys.exit(f"Could not decode image: {path}")
        logger.info(f"Loaded {path}  ({frame.shape[1]}x{frame.shape[0]})")
        return frame

    if args.capture:
        try:
            import mss
        except ImportError:
            sys.exit("--capture needs `mss` installed (pip install mss)")
        with mss.mss() as sct:
            mon = sct.monitors[1]  # primary monitor
            shot = np.array(sct.grab(mon))
            frame = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
        logger.info(f"Captured screen  ({frame.shape[1]}x{frame.shape[0]})")
        return frame

    # Synthetic fallback: a flat gray canvas at the configured resolution.
    # Detection won't find anything real, but it proves the pipeline runs and
    # lets you sanity-check ROI geometry via the overlay.
    w, h = GAME_RESOLUTION.width, GAME_RESOLUTION.height
    logger.info(f"No --image/--capture given; using synthetic {w}x{h} gray frame")
    frame = np.full((h, w, 3), 60, dtype=np.uint8)
    return frame


# ── ROI overlay ───────────────────────────────────────────────────────────────

def draw_overlay(frame: np.ndarray) -> np.ndarray:
    """Draw every named ROI box and the board hex grid onto a copy of frame."""
    out = frame.copy()
    h, w = out.shape[:2]
    rois = GameROIs()

    named = {
        name: getattr(rois, name)
        for name in (
            "stage", "player_hp", "gold", "level",
            "item_bench", "champion_bench", "board", "augment_panel", "shop",
        )
    }

    for name, roi in named.items():
        x, y, rw, rh = roi.to_pixels(w, h)
        cv2.rectangle(out, (x, y), (x + rw, y + rh), (0, 255, 0), 2)
        cv2.putText(
            out, name, (x + 2, max(y - 4, 12)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA,
        )

    # Hex grid, drawn relative to the board ROI.
    bx, by, bw, bh = rois.board.to_pixels(w, h)
    for hexp in BOARD_HEX_GRID:
        cx = bx + int(hexp.cx * bw)
        cy = by + int(hexp.cy * bh)
        r = int(hexp.radius * bw)
        cv2.circle(out, (cx, cy), max(r, 3), (0, 180, 255), 1)

    return out


def dump_roi_crops(frame: np.ndarray) -> None:
    """Save each ROI's actual pixels so you can see what the detector sees."""
    h, w = frame.shape[:2]
    rois = GameROIs()
    for name in (
        "stage", "player_hp", "gold", "level",
        "item_bench", "champion_bench", "board", "augment_panel", "shop",
    ):
        roi = getattr(rois, name)
        x, y, rw, rh = roi.to_pixels(w, h)
        crop = frame[max(y, 0):y + rh, max(x, 0):x + rw]
        if crop.size:
            cv2.imwrite(str(DEBUG_DIR / f"roi_{name}.png"), crop)


# ── Reporting ─────────────────────────────────────────────────────────────────

def report(state) -> None:
    print("\n" + "=" * 60)
    print("  DETECTION RESULT")
    print("=" * 60)
    print(f"  phase        : {state.phase}  (conf {state.phase_confidence:.2f})")
    print(f"  stage        : {state.stage!r}  (conf {state.stage_confidence:.2f})")
    print(f"  hp / gold    : {state.player_hp} / {state.gold}")
    print(f"  level        : {state.level}")
    print(f"  components   : {state.component_ids or '—'}")
    board = [f"{c.name}@({c.board_row},{c.board_col}) {c.confidence:.2f}"
             for c in state.board_champions]
    bench = [f"{c.name} {c.confidence:.2f}" for c in state.bench_champions]
    print(f"  board champs : {board or '—'}")
    print(f"  bench champs : {bench or '—'}")
    print(f"  augments     : {[a.name for a in state.augment_options] or '—'}")
    print(f"  overall conf : {state.overall_confidence}")
    print(f"  detect time  : {state.detection_ms:.1f} ms "
          f"(champion threshold {CHAMPION_MATCH_THRESHOLD})")
    print("=" * 60)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the CV detector on one frame")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--image", help="path to a screenshot to analyze")
    src.add_argument("--capture", action="store_true", help="grab one screen frame now")
    ap.add_argument("--rois-only", action="store_true",
                    help="only draw ROI geometry; skip running the detector")
    ap.add_argument("--debug", action="store_true", help="verbose logging")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    DEBUG_DIR.mkdir(exist_ok=True)
    frame = load_frame(args)

    overlay = draw_overlay(frame)
    cv2.imwrite(str(DEBUG_DIR / "detection_overlay.png"), overlay)
    dump_roi_crops(frame)
    logger.info(f"Wrote ROI overlay + crops to {DEBUG_DIR}/")

    if args.rois_only:
        logger.info("--rois-only: skipping detector")
        return 0

    templates = TemplateStore()
    templates.load()
    detector = Detector(templates)

    state = detector.detect(frame)
    report(state)

    (DEBUG_DIR / "state.json").write_text(
        json.dumps(state.to_frontend_json(), indent=2, default=str)
    )
    logger.info(f"Wrote full state to {DEBUG_DIR}/state.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
