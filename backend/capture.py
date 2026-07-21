"""
TFT Coach — Screen Capture Module

Locates the TFT/League game window, captures frames at the configured FPS,
and provides cropped ROI images to the detection pipeline.
"""

from __future__ import annotations
import platform
import logging
import threading
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

try:
    from windows_capture import WindowsCapture as _WindowsCapture
except ImportError:
    _WindowsCapture = None

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
    hwnd: Optional[int] = None
    outer_width: Optional[int] = None
    outer_height: Optional[int] = None
    capture_inset: tuple[int, int, int, int] = (0, 0, 0, 0)

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
        return WindowRect(
            x=win.left,
            y=win.top,
            width=win.width,
            height=win.height,
            hwnd=int(win._hWnd),
            outer_width=win.width,
            outer_height=win.height,
        )

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
            inset_left = max(0, origin.x - win.left)
            inset_top = max(0, origin.y - win.top)
            inset_right = max(0, win.width - inset_left - width)
            inset_bottom = max(0, win.height - inset_top - height)
            return WindowRect(
                x=origin.x,
                y=origin.y,
                width=width,
                height=height,
                hwnd=int(win._hWnd),
                outer_width=win.width,
                outer_height=win.height,
                capture_inset=(
                    inset_left,
                    inset_top,
                    inset_right,
                    inset_bottom,
                ),
            )
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


class WindowSurfaceCapture:
    """Capture one HWND through Windows Graphics Capture on a worker thread."""

    def __init__(self):
        self._capture = None
        self._control = None
        self._target_hwnd: Optional[int] = None
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_ready = threading.Event()
        self._lock = threading.Lock()
        self._generation = None
        self._closed = False
        self.last_error: Optional[str] = None

    @property
    def available(self) -> bool:
        return platform.system() == "Windows" and _WindowsCapture is not None

    @property
    def active(self) -> bool:
        return self._control is not None and not self._closed

    def start(self, hwnd: Optional[int]) -> bool:
        if not self.available or not hwnd:
            return False
        if self.active and self._target_hwnd == hwnd:
            return True

        self.stop()
        generation = object()
        self._generation = generation
        self._closed = False
        self.last_error = None
        try:
            capture = _WindowsCapture(
                cursor_capture=False,
                draw_border=False,
                secondary_window=False,
                minimum_update_interval=max(1, int(1000 / CAPTURE_FPS)),
                dirty_region=False,
                window_hwnd=int(hwnd),
            )

            @capture.event
            def on_frame_arrived(frame, _capture_control):
                if self._generation is not generation:
                    return
                image = frame.frame_buffer[:, :, :3].copy()
                with self._lock:
                    self._latest_frame = image
                self._frame_ready.set()

            @capture.event
            def on_closed():
                if self._generation is generation:
                    self._closed = True
                    self._frame_ready.set()

            control = capture.start_free_threaded()
            self._capture = capture
            self._control = control
            self._target_hwnd = int(hwnd)
            return True
        except Exception as error:
            self.last_error = str(error)
            self.stop()
            return False

    def grab(self, timeout: float = 0.35) -> Optional[np.ndarray]:
        if not self.active:
            return None
        if not self._frame_ready.wait(timeout):
            return None
        if self._closed:
            return None
        with self._lock:
            frame = self._latest_frame
        return frame.copy() if frame is not None else None

    def stop(self) -> None:
        self._generation = None
        control = self._control
        self._capture = None
        self._control = None
        self._target_hwnd = None
        self._closed = False
        self._frame_ready.clear()
        with self._lock:
            self._latest_frame = None
        if control is not None:
            try:
                control.stop()
            except Exception:
                pass


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
        self.window_capture = WindowSurfaceCapture()
        self.rois = GameROIs()
        self._last_capture_time = 0.0
        self._frame_interval = 1.0 / CAPTURE_FPS
        self._window_capture_failures = 0
        self._window_capture_retry_at = 0.0

    @property
    def capture_method(self) -> str:
        return "window" if self.window_capture.active else "screen"

    def locate_game(self) -> bool:
        """
        Find the game window. Call periodically in case the window
        moves or the game starts/stops.
        Returns True if the game window was found.
        """
        previous_hwnd = self.window.hwnd if self.window else None
        self.window = WindowFinder.find()
        if self.window:
            self._ensure_window_capture(force=self.window.hwnd != previous_hwnd)
            logger.info(
                f"Game window found: {self.window.width}x{self.window.height} "
                f"at ({self.window.x}, {self.window.y})"
            )
            return True
        self.window_capture.stop()
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
            self._ensure_window_capture()
            if self.window_capture.active:
                frame = self.window_capture.grab()
                normalized = self._normalize_window_frame(frame)
                if normalized is not None:
                    self._window_capture_failures = 0
                    self._last_capture_time = time.time()
                    return normalized
                self._window_capture_failures += 1
                if self._window_capture_failures >= 3:
                    logger.warning(
                        "Direct window capture stopped after 3 missing or invalid frames; "
                        "using screen fallback"
                    )
                    self.window_capture.stop()
                    self._window_capture_retry_at = time.monotonic() + 30.0

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

    def _ensure_window_capture(self, force: bool = False) -> bool:
        if self.window is None or not self.window.hwnd:
            return False
        if self.window_capture.active:
            return True
        now = time.monotonic()
        if not force and now < self._window_capture_retry_at:
            return False
        if self.window_capture.start(self.window.hwnd):
            self._window_capture_failures = 0
            self._window_capture_retry_at = 0.0
            logger.info("Direct League window capture active (overlay-safe)")
            return True
        self._window_capture_retry_at = now + 30.0
        if self.window_capture.available:
            logger.warning(
                "Direct window capture unavailable for this window; "
                f"using screen fallback ({self.window_capture.last_error})"
            )
        return False

    def close(self) -> None:
        self.window_capture.stop()
        self.sct.close()

    def _normalize_window_frame(
        self, frame: Optional[np.ndarray]
    ) -> Optional[np.ndarray]:
        if frame is None or self.window is None or frame.size == 0:
            return None
        expected_width = self.window.width
        expected_height = self.window.height
        height, width = frame.shape[:2]
        if (width, height) == (expected_width, expected_height):
            return frame

        outer_width = self.window.outer_width or expected_width
        outer_height = self.window.outer_height or expected_height
        if abs(width - outer_width) <= 4 and abs(height - outer_height) <= 4:
            left, top, right, bottom = self.window.capture_inset
            x2 = width - right if right else width
            y2 = height - bottom if bottom else height
            frame = frame[top:y2, left:x2]
            height, width = frame.shape[:2]

        if width <= 0 or height <= 0:
            return None
        width_error = abs(width - expected_width) / expected_width
        height_error = abs(height - expected_height) / expected_height
        if width_error > 0.03 or height_error > 0.03:
            logger.debug(
                f"Direct capture size {width}x{height} does not match "
                f"client {expected_width}x{expected_height}"
            )
            return None

        import cv2
        return cv2.resize(
            frame,
            (expected_width, expected_height),
            interpolation=cv2.INTER_AREA,
        )

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
