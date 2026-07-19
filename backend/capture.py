"""
TFT Coach — Screen Capture Module

Locates the TFT/League game window, captures frames at the configured FPS,
and provides cropped ROI images to the detection pipeline.
"""

from __future__ import annotations
import platform
import logging
import time
from dataclasses import dataclass
from typing import Optional

# On Windows, mss captures physical pixels but window coordinates come back
# in DPI-virtualized units unless the process declares itself DPI-aware —
# with display scaling ≠ 100% that shifts every crop. Declare awareness
# before any window queries happen.
if platform.system() == "Windows":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

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
    def find(include_launcher: bool = False) -> Optional[WindowRect]:
        """Find the game window. Returns None if not found."""
        system = platform.system()

        try:
            if system == "Windows":
                return WindowFinder._find_windows(include_launcher)
            elif system == "Darwin":
                return WindowFinder._find_macos()
            else:
                return WindowFinder._find_linux()
        except Exception as e:
            logger.warning(f"Window detection failed: {e}")
            return None

    # Exact window titles we will capture, most preferred first. The game
    # renders in "League of Legends (TM) Client"; the launcher/lobby is
    # titled just "League of Legends". Substring matching is NOT safe here:
    # it latched onto any window mentioning the game — editors and terminals
    # with this "TFT-COACH" project open, browser tabs about League — and
    # the detector then OCR'd garbage out of them.
    _GAME_WINDOW_TITLE = "league of legends (tm) client"
    _LAUNCHER_WINDOW_TITLE = "league of legends"

    @staticmethod
    def _pick_game_window(windows, include_launcher: bool = False) -> Optional[object]:
        """Choose the game window from candidates with (title, isMinimized,
        width, height) attributes. Exact title match only. The launcher is
        diagnostic-only because capturing it before a match prevents the
        backend from noticing when the actual game window opens."""
        usable = [
            w for w in windows
            if not w.isMinimized and w.width > 200 and w.height > 200
        ]
        wanted_titles = [WindowFinder._GAME_WINDOW_TITLE]
        if include_launcher:
            wanted_titles.append(WindowFinder._LAUNCHER_WINDOW_TITLE)
        for wanted in wanted_titles:
            for w in usable:
                if w.title.strip().lower() == wanted:
                    return w
        return None

    @staticmethod
    def _find_windows(include_launcher: bool = False) -> Optional[WindowRect]:
        """Find the game window on Windows using pygetwindow."""
        try:
            import pygetwindow as gw
        except ImportError:
            logger.error("pygetwindow not installed — required on Windows")
            return None

        win = WindowFinder._pick_game_window(
            gw.getAllWindows(), include_launcher=include_launcher
        )
        if win is None:
            return None
        rect = WindowFinder._client_rect_windows(win)
        if rect:
            return rect
        return WindowRect(x=win.left, y=win.top, width=win.width, height=win.height)

    @staticmethod
    def _client_rect_windows(win) -> Optional[WindowRect]:
        """Screen-space client area of a window (no title bar / borders).

        In windowed mode the outer rect includes the title bar, which shifts
        every ROI down by ~30px. Fullscreen/borderless windows have identical
        client and outer rects, so this is safe for them too.
        """
        try:
            import ctypes
            from ctypes import wintypes

            hwnd = win._hWnd
            client = wintypes.RECT()
            if not ctypes.windll.user32.GetClientRect(hwnd, ctypes.byref(client)):
                return None
            origin = wintypes.POINT(0, 0)
            if not ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(origin)):
                return None
            width = client.right - client.left
            height = client.bottom - client.top
            if width <= 0 or height <= 0:
                return None
            return WindowRect(x=origin.x, y=origin.y, width=width, height=height)
        except Exception as e:
            logger.debug(f"Client-rect lookup failed, using outer rect: {e}")
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
