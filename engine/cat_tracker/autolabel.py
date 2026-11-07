"""Fill in the labels the stock model missed in a capture session, using the other cameras and time.

1. Each moment, its 3D position comes from whichever cameras did find it (triangulated, or one
   camera's box projected onto the floor), as in the live tracker.
2. A moment where no camera found it gets a position if the sightings just before and after it
   are close together in time (max_gap_s) and place (still_m): it lay still and the detector
   flickered. If it moved further than that between sightings, those moments are left alone.
3. Every camera that should see it at that position but has no box: its outline (a short cylinder
   about cat size) projected into that camera marks where to look, and the stock model is run again on
   an enlarged crop there, at a low bar (cat_tracker.snap). Its box is used; one scoring under
   check_below is marked "check". Where it finds nothing (half hidden, dim), the picture gets no box:
   on the test setup's hand-checked sessions the outline itself was right only 3% of the time, the crop's
   box 84%. (method: outline in the settings: the old way, the outline itself.)
2_label.bat runs it by itself when it opens a session that has pictures to decide and hasn't been autolabelled yet
(or was, the old way), from the current camera setup only (needs_run). Pictures already decided or skipped in
2_label.bat are never changed. Running it again redoes its own undecided boxes (listed in auto.json; the labels and
auto.json are backed up first). Added boxes are shown in orange in 2_label.bat, so check them.

By hand, from the engine folder:  python -m cat_tracker.autolabel                newest session
                                  python -m cat_tracker.autolabel --session 20261030-052100 --dry-run
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from capture.camera import camera_keys, camera_names
from cat_tracker import settings
from cat_tracker.label import read_boxes, write_boxes
from cat_tracker.locate import iou, locate, outline_box, room_bounds
from core.config import get, resolve_path
from fusion.triangulate import Rig
from tools.calib_room import load_intrinsics


METHOD_FILE = "autolabel_method.json"  # which method made a session's auto boxes (2_label offers to redo older ones)
METHOD = "crop"


def method_of(ses):
    """The method that made a session's auto boxes: "crop" (today's), "outline" (the old cat-sized outline), or None
    when the session has no auto boxes."""
    import json as _json
    if not (ses / "auto.json").is_file():
        return None
    try:
        return _json.loads((ses / METHOD_FILE).read_text(encoding="utf-8")).get("method", "outline")
    except (OSError, ValueError):
        return "outline"  # made before methods were recorded: the old way


def needs_run(ses, since):
    """True when the labelling tool should autolabel ses before opening it: it has pictures still to decide, it's
    from the current camera setup (since: the room calibration's time; the projection needs the calibration the
    pictures were taken with), and it was never autolabelled or was the old way."""
    ses = Path(ses)
    own = ses.name[len("labels-"):] if ses.name.startswith("labels-") else ses.name  # a practice copy
    if not since or own[:15] < since or not (ses / "images").is_dir():
        return False
    try:
        if json.loads((ses / METHOD_FILE).read_text(encoding="utf-8")).get("method") == METHOD:
            return False
    except (OSError, ValueError, AttributeError):
        pass
    done = set()
    for fn in ("checked.txt", "skipped.txt"):
        if (ses / fn).is_file():
            done |= set((ses / fn).read_text(encoding="utf-8").split())
    return any(p.stem not in done for p in (ses / "images").glob("*.jpg"))


def main(argv=None, progress=None, root=None):
    """progress(done, total): called as it goes through the moments (the labelling tool shows it). root: the folder
    the session is in (default my_data/captures)."""
    ap = argparse.ArgumentParser(description="Fill in missed cat labels from other cameras and nearby moments")
    ap.add_argument("--session")
    ap.add_argument("--dry-run", action="store_true", help="report what would be added, change nothing")
    ap.add_argument("--cpu", action="store_true", help="run the refining detector on the CPU")
    args = ap.parse_args(argv)
    cfg = settings.load()
    ac = get(cfg, "cat.autolabel", {}) or {}
    lc, dc = cfg["cat"]["locate"], dict(cfg["cat"]["detector"])
    root = Path(root) if root else resolve_path("my_data/captures")
    sessions = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    ses = root / args.session if args.session else (sessions[-1] if sessions else None)
    if ses is None or not (ses / "images").is_dir():
        print(f"No capture session found in {root}")
        return 1
    names = camera_names(cfg)
    data_dir = resolve_path(get(cfg, "calibration.dir", "my_data/calibration"))
    keys = camera_keys(cfg)
    with open(data_dir / "room.json", "r", encoding="utf-8") as f:
        from calibration.room import cameras_in_order
        room = cameras_in_order(json.load(f), keys)  # by calibration key: renamed cameras still match
    intrinsics = load_intrinsics(data_dir, keys)
    rig = Rig(room, intrinsics)
    bounds = room_bounds(rig, float(lc.get("room_margin_m", 0.15)))

    checked_file = ses / "checked.txt"
    checked = set(checked_file.read_text(encoding="utf-8").split()) if checked_file.is_file() else set()
    skipped_file = ses / "skipped.txt"
    keep = checked | (set(skipped_file.read_text(encoding="utf-8").split()) if skipped_file.is_file() else set())
    auto_file = ses / "auto.json"
    auto = json.loads(auto_file.read_text(encoding="utf-8")) if auto_file.is_file() else {}
    redo = {s for s in auto if s not in keep}  # its own earlier boxes, not decided yet: made again
    if redo and not args.dry_run:
        import shutil
        import time
        dest = resolve_path("my_data/backups") / f"autolabel_{ses.name}_{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copytree(ses / "labels", dest / "labels")
        shutil.copy2(auto_file, dest / "auto.json")
        print(f"Redoing {len(redo)} earlier automatic boxes not checked yet (the old ones: {dest})")
    for s in redo:
        auto.pop(s)
    moments = sorted({int(p.stem.rsplit("_", 1)[1]) for p in (ses / "images").glob("*.jpg")})
    times = {}
    if (ses / "moments.csv").is_file():
        for line in (ses / "moments.csv").read_text(encoding="utf-8").split():
            n, t = line.split(",")
            times[int(n)] = float(t)
    every = float(get(cfg, "cat.capture.every_s", 2.0))
    t_of = {n: times.get(n, n * every) for n in moments}
    w, h = 1280, 720
    first = next((ses / "images").glob("*.jpg"), None)
    if first is not None:
        h, w = cv2.imread(str(first)).shape[:2]

    # 1. where it is each moment, from the boxes there are (checked ones count fully)
    boxes = {}
    pos = {}
    for n in moments:
        per_cam = []
        for name in names:
            stem = f"{name}_{n:06d}"
            score = 1.0 if stem in checked else 0.5
            b = [] if stem in redo else read_boxes(ses / "labels" / f"{stem}.txt", w, h)
            per_cam.append(np.array([[*bb, score] for bb in b]).reshape(-1, 5))
        boxes[n] = per_cam
        X, used, how, _ = locate(rig, per_cam, lc, bounds)
        if X is not None:
            pos[n] = (X, how)

    # 2. moments between two nearby sightings in the same spot
    still_m, max_gap = float(ac.get("still_m", 0.3)), float(ac.get("max_gap_s", 8.0))
    seen = sorted(pos)
    filled = 0
    for a, b in zip(seen, seen[1:]):
        if b - a < 2 or t_of[b] - t_of[a] > max_gap:
            continue
        Xa, Xb = pos[a][0], pos[b][0]
        if np.linalg.norm((Xa - Xb)[[0, 2]]) > still_m:
            continue  # it moved: the moments in between can't be placed
        for n in moments:
            if a < n < b and n not in pos:
                pos[n] = ((Xa + Xb) / 2, "filled")
                filled += 1

    # 3. a box in every camera that should see it and has none
    det = crop_det = None
    method = str(ac.get("method", "crop"))
    check_below = float(ac.get("check_below", 0.2))
    if method == "crop":
        from cat_tracker import snap
        crop_det = snap.make_detector(cfg, cpu=args.cpu)
    refine = float(ac.get("refine_score", 0.05)) if method != "crop" else 0
    if refine > 0:
        from cat_tracker.detector import CatDetector
        dc["score"] = refine
        providers = ["CPUExecutionProvider"] if args.cpu else ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if not args.cpu:
            from pose import baseline
            baseline.prepare_onnxruntime(get(cfg, "onnxruntime", {}) or {})
        det = CatDetector(dc, resolve_path(dc["model"]), providers, require_gpu=not args.cpu)
    radius, half_h = float(ac.get("radius_m", 0.22)), float(ac.get("half_height_m", 0.15))
    added = {"cross": 0, "filled": 0, "refined": 0, "check": 0, "empty": 0}
    todo = sorted(pos.items())
    for k, (n, (X, how)) in enumerate(todo):
        if progress is not None:
            progress(k, len(todo))
        for c, name in enumerate(names):
            stem = f"{name}_{n:06d}"
            if stem in keep or len(boxes[n][c]):
                continue
            guess = outline_box(room["cameras"][c], intrinsics[c], X, radius, half_h, w, h)
            if guess is None:
                continue
            kind = "filled" if how == "filled" else "cross"
            if crop_det is not None:
                img = cv2.imread(str(ses / "images" / f"{stem}.jpg"))
                if img is None:  # that camera's picture is missing or unreadable: leave it alone
                    continue
                box, score = snap.crop_box(crop_det, img, guess)
                if box is None:  # not found there: no box beats a wrong one
                    added["empty"] += 1
                    if not args.dry_run:
                        write_boxes(ses / "labels" / f"{stem}.txt", [], w, h)
                    continue
                guess = box
                if score < check_below:
                    kind = "check"
                    added["check"] += 1
            elif det is not None:
                img = cv2.imread(str(ses / "images" / f"{stem}.jpg"))
                cand = [b for b in det([img])[0] if iou(b, guess) >= float(ac.get("refine_iou", 0.3))]
                if cand:
                    guess = list(cand[0][:4])
                    added["refined"] += 1
            added["filled" if how == "filled" else "cross"] += 1
            if not args.dry_run:
                write_boxes(ses / "labels" / f"{stem}.txt", [guess], w, h)
                auto[stem] = kind
    if not args.dry_run:
        for stem in redo - set(auto):  # an earlier automatic box not made again: back to no box, as it was
            write_boxes(ses / "labels" / f"{stem}.txt", [], w, h)
        auto_file.write_text(json.dumps(auto, indent=1), encoding="utf-8")
        (ses / METHOD_FILE).write_text(json.dumps({"method": method}), encoding="utf-8")
    print(f"Session {ses.name}: {len(moments)} moments, it was found in {len(seen)} and placed in {filled} more "
          f"between sightings in the same spot")
    print(f"{'Would add' if args.dry_run else 'Added'} {added['cross']} boxes from other cameras and {added['filled']} "
          f"from nearby moments" + (f" ({added['refined']} tightened by the model's weak guesses)" if method != "crop" else
                                    f": {added['check']} of them marked 'check this'. {added['empty']} pictures where "
                                    "it should be but the model found nothing are left without a box"))
    if not args.dry_run:
        print("They show in orange in 2_label.bat: delete any where it is hidden (behind the couch, under the desk)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
