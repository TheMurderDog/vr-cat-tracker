"""A quick helper model for labelling, trained from the pictures decided so far (2_label's TRAIN A HELPER button runs
this in the background, in the training environment). Measured on the test setup's pictures (one room, one cat): from 150 decided pictures,
2.3 minutes on an RTX 4070 Ti SUPER, the helper found the cat in 92% of the fair test pictures (83% dimmed like a dim
room) against 67% (49%) for the stock model, but also boxed 19% of the empty pictures (44% dimmed); at score 0.5,
88% (76%) found and 11% (18%) empty ones boxed. So its suggestions are orange to check, and under 0.5 marked CHECK
THIS. 60 pictures weren't enough (no better than stock). One room, one cat, one evening: yours will differ.

What it learns from (cat_tracker.helper): every decided picture (checked boxes, and "no cat" pictures) in the current
camera setup's sessions, never the fair test session(s), never undecided suggestions. Each run adds the pictures it
used to my_data/training/helper/used.json. It only ever writes the helper (my_data/models/helper_latest.onnx and .pt):
the tracker's own model and settings are never changed. 3_train.bat still does the real training, with its fair test
and keep-the-better rule. Progress: my_data/training/helper/progress.json, for the labelling tool to show.

  ..\\.venv-train\\Scripts\\python.exe -m cat_tracker.helper_train            (from the engine folder)
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

TOP = Path(__file__).resolve().parent.parent.parent
DATA = TOP / "my_data"
MODELS = DATA / "models"
EPOCHS = 25


def write_progress(path, **state):
    """The progress file, replaced in one step (the labelling tool reads it while this runs)."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(state, t=time.time()), indent=1), encoding="utf-8")
    os.replace(tmp, path)


def pt_of(onnx):
    """The trainable .pt beside an exported model (cat_finetuned_half.onnx -> cat_finetuned.pt), or None."""
    onnx = Path(onnx)
    for stem in (onnx.stem, onnx.stem[:-len("_half")] if onnx.stem.endswith("_half") else None):
        if stem and (onnx.parent / f"{stem}.pt").is_file():
            return onnx.parent / f"{stem}.pt"
    return None


def start_from(models=MODELS, cfg=None):
    """(the .pt to fine-tune, the base it grows from as snap.base_id, its cat class). The model the labelling helpers
    use now: the helper if it grew from today's base (it keeps building on it), else the base model (a trained model
    if there is one, else the stock model). Starting from the best one there is means a helper never ends up worse
    than what the helpers had (a short run from the stock model would)."""
    from cat_tracker import settings, snap
    cfg = cfg or settings.load()
    base, cls = snap.base_model(cfg)
    root = snap.base_id(base)
    meta = snap.helper_meta(models)
    helper_pt = models / "helper_latest.pt"
    if helper_pt.is_file() and meta and meta.get("root") == root:
        return helper_pt, root, 0
    pt = pt_of(base)
    if pt is None:  # (an exported model without its .pt: start from the stock weights)
        pt = models / "yolo11s.pt"
    return pt, root, cls


NEW_MAX = 400       # new decided pictures per run at most (the newest)
REHEARSE_MAX = 300  # ...plus as many already-learned or older ones (at most this many), so it doesn't forget


def items_for(captures, since=None, used=None, seed=0):
    """[(session, image, label)] the helper learns from: the decided pictures of this camera setup's sessions that no
    helper has learned from yet (the newest NEW_MAX), plus as many others, at random (up to REHEARSE_MAX: ones a
    helper learned from, and older camera setups' decided pictures), so it keeps what it knew. Measured: a helper
    from its trained model on 150 new dim pictures alone found 92.4% / 78.4% (clean / dimmed) of the fair test
    cats against 96.4% / 94.5% before; with 150 older ones mixed in, 94.8% / 91.2%. Never a test session."""
    import random
    from cat_tracker import helper
    used = used or {}
    captures = Path(captures)
    held = helper.held_back(captures)
    new, rest = [], []
    current = {p.name for p in helper.eligible(captures, since)}
    for ses in sorted(p for p in captures.iterdir() if p.is_dir() and p.name not in held) if captures.is_dir() else []:
        u = used.get(ses.name, set())
        for stem in helper.decided(ses):
            img, lab = ses / "images" / f"{stem}.jpg", ses / "labels" / f"{stem}.txt"
            if img.is_file():
                (new if ses.name in current and stem not in u else rest).append((ses.name, img, lab))
    new = new[-NEW_MAX:]
    rng = random.Random(seed)
    return new + rng.sample(rest, min(len(new), REHEARSE_MAX, len(rest)))


GATE_CONF = 0.4   # scored as the suggestions are made (CHECK THIS from 0.4)
GATE_MIN_CATS = 10  # fewer held-back cats than this: too few to compare (only a first helper over stock goes ahead)


def held_back_items(items):
    """The decided pictures train.build keeps out of training (its "val" split: the last sixth of each session's
    moments): the gate compares the helper and its parent on them."""
    moment = lambda img: int(img.stem.rsplit("_", 1)[1])  # noqa: E731
    last = {}
    for ses, img, _ in items:
        last[ses] = max(last.get(ses, 0), moment(img))
    return [it for it in items if moment(it[1]) >= last[it[0]] * 5 / 6]


def gate(new, old, cats, parent_is_stock):
    """(use the helper?, why), from both models' scores on the held-back pictures (train_extras.score dicts)."""
    if cats < GATE_MIN_CATS:
        if parent_is_stock:
            return True, f"only {cats} held-back pictures with the cat to compare on; a first helper goes ahead"
        return False, f"only {cats} held-back pictures with the cat: too few to show it's better"
    if new["f1"] >= old["f1"]:
        return True, f"it does as well or better on pictures it didn't learn from (score {new['f1']:.2f} against {old['f1']:.2f})"
    return False, f"it does worse on pictures it didn't learn from (score {new['f1']:.2f} against {old['f1']:.2f})"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Train a quick labelling helper from the decided pictures")
    ap.add_argument("--epochs", type=int, default=EPOCHS)
    ap.add_argument("--captures", default=str(DATA / "captures"))
    ap.add_argument("--models", default=str(MODELS))
    ap.add_argument("--work", default=str(DATA / "training" / "helper"))
    ap.add_argument("--since", help=argparse.SUPPRESS)       # tests: the camera setup's start
    ap.add_argument("--max-images", type=int, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    models, work = Path(args.models), Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    progress = work / "progress.json"
    t0 = time.time()
    write_progress(progress, state="starting", epoch=0, of=args.epochs, pid=os.getpid())
    try:
        from cat_tracker import helper
        items = items_for(Path(args.captures), args.since, helper.load_used(work / "used.json"))
        if args.max_images:
            items = items[: args.max_images]
        with_cat = sum(1 for _, _, lab in items if lab.is_file() and lab.read_text(encoding="utf-8").strip())
        if with_cat < 20:
            write_progress(progress, state="failed", why=f"only {with_cat} decided pictures with the cat: box a few more")
            return 1
        from cat_tracker import train
        data, counts, _ = train.build(items, work / "dataset")
        from core.ultra import load_yolo
        YOLO = load_yolo()  # with Ultralytics' usage events off
        base, root, parent_cls = start_from(models)
        model = YOLO(str(base))

        def on_epoch(trainer):
            write_progress(progress, state="training", epoch=trainer.epoch + 1, of=args.epochs, pid=os.getpid(),
                           pictures=len(items))

        model.add_callback("on_train_epoch_end", on_epoch)
        run = time.strftime("%Y%m%d-%H%M%S")
        model.train(data=str(data), epochs=args.epochs, imgsz=960, batch=8, rect=False, project=str(work / "runs"),
                    name=run, single_cls=True, close_mosaic=3, fliplr=0.5, flipud=0.2, degrees=10, hsv_h=0.02,
                    hsv_s=0.6, hsv_v=0.5, patience=100, workers=0, plots=False, verbose=False)
        best = Path(model.trainer.best)
        write_progress(progress, state="checking", epoch=args.epochs, of=args.epochs, pid=os.getpid())
        from cat_tracker import train_extras as tx
        held = held_back_items(items)
        new = tx.evaluate(best, held, 0, conf=GATE_CONF)
        old = tx.evaluate(base, held, parent_cls, conf=GATE_CONF)
        use, why = gate(new, old, new["cats"], base.name == "yolo11s.pt")
        scores = {"helper": {k: round(new[k], 3) for k in ("f1", "recall", "precision")},
                  "parent": {k: round(old[k], 3) for k in ("f1", "recall", "precision")}, "held_back": len(held),
                  "held_back_cats": new["cats"]}
        if not use:  # nothing changes: the helpers keep what they had, the pictures count as new still
            write_progress(progress, state="done", promoted=False, why=why, scores=scores, pictures=len(items),
                           minutes=round((time.time() - t0) / 60, 1))
            return 0
        write_progress(progress, state="exporting", epoch=args.epochs, of=args.epochs, pid=os.getpid())
        onnx_path = Path(YOLO(str(best)).export(format="onnx", imgsz=960, opset=17, dynamic=True, simplify=True))
        models.mkdir(parents=True, exist_ok=True)
        meta = models / "helper_latest.json.tmp"
        meta.write_text(json.dumps({"root": root, "started_from": str(base), "when": time.strftime("%Y-%m-%d %H:%M"),
                                    "pictures": len(items)}, indent=1), encoding="utf-8")
        for src, name in ((onnx_path, "helper_latest.onnx"), (best, "helper_latest.pt")):
            tmp = models / f"{name}.tmp"
            shutil.copy2(src, tmp)
            os.replace(tmp, models / name)  # the labelling tool never sees a half-written model
        os.replace(meta, models / "helper_latest.json")  # last: the new helper counts only once it's all there
        used_file = work / "used.json"
        try:
            used = json.loads(used_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            used = {}
        pics = {}
        for ses, img, _ in items:
            pics.setdefault(ses, []).append(img.stem)
        used[run] = {"when": time.strftime("%Y-%m-%d %H:%M"), "base": base.name, "pictures": pics}
        tmp = used_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(used, indent=1), encoding="utf-8")
        os.replace(tmp, used_file)
        write_progress(progress, state="done", promoted=True, why=why, scores=scores,
                       model=str(models / "helper_latest.onnx"), pictures=len(items), with_cat=with_cat, base=base.name,
                       minutes=round((time.time() - t0) / 60, 1))
        return 0
    except Exception as e:  # noqa: BLE001  (the labelling tool shows it; labelling goes on)
        write_progress(progress, state="failed", why=f"{type(e).__name__}: {e}"[:300])
        raise


if __name__ == "__main__":
    sys.exit(main())
