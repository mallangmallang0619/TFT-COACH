"""
TFT Coach — Screen Capture Module

Locates the TFT/League game window, captures frames at the configured FPS,
and provides cropped ROI images to the detection pipeline.
NEVER TESTED YET, PROBABLY BROKEN, MAYBE USELESS, PROCEED WITH CAUTION
"""

from __future__ import annotations
import platform
import logging
import time
from dataclasses import dataclass
from typing import Optional

try:
    import mss
    import numpy as np
except ImportError as _e:
    raise ImportError(
        f"Missing dependency: {_e}. "
        f"Install with: pip install mss numpy --break-system-packages"
    ) from _e

from config import (
    GAME_WINDOW_TITLE,
    CAPTURE_FPS,
    GameROIs,
    RegionOfInterest,
)

logger = logging.getLogger(__name__)


@dataclass
class WindowRect:
    """Bounding rectangle of the game window."""
    x: int
    y: int
    width: int
    height: int

    @property
    def monitor_dict(self) -> dict:
        """Format for mss capture."""
        return {
            "left": self.x,
            "top": self.y,
            "width": self.width,
            "height": self.height,
        }


class WindowFinder:
    """
    Cross-platform game window locator.
    Finds the TFT/League window and returns its bounding rect.
    """

    @staticmethod
    def find() -> Optional[WindowRect]:
        """Find the game window. Returns None if not found."""
        system = platform.system()

        try:
            if system == "Windows":
                return WindowFinder._find_windows()
            elif system == "Darwin":
                return WindowFinder._find_macos()
            else:
                return WindowFinder._find_linux()
        except Exception as e:
            logger.warning(f"Window detection failed: {e}")
            return None

    @staticmethod
    def _find_windows() -> Optional[WindowRect]:
        """Find window on Windows using pygetwindow."""
        try:
            import pygetwindow as gw
            windows = gw.getWindowsWithTitle(GAME_WINDOW_TITLE)
            if not windows:
                # Try alternative titles
                for alt_title in ["League of Legends (TM) Client", "Riot Games", "TFT"]:
                    windows = gw.getWindowsWithTitle(alt_title)
                    if windows:
                        break
            if not windows:
                return None

            win = windows[0]
            if win.isMinimized:
                logger.info("Game window is minimized")
                return None

            return WindowRect(
                x=win.left,
                y=win.top,
                width=win.width,
                height=win.height,
            )
        except ImportError:
            logger.error("pygetwindow not installed — required on Windows")
            return None

    @staticmethod
    def _find_macos() -> Optional[WindowRect]:
        """Find window on macOS using Quartz."""
        try:
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
            )
            window_list = CGWindowListCopyWindowInfo(
                kCGWindowListOptionOnScreenOnly, kCGNullWindowID
            )
            for window in window_list:
                name = window.get("kCGWindowOwnerName", "")
                if GAME_WINDOW_TITLE.lower() in name.lower():
                    bounds = window.get("kCGWindowBounds", {})
                    return WindowRect(
                        x=int(bounds.get("X", 0)),
                        y=int(bounds.get("Y", 0)),
                        width=int(bounds.get("Width", 0)),
                        height=int(bounds.get("Height", 0)),
                    )
            return None
        except ImportError:
            logger.error("pyobjc-framework-Quartz not installed — required on macOS")
            return None

    @staticmethod
    def _find_linux() -> Optional[WindowRect]:
        """Find window on Linux using xdotool."""
        import subprocess
        try:
            result = subprocess.run(
                ["xdotool", "search", "--name", GAME_WINDOW_TITLE],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None

            window_id = result.stdout.strip().split("\n")[0]

            geo_result = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", window_id],
                capture_output=True, text=True, timeout=2
            )
            if geo_result.returncode != 0:
                return None

            geo = {}
            for line in geo_result.stdout.strip().split("\n"):
                if "=" in line:
                    key, val = line.split("=", 1)
                    geo[key.strip()] = int(val.strip())

            return WindowRect(
                x=geo.get("X", 0),
                y=geo.get("Y", 0),
                width=geo.get("WIDTH", 0),
                height=geo.get("HEIGHT", 0),
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.error("xdotool not installed — required on Linux")
            return None


class ScreenCapture:
    """
    Captures the game window and provides cropped ROI frames.

    Usage:
        capture = ScreenCapture()
        if capture.locate_game():
            frame = capture.grab_frame()
            item_bench = capture.crop_roi(frame, rois.item_bench)
    """

    def __init__(self):
        self.sct = mss.mss()
        self.window: Optional[WindowRect] = None
        self.rois = GameROIs()
        self._last_capture_time = 0.0
        self._frame_interval = 1.0 / CAPTURE_FPS

    def locate_game(self) -> bool:
        """
        Find the game window. Call periodically in case the window
        moves or the game starts/stops.
        Returns True if the game window was found.
        """
        self.window = WindowFinder.find()
        if self.window:
            logger.info(
                f"Game window found: {self.window.width}x{self.window.height} "
                f"at ({self.window.x}, {self.window.y})"
            )
            return True
        return False

    @property
    def is_game_visible(self) -> bool:
        return self.window is not None

    def grab_frame(self) -> Optional[np.ndarray]:
        """
        Capture the full game window as a numpy array (BGR format).
        Respects the configured FPS cap to avoid burning CPU.
        Returns None if the window isn't available.
        """
        if not self.window:
            return None

        # FPS throttle
        now = time.time()
        elapsed = now - self._last_capture_time
        if elapsed < self._frame_interval:
            time.sleep(self._frame_interval - elapsed)

        try:
            screenshot = self.sct.grab(self.window.monitor_dict)
            self._last_capture_time = time.time()

            # Convert to numpy array (BGRA → BGR)
            frame = np.array(screenshot)
            frame = frame[:, :, :3]  # Drop alpha channel
            return frame

        except Exception as e:
            logger.warning(f"Frame capture failed: {e}")
            # Window may have moved — try relocating next cycle
            self.window = None
            return None

    def crop_roi(self, frame: np.ndarray, roi: RegionOfInterest) -> np.ndarray:
        """
        Crop a region of interest from a captured frame.
        Coordinates are converted from ratios to pixels.
        """
        h, w = frame.shape[:2]
        x, y, rw, rh = roi.to_pixels(w, h)

        # Clamp to frame bounds
        x = max(0, min(x, w - 1))
        y = max(0, min(y, h - 1))
        x2 = min(x + rw, w)
        y2 = min(y + rh, h)

        return frame[y:y2, x:x2].copy()

    def crop_all_rois(self, frame: np.ndarray) -> dict[str, np.ndarray]:
        """Crop all defined ROIs from a frame. Returns a dict of region name → image."""
        return {
            "stage": self.crop_roi(frame, self.rois.stage),
            "player_hp": self.crop_roi(frame, self.rois.player_hp),
            "gold": self.crop_roi(frame, self.rois.gold),
            "level": self.crop_roi(frame, self.rois.level),
            "item_bench": self.crop_roi(frame, self.rois.item_bench),
            "champion_bench": self.crop_roi(frame, self.rois.champion_bench),
            "board": self.crop_roi(frame, self.rois.board),
            "augment_panel": self.crop_roi(frame, self.rois.augment_panel),
            "shop": self.crop_roi(frame, self.rois.shop),
        }

    def grab_full_screen(self) -> np.ndarray:
        """Capture the entire primary monitor (for initial window detection)."""
        monitor = self.sct.monitors[1]  # Primary monitor
        screenshot = self.sct.grab(monitor)
        frame = np.array(screenshot)
        return frame[:, :, :3]
