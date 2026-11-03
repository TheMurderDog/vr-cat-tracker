"""Place every camera in SteamVR space using a tracker (or controller) with the printed marker on it.

Before running: SteamVR up (your usual way), the tracker on and tracking, every camera's lens
calibrated (calibration/data/intrinsics_<name>.json), the marker printed on stiff card with the tracker fixed
rigidly to it, sticking up past the card's edge so the card doesn't block its sensors.

Run from the repo root:  python -m tools.calib_room
Walk slowly around the whole room holding the marker face-up or toward the cameras, at different
heights (floor to head), pausing for a moment every step. On a tripod, tilt the head 20-30 degrees
forward or back at about every third stop (if the tracker only ever turns flat, camera heights can't
be pinned down). Each camera's counter climbs while it sees the marker and the tracker is still. When every camera reaches its target, or you press c,
it solves and saves calibration/data/room.json. q quits without solving.
Re-solve from the last recording without moving anything:  python -m tools.calib_room --resolve
"""

import argparse
import json
import pickle
import threading
import time

import cv2
import numpy as np

from calibration import intrinsics as intr
from calibration import room
from calibration.vr import VRPoller
from capture.camera import camera_names, open_cameras
from core.config import get, load_config, resolve_path
from core.runlog import start_run


def load_intrinsics(data_dir, names):
    out = []
    for name in names:
        p = data_dir / f"intrinsics_{name}.json"
        if not p.is_file():
            raise FileNotFoundError(f"{p} is missing; run calib_intrinsics for the {name} camera first")
        out.append(intr.load(p))
    return out


def solve_and_save(log, obs, intrinsics, names, rc, data_dir, refs):
    log.info("\nSolving from %d observations", len(obs))
    out = room.solve(obs, intrinsics, len(names), log=log, names=names)
    for cam, name in zip(out["cameras"], names):
        cam["name"] = name
    out["universe"] = "standing"
    out["created"] = time.strftime("%Y-%m-%d %H:%M:%S")
    good = all(c["rms_px"] <= float(rc.get("max_rms_px", 3.0)) for c in out["cameras"])
    path = data_dir / "room.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    for i, f in refs.items():
        cv2.imwrite(str(data_dir / f"reference_{names[i]}.png"), f)  # for the drift check
    log.info("\nRoom calibration %s. Saved %s", "GOOD" if good else
             "NOT GOOD (a camera is over %.1f px; record again with more varied positions)" % rc.get("max_rms_px", 3.0),
             path)
    return good


def main():
    ap = argparse.ArgumentParser(description="Place the cameras in SteamVR space")
    ap.add_argument("--config")
    ap.add_argument("--resolve", action="store_true", help="solve again from the last recording")
    args = ap.parse_args()
    cfg = load_config(args.config)
    rc = get(cfg, "calibration.room")
    log, log_file = start_run("calib_room", cfg)
    data_dir = resolve_path(get(cfg, "calibration.dir", "calibration/data"))
    names = camera_names(cfg)
    n = len(names)
    intrinsics = load_intrinsics(data_dir, names)
    rec_path = data_dir / "room_recording.pkl"

    if args.resolve:
        with open(rec_path, "rb") as f:
            rec = pickle.load(f)
        refs = {i: cv2.imread(str(data_dir / f"reference_{names[i]}.png")) for i in range(n)}
        ok = solve_and_save(log, rec["obs"], intrinsics, names, rc, data_dir, {k: v for k, v in refs.items() if v is not None})
        log.info("Log: %s", log_file)
        return 0 if ok else 1

    vr = VRPoller(get(cfg, "steamvr.tracking_universe", "standing"), int(rc.get("vr_rate_hz", 250)))
    for d in vr.devices():
        log.info("SteamVR device %d: %s %s", *d)
    idx, kind, serial = vr.pick(rc.get("device_serial"), rc.get("device", "tracker"))
    log.info("Using %s %s", kind, serial)
    vr.start()
    cams, errors = open_cameras(cfg, log)
    if errors:
        vr.stop()
        return 1

    detector_lock = threading.Lock()
    obs, last_kept, counts, latest_px, refs = [], {}, [0] * n, [None] * n, {}
    skipped = {"tracker lost": 0, "moving": 0, "same spot": 0}  # why marker sightings were not kept
    every = int(rc.get("detect_every_n_frames", 3))
    still = float(rc.get("still_speed_m_s", 0.05))
    spacing = float(rc.get("min_spacing_m", 0.05))
    marker_id = int(rc["marker_id"])
    latency_ns = int(float(rc.get("frame_latency_ms", 15)) * 1e6)
    detectors = [room.marker_detector(rc) for _ in range(n)]  # one each: detectors are not thread-safe

    def hook_for(c):
        k = {"n": 0}

        def hook(frame, t_ns):
            k["n"] += 1
            if c.slot not in refs:
                refs[c.slot] = frame.copy()
            if k["n"] % every:
                return
            px = room.find_marker(detectors[c.slot], frame, marker_id)
            latest_px[c.slot] = px
            if px is None:
                return
            s = vr.at(t_ns - latency_ns)  # the image was exposed a little before it arrived
            if s is None:
                skipped["tracker lost"] += 1
                return
            if s[2] > still:
                skipped["moving"] += 1
                return
            pos, rot, _ = s
            prev = last_kept.get(c.slot)
            if prev is not None and np.linalg.norm(pos - prev) < spacing:
                skipped["same spot"] += 1
                return
            with detector_lock:
                last_kept[c.slot] = pos
                obs.append((c.slot, px, pos, rot))
                counts[c.slot] += 1
        return hook

    for c in cams:
        c.frame_hook = hook_for(c)
        c.start()
    target = int(rc.get("target_per_camera", 25))
    tile_h = int(get(cfg, "preview.tile_height", 640))
    solved = None
    last_log = time.monotonic()
    try:
        while True:
            tiles = []
            for c in cams:
                item = c.latest(rotated=False)
                img = (np.zeros((int(cfg["cameras"]["height"]), int(cfg["cameras"]["width"]), 3), np.uint8)
                       if item is None else item[0].copy())
                if latest_px[c.slot] is not None:
                    cv2.circle(img, tuple(int(v) for v in latest_px[c.slot]), 18, (0, 255, 0), 3)
                if c.rotation is not None:
                    img = cv2.rotate(img, c.rotation)
                img = cv2.resize(img, (int(img.shape[1] * tile_h / img.shape[0]), tile_h), interpolation=cv2.INTER_AREA)
                done = counts[c.slot] >= target
                cv2.putText(img, f"{c.name}  {counts[c.slot]}/{target}", (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                            (80, 220, 80) if done else (0, 210, 255), 2, cv2.LINE_AA)
                tiles.append(img)
            s = vr.at(time.perf_counter_ns() - 20_000_000)
            bar = np.zeros((30, sum(t.shape[1] for t in tiles), 3), np.uint8)
            msg = ("tracker lost" if s is None else f"tracker speed {s[2]:.2f} m/s " + ("(still)" if s[2] <= still else "(moving)"))
            cv2.putText(bar, msg + "    c solve now   q quit", (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (235, 235, 235), 1,
                        cv2.LINE_AA)
            cv2.imshow("Room calibration", np.vstack([np.hstack(tiles), bar]))
            key = cv2.waitKey(30) & 0xFF
            if time.monotonic() - last_log > 5:
                log.info("kept so far: %s  (skipped: %s)", " ".join(f"{names[i]} {k}" for i, k in enumerate(counts)),
                         ", ".join(f"{k} {v}" for k, v in skipped.items()))
                last_log = time.monotonic()
            if key in (ord("q"), 27):
                break
            if key == ord("c") or min(counts) >= target:
                solved = True
                break
    finally:
        for c in cams:
            c.frame_hook = None
        for c in cams:
            c.stop()
        vr.stop()
        cv2.destroyAllWindows()
    log.info("Kept observations per camera: %s", counts)
    with open(rec_path, "wb") as f:
        pickle.dump({"obs": obs, "counts": counts}, f)
    if not solved:
        log.info("Quit without solving. Recording saved; solve it later with --resolve")
        log.info("Log: %s", log_file)
        return 1
    ok = solve_and_save(log, obs, intrinsics, names, rc, data_dir, refs)
    log.info("Log: %s", log_file)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
