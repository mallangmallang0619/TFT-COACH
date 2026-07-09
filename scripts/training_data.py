"""
Training-Data Pack / Merge

The bench-crop harvester saves labeled unit crops to backend/_training/
on whatever machine runs live mode. Raw crops stay local (gitignored) —
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
TRAINING_DIR = REPO_ROOT / "backend" / "_training"


def stats() -> int:
    if not TRAINING_DIR.exists():
        print("No training data collected yet — play games with live mode running.")
        return 0
    total = 0
    rows = []
    for champ_dir in sorted(TRAINING_DIR.iterdir()):
        if not champ_dir.is_dir():
            continue
        n = sum(1 for _ in champ_dir.glob("*.png"))
        total += n
        rows.append((champ_dir.name, n))
    print(f"Training crops: {total} across {len(rows)} champions")
    for name, n in sorted(rows, key=lambda r: -r[1]):
        print(f"  {name:<20} {n}")
    if total:
        print()
        print("Rule of thumb: ~50+ crops per champion trains a usable classifier;")
        print("more is better. Share with: python scripts/training_data.py --pack crops.zip")
    return 0


def pack(out_path: str) -> int:
    if not TRAINING_DIR.exists():
        print("Nothing to pack — no training data collected yet.", file=sys.stderr)
        return 1
    files = sorted(TRAINING_DIR.rglob("*.png"))
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
