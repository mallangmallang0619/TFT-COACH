"""
Configuration

All pixel coordinates are defined as ratios (0.0 - 1.0) of the game window
dimensions so they scale across resolutions. The capture module converts
these to absolute pixel values at runtime.

Multi-resolution support is adaptive: ROI ratios are applied against the
inscribed 16:9 viewport inside the live frame, so the same ratios produce
correctly-placed regions on 1080p, 1440p, 4K, 21:9 ultrawide, and 16:10
windows alike. GAME_RESOLUTION is only used as a fallback when no frame
dimensions are passed in (e.g. offline tooling).
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


# ── Resolution ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Resolution:
    width: int
    height: int

    def __iter__(self):
        return iter((self.width, self.height))

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height


# Common monitor resolutions. Use COMMON_RESOLUTIONS["1440p"] etc., or set
# GAME_RESOLUTION directly to any Resolution(w, h) — live capture overrides
# this at runtime anyway.
COMMON_RESOLUTIONS: dict[str, Resolution] = {
    "720p":            Resolution(1280, 720),    # 16:9
    "1080p":           Resolution(1920, 1080),   # 16:9
    "1440p":           Resolution(2560, 1440),   # 16:9
    "4k":              Resolution(3840, 2160),   # 16:9
    "ultrawide_1080p": Resolution(2560, 1080),   # 21:9
    "ultrawide_1440p": Resolution(3440, 1440),   # 21:9
    "16:10_1200p":     Resolution(1920, 1200),   # 16:10
    "16:10_1600p":     Resolution(2560, 1600),   # 16:10
}

# Fallback resolution used only when no live frame dimensions are passed.
GAME_RESOLUTION = COMMON_RESOLUTIONS["1440p"]

# TFT renders its HUD/board inside a 16:9 region regardless of the host
# window's aspect ratio. When ADAPTIVE_RESOLUTION is True, ROI ratios are
# resolved against this inscribed viewport so 21:9 and 16:10 windows still
# map correctly. Set to False to apply ratios to the raw window dims.
TARGET_ASPECT_RATIO = 16 / 9
ADAPTIVE_RESOLUTION = True

# Multiplier for TFT's in-game UI scale setting. Applied to ROI width/height
# so HUD-anchored regions track UI-scale changes without recalibrating every
# ratio. Keep at 1.0 unless your in-game UI scale isn't default.
UI_SCALE = 1.0


@dataclass(frozen=True)
class GameViewport:
    """The inscribed target-aspect region inside a live window.

    On a 16:9 window this equals the full window. On 21:9 ultrawide, the
    viewport is pillarboxed (offset_x > 0). On 16:10, it is letterboxed
    (offset_y > 0).
    """
    offset_x: int
    offset_y: int
    width: int
    height: int


def compute_viewport(
    window_w: int,
    window_h: int,
    target_aspect: float = TARGET_ASPECT_RATIO,
) -> GameViewport:
    """Inscribe a target-aspect rectangle inside the given window."""
    window_aspect = window_w / window_h
    if window_aspect > target_aspect:
        # Wider than target → pillarbox (constrain by height)
        inner_h = window_h
        inner_w = int(round(inner_h * target_aspect))
    else:
        # Taller than target → letterbox (constrain by width)
        inner_w = window_w
        inner_h = int(round(inner_w / target_aspect))
    return GameViewport(
        offset_x=(window_w - inner_w) // 2,
        offset_y=(window_h - inner_h) // 2,
        width=inner_w,
        height=inner_h,
    )


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

    def to_pixels(
        self,
        window_w: int | None = None,
        window_h: int | None = None,
        *,
        adaptive: bool | None = None,
        ui_scale: float | None = None,
    ) -> tuple[int, int, int, int]:
        """Convert ratios to absolute pixel coordinates (x, y, w, h).

        Defaults to GAME_RESOLUTION when no dimensions are provided. When
        adaptive (default: ADAPTIVE_RESOLUTION), ratios resolve against the
        inscribed 16:9 viewport, so 21:9 and 16:10 windows still produce
        correctly-anchored regions.
        """
        w = window_w if window_w is not None else GAME_RESOLUTION.width
        h = window_h if window_h is not None else GAME_RESOLUTION.height
        use_adaptive = ADAPTIVE_RESOLUTION if adaptive is None else adaptive
        scale = UI_SCALE if ui_scale is None else ui_scale

        if use_adaptive:
            vp = compute_viewport(w, h)
            base_x, base_y = vp.offset_x, vp.offset_y
            region_w, region_h = vp.width, vp.height
        else:
            base_x, base_y = 0, 0
            region_w, region_h = w, h

        px_w = int(self.w * region_w * scale)
        px_h = int(self.h * region_h * scale)
        # Anchor scaled size around the original ratio center so UI_SCALE
        # adjustments expand/contract about the region's midpoint.
        cx = base_x + int((self.x + self.w / 2) * region_w)
        cy = base_y + int((self.y + self.h / 2) * region_h)
        return (cx - px_w // 2, cy - px_h // 2, px_w, px_h)


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
