"""Compare CPU cost and prediction consistency on local reviewed unit crops.

Run: python scripts/benchmark_inference.py --samples 24 --repeats 3
Reports process CPU seconds separately from elapsed inference time; results
are replay measurements, not whole-application Task Manager percentages.
"""
from pathlib import Path
import argparse
import json
import sys
import time

import cv2
import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from unit_classifier import preprocess
from inference_runtime import cpu_session_options


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=24)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--crops", type=Path, default=ROOT / "backend/_training/set18")
    args = parser.parse_args()
    if args.samples < 1 or args.repeats < 1:
        parser.error("samples and repeats must be positive")
    meta = json.loads((ROOT / "assets/models/unit_classifier.json").read_text())
    # Select across class directories rather than taking a single burst.
    crops = []
    for label in meta["labels"]:
        folder = args.crops / label
        candidate = next(folder.glob("*.png"), None)
        if candidate is not None:
            crop = cv2.imread(str(candidate))
            if crop is not None:
                crops.append(crop)
        if len(crops) >= args.samples:
            break
    if not crops:
        parser.error(f"No reviewed PNG crops found in {args.crops}")
    batch = preprocess(
        crops, meta["input_size"],
        np.array(meta["mean"], dtype=np.float32).reshape(3, 1, 1),
        np.array(meta["std"], dtype=np.float32).reshape(3, 1, 1),
        meta.get("resize_mode", "stretch"),
    )
    reference = None
    for threads in (0, 1, 2, 4):
        opts = cpu_session_options() if threads else ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = threads
        session = ort.InferenceSession(
            str(ROOT / "assets/models/unit_classifier.onnx"),
            sess_options=opts, providers=["CPUExecutionProvider"],
        )
        inputs = {session.get_inputs()[0].name: batch}
        session.run(None, inputs)
        cpu_start, wall_start = time.process_time(), time.perf_counter()
        for _ in range(args.repeats):
            result = session.run(None, inputs)[0]
        elapsed = time.perf_counter() - wall_start
        cpu = time.process_time() - cpu_start
        # Live capture runs at 2 FPS; account for workers spinning between reads.
        idle_cpu = time.process_time()
        time.sleep(0.5)
        idle_cpu = time.process_time() - idle_cpu
        if reference is None:
            reference = result.copy()
        print(json.dumps({
            "threads": threads or "default", "samples": len(crops),
            "ms_per_batch": round(elapsed * 1000 / args.repeats, 2),
            "cpu_ms_per_batch": round(cpu * 1000 / args.repeats, 2),
            "post_inference_idle_cpu_ms": round(idle_cpu * 1000, 2),
            "same_top1": bool(np.array_equal(result.argmax(1), reference.argmax(1))),
            "max_logit_difference": float(np.max(np.abs(result - reference))),
        }), flush=True)
        del session


if __name__ == "__main__":
    main()
