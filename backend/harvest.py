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
from collections import deque
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
# static. On the recalibrated ROI, empty slots usually have thumbnail std
# 14-19 while occupied slots start around 20, but relative frame-to-frame
# evidence remains the primary guard because arena lighting varies.
_THUMB_SIZE = (24, 32)          # (w, h) of the comparison thumbnail
_CHANGE_FLOOR = 6.0             # minimum mean-abs-diff to count as a change
_CHANGE_OUTLIER_FACTOR = 1.6    # ...and it must stand out vs the other slots
_LANDING_HISTORY_FRAMES = 6
_EMPTY_STD_MAX = 21.0
_OCCUPIED_STD_MIN = 19.5

# Continuous tracking of confirmed slots: save every Nth frame while the
# slot's thumbnail stays within _TRACK_CHANGE_LIMIT of the last saved one
# (idle animation drifts a little; moves/sells/combines jump far past it).
_TRACK_SAVE_INTERVAL = 1        # every processed frame while stable
_TRACK_MAX_SAVES = 20           # crops per purchase, landing crop included
_TRACK_CHANGE_LIMIT = 18.0      # tolerate idle poses and brief spell glows
_CROP_MIN_STD = 18.0
_CROP_MIN_LAPLACIAN = 500.0
_CROP_MIN_FULL_LAPLACIAN = 80.0


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
    occupancy_misses: int = 0


@dataclass
class _BenchFrame:
    crops: list[np.ndarray]
    thumbs: list[Optional[np.ndarray]]


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
        # Keep a short bench history so delayed shop confirmation can recover
        # the exact frame where a unit landed instead of requiring perfect
        # timing between OCR and animation.
        self._pending_landings: list[_PendingLanding] = []
        self._tracked: dict[int, _TrackedSlot] = {}
        self._history: deque[_BenchFrame] = deque(maxlen=_LANDING_HISTORY_FRAMES)
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
        current_frame = _BenchFrame(
            crops=[crop.copy() for crop in crops],
            thumbs=thumbs,
        )
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
            count = self._harvest_confirmed_fallback(
                purchases, thumbs, current_frame, just_confirmed
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
                    pending_purchases, current_frame
                )
        elif not purchases:
            self._pending_landings.clear()

        saved += self._harvest_tracked(crops, thumbs, just_confirmed)

        self._history.append(current_frame)
        return saved

    def reset(self) -> None:
        self._pending_landings.clear()
        self._tracked.clear()
        self._history.clear()

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
                empty_distance = float(np.mean(cv2.absdiff(
                    thumbs[slot], tracked.empty_reference
                )))
                if empty_distance < 4.0 or tracked.occupancy_misses >= 1:
                    logger.debug(
                        f"Slot {slot} became empty — stop tracking {tracked.label}"
                    )
                    del self._tracked[slot]
                else:
                    tracked.occupancy_misses += 1
                continue
            tracked.occupancy_misses = 0
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
        current_frame: _BenchFrame,
    ) -> None:
        self._pending_landings.clear()
        landings = self._find_recent_landings(names, current_frame)
        if len(landings) != len(names):
            logger.info(
                f"Holding purchase labels but no clean landing: {len(names)} pending vs "
                f"{len(landings)} recoverable bench slots"
            )
            return
        self._pending_landings = landings
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
        thumbs: list[Optional[np.ndarray]],
        current_frame: _BenchFrame,
        just_confirmed: set[int],
    ) -> int:
        landings = self._find_recent_landings(purchases, current_frame)
        if len(landings) != len(purchases):
            logger.info(
                f"Skipping harvest: {len(purchases)} purchases vs "
                f"{len(landings)} recoverable bench slots"
            )
            return 0

        saved = 0
        for landing in landings:
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
        return saved

    def _find_recent_landings(
        self,
        names: list[str],
        current_frame: _BenchFrame,
    ) -> list[_PendingLanding]:
        frames = [*self._history, current_frame]
        for index in range(len(frames) - 1, 0, -1):
            before = frames[index - 1]
            after = frames[index]
            slots = self._newly_occupied_slots(after.thumbs, before.thumbs)
            if not slots:
                continue
            if len(slots) != len(names):
                return []
            landings: list[_PendingLanding] = []
            for name, slot in zip(names, slots):
                occupied = after.thumbs[slot]
                empty = before.thumbs[slot]
                if occupied is None or empty is None:
                    landings = []
                    break
                landings.append(_PendingLanding(
                    label=name,
                    slot=slot,
                    crop=after.crops[slot].copy(),
                    occupied_thumb=occupied.copy(),
                    empty_thumb=empty.copy(),
                ))
            if landings:
                return landings
        return []

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
        baseline_looks_empty = baseline_std <= _EMPTY_STD_MAX
        contrast_gain = current_std >= max(
            _OCCUPIED_STD_MIN,
            baseline_std + 1.0,
        )
        edge_gain = (
            current_std >= baseline_std + 0.3
            and current_laplacian >= max(
                _CROP_MIN_LAPLACIAN,
                baseline_laplacian * 1.18,
            )
        )
        return baseline_looks_empty and (contrast_gain or edge_gain)

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
