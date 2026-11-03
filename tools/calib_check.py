"""Room calibration check: does the tracker's SteamVR position land on the tracker in every camera?

Run from the repo root (SteamVR up, the marked tracker on):  python -m tools.calib_check
Each tile draws a red ring where SteamVR says the marker is, and a green ring where the camera
sees it. They should sit on top of each other everywhere in the room. The log records the pixel
gap per camera every few seconds and a summary at the end. q quits.
"""

import argparse
import json
import time

import cv2
import numpy as np

from calibration import room
from calibration.vr import VRPoller
from capture.camera import camera_names, open_cameras
from core.config import get, load_config, resolve_path
from core.runlog import start_run
from tools.calib_room import load_intrinsics


def main():
    ap = argparse.ArgumentParser(description="Overlay the tracker's SteamVR position on every camera")
    ap.add_argument("--config")
    ap.add_argument("--seconds", type=float, default=0, help="stop after this long")
    args = ap.parse_args()
    cfg = load_config(args.config)
    rc = get(cfg, "calibration.room")
    log, log_file = start_run("calib_check", cfg)
    data_dir = resolve_path(get(cfg, "calibration.dir", "calibration/data"))
    with open(data_dir / "room.json", "r", encoding="utf-8") as f:
        rm = json.load(f)
    names = camera_names(cfg)
    n = len(names)
    intrinsics = load_intrinsics(data_dir, names)
    offset = np.array(rm["marker_offset_m"])
    vr = VRPoller(get(cfg, "steamvr.tracking_universe", "standing"), int(rc.get("vr_rate_hz", 250)))
    vr.pick(rc.get("device_serial"), rc.get("device", "tracker"))
    vr.start()
    cams, errors = open_cameras(cfg, log)
    for c in cams:
        c.start()
    detectors = [room.marker_detector(rc) for _ in range(n)]
    latency_ns = int(float(rc.get("frame_latency_ms", 15)) * 1e6)
    gaps = {c.slot: [] for c in cams}
    tile_h = int(get(cfg, "preview.tile_height", 640))
    t0 = last_log = time.monotonic()
    try:
        while True:
            tiles = []
            for c in cams:
                item = c.latest(rotated=False)
                if item is None:
                    continue
                img, t_ns, _ = item
                img = img.copy()
                s = vr.at(t_ns - latency_ns)
                pred = None
                if s is not None:
                    pred = room.project_vr_point(s[0] + s[1] @ offset, rm["cameras"][c.slot], intrinsics[c.slot])
                seen = room.find_marker(detectors[c.slot], img, int(rc["marker_id"]))
                if pred is not None and 0 <= pred[0] < img.shape[1] and 0 <= pred[1] < img.shape[0]:
                    cv2.circle(img, (int(pred[0]), int(pred[1])), 22, (60, 60, 255), 3)
                if seen is not None:
                    cv2.circle(img, (int(seen[0]), int(seen[1])), 14, (80, 220, 80), 3)
                    if pred is not None and s[2] < 0.3:
                        gaps[c.slot].append(float(np.linalg.norm(pred - seen)))
                if c.rotation is not None:
                    img = cv2.rotate(img, c.rotation)
                img = cv2.resize(img, (int(img.shape[1] * tile_h / img.shape[0]), tile_h), interpolation=cv2.INTER_AREA)
                g = gaps[c.slot][-60:]
                cv2.putText(img, f"{c.name}  gap {np.median(g):.1f} px" if g else c.name,
                            (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (235, 235, 235), 2, cv2.LINE_AA)
                tiles.append(img)
            if tiles:
                cv2.imshow("Calibration check (red = SteamVR, green = camera)", np.hstack(tiles))
            if cv2.waitKey(15) & 0xFF in (ord("q"), 27):
                break
            now = time.monotonic()
            if now - last_log > 5:
                log.info("median gap px: %s", {names[k]: round(float(np.median(v[-200:])), 1) if v else None
                                                for k, v in gaps.items()})
                last_log = now
            if args.seconds and now - t0 > args.seconds:
                break
    finally:
        for c in cams:
            c.stop()
        vr.stop()
        cv2.destroyAllWindows()
    log.info("\nSummary (pixels between where SteamVR puts the marker and where the camera sees it)")
    for k, v in gaps.items():
        if v:
            log.info("  %-6s median %.1f px, 90%% under %.1f px, from %d frames", names[k], np.median(v),
                     np.percentile(v, 90), len(v))
        else:
            log.info("  %-6s never saw the marker", names[k])
    log.info("Log: %s", log_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
