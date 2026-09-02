"""Automatic augment-choice tracking from OCR'd cards plus the game click.

The three offered names alone cannot reveal which card was chosen. On Windows,
``WindowsClickMonitor`` records only left-button down timestamps/coordinates.
``AugmentSelectionTracker`` then accepts the final click inside an offered card
after two consecutive frames confirm that the selection screen closed.

This module never injects input and never guesses the recommended augment was
taken. If the click is missing or ambiguous, the existing manual correction in
the overlay remains the source of truth.
"""

from __future__ import annotations

import platform
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Iterable, Optional

from game_state import DetectedAugment, GamePhase


@dataclass(frozen=True)
class PointerClick:
    timestamp: float
    x: int
    y: int
    foreground_hwnd: Optional[int] = None


class WindowsClickMonitor:
    """Read-only left-click monitor backed by Win32 polling."""

    def __init__(self, poll_seconds: float = 0.008, keep_seconds: float = 20.0):
        self.available = platform.system() == "Windows"
        self.poll_seconds = poll_seconds
        self.keep_seconds = keep_seconds
        self._clicks: deque[PointerClick] = deque(maxlen=256)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        if not self.available:
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="augment-click-monitor",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        self._thread = None

    def recent(self) -> list[PointerClick]:
        cutoff = time.time() - self.keep_seconds
        with self._lock:
            while self._clicks and self._clicks[0].timestamp < cutoff:
                self._clicks.popleft()
            return list(self._clicks)

    def _run(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            pressed = False
            while not self._stop.is_set():
                down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
                if down and not pressed:
                    point = wintypes.POINT()
                    if user32.GetCursorPos(ctypes.byref(point)):
                        foreground = user32.GetForegroundWindow()
                        click = PointerClick(
                            timestamp=time.time(),
                            x=int(point.x),
                            y=int(point.y),
                            foreground_hwnd=int(foreground) if foreground else None,
                        )
                        with self._lock:
                            self._clicks.append(click)
                pressed = down
                self._stop.wait(self.poll_seconds)
        except Exception:
            # Automatic tracking is optional. The manual MARK TAKEN control
            # remains available if Win32 input state cannot be read.
            self.available = False


class AugmentSelectionTracker:
    """Resolve an offered augment after a confirmed selection-screen exit."""

    CARD_CENTERS_X = (0.287, 0.500, 0.713)
    CARD_HALF_WIDTH = 0.105
    CARD_Y_RANGE = (0.22, 0.82)

    def __init__(self, exit_confirmations: int = 2):
        self.exit_confirmations = max(1, exit_confirmations)
        self.reset()

    def reset(self) -> None:
        self._pending: dict[int, str] = {}
        self._offer_seen_at = 0.0
        self._exit_frames = 0

    def observe(
        self,
        phase: GamePhase,
        options: list[DetectedAugment],
        timestamp: float,
        clicks: Iterable[PointerClick],
        window,
    ) -> Optional[str]:
        offered = {
            option.slot_index: option.name.strip()
            for option in options
            if 0 <= option.slot_index < 3 and option.name.strip()
        }
        if phase == GamePhase.AUGMENT_SELECT:
            if len(offered) >= 2:
                if offered != self._pending:
                    self._pending = offered
                    self._offer_seen_at = timestamp
                self._exit_frames = 0
            return None

        if not self._pending:
            return None
        self._exit_frames += 1
        if self._exit_frames < self.exit_confirmations:
            return None

        valid: list[tuple[float, int]] = []
        for click in clicks:
            if not (
                self._offer_seen_at - 0.25
                <= click.timestamp
                <= timestamp + 0.25
            ):
                continue
            slot = self._slot_for_click(click, window)
            if slot is not None and slot in self._pending:
                valid.append((click.timestamp, slot))

        selected = self._pending[max(valid)[1]] if valid else None
        self.reset()
        return selected

    @classmethod
    def _slot_for_click(cls, click: PointerClick, window) -> Optional[int]:
        if window is None or window.width <= 0 or window.height <= 0:
            return None
        if window.hwnd and click.foreground_hwnd != int(window.hwnd):
            return None
        x = (click.x - window.x) / window.width
        y = (click.y - window.y) / window.height
        if not (cls.CARD_Y_RANGE[0] <= y <= cls.CARD_Y_RANGE[1]):
            return None
        slot = min(
            range(3), key=lambda index: abs(x - cls.CARD_CENTERS_X[index])
        )
        if abs(x - cls.CARD_CENTERS_X[slot]) > cls.CARD_HALF_WIDTH:
            return None
        return slot
