"""
Template Capture Wizard

Guided tool for capturing reference screenshots of TFT UI elements.
These templates are used by the CV detector for template matching.

Run this while TFT is open on your screen:
    python backend/capture_templates.py

The wizard will:
  1. Detect your game window
  2. Guide you through capturing each component icon
  3. Save templates to assets/templates/

You only need to run this once per resolution/patch.
NEED TO TEST, NEVER TESTED YET, PROBABLY BROKEN, MAYBE USELESS, PROCEED WITH CAUTION
"""

from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import cv2
import numpy as np

from config import (
    COMPONENT_TEMPLATE_DIR,
    CHAMPION_TEMPLATE_DIR,
    UI_TEMPLATE_DIR,
    COMPONENT_IDS,
    COMPONENT_NAMES,
    GameROIs,
)
from capture import ScreenCapture


class TemplateCaptureWizard:
    """Interactive wizard for capturing template images."""

    def __init__(self):
        self.capture = ScreenCapture()
        self.rois = GameROIs()

        # Ensure template directories exist
        COMPONENT_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
        CHAMPION_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
        UI_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

    def run(self):
        """Run the full template capture wizard."""
        self._print_header()

        # Step 1: Find the game window
        print("\n[Step 1] Locating game window...")
        if not self.capture.locate_game():
            print("  ✗ Could not find the TFT/League game window.")
            print("  Make sure TFT is running and visible on screen.")
            print("  Looked for window title containing 'League of Legends'")
            return

        w = self.capture.window
        print(f"  ✓ Found game window: {w.width}×{w.height} at ({w.x}, {w.y})")

        # Step 2: Full-screen reference capture
        print("\n[Step 2] Capturing full-screen reference...")
        frame = self.capture.grab_frame()
        if frame is None:
            print("  ✗ Failed to capture frame")
            return

        ref_path = COMPONENT_TEMPLATE_DIR.parent / "reference_frame.png"
        cv2.imwrite(str(ref_path), frame)
        print(f"  ✓ Saved reference frame: {ref_path}")

        # Step 3: Show ROI regions
        print("\n[Step 3] Analyzing UI regions...")
        self._show_roi_preview(frame)

        # Step 4: Component capture
        print("\n[Step 4] Component template capture")
        self._capture_components_auto(frame)

        # Step 5: Manual region selection mode
        print("\n[Step 5] Manual region capture (optional)")
        self._manual_capture_mode(frame)

        print("\n" + "=" * 60)
        print("  Template capture complete!")
        print(f"  Components: {len(list(COMPONENT_TEMPLATE_DIR.glob('*.png')))} templates")
        print(f"  Champions:  {len(list(CHAMPION_TEMPLATE_DIR.glob('*.png')))} templates")
        print(f"  UI:         {len(list(UI_TEMPLATE_DIR.glob('*.png')))} templates")
        print("=" * 60)

    def _print_header(self):
        print("=" * 60)
        print("  Template Capture Wizard")
        print("=" * 60)
        print()
        print("  This wizard captures reference images from your TFT client")
        print("  for the computer vision detection pipeline.")
        print()
        print("  Prerequisites:")
        print("  • TFT must be running and visible on your primary monitor")
        print("  • For best results, be in a game (planning phase)")
        print("  • Have item components on your bench")

    def _show_roi_preview(self, frame: np.ndarray):
        """Show where the ROIs are on the captured frame."""
        h, w = frame.shape[:2]
        preview = frame.copy()

        roi_colors = {
            "stage": (0, 255, 0),
            "player_hp": (0, 200, 255),
            "gold": (0, 255, 255),
            "item_bench": (255, 100, 0),
            "board": (255, 0, 255),
            "champion_bench": (100, 255, 100),
            "augment_panel": (255, 255, 0),
            "shop": (200, 200, 200),
        }

        for name, color in roi_colors.items():
            roi = getattr(self.rois, name, None)
            if roi is None:
                continue
            x, y, rw, rh = roi.to_pixels(w, h)
            cv2.rectangle(preview, (x, y), (x + rw, y + rh), color, 2)
            cv2.putText(
                preview, name, (x + 4, y + 16),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1
            )

        preview_path = COMPONENT_TEMPLATE_DIR.parent / "roi_preview.png"
        cv2.imwrite(str(preview_path), preview)
        print(f"  ✓ Saved ROI preview: {preview_path}")
        print("  Open this image to verify regions are correctly positioned.")
        print("  If regions are off, adjust the ratios in config.py → GameROIs")

    def _capture_components_auto(self, frame: np.ndarray):
        """
        Auto-capture component templates from the item bench region.
        Detects individual icons by finding contours in the bench area.
        """
        print("  Extracting item bench region...")
        h, w = frame.shape[:2]
        x, y, rw, rh = self.rois.item_bench.to_pixels(w, h)
        bench = frame[y:y+rh, x:x+rw]

        if bench.size == 0:
            print("  ✗ Item bench region is empty. Are you in a game?")
            return

        bench_path = COMPONENT_TEMPLATE_DIR.parent / "item_bench_raw.png"
        cv2.imwrite(str(bench_path), bench)
        print(f"  ✓ Saved raw bench image: {bench_path}")

        # Try to find individual component icons via contour detection
        gray = cv2.cvtColor(bench, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Filter to reasonable icon-sized contours
        min_area = (rh * 0.3) ** 2
        max_area = (rh * 1.2) ** 2
        icons = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if min_area < area < max_area:
                bx, by, bw, bh = cv2.boundingRect(cnt)
                if 0.5 < bw / bh < 2.0:  # Roughly square
                    icons.append((bx, by, bw, bh))

        # Sort left-to-right
        icons.sort(key=lambda r: r[0])

        if icons:
            print(f"  Found {len(icons)} potential component icon(s)")
            for i, (ix, iy, iw, ih) in enumerate(icons):
                icon_crop = bench[iy:iy+ih, ix:ix+iw]
                icon_path = COMPONENT_TEMPLATE_DIR / f"auto_component_{i:02d}.png"
                cv2.imwrite(str(icon_path), icon_crop)
                print(f"    Saved: {icon_path.name} ({iw}×{ih}px)")

            print()
            print("  AUTO-CAPTURED icons need to be renamed to match component IDs:")
            for comp_id, comp_name in COMPONENT_NAMES.items():
                print(f"    {comp_id}.png → {comp_name}")
            print()
            print("  Rename the auto_component_XX.png files to the correct IDs,")
            print("  or use manual capture mode (Step 5) to capture them precisely.")
        else:
            print("  ✗ Could not auto-detect component icons.")
            print("    Use manual capture mode instead.")

    def _manual_capture_mode(self, frame: np.ndarray):
        """
        Interactive mode for manually selecting regions to capture.
        Uses OpenCV's ROI selection.
        """
        print()
        print("  Manual capture lets you click-and-drag to select regions.")
        print("  This is useful for capturing specific champion portraits")
        print("  or component icons that weren't auto-detected.")
        print()

        response = input("  Start manual capture? (y/n): ").strip().lower()
        if response != "y":
            print("  Skipping manual capture.")
            return

        print()
        print("  Instructions:")
        print("  • A window will show the game screenshot")
        print("  • Click and drag to select a region")
        print("  • Press ENTER to save, ESC to skip")
        print("  • Press 'q' to quit manual capture mode")
        print()

        # Resize for display if frame is very large
        display_scale = 1.0
        if frame.shape[1] > 1920:
            display_scale = 1920 / frame.shape[1]

        display_frame = cv2.resize(frame, None, fx=display_scale, fy=display_scale)

        while True:
            name = input("  Template name (e.g., 'bf_sword', 'jinx', or 'q' to quit): ").strip()
            if name.lower() == "q":
                break

            # Determine save directory based on category
            category = input("  Category — (c)omponent, (h)champion, or (u)i: ").strip().lower()
            if category == "c":
                save_dir = COMPONENT_TEMPLATE_DIR
            elif category == "h":
                save_dir = CHAMPION_TEMPLATE_DIR
            else:
                save_dir = UI_TEMPLATE_DIR

            print("  Select region in the window, then press ENTER or SPACE...")

            roi = cv2.selectROI("TFT Coach - Select Region", display_frame, showCrosshair=True)
            cv2.destroyWindow("TFT Coach - Select Region")

            if roi[2] > 0 and roi[3] > 0:
                # Scale ROI back to original frame coordinates
                rx = int(roi[0] / display_scale)
                ry = int(roi[1] / display_scale)
                rw = int(roi[2] / display_scale)
                rh = int(roi[3] / display_scale)

                crop = frame[ry:ry+rh, rx:rx+rw]
                save_path = save_dir / f"{name}.png"
                cv2.imwrite(str(save_path), crop)
                print(f"  ✓ Saved: {save_path} ({rw}×{rh}px)")
            else:
                print("  ✗ No region selected, skipping.")


def quick_capture():
    """
    Quick capture mode: takes a screenshot of the item bench and board,
    saves them for manual template extraction in an image editor.
    """
    print("Quick Capture Mode — capturing game regions...\n")

    capture = ScreenCapture()
    if not capture.locate_game():
        print("Game window not found. Is TFT running?")
        return

    frame = capture.grab_frame()
    if frame is None:
        print("Failed to capture frame")
        return

    rois = GameROIs()
    regions = capture.crop_all_rois(frame)

    output_dir = COMPONENT_TEMPLATE_DIR.parent / "raw_captures"
    output_dir.mkdir(parents=True, exist_ok=True)

    for name, img in regions.items():
        if img.size > 0:
            path = output_dir / f"{name}.png"
            cv2.imwrite(str(path), img)
            print(f"  ✓ {name}: {img.shape[1]}×{img.shape[0]}px → {path}")

    # Also save the full frame
    full_path = output_dir / "full_frame.png"
    cv2.imwrite(str(full_path), frame)
    print(f"  ✓ full_frame → {full_path}")

    print(f"\nAll captures saved to: {output_dir}")
    print("Open these in an image editor to manually crop individual templates.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TFT Coach Template Capture")
    parser.add_argument("--quick", action="store_true", help="Quick capture (just save regions)")
    args = parser.parse_args()

    if args.quick:
        quick_capture()
    else:
        wizard = TemplateCaptureWizard()
        wizard.run()
