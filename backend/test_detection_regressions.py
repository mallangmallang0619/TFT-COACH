"""Item aliases and changed trait-panel observations."""
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from detector import Detector
from unit_details import EquippedItemTemplateMatcher


class ItemAliasTests(unittest.TestCase):
    def test_aliases_do_not_compete_with_the_same_item(self):
        icon = np.random.default_rng(18).integers(0, 256, (31, 31, 3), dtype=np.uint8)
        matcher = EquippedItemTemplateMatcher()
        result = matcher._classify_icon_groups(
            [[icon]], item_templates={"Warmogs Armor": icon.copy(), "Warmog's Armor": icon},
            component_templates={},
        )
        self.assertEqual([name for name, _ in result[0]], ["Warmog's Armor"])

    def test_distinct_radiant_item_still_requires_margin(self):
        icon = np.random.default_rng(19).integers(0, 256, (31, 31, 3), dtype=np.uint8)
        result = EquippedItemTemplateMatcher()._classify_icon_groups(
            [[icon]], item_templates={"Warmog's Armor": icon, "Radiant Warmog's Armor": icon.copy()},
            component_templates={},
        )
        self.assertEqual(result, [[]])


class TraitPanelTests(unittest.TestCase):
    def test_explicit_inactive_progress_wins_over_plausible_wrong_badge(self):
        d = object.__new__(Detector)
        d._ocr_region = Mock(return_value="5")
        data = {"text": ["Elderwood", "2/3"], "left": [384, 370],
                "top": [560, 610], "width": [140, 55], "height": [32, 28]}
        with patch("detector.pytesseract.image_to_data", return_value=data):
            rows = d._read_trait_panel_text(np.zeros((1440, 2560, 3), dtype=np.uint8))
        self.assertEqual(rows[0][:2], ("Elderwood", 2))
        d._ocr_region.assert_not_called()

    def test_active_progress_is_not_mistaken_for_inactive_first_tier(self):
        d = object.__new__(Detector)
        d._ocr_region = Mock(return_value="3")
        data = {"text": ["Elderwood", "3/5"], "left": [384, 370],
                "top": [560, 610], "width": [140, 55], "height": [32, 28]}
        with patch("detector.pytesseract.image_to_data", return_value=data):
            rows = d._read_trait_panel_text(np.zeros((1440, 2560, 3), dtype=np.uint8))
        self.assertEqual(rows[0][:2], ("Elderwood", 3))

    def test_changed_count_invalidates_cached_active_trait(self):
        d = object.__new__(Detector)
        d._trait_cache = None
        d._trait_cache_age = 0
        d._trait_rows_cache = None
        d._trait_rows_age = 0
        d._read_trait_panel_text = Mock(side_effect=[[("Elderwood", 3, .45)], [("Elderwood", 2, .45)]])
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.assertTrue(d._synergies_from_trait_panel(frame))
        d._synergies_from_trait_panel(frame)
        self.assertEqual(d._read_trait_panel_text.call_count, 1)
        frame[400:450, 600:650] = 255
        d._synergies_from_trait_panel(frame)
        self.assertEqual(d._read_trait_panel_text.call_count, 1)
        frame[320:330, 79:85] = 255
        self.assertEqual(d._synergies_from_trait_panel(frame), [])
        self.assertEqual(d._read_trait_panel_text.call_count, 2)

    def test_latest_local_elderwood_diagnosis(self):
        path = Path(__file__).parent / "_debug/diagnose_20260906_011432.png"
        if not path.exists():
            self.skipTest("local diagnostic is not bundled")
        d = object.__new__(Detector)
        rows = d._read_trait_panel_text(cv2.imread(str(path)))
        counts = {name: count for name, count, _ in rows}
        self.assertEqual(counts["Elderwood"], 2)
        for name in ("Defender", "Juggernaut", "Spellweaver"):
            self.assertEqual(counts[name], 2)


if __name__ == "__main__":
    unittest.main()
