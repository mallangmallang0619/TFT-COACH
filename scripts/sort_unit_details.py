"""Label Set 18 star-level and equipped-item crops with a recoverable UI.

Examples:
    python scripts/sort_unit_details.py --task stars
    python scripts/sort_unit_details.py --task items

Star mode files selected crops with the 1/2/3 keys. Item mode stores up to
three independently selected item names in ``items/labels.json``; it never
creates a class for an item combination. Both modes support crop selection,
defer, recoverable reject, and Ctrl+Z undo.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from game_data import COMPONENT_NAMES, ITEM_RECIPES  # noqa: E402
from set18_data import SET_NUMBER  # noqa: E402

DETAILS_DIR = BACKEND_DIR / "_training" / f"set{SET_NUMBER}_details"
CHAMPION_TRAINING_DIR = BACKEND_DIR / "_training" / f"set{SET_NUMBER}"
ITEM_CACHE = REPO_ROOT / "assets" / "tftacademy_cache.json"
MAX_BATCH = 12
MAX_BATCH_VISUAL_DISTANCE = 12.0


def _unique_destination(directory: Path, filename: str) -> Path:
    directory = Path(directory)
    destination = directory / filename
    if not destination.exists():
        return destination
    stem, suffix = Path(filename).stem, Path(filename).suffix
    index = 2
    while (directory / f"{stem}_{index}{suffix}").exists():
        index += 1
    return directory / f"{stem}_{index}{suffix}"


def list_detail_inbox(task: str, details_dir: Path = DETAILS_DIR) -> list[Path]:
    if task not in {"stars", "items"}:
        raise ValueError(f"Unknown detail task: {task}")
    inbox = Path(details_dir) / task / "_inbox"
    return sorted(
        (path for path in inbox.glob("*.png") if path.is_file()),
        key=lambda path: (path.stat().st_mtime, path.name),
    )


def find_champion_companion(
    filename: str,
    champion_training_dir: Path = CHAMPION_TRAINING_DIR,
) -> Optional[Path]:
    """Find the full unit crop sharing a detail crop's sample filename."""
    root = Path(champion_training_dir)
    if not root.exists():
        return None
    direct = root / "_inbox" / Path(filename).name
    if direct.is_file():
        return direct
    matches = [
        path for path in root.glob(f"*/{Path(filename).name}")
        if path.is_file() and path.parent.name != "_rejected_manual"
    ]
    return sorted(matches)[0] if matches else None


def _champion_from_companion(path: Optional[Path]) -> Optional[str]:
    if path is None or path.parent.name.startswith("_"):
        return None
    return path.parent.name.replace("_", " ")


def move_star_crop(
    source: Path,
    level: int,
    details_dir: Path = DETAILS_DIR,
) -> Path:
    if int(level) not in {1, 2, 3}:
        raise ValueError("Star level must be 1, 2, or 3")
    source = Path(source)
    if not source.is_file() or source.suffix.lower() != ".png":
        raise ValueError(f"Star crop not found: {source}")
    destination_dir = Path(details_dir) / "stars" / str(level)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_destination(destination_dir, source.name)
    shutil.move(str(source), str(destination))
    return destination


def reject_detail_crop(source: Path, rejected_dir: Path) -> Path:
    source = Path(source)
    if not source.is_file():
        raise ValueError(f"Detail crop not found: {source}")
    rejected_dir = Path(rejected_dir)
    rejected_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_destination(rejected_dir, source.name)
    shutil.move(str(source), str(destination))
    return destination


def restore_detail_crop(source: Path, inbox_dir: Path) -> Path:
    source = Path(source)
    if not source.is_file():
        raise ValueError(f"Detail crop not found: {source}")
    inbox_dir = Path(inbox_dir)
    inbox_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_destination(inbox_dir, source.name)
    shutil.move(str(source), str(destination))
    return destination


def available_item_labels(cache_path: Path = ITEM_CACHE) -> list[str]:
    names = {
        str(recipe["name"]).strip()
        for recipe in ITEM_RECIPES
        if str(recipe.get("name", "")).strip()
    }
    names.update(str(name).strip() for name in COMPONENT_NAMES.values())
    path = Path(cache_path)
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            entries = payload.get("items", {}).get("entries", [])
            names.update(
                str(entry.get("name", "")).strip()
                for entry in entries
                if str(entry.get("name", "")).strip()
            )
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return sorted(names, key=str.casefold)


def load_item_labels(manifest_path: Path) -> dict[str, dict]:
    path = Path(manifest_path)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    labels = payload.get("labels", payload) if isinstance(payload, dict) else {}
    return labels if isinstance(labels, dict) else {}


def _write_item_labels(manifest_path: Path, labels: dict[str, dict]) -> None:
    path = Path(manifest_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"version": 1, "labels": labels}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def label_item_crop(
    source: Path,
    items: list[str],
    details_dir: Path = DETAILS_DIR,
    *,
    champion_training_dir: Path = CHAMPION_TRAINING_DIR,
    allowed_labels: Optional[set[str]] = None,
) -> Path:
    source = Path(source)
    if not source.is_file() or source.suffix.lower() != ".png":
        raise ValueError(f"Item crop not found: {source}")
    normalized = list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))
    if len(normalized) > 3:
        raise ValueError("A unit can have at most three labeled items")
    allowed = allowed_labels or set(available_item_labels())
    unknown = [item for item in normalized if item not in allowed]
    if unknown:
        raise ValueError(f"Unknown item label: {', '.join(unknown)}")

    item_root = Path(details_dir) / "items"
    labeled_dir = item_root / "_labeled"
    labeled_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_destination(labeled_dir, source.name)
    companion = find_champion_companion(source.name, champion_training_dir)
    shutil.move(str(source), str(destination))
    manifest = item_root / "labels.json"
    labels = load_item_labels(manifest)
    labels[destination.name] = {
        "items": normalized,
        "champion": _champion_from_companion(companion),
        "champion_crop": str(companion) if companion else None,
    }
    try:
        _write_item_labels(manifest, labels)
    except OSError:
        shutil.move(str(destination), str(source))
        raise
    return destination


def undo_item_label(
    source: Path,
    details_dir: Path = DETAILS_DIR,
) -> Path:
    source = Path(source)
    item_root = Path(details_dir) / "items"
    manifest = item_root / "labels.json"
    labels = load_item_labels(manifest)
    labels.pop(source.name, None)
    _write_item_labels(manifest, labels)
    return restore_detail_crop(source, item_root / "_inbox")


def _detail_batch(
    current: Path,
    paths: list[Path],
    limit: int = MAX_BATCH,
    max_visual_distance: float = MAX_BATCH_VISUAL_DISTANCE,
) -> list[Path]:
    """Group nearest-looking regions; the user still controls selection."""
    import cv2
    import numpy as np

    reference = cv2.imread(str(current), cv2.IMREAD_COLOR)
    if reference is None:
        return [current]

    def signature(image):
        resized = cv2.resize(image, (48, 32), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
        return cv2.resize(hsv, (16, 12), interpolation=cv2.INTER_AREA).astype(np.float32)

    reference_signature = signature(reference)
    ranked: list[tuple[float, Path]] = []
    for path in paths:
        if path == current or not path.is_file():
            continue
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        distance = float(np.mean(np.abs(reference_signature - signature(image))))
        if distance <= max(0.0, max_visual_distance):
            ranked.append((distance, path))
    ranked.sort(key=lambda pair: (pair[0], pair[1].name))
    return [current, *(path for _distance, path in ranked[:max(0, limit - 1)])]


def run_sorter(task: str, details_dir: Path = DETAILS_DIR) -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    from PIL import Image, ImageTk

    details_dir = Path(details_dir)
    inbox_dir = details_dir / task / "_inbox"
    rejected_dir = details_dir / task / "_rejected"
    paths = list_detail_inbox(task, details_dir)
    if not paths:
        print(f"{task.title()} inbox is empty: {inbox_dir}")
        return 0

    item_labels = available_item_labels() if task == "items" else []
    state: dict = {
        "group": [],
        "selected": set(),
        "history": [],
        "photos": [],
        "buttons": {},
        "last_action": "",
    }

    root = tk.Tk()
    root.title(f"TFT Coach — {'Star Level' if task == 'stars' else 'Equipped Items'} Sorter")
    root.geometry("1220x920")
    root.minsize(980, 720)

    status = ttk.Label(root, anchor="center", font=("Segoe UI Semibold", 11))
    status.pack(fill="x", padx=12, pady=(10, 4))
    preview = ttk.Frame(root)
    preview.pack(fill="x", padx=12, pady=4)
    preview.columnconfigure(0, weight=1)
    preview.columnconfigure(1, weight=1)
    detail_preview = ttk.Label(preview, anchor="center", text="Detail crop")
    champion_preview = ttk.Label(preview, anchor="center", text="Matching champion crop")
    detail_preview.grid(row=0, column=0, sticky="nsew", padx=4)
    champion_preview.grid(row=0, column=1, sticky="nsew", padx=4)

    contact = ttk.Frame(root)
    contact.pack(fill="both", expand=True, padx=12, pady=6)
    for column in range(4):
        contact.columnconfigure(column, weight=1)
    for row in range(3):
        contact.rowconfigure(row, weight=1)

    item_box = None
    if task == "items":
        item_panel = ttk.Frame(root)
        item_panel.pack(fill="x", padx=18, pady=4)
        ttk.Label(
            item_panel,
            text="Select 0–3 items (Ctrl+click), then Enter. Press 0 for no items.",
        ).pack(anchor="w")
        item_box = tk.Listbox(
            item_panel,
            selectmode="extended",
            exportselection=False,
            height=7,
            font=("Segoe UI", 10),
        )
        scrollbar = ttk.Scrollbar(item_panel, orient="vertical", command=item_box.yview)
        item_box.configure(yscrollcommand=scrollbar.set)
        item_box.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        for label in item_labels:
            item_box.insert("end", label)

    controls = ttk.Frame(root)
    controls.pack(fill="x", padx=18, pady=(4, 14))

    def clean_paths() -> None:
        nonlocal paths
        paths = [path for path in paths if path.exists()]

    def update_status() -> None:
        state["last_status"] = (
            f"{len(paths)} remaining · selected {len(state['selected'])}/"
            f"{len(state['group'])}"
            + (f" · {state['last_action']}" if state["last_action"] else "")
        )
        status.configure(text=state["last_status"])

    def style_button(path: Path) -> None:
        button = state["buttons"].get(path)
        if button is None:
            return
        selected = path in state["selected"]
        button.configure(
            text="✓ INCLUDED" if selected else "✕ EXCLUDED",
            background="#166534" if selected else "#7f1d1d",
            foreground="#ffffff",
            activebackground="#15803d" if selected else "#991b1b",
            relief="solid" if selected else "flat",
            borderwidth=3,
        )

    def toggle(path: Path) -> None:
        if path in state["selected"]:
            state["selected"].remove(path)
        else:
            state["selected"].add(path)
        style_button(path)
        update_status()

    def refresh() -> None:
        clean_paths()
        for child in contact.winfo_children():
            child.destroy()
        state["photos"] = []
        state["buttons"] = {}
        if not paths:
            state["group"] = []
            state["selected"] = set()
            detail_preview.configure(image="", text="Inbox complete")
            champion_preview.configure(image="", text="No crops remaining")
            update_status()
            return
        group = _detail_batch(paths[0], paths)
        state["group"] = group
        # Star badges batch well by appearance. Item strips start conservative;
        # use A only after confirming the neighbours are truly identical.
        state["selected"] = set(group if task == "stars" else group[:1])

        current = group[0]
        companion = find_champion_companion(current.name)
        for widget, image_path, title, size in (
            (detail_preview, current, "Detail crop", (420, 170)),
            (champion_preview, companion, "Matching champion crop", (420, 240)),
        ):
            if image_path is None:
                widget.configure(image="", text=f"{title}\nnot sorted/found yet")
                continue
            try:
                image = Image.open(image_path).convert("RGB")
                image.thumbnail(size, Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image)
                state["photos"].append(photo)
                widget.configure(image=photo, text=title, compound="top")
            except Exception:
                widget.configure(image="", text=f"{title}\nunreadable")

        for index, path in enumerate(group):
            try:
                image = Image.open(path).convert("RGB")
                image.thumbnail((245, 120), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image)
            except Exception:
                continue
            state["photos"].append(photo)
            button = tk.Button(
                contact,
                image=photo,
                compound="top",
                cursor="hand2",
                font=("Segoe UI Semibold", 9),
                command=lambda crop=path: toggle(crop),
            )
            state["buttons"][path] = button
            style_button(path)
            button.grid(row=index // 4, column=index % 4, padx=4, pady=4, sticky="nsew")
        update_status()
        root.focus_set()

    def rotate_group(_event=None) -> None:
        group_set = set(state["group"])
        remaining = [path for path in paths if path not in group_set and path.exists()]
        remaining.extend(path for path in state["group"] if path.exists())
        paths[:] = remaining
        state["last_action"] = f"deferred {len(state['group'])} crop(s)"
        refresh()

    def chosen_paths() -> list[Path]:
        return [path for path in state["group"] if path in state["selected"] and path.exists()]

    def file_star(level: int) -> None:
        chosen = chosen_paths()
        if not chosen:
            state["last_action"] = "select at least one crop"
            update_status()
            return
        moved = [(move_star_crop(path, level, details_dir), path) for path in chosen]
        state["history"].append(("move", moved))
        state["last_action"] = f"filed {len(moved)} crop(s) as {level}-star"
        refresh()

    def selected_items() -> list[str]:
        if item_box is None:
            return []
        return [str(item_box.get(index)) for index in item_box.curselection()]

    def file_items(items: Optional[list[str]] = None) -> None:
        chosen = chosen_paths()
        labels = selected_items() if items is None else items
        if not chosen:
            state["last_action"] = "select at least one crop"
            update_status()
            return
        if len(labels) > 3:
            messagebox.showerror("Too many items", "Select at most three items.", parent=root)
            return
        moved = []
        try:
            for path in chosen:
                moved.append((label_item_crop(path, labels, details_dir), path))
        except (ValueError, OSError) as error:
            for labeled, _original in reversed(moved):
                if labeled.exists():
                    undo_item_label(labeled, details_dir)
            messagebox.showerror("Cannot label crop", str(error), parent=root)
            return
        state["history"].append(("item", moved))
        state["last_action"] = f"labeled {len(moved)} crop(s) with {len(labels)} item(s)"
        refresh()

    def file_current(_event=None) -> None:
        if task == "items":
            file_items()

    def reject_selected(_event=None) -> None:
        chosen = chosen_paths()
        if not chosen:
            return
        moved = [(reject_detail_crop(path, rejected_dir), path) for path in chosen]
        state["history"].append(("move", moved))
        state["last_action"] = f"rejected {len(moved)} crop(s) recoverably"
        refresh()

    def select_all(_event=None) -> None:
        state["selected"] = set(state["group"])
        for path in state["group"]:
            style_button(path)
        update_status()

    def select_none(_event=None) -> None:
        state["selected"] = set()
        for path in state["group"]:
            style_button(path)
        update_status()

    def undo(_event=None) -> None:
        if not state["history"]:
            return
        operation, moved = state["history"].pop()
        restored = []
        for destination, _original in reversed(moved):
            if not destination.exists():
                continue
            restored.append(
                undo_item_label(destination, details_dir)
                if operation == "item"
                else restore_detail_crop(destination, inbox_dir)
            )
        paths[:0] = [path for path in restored if path not in paths]
        state["last_action"] = f"restored {len(restored)} crop(s)"
        refresh()

    if task == "stars":
        for level in (1, 2, 3):
            ttk.Button(
                controls,
                text=f"{level}-star ({level})",
                command=lambda value=level: file_star(value),
            ).pack(side="left", expand=True, fill="x", padx=3)
            root.bind(f"<Key-{level}>", lambda _event, value=level: file_star(value))
    else:
        ttk.Button(controls, text="Label selected (Enter)", command=file_current).pack(
            side="left", expand=True, fill="x", padx=3
        )
        ttk.Button(controls, text="No items (0)", command=lambda: file_items([])).pack(
            side="left", expand=True, fill="x", padx=3
        )
        root.bind("<Return>", file_current)
        root.bind("<Key-0>", lambda _event: file_items([]))

    ttk.Button(controls, text="Defer (Space)", command=rotate_group).pack(
        side="left", expand=True, fill="x", padx=3
    )
    ttk.Button(controls, text="Reject (Delete)", command=reject_selected).pack(
        side="left", expand=True, fill="x", padx=3
    )
    ttk.Button(controls, text="Undo (Ctrl+Z)", command=undo).pack(
        side="left", expand=True, fill="x", padx=3
    )
    root.bind("<space>", rotate_group)
    root.bind("<Delete>", reject_selected)
    root.bind("<Control-z>", undo)
    root.bind("<Key-a>", select_all)
    root.bind("<Key-n>", select_none)
    refresh()
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("stars", "items"), default="stars")
    parser.add_argument(
        "--details-dir",
        type=Path,
        default=DETAILS_DIR,
        help="detail training root (defaults to the active Set 18 directory)",
    )
    args = parser.parse_args()
    return run_sorter(args.task, args.details_dir)


if __name__ == "__main__":
    raise SystemExit(main())
