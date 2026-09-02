"""
Detection Diagnostic — see exactly what the pipeline sees.

Captures a frame (live game window, full screen, or a saved screenshot),
draws every configured ROI + the board hex grid onto it, runs the full
detector, and writes an annotated PNG plus a text report. This is the tool
to run when live detection misbehaves — one image shows whether the
problem is capture (wrong window/offset) or calibration (ROI drift).

Usage:
    python backend/diagnose_capture.py                  # capture live game window
    python backend/diagnose_capture.py --fullscreen     # capture whole monitor
    python backend/diagnose_capture.py --file shot.png  # annotate a screenshot
    python backend/diagnose_capture.py --dump-hexes     # save occupied board-unit
                                                        # and bench-slot crops

Output goes to backend/_debug/.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import cv2
import numpy as np

from capture import ScreenCapture, WindowFinder
from config import (
    BOARD_HEX_GRID,
    GAME_PROCESS_NAME,
    GAME_PROCESS_NAMES,
    GameROIs,
    ShopGeometry,
    TraitPanel,
    BENCH_CROP_HORIZONTAL_INSET_RATIO,
)
from detector import Detector, TemplateStore
from board_crops import extract_board_unit_crops

logger = logging.getLogger("diagnose")

DEBUG_DIR = Path(__file__).parent / "_debug"

ROI_COLORS = {
    "stage":          (0, 255, 255),   # yellow
    "player_hp":      (0, 0, 255),     # red
    "gold":           (0, 215, 255),   # gold
    "gold_standard":  (0, 165, 255),   # orange-gold
    "level":          (255, 0, 255),   # magenta
    "level_standard": (220, 80, 255),
    "item_bench":     (255, 128, 0),   # orange-blue
    "champion_bench": (255, 0, 0),     # blue
    "champion_bench_capture": (255, 100, 0),
    "board":          (0, 255, 0),     # green
    "augment_panel":  (128, 0, 128),   # purple
    "shop":           (255, 255, 0),   # cyan
}


def list_candidate_windows() -> list[str]:
    """Report TFT.exe plus visible windows that look League/TFT related."""
    lines = []
    try:
        import pygetwindow as gw
        for w in gw.getAllWindows():
            title = (w.title or "").strip()
            process_name = WindowFinder._process_name_windows(int(w._hWnd))
            lowered = title.lower()
            is_game = bool(
                process_name
                and process_name.casefold() in {
                    name.casefold() for name in GAME_PROCESS_NAMES
                }
            )
            if is_game or any(
                k in lowered for k in ("league", "tft", "riot", "teamfight")
            ):
                lines.append(
                    f"    {title!r} [{process_name or 'unknown process'}]  "
                    f"{w.width}x{w.height} at ({w.left},{w.top})"
                    f"{'  [minimized]' if w.isMinimized else ''}"
                )
    except Exception as e:
        lines.append(f"    (window enumeration failed: {e})")
    return lines


def acquire_frame(args) -> tuple[np.ndarray | None, str]:
    """Get a frame per the CLI flags. Returns (frame, source_description)."""
    if args.file:
        frame = cv2.imread(args.file)
        return frame, f"file: {args.file}"

    cap = ScreenCapture()
    if not args.fullscreen and cap.locate_game():
        frame = cap.grab_frame()
        w = cap.window
        return frame, f"game window: {w.width}x{w.height} at ({w.x},{w.y})"

    if not args.fullscreen:
        print(
            f"!! {GAME_PROCESS_NAME} window not found — "
            "capturing the full monitor instead."
        )
        print("   TFT/League-related windows currently visible:")
        for line in list_candidate_windows() or ["    (none)"]:
            print(line)
    frame = cap.grab_full_screen()
    return frame, "full primary monitor"


def annotate(frame: np.ndarray) -> np.ndarray:
    """Draw every ROI, the hex grid, and the trait-panel rows onto a copy."""
    out = frame.copy()
    h, w = out.shape[:2]
    thickness = max(2, w // 1200)
    font_scale = max(0.5, w / 3000)

    rois = GameROIs()
    for name, color in ROI_COLORS.items():
        if name == "player_hp":
            continue
        x, y, rw, rh = getattr(rois, name).to_pixels(w, h)
        cv2.rectangle(out, (x, y), (x + rw, y + rh), color, thickness)
        cv2.putText(out, name, (x, max(15, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness)

    # HP uses the full moving standings list, not the legacy fixed-row ROI.
    x0r, y0r, x1r, y1r = Detector._PLAYER_HP_SCAN
    x0, y0, x1, y1 = int(x0r * w), int(y0r * h), int(x1r * w), int(y1r * h)
    cv2.rectangle(out, (x0, y0), (x1, y1), ROI_COLORS["player_hp"], thickness)
    cv2.putText(out, "player_hp_scan", (x0, max(15, y0 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX, font_scale, ROI_COLORS["player_hp"], thickness)
    # Show the five exact shop cards/name bands used by batched OCR.
    shop = ShopGeometry()
    for slot in range(5):
        sx0 = int((shop.cards_x0 + slot * shop.card_pitch) * w)
        sx1 = int((shop.cards_x0 + (slot + 1) * shop.card_pitch) * w)
        cv2.rectangle(out, (sx0, int(0.855 * h)), (sx1, int(shop.name_y1 * h)),
                      ROI_COLORS["shop"], 1)
        cv2.rectangle(out, (sx0, int(shop.name_y0 * h)), (sx1, int(shop.name_y1 * h)),
                      (255, 255, 255), 1)

    # The harvester compares nine individual crops inside the broad bench ROI.
    nx, ny, nw, nh = rois.champion_bench_capture.to_pixels(w, h)
    slot_w = nw // 9
    inset = int(round(slot_w * BENCH_CROP_HORIZONTAL_INSET_RATIO))
    for slot in range(9):
        sx = nx + slot * slot_w + inset
        cv2.rectangle(out, (sx, ny), (nx + (slot + 1) * slot_w - inset, ny + nh),
                      ROI_COLORS["champion_bench"], 1)

    # Board hex centers (within the board ROI)
    bx, by, bw, bh = rois.board.to_pixels(w, h)
    for hexpos in BOARD_HEX_GRID:
        cx = bx + int(hexpos.cx * bw)
        cy = by + int(hexpos.cy * bh)
        r = int(hexpos.radius * bw)
        cv2.circle(out, (cx, cy), r, (0, 255, 0), thickness)
        cv2.putText(out, f"{hexpos.row},{hexpos.col}", (cx - r // 2, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale * 0.6, (0, 255, 0), 1)

    # Trait panel rows. Dark purple, NOT light gray — annotation pixels
    # land inside OCR/badge-test regions when a saved diagnostic frame is
    # re-analyzed, and near-white lines masquerade as badge digits.
    tp = TraitPanel()
    for i in range(tp.max_rows):
        cx = int(tp.symbol_cx * w)
        cy = int((tp.first_row_cy + i * tp.row_pitch) * h)
        half_w = int(tp.symbol_w * w / 2)
        half_h = int(tp.symbol_h * h / 2)
        cv2.rectangle(out, (cx - half_w, cy - half_h), (cx + half_w, cy + half_h),
                      (140, 40, 120), 1)

    return out


def dump_hex_crops(frame: np.ndarray, out_dir: Path) -> int:
    """Save health-bar-anchored board units and each bench-slot crop."""
    h, w = frame.shape[:2]
    rois = GameROIs()
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for sample in extract_board_unit_crops(frame, rois):
        cv2.imwrite(
            str(out_dir / f"board_r{sample.row}_c{sample.col}.png"),
            sample.crop,
        )
        count += 1

    nx, ny, nw, nh = rois.champion_bench_capture.to_pixels(w, h)
    slot_w = nw // 9
    inset = int(round(slot_w * BENCH_CROP_HORIZONTAL_INSET_RATIO))
    for i in range(9):
        crop = frame[
            ny:ny + nh,
            nx + i * slot_w + inset:nx + (i + 1) * slot_w - inset,
        ]
        if crop.size:
            cv2.imwrite(str(out_dir / f"bench_{i}.png"), crop)
            count += 1
    return count


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", help="Annotate a saved screenshot instead of capturing")
    ap.add_argument("--fullscreen", action="store_true",
                    help="Capture the whole primary monitor (skip window detection)")
    ap.add_argument("--dump-hexes", action="store_true",
                    help="Save occupied board-unit / bench-slot crops as PNGs")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    frame, source = acquire_frame(args)
    if frame is None:
        print("!! Could not acquire a frame.")
        return 1

    h, w = frame.shape[:2]
    print(f"Frame: {w}x{h}  ({source})")

    # Run the real detection pipeline and report what it reads.
    templates = TemplateStore()
    templates.load()
    detector = Detector(templates)
    # Mirror live mode. Portrait-template matching is only valid for the
    # synthetic simulator; UE5 board units are 3D models and otherwise yield
    # convincing false labels in diagnostics. With a trained model this falls
    # through to the CNN path; without one board/bench correctly stay empty.
    detector.match_board_units = False
    state = detector.detect(frame)

    print()
    print("── Detection results ──────────────────────────────")
    print(f"  phase:      {state.phase.value} (conf {state.phase_confidence:.2f})")
    print(f"  stage:      {state.stage!r} (conf {state.stage_confidence:.2f})")
    print(f"  player_hp:  {state.player_hp}")
    print(f"  lobby_hp:   {state.lobby_hp}")
    print(f"  gold:       {state.gold}")
    print(f"  level:      {state.level}")
    print(f"  components: {state.component_ids}")
    print(f"  shop:       {state.shop_units}")
    print(f"  board:      {[(c.name, c.board_row, c.board_col) for c in state.board_champions]}")
    print(f"  bench:      {[c.name for c in state.bench_champions]}")
    print(f"  synergies:  {[(s.name, s.count) for s in state.active_synergies]}")
    print(f"  detect ms:  {state.detection_ms:.0f}")
    print(f"  classifier: {'active' if detector.unit_classifier.available else 'inactive (no model)'}")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DEBUG_DIR / f"diagnose_{ts}.png"
    cv2.imwrite(str(out_path), annotate(frame))
    print()
    print(f"Annotated frame: {out_path}")
    print("Open it and check that each labeled box sits on the matching UI element.")

    if args.dump_hexes:
        crops_dir = DEBUG_DIR / f"hexes_{ts}"
        n = dump_hex_crops(frame, crops_dir)
        print(f"Saved {n} board-unit/bench crops to {crops_dir}")
        print("These crops are the raw material for real in-game unit templates.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
