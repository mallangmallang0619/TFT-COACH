"""Optional ONNX classifiers for star level and equipped unit items.

These models are intentionally independent from champion identity. A missing,
stale, or uncertain detail model abstains and leaves the existing unit result
unchanged. Star level is a three-class softmax task; equipped items are a
multi-label sigmoid task because one unit can hold up to three items.
"""

from __future__ import annotations

import json
import logging
import datetime
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from config import ASSETS_DIR
from game_data import ACTIVE_SET_NUMBER, COMPONENT_NAMES
from unit_classifier import FULL_SPRITE_RESIZE_MODE, preprocess

logger = logging.getLogger(__name__)

MODELS_DIR = ASSETS_DIR / "models"
DETAIL_TRAINING_DIR = (
    Path(__file__).parent / "_training" / f"set{ACTIVE_SET_NUMBER}_details"
)
_SAFE_SOURCE = re.compile(r"[^a-zA-Z0-9_-]+")


def unit_detail_collection_enabled(value: Optional[str]) -> bool:
    """Default detail collection on; retain an explicit environment off switch."""
    return (value or "").strip().lower() not in {"0", "false", "no", "off"}


@dataclass
class UnitDetailRegions:
    health_bar: tuple[int, int, int, int]
    star_badge: np.ndarray
    item_strip: np.ndarray
    item_icons: list[np.ndarray]


class UnitDetailCollector:
    """Save paired, unlabeled star/item regions for later manual review.

    Collection is intentionally source-throttled. One accepted unit crop yields
    exactly one star crop and one equipped-item crop with the same filename so
    labels and provenance can be reconciled later.
    """

    def __init__(
        self,
        out_dir: Path = DETAIL_TRAINING_DIR,
        source_interval: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.out_dir = Path(out_dir)
        self.source_interval = max(0.0, float(source_interval))
        self._clock = clock
        self._last_saved_by_source: dict[str, float] = {}
        self.saved_pairs = 0

    def save(
        self,
        unit_crop: Optional[np.ndarray],
        source: str,
        *,
        sample_id: Optional[str] = None,
    ) -> int:
        """Save a matched crop pair and return the number of image files saved."""
        now = self._clock()
        safe_source = _SAFE_SOURCE.sub("_", str(source)).strip("_") or "unit"
        last_saved = self._last_saved_by_source.get(safe_source)
        if last_saved is not None and now - last_saved < self.source_interval:
            return 0
        regions = extract_unit_detail_regions(unit_crop)
        if regions is None:
            return 0

        if sample_id:
            safe_sample_id = _SAFE_SOURCE.sub(
                "_", Path(str(sample_id)).stem
            ).strip("_")
        else:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            safe_sample_id = f"{timestamp}_{safe_source}"
        filename = f"{safe_sample_id or safe_source}.png"
        star_path = self.out_dir / "stars" / "_inbox" / filename
        item_path = self.out_dir / "items" / "_inbox" / filename
        try:
            star_path.parent.mkdir(parents=True, exist_ok=True)
            item_path.parent.mkdir(parents=True, exist_ok=True)
            star_written = cv2.imwrite(str(star_path), regions.star_badge)
            item_written = cv2.imwrite(str(item_path), regions.item_strip)
        except (OSError, cv2.error) as error:
            logger.warning("Could not save unit-detail crop pair: %s", error)
            star_written = item_written = False

        if not (star_written and item_written):
            # Keep the dataset paired if one write succeeds and the other fails.
            for path in (star_path, item_path):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Could not clean up partial detail crop: %s", path)
            return 0

        self._last_saved_by_source[safe_source] = now
        self.saved_pairs += 1
        logger.info("Unit-detail crop pair saved: %s", filename)
        return 2


def _health_bar_candidates(crop: np.ndarray) -> list[tuple[int, int, int, int]]:
    if crop is None or crop.size == 0:
        return []
    height, width = crop.shape[:2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(
        hsv,
        np.array([45, 160, 45], dtype=np.uint8),
        np.array([78, 255, 255], dtype=np.uint8),
    )
    kernel_width = max(3, width // 18)
    if kernel_width % 2 == 0:
        kernel_width += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_width, 1))
    green = cv2.morphologyEx(green, cv2.MORPH_CLOSE, kernel)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(green)
    candidates: list[tuple[int, int, int, int]] = []
    for x, y, bar_width, bar_height, area in stats[1:count]:
        if not (
            bar_width >= width * 0.22
            and 2 <= bar_height <= max(3, height * 0.14)
            and y < height * 0.65
            and bar_width / max(1, bar_height) >= 4.0
            and area >= bar_width * bar_height * 0.30
        ):
            continue
        candidates.append((int(x), int(y), int(bar_width), int(bar_height)))
    return candidates


def extract_unit_detail_regions(crop: Optional[np.ndarray]) -> Optional[UnitDetailRegions]:
    """Extract health-bar-relative regions without assuming screen resolution.

    The star marker is immediately left of the player health bar. Equipped item
    icons occupy the wider status area around and above that bar. The crops are
    deliberately generous until reviewed positive examples establish tighter
    Set 18 geometry.
    """
    if crop is None or crop.size == 0:
        return None
    candidates = _health_bar_candidates(crop)
    if not candidates:
        return None
    x, y, bar_width, bar_height = max(candidates, key=lambda box: box[2] * box[3])
    height, width = crop.shape[:2]

    star_x1 = max(0, int(round(x - bar_width * 0.35)))
    star_x2 = min(width, int(round(x + bar_width * 0.08)))
    star_y1 = max(0, int(round(y - bar_width * 0.08)))
    star_y2 = min(height, int(round(y + bar_height + bar_width * 0.16)))

    # Equipped icons sit below the health bar and may begin left of its green
    # fill. The earlier region spent most of its height above the bar and cut
    # the icons off after their first few pixels. Retain the rank frame at the
    # left plus a full icon-height below the bar.
    item_x1 = max(0, int(round(x - bar_width * 0.35)))
    item_x2 = min(width, int(round(x + bar_width * 1.08)))
    item_y1 = max(0, int(round(y - bar_width * 0.10)))
    item_y2 = min(height, int(round(y + bar_height + bar_width * 0.60)))
    if star_x2 <= star_x1 or star_y2 <= star_y1 or item_y2 <= item_y1:
        return None
    icon_size = max(1, int(round(bar_width * 0.36)))
    # Anchor below the detected green fill's bottom. Its top/height can vary
    # by a couple of pixels with compression and animation, while the lower
    # edge stays aligned with the status frame.
    icon_y = y + bar_height + int(round(bar_width * 0.095))
    icon_x_offsets = (-0.08, 0.32, 0.706)
    item_icons = [
        crop[icon_y:icon_y + icon_size, icon_x:icon_x + icon_size].copy()
        for offset in icon_x_offsets
        for icon_x in (int(round(x + bar_width * offset)),)
        if (
            icon_x >= 0
            and icon_y >= 0
            and icon_x + icon_size <= width
            and icon_y + icon_size <= height
        )
    ]
    return UnitDetailRegions(
        health_bar=(x, y, bar_width, bar_height),
        star_badge=crop[star_y1:star_y2, star_x1:star_x2].copy(),
        item_strip=crop[item_y1:item_y2, item_x1:item_x2].copy(),
        item_icons=item_icons,
    )


def extract_item_icon_slots(item_strip: Optional[np.ndarray]) -> list[np.ndarray]:
    """Split a health-bar-relative strip into its three equipped-icon slots.

    The ratios come from the 1440p Set 18 review set and scale with the strip
    height, which itself scales from the detected health-bar width. A clipped
    right edge simply omits the unavailable slot instead of matching a partial
    icon.
    """
    if item_strip is None or item_strip.size == 0:
        return []
    height, width = item_strip.shape[:2]
    size = max(1, int(round(height * 0.47)))
    x0 = int(round(height * 0.35))
    y0 = int(round(height * 0.35))
    pitch = max(1, int(round(height * 0.51)))
    if y0 + size > height:
        return []
    return [
        item_strip[y0:y0 + size, x:x + size].copy()
        for slot in range(3)
        for x in (x0 + slot * pitch,)
        if x + size <= width
    ]


def _normalized_icon_descriptor(image: np.ndarray, size: int) -> np.ndarray:
    resized = cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA)
    values = resized.astype(np.float32).reshape(-1)
    values -= float(values.mean())
    norm = float(np.linalg.norm(values))
    if norm > 1e-8:
        values /= norm
    return values


class EquippedItemTemplateMatcher:
    """Recognize each equipped icon from Riot artwork without model training."""

    def __init__(
        self,
        *,
        min_confidence: float = 0.78,
        min_margin: float = 0.10,
    ):
        self.min_confidence = float(min_confidence)
        self.min_margin = float(min_margin)
        self._template_cache: dict[
            tuple[int, tuple], tuple[list[str], np.ndarray]
        ] = {}

    @staticmethod
    def _combined_templates(
        item_templates: dict[str, np.ndarray],
        component_templates: dict[str, np.ndarray],
    ) -> dict[str, np.ndarray]:
        combined = {
            str(name): image
            for name, image in item_templates.items()
            if image is not None and image.size > 0
        }
        for component_id, image in component_templates.items():
            name = COMPONENT_NAMES.get(str(component_id), str(component_id))
            if image is not None and image.size > 0:
                combined[name] = image
        return combined

    def _template_matrix(
        self,
        templates: dict[str, np.ndarray],
        size: int,
    ) -> tuple[list[str], np.ndarray]:
        signature = tuple(
            (name, id(image), image.shape)
            for name, image in sorted(templates.items())
        )
        key = (size, signature)
        cached = self._template_cache.get(key)
        if cached is not None:
            return cached
        names = [name for name, _image in sorted(templates.items())]
        matrix = np.stack([
            _normalized_icon_descriptor(templates[name], size)
            for name in names
        ])
        self._template_cache = {key: (names, matrix)}
        return names, matrix

    def classify_item_strips(
        self,
        item_strips: list[Optional[np.ndarray]],
        *,
        item_templates: dict[str, np.ndarray],
        component_templates: dict[str, np.ndarray],
    ) -> list[list[tuple[str, float]]]:
        """Return up to three high-confidence matches per item strip."""
        return self._classify_icon_groups(
            [extract_item_icon_slots(strip) for strip in item_strips],
            item_templates=item_templates,
            component_templates=component_templates,
        )

    def _classify_icon_groups(
        self,
        icon_groups: list[list[np.ndarray]],
        *,
        item_templates: dict[str, np.ndarray],
        component_templates: dict[str, np.ndarray],
    ) -> list[list[tuple[str, float]]]:
        output: list[list[tuple[str, float]]] = [[] for _icons in icon_groups]
        templates = self._combined_templates(item_templates, component_templates)
        if not templates:
            return output

        for strip_index, icons in enumerate(icon_groups):
            for icon in icons:
                size = icon.shape[0]
                names, matrix = self._template_matrix(templates, size)
                scores = matrix @ _normalized_icon_descriptor(icon, size)
                if scores.size == 0:
                    continue
                order = np.argsort(scores)[::-1]
                best_index = int(order[0])
                confidence = float(scores[best_index])
                runner_up = float(scores[int(order[1])]) if scores.size > 1 else -1.0
                if (
                    confidence < self.min_confidence
                    or confidence - runner_up < self.min_margin
                ):
                    continue
                output[strip_index].append(
                    (names[best_index], max(0.0, min(1.0, confidence)))
                )
        return output

    def classify_batch(
        self,
        unit_crops: list[Optional[np.ndarray]],
        *,
        item_templates: dict[str, np.ndarray],
        component_templates: dict[str, np.ndarray],
    ) -> list[list[tuple[str, float]]]:
        details = [extract_unit_detail_regions(crop) for crop in unit_crops]
        return self._classify_icon_groups(
            [regions.item_icons if regions is not None else [] for regions in details],
            item_templates=item_templates,
            component_templates=component_templates,
        )


def decode_star_logits(
    logits: np.ndarray,
    labels: list[str],
    *,
    min_confidence: float,
) -> tuple[Optional[int], float]:
    values = np.asarray(logits, dtype=np.float32).reshape(-1)
    if values.size == 0 or values.size != len(labels):
        return None, 0.0
    shifted = values - float(values.max())
    probabilities = np.exp(shifted)
    probabilities /= max(float(probabilities.sum()), 1e-12)
    index = int(probabilities.argmax())
    confidence = float(probabilities[index])
    digits = "".join(character for character in str(labels[index]) if character.isdigit())
    level = int(digits) if digits else 0
    if confidence < min_confidence or level not in {1, 2, 3}:
        return None, confidence
    return level, confidence


def decode_item_logits(
    logits: np.ndarray,
    labels: list[str],
    *,
    min_confidence: float,
    max_items: int = 3,
) -> list[tuple[str, float]]:
    values = np.asarray(logits, dtype=np.float32).reshape(-1)
    if values.size == 0 or values.size != len(labels):
        return []
    probabilities = 1.0 / (1.0 + np.exp(-np.clip(values, -30.0, 30.0)))
    accepted = [
        (str(labels[index]), float(probabilities[index]))
        for index in range(len(labels))
        if not str(labels[index]).startswith("_")
        and float(probabilities[index]) >= min_confidence
    ]
    accepted.sort(key=lambda item: item[1], reverse=True)
    return accepted[:max(0, max_items)]


def detail_prediction_fields(
    star_result: tuple[Optional[int], float],
    item_results: list[tuple[str, float]],
    *,
    star_model_available: bool,
    item_model_available: bool,
    item_detection_source: str = "classifier",
) -> dict:
    """Translate accepted detail predictions into DetectedChampion fields."""
    star_level, star_confidence = star_result
    accepted_star = star_model_available and star_level in {1, 2, 3}
    return {
        "star_level": int(star_level) if accepted_star else 1,
        "star_confidence": float(star_confidence) if accepted_star else 0.0,
        "star_detection_source": "classifier" if accepted_star else "unknown",
        "items": [name for name, _confidence in item_results],
        "item_confidences": {
            name: float(confidence) for name, confidence in item_results
        },
        "item_detection_source": (
            item_detection_source if item_model_available else "unknown"
        ),
    }


class _OptionalDetailClassifier:
    task = ""

    def __init__(self, model_path: Path, meta_path: Path):
        self.available = False
        self._session = None
        self.labels: list[str] = []
        self.input_size = 96
        self.resize_mode = FULL_SPRITE_RESIZE_MODE
        self.min_confidence = 0.80
        self._mean = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
        self._std = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)
        self._input_name = "image"
        if not (model_path.exists() and meta_path.exists()):
            return
        try:
            import onnxruntime as ort
            from game_data import ACTIVE_ENGINE, ACTIVE_SET_NUMBER

            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            if (
                metadata.get("task") != self.task
                or metadata.get("set_number") != ACTIVE_SET_NUMBER
                or metadata.get("engine") != ACTIVE_ENGINE
            ):
                logger.warning("Ignoring stale or incompatible %s model", self.task)
                return
            self.labels = [str(label) for label in metadata["labels"]]
            self.input_size = int(metadata.get("input_size", 96))
            self.resize_mode = str(metadata.get("resize_mode", FULL_SPRITE_RESIZE_MODE))
            self.min_confidence = max(0.50, float(metadata.get("min_confidence", 0.80)))
            self._mean = np.array(metadata.get("mean", [0.485, 0.456, 0.406]), dtype=np.float32).reshape(3, 1, 1)
            self._std = np.array(metadata.get("std", [0.229, 0.224, 0.225]), dtype=np.float32).reshape(3, 1, 1)
            self._session = ort.InferenceSession(
                str(model_path), providers=["CPUExecutionProvider"]
            )
            self._input_name = self._session.get_inputs()[0].name
            self.available = True
            logger.info("%s classifier loaded: %d labels", self.task, len(self.labels))
        except Exception as error:
            logger.warning("Could not load %s classifier: %s", self.task, error)
            self._session = None

    def _infer(self, regions: list[Optional[np.ndarray]]) -> tuple[list[int], Optional[np.ndarray]]:
        valid = [
            index for index, region in enumerate(regions)
            if region is not None and region.size > 0
        ]
        if not self.available or not valid:
            return valid, None
        batch = preprocess(
            [regions[index] for index in valid],
            self.input_size,
            self._mean,
            self._std,
            self.resize_mode,
        )
        return valid, self._session.run(None, {self._input_name: batch})[0]


class StarLevelClassifier(_OptionalDetailClassifier):
    task = "star_level"

    def __init__(
        self,
        model_path: Path = MODELS_DIR / "star_level_classifier.onnx",
        meta_path: Path = MODELS_DIR / "star_level_classifier.json",
    ):
        super().__init__(model_path, meta_path)

    def classify_batch(
        self, unit_crops: list[Optional[np.ndarray]]
    ) -> list[tuple[Optional[int], float]]:
        output: list[tuple[Optional[int], float]] = [(None, 0.0)] * len(unit_crops)
        if not self.available:
            return output
        regions = [
            details.star_badge if details else None
            for details in (extract_unit_detail_regions(crop) for crop in unit_crops)
        ]
        valid, logits = self._infer(regions)
        if logits is None:
            return output
        for row, index in enumerate(valid):
            output[index] = decode_star_logits(
                logits[row], self.labels, min_confidence=self.min_confidence
            )
        return output


class EquippedItemClassifier(_OptionalDetailClassifier):
    task = "equipped_items"

    def __init__(
        self,
        model_path: Path = MODELS_DIR / "equipped_item_classifier.onnx",
        meta_path: Path = MODELS_DIR / "equipped_item_classifier.json",
    ):
        super().__init__(model_path, meta_path)

    def classify_batch(
        self, unit_crops: list[Optional[np.ndarray]]
    ) -> list[list[tuple[str, float]]]:
        output: list[list[tuple[str, float]]] = [[] for _crop in unit_crops]
        if not self.available:
            return output
        regions = [
            details.item_strip if details else None
            for details in (extract_unit_detail_regions(crop) for crop in unit_crops)
        ]
        valid, logits = self._infer(regions)
        if logits is None:
            return output
        for row, index in enumerate(valid):
            output[index] = decode_item_logits(
                logits[row], self.labels, min_confidence=self.min_confidence
            )
        return output
