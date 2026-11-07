"""Find which camera ids open, and which of them deliver the configured mode.

Run from engine/ (the step scripts do this):  python -m tools.probe_cameras [--max-id 8]
For each id it opens the camera alone, asks for the mode in settings/cameras.yaml (e.g. 1280x720
MJPG @ 30), reads frames for a couple of seconds and reports the size and fps it really got.
Troubleshooting for 1_connect_cameras/1_set_up_cameras.bat, which sets cameras.ids for you. With the dshow
driver it also prints each device's name, and skips devices in cameras.exclude (--all tries them too).
"""

import argparse
import time

import cv2

from capture.camera import BACKENDS, excluded, fps_list
from capture.devices import list_devices
from core.config import load_config
from core.runlog import start_run
from core.single import hold_cameras


def probe(device_id, c, seconds):
    hold_cameras()  # wait while another tool still has the cameras
    cap = cv2.VideoCapture(device_id, BACKENDS[c.get("backend", "msmf")])
    if not cap.isOpened():
        return None
    try:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*c.get("fourcc", "MJPG")))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, c["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, c["height"])
        cap.set(cv2.CAP_PROP_FPS, c["fps"])
        ok, frame = cap.read()  # first frame can be slow while the stream starts
        if not ok:
            return {"opened": True, "frames": 0}
        # Some backends return the same buffer again instead of waiting for a new frame,
        # so count only frames whose pixels changed, and report the raw loop rate separately.
        reads, new, prev, t0 = 0, 0, None, time.perf_counter()
        while time.perf_counter() - t0 < seconds:
            ok, f = cap.read()
            if not ok:
                continue
            reads += 1
            sig = f[::24, ::24].tobytes()
            if sig != prev:
                new += 1
                prev = sig
        dt = time.perf_counter() - t0
        return {"opened": True, "frames": new, "fps": new / dt, "loop_rate": reads / dt,
                "size": f"{frame.shape[1]}x{frame.shape[0]}",
                "reported_fps": cap.get(cv2.CAP_PROP_FPS), "backend": cap.getBackendName()}
    finally:
        cap.release()


def main():
    ap = argparse.ArgumentParser(description="Probe camera ids")
    ap.add_argument("--config")
    ap.add_argument("--max-id", type=int, default=8)
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--backend", choices=sorted(BACKENDS), help="override cameras.backend from settings/cameras.yaml")
    ap.add_argument("--all", action="store_true", help="also try devices in cameras.exclude")
    args = ap.parse_args()
    cfg = load_config(args.config)
    log, log_file = start_run("probe_cameras", cfg)
    c = dict(cfg["cameras"])
    c["fps"] = max(fps_list(cfg))  # probe at the fastest speed any camera uses
    if args.backend:
        c["backend"] = args.backend
    log.info("Probing ids 0-%d on %s for %dx%d %s @ %d fps\n", args.max_id, c["backend"], c["width"], c["height"],
             c["fourcc"], c["fps"])
    devs = list_devices() if c["backend"] == "dshow" else None
    if devs is not None:
        log.info("Windows lists %d camera(s): %s\n", len(devs), ", ".join(f"id {i} {n}" for i, (n, _) in enumerate(devs)))
    good = []
    for i in range(args.max_id + 1 if devs is None else len(devs)):
        if devs is not None and excluded(c, *devs[i]) and not args.all:
            log.info("id %d (%s): excluded in settings (cameras.exclude), not opened; --all tries it", i, devs[i][0])
            continue
        r = probe(i, c, args.seconds)
        if r is None:
            log.info("id %d: nothing", i)
        elif not r["frames"]:
            log.info("id %d: opened but gave no frames", i)
        else:
            hit = r["size"] == f"{c['width']}x{c['height']}" and r["fps"] >= 0.9 * c["fps"]
            if hit:
                good.append(i)
            log.info("id %d: %s %s, %.1f new frames/s (read loop %.0f/s, driver says %.0f fps) %s", i, r["backend"],
                     r["size"], r["fps"], r["loop_rate"], r["reported_fps"], "<- matches config mode" if hit else "")
    log.info("\nIds delivering the configured mode: %s", good or "none")
    if good:
        log.info("They can be used: run 1_connect_cameras\\1_set_up_cameras.bat to pick, name and order them")
    log.info("Log: %s", log_file)
    return 0 if good else 1


if __name__ == "__main__":
    from core.runlog import exit_now
    exit_now(main())  # for certain: the cameras are free for the next tool at once
