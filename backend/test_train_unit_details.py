"""Tests for the star-level training pipeline without importing PyTorch."""

from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from train_unit_details import (  # noqa: E402
    STAR_LABELS,
    build_star_metadata,
    discover_star_dataset,
    split_star_dataset,
    star_dataset_counts,
    star_model_paths,
)


def _touch_samples(directory: Path, label: str, timestamps: list[str]) -> list[Path]:
    paths = []
    for timestamp in timestamps:
        path = directory / label / f"{timestamp}_board_r1_c2_i9.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"sample")
        paths.append(path)
    return paths


class StarTrainingPipelineTests(unittest.TestCase):
    def test_dataset_uses_only_the_three_reviewed_star_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _touch_samples(root, "1", ["20260901_120000_000001"])
            _touch_samples(root, "2", ["20260901_120001_000001"])
            _touch_samples(root, "3", ["20260901_120002_000001"])
            _touch_samples(root, "_inbox", ["20260901_120003_000001"])
            (root / "other").mkdir()

            self.assertEqual(star_dataset_counts(root), {"1": 1, "2": 1, "3": 1})
            usable, missing = discover_star_dataset(root, min_crops=1)
            self.assertEqual(list(usable), STAR_LABELS)
            self.assertEqual(missing, {})

    def test_dataset_reports_every_underfilled_required_class(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _touch_samples(root, "1", ["20260901_120000_000001"])
            usable, missing = discover_star_dataset(root, min_crops=2)
            self.assertEqual(usable, {})
            self.assertEqual(missing, {"1": 1, "2": 0, "3": 0})

    def test_split_keeps_capture_sessions_out_of_both_sides(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = {}
            for label in STAR_LABELS:
                samples[label] = _touch_samples(root, label, [
                    "20260901_120000_000001",
                    "20260901_120020_000001",
                    "20260902_120000_000001",
                    "20260902_120020_000001",
                ])

            train, validation, labels = split_star_dataset(samples, val_fraction=0.5)

            self.assertEqual(labels, STAR_LABELS)
            train_days = {(path.name[:8], target) for path, target in train}
            validation_days = {(path.name[:8], target) for path, target in validation}
            self.assertTrue(train_days.isdisjoint(validation_days))
            self.assertEqual({target for _path, target in train}, {0, 1, 2})
            self.assertEqual({target for _path, target in validation}, {0, 1, 2})

    def test_metadata_matches_the_runtime_loader_contract(self):
        metadata = build_star_metadata(
            architecture="mobilenet_v3_small",
            min_confidence=0.82,
            val_accuracy=0.91,
            accepted_precision=0.96,
            accepted_coverage=0.74,
            train_count=240,
            validation_count=60,
            dataset_fingerprint="abc123",
        )
        self.assertEqual(metadata["task"], "star_level")
        self.assertEqual(metadata["labels"], STAR_LABELS)
        self.assertEqual(metadata["input_size"], 96)
        self.assertEqual(metadata["min_confidence"], 0.82)
        self.assertEqual(metadata["dataset_fingerprint"], "abc123")

    def test_export_paths_cannot_overwrite_the_champion_model(self):
        with tempfile.TemporaryDirectory() as directory:
            onnx_path, metadata_path = star_model_paths(Path(directory))
            self.assertEqual(onnx_path.name, "star_level_classifier.onnx")
            self.assertEqual(metadata_path.name, "star_level_classifier.json")


if __name__ == "__main__":
    unittest.main()
