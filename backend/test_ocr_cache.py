"""Behavioral tests for change-triggered HUD OCR."""
import unittest
from unittest.mock import Mock

import numpy as np

from config import GameROIs
from detector import Detector


class OCRCacheTests(unittest.TestCase):
    def setUp(self):
        self.detector = object.__new__(Detector)
        d = self.detector
        d.rois = GameROIs()
        d._hud_layout_cache = "standard"
        d._gold_cache = -1
        d._components_cache = []
        d._shop_cache = ([None] * 5, [None] * 5)
        d._stage_cache = ("?", 0.0)
        d._player_hp_cache = d._level_cache = -1
        for name in ("gold", "components", "shop", "stage", "player_hp", "level"):
            setattr(d, f"_{name}_cache_age", 1000000)
        d._ocr_gold = Mock(return_value=40)
        d._detect_shop = Mock(return_value=(["Kayle"] * 5, [None] * 5))
        d._detect_components = Mock(return_value=[])
        d._ocr_stage = Mock(return_value=("3-2", .9))
        d._ocr_player_hp = Mock(return_value=80)
        d._ocr_level_and_layout = Mock(return_value=(6, "standard"))
        self.frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    def read(self):
        self.detector._read_cached_hud(self.frame)
        return self.detector._read_cached_live_ui(self.frame)

    def test_unchanged_frames_skip_ocr_but_eventually_refresh(self):
        for _ in range(10):
            self.read()
        for name in ("_ocr_gold", "_detect_shop", "_ocr_stage", "_ocr_player_hp", "_ocr_level_and_layout"):
            self.assertEqual(getattr(self.detector, name).call_count, 1, name)
        for _ in range(30):
            self.read()
        self.assertGreater(self.detector._ocr_gold.call_count, 1)
        self.assertGreater(self.detector._ocr_level_and_layout.call_count, 1)

    def test_purchase_refreshes_gold_and_shop_together_immediately(self):
        self.read()
        d = self.detector
        x, y, w, h = d.rois.gold_standard.to_pixels(1280, 720)
        self.frame[y:y+h, x:x+w] = 255
        d._ocr_gold.return_value = 37
        d._detect_shop.return_value = ([None] + ["Kayle"] * 4, [None] * 5)
        result = self.read()
        self.assertEqual(result[0], 37)
        self.assertIsNone(result[2][0][0])
        self.assertEqual(d._ocr_gold.call_count, 2)
        self.assertEqual(d._detect_shop.call_count, 2)

    def test_board_animation_does_not_trigger_hud_ocr(self):
        self.read()
        self.frame[300:400, 500:700] = 255
        for _ in range(4):
            self.read()
        self.assertEqual(self.detector._ocr_gold.call_count, 1)
        self.assertEqual(self.detector._detect_shop.call_count, 1)

    def test_failed_read_retries_at_original_interval(self):
        self.detector._ocr_gold.side_effect = [-1, 40]
        self.read()
        self.read()
        self.read()
        self.assertEqual(self.detector._gold_cache, 40)
        self.assertEqual(self.detector._ocr_gold.call_count, 2)

    def test_repeated_failures_do_not_create_busy_retry_loop(self):
        self.detector._ocr_gold.return_value = -1
        for _ in range(10):
            self.read()
        self.assertEqual(self.detector._ocr_gold.call_count, 5)

    def test_phase_and_resolution_changes_force_refresh(self):
        self.read()
        self.detector._read_cached_live_ui(self.frame, phase_changed=True)
        self.assertEqual(self.detector._ocr_gold.call_count, 2)
        self.frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        self.read()
        self.assertEqual(self.detector._ocr_gold.call_count, 3)

    def test_shop_text_change_refreshes_economy_even_with_same_gold(self):
        from config import ShopGeometry
        self.read()
        g = ShopGeometry()
        x, y = int(g.cards_x0 * 1280), int(g.name_y0 * 720)
        self.frame[y:y+3, x:x+2] = 220
        self.detector._detect_shop.return_value = (["Lux"] * 5, [None] * 5)
        self.read()
        self.assertEqual(self.detector._shop_cache[0][0], "Lux")
        self.assertEqual(self.detector._ocr_gold.call_count, 2)

    def test_tiny_noise_waits_for_periodic_audit(self):
        self.read()
        self.frame[:] = 2
        self.read()
        self.assertEqual(self.detector._ocr_gold.call_count, 1)

    def test_disabled_shop_and_layout_change(self):
        self.read()
        self.detector._hud_layout_cache = "trials"
        self.detector._read_cached_live_ui(self.frame, include_shop=False)
        self.assertEqual(self.detector._ocr_gold.call_count, 2)
        self.assertEqual(self.detector._detect_shop.call_count, 1)
        self.detector._read_cached_live_ui(self.frame, include_shop=True)
        self.assertEqual(self.detector._detect_shop.call_count, 2)

    def test_stage_text_change_refreshes_before_old_deadline(self):
        self.read()
        x, y, w, h = self.detector.rois.stage.to_pixels(1280, 720)
        self.frame[y:y+h, x:x+w] = 255
        self.detector._ocr_stage.return_value = ("3-3", .9)
        self.read()
        self.assertEqual(self.detector._stage_cache[0], "3-3")
        self.assertEqual(self.detector._ocr_stage.call_count, 2)

    def test_failed_gold_after_valid_read_retries_without_losing_value(self):
        self.read()
        self.detector._ocr_gold.side_effect = [-1, 35]
        self.detector._read_cached_live_ui(self.frame, phase_changed=True)
        self.assertEqual(self.detector._gold_cache, 40)
        self.read()
        self.read()
        self.assertEqual(self.detector._gold_cache, 35)


if __name__ == "__main__":
    unittest.main()
