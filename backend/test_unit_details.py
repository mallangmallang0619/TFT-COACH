"""Focused tests for star-level and equipped-item classifier foundations."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from game_state import DetectedChampion
from config import GameROIs
from detector import Detector
from unit_details import (
    EquippedItemTemplateMatcher,
    EquippedItemClassifier,
    StarLevelClassifier,
    UnitDetailCollector,
    unit_detail_collection_enabled,
    detail_prediction_fields,
    decode_item_logits,
    decode_star_logits,
    extract_item_icon_slots,
    extract_unit_detail_regions,
)


class UnitDetailRegionTests(unittest.TestCase):
    def test_health_bar_relative_regions_include_badge_and_item_area(self):
        crop = np.zeros((180, 120, 3), dtype=np.uint8)
        # Player health bar, plus a bronze-colored badge immediately left.
        cv2.rectangle(crop, (30, 40), (89, 44), (0, 255, 0), -1)
        cv2.rectangle(crop, (12, 37), (27, 53), (40, 105, 170), -1)
        # Two equipped-item icons extend well below the bar. The item crop
        # must retain their complete height, not only their top few pixels.
        cv2.rectangle(crop, (30, 50), (49, 80), (20, 20, 230), -1)
        cv2.rectangle(crop, (50, 50), (69, 80), (230, 80, 20), -1)
        regions = extract_unit_detail_regions(crop)

        self.assertIsNotNone(regions)
        self.assertEqual(regions.health_bar, (30, 40, 60, 5))
        self.assertGreater(regions.star_badge.size, 0)
        self.assertGreater(regions.item_strip.size, 0)
        # The left badge must be retained rather than cropped off at bar x=30.
        self.assertTrue(np.any(regions.star_badge[:, :, 2] > 100))
        self.assertTrue(np.any(regions.item_strip[:, :, 2] > 200))
        self.assertTrue(np.any(regions.item_strip[:, :, 0] > 200))
        self.assertGreaterEqual(regions.item_strip.shape[0], 45)
        self.assertGreaterEqual(regions.item_strip.shape[1], 80)
        self.assertEqual(len(regions.item_icons), 3)
        self.assertTrue(np.any(regions.item_icons[0][:, :, 2] > 200))
        self.assertTrue(np.any(regions.item_icons[1][:, :, 0] > 200))

    def test_no_health_bar_abstains_from_detail_extraction(self):
        crop = np.full((180, 120, 3), 80, dtype=np.uint8)
        self.assertIsNone(extract_unit_detail_regions(crop))


class UnitDetailDecodeTests(unittest.TestCase):
    def test_star_decoder_uses_softmax_confidence_and_valid_levels(self):
        level, confidence = decode_star_logits(
            np.array([0.0, 4.0, 1.0], dtype=np.float32),
            ["1", "2", "3"],
            min_confidence=0.80,
        )
        self.assertEqual(level, 2)
        self.assertGreater(confidence, 0.90)
        self.assertEqual(
            decode_star_logits(
                np.array([1.0, 1.0, 1.0], dtype=np.float32),
                ["1", "2", "3"],
                min_confidence=0.80,
            )[0],
            None,
        )

    def test_item_decoder_is_multilabel_bounded_and_thresholded(self):
        items = decode_item_logits(
            np.array([4.0, -3.0, 2.0, 1.0], dtype=np.float32),
            ["Deathblade", "Sunfire Cape", "Jeweled Gauntlet", "Warmog's Armor"],
            min_confidence=0.75,
            max_items=3,
        )
        self.assertEqual([name for name, _confidence in items], [
            "Deathblade",
            "Jeweled Gauntlet",
        ])

    def test_detail_predictions_expose_only_accepted_observations(self):
        self.assertEqual(
            detail_prediction_fields(
                (2, 0.94),
                [("Deathblade", 0.91), ("Guardbreaker", 0.82)],
                star_model_available=True,
                item_model_available=True,
            ),
            {
                "star_level": 2,
                "star_confidence": 0.94,
                "star_detection_source": "classifier",
                "items": ["Deathblade", "Guardbreaker"],
                "item_confidences": {"Deathblade": 0.91, "Guardbreaker": 0.82},
                "item_detection_source": "classifier",
            },
        )
        self.assertEqual(
            detail_prediction_fields(
                (None, 0.45), [],
                star_model_available=True,
                item_model_available=False,
            )["star_detection_source"],
            "unknown",
        )


class EquippedItemTemplateTests(unittest.TestCase):
    def test_item_strip_is_split_into_three_complete_icon_slots(self):
        strip = np.zeros((66, 122, 3), dtype=np.uint8)
        for index, value in enumerate((60, 130, 220)):
            x = 23 + index * 34
            strip[23:54, x:x + 31] = value

        slots = extract_item_icon_slots(strip)

        self.assertEqual(len(slots), 3)
        self.assertEqual([slot.shape for slot in slots], [(31, 31, 3)] * 3)
        self.assertEqual([int(slot.mean()) for slot in slots], [60, 130, 220])

    def test_matcher_recognizes_each_icon_independently_and_ignores_empty(self):
        component = cv2.imread(str(
            Path(__file__).parent.parent / "assets" / "templates" /
            "components" / "bf_sword.png"
        ))
        completed = cv2.imread(str(
            Path(__file__).parent.parent / "assets" / "templates" /
            "items" / "Red Buff.png"
        ))
        self.assertIsNotNone(component)
        self.assertIsNotNone(completed)

        strip = np.full((66, 122, 3), 45, dtype=np.uint8)
        strip[23:54, 23:54] = cv2.resize(component, (31, 31))
        strip[23:54, 57:88] = cv2.resize(completed, (31, 31))
        matcher = EquippedItemTemplateMatcher(min_confidence=0.75)

        results = matcher.classify_item_strips(
            [strip],
            item_templates={"Red Buff": completed},
            component_templates={"bf_sword": component},
        )

        self.assertEqual([name for name, _confidence in results[0]], [
            "B.F. Sword",
            "Red Buff",
        ])

    def test_matcher_abstains_when_two_templates_are_indistinguishable(self):
        icon = np.random.default_rng(18).integers(
            0, 256, (31, 31, 3), dtype=np.uint8
        )
        strip = np.full((66, 122, 3), 45, dtype=np.uint8)
        strip[23:54, 23:54] = icon
        matcher = EquippedItemTemplateMatcher(
            min_confidence=0.75, min_margin=0.10
        )

        results = matcher.classify_item_strips(
            [strip],
            item_templates={"Item A": icon, "Item B": icon.copy()},
            component_templates={},
        )

        self.assertEqual(results, [[]])


class OptionalModelTests(unittest.TestCase):
    def test_missing_models_are_safe_noops(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stars = StarLevelClassifier(
                model_path=root / "missing.onnx",
                meta_path=root / "missing.json",
            )
            items = EquippedItemClassifier(
                model_path=root / "missing-items.onnx",
                meta_path=root / "missing-items.json",
            )
            crop = np.zeros((20, 20, 3), dtype=np.uint8)
            self.assertFalse(stars.available)
            self.assertFalse(items.available)
            self.assertEqual(stars.classify_batch([crop]), [(None, 0.0)])
            self.assertEqual(items.classify_batch([crop]), [[]])

    def test_champion_schema_exposes_detail_confidence_and_provenance(self):
        champion = DetectedChampion(name="Lux")
        self.assertEqual(champion.star_level, 1)
        self.assertEqual(champion.star_confidence, 0.0)
        self.assertEqual(champion.star_detection_source, "unknown")
        self.assertEqual(champion.item_confidences, {})
        self.assertEqual(champion.item_detection_source, "unknown")

    def test_detail_models_are_skipped_when_planning_details_are_disabled(self):
        class UnitClassifierStub:
            board_crop_mode = "legacy_hex_v1"
            board_min_confidence = 0.08
            min_confidence = 0.35

            def classify_batch(self, crops, min_confidences=None):
                return [(None, 0.0)] * len(crops)

        class DetailClassifierStub:
            available = True

            def __init__(self, output):
                self.output = output
                self.calls = 0

            def classify_batch(self, crops):
                self.calls += 1
                return [self.output for _crop in crops]

        detector = object.__new__(Detector)
        detector.rois = GameROIs()
        detector.unit_classifier = UnitClassifierStub()
        detector.stabilize_unit_predictions = False
        detector.star_level_classifier = DetailClassifierStub((None, 0.0))
        detector.equipped_item_classifier = DetailClassifierStub([])
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        detector._detect_units_cnn(frame, include_details=False)

        self.assertEqual(detector.star_level_classifier.calls, 0)
        self.assertEqual(detector.equipped_item_classifier.calls, 0)

        detector._detect_units_cnn(frame, include_details=True)

        self.assertEqual(detector.star_level_classifier.calls, 1)
        self.assertEqual(detector.equipped_item_classifier.calls, 1)

    def test_live_detection_prefers_item_templates_over_optional_model(self):
        class UnitClassifierStub:
            board_crop_mode = "legacy_hex_v1"
            board_min_confidence = 0.08
            min_confidence = 0.35

            @staticmethod
            def classify_batch(crops, min_confidences=None):
                return [
                    ("Kayle", 0.91) if index == 0 else (None, 0.0)
                    for index, _crop in enumerate(crops)
                ]

        class MatcherStub:
            calls = 0

            def classify_batch(self, crops, **_templates):
                self.calls += 1
                return [
                    [("Red Buff", 0.96)] if index == 0 else []
                    for index, _crop in enumerate(crops)
                ]

        class ModelStub:
            available = True
            calls = 0

            def classify_batch(self, crops):
                self.calls += 1
                return [[] for _crop in crops]

        detector = object.__new__(Detector)
        detector.rois = GameROIs()
        detector.unit_classifier = UnitClassifierStub()
        detector.stabilize_unit_predictions = False
        detector.star_level_classifier = None
        detector.equipped_item_matcher = MatcherStub()
        detector.equipped_item_classifier = ModelStub()
        icon = np.ones((16, 16, 3), dtype=np.uint8)
        detector.templates = SimpleNamespace(
            item_templates={"Red Buff": icon},
            component_templates={},
        )

        board, _bench = detector._detect_units_cnn(
            np.zeros((720, 1280, 3), dtype=np.uint8),
            include_details=True,
        )

        self.assertEqual(detector.equipped_item_matcher.calls, 1)
        self.assertEqual(detector.equipped_item_classifier.calls, 0)
        self.assertEqual(board[0].items, ["Red Buff"])
        self.assertEqual(board[0].item_detection_source, "template")


class UnitDetailCollectorTests(unittest.TestCase):
    def test_collector_saves_paired_unlabeled_regions_with_a_cooldown(self):
        now = [100.0]
        crop = np.zeros((180, 120, 3), dtype=np.uint8)
        cv2.rectangle(crop, (30, 40), (89, 44), (0, 255, 0), -1)
        with tempfile.TemporaryDirectory() as directory:
            collector = UnitDetailCollector(
                out_dir=Path(directory),
                source_interval=30.0,
                clock=lambda: now[0],
            )
            self.assertEqual(collector.save(crop, "board_r1_c2_i9"), 2)
            self.assertEqual(collector.save(crop, "board_r1_c2_i9"), 0)
            now[0] += 31.0
            self.assertEqual(collector.save(crop, "board_r1_c2_i9"), 2)
            self.assertEqual(len(list((Path(directory) / "stars" / "_inbox").glob("*.png"))), 2)
            self.assertEqual(len(list((Path(directory) / "items" / "_inbox").glob("*.png"))), 2)

    def test_collector_can_reuse_the_full_champion_crop_sample_id(self):
        crop = np.zeros((180, 120, 3), dtype=np.uint8)
        cv2.rectangle(crop, (30, 40), (89, 44), (0, 255, 0), -1)
        with tempfile.TemporaryDirectory() as directory:
            collector = UnitDetailCollector(out_dir=Path(directory))
            self.assertEqual(
                collector.save(
                    crop,
                    "board_r1_c2_i9",
                    sample_id="20260903_120000_123456_board_r1_c2_i9",
                ),
                2,
            )
            self.assertTrue(
                (Path(directory) / "stars" / "_inbox" /
                 "20260903_120000_123456_board_r1_c2_i9.png").exists()
            )

    def test_detail_collection_defaults_on_but_has_an_explicit_off_switch(self):
        self.assertTrue(unit_detail_collection_enabled(None))
        self.assertTrue(unit_detail_collection_enabled(""))
        self.assertTrue(unit_detail_collection_enabled("1"))
        self.assertFalse(unit_detail_collection_enabled("0"))
        self.assertFalse(unit_detail_collection_enabled("false"))

    def test_collector_rejects_crops_without_a_health_bar(self):
        with tempfile.TemporaryDirectory() as directory:
            collector = UnitDetailCollector(out_dir=Path(directory))
            self.assertEqual(
                collector.save(np.zeros((180, 120, 3), dtype=np.uint8), "bench_slot2"),
                0,
            )


if __name__ == "__main__":
    unittest.main()
