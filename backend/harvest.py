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
  4. While that slot stays visually stable (the unit is still standing
     there), keep saving crops of it every few frames — idle-animation
     poses multiply one purchase into a dozen labeled samples. Any abrupt
     slot change (moved, sold, combined, item flash) stops the tracking
     immediately, so labels stay pure.

A few games of normal play yields hundreds of labeled samples per set —
no manual labeling. The directory is gitignored; it feeds model training
offline.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
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

# Continuous tracking of confirmed slots: save every Nth frame while the
# slot's thumbnail stays within _TRACK_CHANGE_LIMIT of the last saved one
# (idle animation drifts a little; moves/sells/combines jump far past it).
_TRACK_SAVE_INTERVAL = 1        # every processed frame while stable
_TRACK_MAX_SAVES = 20           # crops per purchase, landing crop included
_TRACK_CHANGE_LIMIT = 18.0      # tolerate idle poses and brief spell glows
_CROP_MIN_STD = 20.0
_CROP_MIN_LAPLACIAN = 700.0
_CROP_MIN_FULL_LAPLACIAN = 100.0


@dataclass
class _PendingLanding:
    label: str
    slot: int
    crop: np.ndarray
    occupied_thumb: np.ndarray
    empty_thumb: np.ndarray


@dataclass
class _TrackedSlot:
    label: str
    reference: np.ndarray
    empty_reference: np.ndarray
    frames_since: int = 0
    saves: int = 0
    change_frames: int = 0


def training_stats(out_dir: Path = TRAINING_DIR) -> tuple[int, int, int]:
    """Return ``(total crops, champion folders, classes ready at 20+)``."""
    if not out_dir.exists():
        return 0, 0, 0
    counts = [
        len(list(folder.glob("*.png")))
        for folder in out_dir.iterdir()
        if folder.is_dir()
    ]
    return sum(counts), len(counts), sum(count >= 20 for count in counts)


class BenchHarvester:
    """Feed each captured frame + that frame's purchases."""

    def __init__(
        self,
        out_dir: Path = TRAINING_DIR,
        track_interval: int = _TRACK_SAVE_INTERVAL,
        track_max_saves: int = _TRACK_MAX_SAVES,
        track_change_limit: float = _TRACK_CHANGE_LIMIT,
    ):
        self.out_dir = out_dir
        self.rois = GameROIs()
        self.track_interval = track_interval
        self.track_max_saves = track_max_saves
        self.track_change_limit = track_change_limit
        # Thumbnails of each slot from the last two frames — purchases are
        # confirmed one frame after the unit lands, so "just changed" must
        # look two frames back.
        self._thumbs_prev: Optional[list[np.ndarray]] = None
        self._thumbs_prev2: Optional[list[np.ndarray]] = None
        self._pending_landings: list[_PendingLanding] = []
        self._tracked: dict[int, _TrackedSlot] = {}
        self.saved_count = 0

    def process(
        self,
        frame: np.ndarray,
        purchases: list[str],
        pending_purchases: Optional[list[str]] = None,
    ) -> int:
        """Returns how many labeled crops were saved this frame."""
        crops = self._bench_slot_crops(frame)
        thumbs = [self._thumb(c) for c in crops]
        pending_purchases = list(pending_purchases or [])

        saved = 0
        just_confirmed: set[int] = set()
        confirmed_from_cache = False
        if purchases and self._pending_landings:
            confirmed_from_cache, count = self._confirm_pending(
                purchases, crops, thumbs, just_confirmed
            )
            saved += count

        if purchases and not confirmed_from_cache:
            baseline = self._thumbs_prev2 or self._thumbs_prev
            count = self._harvest_confirmed_fallback(
                purchases, crops, thumbs, baseline, just_confirmed
            )
            saved += count

        # The roster exposes a card vanish one frame before confirming it as
        # a purchase. Preserve that exact landing frame in memory, then write
        # it only after confirmation. This avoids missing fast buys, combines,
        # or units moved immediately after they reach the bench.
        if pending_purchases:
            labels_match = [p.label for p in self._pending_landings] == pending_purchases
            if not labels_match:
                self._stage_pending(
                    pending_purchases, crops, thumbs, self._thumbs_prev
                )
        elif not purchases:
            self._pending_landings.clear()

        saved += self._harvest_tracked(crops, thumbs, just_confirmed)

        self._thumbs_prev2 = self._thumbs_prev
        self._thumbs_prev = thumbs
        return saved

    def reset(self) -> None:
        self._thumbs_prev = None
        self._thumbs_prev2 = None
        self._pending_landings.clear()
        self._tracked.clear()

    # ── Internals ─────────────────────────────────────────────────────────────

    def _harvest_tracked(
        self,
        crops: list[np.ndarray],
        thumbs: list[Optional[np.ndarray]],
        just_confirmed: set[int],
    ) -> int:
        """
        Save extra crops of slots whose occupant was confirmed by a
        purchase, for as long as the slot looks like the same unit. The
        reference thumbnail advances on each save so slow idle-animation
        drift is tolerated, while any abrupt change (move, sell, combine)
        exceeds the tracking limit and stops the tracking.
        """
        saved = 0
        for slot in list(self._tracked):
            if slot in just_confirmed:
                continue    # landing crop already saved this frame
            tracked = self._tracked[slot]
            if thumbs[slot] is None:
                del self._tracked[slot]
                continue
            if not self._became_occupied(thumbs[slot], tracked.empty_reference):
                logger.debug(f"Slot {slot} became empty — stop tracking {tracked.label}")
                del self._tracked[slot]
                continue
            drift = float(np.mean(cv2.absdiff(thumbs[slot], tracked.reference)))
            if drift >= self.track_change_limit:
                # Empty/low-detail means the unit definitely left. A single
                # viable high-drift frame may just be an idle animation or
                # spell glow, so require it to repeat before abandoning the
                # label without ever saving the uncertain frame.
                if tracked.change_frames >= 1:
                    logger.debug(
                        f"Slot {slot} changed (drift {drift:.0f}) — "
                        f"stop tracking {tracked.label}"
                    )
                    del self._tracked[slot]
                else:
                    tracked.change_frames += 1
                continue
            tracked.change_frames = 0
            tracked.frames_since += 1
            if tracked.frames_since >= self.track_interval:
                if self._save(crops[slot], tracked.label, slot):
                    saved += 1
                    tracked.saves += 1
                    tracked.frames_since = 0
                    tracked.reference = thumbs[slot]
                    if tracked.saves >= self.track_max_saves:
                        del self._tracked[slot]
                        continue
        return saved

    def _stage_pending(
        self,
        names: list[str],
        crops: list[np.ndarray],
        thumbs: list[Optional[np.ndarray]],
        baseline: Optional[list[np.ndarray]],
    ) -> None:
        self._pending_landings.clear()
        slots = self._newly_occupied_slots(thumbs, baseline)
        if len(slots) != len(names) or baseline is None:
            logger.info(
                f"Holding purchase labels but no clean landing: {len(names)} pending vs "
                f"{len(slots)} newly occupied bench slots"
            )
            return
        for name, slot in zip(names, slots):
            if thumbs[slot] is None or baseline[slot] is None:
                self._pending_landings.clear()
                return
            self._pending_landings.append(_PendingLanding(
                label=name,
                slot=slot,
                crop=crops[slot].copy(),
                occupied_thumb=thumbs[slot].copy(),
                empty_thumb=baseline[slot].copy(),
            ))
        logger.debug(
            f"Retained pending bench landings: "
            f"{[(p.label, p.slot) for p in self._pending_landings]}"
        )

    def _confirm_pending(
        self,
        purchases: list[str],
        crops: list[np.ndarray],
        thumbs: list[Optional[np.ndarray]],
        just_confirmed: set[int],
    ) -> tuple[bool, int]:
        pending = self._pending_landings
        self._pending_landings = []
        if [p.label for p in pending] != purchases:
            logger.info("Pending bench landing did not match confirmed purchases")
            return False, 0

        saved = 0
        for landing in pending:
            did_save = self._save(landing.crop, landing.label, landing.slot)
            saved += int(did_save)
            current = thumbs[landing.slot]
            if self._became_occupied(current, landing.empty_thumb):
                self._tracked[landing.slot] = _TrackedSlot(
                    label=landing.label,
                    reference=current.copy(),
                    empty_reference=landing.empty_thumb,
                    saves=int(did_save),
                )
                just_confirmed.add(landing.slot)
        return True, saved

    def _harvest_confirmed_fallback(
        self,
        purchases: list[str],
        crops: list[np.ndarray],
        thumbs: list[Optional[np.ndarray]],
        baseline: Optional[list[np.ndarray]],
        just_confirmed: set[int],
    ) -> int:
        slots = self._newly_occupied_slots(thumbs, baseline)
        if len(slots) != len(purchases) or baseline is None:
            logger.info(
                f"Skipping harvest: {len(purchases)} purchases vs "
                f"{len(slots)} newly occupied bench slots"
            )
            return 0

        saved = 0
        for name, slot in zip(purchases, slots):
            if thumbs[slot] is None or baseline[slot] is None:
                continue
            did_save = self._save(crops[slot], name, slot)
            saved += int(did_save)
            self._tracked[slot] = _TrackedSlot(
                label=name,
                reference=thumbs[slot].copy(),
                empty_reference=baseline[slot].copy(),
                saves=int(did_save),
            )
            just_confirmed.add(slot)
        return saved

    def _newly_occupied_slots(
        self,
        thumbs: list[Optional[np.ndarray]],
        baseline: Optional[list[np.ndarray]],
    ) -> list[int]:
        if baseline is None:
            return []
        diffs = [
            float(np.mean(cv2.absdiff(thumbs[i], baseline[i])))
            if thumbs[i] is not None and baseline[i] is not None else 0.0
            for i in range(BENCH_SLOTS)
        ]
        typical = float(np.median(diffs)) if diffs else 0.0
        threshold = max(_CHANGE_FLOOR, typical * _CHANGE_OUTLIER_FACTOR)
        changed = [i for i in range(BENCH_SLOTS) if diffs[i] >= threshold]
        occupied = [
            i for i in changed
            if self._became_occupied(thumbs[i], baseline[i])
        ]
        logger.debug(
            f"bench diffs={[f'{d:.0f}' for d in diffs]} "
            f"threshold={threshold:.0f} changed={changed} occupied={occupied}"
        )
        return occupied

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

    @staticmethod
    def _crop_metrics(thumb: np.ndarray) -> tuple[float, float]:
        return (
            float(np.std(thumb)),
            float(cv2.Laplacian(thumb, cv2.CV_64F).var()),
        )

    @classmethod
    def _is_viable_crop(cls, thumb: Optional[np.ndarray]) -> bool:
        if thumb is None:
            return False
        std, laplacian = cls._crop_metrics(thumb)
        return std >= _CROP_MIN_STD or laplacian >= _CROP_MIN_LAPLACIAN

    @classmethod
    def _became_occupied(
        cls,
        current: Optional[np.ndarray],
        baseline: Optional[np.ndarray],
    ) -> bool:
        if not cls._is_viable_crop(current) or baseline is None:
            return False
        current_std, current_laplacian = cls._crop_metrics(current)
        baseline_std, baseline_laplacian = cls._crop_metrics(baseline)
        return (
            current_std >= baseline_std + 2.0
            or current_laplacian >= baseline_laplacian * 1.15
        )

    def _save(self, crop: np.ndarray, name: str, slot: int) -> bool:
        if crop.size == 0:
            return False
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        full_laplacian = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if (
            not self._is_viable_crop(self._thumb(crop))
            or full_laplacian < _CROP_MIN_FULL_LAPLACIAN
        ):
            logger.info(f"Skipping low-detail training crop: {name} (bench slot {slot})")
            return False
        safe = name.replace("'", "").replace(" ", "_").replace(".", "")
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out = self.out_dir / safe / f"{ts}_slot{slot}.png"
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            # imwrite reports failure by returning False, not raising.
            if not cv2.imwrite(str(out), crop):
                logger.warning(f"Could not save training crop: imwrite failed for {out}")
                return False
        except OSError as e:
            logger.warning(f"Could not save training crop: {e}")
            return False
        self.saved_count += 1
        logger.info(f"Training crop saved: {name} (bench slot {slot}) → {out.name}")
        return True
