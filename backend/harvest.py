"""Unit-crop collection and quality auditing for the Set 18 classifier.

Live mode uses a high-volume manual inbox: health-bar-verified board and bench
crops are saved to ``_training/set18/_inbox`` without guessing names. The sorter
moves reviewed crops into champion folders. The older purchase-pairing path is
retained as an opt-in mode and for regression coverage, but is no longer used by
the live server because UE5 animations made its inferred labels unreliable.
"""

from __future__ import annotations

import datetime
import logging
import re
import time
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from config import (
    BENCH_CROP_HORIZONTAL_INSET_RATIO,
    BOARD_HEX_GRID,
    GameROIs,
    UNSAFE_BENCH_SLOTS,
)
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
_LANDING_RECOVERY_MIN_SCORE = 9.0
_LANDING_RECOVERY_MIN_MARGIN = 4.0
_LANDING_HISTORY_FRAMES = 6
_EMPTY_STD_MAX = 21.0
_OCCUPIED_STD_MIN = 19.5

# Continuous tracking of confirmed slots: save every Nth frame while the
# slot's thumbnail stays within _TRACK_CHANGE_LIMIT of the last saved one
# (idle animation drifts a little; moves/sells/combines jump far past it).
_TRACK_SAVE_INTERVAL = 1        # every processed frame while stable
_TRACK_MAX_SAVES = 12           # diverse poses without one purchase dominating
_TRACK_CHANGE_LIMIT = 18.0      # tolerate idle poses and brief spell glows
_TRACK_TOP_CHANGE_LIMIT = 10.0  # board units/effects entering above the bench
READY_CROPS_PER_CLASS = 50
_DUPLICATE_THUMB_MAD = 1.0      # <= this is effectively the same pose/frame
_MANUAL_STABILITY_THUMB_MAD = 12.0
_CROSS_LABEL_THUMB_MAD = 5.0    # same model must never survive under two labels
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
_HEALTH_BAR_MIN_WIDTH_RATIO = 0.22
_HEALTH_BAR_MAX_HEIGHT_RATIO = 0.12
_TOOLTIP_DARK_ROW_RATIO = 0.65
_TOOLTIP_MIN_DENSE_ROWS_RATIO = 0.20
_MANUAL_INBOX_DIR = "_inbox"
_MANUAL_REJECTED_DIR = "_rejected_manual"
_BENCH_CROP_FILENAME = re.compile(r"(?:^|_)(?:bench_)?slot[0-8](?:_|$)")


@dataclass
class _PendingLanding:
    label: str
    slot: int
    occupied_thumb: np.ndarray
    empty_thumb: np.ndarray


@dataclass
class _TrackedSlot:
    label: str
    reference: np.ndarray
    crop_reference: np.ndarray
    top_reference: np.ndarray
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
        if champ_dir.name in {_MANUAL_INBOX_DIR, _MANUAL_REJECTED_DIR}:
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
                require_health_bar=not bool(_BENCH_CROP_FILENAME.search(path.stem)),
            )
            thumb = BenchHarvester._thumb(image) if image is not None else None
            if reason:
                counts = rejected[label]
                counts[reason] = counts.get(reason, 0) + 1
                continue
            accepted[label].append(path)
            thumbs[label].append(thumb)

    # Pixel-quality checks cannot detect a semantically wrong folder. Flag
    # nearly identical crops appearing under different canonical labels; both
    # sides are unsafe because the image alone cannot tell us which label won.
    collision_paths: set[Path] = set()
    labels = [name for name, paths in accepted.items() if paths]
    for left_index, left_label in enumerate(labels):
        for right_label in labels[left_index + 1:]:
            for left_path, left_thumb in zip(
                accepted[left_label], thumbs[left_label]
            ):
                left_mean = float(np.mean(left_thumb))
                for right_path, right_thumb in zip(
                    accepted[right_label], thumbs[right_label]
                ):
                    if abs(left_mean - float(np.mean(right_thumb))) > (
                        _CROSS_LABEL_THUMB_MAD
                    ):
                        continue
                    distance = float(np.mean(cv2.absdiff(left_thumb, right_thumb)))
                    if distance <= _CROSS_LABEL_THUMB_MAD:
                        collision_paths.update((left_path, right_path))

    if collision_paths:
        for label, paths in accepted.items():
            removed = sum(path in collision_paths for path in paths)
            if removed:
                rejected[label]["label_collision"] = (
                    rejected[label].get("label_collision", 0) + removed
                )
                accepted[label] = [
                    path for path in paths if path not in collision_paths
                ]

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
        manual_inbox: bool = False,
        manual_interval: int = 1,
        manual_collect_board: bool = True,
        manual_source_interval: float = 8.0,
        manual_max_crops_per_session: Optional[int] = None,
        manual_max_inbox: Optional[int] = None,
        manual_stability_threshold: Optional[float] = _MANUAL_STABILITY_THUMB_MAD,
        manual_clock: Callable[[], float] = time.monotonic,
    ):
        self.out_dir = out_dir
        self.rois = GameROIs()
        self.track_interval = track_interval
        self.track_max_saves = track_max_saves
        self.track_change_limit = track_change_limit
        self.manual_inbox = manual_inbox
        self.manual_interval = max(1, manual_interval)
        self.manual_collect_board = manual_collect_board
        self.manual_source_interval = max(0.0, manual_source_interval)
        self.manual_max_crops_per_session = (
            None
            if manual_max_crops_per_session is None
            else max(1, manual_max_crops_per_session)
        )
        self.manual_max_inbox = (
            None if manual_max_inbox is None else max(1, manual_max_inbox)
        )
        self.manual_stability_threshold = manual_stability_threshold
        self._manual_clock = manual_clock
        self._manual_frame_count = 0
        self._manual_game_saved = 0
        self._manual_last_saved_by_source: dict[str, float] = {}
        self._manual_previous_by_source: dict[str, np.ndarray] = {}
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
        self.last_event = (
            "Manual inbox ready; waiting for visible units"
            if manual_inbox
            else "Waiting for a readable shop and bench baseline"
        )
        self.last_save_at: Optional[float] = None
        self.last_saved_label: Optional[str] = None
        self._suspended = False

    def process(
        self,
        frame: np.ndarray,
        purchases: list[str],
        pending_purchases: Optional[list[str]] = None,
    ) -> int:
        """Returns how many labeled or manual-inbox crops were saved."""
        if self.manual_inbox:
            if self._suspended:
                self._suspended = False
                self._manual_frame_count = 0
                self.last_event = "Trusted capture resumed; manual inbox rebased"
                return 0
            self._manual_frame_count += 1
            if self._manual_frame_count < self.manual_interval:
                return 0
            self._manual_frame_count = 0
            return self._collect_manual_inbox(frame)

        # Compare only the stable lower bench strip, but retain a taller crop
        # for training so the full UE5 model is visible. Using the tall crop
        # for motion detection would mix in board units above the bench.
        crops = self._bench_slot_crops(frame)
        anchor_crops = self._bench_anchor_slot_crops(frame)
        thumbs = [self._thumb(c) for c in anchor_crops]
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
                crop_current = self._thumb(crops[slot])
                top_current = self._top_thumb(crops[slot])
                if (
                    current is None
                    or crop_current is None
                    or top_current is None
                    or not self._has_champion_health_bar(crops[slot])
                    or self._has_ui_overlay(crops[slot])
                    or not self._became_occupied(
                        current, tracked.empty_reference
                    )
                ):
                    del self._tracked[slot]
                    continue
                drift = float(np.mean(cv2.absdiff(current, tracked.reference)))
                if drift >= self.track_change_limit:
                    del self._tracked[slot]
                    continue
                tracked.reference = current.copy()
                tracked.crop_reference = crop_current.copy()
                tracked.top_reference = top_current.copy()
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
        self._manual_frame_count = 0
        self._manual_game_saved = 0
        self._manual_last_saved_by_source.clear()
        self._manual_previous_by_source.clear()
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
        self._manual_previous_by_source.clear()

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
            "mode": "manual_inbox" if self.manual_inbox else "automatic",
            "inbox_crops": self.manual_inbox_count(),
            "manual_game_crops": self._manual_game_saved,
            "manual_game_cap": self.manual_max_crops_per_session,
            "manual_inbox_cap": self.manual_max_inbox,
        }

    def manual_inbox_count(self) -> int:
        return sum(1 for _ in (self.out_dir / _MANUAL_INBOX_DIR).glob("*.png"))

    def _collect_manual_inbox(self, frame: np.ndarray) -> int:
        """Save visible units without assigning champion names."""
        if (
            self.manual_max_crops_per_session is not None
            and self._manual_game_saved >= self.manual_max_crops_per_session
        ):
            self.skip_counts["manual_session_cap"] += 1
            self.last_event = (
                "Manual inbox paused: this game reached its crop limit"
            )
            return 0
        inbox_count = self.manual_inbox_count()
        if (
            self.manual_max_inbox is not None
            and inbox_count >= self.manual_max_inbox
        ):
            self.skip_counts["manual_inbox_full"] += 1
            self.last_event = "Manual inbox full; sort or reject crops to resume"
            return 0

        now = self._manual_clock()
        candidates: list[tuple[str, np.ndarray]] = []
        if self.manual_collect_board:
            candidates.extend(self._board_hex_crops(frame))
        candidates.extend(
            (f"bench_slot{slot}", crop)
            for slot, crop in enumerate(self._bench_slot_crops(frame))
            if slot not in UNSAFE_BENCH_SLOTS
        )

        saved = 0
        for source, crop in candidates:
            # Board health bars are the safest occupancy signal. Set 18 bench
            # models can render without one, so reviewed bench crops rely on
            # detail, stability, cooldowns, and review instead of this
            # board-only gate.
            reason = self.training_crop_rejection_reason(
                crop,
                require_health_bar=source.startswith("board_"),
            )
            if reason:
                self.rejection_counts[reason] += 1
                continue
            thumb = self._thumb(crop)
            previous = self._manual_previous_by_source.get(source)
            if thumb is None:
                self.rejection_counts["unreadable"] += 1
                continue
            self._manual_previous_by_source[source] = thumb
            if self.manual_stability_threshold is not None:
                if previous is None:
                    self.skip_counts["manual_stability_baseline"] += 1
                    continue
                movement = float(np.mean(cv2.absdiff(thumb, previous)))
                if movement > self.manual_stability_threshold:
                    self.skip_counts["manual_unstable"] += 1
                    continue
            last_saved = self._manual_last_saved_by_source.get(source)
            if (
                last_saved is not None
                and now - last_saved < self.manual_source_interval
            ):
                self.skip_counts["manual_source_cooldown"] += 1
                continue
            if self._write_manual_crop(crop, source):
                saved += 1
                self._manual_game_saved += 1
                self._manual_last_saved_by_source[source] = now
                if (
                    (
                        self.manual_max_crops_per_session is not None
                        and self._manual_game_saved
                        >= self.manual_max_crops_per_session
                    )
                    or (
                        self.manual_max_inbox is not None
                        and inbox_count + saved >= self.manual_max_inbox
                    )
                ):
                    break

        if saved:
            self.last_event = (
                f"Saved {saved} unlabeled unit crop(s) to the manual inbox"
            )
        else:
            self.last_event = "Manual inbox watching visible board and bench units"
        return saved

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
            if slot in UNSAFE_BENCH_SLOTS:
                del self._tracked[slot]
                continue
            if slot in just_confirmed:
                continue    # landing crop already saved this frame
            tracked = self._tracked[slot]
            crop_thumb = self._thumb(crops[slot])
            top_thumb = self._top_thumb(crops[slot])
            if thumbs[slot] is None or crop_thumb is None or top_thumb is None:
                del self._tracked[slot]
                continue
            if (
                not self._has_champion_health_bar(crops[slot])
                or self._has_ui_overlay(crops[slot])
            ):
                # Little Legends, tooltips, and replacement effects can occupy
                # the same pixels as a previously confirmed bench unit. Never
                # turn those frames into pose diversity or background data.
                tracked.occupancy_misses += 1
                if tracked.occupancy_misses >= 2:
                    del self._tracked[slot]
                continue
            if not self._became_occupied(thumbs[slot], tracked.empty_reference):
                if tracked.occupancy_misses >= 1:
                    # Runtime motion cannot prove that a crop is background:
                    # the old occupant may have been replaced by another unit
                    # or the movable Little Legend. Stop tracking without ever
                    # writing an automatic _empty sample.
                    logger.debug(
                        f"Slot {slot} no longer contains a trusted champion — "
                        f"stop tracking {tracked.label}"
                    )
                    del self._tracked[slot]
                else:
                    tracked.occupancy_misses += 1
                continue
            tracked.occupancy_misses = 0
            drift = float(np.mean(cv2.absdiff(thumbs[slot], tracked.reference)))
            crop_drift = float(np.mean(cv2.absdiff(
                crop_thumb, tracked.crop_reference
            )))
            top_drift = float(np.mean(cv2.absdiff(
                top_thumb, tracked.top_reference
            )))

            # The first confirmation frame can still be the UE5 purchase
            # hologram.  If it failed the quality gate, keep the trusted slot
            # label alive and follow the animation until it settles.  Rebase
            # on large visual changes instead of treating the hologram ->
            # champion transition as the unit leaving.
            if tracked.saves == 0:
                if (
                    drift >= self.track_change_limit
                    or crop_drift >= self.track_change_limit
                    or top_drift >= _TRACK_TOP_CHANGE_LIMIT
                ):
                    tracked.reference = thumbs[slot].copy()
                    tracked.crop_reference = crop_thumb.copy()
                    tracked.top_reference = top_thumb.copy()
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
                        tracked.crop_reference = crop_thumb.copy()
                        tracked.top_reference = top_thumb.copy()
                continue

            if (
                drift >= self.track_change_limit
                or crop_drift >= self.track_change_limit
                or top_drift >= _TRACK_TOP_CHANGE_LIMIT
            ):
                # Empty/low-detail means the unit definitely left. A single
                # viable high-drift frame may just be an idle animation or
                # spell glow, so require it to repeat before abandoning the
                # label without ever saving the uncertain frame.
                if tracked.change_frames >= 2:
                    logger.debug(
                        f"Slot {slot} changed (anchor drift {drift:.0f}, "
                        f"crop drift {crop_drift:.0f}, top drift {top_drift:.0f}) — "
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
                    tracked.crop_reference = crop_thumb
                    tracked.top_reference = top_thumb
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
            if not self._landing_persists(
                current, landing, crops[landing.slot]
            ):
                self.skip_counts["landing_not_persistent"] += 1
                self.last_event = (
                    f"Confirmed {landing.label}, but bench slot "
                    f"{landing.slot} no longer matched its staged landing"
                )
                continue
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
                crop_reference=self._thumb(crops[landing.slot]),
                top_reference=self._top_thumb(crops[landing.slot]),
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
            if not self._landing_persists(
                current, landing, current_frame.crops[landing.slot]
            ):
                self.skip_counts["landing_not_persistent"] += 1
                self.last_event = (
                    f"Confirmed {landing.label}, but bench slot "
                    f"{landing.slot} no longer matched its landing"
                )
                continue
            did_save = self._save(
                current_frame.crops[landing.slot], landing.label, landing.slot
            )
            saved += int(did_save)
            self._tracked[landing.slot] = _TrackedSlot(
                label=landing.label,
                reference=current.copy(),
                crop_reference=self._thumb(current_frame.crops[landing.slot]),
                top_reference=self._top_thumb(current_frame.crops[landing.slot]),
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
            changed_slots = self._newly_occupied_slots(after.thumbs, before.thumbs)
            if not changed_slots:
                mismatches.append(
                    f"-{len(frames) - index}: "
                    f"{self._last_transition_diagnostic}"
                )
                continue
            slots = [
                slot for slot in changed_slots
                if self._is_trusted_landing_transition(
                    before.crops[slot], after.crops[slot]
                )
            ]
            if not slots:
                self._last_landing_diagnostic = (
                    f"history offset {len(frames) - index}: visual transition "
                    f"rejected for slots={changed_slots}"
                )
                return []
            if len(slots) != len(names):
                # UE5 idle poses can move several already-occupied slots in
                # the same slow detector interval as one real landing. Once
                # a later confirmation frame proves which change persisted,
                # recover a single dominant stable-before → stable-after
                # landing. Never guess for multi-buy labels: their ordering
                # cannot be recovered safely from a single sampled frame.
                recovered = None
                if len(names) == 1 and len(slots) > 1:
                    recovered = self._recover_single_landing_slot(
                        frames, index, slots
                    )
                if recovered is None:
                    self._last_landing_diagnostic = (
                        f"history offset {len(frames) - index}: "
                        f"slots={slots}, wanted={len(names)}"
                    )
                    return []
                slots = [recovered]
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

    def _recover_single_landing_slot(
        self,
        frames: list[_BenchFrame],
        transition_index: int,
        slots: list[int],
    ) -> Optional[int]:
        """Resolve one landing hidden among animated occupied bench slots.

        Recovery requires frames on both sides of the transition. A real
        landing has a stable empty baseline, a large transition, and remains
        occupied on the confirmation frame. Existing units that merely change
        pose pay both a pre-transition motion penalty and a post-transition
        drift penalty. A minimum score and lead over the runner-up keep this
        conservative when arena effects make two candidates equally likely.
        """
        if transition_index < 2 or transition_index + 1 >= len(frames):
            return None

        prior = frames[transition_index - 2]
        before = frames[transition_index - 1]
        after = frames[transition_index]
        confirmed = frames[transition_index + 1]
        scored: list[tuple[float, int, float, float, float]] = []

        for slot in slots:
            four = (
                prior.thumbs[slot],
                before.thumbs[slot],
                after.thumbs[slot],
                confirmed.thumbs[slot],
            )
            if any(thumb is None for thumb in four):
                continue
            prior_thumb, before_thumb, after_thumb, confirmed_thumb = four
            transition = float(np.mean(cv2.absdiff(after_thumb, before_thumb)))
            pre_drift = float(np.mean(cv2.absdiff(before_thumb, prior_thumb)))
            post_drift = float(np.mean(cv2.absdiff(confirmed_thumb, after_thumb)))
            if not self._became_occupied(
                confirmed_thumb,
                before_thumb,
                change_evidence=True,
            ):
                continue
            score = transition - (1.5 * pre_drift) - (0.5 * post_drift)
            scored.append((score, slot, transition, pre_drift, post_drift))

        scored.sort(reverse=True)
        if not scored:
            return None
        best = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        margin = best[0] - runner_up
        self._last_transition_diagnostic += (
            "; recovery="
            + str([
                {
                    "slot": slot,
                    "score": round(score, 1),
                    "change": round(change, 1),
                    "pre": round(pre, 1),
                    "post": round(post, 1),
                }
                for score, slot, change, pre, post in scored
            ])
        )
        if (
            best[0] < _LANDING_RECOVERY_MIN_SCORE
            or margin < _LANDING_RECOVERY_MIN_MARGIN
        ):
            return None

        self.skip_counts["ambiguous_landing_recovered"] += 1
        logger.info(
            f"Recovered animated single-unit landing in bench slot {best[1]} "
            f"(score={best[0]:.1f}, margin={margin:.1f})"
        )
        return best[1]

    @classmethod
    def _landing_persists(
        cls,
        current: Optional[np.ndarray],
        landing: _PendingLanding,
        current_crop: Optional[np.ndarray] = None,
    ) -> bool:
        """Validate a staged landing without assuming empty arenas are smooth.

        The transition detector already proved that the slot changed relative
        to its eight peers. Confirmation only needs to show that the current
        slot remains materially different from the staged empty crop and is
        at least approximately as close to the landed model as to that empty
        texture. This works on high-detail Set 18 arenas while still rejecting
        a unit that was moved away before shop confirmation.
        """
        if (
            current is None
            or current_crop is None
            or not cls._has_champion_health_bar(current_crop)
            or cls._has_ui_overlay(current_crop)
        ):
            return False
        empty_distance = float(np.mean(cv2.absdiff(
            current, landing.empty_thumb
        )))
        landed_distance = float(np.mean(cv2.absdiff(
            current, landing.occupied_thumb
        )))
        return (
            empty_distance >= _CHANGE_FLOOR
            and landed_distance <= empty_distance * 1.15
        )

    def _newly_occupied_slots(
        self,
        thumbs: list[Optional[np.ndarray]],
        baseline: Optional[list[np.ndarray]],
    ) -> list[int]:
        if baseline is None:
            return []
        diffs = [
            float(np.mean(cv2.absdiff(thumbs[i], baseline[i])))
            if (
                i not in UNSAFE_BENCH_SLOTS
                and thumbs[i] is not None
                and baseline[i] is not None
            ) else 0.0
            for i in range(BENCH_SLOTS)
        ]
        typical = float(np.median(diffs)) if diffs else 0.0
        threshold = max(_CHANGE_FLOOR, typical * _CHANGE_OUTLIER_FACTOR)
        changed = [
            i for i in range(BENCH_SLOTS)
            if i not in UNSAFE_BENCH_SLOTS and diffs[i] >= threshold
        ]
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
        """Return vertically tightened model crops for saving and inference."""
        return self._split_bench_roi(
            frame,
            self.rois.champion_bench_capture,
            horizontal_inset_ratio=BENCH_CROP_HORIZONTAL_INSET_RATIO,
        )

    def _board_hex_crops(self, frame: np.ndarray) -> list[tuple[str, np.ndarray]]:
        """Use pixel-identical board geometry to classifier inference."""
        height, width = frame.shape[:2]
        bx, by, bw, bh = self.rois.board.to_pixels(width, height)
        board_region = frame[by:by + bh, bx:bx + bw]
        region_height, region_width = board_region.shape[:2]
        crops: list[tuple[str, np.ndarray]] = []
        for index, position in enumerate(BOARD_HEX_GRID):
            center_x = int(position.cx * region_width)
            center_y = int(position.cy * region_height)
            radius = int(position.radius * region_width)
            crop = board_region[
                max(0, center_y - int(2.55 * radius)):
                min(region_height, center_y + radius),
                max(0, center_x - int(1.1 * radius)):
                min(region_width, center_x + int(1.1 * radius)),
            ]
            crops.append(
                (f"board_r{position.row}_c{position.col}_i{index}", crop)
            )
        return crops

    def _bench_anchor_slot_crops(self, frame: np.ndarray) -> list[np.ndarray]:
        """Return the lower, stable strip used only for landing motion."""
        return self._split_bench_roi(frame, self.rois.champion_bench)

    @staticmethod
    def _split_bench_roi(
        frame: np.ndarray,
        roi,
        *,
        horizontal_inset_ratio: float = 0.0,
    ) -> list[np.ndarray]:
        h, w = frame.shape[:2]
        bx, by, bw, bh = roi.to_pixels(w, h)
        slot_w = max(1, bw // BENCH_SLOTS)
        inset = min(
            slot_w // 3,
            max(0, int(round(slot_w * horizontal_inset_ratio))),
        )
        return [
            frame[
                by:by + bh,
                bx + i * slot_w + inset:bx + (i + 1) * slot_w - inset,
            ]
            for i in range(BENCH_SLOTS)
        ]

    @classmethod
    def _is_trusted_landing_transition(
        cls,
        before_crop: np.ndarray,
        after_crop: np.ndarray,
    ) -> bool:
        """Require visual evidence of a real empty -> champion transition."""
        return (
            not cls._has_ui_overlay(before_crop)
            and not cls._has_ui_overlay(after_crop)
            and not cls._has_champion_health_bar(before_crop)
            and cls._has_champion_health_bar(after_crop)
        )

    @staticmethod
    def _champion_health_bar_bands(
        crop: Optional[np.ndarray],
    ) -> list[tuple[int, int, int, int]]:
        """Return plausible champion health-bar bands as x/y/width/height."""
        if crop is None or crop.size == 0:
            return []
        height, width = crop.shape[:2]
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        green = cv2.inRange(
            hsv,
            np.array([45, 170, 50], dtype=np.uint8),
            np.array([75, 255, 255], dtype=np.uint8),
        )
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(3, width // 16), 1)
        )
        green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, kernel)
        dense_rows = np.mean(green > 0, axis=1) >= 0.35
        padded = np.pad(dense_rows.astype(np.int8), (1, 1))
        edges = np.diff(padded)
        starts = np.flatnonzero(edges == 1)
        ends = np.flatnonzero(edges == -1)
        bars: list[tuple[int, int, int, int]] = []
        for start, end in zip(starts, ends):
            bar_height = end - start
            if start >= height * 0.60 or not (
                2 <= bar_height <= height * _HEALTH_BAR_MAX_HEIGHT_RATIO
            ):
                continue
            columns = np.any(green[start:end] > 0, axis=0)
            positions = np.flatnonzero(columns)
            if positions.size == 0:
                continue
            x, right = int(positions[0]), int(positions[-1])
            bar_width = right - x + 1
            if (
                bar_width >= width * _HEALTH_BAR_MIN_WIDTH_RATIO
                and x < width * 0.70
                and right > width * 0.30
            ):
                bars.append((x, int(start), bar_width, int(bar_height)))
        return bars

    @classmethod
    def _has_champion_health_bar(cls, crop: Optional[np.ndarray]) -> bool:
        """Detect the long green bar rendered above every bench champion."""
        return bool(cls._champion_health_bar_bands(crop))

    @staticmethod
    def _has_ui_overlay(crop: Optional[np.ndarray]) -> bool:
        """Recognize dark text panels that can mimic a bench transition."""
        if crop is None or crop.size == 0:
            return False
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        dark_rows = np.mean(gray < 55, axis=1) >= _TOOLTIP_DARK_ROW_RATIO
        if float(np.mean(dark_rows)) < _TOOLTIP_MIN_DENSE_ROWS_RATIO:
            return False
        neutral_bright = (gray > 150) & (hsv[:, :, 1] < 60)
        text_rows = np.mean(neutral_bright, axis=1) >= 0.01
        return float(np.mean(dark_rows & text_rows)) >= 0.02

    @staticmethod
    def _thumb(crop: np.ndarray) -> Optional[np.ndarray]:
        if crop.size == 0:
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        return cv2.resize(gray, _THUMB_SIZE, interpolation=cv2.INTER_AREA)

    @staticmethod
    def _top_thumb(crop: np.ndarray) -> Optional[np.ndarray]:
        """Thumbnail of the top edge where neighboring board units intrude."""
        if crop is None or crop.size == 0:
            return None
        top_height = max(1, int(round(crop.shape[0] * 0.18)))
        return BenchHarvester._thumb(crop[:top_height])

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
        cls,
        crop: Optional[np.ndarray],
        *,
        background: bool = False,
        require_health_bar: bool = True,
    ) -> Optional[str]:
        """Explain why a crop must not enter training, or return ``None``."""
        if crop is None or crop.size == 0:
            return "unreadable"
        if cls._has_ui_overlay(crop):
            return "ui_overlay"
        health_bars = cls._champion_health_bar_bands(crop)
        if background and health_bars:
            return "occupied_background"
        if not background and require_health_bar and not health_bars:
            return "no_health_bar"
        if not background and len(health_bars) > 1:
            return "multiple_health_bars"
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

    @staticmethod
    def _safe_label(name: str) -> str:
        return name.replace("'", "").replace(" ", "_").replace(".", "")

    def _is_near_duplicate(
        self,
        crop: np.ndarray,
        name: str,
        *,
        threshold: float = _DUPLICATE_THUMB_MAD,
    ) -> bool:
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
            float(np.mean(cv2.absdiff(thumb, prior))) <= threshold
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

    def _write_manual_crop(self, crop: np.ndarray, source: str) -> bool:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out = self.out_dir / _MANUAL_INBOX_DIR / f"{ts}_{source}.png"
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            if not cv2.imwrite(str(out), crop):
                self.rejection_counts["write_failed"] += 1
                logger.warning(f"Could not save manual training crop: {out}")
                return False
        except OSError as error:
            self.rejection_counts["write_failed"] += 1
            logger.warning(f"Could not save manual training crop: {error}")
            return False
        self.saved_count += 1
        self.last_save_at = datetime.datetime.now().timestamp()
        self.last_saved_label = _MANUAL_INBOX_DIR
        logger.info(f"Manual training crop saved: {source} → {out.name}")
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
