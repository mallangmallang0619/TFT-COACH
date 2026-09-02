"""Quickly sort unlabeled Set 18 unit crops into champion folders.

Live mode writes visually valid board and bench crops to
``backend/_training/set18/_inbox`` without guessing a champion name. Run:

    python scripts/sort_training_inbox.py

The smart sorter groups up to 20 visually/model-similar crops across every board
hex and bench slot. Click any outlier to deselect it, choose a champion from the
read-only dropdown, then press Enter to file the selected contact sheet. ``S``
accepts the displayed model suggestion (it never files automatically), ``A``
selects all, ``N`` selects none, Space defers the group, Delete rejects selected
crops recoverably, and Ctrl+Z undoes the latest batch. To review crops created
by the old automatic labeler first, run with ``--requeue-existing``.

Use ``--filter-inbox-dry-run`` to preview recoverable quality/burst filtering,
or ``--filter-inbox`` to quarantine rejects and open the remaining crops.
"""

from __future__ import annotations

import argparse
import datetime
import re
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
SORTER_COMBO_STATE = "readonly"
DEFAULT_FILTER_INTERVAL_SECONDS = 12.0
DEFAULT_FILTER_VISUAL_CHANGE = 25.0
DEFAULT_BATCH_WINDOW_SECONDS = 30.0
DEFAULT_BATCH_VISUAL_CHANGE = 12.0
DEFAULT_BATCH_LIMIT = 25
SMART_BATCH_LIMIT = 20
SMART_VISUAL_DISTANCE = 0.34
_SOURCE_RE = re.compile(
    r"_(board_r\d_c\d_i\d+|bench_slot\d+)(?:_\d+)?$"
)
_LEGACY_BENCH_RE = re.compile(r"(?:^|_)slot([0-8])(?:_|$)")
_TIMESTAMP_RE = re.compile(r"(\d{8}_\d{6}_\d{6})")


def available_labels() -> list[str]:
    """Canonical model classes shown by the sorter."""
    return sorted({canonical_training_label(name) for name in CHAMPIONS})


def list_inbox(inbox_dir: Path = INBOX_DIR) -> list[Path]:
    return sorted(
        (path for path in inbox_dir.glob("*.png") if path.is_file()),
        key=_inbox_sort_key,
    )


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


def archive_inbox(training_dir: Path = TRAINING_DIR) -> int:
    """Move the current noisy inbox aside without permanently deleting it."""
    training_dir = Path(training_dir)
    inbox_dir = training_dir / "_inbox"
    rejected_dir = training_dir / "_rejected_manual"
    moved = 0
    for source in list_inbox(inbox_dir):
        destination = _unique_destination(
            rejected_dir,
            f"archived-{source.name}",
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        moved += 1
    return moved


def _capture_source(path: Path) -> str | None:
    match = _SOURCE_RE.search(path.stem)
    if match:
        return match.group(1)
    legacy = _LEGACY_BENCH_RE.search(path.stem)
    if legacy:
        return f"bench_slot{legacy.group(1)}"
    return None


def _capture_time(path: Path) -> float:
    match = _TIMESTAMP_RE.search(path.name)
    if match:
        try:
            return datetime.datetime.strptime(
                match.group(1),
                "%Y%m%d_%H%M%S_%f",
            ).timestamp()
        except ValueError:
            pass
    return path.stat().st_mtime


def _inbox_sort_key(path: Path) -> tuple[int, int, float, str]:
    """Group bench slots numerically, then show board/unknown crops."""
    source = _capture_source(path)
    bench = re.fullmatch(r"bench_slot([0-8])", source or "")
    if bench:
        return (0, int(bench.group(1)), _capture_time(path), path.name)
    if source and source.startswith("board_"):
        return (1, 0, _capture_time(path), path.name)
    return (2, 0, _capture_time(path), path.name)


def _insert_inbox_path(paths: list[Path], restored: Path) -> int:
    """Insert an undone crop without losing the slot-grouped queue order."""
    if restored not in paths:
        paths.append(restored)
    paths.sort(key=_inbox_sort_key)
    return paths.index(restored)


def similar_crop_batch(
    current: Path,
    paths: list[Path],
    *,
    max_time_gap: float = DEFAULT_BATCH_WINDOW_SECONDS,
    max_visual_change: float = DEFAULT_BATCH_VISUAL_CHANGE,
    limit: int = DEFAULT_BATCH_LIMIT,
) -> list[Path]:
    """Return a conservative same-occupant burst headed by ``current``."""
    import cv2

    from harvest import BenchHarvester

    current = Path(current)
    source = _capture_source(current)
    image = cv2.imread(str(current), cv2.IMREAD_COLOR)
    reference = BenchHarvester._thumb(image) if image is not None else None
    if source is None or reference is None:
        return [current]

    captured_at = _capture_time(current)
    candidates: list[Path] = []
    for path in paths:
        if not path.is_file() or _capture_source(path) != source:
            continue
        if abs(_capture_time(path) - captured_at) > max(0.0, max_time_gap):
            continue
        candidate_image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        candidate = (
            BenchHarvester._thumb(candidate_image)
            if candidate_image is not None else None
        )
        if candidate is None or candidate.shape != reference.shape:
            continue
        visual_change = float(cv2.absdiff(reference, candidate).mean())
        if visual_change <= max(0.0, max_visual_change):
            candidates.append(path)

    candidates.sort(key=lambda path: (_capture_time(path), path.name))
    if current in candidates:
        candidates.remove(current)
    return [current, *candidates[:max(0, limit - 1)]]


def visual_signature(image) -> "object":
    """Return a compact lighting-tolerant fingerprint for visual grouping.

    This is deliberately not a labeler. It only places likely neighbours on
    the same contact sheet; the user must still choose the champion and may
    deselect every outlier before anything is moved.
    """
    import cv2
    import numpy as np

    if image is None or getattr(image, "size", 0) == 0:
        return np.zeros(112, dtype=np.float32)
    resized = cv2.resize(image, (32, 48), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    gray = (gray - float(gray.mean())) / max(0.08, float(gray.std()))
    low_frequency = cv2.dct(gray)[:8, :8].reshape(-1)
    low_frequency /= max(1e-6, float(np.linalg.norm(low_frequency)))

    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    color = cv2.calcHist([hsv], [0, 1], None, [12, 4], [0, 180, 0, 256])
    color = cv2.normalize(color, None, norm_type=cv2.NORM_L1).reshape(-1)
    return np.concatenate((low_frequency, color)).astype(np.float32)


def build_visual_index(paths: list[Path]) -> dict[Path, "object"]:
    """Decode inbox crops once and cache their visual fingerprints."""
    import cv2

    signatures = {}
    for path in paths:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is not None:
            signatures[path] = visual_signature(image)
    return signatures


def model_suggestions(
    paths: list[Path],
    *,
    batch_size: int = 96,
) -> dict[Path, tuple[str | None, float]]:
    """Return non-binding current-model suggestions for sorter grouping."""
    import cv2

    from unit_classifier import UnitClassifier

    classifier = UnitClassifier()
    suggestions = {path: (None, 0.0) for path in paths}
    if not classifier.available:
        return suggestions
    for start in range(0, len(paths), max(1, batch_size)):
        batch_paths = paths[start:start + max(1, batch_size)]
        images = [cv2.imread(str(path), cv2.IMREAD_COLOR) for path in batch_paths]
        results = classifier.classify_batch(
            images,
            min_confidences=[0.0] * len(images),
        )
        suggestions.update(zip(batch_paths, results))
    return suggestions


def smart_crop_batch(
    current: Path,
    paths: list[Path],
    *,
    signatures: dict[Path, "object"],
    suggestions: dict[Path, tuple[str | None, float]] | None = None,
    limit: int = SMART_BATCH_LIMIT,
    max_visual_distance: float = SMART_VISUAL_DISTANCE,
) -> list[Path]:
    """Build a review-only cross-slot group around ``current``.

    A shared model suggestion takes priority because logits are comparatively
    stable across idle poses. Visual distance orders that bucket and is the
    fallback when the model is unavailable. No crop is moved by this function.
    """
    import numpy as np

    current = Path(current)
    reference = signatures.get(current)
    if reference is None:
        return [current]
    suggestions = suggestions or {}
    current_label, current_confidence = suggestions.get(current, (None, 0.0))
    current_label = current_label if current_confidence >= 0.03 else None
    ranked: list[tuple[int, float, float, str, Path]] = []
    for path in paths:
        if path == current or not path.is_file():
            continue
        signature = signatures.get(path)
        if signature is None or signature.shape != reference.shape:
            continue
        distance = float(np.mean(np.abs(reference - signature)))
        label, confidence = suggestions.get(path, (None, 0.0))
        label = label if confidence >= 0.03 else None
        same_suggestion = bool(current_label and label == current_label)
        if current_label is not None and label is not None and not same_suggestion:
            continue
        if not same_suggestion and distance > max(0.0, max_visual_distance):
            continue
        ranked.append((0 if same_suggestion else 1, distance, -confidence, path.name, path))
    ranked.sort(key=lambda row: row[:-1])
    return [current, *(row[-1] for row in ranked[:max(0, limit - 1)])]


def plan_inbox_filter(
    training_dir: Path = TRAINING_DIR,
    *,
    min_source_interval: float = DEFAULT_FILTER_INTERVAL_SECONDS,
    max_burst_visual_change: float = DEFAULT_FILTER_VISUAL_CHANGE,
) -> dict[Path, str]:
    """Plan obvious-quality and visually similar burst rejections."""
    import cv2

    from harvest import BenchHarvester

    training_dir = Path(training_dir)
    records = sorted(
        (
            (_capture_time(path), path, _capture_source(path))
            for path in list_inbox(training_dir / "_inbox")
        ),
        key=lambda item: (item[0], item[1].name),
    )
    decisions: dict[Path, str] = {}
    last_kept_by_source: dict[str, tuple[float, object]] = {}
    interval = max(0.0, float(min_source_interval))
    visual_limit = max(0.0, float(max_burst_visual_change))

    for captured_at, path, source in records:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        reason = BenchHarvester.training_crop_rejection_reason(
            image,
            require_health_bar=not bool(source and source.startswith("bench_slot")),
        )
        if reason:
            decisions[path] = reason
            continue
        if source is None:
            continue
        thumb = BenchHarvester._thumb(image)
        last_kept = last_kept_by_source.get(source)
        if last_kept is not None and thumb is not None:
            last_time, last_thumb = last_kept
            visual_change = float(cv2.absdiff(thumb, last_thumb).mean())
            if (
                captured_at - last_time < interval
                and visual_change <= visual_limit
            ):
                decisions[path] = "burst_excess"
                continue
        if thumb is not None:
            last_kept_by_source[source] = (captured_at, thumb)
    return decisions


def filter_inbox(
    training_dir: Path = TRAINING_DIR,
    *,
    min_source_interval: float = DEFAULT_FILTER_INTERVAL_SECONDS,
    max_burst_visual_change: float = DEFAULT_FILTER_VISUAL_CHANGE,
    dry_run: bool = False,
) -> dict[str, int]:
    """Filter obvious failures/bursts, moving rejects aside unless dry-run."""
    training_dir = Path(training_dir)
    inbox = list_inbox(training_dir / "_inbox")
    decisions = plan_inbox_filter(
        training_dir,
        min_source_interval=min_source_interval,
        max_burst_visual_change=max_burst_visual_change,
    )
    report: dict[str, int] = {"kept": len(inbox) - len(decisions)}
    for reason in decisions.values():
        report[reason] = report.get(reason, 0) + 1
    if dry_run:
        return report

    rejected_dir = training_dir / "_rejected_manual"
    for source, reason in decisions.items():
        if not source.exists():
            continue
        rejected_dir.mkdir(parents=True, exist_ok=True)
        destination = _unique_destination(
            rejected_dir,
            f"filtered-{reason}-{source.name}",
        )
        shutil.move(str(source), str(destination))
    return report


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


def crop_selection_style(selected: bool, source: str | None) -> dict[str, object]:
    """Return a high-contrast visual style for a batch-sorter crop."""
    source_name = source or "unknown"
    if selected:
        return {
            "text": f"✓ INCLUDED · {source_name}",
            "background": "#166534",
            "foreground": "#ffffff",
            "activebackground": "#15803d",
            "activeforeground": "#ffffff",
            "highlightbackground": "#4ade80",
            "highlightcolor": "#4ade80",
            "relief": "solid",
            "borderwidth": 3,
            "highlightthickness": 4,
        }
    return {
        "text": f"✕ EXCLUDED · {source_name}",
        "background": "#4c1d24",
        "foreground": "#ffe4e6",
        "activebackground": "#7f1d1d",
        "activeforeground": "#ffffff",
        "highlightbackground": "#fb7185",
        "highlightcolor": "#fb7185",
        "relief": "flat",
        "borderwidth": 3,
        "highlightthickness": 4,
    }


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

    print(f"Indexing {len(paths)} crops for smart visual batches...")
    signatures = build_visual_index(paths)
    suggestions = model_suggestions(paths)
    paths.sort(key=lambda path: (
        suggestions.get(path, (None, 0.0))[0] is None,
        suggestions.get(path, (None, 0.0))[0] or "",
        -suggestions.get(path, (None, 0.0))[1],
        _inbox_sort_key(path),
    ))

    labels = available_labels()
    state = {
        "history": [],
        "last_action": "",
        "group": [],
        "selected": set(),
        "photos": [],
        "crop_buttons": {},
    }

    root = tk.Tk()
    root.title("TFT Coach — Smart Batch Sorter")
    root.geometry("1180x930")
    root.minsize(900, 720)

    status = ttk.Label(root, anchor="center")
    status.pack(fill="x", padx=12, pady=(12, 4))
    suggestion_label = ttk.Label(root, anchor="center")
    suggestion_label.pack(fill="x", padx=12, pady=(0, 6))

    selection_legend = tk.Frame(root, background="#111827")
    selection_legend.pack(fill="x", padx=12, pady=(0, 4))
    tk.Label(
        selection_legend,
        text="✓ INCLUDED — NEXT ACTION",
        background="#166534",
        foreground="#ffffff",
        font=("Segoe UI Semibold", 10),
        padx=12,
        pady=6,
    ).pack(side="left")
    tk.Label(
        selection_legend,
        text="Click any crop to toggle its selection",
        background="#111827",
        foreground="#f3f4f6",
        font=("Segoe UI", 10),
        pady=6,
    ).pack(side="left", expand=True)
    tk.Label(
        selection_legend,
        text="✕ EXCLUDED — STAYS IN INBOX",
        background="#7f1d1d",
        foreground="#ffffff",
        font=("Segoe UI Semibold", 10),
        padx=12,
        pady=6,
    ).pack(side="right")

    contact = ttk.Frame(root)
    contact.pack(fill="both", expand=True, padx=12, pady=6)
    for column in range(5):
        contact.columnconfigure(column, weight=1)
    for row in range(4):
        contact.rowconfigure(row, weight=1)

    selected = tk.StringVar()
    combo = ttk.Combobox(
        root,
        textvariable=selected,
        values=labels,
        state=SORTER_COMBO_STATE,
        takefocus=False,
        font=("Segoe UI", 14),
    )
    combo.pack(fill="x", padx=20, pady=8)

    buttons = ttk.Frame(root)
    buttons.pack(fill="x", padx=20, pady=(4, 16))

    def clean_paths() -> None:
        nonlocal paths
        paths = [path for path in paths if path.exists()]

    def rotate_group(group: list[Path]) -> None:
        nonlocal paths
        group_set = set(group)
        paths = [path for path in paths if path.exists() and path not in group_set]
        paths.extend(path for path in group if path.exists())

    def current_suggestion() -> tuple[str | None, float]:
        group = state["group"]
        return suggestions.get(group[0], (None, 0.0)) if group else (None, 0.0)

    def update_status() -> None:
        selected_count = len(state["selected"])
        excluded_count = len(state["group"]) - selected_count
        status.configure(
            text=f"{len(paths)} crops left · review group {len(state['group'])} · "
            f"INCLUDED {selected_count} / EXCLUDED {excluded_count} · "
            f"sorted this run {sum(len(group) for group in state['history'])}"
            + (f" · {state['last_action']}" if state["last_action"] else "")
        )

    def apply_crop_style(path: Path, button) -> None:
        button.configure(**crop_selection_style(
            path in state["selected"],
            _capture_source(path),
        ))

    def toggle_crop(path: Path) -> None:
        if path in state["selected"]:
            state["selected"].remove(path)
        else:
            state["selected"].add(path)
        button = state["crop_buttons"].get(path)
        if button is not None:
            apply_crop_style(path, button)
        update_status()

    def refresh() -> None:
        clean_paths()
        for child in contact.winfo_children():
            child.destroy()
        state["photos"] = []
        state["crop_buttons"] = {}
        if not paths:
            status.configure(text="Inbox complete — no crops remaining")
            suggestion_label.configure(text="")
            state["group"] = []
            state["selected"] = set()
            return
        group = smart_crop_batch(
            paths[0],
            paths,
            signatures=signatures,
            suggestions=suggestions,
        )
        state["group"] = group
        state["selected"] = set(group)
        label, confidence = current_suggestion()
        suggestion_label.configure(text=(
            f"Model suggestion: {label} ({confidence:.0%}) — press S to use it"
            if label else
            "No model suggestion — visually similar crops only"
        ))
        for index, path in enumerate(group):
            try:
                image = Image.open(path).convert("RGB")
            except Exception:
                continue
            image.thumbnail((190, 155), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            state["photos"].append(photo)
            button = tk.Button(
                contact,
                image=photo,
                compound="top",
                font=("Segoe UI Semibold", 9),
                cursor="hand2",
                command=lambda crop=path: toggle_crop(crop),
            )
            apply_crop_style(path, button)
            button.grid(
                row=index // 5,
                column=index % 5,
                padx=4,
                pady=4,
                sticky="nsew",
            )
            state["crop_buttons"][path] = button
        update_status()
        root.focus_set()

    def file_paths(paths_to_file: list[Path]) -> None:
        moved_group: list[tuple[Path, Path]] = []
        try:
            for path in paths_to_file:
                if path.exists():
                    destination = move_crop(path, selected.get(), training_dir)
                    moved_group.append((destination, path))
        except ValueError as error:
            for moved, _original in reversed(moved_group):
                if moved.exists():
                    restore_crop(moved, inbox_dir)
            messagebox.showerror("Cannot file crop", str(error), parent=root)
            return
        if not moved_group:
            return
        state["history"].append(moved_group)
        state["last_action"] = (
            f"filed {len(moved_group)} similar crops"
            if len(moved_group) > 1 else "filed 1 crop"
        )
        selected.set(canonical_training_label(selected.get().replace("_", " ")))
        rotate_group(state["group"])
        refresh()

    def file_selected(_event=None) -> None:
        chosen = [
            path for path in state["group"]
            if path in state["selected"] and path.exists()
        ]
        if not chosen:
            state["last_action"] = "select at least one crop"
            update_status()
            return
        file_paths(chosen)

    def defer_group(_event=None) -> None:
        if state["group"]:
            rotate_group(state["group"])
            state["last_action"] = f"deferred {len(state['group'])} crops"
            refresh()

    def reject_selected(_event=None) -> None:
        chosen = [
            path for path in state["group"]
            if path in state["selected"] and path.exists()
        ]
        if not chosen:
            return
        moved_group = [(reject_crop(path, rejected_dir), path) for path in chosen]
        state["history"].append(moved_group)
        state["last_action"] = f"rejected {len(moved_group)} crop(s)"
        rotate_group(state["group"])
        refresh()

    def select_all(_event=None) -> None:
        state["selected"] = set(state["group"])
        for path, button in state["crop_buttons"].items():
            apply_crop_style(path, button)
        update_status()

    def select_none(_event=None) -> None:
        state["selected"] = set()
        for path, button in state["crop_buttons"].items():
            apply_crop_style(path, button)
        update_status()

    def use_suggestion(_event=None) -> None:
        label, _confidence = current_suggestion()
        if label in labels:
            selected.set(label)
            state["last_action"] = f"selected suggestion {label}"
            update_status()

    def undo(_event=None) -> None:
        if not state["history"]:
            return
        group = state["history"].pop()
        restored_paths = []
        for moved, _original in reversed(group):
            if moved.exists():
                restored_paths.append(restore_crop(moved, inbox_dir))
        for restored in restored_paths:
            if restored not in signatures:
                import cv2
                image = cv2.imread(str(restored), cv2.IMREAD_COLOR)
                if image is not None:
                    signatures[restored] = visual_signature(image)
            if restored not in paths:
                paths.insert(0, restored)
        state["last_action"] = f"restored {len(restored_paths)} crop(s)"
        refresh()

    ttk.Button(buttons, text="File selected (Enter)", command=file_selected).pack(
        side="left", expand=True, fill="x", padx=4
    )
    ttk.Button(buttons, text="Use suggestion (S)", command=use_suggestion).pack(
        side="left", expand=True, fill="x", padx=4
    )
    ttk.Button(buttons, text="Defer group (Space)", command=defer_group).pack(
        side="left", expand=True, fill="x", padx=4
    )
    ttk.Button(buttons, text="Reject selected (Delete)", command=reject_selected).pack(
        side="left", expand=True, fill="x", padx=4
    )
    ttk.Button(buttons, text="Undo (Ctrl+Z)", command=undo).pack(
        side="left", expand=True, fill="x", padx=4
    )

    combo.bind("<<ComboboxSelected>>", lambda _event: root.after_idle(root.focus_set))
    root.bind("<Return>", file_selected)
    root.bind("<Shift-Return>", file_selected)
    root.bind("<space>", defer_group)
    root.bind("<Delete>", reject_selected)
    root.bind("<Control-z>", undo)
    root.bind("<Key-s>", use_suggestion)
    root.bind("<Key-a>", select_all)
    root.bind("<Key-n>", select_none)
    refresh()
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--requeue-existing",
        action="store_true",
        help="move old auto-labeled champion crops into the manual inbox first",
    )
    actions.add_argument(
        "--archive-inbox",
        action="store_true",
        help="move the current inbox aside without deleting its crops",
    )
    actions.add_argument(
        "--filter-inbox",
        action="store_true",
        help="quarantine obvious failures and excessive same-position bursts",
    )
    actions.add_argument(
        "--filter-inbox-dry-run",
        action="store_true",
        help="report what inbox filtering would do without moving files",
    )
    args = parser.parse_args()
    if args.archive_inbox:
        moved = archive_inbox()
        print(f"Archived {moved} inbox crop(s) without deleting them.")
        return 0
    if args.filter_inbox or args.filter_inbox_dry_run:
        report = filter_inbox(dry_run=args.filter_inbox_dry_run)
        action = "Would keep" if args.filter_inbox_dry_run else "Kept"
        details = ", ".join(
            f"{reason}={count}"
            for reason, count in report.items()
            if reason != "kept"
        )
        print(f"{action} {report['kept']} inbox crop(s); filtered {details or 'none'}.")
        if args.filter_inbox_dry_run:
            return 0
    if args.requeue_existing:
        moved = requeue_existing()
        print(f"Requeued {moved} previously labeled crop(s) for review.")
    return run_sorter()


if __name__ == "__main__":
    raise SystemExit(main())
