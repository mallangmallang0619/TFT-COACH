"""
In-Game Capture Wizard — UI references only

Component icons and champion portraits are sourced from Data Dragon
(see backend/fetch_templates.py). This wizard handles the assets that
can only come from a live client:

  - A full-frame reference screenshot
  - An ROI overlay preview for verifying config.py is calibrated
  - Per-region UI crops (stage banner, augment panel, item bench frame)
    used as anchors and phase detectors by the detector

Run while TFT is open and visible (planning phase is ideal):

    python backend/capture_templates.py
    python backend/capture_templates.py --quick      # save every ROI crop, no prompts
    python backend/capture_templates.py --no-confirm # don't pause between regions
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

import cv2
import numpy as np

from config import (
    COMPONENT_TEMPLATE_DIR,
    UI_TEMPLATE_DIR,
    GameROIs,
    RegionOfInterest,
)
from capture import ScreenCapture

logger = logging.getLogger("capture_templates")


# Which UI elements we save as named templates. Each one corresponds to a
# field on GameROIs — the detector matches against these to find the live
# region on screen.
UI_REGIONS: list[str] = [
    "stage",
    "player_hp",
    "gold",
    "level",
    "item_bench",
    "champion_bench",
    "board",
    "augment_panel",
    "shop",
]

# Colors (BGR) used to draw ROI rectangles on the preview frame.
ROI_COLORS: dict[str, tuple[int, int, int]] = {
    "stage":          (0, 255, 0),
    "player_hp":      (0, 200, 255),
    "gold":           (0, 255, 255),
    "level":          (200, 200, 0),
    "item_bench":     (255, 100, 0),
    "champion_bench": (100, 255, 100),
    "board":          (255, 0, 255),
    "augment_panel":  (255, 255, 0),
    "shop":           (200, 200, 200),
}


@dataclass
class WizardOptions:
    quick: bool = False
    no_confirm: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _print_header():
    print("=" * 60)
    print("  TFT Coach — In-Game Capture Wizard")
    print("=" * 60)
    print()
    print("  Captures live UI references from your running TFT client.")
    print("  Components and champion portraits come from Data Dragon —")
    print("  run `python backend/fetch_templates.py` for those.")
    print()
    print("  Make sure TFT is running, visible, and ideally in the")
    print("  planning phase of a game.")
    print()


def _confirm(prompt: str, skip: bool) -> bool:
    if skip:
        return True
    try:
        ans = input(f"  {prompt} [Y/n]: ").strip().lower()
    except EOFError:
        return True
    return ans in ("", "y", "yes")


def _ensure_dirs():
    COMPONENT_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    UI_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)


# ── Drawing ───────────────────────────────────────────────────────────────────

def annotate_rois(frame: np.ndarray, rois: GameROIs) -> np.ndarray:
    """Return a copy of `frame` with every ROI from config drawn on it."""
    preview = frame.copy()
    h, w = preview.shape[:2]
    for name in UI_REGIONS:
        roi: Optional[RegionOfInterest] = getattr(rois, name, None)
        if roi is None:
            continue
        x, y, rw, rh = roi.to_pixels(w, h)
        color = ROI_COLORS.get(name, (255, 255, 255))
        cv2.rectangle(preview, (x, y), (x + rw, y + rh), color, 2)
        cv2.putText(
            preview, name, (x + 4, max(16, y - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA,
        )
    return preview


# ── Capture steps ─────────────────────────────────────────────────────────────

def capture_reference(capture: ScreenCapture) -> Optional[np.ndarray]:
    """Step 1: locate the game window + grab a single full-window frame."""
    print("\n[1/3] Locating game window...")
    if not capture.locate_game():
        print("  ✗ Could not find the TFT/League window.")
        print("    Make sure TFT is running and not minimized.")
        return None
    w = capture.window
    print(f"  ✓ Found: {w.width}×{w.height} at ({w.x}, {w.y})")

    print("\n[2/3] Capturing reference frame...")
    frame = capture.grab_frame()
    if frame is None or frame.size == 0:
        print("  ✗ Failed to capture frame.")
        return None

    ref_path = COMPONENT_TEMPLATE_DIR.parent / "reference_frame.png"
    cv2.imwrite(str(ref_path), frame)
    print(f"  ✓ {ref_path.relative_to(Path.cwd()) if ref_path.is_relative_to(Path.cwd()) else ref_path}")
    return frame


def save_roi_preview(frame: np.ndarray, rois: GameROIs) -> Path:
    """Step 3: draw every configured ROI on the frame and save it."""
    preview = annotate_rois(frame, rois)
    out = COMPONENT_TEMPLATE_DIR.parent / "roi_preview.png"
    cv2.imwrite(str(out), preview)
    return out


def save_ui_crops(
    frame: np.ndarray,
    rois: GameROIs,
    opts: WizardOptions,
) -> dict[str, Path]:
    """Crop and save each configured ROI to assets/templates/ui/<name>.png."""
    h, w = frame.shape[:2]
    saved: dict[str, Path] = {}

    for name in UI_REGIONS:
        roi: Optional[RegionOfInterest] = getattr(rois, name, None)
        if roi is None:
            continue

        x, y, rw, rh = roi.to_pixels(w, h)
        x = max(0, min(x, w - 1))
        y = max(0, min(y, h - 1))
        x2 = min(x + rw, w)
        y2 = min(y + rh, h)
        crop = frame[y:y2, x:x2]

        if crop.size == 0:
            print(f"  ✗ {name}: empty crop (check ROI ratios in config.py)")
            continue

        out_path = UI_TEMPLATE_DIR / f"{name}.png"
        if out_path.exists() and not opts.no_confirm and not opts.quick:
            if not _confirm(f"{out_path.name} exists — overwrite?", skip=False):
                print(f"  · {name}: skipped (kept existing)")
                continue

        cv2.imwrite(str(out_path), crop)
        saved[name] = out_path
        print(f"  ✓ {name:14s} {crop.shape[1]}×{crop.shape[0]}px → {out_path.name}")

    return saved


# ── Quick mode ────────────────────────────────────────────────────────────────

def quick_capture(capture: ScreenCapture) -> bool:
    """
    Non-interactive: dump every ROI to assets/templates/raw_captures/.
    Useful for offline inspection / manual cropping in an image editor.
    """
    print("Quick capture — saving every ROI region...\n")
    if not capture.locate_game():
        print("  ✗ Game window not found.")
        return False

    frame = capture.grab_frame()
    if frame is None or frame.size == 0:
        print("  ✗ Failed to capture frame.")
        return False

    out_dir = COMPONENT_TEMPLATE_DIR.parent / "raw_captures"
    out_dir.mkdir(parents=True, exist_ok=True)

    regions = capture.crop_all_rois(frame)
    for name, img in regions.items():
        if img.size == 0:
            print(f"  ✗ {name}: empty region")
            continue
        path = out_dir / f"{name}.png"
        cv2.imwrite(str(path), img)
        print(f"  ✓ {name:14s} {img.shape[1]}×{img.shape[0]}px → {path}")

    full_path = out_dir / "full_frame.png"
    cv2.imwrite(str(full_path), frame)
    print(f"  ✓ full_frame    → {full_path}")
    return True


# ── Entry point ───────────────────────────────────────────────────────────────

def run(opts: WizardOptions) -> int:
    _ensure_dirs()
    _print_header()

    capture = ScreenCapture()

    if opts.quick:
        ok = quick_capture(capture)
        return 0 if ok else 1

    frame = capture_reference(capture)
    if frame is None:
        return 1

    print("\n[3/3] Saving ROI preview + per-region crops...")
    preview_path = save_roi_preview(frame, capture.rois)
    print(f"  ✓ ROI preview → {preview_path.name}")
    print("    Open it to verify regions are aligned with the game UI.")
    print("    If they're off, tweak the ratios in config.py → GameROIs.")
    print()

    saved = save_ui_crops(frame, capture.rois, opts)

    print("\n" + "=" * 60)
    print(f"  Done. Saved {len(saved)} UI crop(s) to {UI_TEMPLATE_DIR}")
    print("=" * 60)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture live UI templates from TFT")
    parser.add_argument(
        "--quick", action="store_true",
        help="Dump every ROI to raw_captures/ without prompts",
    )
    parser.add_argument(
        "--no-confirm", action="store_true",
        help="Overwrite existing UI templates without prompting",
    )
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(message)s",
    )

    return run(WizardOptions(quick=args.quick, no_confirm=args.no_confirm))


if __name__ == "__main__":
    sys.exit(main())
