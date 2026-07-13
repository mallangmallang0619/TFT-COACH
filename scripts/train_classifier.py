"""
Unit Classifier Training — bench/board 3D-model crops -> ONNX.

Live TFT renders units as 3D models that portrait template matching can't
identify. The bench harvester (backend/harvest.py) auto-collects labeled
crops of those models into backend/_training/<champion>/ while the player
plays. This script turns those crops into the classifier that ships in
the repo — users never train, they just get assets/models/.

    python scripts/train_classifier.py --check     # is the data ready?
    python scripts/train_classifier.py             # train + export ONNX

Outputs (committed to the repo):
    assets/models/unit_classifier.onnx   the network (MobileNetV3-small)
    assets/models/unit_classifier.json   labels + preprocessing contract

The .json is the source of truth for inference preprocessing
(backend/unit_classifier.py reads input size / normalization from it),
so retraining with different settings can't silently break inference.

Class folders whose name starts with "_" (e.g. _empty) are trained as
background classes: the model learns them, but inference reports them
as "no unit".

Training dependencies (NOT needed at runtime — inference only needs
onnxruntime):
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple
    pip install onnx onnxscript   # torch's ONNX exporter needs these
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

# Legacy Windows consoles (cp1252/cp949) can't encode the punctuation below.
for _stream in (sys.stdout, sys.stderr):
    if _stream.encoding and _stream.encoding.lower() not in ("utf-8", "utf8"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = Path(__file__).resolve().parent.parent
TRAINING_DIR = REPO_ROOT / "backend" / "_training"
MODELS_DIR = REPO_ROOT / "assets" / "models"

# Preprocessing contract — written into unit_classifier.json and read back
# by backend/unit_classifier.py. Change here, retrain, and inference follows.
INPUT_SIZE = 128
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]

MIN_CROPS_DEFAULT = 20      # skip champions with fewer crops than this
VAL_FRACTION = 0.15


# ── Dataset discovery (stdlib only — importable without torch) ────────────────

def discover_dataset(
    train_dir: Path = TRAINING_DIR,
    min_crops: int = MIN_CROPS_DEFAULT,
) -> tuple[dict[str, list[Path]], dict[str, int]]:
    """
    Scan the harvester output directory.

    Returns (usable, skipped): usable maps class name -> crop paths for
    classes with >= min_crops samples; skipped maps class name -> count
    for the rest. Class names are the folder names (background classes
    keep their leading underscore).
    """
    usable: dict[str, list[Path]] = {}
    skipped: dict[str, int] = {}
    if not train_dir.exists():
        return usable, skipped
    for champ_dir in sorted(train_dir.iterdir()):
        if not champ_dir.is_dir():
            continue
        files = sorted(champ_dir.glob("*.png"))
        if len(files) >= min_crops:
            usable[champ_dir.name] = files
        elif files:
            skipped[champ_dir.name] = len(files)
    return usable, skipped


def split_dataset(
    usable: dict[str, list[Path]],
    val_fraction: float = VAL_FRACTION,
    seed: int = 17,
) -> tuple[list[tuple[Path, int]], list[tuple[Path, int]], list[str]]:
    """
    Stratified train/val split. Returns (train, val, labels) where train
    and val are (path, class_index) pairs and labels[i] is the class name
    for index i. Every class keeps at least one validation sample.
    """
    import random

    rng = random.Random(seed)
    labels = sorted(usable.keys())
    train: list[tuple[Path, int]] = []
    val: list[tuple[Path, int]] = []
    for idx, name in enumerate(labels):
        files = list(usable[name])
        rng.shuffle(files)
        n_val = max(1, round(len(files) * val_fraction))
        val.extend((f, idx) for f in files[:n_val])
        train.extend((f, idx) for f in files[n_val:])
    return train, val, labels


def print_readiness(min_crops: int, train_dir: Path = TRAINING_DIR) -> bool:
    """Report per-class readiness; returns True when training can proceed."""
    usable, skipped = discover_dataset(train_dir, min_crops)
    if not usable and not skipped:
        print(f"No training data in {train_dir} — play games with live mode running.")
        return False
    print(f"Training data in {train_dir} (need >= {min_crops} crops/champion):")
    for name in sorted(usable, key=lambda n: -len(usable[n])):
        print(f"  READY    {name:<20} {len(usable[name])}")
    for name in sorted(skipped, key=lambda n: -skipped[n]):
        print(f"  waiting  {name:<20} {skipped[name]}")
    total = sum(len(v) for v in usable.values())
    real_classes = [n for n in usable if not n.startswith("_")]
    print(f"\n{len(real_classes)} champion(s) ready, {total} usable crops.")
    if len(real_classes) < 2:
        print("Need at least 2 ready champions to train a classifier.")
        return False
    return True


# ── Training (torch imported lazily) ──────────────────────────────────────────

def _require_torch():
    try:
        import torch  # noqa: F401
        import torchvision  # noqa: F401
        import onnxscript  # noqa: F401  (torch.onnx.export dependency)
    except ImportError:
        print(
            "Training requires PyTorch + torchvision + onnxscript (runtime "
            "inference does not).\nInstall the CPU build:\n"
            "    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple\n"
            "    pip install onnx onnxscript",
            file=sys.stderr,
        )
        sys.exit(1)


def train(args: argparse.Namespace) -> int:
    if not print_readiness(args.min_crops, args.data_dir):
        return 1
    _require_torch()

    import cv2
    import numpy as np
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
    from torchvision import transforms
    from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

    usable, _ = discover_dataset(args.data_dir, args.min_crops)
    train_items, val_items, labels = split_dataset(usable)
    print(f"\nTrain {len(train_items)} / val {len(val_items)} crops, {len(labels)} classes.")

    mean_t = torch.tensor(IMAGENET_MEAN).view(3, 1, 1)
    std_t = torch.tensor(IMAGENET_STD).view(3, 1, 1)

    class CropDataset(Dataset):
        """Decodes with cv2 so training sees exactly what inference will."""

        def __init__(self, items: list[tuple[Path, int]], augment: bool):
            self.items = items
            self.aug = (
                transforms.Compose([
                    transforms.RandomResizedCrop(
                        INPUT_SIZE, scale=(0.7, 1.0), ratio=(0.75, 1.33), antialias=True
                    ),
                    transforms.RandomHorizontalFlip(),
                    transforms.ColorJitter(0.25, 0.25, 0.25, 0.04),
                ])
                if augment
                else transforms.Resize((INPUT_SIZE, INPUT_SIZE), antialias=True)
            )

        def __len__(self) -> int:
            return len(self.items)

        def __getitem__(self, i: int):
            path, label = self.items[i]
            img = cv2.imread(str(path))
            if img is None:
                raise RuntimeError(f"Unreadable crop: {path}")
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            t = torch.from_numpy(np.ascontiguousarray(rgb)).permute(2, 0, 1).float() / 255.0
            t = self.aug(t)
            return (t - mean_t) / std_t, label

    # Champions appear at very different rates (cost-1 units get bought far
    # more often) — oversample rare classes instead of letting the model
    # coast on the common ones.
    class_counts = [0] * len(labels)
    for _, lbl in train_items:
        class_counts[lbl] += 1
    weights = [1.0 / class_counts[lbl] for _, lbl in train_items]
    sampler = WeightedRandomSampler(weights, num_samples=len(train_items), replacement=True)

    train_dl = DataLoader(
        CropDataset(train_items, augment=True),
        batch_size=args.batch_size, sampler=sampler, num_workers=0,
    )
    val_dl = DataLoader(
        CropDataset(val_items, augment=False),
        batch_size=args.batch_size, shuffle=False, num_workers=0,
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.DEFAULT)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, len(labels))
    model.to(device)

    # Backbone fine-tunes at a tenth of the head's rate — the ImageNet
    # features are mostly right already, the head is random.
    head_params = list(model.classifier.parameters())
    head_ids = {id(p) for p in head_params}
    backbone_params = [p for p in model.parameters() if id(p) not in head_ids]
    opt = torch.optim.AdamW(
        [
            {"params": backbone_params, "lr": args.lr * 0.1},
            {"params": head_params, "lr": args.lr},
        ],
        weight_decay=1e-4,
    )
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
    loss_fn = nn.CrossEntropyLoss(label_smoothing=0.1)

    def _freeze_batchnorm(m: nn.Module) -> None:
        # Small dataset + big domain gap: batch statistics diverge from the
        # running statistics used at eval, so a model that fits the training
        # set can still predict uniformly at inference. Keep the ImageNet
        # running stats frozen — standard small-data fine-tuning practice.
        if isinstance(m, nn.modules.batchnorm._BatchNorm):
            m.eval()

    best_acc, best_state, stale = 0.0, None, 0
    for epoch in range(1, args.epochs + 1):
        model.train()
        model.apply(_freeze_batchnorm)
        running = 0.0
        for x, y in train_dl:
            x, y = x.to(device), y.to(device)
            opt.zero_grad()
            loss = loss_fn(model(x), y)
            loss.backward()
            opt.step()
            running += loss.item() * x.size(0)
        sched.step()

        model.eval()
        correct = total = 0
        with torch.no_grad():
            for x, y in val_dl:
                pred = model(x.to(device)).argmax(1).cpu()
                correct += int((pred == y).sum())
                total += y.size(0)
        acc = correct / max(1, total)
        print(f"  epoch {epoch:>3}: train loss {running / len(train_items):.3f}, val acc {acc:.1%}")

        if acc > best_acc:
            best_acc, stale = acc, 0
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        else:
            stale += 1
            if stale >= args.patience:
                print(f"  early stop (no val improvement in {args.patience} epochs)")
                break

    if best_state is None:
        print("Training produced no usable checkpoint.", file=sys.stderr)
        return 1
    model.load_state_dict(best_state)
    model.cpu().eval()

    # Per-class validation accuracy — the readiness signal for shipping —
    # and the confidence gate, calibrated so ~95% of correct validation
    # predictions pass it (a fixed threshold misjudges how confident a
    # label-smoothed model actually is).
    per_class = {name: [0, 0] for name in labels}
    correct_confs: list[float] = []
    with torch.no_grad():
        for x, y in val_dl:
            probs = torch.softmax(model(x), dim=1)
            conf, pred = probs.max(1)
            for p, t, c in zip(pred.tolist(), y.tolist(), conf.tolist()):
                per_class[labels[t]][1] += 1
                per_class[labels[t]][0] += int(p == t)
                if p == t:
                    correct_confs.append(c)
    print("\nPer-class val accuracy:")
    for name, (c, n) in sorted(per_class.items()):
        print(f"  {name:<20} {c}/{n}")

    min_confidence = float(np.clip(np.percentile(correct_confs, 5), 0.35, 0.75))
    print(f"Calibrated min confidence: {min_confidence:.3f}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = args.out_dir / "unit_classifier.onnx"
    meta_path = args.out_dir / "unit_classifier.json"
    torch.onnx.export(
        model,
        (torch.zeros(1, 3, INPUT_SIZE, INPUT_SIZE),),
        str(onnx_path),
        input_names=["image"],
        output_names=["logits"],
        dynamic_shapes=({0: "batch"},),
        opset_version=18,
    )
    meta = {
        "labels": labels,
        "input_size": INPUT_SIZE,
        "mean": IMAGENET_MEAN,
        "std": IMAGENET_STD,
        "color": "rgb",
        "min_confidence": round(min_confidence, 3),
        "val_accuracy": round(best_acc, 4),
        "num_train_crops": len(train_items),
        "trained_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nExported {onnx_path.name} + {meta_path.name} (best val acc {best_acc:.1%})")

    # Sanity-check the export against the torch model when onnxruntime is here.
    try:
        import onnxruntime as ort

        sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
        x = torch.randn(2, 3, INPUT_SIZE, INPUT_SIZE)
        with torch.no_grad():
            ref = model(x).numpy()
        out = sess.run(None, {"image": x.numpy()})[0]
        if np.allclose(ref, out, atol=1e-3):
            print("ONNX output matches torch (verified with onnxruntime).")
        else:
            print("WARNING: ONNX output diverges from torch — do not ship this model.",
                  file=sys.stderr)
            return 1
    except ImportError:
        print("onnxruntime not installed — skipping export verification.")

    print("\nCommit assets/models/ so users get the classifier without training.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="Report data readiness and exit (no torch needed)")
    ap.add_argument("--min-crops", type=int, default=MIN_CROPS_DEFAULT,
                    help=f"Skip champions with fewer crops (default {MIN_CROPS_DEFAULT})")
    ap.add_argument("--data-dir", type=Path, default=TRAINING_DIR,
                    help=f"Crop directory (default {TRAINING_DIR})")
    ap.add_argument("--out-dir", type=Path, default=MODELS_DIR,
                    help=f"Where to write the .onnx + .json (default {MODELS_DIR})")
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--patience", type=int, default=8,
                    help="Early-stop after this many epochs without val improvement")
    args = ap.parse_args()

    if args.check:
        return 0 if print_readiness(args.min_crops, args.data_dir) else 1
    return train(args)


if __name__ == "__main__":
    sys.exit(main())
