"""Quick check that no camera has moved since the room calibration.

Run from engine/ (the step scripts do this):  python -m tools.drift_check
Compares one fresh frame per camera with the reference frame saved by calib_room, tile by tile (calibration.drift
judge), and reports how far each picture has shifted and what that means on the floor. Over
calibration.drift.recalibrate_px: that camera was bumped, redo the room calibration (the lens one is still fine).
Between max_shift_px and that: it moved a little, not enough to matter. A result is not an error: exit 1 only when
a camera couldn't be opened or checked.
"""

import argparse
import time

import cv2
import numpy as np

from calibration.drift import judge
from capture.camera import camera_keys, open_cameras
from core.config import get, load_config, resolve_path
from core.runlog import start_run


def main():
    ap = argparse.ArgumentParser(description="Report which camera moved since calibration")
    ap.add_argument("--config")
    args = ap.parse_args()
    cfg = load_config(args.config)
    log, log_file = start_run("drift_check", cfg)
    data_dir = resolve_path(get(cfg, "calibration.dir", "my_data/calibration"))
    limit = float(get(cfg, "calibration.drift.max_shift_px", 2.0))
    recal = float(get(cfg, "calibration.drift.recalibrate_px", 5.0))
    import json
    keys = camera_keys(cfg)
    cams, errors = open_cameras(cfg, log)
    for c in cams:
        c.start()
    time.sleep(1.5)
    moved, unsure, slight = [], [], []
    for c in cams:
        if c.state != "ok":
            log.warning("%s: not there (unplugged?), so it can't be checked", c.name)
            unsure.append(c.name)
            continue
        ref = cv2.imread(str(data_dir / f"reference_{keys[c.slot]}.png"))
        item = c.latest(rotated=False)
        if ref is None or item is None:
            log.warning("%s: %s", c.name, "no reference frame (run calib_room)" if ref is None else "no frame")
            unsure.append(c.name)
            continue
        v, shift, dx, dy, n = judge(ref, item[0], limit, recal)
        try:  # what the shift means: its angle, and how far that puts the cat off at 3 m
            fx = json.loads((data_dir / f"intrinsics_{keys[c.slot]}.json").read_text(encoding="utf-8"))["K"][0][0]
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            fx = 0.6 * item[0].shape[1]
        deg = float(np.degrees(np.arctan2(shift, fx)))
        cm = 300 * np.tan(np.radians(deg))
        if v == "unsure":
            unsure.append(c.name)
            say = "UNSURE: too much of the view changed to tell (people or things in front of it?)"
        elif v == "moved":
            moved.append(c.name)
            say = f"MOVED {deg:.1f} degrees (about {cm:.0f} cm at 3 m): redo the room calibration"
        elif v == "slight":
            slight.append(c.name)
            say = f"moved a little ({deg:.1f} degrees, about {cm:.0f} cm at 3 m): fine, nothing to do"
        else:
            say = "ok"
        log.info("  %-6s shifted %.1f px (dx %.1f, dy %.1f; %d of 12 parts of the picture agree)  %s", c.name, shift,
                 dx, dy, n, say)
    for c in cams:
        c.stop()
    if moved:
        log.info("\nRecalibrate the room: %s moved. Run 2_calibrate_cameras\\2_room_calibration.bat, then "
                 "3_check_calibration.bat (the lens calibration is still fine).", ", ".join(moved))
    elif slight:
        log.info("\n%s moved a little since the room calibration, not enough to matter. If the cat's marker ever "
                 "sits off in that camera's part of the room, redo the room calibration.", ", ".join(slight))
    if unsure:
        log.info("\nCould not check %s; clear the room and run it again.", ", ".join(unsure))
    if errors:
        log.info("\nSome cameras did not open.")
    if not (moved or unsure or errors or slight):
        log.info("\nAll cameras are where they were calibrated.")
    log.info("Log: %s", log_file)
    return 1 if errors else 0  # a camera that moved is a result, not a failure


if __name__ == "__main__":
    from core.runlog import exit_now
    exit_now(main())  # for certain: the cameras are free for the next tool at once
