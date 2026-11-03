"""Find which camera ids open, and which of them deliver the configured mode.

Run from the repo root:  python -m tools.probe_cameras [--max-id 8]
For each id it opens the camera alone, asks for the mode in config.yaml (e.g. 1280x720
MJPG @ 30), reads frames for a couple of seconds and reports the size and fps it really got.
Use the result to fill cameras.ids in config.yaml.
"""

import argparse
import time

import cv2

from capture.camera import BACKENDS
from core.config import load_config
from core.runlog import start_run


def probe(device_id, c, seconds):
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
    ap.add_argument("--backend", choices=sorted(BACKENDS), help="override cameras.backend from config.yaml")
    args = ap.parse_args()
    cfg = load_config(args.config)
    log, log_file = start_run("probe_cameras", cfg)
    c = dict(cfg["cameras"])
    if args.backend:
        c["backend"] = args.backend
    log.info("Probing ids 0-%d on %s for %dx%d %s @ %d fps\n", args.max_id, c["backend"], c["width"], c["height"],
             c["fourcc"], c["fps"])
    good = []
    for i in range(args.max_id + 1):
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
        log.info("Put them in config.yaml as cameras.ids: %s (any order; preview shows which is which)", good)
    log.info("Log: %s", log_file)
    return 0 if good else 1


if __name__ == "__main__":
    raise SystemExit(main())
