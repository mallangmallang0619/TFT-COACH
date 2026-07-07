"""
Detection Accuracy Harness

Scores the champion detector against ground truth and reports precision / recall
and a confidence histogram. Two case sources:

  • Synthetic (default): boards built from the TFT Academy cache via
    simulate_screenshot, run at several `Realism` levels. Because we build the
    frame we know the exact ground truth, so we can measure how matching degrades
    as the frame gets noisier — and tune CHAMPION_MATCH_THRESHOLD against data.

  • Fixtures: real screenshots under backend/fixtures/<name>.png with a sibling
    <name>.json describing the expected board. Realism levels don't apply to these
    (the image is fixed); they're scored once. Use --save-fixtures to dump the
    synthetic boards as labeled fixtures to seed the directory.

Usage:
    python backend/eval_detection.py                      # default comps, all levels
    python backend/eval_detection.py --comps set-17-dark-star --levels none,heavy
    python backend/eval_detection.py --fixtures            # score real fixtures too
    python backend/eval_detection.py --save-fixtures light # write labeled fixtures

Ground truth excludes units with no champion template (summons like Galio), since
the detector cannot possibly match those.
"""

from __future__ import annotations
import argparse
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import cv2
import numpy as np

from detector import Detector, TemplateStore
from config import CHAMPION_MATCH_THRESHOLD
import simulate_screenshot as sim

logger = logging.getLogger("eval")

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@dataclass
class Case:
    """One scored board: a frame plus the champions that should be detected."""
    name: str
    frame: np.ndarray
    expected: list[tuple[str, int, int]]  # (champ, row, col), template-less excluded


@dataclass
class Score:
    tp_name: int = 0          # detected champions matching an expected name (multiset)
    tp_pos: int = 0           # detected at the exact expected (name, row, col)
    n_expected: int = 0
    n_detected: int = 0
    confidences: list[float] = field(default_factory=list)
    false_positives: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)

    def merge(self, other: "Score") -> None:
        self.tp_name += other.tp_name
        self.tp_pos += other.tp_pos
        self.n_expected += other.n_expected
        self.n_detected += other.n_detected
        self.confidences += other.confidences
        self.false_positives += other.false_positives
        self.missed += other.missed

    @property
    def precision(self) -> float:
        return self.tp_name / self.n_detected if self.n_detected else 0.0

    @property
    def recall(self) -> float:
        return self.tp_name / self.n_expected if self.n_expected else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def pos_accuracy(self) -> float:
        return self.tp_pos / self.n_expected if self.n_expected else 0.0


# ── Case construction ─────────────────────────────────────────────────────────

def expected_from_units(units: list[dict], templates: TemplateStore
                        ) -> list[tuple[str, int, int]]:
    """Ground truth = placed units that actually have a champion template."""
    out = []
    for u in units:
        if u["name"] not in templates.champion_templates:
            continue
        hexp = sim._hex_by_board_index(u["boardIndex"])
        if hexp is not None:
            out.append((u["name"], hexp.row, hexp.col))
    return out


def synthetic_case(slug: str, templates: TemplateStore,
                   realism: sim.Realism, seed: int) -> Case:
    units, label = sim.units_from_comp(slug)
    frame = sim.synthesize_frame(units, templates, realism=realism, seed=seed)
    return Case(name=label, frame=frame,
                expected=expected_from_units(units, templates))


def load_fixture_cases() -> list[Case]:
    """Load real labeled screenshots from backend/fixtures/."""
    cases = []
    if not FIXTURE_DIR.exists():
        return cases
    for img_path in sorted(FIXTURE_DIR.glob("*.png")):
        meta_path = img_path.with_suffix(".json")
        if not meta_path.exists():
            logger.warning(f"{img_path.name}: no sibling .json, skipping")
            continue
        frame = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
        if frame is None:
            logger.warning(f"{img_path.name}: could not decode, skipping")
            continue
        meta = json.loads(meta_path.read_text())
        expected = [(b["name"], b["row"], b["col"]) for b in meta.get("board", [])]
        cases.append(Case(name=img_path.stem, frame=frame, expected=expected))
    return cases


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_case(case: Case, detector: Detector) -> Score:
    state = detector.detect(case.frame)
    detected = [(c.name, c.board_row, c.board_col, c.confidence)
                for c in state.board_champions]

    s = Score(n_expected=len(case.expected), n_detected=len(detected))
    s.confidences = [c[3] for c in detected]

    exp_names = Counter(e[0] for e in case.expected)
    det_names = Counter(d[0] for d in detected)
    for name in (exp_names | det_names):
        s.tp_name += min(exp_names[name], det_names[name])
    # name-level misses / false positives for eyeballing
    for name, cnt in exp_names.items():
        miss = cnt - det_names.get(name, 0)
        s.missed += [name] * max(0, miss)
    for name, cnt in det_names.items():
        fp = cnt - exp_names.get(name, 0)
        s.false_positives += [name] * max(0, fp)

    exp_pos = Counter((e[0], e[1], e[2]) for e in case.expected)
    det_pos = Counter((d[0], d[1], d[2]) for d in detected)
    for key in exp_pos:
        s.tp_pos += min(exp_pos[key], det_pos.get(key, 0))
    return s


def _histogram(confidences: list[float], width: int = 30) -> str:
    if not confidences:
        return "    (no detections)"
    bins = [0.0, 0.5, 0.6, 0.7, 0.78, 0.85, 0.9, 0.95, 1.01]
    counts = [0] * (len(bins) - 1)
    for c in confidences:
        for i in range(len(bins) - 1):
            if bins[i] <= c < bins[i + 1]:
                counts[i] += 1
                break
    peak = max(counts) or 1
    lines = []
    for i, n in enumerate(counts):
        bar = "█" * int(width * n / peak)
        lines.append(f"    [{bins[i]:.2f},{bins[i+1]:.2f})  {n:>3} {bar}")
    return "\n".join(lines)


def run(cases_by_level: dict[str, list[Case]], detector: Detector) -> None:
    print("\n" + "=" * 72)
    print(f"  DETECTION ACCURACY   (threshold = {CHAMPION_MATCH_THRESHOLD})")
    print("=" * 72)
    print(f"  {'level':<10}{'cases':>6}{'exp':>6}{'det':>6}"
          f"{'prec':>8}{'recall':>8}{'F1':>8}{'pos-acc':>9}{'meanConf':>10}")
    print("  " + "-" * 69)

    all_conf: list[float] = []
    for level, cases in cases_by_level.items():
        agg = Score()
        for case in cases:
            agg.merge(score_case(case, detector))
        all_conf += agg.confidences
        mean_conf = float(np.mean(agg.confidences)) if agg.confidences else 0.0
        print(f"  {level:<10}{len(cases):>6}{agg.n_expected:>6}{agg.n_detected:>6}"
              f"{agg.precision:>8.2f}{agg.recall:>8.2f}{agg.f1:>8.2f}"
              f"{agg.pos_accuracy:>9.2f}{mean_conf:>10.3f}")
        if agg.false_positives:
            print(f"             false+: {Counter(agg.false_positives).most_common(6)}")
        if agg.missed:
            print(f"             missed: {Counter(agg.missed).most_common(6)}")

    print("\n  Confidence histogram (all detections):")
    print(_histogram(all_conf))
    print("=" * 72)


# ── Fixtures dump ─────────────────────────────────────────────────────────────

def save_fixtures(slugs: list[str], templates: TemplateStore,
                  realism_name: str, seed: int) -> None:
    FIXTURE_DIR.mkdir(exist_ok=True)
    realism = sim.Realism.preset(realism_name)
    for slug in slugs:
        case = synthetic_case(slug, templates, realism, seed)
        stem = f"{slug}__{realism_name}"
        cv2.imwrite(str(FIXTURE_DIR / f"{stem}.png"), case.frame)
        meta = {
            "source": "synthetic", "comp": slug, "realism": realism_name, "seed": seed,
            "board": [{"name": n, "row": r, "col": c} for n, r, c in case.expected],
        }
        (FIXTURE_DIR / f"{stem}.json").write_text(json.dumps(meta, indent=2))
        print(f"  wrote fixtures/{stem}.png + .json ({len(case.expected)} units)")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--comps",
                    default="set-17-the-big-bang-meepsie,set-17-gnar-printer,"
                            "set-17-samira-knock-up-copy,set-17-dark-star,"
                            "set-17-invader-zed",
                    help="comma-separated comp slugs to synthesize")
    ap.add_argument("--levels", default=",".join(sim.PRESET_ORDER),
                    help="comma-separated realism presets to evaluate")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--fixtures", action="store_true",
                    help="also score real labeled fixtures from backend/fixtures/")
    ap.add_argument("--save-fixtures", metavar="LEVEL", default=None,
                    help="write the synthetic boards as labeled fixtures at this level")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s")

    templates = TemplateStore()
    templates.load()
    detector = Detector(templates)

    slugs = [s.strip() for s in args.comps.split(",") if s.strip()]

    if args.save_fixtures:
        save_fixtures(slugs, templates, args.save_fixtures, args.seed)
        return 0

    cases_by_level: dict[str, list[Case]] = {}
    for level in [s.strip() for s in args.levels.split(",") if s.strip()]:
        realism = sim.Realism.preset(level)
        cases_by_level[level] = [
            synthetic_case(slug, templates, realism, args.seed) for slug in slugs
        ]

    if args.fixtures:
        fx = load_fixture_cases()
        if fx:
            cases_by_level["fixtures"] = fx
        else:
            print("(no fixtures found in backend/fixtures/)")

    run(cases_by_level, detector)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
