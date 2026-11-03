"""Intrinsics wizard: hold the small board in front of one camera, it captures views by itself.

Run from the repo root:
  python -m tools.calib_intrinsics --cam cam1          live wizard for one camera (name from cameras.names, or number)
  python -m tools.calib_intrinsics --cam cam1 --from-dir   recalibrate from the frames saved last time

In the window: move the board slowly through the whole picture, near and far, tilted left, right,
up and down, and into the corners. A view is captured when the board is held still and differs
enough from earlier views. Green cells on the grid are covered. When the target number of views
is reached it calibrates by itself; press c to calibrate early, space to force a capture, q to quit.
Result: calibration/data/intrinsics_<name>.json, plus the frames in calibration/data/intrinsics/<name>/.
"""

import argparse
import time

import cv2
import numpy as np

from calibration import intrinsics as intr
from calibration.board import make_board
from capture.camera import Camera, camera_names, camera_slot
from core.config import get, load_config, resolve_path
from core.runlog import start_run


def novelty(view, accepted):
    """Smallest mean corner distance to any accepted view sharing corners (large = new pose)."""
    best = np.inf
    for a in accepted:
        common, ia, ib = np.intersect1d(view[2], a[2], return_indices=True)
        if len(common) < 4:
            continue
        best = min(best, float(np.mean(np.linalg.norm(view[1][ia] - a[1][ib], axis=1))))
    return best


def run_calibration(log, views, size, ic, out_path, cam_name, device_id):
    cov, _ = intr.coverage(views, size)
    log.info("Calibrating %s from %d views, %.0f%% of the image covered", cam_name, len(views), 100 * cov)
    res = intr.calibrate(views, size, models=ic.get("models", ["fisheye", "rational"]),
                         outlier_factor=float(ic.get("outlier_factor", 3.0)), log=log)
    intr.save(out_path, cam_name, device_id, size, res)
    good = res["rms_px"] <= float(ic.get("max_rms_px", 0.8)) and cov >= float(ic.get("min_coverage", 0.6))
    log.info("\n%s: %s model, RMS %.3f px, coverage %.0f%%  ->  %s", cam_name, res["model"], res["rms_px"], 100 * cov,
             "GOOD" if good else "REDO (want RMS <= %.2f px and coverage >= %.0f%%)" % (
                 float(ic.get("max_rms_px", 0.8)), 100 * float(ic.get("min_coverage", 0.6))))
    log.info("Saved %s", out_path)
    return res, good


def main():
    ap = argparse.ArgumentParser(description="Per-camera intrinsics wizard")
    ap.add_argument("--config")
    ap.add_argument("--cam", required=True, help="camera name from cameras.names (e.g. cam1) or number from 1")
    ap.add_argument("--from-dir", action="store_true", help="recalibrate from saved frames, no camera needed")
    args = ap.parse_args()
    cfg = load_config(args.config)
    ic = get(cfg, "calibration.intrinsics", {}) or {}
    slot = camera_slot(cfg, args.cam)
    name = camera_names(cfg)[slot]
    log, log_file = start_run(f"calib_intrinsics_{name}", cfg)
    board = make_board(get(cfg, "calibration.boards.small"))
    detector = intr.make_detector(board, ic)
    data_dir = resolve_path(get(cfg, "calibration.dir", "calibration/data"))
    frame_dir = data_dir / "intrinsics" / name
    out_path = data_dir / f"intrinsics_{name}.json"
    c = cfg["cameras"]
    size = (int(c["width"]), int(c["height"]))
    min_corners = int(ic.get("min_corners", 8))

    if args.from_dir:
        views = []
        for p in sorted(frame_dir.glob("*.png")):
            v = intr.detect(detector, board, cv2.imread(str(p)))
            if v is not None and intr.usable(board, v, min_corners):
                views.append(v)
        log.info("%d usable views in %s", len(views), frame_dir)
        if len(views) < 8:
            log.error("Need at least 8 views")
            return 1
        _, good = run_calibration(log, views, size, ic, out_path, name, c["ids"][slot])
        log.info("Log: %s", log_file)
        return 0 if good else 1

    rot = c.get("rotate", "none")
    rotation = rot[slot] if isinstance(rot, list) else rot
    cam = Camera(slot, c["ids"][slot], c, rotation)
    cam.open()
    cam.start()
    frame_dir.mkdir(parents=True, exist_ok=True)
    for old in frame_dir.glob("*.png"):
        old.unlink()  # a new session replaces the previous frames
    target = int(ic.get("target_views", 40))
    still_px = float(ic.get("still_px", 1.5))
    novelty_px = float(ic.get("novelty_px", 40))
    views, last, last_seq, flash_until = [], None, -1, 0.0
    tile_h = int(get(cfg, "preview.tile_height", 640)) + 200
    win = f"Intrinsics {name}"
    log.info("Hold the small board in front of the %s camera. Target %d views.", name, target)
    result = None
    try:
        while True:
            item = cam.latest(rotated=False)
            if item is None or item[2] == last_seq:
                if cv2.waitKey(5) & 0xFF in (ord("q"), 27):
                    break
                continue
            frame, _, last_seq = item
            v = intr.detect(detector, board, frame)
            force = False
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" "):
                force = True
            status = "no board"
            if v is not None and intr.usable(board, v, min_corners):
                still = False
                if last is not None:
                    common, ia, ib = np.intersect1d(v[2], last[2], return_indices=True)
                    still = len(common) >= min_corners and np.mean(np.linalg.norm(v[1][ia] - last[1][ib], axis=1)) < still_px
                new = novelty(v, views) > novelty_px
                status = "hold still" if new and not still else "move to a new pose" if not new else "captured"
                if (still and new) or force:
                    views.append(v)
                    cv2.imwrite(str(frame_dir / f"{len(views):03d}.png"), frame)
                    flash_until = time.monotonic() + 0.25
                    log.info("view %d: %d corners", len(views), len(v[2]))
                last = v
            elif v is not None:
                status = "board too small, cut off or edge-on"
                last = None
            else:
                last = None

            disp = frame.copy()
            cov, hit = intr.coverage(views, size) if views else (0.0, np.zeros((6, 8), bool))
            gh, gw = hit.shape
            for gy in range(gh):
                for gx in range(gw):
                    x0, y0 = gx * size[0] // gw, gy * size[1] // gh
                    x1, y1 = (gx + 1) * size[0] // gw, (gy + 1) * size[1] // gh
                    if hit[gy, gx]:
                        disp[y0:y1, x0:x1, 1] = np.clip(disp[y0:y1, x0:x1, 1].astype(np.int16) + 50, 0, 255)
                    cv2.rectangle(disp, (x0, y0), (x1, y1), (90, 90, 90), 1)
            if v is not None:
                for p in v[1]:
                    cv2.circle(disp, (int(p[0]), int(p[1])), 4, (0, 255, 255), -1)
            if time.monotonic() < flash_until:
                disp = cv2.addWeighted(disp, 0.5, np.full_like(disp, 255), 0.5, 0)
            if cam.rotation is not None:
                disp = cv2.rotate(disp, cam.rotation)
            scale = tile_h / disp.shape[0]
            disp = cv2.resize(disp, (int(disp.shape[1] * scale), tile_h), interpolation=cv2.INTER_AREA)
            for i, (text, color) in enumerate([
                (f"{name}  views {len(views)}/{target}  coverage {cov * 100:.0f}%", (255, 255, 255)),
                (status, (80, 220, 80) if status == "captured" else (0, 210, 255)),
                ("space capture  c calibrate  q quit", (200, 200, 200)),
            ]):
                cv2.putText(disp, text, (10, 28 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 4, cv2.LINE_AA)
                cv2.putText(disp, text, (10, 28 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 1, cv2.LINE_AA)
            cv2.imshow(win, disp)
            if (len(views) >= target or key == ord("c")) and len(views) >= 8:
                result = run_calibration(log, views, size, ic, out_path, name, c["ids"][slot])
                break
    finally:
        cam.stop()
        cv2.destroyAllWindows()
    if result is None:
        log.info("Stopped with %d views; nothing calibrated. Frames kept in %s", len(views), frame_dir)
    log.info("Log: %s", log_file)
    return 0 if result and result[1] else 1


if __name__ == "__main__":
    raise SystemExit(main())
