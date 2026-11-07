"""Room calibration check: does the card's SteamVR position land on the marker in every camera?

Run from engine/ (2_calibrate_cameras/3_check_calibration.bat does this), SteamVR up and the card's tracker or
controller on:  python -m tools.calib_check   (--quiet: no voice, --seconds N: stop after N seconds)
It follows the device picked in room calibration (my_data/calibration/room_device.json), or asks you to wave it.
Each camera draws a red ring where SteamVR says the marker is and a green ring where the camera sees it; they
should sit on top of each other everywhere in the room. Each camera says GOOD once its median gap (over moments
when the card is nearly still) is at most calibration.room.check_max_px, or OFF. q (or Esc) ends with a summary,
on screen and spoken; the log records the gaps too. f toggles fullscreen.
"""

import argparse
import json
import time

import cv2
import numpy as np

from calibration import room
from capture.camera import camera_keys, camera_names, open_cameras, outlined_text, spoken, spoken_list, tile_grid
from core.config import get, load_config, resolve_path
from core.runlog import start_run
from tools.calib_room import (GREEN, RED, WHITE, YELLOW, DeviceWatch, connect_vr, load_intrinsics, message_screen, missing_lenses,
                              pick_device)

MIN_SAMPLES = 30  # still moments a camera needs before it gets a verdict
RECENT = 200      # the verdict uses the most recent this-many gaps


def verdict(gaps, max_px, min_n=MIN_SAMPLES):
    """(GOOD / OFF / None if not enough yet, median gap px or None) from a camera's gaps."""
    if len(gaps) < min_n:
        return None, (float(np.median(gaps)) if gaps else None)
    m = float(np.median(gaps[-RECENT:]))
    return ("GOOD" if m <= max_px else "OFF"), m


SHOW = {"GOOD": "FIT GOOD", "OFF": "OFF"}  # on screen: what was graded (the fit), not that tracking is fine


def summary_lines(gaps, names, max_px):
    lines, off = [], []
    for k, name in enumerate(names):
        v, m = verdict(gaps.get(k, []), max_px)
        if v is None:
            lines.append((f"{name}: not enough seen" + (f" ({m:.1f} px so far)" if m is not None else ""), YELLOW))
        else:
            lines.append((f"{name}: {SHOW[v]}   {m:.1f} px", GREEN if v == "GOOD" else RED))
            if v == "OFF":
                off.append(name)
    return lines, off


def main():
    ap = argparse.ArgumentParser(description="Overlay the card's SteamVR position on every camera")
    ap.add_argument("--config")
    ap.add_argument("--seconds", type=float, default=0, help="stop after this long")
    ap.add_argument("--quiet", action="store_true", help="no voice or beeps")
    args = ap.parse_args()
    cfg = load_config(args.config)
    rc = dict(get(cfg, "calibration.room"))
    log, log_file = start_run("calib_check", cfg)
    data_dir = resolve_path(get(cfg, "calibration.dir", "my_data/calibration"))
    names = camera_names(cfg)
    size = (int(cfg["cameras"]["width"]), int(cfg["cameras"]["height"]))
    from tools import calib_intrinsics as ci
    from tools.voice import Voice
    voice = Voice(on=not args.quiet and bool(rc.get("voice", True)), volume=float(get(cfg, "calibration.voice_volume", 0.8)),
                  prerender=["Every camera lines up well. Press Q to finish."])
    win = ci.Window("Calibration check")
    try:
        run(args, cfg, rc, log, log_file, data_dir, names, size, voice, win, ci)
        return 0  # every ending was shown and spoken; only a crash is an error
    finally:
        cv2.destroyAllWindows()
        voice.close()


def run(args, cfg, rc, log, log_file, data_dir, names, size, voice, win, ci):
    keys = camera_keys(cfg)
    missing = [names[keys.index(k)] for k in missing_lenses(data_dir, keys)]
    if missing or not (data_dir / "room.json").is_file():
        what = f"lens calibration for {', '.join(missing)}" if missing else "room calibration"
        message_screen(win, voice, "Nothing to check yet", [(f"Do the {what} first.", YELLOW)],
                       f"Do the {what} first.", size=size)
        return 1
    with open(data_dir / "room.json", "r", encoding="utf-8") as f:
        rm = json.load(f)
    try:
        rm = room.cameras_in_order(rm, keys)  # by calibration key: renamed or reordered cameras still match
    except ValueError as e:
        log.warning("room.json doesn't match the cameras in the settings: %s", e)
        message_screen(win, voice, "Cameras changed", [("The cameras changed since room calibration.", YELLOW),
                       ("Run 2_room_calibration.bat again.", WHITE)],
                       "The cameras changed since room calibration. Please run it again.", RED, size)
        return 1
    intrinsics = load_intrinsics(data_dir, keys)
    for name, lens in zip(names, intrinsics):
        log.info("%s lens: %s, RMS %.3f px, board height/width %.4f%s", name, lens["model"], lens["rms_px"],
                 lens.get("board_stretch", 1.0), " (printer stretch corrected)" if lens.get("stretch_corrected") else "")
    offset = np.array(rm["marker_offset_m"])
    from core.single import hold_cameras
    hold_cameras(log, say=lambda t: (voice.say(t, force=True), voice.flush()), show=True)  # a window says who has them
    vr = connect_vr(cfg, rc, log)
    if vr is None:
        message_screen(win, voice, "SteamVR isn't running", [("Start SteamVR, then run this again.", YELLOW)],
                       "Start SteamVR first, then run this again.", RED, size)
        return 1
    picked = pick_device(vr, rc, win, voice, size, log, data_dir / "room_device.json")
    if picked is None:
        vr.stop()
        return 1
    kind, serial, _ = picked
    log.info("Following %s %s", kind, serial)
    vr.start()
    watch = DeviceWatch(vr, kind, serial, log)
    cams, errors = open_cameras(cfg, log)
    if errors:
        for c in cams:
            c.stop()
        vr.stop()
        bad = ", ".join(names[e[0]] for e in errors)
        message_screen(win, voice, "A camera didn't open", [(f"Didn't open: {bad}", YELLOW),
                       ("Close other programs using the cameras, then run this again.", WHITE)],
                       f"{spoken_list([names[e[0]] for e in errors], True)} didn't open. Close other programs using "
                       "the cameras.", RED, size)
        return 1
    for c in cams:
        c.start()
    max_px = float(rc.get("check_max_px", 6.0))
    detectors = [room.marker_detector(rc) for _ in names]
    latency_ns = int(float(rc.get("frame_latency_ms", 15)) * 1e6)
    still = 2 * float(rc.get("still_speed_m_s", 0.05))  # gaps only while the card is nearly still (timing jitters)
    gaps = {c.slot: [] for c in cams}
    said = {}  # camera -> the verdict last spoken
    all_said = False
    tile_h = int(get(cfg, "preview.tile_height", 640))
    voice.say("Move Board B around the room, stopping now and then. The red and green rings should sit on "
              "top of each other.", force=True)
    t0 = last_log = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            voice.tick(now)
            tiles = []
            for c in cams:
                item = c.latest(rotated=False)
                if item is None:
                    img, t_ns = np.zeros((size[1], size[0], 3), np.uint8), None
                else:
                    img, t_ns, _ = item
                    img = img.copy()
                s = vr.at(t_ns - latency_ns) if t_ns is not None else None
                pred = None
                if s is not None:
                    pred = room.project_vr_point(s[0] + s[1] @ offset, rm["cameras"][c.slot], intrinsics[c.slot])
                seen = room.find_marker(detectors[c.slot], img, int(rc["marker_id"])) if t_ns is not None else None
                if pred is not None and 0 <= pred[0] < img.shape[1] and 0 <= pred[1] < img.shape[0]:
                    cv2.circle(img, (int(pred[0]), int(pred[1])), 26, RED, 4)
                if seen is not None:
                    cv2.circle(img, (int(seen[0]), int(seen[1])), 16, GREEN, 4)
                    if pred is not None and s[2] < still:
                        gaps[c.slot].append(float(np.linalg.norm(pred - seen)))
                if c.rotation is not None:
                    img = cv2.rotate(img, c.rotation)
                img = cv2.resize(img, (int(img.shape[1] * tile_h / img.shape[0]), tile_h), interpolation=cv2.INTER_AREA)
                v, m = verdict(gaps[c.slot], max_px)
                sc = tile_h / 640
                text = c.name + (f"  {m:.1f} px" if m is not None else "") + (f"  {SHOW[v]}" if v else "")
                outlined_text(img, text, (14, int(62 * sc)), cv2.FONT_HERSHEY_SIMPLEX, 1.7 * sc,
                              GREEN if v == "GOOD" else RED if v == "OFF" else YELLOW, max(2, int(4 * sc)), cv2.LINE_AA)
                tiles.append(img)
                if v and said.get(c.slot) != v:  # speak a camera's verdict when it first comes, or changes
                    said[c.slot] = v
                    if v == "GOOD":
                        voice.click()
                        voice.say(f"{spoken(c.name, True)} lines up well.", now)
                    else:
                        voice.say(f"{spoken(c.name, True)} is off by {m:.0f} pixels.", now, force=True)
            from capture.camera import say_camera_events
            say_camera_events(cams, voice, now)  # a camera unplugged, or back
            if not all_said and len(said) == len(cams) and all(v == "GOOD" for v in said.values()):
                all_said = True
                voice.say("Every camera lines up well. Press Q to finish.", now, force=True)
            done = sum(1 for v in said.values() if v == "GOOD")
            _, device_problem = watch.check(now, voice)
            if device_problem is not None:
                instruction, color = device_problem
            elif all_said:
                instruction, color = "Every camera lines up well: press q to finish", GREEN
            else:
                instruction, color = "Red and green rings should sit on top of each other", WHITE
            win.show(ci.overlay(tile_grid(tiles), "Calibration check", f"{done} of {len(cams)} cameras FIT GOOD",
                                instruction, "", color, "q finish   f fullscreen"))
            key = cv2.waitKey(15) & 0xFF
            if key == ord("f"):
                win.toggle_full()
            if key in (ord("q"), 27):
                break
            if now - last_log > 5:
                log.info("median gap px: %s", {names[k]: round(float(np.median(v[-RECENT:])), 1) if v else None
                                                for k, v in gaps.items()})
                last_log = now
            if args.seconds and now - t0 > args.seconds:
                break
    finally:
        for c in cams:
            c.stop()
        vr.stop()
    log.info("\nSummary (pixels between where SteamVR puts the marker and where the camera sees it)")
    for k, v in gaps.items():
        if v:
            log.info("  %-6s median %.1f px, 90%% under %.1f px, from %d still moments", names[k], np.median(v),
                     np.percentile(v, 90), len(v))
        else:
            log.info("  %-6s never saw the marker", names[k])
    lines, off = summary_lines(gaps, names, max_px)
    ok = all(verdict(gaps.get(k, []), max_px)[0] == "GOOD" for k in range(len(names)))
    if ok:
        said_end = ("Calibration check passed. You only need to redo it if a camera moves. Next, open step 3, first "
                    "test. After that you'll teach it your cat: that takes the longest, but the labelling tool does "
                    "most of the work.")
    elif off:
        lines.append(("Run 2_room_calibration.bat again. If one camera is still off, redo its lens.", WHITE))
        said_end = f"The {', '.join(off)} camera is off. Run room calibration again."
    else:
        lines.append(("Move Board B where every camera can see it, stopping now and then.", WHITE))
        said_end = "Some cameras didn't see Board B enough. Run the check again, covering more of the room."
    message_screen(win, voice, "Calibration check: FIT GOOD" if ok else "Calibration check not passed", lines, said_end,
                   GREEN if ok else RED if off else YELLOW, size)
    log.info("Log: %s", log_file)
    return 0 if ok else 1


if __name__ == "__main__":
    from core.runlog import exit_now
    exit_now(main())  # for certain: the cameras are free for the next tool at once
