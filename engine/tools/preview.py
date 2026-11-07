"""Live preview of every camera, and a capture soak test.

Run from engine/ (1_connect_cameras/troubleshoot_preview_cameras.bat does this):
  python -m tools.preview                      window with all cameras and live numbers
  python -m tools.preview --seconds 600        same, stops after 10 minutes and prints a verdict
  python -m tools.preview --seconds 60 --no-window   headless soak test

Keys in the window:
  1-9      select a camera            p   open the selected camera's driver settings dialog
  [ / ]    exposure one step shorter / longer on ALL cameras (Windows backends only)
  s        save a snapshot of every camera to my_data/logs/cameras/snapshots/
  q / Esc  quit

Numbers per camera: fps over the last 2 s, frames dropped (fewer frames than cameras.fps
should have delivered), stalls (arrival gaps over 1.5 frames),
flicker % (brightness swing of each image row band over the flicker window; keep the
scene still while reading it), and the exposure/gain the driver reports back.
"""

import argparse
import datetime as _dt
import time

import cv2
import numpy as np

from capture.camera import camera_names, exposure_ms_to_step, exposure_step_to_ms, open_cameras, outlined_text, tile_grid
from core.config import get, load_config, resolve_path
from core.runlog import start_run

GREEN, YELLOW, RED, WHITE = (80, 220, 80), (0, 210, 255), (60, 60, 255), (235, 235, 235)


def tile(cam, height, selected):
    item = cam.latest(rotated=True)
    if item is None:
        img = np.zeros((height, int(height * 9 / 16), 3), np.uint8)
    else:
        frame = item[0]
        img = cv2.resize(frame, (int(frame.shape[1] * height / frame.shape[0]), height),
                         interpolation=cv2.INTER_AREA)
    st, rb, target = cam.stats, cam.readback, cam.fps
    fps, flick = st.fps(), st.flicker_pct()
    lines = [
        (f"{cam.slot + 1} {cam.name}  (id {cam.device_id})", WHITE),
        (f"{fps:6.1f} fps", GREEN if fps >= 0.97 * target else RED),
        (f"dropped {st.dropped}  stalls {st.stalls}", GREEN if st.dropped == 0 and not st.read_failures else YELLOW),
        (f"flicker {'...' if flick is None else f'{flick:.1f}%'}",
         WHITE if flick is None else GREEN if flick < 20 else YELLOW if flick < 40 else RED),  # p-p %: harmless under 40 (docs/technical/camera_checks.md)
        (f"exp {rb.get('exposure', float('nan')):.0f}  gain {rb.get('gain', float('nan')):.0f}", WHITE),
        (f"bright {st.brightness():.0f}/255", WHITE),
    ]
    panel = img[: 12 + 24 * len(lines)]
    panel[:] = (panel * 0.35).astype(np.uint8)  # darken behind the text so it reads on any scene
    for i, (text, color) in enumerate(lines):
        outlined_text(img, text, (8, 24 + i * 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)
    if selected:
        cv2.rectangle(img, (0, 0), (img.shape[1] - 1, img.shape[0] - 1), YELLOW, 3)
    return img


def log_stats(log, cams):
    for c in cams:
        st = c.stats
        flick = st.flicker_pct()
        log.info("%-6s fps %.1f (mean %.2f) dropped %d stalls %d dup %d fail %d max_gap %.1f ms flicker %s bright %.0f",
                 c.name, st.fps(), st.mean_fps(), st.dropped, st.stalls, st.duplicates, st.read_failures,
                 st.max_gap_ms,
                 "n/a" if flick is None else f"{flick:.2f}%", st.brightness())


def verdict(log, cams, cfg):
    log.info("\nSummary")
    ok_all = True
    for c in cams:
        st, target = c.stats, c.fps
        expected = max(st.frames + st.dropped, 1)
        drop_pct = 100.0 * st.dropped / expected
        flick = st.flicker_pct()
        ok = st.mean_fps() >= 0.97 * target and drop_pct < 0.5 and st.read_failures == 0
        ok_all &= ok
        log.info("  [%s] %s (id %d): mean %.2f fps, %d frames, dropped %d (%.2f%%), stalls %d, failures %d, "
                 "max gap %.1f ms, flicker %s",
                 "PASS" if ok else "FAIL", c.name, c.device_id, st.mean_fps(), st.frames, st.dropped,
                 drop_pct, st.stalls, st.read_failures, st.max_gap_ms, "n/a" if flick is None else f"{flick:.2f}%")
    return ok_all


def main():
    ap = argparse.ArgumentParser(description="Live camera preview and capture soak test")
    ap.add_argument("--config")
    ap.add_argument("--seconds", type=float, default=0, help="stop after this long and print a verdict")
    ap.add_argument("--no-window", action="store_true")
    args = ap.parse_args()

    cfg = load_config(args.config)
    log, log_file = start_run("preview", cfg)
    cams, errors = open_cameras(cfg, log)
    if not cams:
        log.error("No cameras opened. Check cameras.ids and cameras.backend in settings/cameras.yaml, "
                  "or run: 1_connect_cameras\\1_set_up_cameras.bat")
        return 1
    for c in cams:
        c.start()
    log.info("%d of %d cameras running. Log: %s", len(cams), len(cfg["cameras"]["ids"]), log_file)

    exp_step = exposure_ms_to_step(float(cfg["cameras"].get("exposure_ms") or 7.8))
    selected = 0
    watching = False  # closing the window quits (set up once it has been shown)
    tile_h = int(get(cfg, "preview.tile_height", 640))
    log_every = float(get(cfg, "preview.log_every_s", 5))
    snap_dir = resolve_path(get(cfg, "logging.dir", "my_data/logs/cameras")) / "snapshots"
    t0 = last_log = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            if now - last_log >= log_every:
                log_stats(log, cams)
                last_log = now
            if args.seconds and now - t0 >= args.seconds:
                break
            if args.no_window:
                time.sleep(0.05)
                continue
            grid = tile_grid([tile(c, tile_h, i == selected) for i, c in enumerate(cams)])
            bar = np.zeros((28, grid.shape[1], 3), np.uint8)
            outlined_text(bar, f"exposure step {exp_step} = {exposure_step_to_ms(exp_step):.2f} ms   "
                        "[1-9] select  [p] driver settings  [ [ ] ] exposure  [s] snapshot  [q] quit",
                        (8, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 1, cv2.LINE_AA)
            if not watching:
                from tools.window import quit_when_closed
                quit_when_closed("Cameras")  # closing the window quits, as q does
                watching = True
            cv2.imshow("Cameras", np.vstack([grid, bar]))
            key = cv2.waitKey(15) & 0xFF
            if key in (ord("q"), 27):
                break
            if ord("1") <= key <= ord(str(min(len(cams), 9))):
                selected = key - ord("1")
            elif key == ord("p"):
                cams[min(selected, len(cams) - 1)].queue_set("settings_dialog")
                log.info("Opened driver settings for %s", cams[selected].name)
            elif key in (ord("["), ord("]")) and cfg["cameras"].get("exposure_units", "log2_s") == "log2_s":
                exp_step += -1 if key == ord("[") else 1
                for c in cams:
                    c.queue_set(cv2.CAP_PROP_EXPOSURE, exp_step)
                log.info("Exposure step %d (%.2f ms) on all cameras; put exposure_ms: %.2f in settings/cameras.yaml to keep it",
                         exp_step, exposure_step_to_ms(exp_step), exposure_step_to_ms(exp_step))
            elif key == ord("s"):
                snap_dir.mkdir(parents=True, exist_ok=True)
                stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                for c in cams:
                    item = c.latest(rotated=True)
                    if item is not None:
                        cv2.imwrite(str(snap_dir / f"{stamp}_{c.name}.png"), item[0])
                log.info("Saved snapshots to %s", snap_dir)
    except KeyboardInterrupt:
        pass
    finally:
        for c in cams:
            c.stop()
        cv2.destroyAllWindows()

    ok = verdict(log, cams, cfg) and not errors
    for slot, device_id, err in errors:
        log.info("  [FAIL] %s (id %d) did not open: %s", camera_names(cfg)[slot], device_id, err)
    log.info("\nCapture %s. Log: %s", "PASSED" if ok else "FAILED", log_file)
    return 0 if ok else 1


if __name__ == "__main__":
    from core.runlog import exit_now
    exit_now(main())  # for certain: the cameras are free for the next tool at once
