"""Quickly sort unlabeled Set 18 unit crops into champion folders.

Live mode writes visually valid board and bench crops to
``backend/_training/set18/_inbox`` without guessing a champion name. Run:

    python scripts/sort_training_inbox.py

Type or select a champion and press Enter to file the crop. Space defers it,
Delete moves it to a recoverable rejected folder, and Ctrl+Z undoes the most
recent move. To review crops created by the old automatic labeler first, run
with ``--requeue-existing`` once.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from set18_data import CHAMPIONS, SET_NUMBER, canonical_training_label  # noqa: E402

TRAINING_DIR = BACKEND_DIR / "_training" / f"set{SET_NUMBER}"
INBOX_DIR = TRAINING_DIR / "_inbox"
REJECTED_DIR = TRAINING_DIR / "_rejected_manual"


def available_labels() -> list[str]:
    """Canonical model classes shown by the sorter."""
    return sorted({canonical_training_label(name) for name in CHAMPIONS})


def list_inbox(inbox_dir: Path = INBOX_DIR) -> list[Path]:
    return sorted(path for path in inbox_dir.glob("*.png") if path.is_file())


def _safe_folder(label: str) -> str:
    return label.replace("'", "").replace(" ", "_").replace(".", "")


def _unique_destination(directory: Path, filename: str) -> Path:
    destination = directory / filename
    if not destination.exists():
        return destination
    stem, suffix = Path(filename).stem, Path(filename).suffix
    index = 2
    while (directory / f"{stem}_{index}{suffix}").exists():
        index += 1
    return directory / f"{stem}_{index}{suffix}"


def move_crop(source: Path, label: str, training_dir: Path = TRAINING_DIR) -> Path:
    """Move one inbox crop into a canonical champion folder."""
    source = Path(source)
    if not source.is_file() or source.suffix.lower() != ".png":
        raise ValueError(f"Not a PNG crop: {source}")
    canonical = canonical_training_label(label.strip().replace("_", " "))
    labels = set(available_labels())
    if canonical not in labels:
        raise ValueError(f"Unknown Set 18 champion: {label}")
    destination_dir = Path(training_dir) / _safe_folder(canonical)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_destination(destination_dir, source.name)
    shutil.move(str(source), str(destination))
    return destination


def reject_crop(source: Path, rejected_dir: Path = REJECTED_DIR) -> Path:
    """Move a bad/ambiguous crop aside without deleting it."""
    source = Path(source)
    if not source.is_file():
        raise ValueError(f"Crop not found: {source}")
    rejected_dir = Path(rejected_dir)
    rejected_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_destination(rejected_dir, source.name)
    shutil.move(str(source), str(destination))
    return destination


def restore_crop(source: Path, inbox_dir: Path = INBOX_DIR) -> Path:
    """Undo a sort/reject operation by returning a crop to the inbox."""
    source = Path(source)
    if not source.is_file():
        raise ValueError(f"Crop not found: {source}")
    inbox_dir = Path(inbox_dir)
    inbox_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_destination(inbox_dir, source.name)
    shutil.move(str(source), str(destination))
    return destination


def requeue_existing(training_dir: Path = TRAINING_DIR) -> int:
    """Move previously labeled crops back to the inbox for manual review."""
    training_dir = Path(training_dir)
    inbox_dir = training_dir / "_inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for label_dir in sorted(training_dir.iterdir()):
        if not label_dir.is_dir() or label_dir.name.startswith("_"):
            continue
        for source in sorted(label_dir.glob("*.png")):
            # Preserve the old guessed label as context, but do not trust it as
            # the destination class. The sorter still requires a human choice.
            filename = f"prior-{label_dir.name}-{source.name}"
            destination = _unique_destination(inbox_dir, filename)
            shutil.move(str(source), str(destination))
            moved += 1
    return moved


def run_sorter(training_dir: Path = TRAINING_DIR) -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    from PIL import Image, ImageTk

    training_dir = Path(training_dir)
    inbox_dir = training_dir / "_inbox"
    rejected_dir = training_dir / "_rejected_manual"
    paths = list_inbox(inbox_dir)
    if not paths:
        print(f"Inbox is empty: {inbox_dir}")
        return 0

    labels = available_labels()
    state = {"index": 0, "photo": None, "history": []}

    root = tk.Tk()
    root.title("TFT Coach — Sort Training Crops")
    root.geometry("760x780")
    root.minsize(620, 620)

    status = ttk.Label(root, anchor="center")
    status.pack(fill="x", padx=12, pady=(12, 4))
    image_label = ttk.Label(root, anchor="center")
    image_label.pack(fill="both", expand=True, padx=12, pady=8)
    filename_label = ttk.Label(root, anchor="center")
    filename_label.pack(fill="x", padx=12, pady=4)

    selected = tk.StringVar()
    combo = ttk.Combobox(root, textvariable=selected, values=labels, font=("Segoe UI", 14))
    combo.pack(fill="x", padx=20, pady=8)

    buttons = ttk.Frame(root)
    buttons.pack(fill="x", padx=20, pady=(4, 16))

    def current_path() -> Path | None:
        nonlocal paths
        paths = [path for path in paths if path.exists()]
        if not paths:
            return None
        state["index"] %= len(paths)
        return paths[state["index"]]

    def refresh() -> None:
        path = current_path()
        if path is None:
            status.configure(text="Inbox complete — no crops remaining")
            filename_label.configure(text="")
            image_label.configure(image="")
            state["photo"] = None
            return
        image = Image.open(path).convert("RGB")
        image.thumbnail((680, 590), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(image)
        state["photo"] = photo
        image_label.configure(image=photo)
        filename_label.configure(text=path.name)
        status.configure(
            text=f"Crop {state['index'] + 1} of {len(paths)} · "
            f"sorted this run: {len(state['history'])}"
        )
        combo.focus_set()

    def file_current(_event=None) -> None:
        path = current_path()
        if path is None:
            return
        try:
            destination = move_crop(path, selected.get(), training_dir)
        except ValueError as error:
            messagebox.showerror("Cannot file crop", str(error), parent=root)
            return
        state["history"].append((destination, path))
        selected.set(canonical_training_label(selected.get().replace("_", " ")))
        refresh()

    def defer_current(_event=None) -> None:
        if current_path() is not None:
            state["index"] += 1
            refresh()

    def reject_current(_event=None) -> None:
        path = current_path()
        if path is None:
            return
        destination = reject_crop(path, rejected_dir)
        state["history"].append((destination, path))
        refresh()

    def undo(_event=None) -> None:
        if not state["history"]:
            return
        moved, original = state["history"].pop()
        if moved.exists():
            restored = restore_crop(moved, inbox_dir)
            paths.append(restored)
            paths.sort()
            state["index"] = paths.index(restored)
        refresh()

    ttk.Button(buttons, text="File (Enter)", command=file_current).pack(
        side="left", expand=True, fill="x", padx=4
    )
    ttk.Button(buttons, text="Defer (Space)", command=defer_current).pack(
        side="left", expand=True, fill="x", padx=4
    )
    ttk.Button(buttons, text="Reject (Delete)", command=reject_current).pack(
        side="left", expand=True, fill="x", padx=4
    )
    ttk.Button(buttons, text="Undo (Ctrl+Z)", command=undo).pack(
        side="left", expand=True, fill="x", padx=4
    )

    combo.bind("<Return>", file_current)
    root.bind("<space>", defer_current)
    root.bind("<Delete>", reject_current)
    root.bind("<Control-z>", undo)
    refresh()
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requeue-existing",
        action="store_true",
        help="move old auto-labeled champion crops into the manual inbox first",
    )
    args = parser.parse_args()
    if args.requeue_existing:
        moved = requeue_existing()
        print(f"Requeued {moved} previously labeled crop(s) for review.")
    return run_sorter()


if __name__ == "__main__":
    raise SystemExit(main())
