"""Score cat models on your fair test set: how often each one finds the cat, and how often it sees a cat that isn't
there. Read only: nothing is trained, no settings or labels change.

The fair test set is the capture session(s) marked as test ("TEST SET: not trained on" on the sessions screen; mark
one with python -m cat_tracker.sessions --test NAME). Only its decided pictures count (skipped ones don't). Each
model runs the tracker's way: its own detector code, the input size from settings, and the tracker's confidence
threshold (detector.score), so the numbers match what the tracker sees on its own.

From the engine folder:
  python -m cat_tracker.score_test_set                       the model in settings, and the stock model if present
  python -m cat_tracker.score_test_set --model my_data/models/other.onnx --model my_data/models/yolo11s.onnx
  python -m cat_tracker.score_test_set --session 20261105-184947 --score 0.3 --cpu

Each run adds one line per model to my_data/training/test_scores.jsonl, so later runs can be compared.
"""

import argparse
import json
import time
from pathlib import Path

import cv2

from cat_tracker import settings
from cat_tracker import train_extras as tx
from cat_tracker.detector import CatDetector
from cat_tracker.label import read_boxes
from core.config import get, resolve_path

STOCK = "my_data/models/yolo11s.onnx"
OVERLAP = 0.5  # a box "on the cat" overlaps a checked box at least this much (IoU)


def cat_class(model_path, fallback):
    """The cat's class number from the model's outputs: 0 for a model trained on your cat (one class), 15 for the
    stock COCO model (80 classes). Anything else: fallback."""
    import onnxruntime as ort
    shape = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"]).get_outputs()[0].shape
    channels = shape[1] if len(shape) > 1 else None
    return {5: 0, 84: 15}.get(channels, fallback)


def test_pictures(ses):
    """[(camera, image path, label path)] for every decided picture of a session."""
    checked = set((ses / "checked.txt").read_text(encoding="utf-8").split()) if (ses / "checked.txt").is_file() else set()
    out = []
    for img in sorted((ses / "images").glob("*.jpg")):
        if img.stem in checked:
            out.append((img.stem.rsplit("_", 1)[0], img, ses / "labels" / f"{img.stem}.txt"))
    return out


def score_model(det, pictures):
    """Counts for one model, overall and per camera."""
    def blank():
        return {"cat": 0, "found": 0, "on_cat": 0, "no_cat": 0, "false_alarm": 0, "extra": 0}
    total, per_cam, ms = blank(), {}, []
    for cam, img_path, lab in pictures:
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        h, w = img.shape[:2]
        truth = read_boxes(lab, w, h)
        t0 = time.perf_counter()
        boxes = det([img])[0]
        ms.append((time.perf_counter() - t0) * 1000)
        c = per_cam.setdefault(cam, blank())
        for d in (total, c):
            if truth:
                d["cat"] += 1
                d["found"] += 1 if len(boxes) else 0
                d["on_cat"] += 1 if any(tx._iou(b[:4], g) >= OVERLAP for b in boxes for g in truth) else 0
                d["extra"] += max(0, len(boxes) - len(truth))
            else:
                d["no_cat"] += 1
                d["false_alarm"] += 1 if len(boxes) else 0
    ms = sorted(ms)[len(ms) // 10:] or ms  # the first runs warm the GPU up
    return total, per_cam, (sum(ms) / len(ms) if ms else 0.0)


def pct(a, b):
    return f"{100 * a / b:5.1f}%" if b else "   -  "


def main(argv=None):
    ap = argparse.ArgumentParser(description="Score cat models on the fair test set (read only)")
    ap.add_argument("--model", action="append", help="an .onnx model to score (repeat for more). "
                    "Default: the one in settings/cat_tracker.yaml, plus the stock model if it's there")
    ap.add_argument("--session", action="append", help="a test session to use (default: every session marked test)")
    ap.add_argument("--score", type=float, help="confidence that counts as a cat (default: detector.score)")
    ap.add_argument("--cpu", action="store_true", help="run on the CPU (slower, same results)")
    args = ap.parse_args(argv)

    cfg = settings.load()
    dc = dict(cfg["cat"]["detector"])
    if args.score is not None:
        dc["score"] = args.score
    dc["score"] = float(dc.get("score", 0.2))
    captures = resolve_path("my_data/captures")

    names = args.session or tx.marked_tests(captures)
    if not names:
        print("No test session yet. Capture a short session on another day, label it in 2_label, and mark it with\n"
              "  python -m cat_tracker.sessions --test NAME\n"
              "Training leaves marked sessions out, so it gives a fair score.")
        return 1
    pictures = []
    for n in names:
        ses = captures / n
        if not (ses / "images").is_dir():
            print(f"Session {n} isn't in my_data/captures.")
            return 1
        pictures += test_pictures(ses)
    if not pictures:
        print("The test session has no decided pictures yet: label it in 2_label first.")
        return 1

    models = [resolve_path(m) for m in (args.model or [])]
    if not models:
        models = [resolve_path(dc["model"])]
        stock = resolve_path(STOCK)
        if stock.is_file() and stock.resolve() != models[0].resolve():
            models.append(stock)
    missing = [str(m) for m in models if not Path(m).is_file()]
    if missing:
        print("Model not found: " + ", ".join(missing))
        return 1

    providers = ["CPUExecutionProvider"]
    if not args.cpu:
        try:
            from pose import baseline
            baseline.prepare_onnxruntime(get(cfg, "onnxruntime", {}) or {})
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        except Exception:  # noqa: BLE001  (no GPU setup: the CPU gives the same numbers, just slower)
            pass

    n_cat = 0
    for cam, img, lab in pictures:
        n_cat += 1 if lab.is_file() and lab.read_text(encoding="utf-8").split() else 0
    n_none = len(pictures) - n_cat
    print(f"Test set: {', '.join(names)} ({len(pictures)} decided pictures: {n_cat} with the cat, {n_none} without)")
    print(f"Confidence that counts as a cat: {dc['score']}, input {dc.get('input', 640)}\n")

    out_file = resolve_path("my_data/training") / "test_scores.jsonl"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    for model in models:
        cls = cat_class(model, int(dc.get("cat_class", 15)))
        det = CatDetector({**dc, "cat_class": cls}, model, providers, require_gpu=False)
        total, per_cam, ms = score_model(det, pictures)
        print(f"{Path(model).name}  (cat class {cls}, {ms:.0f} ms a picture)")
        print(f"  found the cat      {pct(total['found'], total['cat'])}  ({total['found']}/{total['cat']} pictures with the cat had a box)")
        print(f"  box on the cat     {pct(total['on_cat'], total['cat'])}  (a box overlapping yours by {OVERLAP} IoU or more)")
        print(f"  false alarms       {pct(total['false_alarm'], total['no_cat'])}  ({total['false_alarm']}/{total['no_cat']} no-cat pictures had a box)")
        print(f"  extra boxes        {total['extra']} on pictures with the cat")
        for cam in sorted(per_cam):
            c = per_cam[cam]
            print(f"    {cam:<10} found {pct(c['found'], c['cat'])}   false alarms {pct(c['false_alarm'], c['no_cat'])}"
                  f" ({c['false_alarm']}/{c['no_cat']})")
        print()
        with open(out_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({"when": time.strftime("%Y-%m-%d %H:%M:%S"), "model": str(model), "sessions": names,
                                "score": dc["score"], "input": dc.get("input"), "cat_class": cls,
                                "total": total, "per_camera": per_cam}) + "\n")

    print("These numbers come from your test session only: one room, one day, your cat and light. Pictures next to\n"
          "each other look alike, so treat each number as roughly +/-5%. A small difference between two models may be\n"
          "chance. If a model's own boxes were the starting point for your labels, its box-on-the-cat number reads\n"
          "a little high. The tracker also uses weaker boxes near where another camera sees the cat, which this\n"
          "doesn't count.")
    print(f"Saved to {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
