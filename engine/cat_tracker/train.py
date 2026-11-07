"""Fine-tune YOLO11s on the labelled captures of the cat, then export it for the tracker.

Run by 3_train.bat with the cat tracker's own training environment (.venv-train in the top folder), never
the main .venv. Only images checked in label.py are used. Images with no box teach it what isn't a cat
(a painting on the wall, the couch, laundry), so keep those too. The last sixth of every capture session
(in time, all cameras) is held out for checking, so each session teaches it and each is tested on
moments it didn't train on.

  python -m cat_tracker.train                    all sessions in my_data/captures
  python -m cat_tracker.train --epochs 80 --batch 8
  python -m cat_tracker.train --resume-from-last   start from the last fine-tuned model (20 epochs by default):
                                                   quicker when adding a session, still trains on every session
  python -m cat_tracker.train --overnight         a long run (up to 300 epochs, at most 6 hours, the PC kept awake);
                                                   an interrupted one picks up where it stopped when started again
At the end the new model and the one in use are scored on the same held-back pictures (a fair test set: whole
sessions, cat_tracker.train_extras), and the new one is only used if it's better: then it's written to
my_data/models/cat_finetuned_half.onnx and settings/cat_tracker.yaml switched to it (the old model and settings are
backed up to my_data/backups first). The GPU's temperature and power are logged every minute, and the summary says
how hot it got. Everything said is also in my_data/training/training_log.txt and a summary file per run.
"""

import argparse
import os
import re
import shutil
import time
from pathlib import Path

import numpy as np

TOP = Path(__file__).resolve().parent.parent.parent   # the top folder, next to engine/
DATA = TOP / "my_data"
MODELS = DATA / "models"
TRAINING = DATA / "training"
CAT_SETTINGS = TOP / "settings" / "cat_tracker.yaml"
BACKUPS = DATA / "backups"
MODEL_SETTING = "my_data/models/cat_finetuned_half.onnx"


def cats_setting():
    try:
        import yaml
        return int(((yaml.safe_load(CAT_SETTINGS.read_text(encoding="utf-8")) or {}).get("label") or {}).get("cats", 1))
    except (OSError, ValueError, TypeError):
        return 1


def gather(captures, extra=None):
    """[(session, image path, label path)] for every checked image. A picture with more boxes than cats
    (label.cats) is left out and listed in extra: one of its boxes is likely wrong (fix it in 2_label.bat)."""
    out = []
    cats = cats_setting()
    for ses in sorted(p for p in captures.iterdir() if p.is_dir()):
        ck = ses / "checked.txt"
        if not ck.is_file():
            continue
        for stem in ck.read_text(encoding="utf-8").split():
            img, lab = ses / "images" / f"{stem}.jpg", ses / "labels" / f"{stem}.txt"
            if img.is_file():
                n = sum(1 for line in lab.read_text(encoding="utf-8").split("\n") if len(line.split()) == 5) \
                    if lab.is_file() else 0
                if n > cats:
                    if extra is not None:
                        extra.append(f"{ses.name}/{stem}")
                    continue
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
    counts = {"train": [0, 0], "val": [0, 0]}  # images, images with it
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


def switch_settings():
    """Point settings/cat_tracker.yaml's detector at the fine-tuned model (cat_class 0), keeping its comments.
    The file is copied to my_data/backups first; nothing changes if it already uses the fine-tuned model."""
    text = CAT_SETTINGS.read_text(encoding="utf-8")
    new = re.sub(r"(?m)^(  model:)[ \t]*\S+", rf"\1 {MODEL_SETTING}", text, count=1)
    new = re.sub(r"(?m)^(  cat_class:)[ \t]*\d+", r"\1 0", new, count=1)
    if new == text:
        print(f"{CAT_SETTINGS} already uses {MODEL_SETTING}")
        return
    backup = BACKUPS / f"cat_tracker_{time.strftime('%Y%m%d-%H%M%S')}.yaml"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CAT_SETTINGS, backup)
    CAT_SETTINGS.write_text(new, encoding="utf-8")
    print(f"Switched {CAT_SETTINGS} to {MODEL_SETTING} with cat_class 0 (old file backed up to {backup})")


def val_items(items):
    """The pictures build() puts in its checking slice (the last sixth of each session): the fallback when there is
    no held-back session. Not a fair test: they look just like the pictures trained on."""
    moment = lambda img: int(img.stem.rsplit("_", 1)[1])  # noqa: E731
    last = {}
    for ses, img, _ in items:
        last[ses] = max(last.get(ses, 0), moment(img))
    return [it for it in items if moment(it[1]) >= last[it[0]] * 5 / 6]


def main(argv=None):
    global TRAINING, MODELS, CAT_SETTINGS, BACKUPS
    ap = argparse.ArgumentParser(description="Fine-tune the cat detector on your captures")
    ap.add_argument("--epochs", type=int, help="default 60, 20 with --resume-from-last, 300 with --overnight")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--patience", type=int, help="stop after this many epochs without improving (20; overnight 50)")
    ap.add_argument("--imgsz", type=int, default=960, help="match detector.input in settings/cat_tracker.yaml")
    ap.add_argument("--base", default=str(MODELS / "yolo11s.pt"), help="starting weights (COCO-trained YOLO11s)")
    ap.add_argument("--resume-from-last", action="store_true",
                    help="start from the newest training run's best weights instead of --base")
    ap.add_argument("--overnight", action="store_true",
                    help="a long run: up to 300 epochs, stops when it stops improving, at most --hours; keeps the PC "
                         "awake; an interrupted overnight run picks up where it stopped when started again")
    ap.add_argument("--hours", type=float, help="stop after this long at the most (overnight: 6)")
    ap.add_argument("--device", help="e.g. cpu (default: the GPU)")
    ap.add_argument("--captures", default=str(DATA / "captures"), help=argparse.SUPPRESS)
    ap.add_argument("--workdir", help=argparse.SUPPRESS)    # tests: training, models and settings somewhere else
    ap.add_argument("--settings", help=argparse.SUPPRESS)
    ap.add_argument("--max-images", type=int, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.workdir:
        TRAINING, MODELS, BACKUPS = (Path(args.workdir) / d for d in ("training", "models", "backups"))
    if args.settings:
        CAT_SETTINGS = Path(args.settings)
    # my_data/training/defaults.json (your own, never shared): more capture folders to train on (read only, e.g. an
    # older setup's labelled sessions) and the model to start from, e.g. {"extra_captures": ["D:/old/captures"],
    # "start_from": "D:/old/best.pt"}. Pictures from other camera setups only ever train: the fair test set is
    # always from the current setup (my_data/captures).
    defaults = {}
    try:
        import json as _json
        defaults = _json.loads((TRAINING / "defaults.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    default_base = str(MODELS / "yolo11s.pt")
    if args.base == default_base and defaults.get("start_from") and Path(defaults["start_from"]).is_file() \
            and not args.resume_from_last:
        args.base = defaults["start_from"]
        print(f"Starting from {args.base} (my_data/training/defaults.json)")
    args.base = str(Path(args.base).resolve())  # training changes folder later, so pin a relative --base now
    from core.ultra import load_yolo
    YOLO = load_yolo()  # with Ultralytics' usage events off (docs/SECURITY.md)

    from cat_tracker import train_extras as tx
    TRAINING.mkdir(parents=True, exist_ok=True)
    log_lines = []

    def say(text):
        print(text, flush=True)
        log_lines.append(time.strftime("%H:%M ") + text)
        with open(TRAINING / "training_log.txt", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")

    state_path = TRAINING / "overnight.json"
    resume = tx.unfinished_run(state_path, TRAINING / "runs") if args.overnight else None
    if args.resume_from_last and not resume:
        runs = sorted((TRAINING / "runs").glob("*/weights/best.pt"))
        if not runs:
            print("No earlier training run found in my_data/training/runs; run 4_teach_it_your_cat\\3_train.bat first")
            return 1
        args.base = str(runs[-1])
        print(f"Starting from {args.base}")
    if args.epochs is None:
        args.epochs = 300 if args.overnight else 20 if args.resume_from_last else 60
    if args.patience is None:
        args.patience = 50 if args.overnight else 20
    if args.hours is None and args.overnight:
        args.hours = 6.0

    captures = Path(args.captures)
    extra = []
    items = gather(captures, extra)
    for root in defaults.get("extra_captures", []):  # read only: the pictures are copied into the dataset
        more = [(f"old-{ses}", img, lab) for ses, img, lab in gather(Path(root), extra)] if Path(root).is_dir() else []
        print(f"Also training on {len(more)} checked pictures from {root}")
        items += more
    if extra:
        print(f"Left out {len(extra)} pictures with more boxes than cats (label.cats in settings): one of their boxes "
              f"is likely wrong. Fix them with 4_teach_it_your_cat\\2_label.bat --review-extra: {', '.join(extra[:8])}"
              + (" ..." if len(extra) > 8 else ""))
    if not items:
        print("No checked images yet: run 1_capture.bat, then 2_label.bat")
        return 1
    since = tx.setup_since(DATA / "calibration" / "room.json")  # the current camera setup's start
    tests = tx.test_sessions(captures, TRAINING / "test_sessions.txt", since)
    held = set(tests) | set(tx.marked_tests(captures))  # marked test sessions are never trained on, any setup
    test_items = [it for it in items if it[0] in tests]  # never an "old-" session: other camera setups
    train_items = [it for it in items if it[0] not in held]
    if args.max_images:
        train_items, test_items = train_items[:args.max_images], test_items[:args.max_images]
    data, counts, sessions = build(train_items, TRAINING / "dataset")
    say(f"Training on {counts['train'][0]} images ({counts['train'][1]} with it), checking on "
        f"{counts['val'][0]} ({counts['val'][1]} with it) from {len(sessions)} sessions")
    if tests:
        for t in sorted(held):
            n = sum(1 for it in test_items if it[0] == t)
            say(f"TEST SET (held back, never trained on): {t}, {n} labelled pictures"
                + ("" if n else ": label it with 2_label.bat for a fair score"))
    else:
        say("No fair test set yet: the score below is NOT reliable. For a fair score, capture a second short session "
            "(about 5 minutes) on another day and label it: it becomes your test set.")
    if counts["train"][1] < 50:
        say("Warning: under 50 training images with it in them; it will learn, but label more for a reliable model")

    # Ultralytics drops helper downloads (e.g. a small model for its mixed-precision check) in the
    # working folder; keep them inside my_data/training rather than the code folder
    os.chdir(TRAINING)
    started = time.time()
    watch = tx.GpuWatch(say)
    with tx.KeepAwake() if args.overnight else _nothing():
        watch.start() if args.device != "cpu" else None
        try:
            if resume is not None:
                st = tx.load_state(state_path)
                run_name = st["run"]
                say(f"Picking up the interrupted overnight run {run_name} where it stopped")
                model = YOLO(str(resume))
                model.train(resume=True)
            else:
                run_name = time.strftime("%Y%m%d-%H%M%S")
                if args.overnight:
                    tx.save_state(state_path, run=run_name, started=time.strftime("%Y-%m-%d %H:%M"), finished=False)
                model = YOLO(args.base)
                # flips and colour jitter suit ceiling cameras; no mosaic in the last epochs so it ends on whole frames
                model.train(data=str(data), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch, rect=False,
                            project=str(TRAINING / "runs"), name=run_name, single_cls=True, close_mosaic=10,
                            fliplr=0.5, flipud=0.2, degrees=10, hsv_h=0.02, hsv_s=0.6, hsv_v=0.5,
                            patience=args.patience, workers=4 if args.device != "cpu" else 0,
                            **({"time": args.hours} if args.hours else {}),
                            **({"device": args.device} if args.device else {}))
        finally:
            watch.stop()
    best = TRAINING / "runs" / run_name / "weights" / "best.pt"
    took = (time.time() - started) / 3600

    # the new model against the one in use, on the same pictures
    judge = test_items or val_items(train_items)
    in_use = re.search(r"(?m)^  model:[ 	]*(\S+)", CAT_SETTINGS.read_text(encoding="utf-8"))  # the line, not a comment
    uses_finetuned = bool(in_use and "cat_finetuned" in in_use.group(1))
    old_pt = MODELS / "cat_finetuned.pt"
    if uses_finetuned and old_pt.is_file():
        old_model, old_class = old_pt, 0
    elif uses_finetuned:
        old_model, old_class = None, 0  # an older fine-tuned model without its .pt: can't be compared
    else:
        old_model, old_class = MODELS / "yolo11s.pt", 15  # the stock model is in use (not the starting weights)
    new_score = tx.evaluate(best, judge, 0, args.imgsz, device=args.device)
    old_score = tx.evaluate(old_model, judge, old_class, args.imgsz, device=args.device) if old_model else None
    keep_new, why = tx.decide(old_score, new_score, fair=bool(test_items))
    fair = "fair test set" if test_items else "NOT a fair test (no held-back session yet)"
    say(f"New model: score {new_score['f1']:.2f} (found {new_score['recall']:.0%} of the cats, "
        f"{new_score['precision']:.0%} of its boxes right) on {len(judge)} pictures, {fair}")
    if old_score:
        say(f"Model in use: score {old_score['f1']:.2f} (found {old_score['recall']:.0%}, {old_score['precision']:.0%} right)")

    MODELS.mkdir(parents=True, exist_ok=True)
    if keep_new:
        backup = BACKUPS / f"models_{time.strftime('%Y%m%d-%H%M%S')}"
        old_files = [p for p in (MODELS / "cat_finetuned.onnx", MODELS / "cat_finetuned_half.onnx", old_pt) if p.is_file()]
        if old_files:
            backup.mkdir(parents=True, exist_ok=True)
            for p in old_files:
                shutil.copy2(p, backup / p.name)
        onnx_path = Path(YOLO(str(best)).export(format="onnx", imgsz=args.imgsz, opset=17, dynamic=True, simplify=True))
        out = MODELS / "cat_finetuned.onnx"
        store_fp16(onnx_path, out)
        from cat_tracker.half import make_half
        half = MODELS / "cat_finetuned_half.onnx"
        make_half(onnx_path, half)  # what the tracker runs: same boxes, about half the GPU work
        shutil.copy2(best, old_pt)  # kept, so the next training can be compared with it
        say(("Switched to the new model" if not test_items else "Kept the NEW model") + f": {why}."
            + (f" The old one is backed up in {backup}." if old_files else ""))
        switch_settings()
    else:
        cand = MODELS / "candidates"
        cand.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best, cand / f"{run_name}.pt")
        say(f"Kept the model you HAVE: {why}. The new one is saved as {cand / (run_name + '.pt')} in case.")

    if args.overnight:
        tx.save_state(state_path, run=run_name, finished=True)
    heat = (" " + watch.summary()) if watch.max_c else ""
    summary = [f"Training {run_name}: {took:.1f} hours." + heat] + log_lines[-4:]
    (TRAINING / f"summary_{run_name}.txt").write_text(tx.summary_text(summary), encoding="utf-8")
    print("\n" + "\n".join(summary))
    print(f"(This summary is also in {TRAINING / ('summary_' + run_name + '.txt')})")
    print("Next: 5_play_in_vr\\run_tracker.bat (or 3_first_test\\2_desktop_test.bat to check it on the desktop first)")
    return 0


class _nothing:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


if __name__ == "__main__":
    raise SystemExit(main())
