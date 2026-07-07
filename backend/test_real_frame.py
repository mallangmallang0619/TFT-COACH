"""
Real-frame HUD regression check.

Runs the detector's OCR against the labeled real screenshot in fixtures/ and
asserts the calibrated ROIs still read the right stage/gold/level/HP. This guards
the ROI calibration in config.GameROIs from silent regressions.

    python backend/test_real_frame.py

Champion/board detection is intentionally NOT checked here — board units are 3D
models that the current portrait templates can't match (see
fixtures/tft_screenshot.json note).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import cv2
from detector import Detector, TemplateStore
from config import GameROIs

FIXTURES = Path(__file__).parent / "fixtures"


def main() -> int:
    img = FIXTURES / "tft_screenshot.png"
    meta = json.loads((FIXTURES / "tft_screenshot.json").read_text())
    hud = meta["hud"]

    frame = cv2.imread(str(img))
    if frame is None:
        print(f"!! could not load {img}")
        return 1

    templates = TemplateStore(); templates.load()
    d = Detector(templates)
    rois = GameROIs()

    got = {
        "stage": d._ocr_stage(frame)[0],
        "gold": d._ocr_number(frame, rois.gold, "gold"),
        "level": d._ocr_number(frame, rois.level, "level"),
        "player_hp": d._ocr_number(frame, rois.player_hp, "hp"),
    }

    ok = True
    for key, expected in hud.items():
        actual = got[key]
        status = "OK  " if actual == expected else "FAIL"
        if actual != expected:
            ok = False
        print(f"  [{status}] {key:<10} expected={expected!r:<6} got={actual!r}")

    print("\nReal-frame HUD OCR:", "PASS" if ok else "FAIL")

    # ── Trait detection ───────────────────────────────────────────────────────
    # Every active trait must be detected (extra greyed-row matches are tolerated
    # for now — see fixtures/tft_screenshot.json note on inactive traits).
    expected_traits = set(meta.get("traits_active", {}))
    detected = {n for n, _ in d._detect_traits(frame)}
    missing = expected_traits - detected
    print("\n  Trait detection:")
    for name in sorted(expected_traits):
        print(f"  [{'OK  ' if name in detected else 'FAIL'}] {name}")
    extra = detected - expected_traits - set(meta.get("traits_inactive", {}))
    if extra:
        print(f"  (extra matches, tolerated: {sorted(extra)})")
    traits_ok = not missing
    print("Real-frame trait detection:", "PASS" if traits_ok else "FAIL")

    return 0 if (ok and traits_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
