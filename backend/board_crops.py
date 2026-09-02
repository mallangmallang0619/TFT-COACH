"""Health-bar-anchored crops for live Set 18 board units.

Fixed hex rectangles are useful for locating the board, but a tall UE5 model
and its health bar extend far above the hex center.  A bar can also cross two
neighboring rectangles, causing one champion to be harvested several times as
partial bodies.  This module finds the player's green health bars first, then
frames one full model crop and maps it back to the nearest hex.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from config import BOARD_HEX_GRID, GameROIs

BOARD_CROP_MODE = "health_bar_v1"


@dataclass
class BoardUnitCrop:
    row: int
    col: int
    index: int
    crop: np.ndarray


def _health_bar_components(
    frame: np.ndarray,
    rois: GameROIs,
) -> list[tuple[int, int, int, int]]:
    """Return full-frame x/y/w/h boxes for plausible player board bars."""
    height, width = frame.shape[:2]
    bx, by, bw, bh = rois.board.to_pixels(width, height)
    _bench_x, bench_y, _bench_w, _bench_h = (
        rois.champion_bench_capture.to_pixels(width, height)
    )

    # Row-zero models extend above the nominal board ROI.  Stop above the
    # bench so its nine green bars cannot masquerade as bottom-row units.
    x1 = max(0, bx - int(round(bw * 0.03)))
    x2 = min(width, bx + bw)
    y1 = max(0, by - int(round(bh * 0.45)))
    y2 = min(height, bench_y - max(2, int(round(height * 0.008))))
    search = frame[y1:y2, x1:x2]
    if search.size == 0:
        return []

    hsv = cv2.cvtColor(search, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(
        hsv,
        np.array([45, 170, 50], dtype=np.uint8),
        np.array([75, 255, 255], dtype=np.uint8),
    )
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(3, width // 300), 1)
    )
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, kernel)
    _count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(green)

    min_width = max(24, int(round(width * 0.022)))
    # Champion bars are ~3.4% of viewport width.  The Little Legend's named
    # player plate is visibly wider (~5.4%) and must never become a unit crop.
    max_width = max(min_width + 1, int(round(width * 0.045)))
    min_height = max(2, int(round(height * 0.002)))
    max_height = max(min_height + 1, int(round(height * 0.014)))
    bars: list[tuple[int, int, int, int]] = []
    for x, y, bar_width, bar_height, area in stats[1:]:
        if not (
            min_width <= bar_width <= max_width
            and min_height <= bar_height <= max_height
            and bar_width / max(1, bar_height) >= 4.0
            and area >= bar_width * bar_height * 0.30
        ):
            continue
        bars.append((x1 + int(x), y1 + int(y), int(bar_width), int(bar_height)))
    return bars


def extract_board_unit_crops(
    frame: np.ndarray,
    rois: GameROIs | None = None,
) -> list[BoardUnitCrop]:
    """Return one centered full-body crop per occupied player-board hex."""
    rois = rois or GameROIs()
    height, width = frame.shape[:2]
    bx, by, bw, bh = rois.board.to_pixels(width, height)
    _bench_x, bench_anchor_y, _bench_w, _bench_h = (
        rois.champion_bench.to_pixels(width, height)
    )
    hex_centers = [
        (
            bx + position.cx * bw,
            by + position.cy * bh,
        )
        for position in BOARD_HEX_GRID
    ]
    pitch_x = max(1.0, bw * 0.136)
    pitch_y = max(1.0, bh * 0.24)

    # If noise produces two bands for one health bar, keep only the band whose
    # estimated feet land closest to that hex center.
    closest_by_hex: dict[int, tuple[float, tuple[int, int, int, int]]] = {}
    for bar in _health_bar_components(frame, rois):
        x, y, bar_width, _bar_height = bar
        estimated_x = x + bar_width / 2
        estimated_y = y + bar_width * 1.55
        distances = [
            ((estimated_x - hx) / pitch_x) ** 2
            + ((estimated_y - hy) / pitch_y) ** 2
            for hx, hy in hex_centers
        ]
        index = int(np.argmin(distances))
        distance = float(distances[index])
        # UI bars can share the right color.  A real unit bar still projects
        # near one of the 28 player hexes after the foot offset.
        if distance > 0.80:
            continue
        previous = closest_by_hex.get(index)
        if previous is None or distance < previous[0]:
            closest_by_hex[index] = (distance, bar)

    samples: list[BoardUnitCrop] = []
    for index, (_distance, (x, y, bar_width, _bar_height)) in sorted(
        closest_by_hex.items()
    ):
        base = max(float(bar_width), width * 0.03)
        crop_width = int(round(base * 1.90))
        above = int(round(base * 0.42))
        below = int(round(base * 2.25))
        center_x = x + bar_width / 2
        crop_x1 = max(0, int(round(center_x - crop_width / 2)))
        crop_x2 = min(width, crop_x1 + crop_width)
        # Keep the intended width when clamping against a screen edge.
        crop_x1 = max(0, crop_x2 - crop_width)
        crop_y1 = max(0, y - above)
        # The bottom board row sits close to the bench.  Stop before bench
        # health bars/models enter the fielded champion's crop.
        crop_y2 = min(height, bench_anchor_y, y + below)
        crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
        if crop.size == 0:
            continue
        position = BOARD_HEX_GRID[index]
        samples.append(
            BoardUnitCrop(
                row=position.row,
                col=position.col,
                index=index,
                crop=crop,
            )
        )
    return samples
