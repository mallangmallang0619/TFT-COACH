"""
Training-Data Pack / Merge

The live harvester saves unlabeled crops to backend/_training/set18/_inbox;
the sorter moves reviewed crops into champion folders. Raw crops stay local —
only the trained model ships in the repo. When several machines collect
crops, this script moves data between them without any cloud setup:

    python scripts/training_data.py --stats            # what's collected here
    python scripts/training_data.py --pack out.zip     # zip crops to share
    python scripts/training_data.py --merge their.zip  # import someone's zip

Merging is collision-safe: files are stored per-champion with
timestamped names, and duplicates (same name) are skipped.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
from harvest import READY_CROPS_PER_CLASS, audit_training_crops  # noqa: E402
from set18_data import SET_NUMBER, canonical_training_label  # noqa: E402

TRAINING_DIR = REPO_ROOT / "backend" / "_training" / f"set{SET_NUMBER}"
RESERVED_DIRS = {"_inbox", "_rejected_manual"}


def stats() -> int:
    if not TRAINING_DIR.exists():
        print("No training data collected yet — play games with live mode running.")
        return 0
    raw_by_label: dict[str, int] = {}
    inbox_count = sum(1 for _ in (TRAINING_DIR / "_inbox").glob("*.png"))
    for champ_dir in sorted(TRAINING_DIR.iterdir()):
        if not champ_dir.is_dir():
            continue
        if champ_dir.name in RESERVED_DIRS:
            continue
        n = sum(1 for _ in champ_dir.glob("*.png"))
        if n:
            label = canonical_training_label(champ_dir.name)
            raw_by_label[label] = raw_by_label.get(label, 0) + n
    accepted, rejected = audit_training_crops(TRAINING_DIR)
    raw_total = sum(raw_by_label.values())
    clean_total = sum(len(paths) for paths in accepted.values())
    print(
        f"Training crops: {raw_total} raw / {clean_total} accepted "
        f"across {len(raw_by_label)} classes"
    )
    print(f"Manual inbox: {inbox_count} unsorted crops")
    for name in sorted(raw_by_label, key=lambda n: -raw_by_label[n]):
        clean = len(accepted.get(name, []))
        status = "READY" if clean >= READY_CROPS_PER_CLASS else "waiting"
        reason_text = ", ".join(
            f"{reason}={count}"
            for reason, count in sorted(rejected.get(name, {}).items())
        )
        suffix = f"; excluded {reason_text}" if reason_text else ""
        print(
            f"  {status:<7} {name:<18} {clean:>3}/{raw_by_label[name]:<3}{suffix}"
        )
    if raw_total:
        print()
        print("Training uses 50+ reviewed crops per champion plus _empty;")
        print(
            "effects and cross-label collisions are excluded. Share with: "
            "python scripts/training_data.py --pack crops.zip"
        )
        print("Check readiness / train:    python scripts/train_classifier.py --check")
    return 0


def pack(out_path: str) -> int:
    if not TRAINING_DIR.exists():
        print("Nothing to pack — no training data collected yet.", file=sys.stderr)
        return 1
    files = sorted(
        path for path in TRAINING_DIR.rglob("*.png")
        if path.relative_to(TRAINING_DIR).parts[0] not in RESERVED_DIRS
    )
    if not files:
        print("Nothing to pack — no crops found.", file=sys.stderr)
        return 1
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.relative_to(TRAINING_DIR))
    print(f"Packed {len(files)} crops → {out_path}")
    return 0


def merge(zip_path: str) -> int:
    src = Path(zip_path)
    if not src.exists():
        print(f"Not found: {zip_path}", file=sys.stderr)
        return 1
    added = skipped = 0
    with zipfile.ZipFile(src) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.endswith(".png"):
                continue
            rel = Path(info.filename)
            # Only accept the expected <champion>/<file>.png layout.
            if len(rel.parts) != 2 or ".." in rel.parts:
                skipped += 1
                continue
            dest = TRAINING_DIR / rel
            if dest.exists():
                skipped += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(info))
            added += 1
    print(f"Merged {added} crops (skipped {skipped} duplicates/invalid) → {TRAINING_DIR}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--stats", action="store_true", help="Show collected crop counts")
    group.add_argument("--pack", metavar="OUT.zip", help="Zip local crops for sharing")
    group.add_argument("--merge", metavar="IN.zip", help="Import crops from someone's zip")
    args = ap.parse_args()

    if args.stats:
        return stats()
    if args.pack:
        return pack(args.pack)
    return merge(args.merge)


if __name__ == "__main__":
    sys.exit(main())
