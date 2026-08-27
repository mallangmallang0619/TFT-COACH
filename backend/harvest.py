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
  3. Save the crop to _training/set18/<champion>/<timestamp>.png.
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
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from config import GameROIs
from game_data import ACTIVE_SET_NUMBER, canonical_training_label

logger = logging.getLogger(__name__)

TRAINING_DIR = Path(__file__).parent / "_training" / f"set{ACTIVE_SET_NUMBER}"
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
_TRACK_MAX_SAVES = 50           # crops per purchase, landing crop included
_TRACK_CHANGE_LIMIT = 18.0      # tolerate idle poses and brief spell glows
READY_CROPS_PER_CLASS = 50
_DUPLICATE_THUMB_MAD = 1.0      # <= this is effectively the same pose/frame
_CROP_MIN_STD = 18.0
_CROP_MIN_LAPLACIAN = 500.0
# Real Set 18 unit crops measured 210-3200; empty portal/platform crops that
# previously slipped through measured 125-140. Keep a margin between them.
_CROP_MIN_FULL_LAPLACIAN = 180.0
# A newly bought unit is briefly rendered as a bright cyan/blue hologram.
# Those frames are sharp enough to pass the edge checks but teach the model
# the purchase effect instead of the champion.  A real selected unit may have
# a thin cyan outline (observed at ~7% of the crop); the materialisation effect
# fills much more of the crop (observed at ~16%), so keep a conservative gap.
_MATERIALIZATION_BLUE_COMPONENT_RATIO = 0.10


@dataclass
class _PendingLanding:
    label: str
    slot: int
    crop: np.ndarray
    empty_crop: np.ndarray
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
    """Return ``(clean crops, champion classes, champions ready at 50+)``."""
    accepted, _rejected = audit_training_crops(out_dir)
    champion_counts = [
        len(files) for name, files in accepted.items() if not name.startswith("_")
    ]
    return (
        sum(len(files) for files in accepted.values()),
        len(champion_counts),
        sum(count >= READY_CROPS_PER_CLASS for count in champion_counts),
    )


def audit_training_crops(
    train_dir: Path = TRAINING_DIR,
) -> tuple[dict[str, list[Path]], dict[str, dict[str, int]]]:
    """Audit raw crops without moving/deleting them; pool Lux form labels."""
    accepted: dict[str, list[Path]] = {}
    rejected: dict[str, dict[str, int]] = {}
    thumbs: dict[str, list[np.ndarray]] = {}
    if not train_dir.exists():
        return accepted, rejected

    for champ_dir in sorted(train_dir.iterdir()):
        if not champ_dir.is_dir():
            continue
        label = canonical_training_label(champ_dir.name)
        accepted.setdefault(label, [])
        rejected.setdefault(label, {})
        thumbs.setdefault(label, [])
        for path in sorted(champ_dir.glob("*.png")):
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            reason = BenchHarvester.training_crop_rejection_reason(
                image,
                background=label.startswith("_"),
            )
            thumb = BenchHarvester._thumb(image) if image is not None else None
            if reason is None and thumb is not None:
                if any(
                    float(np.mean(cv2.absdiff(thumb, prior)))
                    <= _DUPLICATE_THUMB_MAD
                    for prior in thumbs[label]
                ):
                    reason = "duplicate"
            if reason:
                counts = rejected[label]
                counts[reason] = counts.get(reason, 0) + 1
                continue
            accepted[label].append(path)
            thumbs[label].append(thumb)

    accepted = {name: paths for name, paths in accepted.items() if paths}
    rejected = {name: reasons for name, reasons in rejected.items() if reasons}
    return accepted, rejected


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
        self._last_landing_diagnostic = "no bench transitions inspected"
        self._last_transition_diagnostic = "no transition"
        self._saved_thumbs: dict[str, list[np.ndarray]] = {}
        self._loaded_thumb_labels: set[str] = set()
        self.saved_count = 0
        self.rejection_counts: Counter[str] = Counter()
        self.skip_counts: Counter[str] = Counter()
        self.last_event = "Waiting for a readable shop and bench baseline"
        self.last_save_at: Optional[float] = None
        self.last_saved_label: Optional[str] = None
        self._suspended = False

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

        if self._suspended:
            # The first trusted frame after a capture gap is a new baseline,
            # never a training example. Preserve a tracked label only when
            # the slot still resembles the same occupied unit; otherwise
            # discard it instead of risking a stale label.
            kept = 0
            for slot in list(self._tracked):
                tracked = self._tracked[slot]
                current = thumbs[slot]
                if current is None or not self._became_occupied(
                    current, tracked.empty_reference
                ):
                    del self._tracked[slot]
                    continue
                drift = float(np.mean(cv2.absdiff(current, tracked.reference)))
                if drift >= self.track_change_limit:
                    del self._tracked[slot]
                    continue
                tracked.reference = current.copy()
                tracked.frames_since = 0
                tracked.change_frames = 0
                tracked.occupancy_misses = 0
                kept += 1
            self._suspended = False
            self._history.append(current_frame)
            self.last_event = (
                f"Trusted capture resumed; rebased {kept} tracked bench slot(s)"
            )
            logger.info(self.last_event)
            return 0

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
        self._last_landing_diagnostic = "no bench transitions inspected"
        self._last_transition_diagnostic = "no transition"
        self._suspended = False

    def suspend_observation(self, reason: str = "capture is not trusted") -> None:
        """Pause labeling without throwing away confirmed tracked identities.

        Pending purchases and transition history cannot cross an untrusted
        frame, but a confirmed slot label can survive a brief direct-capture
        outage. The next trusted frame is used only to validate/rebase it.
        """
        if not self._suspended:
            self.skip_counts["capture_untrusted"] += 1
            self.last_event = f"Collection paused: {reason}"
            logger.info(self.last_event)
        self._suspended = True
        self._pending_landings.clear()
        self._history.clear()

    def telemetry(self) -> dict:
        """Small JSON-safe snapshot for logs and the live overlay."""
        return {
            "session_crops_saved": self.saved_count,
            "rejected_crops": sum(self.rejection_counts.values()),
            "rejection_reasons": dict(self.rejection_counts),
            "skipped_events": dict(self.skip_counts),
            "tracked_slots": len(self._tracked),
            "last_event": self.last_event,
            "last_save_at": self.last_save_at,
            "last_saved_label": self.last_saved_label,
        }

    def _record_rejection(self, reason: str, name: str, slot: int) -> None:
        self.rejection_counts[reason] += 1
        self.last_event = (
            f"Rejected {name} slot {slot}: {reason.replace('_', ' ')}"
        )

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
                    self._save_empty(crops[slot], slot)
                    logger.debug(
                        f"Slot {slot} became empty — stop tracking {tracked.label}"
                    )
                    del self._tracked[slot]
                else:
                    tracked.occupancy_misses += 1
                continue
            tracked.occupancy_misses = 0
            drift = float(np.mean(cv2.absdiff(thumbs[slot], tracked.reference)))

            # The first confirmation frame can still be the UE5 purchase
            # hologram.  If it failed the quality gate, keep the trusted slot
            # label alive and follow the animation until it settles.  Rebase
            # on large visual changes instead of treating the hologram ->
            # champion transition as the unit leaving.
            if tracked.saves == 0:
                if drift >= self.track_change_limit:
                    tracked.reference = thumbs[slot].copy()
                    tracked.frames_since = 0
                    tracked.change_frames = 0
                    continue
                tracked.frames_since += 1
                if tracked.frames_since >= self.track_interval:
                    if self._save(crops[slot], tracked.label, slot):
                        saved += 1
                        tracked.saves = 1
                        tracked.frames_since = 0
                        tracked.reference = thumbs[slot].copy()
                continue

            if drift >= self.track_change_limit:
                # Empty/low-detail means the unit definitely left. A single
                # viable high-drift frame may just be an idle animation or
                # spell glow, so require it to repeat before abandoning the
                # label without ever saving the uncertain frame.
                if tracked.change_frames >= 2:
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
                        logger.info(
                            f"Harvest complete: {tracked.label} reached "
                            f"{self.track_max_saves} crops (bench slot {slot})"
                        )
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
            self.skip_counts["no_clean_landing"] += 1
            self.last_event = (
                f"No clean bench landing for {', '.join(names)}: "
                f"{self._last_landing_diagnostic}"
            )
            logger.info(
                f"Holding purchase labels but no clean landing: {len(names)} pending vs "
                f"{len(landings)} recoverable bench slots "
                f"({self._last_landing_diagnostic})"
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
            self.skip_counts["pending_mismatch"] += 1
            self.last_event = "Pending bench landing did not match confirmed purchases"
            logger.info("Pending bench landing did not match confirmed purchases")
            return False, 0

        saved = 0
        for landing in pending:
            current = thumbs[landing.slot]
            if not self._became_occupied(current, landing.empty_thumb):
                continue
            # The pre-purchase frame is a trustworthy empty-slot label. Keep
            # it as classifier background; deduplication prevents the same
            # arena plank from flooding the dataset.
            self._save_empty(landing.empty_crop, landing.slot)
            # Confirmation arrives after the initial landing transition. Save
            # this later frame, where the UE5 model has finished materializing,
            # rather than the cached dust/shadow animation.
            did_save = self._save(crops[landing.slot], landing.label, landing.slot)
            saved += int(did_save)
            # Even when the first crop is rejected (most commonly the bright
            # UE5 materialisation effect), the purchase-to-slot pairing is
            # already trusted. Keep tracking and retry on a settled frame.
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
            self.skip_counts["no_clean_landing"] += 1
            self.last_event = (
                f"No clean bench landing for {', '.join(purchases)}: "
                f"{self._last_landing_diagnostic}"
            )
            logger.info(
                f"Skipping harvest: {len(purchases)} purchases vs "
                f"{len(landings)} recoverable bench slots "
                f"({self._last_landing_diagnostic})"
            )
            return 0

        saved = 0
        for landing in landings:
            current = thumbs[landing.slot]
            if not self._became_occupied(current, landing.empty_thumb):
                continue
            self._save_empty(landing.empty_crop, landing.slot)
            did_save = self._save(
                current_frame.crops[landing.slot], landing.label, landing.slot
            )
            saved += int(did_save)
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
        mismatches: list[str] = []
        for index in range(len(frames) - 1, 0, -1):
            before = frames[index - 1]
            after = frames[index]
            slots = self._newly_occupied_slots(after.thumbs, before.thumbs)
            if not slots:
                mismatches.append(
                    f"-{len(frames) - index}: "
                    f"{self._last_transition_diagnostic}"
                )
                continue
            if len(slots) != len(names):
                # Do not jump past an ambiguous newer transition and attach
                # the purchase label to an unrelated older unit movement.
                self._last_landing_diagnostic = (
                    f"history offset {len(frames) - index}: "
                    f"slots={slots}, wanted={len(names)}"
                )
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
                    empty_crop=before.crops[slot].copy(),
                    occupied_thumb=occupied.copy(),
                    empty_thumb=empty.copy(),
                ))
            if landings:
                self._last_landing_diagnostic = (
                    f"matched slots {slots} at history offset "
                    f"{len(frames) - index}"
                )
                return landings
        self._last_landing_diagnostic = (
            f"searched {max(0, len(frames) - 1)} transitions; "
            + ", ".join(mismatches[:2])
        )
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
            if self._became_occupied(
                thumbs[i],
                baseline[i],
                # The slot is already a strong change outlier relative to
                # the other eight slots. Accept same-contrast champions too:
                # several dark/small models change the pixels substantially
                # without increasing thumbnail stddev or edge energy.
                change_evidence=diffs[i] >= threshold,
            )
        ]
        before_stds = [
            round(self._crop_metrics(thumb)[0], 1) if thumb is not None else None
            for thumb in baseline
        ]
        self._last_transition_diagnostic = (
            f"diffs={[round(d, 1) for d in diffs]}, "
            f"threshold={threshold:.1f}, changed={changed}, "
            f"accepted={occupied}, before_std={before_stds}"
        )
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
        *,
        change_evidence: bool = False,
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
        if baseline_looks_empty and (contrast_gain or edge_gain or change_evidence):
            return True

        # `change_evidence` is supplied only after this slot beats the
        # frame-relative outlier threshold. Empty platforms are not
        # consistently low-contrast across arenas (real empty slots range
        # well above _EMPTY_STD_MAX), so a high-detail baseline cannot be an
        # automatic veto. Reject only a *large loss* of both contrast and
        # edges, which is strong evidence that a unit vacated the slot.
        clearly_vacated = (
            current_std < baseline_std * 0.72
            and current_laplacian < baseline_laplacian * 0.72
        )
        return change_evidence and not clearly_vacated

    @classmethod
    def training_crop_rejection_reason(
        cls, crop: Optional[np.ndarray], *, background: bool = False
    ) -> Optional[str]:
        """Explain why a crop must not enter training, or return ``None``."""
        if crop is None or crop.size == 0:
            return "unreadable"
        if cls._has_materialization_effect(crop):
            return "materialization"
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        full_laplacian = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if background:
            # Empty arena slots are naturally much smoother than champions,
            # but a completely flat/black crop indicates a bad capture.
            if float(np.std(gray)) < 4.0 and full_laplacian < 10.0:
                return "low_detail"
            return None
        if (
            not cls._is_viable_crop(cls._thumb(crop))
            or full_laplacian < _CROP_MIN_FULL_LAPLACIAN
        ):
            return "low_detail"
        return None

    def _save(self, crop: np.ndarray, name: str, slot: int) -> bool:
        if crop.size == 0:
            self._record_rejection("unreadable", name, slot)
            return False
        reason = self.training_crop_rejection_reason(crop)
        if reason:
            self._record_rejection(reason, name, slot)
            logger.info(
                f"Skipping {reason.replace('_', '-')} training crop: "
                f"{name} (bench slot {slot})"
            )
            return False
        if self._is_near_duplicate(crop, name):
            self._record_rejection("duplicate", name, slot)
            logger.debug(f"Skipping near-duplicate training crop: {name} (slot {slot})")
            return False
        return self._write_crop(crop, name, slot)

    def _save_empty(self, crop: np.ndarray, slot: int) -> bool:
        reason = self.training_crop_rejection_reason(crop, background=True)
        if reason:
            self._record_rejection(reason, "_empty", slot)
            return False
        if self._is_near_duplicate(crop, "_empty"):
            self._record_rejection("duplicate", "_empty", slot)
            return False
        return self._write_crop(crop, "_empty", slot)

    @staticmethod
    def _safe_label(name: str) -> str:
        return name.replace("'", "").replace(" ", "_").replace(".", "")

    def _is_near_duplicate(self, crop: np.ndarray, name: str) -> bool:
        safe = self._safe_label(name)
        if safe not in self._loaded_thumb_labels:
            remembered: list[np.ndarray] = []
            for path in sorted((self.out_dir / safe).glob("*.png")):
                image = cv2.imread(str(path), cv2.IMREAD_COLOR)
                thumb = self._thumb(image) if image is not None else None
                if thumb is not None:
                    remembered.append(thumb)
            self._saved_thumbs[safe] = remembered
            self._loaded_thumb_labels.add(safe)
        thumb = self._thumb(crop)
        if thumb is None:
            return True
        return any(
            float(np.mean(cv2.absdiff(thumb, prior))) <= _DUPLICATE_THUMB_MAD
            for prior in self._saved_thumbs.get(safe, [])
        )

    def _write_crop(self, crop: np.ndarray, name: str, slot: int) -> bool:
        safe = self._safe_label(name)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out = self.out_dir / safe / f"{ts}_slot{slot}.png"
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            # imwrite reports failure by returning False, not raising.
            if not cv2.imwrite(str(out), crop):
                self._record_rejection("write_failed", name, slot)
                logger.warning(f"Could not save training crop: imwrite failed for {out}")
                return False
        except OSError as e:
            self._record_rejection("write_failed", name, slot)
            logger.warning(f"Could not save training crop: {e}")
            return False
        self.saved_count += 1
        self.last_save_at = datetime.datetime.now().timestamp()
        self.last_saved_label = name
        self.last_event = f"Saved {name} from bench slot {slot}"
        thumb = self._thumb(crop)
        if thumb is not None:
            self._saved_thumbs.setdefault(safe, []).append(thumb)
            self._loaded_thumb_labels.add(safe)
        logger.info(f"Training crop saved: {name} (bench slot {slot}) → {out.name}")
        return True

    @staticmethod
    def _has_materialization_effect(crop: np.ndarray) -> bool:
        """Return True for the cyan/blue full-model purchase hologram."""
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        blue = (
            (hsv[:, :, 0] >= 80)
            & (hsv[:, :, 0] <= 115)
            & (hsv[:, :, 1] >= 130)
            & (hsv[:, :, 2] >= 140)
        ).astype(np.uint8)
        # Champion models and random scene detail can contain the same total
        # amount of blue in scattered pixels. The purchase hologram is one
        # contiguous full-model region, so gate on its largest component.
        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(
            blue, connectivity=8
        )
        if count <= 1:
            return False
        largest = int(stats[1:, cv2.CC_STAT_AREA].max())
        return largest / float(blue.size) >= _MATERIALIZATION_BLUE_COMPONENT_RATIO
