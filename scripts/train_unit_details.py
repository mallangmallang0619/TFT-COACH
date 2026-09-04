"""Train and export the Set 18 star-level classifier.

The detail sorter creates ``stars/1``, ``stars/2``, and ``stars/3``. This
script trains a compact image classifier, calibrates a precision-oriented
acceptance threshold, and exports the ONNX/JSON files consumed by
``backend/unit_details.py``.

Examples:
    python scripts/train_unit_details.py --task stars --quick-check
    python scripts/train_unit_details.py --task stars --check
    python scripts/train_unit_details.py --task stars
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from set18_data import ENGINE, SET_NAME, SET_NUMBER  # noqa: E402
from train_classifier import (  # noqa: E402
    architecture_metadata,
    build_classifier_model,
    calibrate_confidence_threshold,
    split_dataset,
)
from unit_classifier import (  # noqa: E402
    FULL_SPRITE_RESIZE_MODE,
    resize_for_classifier,
)

STAR_LABELS = ["1", "2", "3"]
DETAILS_DIR = BACKEND_DIR / "_training" / f"set{SET_NUMBER}_details"
STAR_DATA_DIR = DETAILS_DIR / "stars"
MODELS_DIR = REPO_ROOT / "assets" / "models"
INPUT_SIZE = 96
RESIZE_MODE = FULL_SPRITE_RESIZE_MODE
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]
DEFAULT_MIN_CROPS = 50
DEFAULT_ARCHITECTURE = "mobilenet_v3_small"
SUPPORTED_ARCHITECTURES = ("mobilenet_v3_small", "efficientnet_b0")


def star_model_paths(out_dir: Path = MODELS_DIR) -> tuple[Path, Path]:
    root = Path(out_dir)
    return (
        root / "star_level_classifier.onnx",
        root / "star_level_classifier.json",
    )


def star_dataset_counts(data_dir: Path = STAR_DATA_DIR) -> dict[str, int]:
    root = Path(data_dir)
    return {
        label: sum(1 for path in (root / label).glob("*.png") if path.is_file())
        for label in STAR_LABELS
    }


def discover_star_dataset(
    data_dir: Path = STAR_DATA_DIR,
    min_crops: int = DEFAULT_MIN_CROPS,
) -> tuple[dict[str, list[Path]], dict[str, int]]:
    root = Path(data_dir)
    threshold = max(1, int(min_crops))
    usable: dict[str, list[Path]] = {}
    missing: dict[str, int] = {}
    for label in STAR_LABELS:
        paths = sorted(path for path in (root / label).glob("*.png") if path.is_file())
        if len(paths) >= threshold:
            usable[label] = paths
        else:
            missing[label] = len(paths)
    # Training is only meaningful when every required class is represented.
    if missing:
        usable = {}
    return usable, missing


def split_star_dataset(
    usable: dict[str, list[Path]],
    val_fraction: float = 0.20,
    seed: int = SET_NUMBER,
) -> tuple[list[tuple[Path, int]], list[tuple[Path, int]], list[str]]:
    return split_dataset(usable, val_fraction=val_fraction, seed=seed)


def dataset_fingerprint(usable: dict[str, list[Path]]) -> str:
    digest = hashlib.sha256()
    for label in STAR_LABELS:
        for path in sorted(usable.get(label, []), key=lambda item: item.name):
            digest.update(label.encode("utf-8"))
            digest.update(path.name.encode("utf-8"))
            try:
                digest.update(path.read_bytes())
            except OSError:
                digest.update(b"unreadable")
    return digest.hexdigest()


def build_star_metadata(
    *,
    architecture: str,
    min_confidence: float,
    val_accuracy: float,
    accepted_precision: float,
    accepted_coverage: float,
    train_count: int,
    validation_count: int,
    dataset_fingerprint: str,
) -> dict:
    return {
        **architecture_metadata(architecture),
        "task": "star_level",
        "set_number": SET_NUMBER,
        "set_name": SET_NAME,
        "engine": ENGINE,
        "labels": list(STAR_LABELS),
        "input_size": INPUT_SIZE,
        "resize_mode": RESIZE_MODE,
        "mean": IMAGENET_MEAN,
        "std": IMAGENET_STD,
        "color": "rgb",
        "min_confidence": round(float(min_confidence), 3),
        "val_accuracy": round(float(val_accuracy), 4),
        "accepted_val_precision": round(float(accepted_precision), 4),
        "accepted_val_coverage": round(float(accepted_coverage), 4),
        "num_train_crops": int(train_count),
        "num_validation_crops": int(validation_count),
        "validation_split": "capture_burst_aware",
        "dataset_fingerprint": str(dataset_fingerprint),
        "trained_at": datetime.datetime.now(datetime.timezone.utc).isoformat(
            timespec="seconds"
        ),
    }


def print_readiness(data_dir: Path, min_crops: int, *, audit: bool) -> bool:
    counts = star_dataset_counts(data_dir)
    print(f"Star-level data in {data_dir} (need >= {min_crops} per class):")
    for label in STAR_LABELS:
        state = "READY" if counts[label] >= min_crops else "waiting"
        print(f"  {state:<7} {label}-star  {counts[label]}")
    ready = all(counts[label] >= min_crops for label in STAR_LABELS)
    if audit and any(counts.values()):
        import cv2

        unreadable = []
        for label in STAR_LABELS:
            for path in (Path(data_dir) / label).glob("*.png"):
                image = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if image is None or image.size == 0:
                    unreadable.append(path)
        if unreadable:
            print(f"  unreadable {len(unreadable)} (files preserved)")
            ready = False
    if not ready:
        print("Sort more planning-phase crops before training.")
    return ready


def _require_training_dependencies() -> None:
    try:
        import onnxscript  # noqa: F401
        import torch  # noqa: F401
        import torchvision  # noqa: F401
    except ImportError as error:
        raise RuntimeError(
            "Training requires torch, torchvision, onnx, and onnxscript. "
            "Install a CUDA-enabled PyTorch build for GPU training, then run "
            "`pip install onnx onnxscript`."
        ) from error


def _training_device(torch, requested: str):
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("--device cuda requested, but CUDA is unavailable")
    if requested == "auto":
        requested = "cuda" if torch.cuda.is_available() else "cpu"
    return torch.device(requested)


def train_stars(args: argparse.Namespace) -> int:
    if not print_readiness(args.data_dir, args.min_crops, audit=True):
        return 1
    _require_training_dependencies()

    import cv2
    import numpy as np
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
    from torchvision import transforms

    usable, missing = discover_star_dataset(args.data_dir, args.min_crops)
    if missing:
        return 1
    train_items, validation_items, labels = split_star_dataset(
        usable,
        val_fraction=args.val_fraction,
        seed=args.seed,
    )
    if set(labels) != set(STAR_LABELS) or not train_items or not validation_items:
        print("Could not create populated train/validation splits.", file=sys.stderr)
        return 1

    mean = torch.tensor(IMAGENET_MEAN).view(3, 1, 1)
    std = torch.tensor(IMAGENET_STD).view(3, 1, 1)

    class StarDataset(Dataset):
        def __init__(self, items, augment: bool):
            self.items = items
            self.augment = transforms.Compose([
                transforms.RandomAffine(
                    degrees=3,
                    translate=(0.03, 0.03),
                    scale=(0.96, 1.04),
                ),
                transforms.ColorJitter(0.12, 0.10, 0.08, 0.01),
                transforms.RandomApply([transforms.GaussianBlur(3)], p=0.05),
            ]) if augment else transforms.Compose([])

        def __len__(self):
            return len(self.items)

        def __getitem__(self, index):
            path, target = self.items[index]
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                raise RuntimeError(f"Unreadable star crop: {path}")
            image = resize_for_classifier(image, INPUT_SIZE, RESIZE_MODE)
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            tensor = (
                torch.from_numpy(np.ascontiguousarray(image))
                .permute(2, 0, 1)
                .float()
                / 255.0
            )
            tensor = self.augment(tensor)
            return (tensor - mean) / std, target

    class_counts = {
        target: sum(item_target == target for _path, item_target in train_items)
        for target in range(len(labels))
    }
    weights = [1.0 / class_counts[target] for _path, target in train_items]
    sampler = WeightedRandomSampler(weights, len(train_items), replacement=True)
    train_loader = DataLoader(
        StarDataset(train_items, augment=True),
        batch_size=args.batch_size,
        sampler=sampler,
        num_workers=0,
    )
    validation_loader = DataLoader(
        StarDataset(validation_items, augment=False),
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
    )

    device = _training_device(torch, args.device)
    print(
        f"Training {len(train_items)} / validating {len(validation_items)} crops "
        f"on {device} ({args.architecture})."
    )
    if device.type == "cuda":
        print(f"CUDA device: {torch.cuda.get_device_name(device)}")

    model = build_classifier_model(args.architecture, len(labels))
    model.to(device)
    head_parameters = list(model.classifier.parameters())
    head_ids = {id(parameter) for parameter in head_parameters}
    backbone_parameters = [
        parameter for parameter in model.parameters()
        if id(parameter) not in head_ids
    ]
    optimizer = torch.optim.AdamW([
        {"params": backbone_parameters, "lr": args.lr * 0.1},
        {"params": head_parameters, "lr": args.lr},
    ], weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=args.epochs
    )
    loss_function = nn.CrossEntropyLoss(label_smoothing=0.05)

    def freeze_batch_norm(module):
        if isinstance(module, nn.modules.batchnorm._BatchNorm):
            module.eval()

    best_accuracy = -1.0
    best_state = None
    stale_epochs = 0
    for epoch in range(1, args.epochs + 1):
        model.train()
        model.apply(freeze_batch_norm)
        running_loss = 0.0
        for images, targets in train_loader:
            images, targets = images.to(device), targets.to(device)
            optimizer.zero_grad()
            loss = loss_function(model(images), targets)
            loss.backward()
            optimizer.step()
            running_loss += float(loss.item()) * images.size(0)
        scheduler.step()

        model.eval()
        correct = total = 0
        with torch.no_grad():
            for images, targets in validation_loader:
                predictions = model(images.to(device)).argmax(1).cpu()
                correct += int((predictions == targets).sum())
                total += targets.size(0)
        accuracy = correct / max(1, total)
        print(
            f"  epoch {epoch:>3}: loss {running_loss / len(train_items):.3f}, "
            f"val accuracy {accuracy:.1%}"
        )
        if accuracy > best_accuracy:
            best_accuracy = accuracy
            stale_epochs = 0
            best_state = {
                name: value.detach().cpu().clone()
                for name, value in model.state_dict().items()
            }
        else:
            stale_epochs += 1
            if stale_epochs >= args.patience:
                print(f"Early stopping after {args.patience} stale epochs.")
                break

    if best_state is None:
        print("Training produced no checkpoint.", file=sys.stderr)
        return 1
    model.load_state_dict(best_state)
    model.cpu().eval()

    confidences: list[float] = []
    correctness: list[bool] = []
    per_class = {label: [0, 0] for label in labels}
    with torch.no_grad():
        for images, targets in validation_loader:
            probabilities = torch.softmax(model(images), dim=1)
            confidence, prediction = probabilities.max(1)
            for predicted, target, score in zip(
                prediction.tolist(), targets.tolist(), confidence.tolist()
            ):
                per_class[labels[target]][1] += 1
                per_class[labels[target]][0] += int(predicted == target)
                confidences.append(score)
                correctness.append(predicted == target)
    print("Per-class validation accuracy:")
    for label in labels:
        correct, total = per_class[label]
        print(f"  {label}-star: {correct}/{total}")

    threshold, precision, coverage = calibrate_confidence_threshold(
        confidences,
        correctness,
        target_precision=args.target_precision,
        minimum=0.70,
        maximum=0.98,
        minimum_coverage=0.10,
    )
    print(
        f"Accepted threshold {threshold:.3f}: precision {precision:.1%}, "
        f"coverage {coverage:.1%}"
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    onnx_path, metadata_path = star_model_paths(args.out_dir)
    torch.onnx.export(
        model,
        (torch.zeros(1, 3, INPUT_SIZE, INPUT_SIZE),),
        str(onnx_path),
        input_names=["image"],
        output_names=["logits"],
        dynamic_shapes=({0: "batch"},),
        opset_version=18,
    )
    metadata = build_star_metadata(
        architecture=args.architecture,
        min_confidence=threshold,
        val_accuracy=best_accuracy,
        accepted_precision=precision,
        accepted_coverage=coverage,
        train_count=len(train_items),
        validation_count=len(validation_items),
        dataset_fingerprint=dataset_fingerprint(usable),
    )
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    try:
        import onnxruntime as ort

        session = ort.InferenceSession(
            str(onnx_path), providers=["CPUExecutionProvider"]
        )
        sample = torch.randn(2, 3, INPUT_SIZE, INPUT_SIZE)
        with torch.no_grad():
            torch_output = model(sample).numpy()
        onnx_output = session.run(None, {session.get_inputs()[0].name: sample.numpy()})[0]
        if not np.allclose(torch_output, onnx_output, atol=1e-3):
            print("ONNX output does not match PyTorch; model not accepted.", file=sys.stderr)
            return 1
        print("ONNX output matches PyTorch on CPU.")
    except ImportError:
        print("onnxruntime unavailable; skipped ONNX parity check.")

    print(f"Exported {onnx_path}")
    print(f"Exported {metadata_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("stars",), default="stars")
    checks = parser.add_mutually_exclusive_group()
    checks.add_argument("--quick-check", action="store_true")
    checks.add_argument("--check", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=STAR_DATA_DIR)
    parser.add_argument("--out-dir", type=Path, default=MODELS_DIR)
    parser.add_argument("--min-crops", type=int, default=DEFAULT_MIN_CROPS)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--patience", type=int, default=7)
    parser.add_argument("--val-fraction", type=float, default=0.20)
    parser.add_argument("--target-precision", type=float, default=0.95)
    parser.add_argument("--seed", type=int, default=SET_NUMBER)
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument(
        "--architecture",
        choices=SUPPORTED_ARCHITECTURES,
        default=DEFAULT_ARCHITECTURE,
    )
    args = parser.parse_args()
    if args.quick_check:
        return 0 if print_readiness(args.data_dir, args.min_crops, audit=False) else 1
    if args.check:
        return 0 if print_readiness(args.data_dir, args.min_crops, audit=True) else 1
    try:
        return train_stars(args)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
