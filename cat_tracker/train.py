"""Fine-tune YOLO11s on the labelled captures of the cat, then export it for the tracker.

Run by train.bat with the cat tracker's own training environment (cat_tracker/.venv), never
the camera core's .venv. Only images checked in label.py are used. Images with no box teach it what isn't a cat
(the bear painting, the couch, laundry), so keep those too. The last sixth of every capture session
(in time, all cameras) is held out for checking, so each session teaches it and each is tested on
moments it didn't train on.

  python -m cat_tracker.train                    all sessions in cat_tracker/captures
  python -m cat_tracker.train --epochs 80 --batch 8
  python -m cat_tracker.train --resume-from-last   start from the last fine-tuned model (20 epochs by default):
                                                   quicker when adding a session, still trains on every session
At the end it writes cat_tracker/models/cat_finetuned.onnx and prints how to switch config.yaml to it.
"""

import argparse
import os
import shutil
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def gather(captures):
    """[(session, image path, label path)] for every checked image."""
    out = []
    for ses in sorted(p for p in captures.iterdir() if p.is_dir()):
        ck = ses / "checked.txt"
        if not ck.is_file():
            continue
        for stem in ck.read_text(encoding="utf-8").split():
            img, lab = ses / "images" / f"{stem}.jpg", ses / "labels" / f"{stem}.txt"
            if img.is_file():
                out.append((ses.name, img, lab))
    return out


def build(items, root):
    """YOLO dataset folders (copies, so captures stay as they are) and its data.yaml."""
    if root.exists():
        shutil.rmtree(root)
    moment = lambda img: int(img.stem.rsplit("_", 1)[1])  # images are <camera>_<moment>.jpg
    last = {}
    for ses, img, _ in items:
        last[ses] = max(last.get(ses, 0), moment(img))
    counts = {"train": [0, 0], "val": [0, 0]}  # images, images with her
    for ses, img, lab in items:
        split = "val" if moment(img) >= last[ses] * 5 / 6 else "train"
        name = f"{ses}_{img.stem}"
        for sub in ("images", "labels"):
            (root / sub / split).mkdir(parents=True, exist_ok=True)
        shutil.copy2(img, root / "images" / split / f"{name}.jpg")
        text = lab.read_text(encoding="utf-8").strip() if lab.is_file() else ""
        (root / "labels" / split / f"{name}.txt").write_text(text, encoding="utf-8")
        counts[split][0] += 1
        counts[split][1] += bool(text)
    (root / "data.yaml").write_text(f"path: {root.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n  0: cat\n",
                                    encoding="utf-8")
    return root / "data.yaml", counts, sorted(last)


def store_fp16(src, dst):
    """Same model with its weights stored as fp16 (half the file); maths still runs in fp32."""
    import onnx
    from onnx import TensorProto, helper, numpy_helper
    m = onnx.load(str(src))
    g = m.graph
    inits, casts = [], []
    for t in g.initializer:
        a = numpy_helper.to_array(t)
        if a.dtype == np.float32 and a.size >= 16:
            h = numpy_helper.from_array(a.astype(np.float16), t.name + "__fp16")
            inits.append(h)
            casts.append(helper.make_node("Cast", [h.name], [t.name], to=TensorProto.FLOAT, name=t.name + "__cast"))
        else:
            inits.append(t)
    del g.initializer[:]
    g.initializer.extend(inits)
    nodes = list(g.node)
    del g.node[:]
    g.node.extend(casts + nodes)
    onnx.checker.check_model(m)
    onnx.save(m, str(dst))


def main():
    ap = argparse.ArgumentParser(description="Fine-tune the cat detector on your captures")
    ap.add_argument("--epochs", type=int, help="default 60, or 20 with --resume-from-last")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--patience", type=int, default=20, help="stop after this many epochs without improving")
    ap.add_argument("--imgsz", type=int, default=960, help="match detector.input in config.yaml")
    ap.add_argument("--base", default=str(HERE / "models" / "yolo11s.pt"), help="starting weights (COCO-trained YOLO11s)")
    ap.add_argument("--resume-from-last", action="store_true",
                    help="start from the newest training run's best weights instead of --base")
    args = ap.parse_args()
    args.base = str(Path(args.base).resolve())  # training changes folder later, so pin a relative --base now
    from ultralytics import YOLO

    if args.resume_from_last:
        runs = sorted((HERE / "training" / "runs").glob("*/weights/best.pt"))
        if not runs:
            print("No earlier training run found in cat_tracker/training/runs; run train.bat without it first")
            return 1
        args.base = str(runs[-1])
        print(f"Starting from {args.base}")
    if args.epochs is None:
        args.epochs = 20 if args.resume_from_last else 60

    items = gather(HERE / "captures")
    if not items:
        print("No checked images yet: capture.bat, then label.bat")
        return 1
    data, counts, sessions = build(items, HERE / "training" / "dataset")
    print(f"Training on {counts['train'][0]} images ({counts['train'][1]} with her), checking on "
          f"{counts['val'][0]} ({counts['val'][1]} with her): the last sixth of each of {len(sessions)} sessions")
    if counts["train"][1] < 50:
        print("Warning: under 50 training images with her in them; it will learn, but label more for a reliable model")

    # Ultralytics drops helper downloads (e.g. a small model for its mixed-precision check) in the
    # working folder; keep them inside cat_tracker/training rather than the camera core folder
    os.chdir(HERE / "training")
    run_name = time.strftime("%Y%m%d-%H%M%S")
    model = YOLO(args.base)
    # flips and colour jitter suit ceiling cameras; no mosaic in the last epochs so it ends on whole frames
    model.train(data=str(data), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, rect=False,
                project=str(HERE / "training" / "runs"), name=run_name, single_cls=True, close_mosaic=10,
                fliplr=0.5, flipud=0.2, degrees=10, hsv_h=0.02, hsv_s=0.6, hsv_v=0.5, patience=args.patience, workers=4)
    best = HERE / "training" / "runs" / run_name / "weights" / "best.pt"
    metrics = YOLO(str(best)).val(data=str(data), imgsz=args.imgsz, batch=args.batch)
    onnx_path = Path(YOLO(str(best)).export(format="onnx", imgsz=args.imgsz, opset=17, dynamic=True, simplify=True))
    out = HERE / "models" / "cat_finetuned.onnx"
    store_fp16(onnx_path, out)
    from cat_tracker.half import make_half
    half = HERE / "models" / "cat_finetuned_half.onnx"
    make_half(onnx_path, half)  # what the tracker runs: same boxes, about half the GPU work
    print(f"\nHeld-out check: precision {metrics.box.mp:.2f}, recall {metrics.box.mr:.2f}, mAP50 {metrics.box.map50:.2f}")
    print(f"Saved {half} (used by the tracker) and {out} (full precision)")
    print("To use it, in cat_tracker\\config.yaml under detector set:\n"
          "  model: cat_tracker/models/cat_finetuned_half.onnx\n  cat_class: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
