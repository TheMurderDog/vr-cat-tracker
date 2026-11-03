"""Try the cat detector on footage, with no cameras or SteamVR needed.

From the camera core folder:
  python -m cat_tracker.check_recording                    newest session in recordings/
  python -m cat_tracker.check_recording --session 20261022-221944_main --every 15
  python -m cat_tracker.check_recording --image some_photo.jpg
For a recording it runs every Nth frame of all four cameras, locates her like the live tracker does,
and saves a sheet of the frames where she was found to cat_tracker/logs/snapshots. Record a session
with her in the room (the camera core's recorder; the public camera core has no recorder, so use --image) to see how well she is found.
"""

import argparse
import json
import time

import cv2
import numpy as np

from capture.camera import camera_names
from cat_tracker import settings
from cat_tracker.detector import CatDetector, draw
from cat_tracker.locate import locate, room_bounds
from core.config import get, resolve_path
from core.runlog import start_run
from fusion.triangulate import Rig
from tools.calib_room import load_intrinsics


def main():
    ap = argparse.ArgumentParser(description="Cat detector on recorded footage")
    ap.add_argument("--session", help="folder name under recordings/ (default: newest)")
    ap.add_argument("--image", help="a single photo instead of a recording")
    ap.add_argument("--every", type=int, default=10, help="use every Nth recorded frame")
    ap.add_argument("--max-sheets", type=int, default=24, help="frames with a cat to save as pictures")
    ap.add_argument("--cpu", action="store_true", help="run the model on the CPU (slow)")
    args = ap.parse_args()
    cfg = settings.load()
    dc, lc = cfg["cat"]["detector"], cfg["cat"]["locate"]
    log, log_file = start_run("cat_check", cfg)
    providers = ["CPUExecutionProvider"] if args.cpu else ["CUDAExecutionProvider", "CPUExecutionProvider"]
    if not args.cpu:
        from pose import baseline
        baseline.prepare_onnxruntime(get(cfg, "onnxruntime", {}) or {})
    det = CatDetector(dc, resolve_path(dc["model"]), providers, require_gpu=not args.cpu)
    snap_dir = resolve_path(cfg["logging"]["dir"]) / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)

    if args.image:
        img = cv2.imread(args.image)
        if img is None:
            log.error("Can't read %s", args.image)
            return 1
        boxes = det([img])[0]
        log.info("%d cat(s) found: %s", len(boxes), np.round(boxes, 2).tolist())
        draw(img, boxes, 0)
        p = snap_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_cat_image.jpg"
        cv2.imwrite(str(p), img)
        log.info("Saved %s", p)
        return 0

    rec_dir = resolve_path(get(cfg, "recording.dir", "recordings"))
    sessions = sorted(p for p in rec_dir.iterdir() if p.is_dir()) if rec_dir.is_dir() else []
    if args.session:
        sessions = [rec_dir / args.session]
    if not sessions or not sessions[-1].is_dir():
        log.error("No recording found in %s", rec_dir)
        return 1
    ses = sessions[-1]
    names = camera_names(cfg)
    # the session keeps its own copy of the calibration it was recorded with
    cal = ses if (ses / "room.json").is_file() else resolve_path(get(cfg, "calibration.dir", "calibration/data"))
    with open(cal / "room.json", "r", encoding="utf-8") as f:
        rig = Rig(json.load(f), load_intrinsics(cal, names))
    caps = [cv2.VideoCapture(str(ses / f"cam_{n}.avi")) for n in names]
    if not all(c.isOpened() for c in caps):
        log.error("Missing camera videos in %s", ses)
        return 1
    bounds = room_bounds(rig, float(lc.get("room_margin_m", 0.15)))
    log.info("Session %s (calibration from %s), every %d frames", ses.name, cal, args.every)
    frame_i, done, saved = 0, 0, 0
    found = {"triangulated": 0, "floor": 0}
    per_cam = np.zeros(len(names), int)
    t0 = time.perf_counter()
    while True:
        frames = []
        for c in caps:
            ok, f = c.read()
            frames.append(f if ok else None)
        if any(f is None for f in frames):
            break
        frame_i += 1
        if frame_i % args.every:
            continue
        done += 1
        boxes_all = det(frames)
        X, used, how, picked = locate(rig, boxes_all, lc, bounds)
        per_cam += [b is not None for b in picked]
        if X is None:
            continue
        found[how] += 1
        log.info("frame %d: cat at x %.2f y %.2f z %.2f m (%s, %d cameras)", frame_i, *X, how, used)
        if saved < args.max_sheets:
            tl = []
            for i, f in enumerate(frames):
                img = f.copy()
                draw(img, boxes_all[i], color=(120, 120, 120))
                if picked[i] is not None:
                    draw(img, [picked[i]], 0)
                cv2.putText(img, names[i], (12, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3, cv2.LINE_AA)
                tl.append(cv2.resize(img, (640, 360), interpolation=cv2.INTER_AREA))
            g = np.vstack([np.hstack(tl[:2]), np.hstack(tl[2:])])
            cv2.imwrite(str(snap_dir / f"{ses.name}_cat_{frame_i:06d}.jpg"), g)
            saved += 1
    dt = time.perf_counter() - t0
    log.info("Checked %d moments (one frame from each of %d cameras) in %.0f s", done, len(names), dt)
    log.info("Cat found in %d moments: %d triangulated, %d from one camera on the floor", sum(found.values()),
             found["triangulated"], found["floor"])
    log.info("Per camera: %s", ", ".join(f"{n} {k}" for n, k in zip(names, per_cam)))
    log.info("Pictures: %s (%d saved)  Log: %s", snap_dir, saved, log_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
