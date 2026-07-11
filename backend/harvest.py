"""
Bench-Crop Harvester — auto-labeled training data for the unit classifier.

Live board/bench units are 3D models that template matching can't
identify; the plan is a small per-hex CNN classifier, which needs labeled
crops of those models. This module collects them for free while the
player plays:

  1. The purchase tracker (roster.py) tells us WHICH champion was just
     bought — the shop card name is reliable OCR.
  2. A bought unit always lands on the leftmost empty bench slot, so the
     bench slot that flips empty → occupied between the frames around a
     purchase is a picture OF that champion.
  3. Save the crop to _training/<champion>/<timestamp>.png.

A few games of normal play yields hundreds of labeled samples per set —
no manual labeling. The directory is gitignored; it feeds model training
offline.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from config import GameROIs

logger = logging.getLogger(__name__)

TRAINING_DIR = Path(__file__).parent / "_training"
BENCH_SLOTS = 9

# Bench slots are compared frame-to-frame as small grayscale thumbnails:
# a unit arriving changes its slot drastically while empty planks stay
# static. Texture alone can't do this — measured on a real frame, empty
# plank slots have std 22-27 vs occupied 29-34, far too close to gate on.
_THUMB_SIZE = (24, 32)          # (w, h) of the comparison thumbnail
_CHANGE_FLOOR = 9.0             # minimum mean-abs-diff to count as a change
_CHANGE_OUTLIER_FACTOR = 2.5    # ...and it must stand out vs the other slots


class BenchHarvester:
    """Feed each captured frame + that frame's purchases."""

    def __init__(self, out_dir: Path = TRAINING_DIR):
        self.out_dir = out_dir
        self.rois = GameROIs()
        # Thumbnails of each slot from the last two frames — purchases are
        # confirmed one frame after the unit lands, so "just changed" must
        # look two frames back.
        self._thumbs_prev: Optional[list[np.ndarray]] = None
        self._thumbs_prev2: Optional[list[np.ndarray]] = None
        self.saved_count = 0

    def process(self, frame: np.ndarray, purchases: list[str]) -> int:
        """Returns how many labeled crops were saved this frame."""
        crops = self._bench_slot_crops(frame)
        thumbs = [self._thumb(c) for c in crops]

        saved = 0
        if purchases and self._thumbs_prev is not None:
            baseline = self._thumbs_prev2 or self._thumbs_prev
            diffs = [
                float(np.mean(cv2.absdiff(thumbs[i], baseline[i])))
                if thumbs[i] is not None and baseline[i] is not None else 0.0
                for i in range(BENCH_SLOTS)
            ]
            # A slot where a unit just landed is an outlier against the
            # ambient change of the other slots (lighting, idle animation).
            typical = float(np.median(diffs)) if diffs else 0.0
            threshold = max(_CHANGE_FLOOR, typical * _CHANGE_OUTLIER_FACTOR)
            newly = [i for i in range(BENCH_SLOTS) if diffs[i] >= threshold]
            logger.debug(
                f"bench diffs={[f'{d:.0f}' for d in diffs]} "
                f"threshold={threshold:.0f} newly={newly}"
            )

            # Label purity beats coverage: only save when the number of
            # changed slots matches the confirmed purchases exactly.
            # A mismatch (unit moved board↔bench in the window, a combine
            # consumed the copies) risks pairing the wrong crop with the
            # name — skip those frames; more games bring more clean ones.
            if len(newly) == len(purchases):
                for name, slot in zip(purchases, newly):
                    if self._save(crops[slot], name, slot):
                        saved += 1
            else:
                logger.debug(
                    f"Skipping harvest: {len(purchases)} purchases vs "
                    f"{len(newly)} changed bench slots (ambiguous pairing)"
                )

        self._thumbs_prev2 = self._thumbs_prev
        self._thumbs_prev = thumbs
        return saved

    def reset(self) -> None:
        self._thumbs_prev = None
        self._thumbs_prev2 = None

    # ── Internals ─────────────────────────────────────────────────────────────

    def _bench_slot_crops(self, frame: np.ndarray) -> list[np.ndarray]:
        h, w = frame.shape[:2]
        bx, by, bw, bh = self.rois.champion_bench.to_pixels(w, h)
        slot_w = max(1, bw // BENCH_SLOTS)
        return [
            frame[by:by + bh, bx + i * slot_w: bx + (i + 1) * slot_w]
            for i in range(BENCH_SLOTS)
        ]

    @staticmethod
    def _thumb(crop: np.ndarray) -> Optional[np.ndarray]:
        if crop.size == 0:
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, _THUMB_SIZE, interpolation=cv2.INTER_AREA)

    def _save(self, crop: np.ndarray, name: str, slot: int) -> bool:
        if crop.size == 0:
            return False
        safe = name.replace("'", "").replace(" ", "_").replace(".", "")
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out = self.out_dir / safe / f"{ts}_slot{slot}.png"
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out), crop)
        except OSError as e:
            logger.warning(f"Could not save training crop: {e}")
            return False
        self.saved_count += 1
        logger.info(f"Training crop saved: {name} (bench slot {slot}) → {out.name}")
        return True
