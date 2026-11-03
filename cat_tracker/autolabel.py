"""Fill in the labels the stock model missed in a capture session, using the other cameras and time.

1. Each moment, its 3D position comes from whichever cameras did find it (triangulated, or one
   camera's box projected onto the floor), as in the live tracker.
2. A moment where no camera found it gets a position if the sightings just before and after it
   are close together in time (max_gap_s) and place (still_m): it lay still and the detector
   flickered. If it moved further than that between sightings, those moments are left alone.
3. Every camera that should see it at that position but has no box gets one: its outline (a
   short cylinder about cat size) projected into that camera. Where the stock model has a weak
   guess (above refine_score) overlapping that outline, its tighter box is used instead.
Images already checked in label.bat are never changed. Added boxes are listed in auto.json and
shown in orange in label.bat, so check them: a cat hidden behind the couch still gets a box.

From the camera core folder:  python -m cat_tracker.autolabel                newest session
                      python -m cat_tracker.autolabel --session 20261030-052100 --dry-run
"""

import argparse
import json

import cv2
import numpy as np

from capture.camera import camera_names
from cat_tracker import settings
from cat_tracker.label import read_boxes, write_boxes
from cat_tracker.locate import iou, locate, outline_box, room_bounds
from core.config import get, resolve_path
from fusion.triangulate import Rig
from tools.calib_room import load_intrinsics


def main():
    ap = argparse.ArgumentParser(description="Fill in missed cat labels from other cameras and nearby moments")
    ap.add_argument("--session")
    ap.add_argument("--dry-run", action="store_true", help="report what would be added, change nothing")
    ap.add_argument("--cpu", action="store_true", help="run the refining detector on the CPU")
    args = ap.parse_args()
    cfg = settings.load()
    ac = get(cfg, "cat.autolabel", {}) or {}
    lc, dc = cfg["cat"]["locate"], dict(cfg["cat"]["detector"])
    root = resolve_path("cat_tracker/captures")
    sessions = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    ses = root / args.session if args.session else (sessions[-1] if sessions else None)
    if ses is None or not (ses / "images").is_dir():
        print(f"No capture session found in {root}")
        return 1
    names = camera_names(cfg)
    data_dir = resolve_path(get(cfg, "calibration.dir", "calibration/data"))
    with open(data_dir / "room.json", "r", encoding="utf-8") as f:
        room = json.load(f)
    intrinsics = load_intrinsics(data_dir, names)
    rig = Rig(room, intrinsics)
    bounds = room_bounds(rig, float(lc.get("room_margin_m", 0.15)))

    checked_file = ses / "checked.txt"
    checked = set(checked_file.read_text(encoding="utf-8").split()) if checked_file.is_file() else set()
    auto_file = ses / "auto.json"
    auto = json.loads(auto_file.read_text(encoding="utf-8")) if auto_file.is_file() else {}
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
            b = read_boxes(ses / "labels" / f"{stem}.txt", w, h)
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
    det = None
    refine = float(ac.get("refine_score", 0.05))
    if refine > 0:
        from cat_tracker.detector import CatDetector
        dc["score"] = refine
        providers = ["CPUExecutionProvider"] if args.cpu else ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if not args.cpu:
            from pose import baseline
            baseline.prepare_onnxruntime(get(cfg, "onnxruntime", {}) or {})
        det = CatDetector(dc, resolve_path(dc["model"]), providers, require_gpu=not args.cpu)
    radius, half_h = float(ac.get("radius_m", 0.22)), float(ac.get("half_height_m", 0.15))
    added = {"cross": 0, "filled": 0, "refined": 0}
    for n, (X, how) in sorted(pos.items()):
        for c, name in enumerate(names):
            stem = f"{name}_{n:06d}"
            if stem in checked or len(boxes[n][c]):
                continue
            guess = outline_box(room["cameras"][c], intrinsics[c], X, radius, half_h, w, h)
            if guess is None:
                continue
            kind = "filled" if how == "filled" else "cross"
            if det is not None:
                img = cv2.imread(str(ses / "images" / f"{stem}.jpg"))
                cand = [b for b in det([img])[0] if iou(b, guess) >= float(ac.get("refine_iou", 0.3))]
                if cand:
                    guess = list(cand[0][:4])
                    added["refined"] += 1
            added[kind] += 1
            if not args.dry_run:
                write_boxes(ses / "labels" / f"{stem}.txt", [guess], w, h)
                auto[stem] = kind
    if not args.dry_run:
        auto_file.write_text(json.dumps(auto, indent=1), encoding="utf-8")
    print(f"Session {ses.name}: {len(moments)} moments, it was found in {len(seen)} and placed in {filled} more "
          f"between sightings in the same spot")
    print(f"{'Would add' if args.dry_run else 'Added'} {added['cross']} boxes from other cameras and {added['filled']} "
          f"from nearby moments ({added['refined']} tightened by the model's weak guesses)")
    if not args.dry_run:
        print("They show in orange in label.bat: delete any where it is hidden (behind the couch, under the desk)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
