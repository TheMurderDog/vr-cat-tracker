"""Quick check that no camera has moved since the room calibration.

Run from the repo root:  python -m tools.drift_check
Compares one fresh frame per camera with the reference frame saved by calib_room and reports how
far each image has shifted. Anything over calibration.drift.max_shift_px means that camera was
bumped: redo its room calibration (its lens calibration is still fine).
"""

import argparse
import time

import cv2
import numpy as np

from calibration.drift import image_shift
from capture.camera import open_cameras
from core.config import get, load_config, resolve_path
from core.runlog import start_run


def main():
    ap = argparse.ArgumentParser(description="Report which camera moved since calibration")
    ap.add_argument("--config")
    args = ap.parse_args()
    cfg = load_config(args.config)
    log, log_file = start_run("drift_check", cfg)
    data_dir = resolve_path(get(cfg, "calibration.dir", "calibration/data"))
    limit = float(get(cfg, "calibration.drift.max_shift_px", 2.0))
    cams, errors = open_cameras(cfg, log)
    for c in cams:
        c.start()
    time.sleep(1.5)
    moved, unsure = [], []
    min_conf = float(get(cfg, "calibration.drift.min_confidence", 0.2))
    for c in cams:
        ref = cv2.imread(str(data_dir / f"reference_{c.name}.png"))
        item = c.latest(rotated=False)
        if ref is None or item is None:
            log.warning("%s: %s", c.name, "no reference frame (run calib_room)" if ref is None else "no frame")
            unsure.append(c.name)
            continue
        dx, dy, conf = image_shift(ref, item[0])
        shift = float(np.hypot(dx, dy))
        if conf < min_conf:
            unsure.append(c.name)
            verdict = "UNSURE: the view changed too much to compare (people or things moved in front of it?)"
        elif shift > limit:
            moved.append(c.name)
            verdict = "MOVED"
        else:
            verdict = "ok"
        log.info("  %-6s shifted %.1f px (dx %.1f, dy %.1f), match confidence %.2f  %s", c.name, shift, dx, dy,
                 conf, verdict)
    for c in cams:
        c.stop()
    if moved:
        log.info("\nRecalibrate the room: %s moved.", ", ".join(moved))
    if unsure:
        log.info("\nCould not check %s; clear the room and run it again.", ", ".join(unsure))
    if errors:
        log.info("\nSome cameras did not open.")
    if not (moved or unsure or errors):
        log.info("\nAll cameras are where they were calibrated.")
    log.info("Log: %s", log_file)
    return 0 if not (moved or unsure or errors) else 1


if __name__ == "__main__":
    raise SystemExit(main())
