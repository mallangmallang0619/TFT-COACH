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


def preprocess(
    crops: list[np.ndarray],
    input_size: int,
    mean: np.ndarray,
    std: np.ndarray,
) -> np.ndarray:
    """
    BGR crops -> normalized NCHW float32 batch, mirroring the training
    pipeline (cv2 decode, RGB, squash-resize, ImageNet normalization).
    """
    batch = np.empty((len(crops), 3, input_size, input_size), dtype=np.float32)
    for i, crop in enumerate(crops):
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (input_size, input_size), interpolation=cv2.INTER_AREA)
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
            self.labels = meta["labels"]
            self.input_size = int(meta["input_size"])
            self._mean = np.array(meta["mean"], dtype=np.float32).reshape(3, 1, 1)
            self._std = np.array(meta["std"], dtype=np.float32).reshape(3, 1, 1)
            self.min_confidence = float(meta.get("min_confidence", 0.60))
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
        from game_data import find_champion_name

        self.display_names = [
            None if lbl.startswith("_")
            else (find_champion_name(lbl.replace("_", " ")) or lbl.replace("_", " "))
            for lbl in self.labels
        ]
        self.available = True
        logger.info(
            f"Unit classifier loaded: {len(self.labels)} classes, "
            f"input {self.input_size}px, min confidence {self.min_confidence}"
        )

    def classify_batch(
        self, crops: list[np.ndarray]
    ) -> list[tuple[Optional[str], float]]:
        """
        Classify BGR crops in one session run. Returns one (name,
        confidence) per crop; name is None for low-confidence results,
        background classes, or unusable crops.
        """
        if not self.available or not crops:
            return [(None, 0.0)] * len(crops)

        valid = [i for i, c in enumerate(crops) if c is not None and c.size > 0]
        results: list[tuple[Optional[str], float]] = [(None, 0.0)] * len(crops)
        if not valid:
            return results

        batch = preprocess(
            [crops[i] for i in valid], self.input_size, self._mean, self._std
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
            if name is not None and conf >= self.min_confidence:
                results[i] = (name, conf)
            else:
                results[i] = (None, conf)
        return results
