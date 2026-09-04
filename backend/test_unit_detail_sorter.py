"""Tests for recoverable star-level and equipped-item labeling."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from sort_unit_details import (  # noqa: E402
    available_item_labels,
    _detail_batch,
    find_champion_companion,
    label_item_crop,
    load_item_labels,
    move_star_crop,
    reject_detail_crop,
    restore_detail_crop,
    undo_item_label,
)


def _png(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"png")
    return path


class DetailSorterTests(unittest.TestCase):
    def test_star_label_and_reject_are_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inbox = root / "stars" / "_inbox"
            source = _png(inbox / "sample.png")

            labeled = move_star_crop(source, 2, root)
            self.assertEqual(labeled.parent.name, "2")
            self.assertFalse(source.exists())
            restored = restore_detail_crop(labeled, inbox)
            self.assertTrue(restored.exists())

            rejected = reject_detail_crop(restored, root / "stars" / "_rejected")
            self.assertTrue(rejected.exists())
            self.assertTrue(restore_detail_crop(rejected, inbox).exists())

    def test_invalid_star_level_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = _png(Path(directory) / "stars" / "_inbox" / "sample.png")
            with self.assertRaises(ValueError):
                move_star_crop(source, 4, Path(directory))

    def test_item_labels_are_multilabel_and_undo_restores_the_crop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _png(root / "items" / "_inbox" / "sample.png")
            companion = _png(root / "units" / "Lux" / "sample.png")

            labeled = label_item_crop(
                source,
                ["Deathblade", "Infinity Edge"],
                root,
                champion_training_dir=root / "units",
                allowed_labels={"Deathblade", "Infinity Edge", "Warmog's Armor"},
            )

            labels = load_item_labels(root / "items" / "labels.json")
            self.assertEqual(labels["sample.png"]["items"], [
                "Deathblade",
                "Infinity Edge",
            ])
            self.assertEqual(labels["sample.png"]["champion"], "Lux")
            self.assertEqual(labels["sample.png"]["champion_crop"], str(companion))
            restored = undo_item_label(labeled, root)
            self.assertTrue(restored.exists())
            self.assertNotIn(
                "sample.png",
                load_item_labels(root / "items" / "labels.json"),
            )

    def test_no_items_is_a_valid_label_but_more_than_three_is_not(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _png(root / "items" / "_inbox" / "empty.png")
            label_item_crop(source, [], root, allowed_labels={"A", "B", "C", "D"})
            self.assertEqual(
                load_item_labels(root / "items" / "labels.json")["empty.png"]["items"],
                [],
            )
            too_many = _png(root / "items" / "_inbox" / "many.png")
            with self.assertRaises(ValueError):
                label_item_crop(
                    too_many,
                    ["A", "B", "C", "D"],
                    root,
                    allowed_labels={"A", "B", "C", "D"},
                )

    def test_matching_champion_crop_is_found_after_manual_sorting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = _png(root / "Yorick" / "sample.png")
            _png(root / "_rejected_manual" / "other.png")
            self.assertEqual(find_champion_companion("sample.png", root), expected)
            self.assertIsNone(find_champion_companion("missing.png", root))

    def test_item_catalog_combines_static_and_cached_special_items(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            cache.write_text(json.dumps({
                "items": {"entries": [
                    {"name": "Aegis of Dawn", "kind": "artifact"},
                    {"name": "Radiant Deathblade", "kind": "radiant"},
                ]}
            }), encoding="utf-8")
            labels = available_item_labels(cache)
            self.assertIn("Deathblade", labels)
            self.assertIn("B.F. Sword", labels)
            self.assertIn("Aegis of Dawn", labels)
            self.assertIn("Radiant Deathblade", labels)

    def test_visual_batch_keeps_similar_crops_and_excludes_different_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "current.png"
            similar = root / "similar.png"
            different = root / "different.png"
            cv2.imwrite(str(current), np.full((40, 60, 3), 30, dtype=np.uint8))
            cv2.imwrite(str(similar), np.full((40, 60, 3), 32, dtype=np.uint8))
            cv2.imwrite(str(different), np.full((40, 60, 3), 240, dtype=np.uint8))

            batch = _detail_batch(current, [current, similar, different])

            self.assertEqual(batch, [current, similar])


if __name__ == "__main__":
    unittest.main()
