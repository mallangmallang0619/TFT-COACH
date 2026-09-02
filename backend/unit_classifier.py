"""
Unit Classifier — ONNX inference for live board/bench unit identification.

Live frames render units as 3D models that template matching can't
identify. The trained classifier (scripts/train_classifier.py, fed by the
bench-crop harvester) ships in assets/models/ and identifies those models
directly from per-slot / per-hex crops.

Fully optional at runtime: when the model files or onnxruntime are
missing, `available` is False and classify() returns nothing — the
detector falls back to the roster (shop purchase tracking) exactly as
before. Preprocessing (input size, normalization, color order) is read
from unit_classifier.json, which training writes alongside the model, so
the two can't drift apart.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from config import ASSETS_DIR

logger = logging.getLogger(__name__)

MODELS_DIR = ASSETS_DIR / "models"
MODEL_PATH = MODELS_DIR / "unit_classifier.onnx"
META_PATH = MODELS_DIR / "unit_classifier.json"
LEGACY_BOARD_CROP_MODE = "legacy_hex_v1"
DEFAULT_BOARD_CROP_MODE = "health_bar_v1"
DEFAULT_OCCUPIED_BOARD_MIN_CONFIDENCE = 0.08
LEGACY_RESIZE_MODE = "stretch"
FULL_SPRITE_RESIZE_MODE = "letterbox"
MINIMUM_ACCEPTED_UNIT_CONFIDENCE = 0.55


def safe_confidence_floor(value: float) -> float:
    """Never accept a trained-model identity below the shipping safety floor."""
    return max(MINIMUM_ACCEPTED_UNIT_CONFIDENCE, float(value))


class UnitPredictionStabilizer:
    """Turn noisy per-frame slot predictions into stable unit identities.

    A TFT model idles and animates inside an otherwise fixed board/bench
    position.  One frame can therefore favor a visually similar champion.
    New identities must repeat before they are shown, established identities
    survive uncertain frames, and confident background must repeat before a
    slot is cleared.
    """

    def __init__(
        self,
        slot_count: int,
        min_confidence: float,
        acquire_frames: int = 2,
        switch_frames: int = 3,
        clear_frames: int = 3,
    ):
        self.slot_count = slot_count
        self.min_confidence = min_confidence
        self.acquire_frames = acquire_frames
        self.switch_frames = switch_frames
        self.clear_frames = clear_frames
        self.reset()

    def reset(self) -> None:
        self._names: list[Optional[str]] = [None] * self.slot_count
        self._confidences: list[float] = [0.0] * self.slot_count
        self._candidates: list[Optional[str]] = [None] * self.slot_count
        self._candidate_counts: list[int] = [0] * self.slot_count
        self._candidate_confidences: list[float] = [0.0] * self.slot_count
        self._clear_counts: list[int] = [0] * self.slot_count

    def current(self) -> list[tuple[Optional[str], float]]:
        return list(zip(self._names, self._confidences))

    def update(
        self,
        results: list[tuple[Optional[str], float]],
        update_mask: Optional[list[bool]] = None,
        min_confidences: Optional[list[float]] = None,
    ) -> list[tuple[Optional[str], float]]:
        if len(results) != self.slot_count:
            raise ValueError(
                f"Expected {self.slot_count} unit slots, got {len(results)}"
            )
        if update_mask is not None and len(update_mask) != self.slot_count:
            raise ValueError(
                f"Expected {self.slot_count} update flags, got {len(update_mask)}"
            )
        if min_confidences is not None and len(min_confidences) != self.slot_count:
            raise ValueError(
                f"Expected {self.slot_count} confidence floors, "
                f"got {len(min_confidences)}"
            )

        for i, (name, confidence) in enumerate(results):
            if update_mask is not None and not update_mask[i]:
                continue

            stable_name = self._names[i]
            confidence_floor = (
                min_confidences[i]
                if min_confidences is not None
                else self.min_confidence
            )
            confident = confidence >= confidence_floor
            if name is not None and not confident:
                name = None

            if name is None:
                # A low score means the network is unsure, not that a model
                # disappeared.  Preserve the last trustworthy identity.
                self._candidates[i] = None
                self._candidate_counts[i] = 0
                self._candidate_confidences[i] = 0.0
                if confident and stable_name is not None:
                    self._clear_counts[i] += 1
                    if self._clear_counts[i] >= self.clear_frames:
                        self._names[i] = None
                        self._confidences[i] = 0.0
                        self._clear_counts[i] = 0
                elif not confident:
                    self._clear_counts[i] = 0
                continue

            self._clear_counts[i] = 0
            if name == stable_name:
                # Smooth the displayed confidence without changing identity.
                old = self._confidences[i]
                self._confidences[i] = confidence if old == 0.0 else (
                    old * 0.6 + confidence * 0.4
                )
                self._candidates[i] = None
                self._candidate_counts[i] = 0
                self._candidate_confidences[i] = 0.0
                continue

            if name == self._candidates[i]:
                count = self._candidate_counts[i] + 1
                self._candidate_counts[i] = count
                self._candidate_confidences[i] = (
                    self._candidate_confidences[i] * (count - 1) + confidence
                ) / count
            else:
                self._candidates[i] = name
                self._candidate_counts[i] = 1
                self._candidate_confidences[i] = confidence

            needed = self.acquire_frames if stable_name is None else self.switch_frames
            if self._candidate_counts[i] >= needed:
                self._names[i] = name
                self._confidences[i] = self._candidate_confidences[i]
                self._candidates[i] = None
                self._candidate_counts[i] = 0
                self._candidate_confidences[i] = 0.0

        return self.current()


def resize_for_classifier(
    crop: np.ndarray,
    input_size: int,
    mode: str = LEGACY_RESIZE_MODE,
) -> np.ndarray:
    """Resize a crop while optionally preserving the full sprite geometry."""
    if mode != FULL_SPRITE_RESIZE_MODE:
        return cv2.resize(
            crop, (input_size, input_size), interpolation=cv2.INTER_AREA
        )
    height, width = crop.shape[:2]
    scale = min(input_size / max(1, width), input_size / max(1, height))
    resized_width = max(1, min(input_size, round(width * scale)))
    resized_height = max(1, min(input_size, round(height * scale)))
    interpolation = cv2.INTER_AREA if scale <= 1.0 else cv2.INTER_LINEAR
    resized = cv2.resize(
        crop, (resized_width, resized_height), interpolation=interpolation
    )
    canvas = np.zeros((input_size, input_size, crop.shape[2]), dtype=crop.dtype)
    left = (input_size - resized_width) // 2
    top = (input_size - resized_height) // 2
    canvas[top:top + resized_height, left:left + resized_width] = resized
    return canvas


def preprocess(
    crops: list[np.ndarray],
    input_size: int,
    mean: np.ndarray,
    std: np.ndarray,
    resize_mode: str = LEGACY_RESIZE_MODE,
) -> np.ndarray:
    """
    BGR crops -> normalized NCHW float32 batch, mirroring the training
    pipeline (cv2 decode, RGB, squash-resize, ImageNet normalization).
    """
    batch = np.empty((len(crops), 3, input_size, input_size), dtype=np.float32)
    for i, crop in enumerate(crops):
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        resized = resize_for_classifier(rgb, input_size, resize_mode)
        chw = resized.astype(np.float32).transpose(2, 0, 1) / 255.0
        batch[i] = (chw - mean) / std
    return batch


class UnitClassifier:
    """Loads the ONNX model when present; a no-op otherwise."""

    def __init__(self, model_path: Path = MODEL_PATH, meta_path: Path = META_PATH):
        self.available = False
        self._session = None
        self.labels: list[str] = []
        self.display_names: list[Optional[str]] = []
        self.min_confidence = 0.60
        # A health bar independently establishes board occupancy, letting the
        # classifier use a lower identity floor there while still requiring
        # temporal agreement. Bench predictions retain the global floor.
        self.board_crop_mode = DEFAULT_BOARD_CROP_MODE
        self.board_min_confidence = DEFAULT_OCCUPIED_BOARD_MIN_CONFIDENCE
        self.resize_mode = LEGACY_RESIZE_MODE

        if not (model_path.exists() and meta_path.exists()):
            logger.debug("Unit classifier model not present — CNN unit ID disabled.")
            return
        try:
            import onnxruntime as ort
        except ImportError:
            logger.warning(
                "Unit classifier model found but onnxruntime is not installed "
                "(pip install onnxruntime) — CNN unit ID disabled."
            )
            return

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            from game_data import ACTIVE_ENGINE, ACTIVE_SET_NUMBER

            model_set = meta.get("set_number")
            model_engine = meta.get("engine")
            if model_set != ACTIVE_SET_NUMBER or model_engine != ACTIVE_ENGINE:
                logger.warning(
                    "Ignoring stale unit classifier "
                    f"(model set={model_set}, engine={model_engine}; "
                    f"runtime set={ACTIVE_SET_NUMBER}, engine={ACTIVE_ENGINE}). "
                    "Collect Unreal crops and retrain for the current set."
                )
                return
            self.labels = meta["labels"]
            self.input_size = int(meta["input_size"])
            self._mean = np.array(meta["mean"], dtype=np.float32).reshape(3, 1, 1)
            self._std = np.array(meta["std"], dtype=np.float32).reshape(3, 1, 1)
            self.min_confidence = safe_confidence_floor(
                meta.get("min_confidence", 0.60)
            )
            self.resize_mode = str(meta.get("resize_mode", LEGACY_RESIZE_MODE))
            self.board_crop_mode = str(
                meta.get("board_crop_mode", DEFAULT_BOARD_CROP_MODE)
            )
            default_board_floor = (
                DEFAULT_OCCUPIED_BOARD_MIN_CONFIDENCE
                if "board_crop_mode" not in meta
                else self.min_confidence
            )
            self.board_min_confidence = safe_confidence_floor(
                meta.get("board_min_confidence", default_board_floor)
            )
            self._session = ort.InferenceSession(
                str(model_path), providers=["CPUExecutionProvider"]
            )
        except Exception as e:
            logger.warning(f"Could not load unit classifier: {e}")
            self._session = None
            return

        # Training labels are sanitized directory names (BelVeth,
        # Miss_Fortune) — resolve them to canonical champion names once.
        # Background classes (leading underscore, e.g. _empty) resolve to
        # None and are reported as "no unit".
        from game_data import canonical_training_label, find_champion_name

        self.display_names = [
            None if lbl.startswith("_")
            else (
                find_champion_name(canonical_training_label(lbl.replace("_", " ")))
                or canonical_training_label(lbl.replace("_", " "))
            )
            for lbl in self.labels
        ]
        self.available = True
        logger.info(
            f"Unit classifier loaded: {len(self.labels)} classes, "
            f"input {self.input_size}px, min confidence {self.min_confidence}"
        )

    def classify_batch(
        self,
        crops: list[np.ndarray],
        min_confidences: Optional[list[float]] = None,
    ) -> list[tuple[Optional[str], float]]:
        """
        Classify BGR crops in one session run. Returns one (name,
        confidence) per crop; name is None for low-confidence results,
        background classes, or unusable crops.
        """
        if not self.available or not crops:
            return [(None, 0.0)] * len(crops)
        if min_confidences is not None and len(min_confidences) != len(crops):
            raise ValueError(
                f"Expected {len(crops)} confidence floors, "
                f"got {len(min_confidences)}"
            )

        valid = [i for i, c in enumerate(crops) if c is not None and c.size > 0]
        results: list[tuple[Optional[str], float]] = [(None, 0.0)] * len(crops)
        if not valid:
            return results

        batch = preprocess(
            [crops[i] for i in valid],
            self.input_size,
            self._mean,
            self._std,
            self.resize_mode,
        )
        logits = self._session.run(None, {"image": batch})[0]
        # Softmax (stable) — confidences gate acceptance.
        z = logits - logits.max(axis=1, keepdims=True)
        probs = np.exp(z)
        probs /= probs.sum(axis=1, keepdims=True)

        for row, i in enumerate(valid):
            k = int(probs[row].argmax())
            conf = float(probs[row, k])
            name = self.display_names[k]
            confidence_floor = (
                min_confidences[i]
                if min_confidences is not None
                else self.min_confidence
            )
            if name is not None and conf >= confidence_floor:
                results[i] = (name, conf)
            else:
                results[i] = (None, conf)
        return results
