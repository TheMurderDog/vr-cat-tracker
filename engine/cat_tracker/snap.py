"""A tight cat box near a known spot: the stock model run again on an enlarged crop around it, at a low bar.

Used by autolabel (run by 2_label.bat; the spot: where the other cameras place the cat, projected into this camera) and by
2_label.bat (the spot: where you clicked). Measured on the test setup's 1,462 hand-checked autolabel cases (old camera
angles, the stock COCO model, never trained on them): a box in 78% of them, 84% of those within IoU 0.8 of the hand-drawn
box, against 3% for the projected cat-sized outline alone. The outline is centred well but 20-30% too big; the model
on the enlarged crop finds the cat's real extent. Where it finds nothing (half hidden, dim), no box is better than a
wrong one: 241 of 244 cases cleared by hand got none.
"""

from pathlib import Path

import numpy as np

from cat_tracker.locate import iou  # noqa: F401  (re-exported for callers)

CROP_INPUT = 640   # the crop is fed to the model at this size (so small cats are enlarged)
CROP_SCORE = 0.03  # the low bar: the spot is already known, the model only has to find the extent
CHECK_BELOW = 0.2  # boxes scoring below this are marked "check this" (at 0.2 or more, 90% were right)


FINETUNED = ("cat_finetuned_half.onnx", "cat_finetuned.onnx")  # what 3_train.bat makes
HELPER = "helper_latest"  # 2_label's TRAIN A HELPER: helper_latest.onnx / .pt / .json (what it grew from)


def base_model(cfg):
    """(model path, cat class) the labelling helpers start from: the newest of 3_train's fine-tuned model and
    label.helper_model (label.helper_cat_class, default 0); none: the tracker's detector model (the stock one)."""
    from core.config import get, resolve_path
    have = [(p, 0) for p in (resolve_path(f"my_data/models/{n}") for n in FINETUNED) if p.is_file()]
    own = get(cfg, "cat.label.helper_model", None)
    if own and resolve_path(own).is_file():
        have.append((resolve_path(own), int(get(cfg, "cat.label.helper_cat_class", 0))))
    if have:
        return max(have, key=lambda pc: pc[0].stat().st_mtime)
    dc = cfg["cat"]["detector"]
    return resolve_path(dc["model"]), int(dc.get("cat_class", 15))


def base_id(path):
    """What a helper records as the model it grew from: the file and when it was written (a retrained model at the
    same path is another model)."""
    p = Path(path).resolve()
    return f"{p}|{p.stat().st_mtime_ns}" if p.is_file() else str(p)


def helper_meta(models=None):
    """The helper's metadata ({"root": base_id, ...}) in models (default my_data/models), or None."""
    import json
    from core.config import resolve_path
    try:
        return json.loads((Path(models or resolve_path("my_data/models")) / f"{HELPER}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def helper_model(cfg):
    """(model path, cat class) for the labelling helpers (the click snap in 2_label, autolabel's crop, the helper's
    suggestions): the helper (TRAIN A HELPER) when it grew from today's base model (base_model), else the base model
    itself. So a helper never replaces a better model it didn't learn from (e.g. one started from the stock model
    while a trained one is there), and a new 3_train model takes over until a helper is trained from it. Only the
    helpers use this: the tracker always uses detector.model."""
    from core.config import resolve_path
    base = base_model(cfg)
    onnx = resolve_path(f"my_data/models/{HELPER}.onnx")
    meta = helper_meta()
    if onnx.is_file() and meta and meta.get("root") == base_id(base[0]):
        return onnx, 0
    return base


def make_detector(cfg, cpu=False, size=CROP_INPUT, score=CROP_SCORE):
    """The cat model for crops: the labelling helpers' model (helper_model). GPU unless cpu, falling back to the CPU
    quietly."""
    from cat_tracker.detector import CatDetector
    from core.config import get
    model, cat_class = helper_model(cfg)
    dc = dict(cfg["cat"]["detector"], input=size, score=score, cat_class=cat_class, model=str(model))
    providers = ["CPUExecutionProvider"] if cpu else ["CUDAExecutionProvider", "CPUExecutionProvider"]
    if not cpu:
        try:
            from pose import baseline
            baseline.prepare_onnxruntime(get(cfg, "onnxruntime", {}) or {})
        except Exception:  # noqa: BLE001  (no GPU setup: the CPU works, just slower)
            providers = ["CPUExecutionProvider"]
    return CatDetector(dc, model, providers, require_gpu=False)


def crop_box(det, img, region, grow=1.0, max_dist=0.8):
    """(box [x1, y1, x2, y2], score) of the cat near region's centre, or (None, 0.0).

    The crop is a square of the region's longer side times (1 + 2 * grow), centred on it. Of the model's boxes, the
    best one whose centre is within max_dist region-sizes of the region's centre wins (score, less the further it
    is)."""
    H, W = img.shape[:2]
    x1, y1, x2, y2 = region
    bw, bh = max(x2 - x1, 1.0), max(y2 - y1, 1.0)
    side = max(bw, bh) * (1 + 2 * grow)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    X1, Y1 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
    X2, Y2 = int(min(W, cx + side / 2)), int(min(H, cy + side / 2))
    crop = img[Y1:Y2, X1:X2]
    if crop.shape[0] < 16 or crop.shape[1] < 16:
        return None, 0.0
    best, best_s = None, 0.0
    for b in det([np.ascontiguousarray(crop)])[0]:
        box = [float(b[0] + X1), float(b[1] + Y1), float(b[2] + X1), float(b[3] + Y1)]
        d = np.hypot((box[0] + box[2]) / 2 - cx, (box[1] + box[3]) / 2 - cy) / max(bw, bh)
        if d > max_dist:
            continue
        s = float(b[4]) * (1 - d / max_dist * 0.5)
        if s > best_s:
            best, best_s = box, s
    return best, best_s
