"""
Configuration

All pixel coordinates are defined as ratios (0.0 - 1.0) of the game window
dimensions so they scale across resolutions. The capture module converts
these to absolute pixel values at runtime.
"""

from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum


# ── Paths ─────────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
ASSETS_DIR = PROJECT_ROOT / "assets"
TEMPLATE_DIR = ASSETS_DIR / "templates"
COMPONENT_TEMPLATE_DIR = TEMPLATE_DIR / "components"
CHAMPION_TEMPLATE_DIR = TEMPLATE_DIR / "champions"
UI_TEMPLATE_DIR = TEMPLATE_DIR / "ui"


# ── Server ────────────────────────────────────────────────────────────────────

WEBSOCKET_HOST = "localhost"
WEBSOCKET_PORT = 8765


# ── Capture ───────────────────────────────────────────────────────────────────

CAPTURE_FPS = 2  # Frames per second to analyze (higher = more CPU)
GAME_WINDOW_TITLE = "League of Legends"  # Window title to locate


# ── Detection Thresholds ──────────────────────────────────────────────────────

CONFIDENCE_THRESHOLD = 0.80   # Template match confidence minimum
OCR_CONFIDENCE_MIN = 60       # Tesseract confidence minimum (0-100)
COMPONENT_MATCH_THRESHOLD = 0.82
CHAMPION_MATCH_THRESHOLD = 0.78


# ── Regions of Interest (ROI) ─────────────────────────────────────────────────
#
# Defined as (x_ratio, y_ratio, w_ratio, h_ratio) relative to game window.
# Example: (0.5, 0.0, 0.1, 0.05) = starts at 50% across, 0% down, spans
#          10% of width and 5% of height.
#
# These values are calibrated for TFT on a standard 16:9 display.
# You may need to fine-tune them for your specific resolution and UI scale.

@dataclass
class RegionOfInterest:
    """A rectangular region as ratios of the game window dimensions."""
    x: float  # Left edge (0.0 - 1.0)
    y: float  # Top edge  (0.0 - 1.0)
    w: float  # Width     (0.0 - 1.0)
    h: float  # Height    (0.0 - 1.0)

    def to_pixels(self, window_w: int, window_h: int) -> tuple[int, int, int, int]:
        """Convert ratios to absolute pixel coordinates (x, y, w, h)."""
        return (
            int(self.x * window_w),
            int(self.y * window_h),
            int(self.w * window_w),
            int(self.h * window_h),
        )


@dataclass
class GameROIs:
    """All regions of interest in the TFT game UI."""

    # Stage indicator — top center of screen (e.g., "Stage 3-2")
    stage: RegionOfInterest = field(
        default_factory=lambda: RegionOfInterest(0.46, 0.0, 0.08, 0.04)
    )

    # Player HP — left side HUD
    player_hp: RegionOfInterest = field(
        default_factory=lambda: RegionOfInterest(0.32, 0.895, 0.04, 0.025)
    )

    # Gold count — bottom center
    gold: RegionOfInterest = field(
        default_factory=lambda: RegionOfInterest(0.48, 0.88, 0.04, 0.03)
    )

    # Level indicator — bottom left area
    level: RegionOfInterest = field(
        default_factory=lambda: RegionOfInterest(0.31, 0.88, 0.03, 0.025)
    )

    # Item bench — the component storage area (bottom-left of board)
    item_bench: RegionOfInterest = field(
        default_factory=lambda: RegionOfInterest(0.325, 0.775, 0.35, 0.045)
    )

    # Champion bench — the bench row below the board
    champion_bench: RegionOfInterest = field(
        default_factory=lambda: RegionOfInterest(0.30, 0.77, 0.40, 0.07)
    )

    # Board area — the hex grid where champions are placed
    board: RegionOfInterest = field(
        default_factory=lambda: RegionOfInterest(0.25, 0.35, 0.50, 0.40)
    )

    # Augment selection screen — center overlay when choosing augments
    augment_panel: RegionOfInterest = field(
        default_factory=lambda: RegionOfInterest(0.18, 0.20, 0.64, 0.55)
    )

    # Shop area — the champion shop at the bottom
    shop: RegionOfInterest = field(
        default_factory=lambda: RegionOfInterest(0.295, 0.92, 0.41, 0.075)
    )


# ── Board Hex Grid Mapping ────────────────────────────────────────────────────
#
# TFT board is 7 columns × 4 rows. Each hex center is mapped as a ratio
# of the board ROI dimensions. Odd rows are offset by half a hex width.

@dataclass
class HexPosition:
    """A single hex position on the board grid."""
    row: int
    col: int
    # Center position as ratio within the board ROI
    cx: float
    cy: float
    # Sampling radius (ratio) for champion portrait detection
    radius: float = 0.04


def generate_hex_grid() -> list[HexPosition]:
    """Generate the 28 hex positions (7 × 4) for the TFT board."""
    hexes = []
    rows = 4
    cols = 7

    for row in range(rows):
        for col in range(cols):
            cx = (col + 0.5) / cols
            # Odd rows get a half-column offset
            if row % 2 == 1:
                cx += 0.5 / cols
            cy = (row + 0.5) / rows
            hexes.append(HexPosition(row=row, col=col, cx=cx, cy=cy))

    return hexes


BOARD_HEX_GRID = generate_hex_grid()


# ── Component Item Data ───────────────────────────────────────────────────────
# Canonical lists live in game_data.py — import from there so there is a
# single source of truth. These re-exports keep any existing code that
# imports directly from config working without changes.

from game_data import COMPONENT_IDS, COMPONENT_NAMES  # noqa: F401  (re-export)


# ── Logging ───────────────────────────────────────────────────────────────────

class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"

LOG_LEVEL = LogLevel.INFO
LOG_DETECTION_FRAMES = False  # Save annotated frames for debugging
LOG_FRAME_DIR = PROJECT_ROOT / "debug_frames"
