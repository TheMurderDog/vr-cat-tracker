"""Solve the lens calibrations again from their saved pictures, with the printer-stretch check, without any camera.

Run from engine/:  python -m tools.refit_lenses [--out DIR]
Reads my_data/calibration/intrinsics/<camera>/*.png (the views the wizard saved) and the current results, estimates
the board's height/width stretch per camera and for all cameras together (it's one board), and writes corrected
lens results to --out (default my_data/calibration/stretch_corrected), never over the live files. With a room
recording, it also solves the room again with the corrected lenses, into the same folder, so the two can be
compared. The current lens results are copied to my_data/backups first. Nothing is applied: to use the results,
copy them over the live ones yourself.
"""

import argparse
import json
import shutil
import time

import cv2
import numpy as np

from calibration import intrinsics as intr
from calibration import room_needs
from calibration.board import make_board
from capture.camera import camera_keys, camera_names
from core.config import DATA, get, load_config, resolve_path
from core.runlog import start_run


def load_views(frame_dir, detector, board, min_corners):
    views = []
    for p in sorted(frame_dir.glob("*.png")):
        v = intr.detect(detector, board, cv2.imread(str(p)))
        if v is not None and intr.usable(board, v, min_corners):
            views.append(v)
    return views


def joint_stretch(per_cam, size, factor, limit=0.05):
    """One stretch for every camera (the same board): the height/width that fits all their views best together."""
    from scipy.optimize import minimize_scalar
    kept = {}
    for name, (views, model) in per_cam.items():
        _, _, _, errs = intr.MODELS[model](views, size)
        bad = errs > factor * np.median(errs)
        kept[name] = ([v for v, b in zip(views, bad) if not b] if bad.any() and len(views) - bad.sum() >= 8 else
                      views, model)

    def total(a):
        out = 0.0
        for views, model in kept.values():
            rms = intr.MODELS[model](intr.stretch_views(views, a), size)[0]
            out += rms ** 2 * sum(len(v[1]) for v in views)
        return out
    r = minimize_scalar(total, bounds=(1 - limit, 1 + limit), method="bounded", options={"xatol": 2e-4})
    return float(r.x)


def main():
    ap = argparse.ArgumentParser(description="Re-solve the lens calibrations from saved pictures (printer stretch)")
    ap.add_argument("--config")
    ap.add_argument("--out", help="where the corrected results go (default my_data/calibration/stretch_corrected)")
    args = ap.parse_args()
    cfg = load_config(args.config)
    ic = get(cfg, "calibration.intrinsics")
    log, log_file = start_run("refit_lenses", cfg)
    cal = resolve_path(get(cfg, "calibration.dir", "my_data/calibration"))
    out = resolve_path(args.out) if args.out else cal / "stretch_corrected"
    names = camera_keys(cfg)  # the files' keys (the same as the names unless cameras were renamed)
    size = (int(cfg["cameras"]["width"]), int(cfg["cameras"]["height"]))
    board = make_board(get(cfg, "calibration.boards.small"))
    detector = intr.make_detector(board, ic)
    factor = float(ic.get("outlier_factor", 3.0))
    correct_above = float(ic.get("stretch_correct_above", 0.005))

    live = {n: cal / f"intrinsics_{n}.json" for n in names}
    backup = DATA / "backups" / f"lens_before_refit_{time.strftime('%Y%m%d-%H%M%S')}"
    backup.mkdir(parents=True, exist_ok=True)
    for p in live.values():
        if p.is_file():
            shutil.copy2(p, backup / p.name)
    log.info("Current lens results copied to %s", backup)
    out.mkdir(parents=True, exist_ok=True)

    per_cam, report = {}, {}
    for n in names:
        views = load_views(cal / "intrinsics" / n, detector, board, int(ic.get("min_corners", 8)))
        if len(views) < 8 or not live[n].is_file():
            log.warning("%s: %d saved views, %s; skipped", n, len(views), "result found" if live[n].is_file() else
                        "no result")
            continue
        old = intr.load(live[n])
        model = old["model"]
        stretch, rms_as_printed, rms_fit = intr.fit_stretch(views, size, model, factor)
        per_cam[n] = (views, model)
        report[n] = {"views": len(views), "model": model, "rms_px_live": round(float(old["rms_px"]), 4),
                     "stretch_this_camera": round(stretch, 5)}
        log.info("%s: %d views, %s; board height/width fits best at %.4f (RMS %.3f px as designed, %.3f px fitted)",
                 n, len(views), model, stretch, rms_as_printed, rms_fit)
    if not per_cam:
        log.error("No saved views to work from")
        return 1
    joint = joint_stretch(per_cam, size, factor)
    use = joint if abs(joint - 1) >= correct_above else 1.0
    log.info("\nAll cameras together: the board's height/width is %.4f (%+.2f%%); %s", joint, 100 * (joint - 1),
             "correcting for it" if use != 1.0 else "under the %.1f%% threshold: no correction" % (100 * correct_above))
    for n, (views, model) in per_cam.items():
        res = intr.calibrate(intr.stretch_views(views, use), size, models=(model,), outlier_factor=factor)
        res.update(board_stretch=round(use, 5), stretch_corrected=use != 1.0, status="GOOD"
                   if res["rms_px"] <= float(ic.get("max_rms_px", 0.8)) else "REDO")
        old = json.loads(live[n].read_text(encoding="utf-8"))
        intr.save(out / f"intrinsics_{n}.json", n, old.get("device_id"), size, res)
        report[n].update(rms_px_corrected=round(float(res["rms_px"]), 4), status=res["status"])
        log.info("  %-6s RMS %.3f px live -> %.3f px corrected  (%s)", n, report[n]["rms_px_live"], res["rms_px"],
                 "FIT GOOD" if res["status"] == "GOOD" else res["status"])

    rec_path = cal / "room_recording.json"
    if rec_path.is_file() and len(per_cam) == len(names):
        from tools.calib_room import load_recording
        rec = load_recording(rec_path)
        for label, folder in (("live lenses", cal), ("corrected lenses", out)):
            lenses = [intr.load(folder / f"intrinsics_{n}.json") for n in names]
            solved, needs = room_needs.try_solve(rec["obs"], lenses, names, size,
                                                 float(get(cfg, "calibration.room.max_rms_px", 3.0)))
            if solved is None:
                log.info("Room from the saved stops, %s: couldn't place every camera", label)
                continue
            for c, n in zip(solved["cameras"], names):
                c["name"] = n
                report[n][f"room_rms_px_{label.split()[0]}"] = round(float(c["rms_px"]), 3)
                report[n][f"room_position_m_{label.split()[0]}"] = [round(float(v), 4) for v in c["position_m"]]
            log.info("Room from the saved stops (%d), %s: %s", len(rec["obs"]), label,
                     ", ".join(f"{n} {c['rms_px']:.2f} px" for n, c in zip(names, solved["cameras"])))
            if folder == out:
                solved["created"] = time.strftime("%Y-%m-%d %H:%M:%S")
                solved["universe"] = "standing"
                with open(out / "room.json", "w", encoding="utf-8") as f:
                    json.dump(solved, f, indent=2)
        moved = [np.linalg.norm(np.subtract(report[n]["room_position_m_corrected"], report[n]["room_position_m_live"]))
                 for n in names if "room_position_m_corrected" in report[n] and "room_position_m_live" in report[n]]
        if moved:
            log.info("Camera positions moved by %s mm with the corrected lenses",
                     ", ".join(f"{1000 * m:.0f}" for m in moved))
    summary = {"joint_stretch": round(joint, 5), "applied_stretch": round(use, 5), "cameras": report,
               "backup": str(backup), "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(out / "refit_report.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    log.info("\nWritten to %s (nothing applied to the live files). Log: %s", out, log_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
