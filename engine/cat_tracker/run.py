"""Cat tracker: cameras -> cat boxes -> 3D position -> SteamVR overlay at the real cat, and an arrow
at the edge of your view pointing to it when it's close.

Run from engine/ (5_play_in_vr\\run_tracker.bat does this; SteamVR up first):  python -m cat_tracker.run
  --new-anchor    do the walk-around again even though an anchor is saved (normally the saved one in
                  my_data/tracker/anchor.json is used, and the walk-around only happens when there's none)
  --reuse-anchor  the old way to ask for the saved anchor; it's the default now, so this does nothing
  --no-vr         detect and show it on the desktop only (no SteamVR needed)
  --capture       save frames for training from the start (also c in the window); see label.py
  --seconds N     stop after N seconds
  --osc           also send its position to VRChat for the avatar's cat prop (see osc.py)
  --headless      no window (how SteamVR starts it, see install_autostart.py); needs a saved anchor,
                  and closes when SteamVR does
In the window: q quits, a re-runs the anchor, s saves a snapshot, c starts/stops capturing. Uses the cameras itself, so other camera programs
track.bat can't run at the same time.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from capture.camera import camera_keys, camera_names, label_tile, open_cameras, outlined_text, tile_grid
from cat_tracker import anchor as anc
from cat_tracker.alert import Heading, Motion, Proximity, Smoother
from cat_tracker import settings
from cat_tracker.detector import CatDetector, draw
from cat_tracker.collect import ENOUGH_SAID, NOCAT_ASK, FrameSaver
from cat_tracker.hardframes import HardSaver
from cat_tracker.health import Health, Heartbeat
from cat_tracker.light import LightWatch
from cat_tracker.notice import render as render_notice
from cat_tracker.locate import CatTrack, locate, room_bounds, weak_matches
from cat_tracker.osc import OscCat, OscStream
from cat_tracker.stick_anchor import StickAnchor
from cat_tracker.vrlink import billboard, edge_pose, flat, horizontal_distance
from core.config import get, resolve_path
from core.runlog import start_run
from fusion.triangulate import Rig
from pose import baseline
from tools.calib_room import load_intrinsics


def colour_report(items, names):
    """Mean blue/green/red per camera and how far blue sits from red: a quick way to spot a camera
    whose white balance isn't what was asked for (same room, so all four should be close)."""
    out = []
    for n, it in zip(names, items):
        if it is None:
            continue
        b, g, r = it[0][::8, ::8].reshape(-1, 3).mean(axis=0)
        out.append("%s B/G/R %.0f/%.0f/%.0f (blue %+.0f%% vs red)" % (n, b, g, r, 100 * (b - r) / max(r, 1)))
    return "; ".join(out)


def reset_white_balance(cams, cam_cfg, log, names):
    """Turn auto white balance on and off again, then set the temperature. Some UVC drivers keep an
    old white balance (from another program or a previous run) until auto is toggled, while still
    reporting the requested value back."""
    if cam_cfg.get("white_balance_k") is None:
        return  # automatic white balance: nothing to reset
    log.info("Colours before the white balance reset: %s", colour_report([c.latest(rotated=False) for c in cams], names))
    for c in cams:
        c.queue_set(cv2.CAP_PROP_AUTO_WB, 1)
    time.sleep(1.5)
    for c in cams:
        c.queue_set(cv2.CAP_PROP_AUTO_WB, 0)
        if cam_cfg.get("white_balance_k") is not None:
            c.queue_set(cv2.CAP_PROP_WB_TEMPERATURE, float(cam_cfg["white_balance_k"]))
    time.sleep(1.5)
    log.info("Colours after the white balance reset: %s", colour_report([c.latest(rotated=False) for c in cams], names))


def tiles(items, names, boxes_all, picked, views=None, tile_h=360, banner=None, turns=None):
    """The tracker window: boxes drawn on the raw frames, then each turned upright (cameras.rotate) and laid out
    like every other camera window (capture.camera.tile_grid)."""
    out = []
    for i, it in enumerate(items):
        if it is None:
            continue
        img = it[0].copy()
        if boxes_all is not None:
            draw(img, boxes_all[i], color=(120, 120, 120))  # every box, grey; the one used, thick
            if picked[i] is not None:
                draw(img, [picked[i]], 0)
        if views is not None and views[i] is not None:
            baseline.draw(img, views[i][0], views[i][1], 0.3)
        if turns is not None and turns[i] is not None:
            img = cv2.rotate(img, turns[i])
        out.append(label_tile(img, names[i], tile_h))
    if not out:
        return None
    grid = tile_grid(out)
    if banner:
        for k, line in enumerate(reversed(banner.split("\n"))):  # more than one line: stacked upward
            outlined_text(grid, line, (10, grid.shape[0] - 14 - 32 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2,
                          cv2.LINE_AA)
    return grid


def start_watchdog(hang_s, buzz, log):
    """Starts watchdog.py as its own process, detached, so it outlives this one if it crashes."""
    exe = Path(sys.executable)
    if os.name == "nt" and exe.with_name("pythonw.exe").is_file():
        exe = exe.with_name("pythonw.exe")  # no console window
    flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == "nt" else 0
    cmd = [str(exe), "-m", "cat_tracker.watchdog", "--pid", str(os.getpid()), "--hang-s", str(hang_s)]
    if not buzz:
        cmd.append("--no-buzz")
    try:
        subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parent.parent), creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, start_new_session=os.name != "nt")
        log.info("Watchdog started: a notice shows in VR if the tracker stops unexpectedly")
    except OSError as e:
        log.warning("Couldn't start the watchdog (%s): a crash won't show a notice in VR", e)


def enough_args(cfg):
    """cat.capture.enough_moments / enough_spots from the settings (a rough guide: FrameSaver)."""
    return {"enough_moments": int(get(cfg, "cat.capture.enough_moments", 150)),
            "enough_spots": int(get(cfg, "cat.capture.enough_spots", 3))}


def main():
    ap = argparse.ArgumentParser(description="Cat tracker")
    ap.add_argument("--config", help="camera settings (default: settings/cameras.yaml)")
    ap.add_argument("--cat-config", help="cat tracker settings (default: settings/cat_tracker.yaml)")
    ap.add_argument("--reuse-anchor", action="store_true", help="default now; kept for old launchers")
    ap.add_argument("--new-anchor", action="store_true", help="walk around for a new anchor even if one is saved")
    ap.add_argument("--no-vr", action="store_true")
    ap.add_argument("--seconds", type=float, default=0)
    ap.add_argument("--capture", action="store_true")
    ap.add_argument("--osc", action="store_true", help="send its position to VRChat over OSC")
    ap.add_argument("--headless", action="store_true", help="no window; needs a saved anchor")
    args = ap.parse_args()
    cfg = settings.load(args.config, args.cat_config)
    cc = cfg["cat"]
    dc, lc, fc, oc, al = (cc.get(k, {}) or {} for k in ("detector", "locate", "filter", "overlay", "alert"))
    log, log_file = start_run("cat_tracker", cfg)
    for note in cfg.get("_notes", []):
        log.warning(note)
    names = camera_names(cfg)
    data_dir = resolve_path(get(cfg, "calibration.dir", "my_data/calibration"))
    keys = camera_keys(cfg)
    with open(data_dir / "room.json", "r", encoding="utf-8") as f:
        from calibration.room import cameras_in_order
        room = cameras_in_order(json.load(f), keys)  # by calibration key: renamed cameras still match
    intrinsics = load_intrinsics(data_dir, keys)
    rig = Rig(room, intrinsics)

    baseline.prepare_onnxruntime(get(cfg, "onnxruntime", {}) or {})
    dev = int(get(cfg, "gpu.device_id", 0))
    # the model reports weak boxes too; only confident ones (detector.score) find it on their own,
    # weak ones count where it is expected (another camera's sighting, or where it just was)
    strong = float(dc.get("score", 0.2))
    det = CatDetector({**dc, "score": min(strong, float(dc.get("weak_score", 0.08)))}, resolve_path(dc["model"]), [("CUDAExecutionProvider", {"device_id": dev}), "CPUExecutionProvider"])
    log.info("Cat model loaded: %s", dc["model"])

    vr = None
    if not args.no_vr:
        from cat_tracker.vrlink import VRLink
        try:
            vr = VRLink()
        except Exception as e:  # noqa: BLE001
            log.error("SteamVR not available (%s). Start SteamVR first, or use --no-vr", e)
            return 1

    cams, errors = open_cameras(cfg, log)  # a camera that isn't there yet (autostart: USB can be late) joins later
    if errors:
        log.error("A camera in the settings is a device cameras.exclude forbids: run 1_connect_cameras\\1_set_up_cameras.bat; stopping")
        for c in cams:
            c.stop()
        if vr is not None:
            vr.stop()
        return 1
    for c in cams:
        c.start()
    from capture.camera import wait_for_any
    wait_for_any(cams, log)
    time.sleep(1.0)  # first frames
    if get(cfg, "cat.reset_white_balance", True):
        reset_white_balance(cams, cfg["cameras"], log, names)

    tile_h = int(get(cfg, "cat.preview.tile_height", 360))
    show_every = max(1, int(get(cfg, "cat.preview.show_every_n", 2)))
    win = "Cat tracker (q quits, a re-anchors, s saves a snapshot)"
    from tools.window import quit_when_closed
    quit_when_closed(win)  # closing the window quits, as q does
    if not args.headless:  # no window at all: Windows marks a window nobody redraws "Not Responding", and closing it ends the tracker
        cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)

    voices = []

    def voice_say(text):
        """The calm voice, started only when there's something to say (the anchor walk, capturing)."""
        try:
            if not voices:
                from tools.voice import Voice
                voices.append(Voice(volume=float((cfg.get("calibration") or {}).get("voice_volume", 0.8))))
            voices[0].say(text, force=True)
        except Exception as e:  # noqa: BLE001  (no voice: the banner says it too)
            log.info("No voice: %s", e)

    redo_clicked = [False]
    nocat_clicked = [False]
    dim_said = [0]  # 1_capture: when "the room is dim" was said (once)
    BTN = (10, 10, 250, 50)  # the Redo anchor walk button, top left of the window
    NC_BTN = (260 if vr is not None else 10, 10, (260 if vr is not None else 10) + 330, 50)  # NO CAT, while capturing

    def capturing():
        try:
            return saver is not None and saver.on
        except NameError:  # (asked before capturing is set up, e.g. during the anchor walk)
            return False

    def on_mouse(ev, u, v, flags, _):
        if ev == cv2.EVENT_LBUTTONDOWN and vr is not None and BTN[0] <= u <= BTN[2] and BTN[1] <= v <= BTN[3]:
            redo_clicked[0] = True
        if ev == cv2.EVENT_LBUTTONDOWN and capturing() and NC_BTN[0] <= u <= NC_BTN[2] and NC_BTN[1] <= v <= NC_BTN[3]:
            nocat_clicked[0] = True

    def with_button(g):
        if g is not None and vr is not None:
            cv2.rectangle(g, BTN[:2], BTN[2:], (0, 210, 255), -1)
            cv2.putText(g, "REDO ANCHOR WALK (a)", (BTN[0] + 10, BTN[3] - 13), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (20, 20, 20), 2, cv2.LINE_AA)
        if g is not None and capturing():  # NO CAT: lit while on (the cat is out of the room)
            on, asking = saver.nocat, saver.asking(time.monotonic())
            fill = (80, 200, 80) if on else (0, 210, 255) if asking else (60, 60, 60)
            cv2.rectangle(g, NC_BTN[:2], NC_BTN[2:], fill, -1)
            cv2.rectangle(g, NC_BTN[:2], NC_BTN[2:], (240, 240, 240), 1)
            text = ("NO CAT ON: cat out of the room (n: it's back)" if on else "PRESS N AGAIN TO START" if asking
                    else "NO CAT (n): cat out of the room?")
            cv2.putText(g, text, (NC_BTN[0] + 10, NC_BTN[3] - 13), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (20, 20, 20) if (on or asking) else (240, 240, 240), 1, cv2.LINE_AA)
            if on:  # can't be missed: a thick green border round the whole window
                cv2.rectangle(g, (0, 0), (g.shape[1] - 1, g.shape[0] - 1), (80, 200, 80), 12)
        return g

    def show_anchor(items, views, text="Anchoring: headset on, walk slowly around the room"):
        heartbeat.beat()  # the walk-around can take a minute; the watchdog mustn't think we froze
        if items is None:  # waiting for the headset: the cameras' latest pictures, no pose yet
            items = [c.latest(rotated=False) for c in cams]
            views = [None] * len(items)
        g = tiles(items, names, None, [None] * len(items), views, tile_h, text, [c.rotation for c in cams])
        if g is not None:
            cv2.imshow(win, g)
        return (cv2.waitKey(1) & 0xFF) not in (ord("q"), 27)

    def do_anchor(keeping=False):
        heartbeat.busy(30)  # the pose model loads before the walk's own heartbeats start
        T, why = anc.run(cfg, cams, rig, vr, log, show_anchor, voice_say)
        if T is not None:
            voice_say("Anchor saved. The cat's marker is lined up with your headset now.")
            return T
        if why and why.startswith("stopped"):
            return None
        voice_say("That anchor walk didn't work. " + why.split(";")[0].split(".")[0] + ".")
        if keeping:
            log.warning("New anchor not saved (%s); still using the previous one. Press a or the button to try again", why)
        else:
            log.error("No anchor (%s): the marker can't be placed in SteamVR until one works. Press a or the button", why)
        last_problem[0] = why
        return None

    last_problem = [None]

    hc_ = cc.get("health", {}) or {}
    notice_dir = resolve_path("my_data/tracker")
    health = Health(hc_, names)
    heartbeat = Heartbeat(notice_dir / "heartbeat.json")
    light = LightWatch(names, log)  # the room light, judged over minutes: a note in this window, not in VR
    raw_to_cam = cam_to_raw = None
    if vr is not None:
        raw_to_cam = None if args.new_anchor else anc.load(cfg, log)
        if raw_to_cam is not None:
            log.info("Using the saved anchor from %s", get(cfg, "cat.anchor.file"))
        elif args.headless:
            log.error("No saved anchor, and there's no window to make one in: run run_tracker.bat once and do the walk-around")
            for c in cams:
                c.stop()
            vr.stop()
            return 1
        else:
            raw_to_cam = do_anchor()
        cam_to_raw = np.linalg.inv(raw_to_cam) if raw_to_cam is not None else None
        vr.add_overlay("icon", resolve_path(oc["icon"]), oc.get("icon_width_m", 0.28))
        vr.add_overlay("ring", resolve_path(oc["ring"]), oc.get("ring_width_m", 0.55))
        vr.add_overlay("edge", resolve_path(al.get("image", "engine/cat_tracker/assets/edge_arrow.png")), al.get("width_m", 0.07))
        vr.add_overlay("warn", resolve_path(get(cfg, "cat.anchor_check.image", "engine/cat_tracker/assets/anchor_warning.png")), 0.5)
        vr.add_overlay("health", render_notice(notice_dir / "notice_health.png", "Cat tracker"), 0.5)
        if al.get("buzz", True):
            vr.setup_haptics(resolve_path("engine/cat_tracker/input/actions.json"), log)

    bounds = room_bounds(rig, float(lc.get("room_margin_m", 0.15)))
    log.info("Room (from the camera positions): x %.2f to %.2f m, z %.2f to %.2f m", *bounds)
    saver = FrameSaver(resolve_path("my_data/captures"), names, float(get(cfg, "cat.capture.every_s", 2.0)),
                           float(get(cfg, "cat.capture.min_free_gb", 5)), log, **enough_args(cfg)) if args.capture else None
    if saver is not None:
        saver.cats = int(get(cfg, "cat.label.cats", 1) or 1)
    said_enough = [False]
    track = CatTrack(fc, float(oc.get("lost_alpha", 0.6)))
    motion, prox, heading = Motion(oc), Proximity(al), Heading(oc)
    smooth = Smoother(float(oc.get("smooth_s", 0.15)))
    buzz_armed, calm_since = True, None  # one buzz pattern each time the warning comes on, see alert.buzz_rearm_s
    hc = cc.get("hard_frames", {}) or {}
    hard = HardSaver(resolve_path("my_data/captures"), names, hc, lc, log) if hc.get("enabled", True) else None
    if hard is not None:  # say so every run: anyone in view can end up in these pictures
        log.info("Saving training pictures while it runs: ON. Anyone in view can be in them. "
                 "Turn off: hard_frames enabled: false in settings\\cat_tracker.yaml")
    check = anc.AnchorCheck(cfg, log) if vr is not None else None
    if check is not None and raw_to_cam is not None:
        check.startup(vr)  # asks for a re-anchor at once if SteamVR's base station map changed
    icons = {k: resolve_path(oc[k]) for k in ("icon", "icon_close", "icon_rest", "icon_move") if oc.get(k)}
    osc = OscCat(cc.get("vrchat", {}) or {}, lc) if args.osc and vr is not None else None
    if args.osc and vr is None:
        log.warning("--osc needs SteamVR (its offset is measured from your headset); not sending")
    stream = None
    if osc is not None:
        send_hz = float((cc.get("vrchat", {}) or {}).get("send_hz", 60))
        sa = StickAnchor((cc.get("vrchat", {}) or {}).get("stick_anchor"), log)
        if sa.enabled:
            vr.setup_haptics(resolve_path("engine/cat_tracker/input/actions.json"), log)  # for the thumbsticks
            log.info("Stick anchor (experimental): ON, anchoring the cat while the thumbsticks rest")
        stream = OscStream(osc, vr, send_hz, log, anchor=sa)
        log.info("Sending its position to VRChat over OSC at %s:%d, %g a second", *osc.addr, send_hz)
    floor_y = float(lc.get("floor_y_m", 0.0))
    # detections per second: the full rate only while it's moving or close to you; it's mostly asleep
    # or out of the room, and then a slower rate is plenty (and saves the GPU)
    fast_period = 1.0 / float(dc.get("rate_hz", 8))
    idle_period = 1.0 / float(dc.get("idle_rate_hz", 3))
    det_period = idle_period
    # at the idle rate, a cheap check of the cat's spot between detections runs the detector at once when it moves
    from cat_tracker.tripwire import Tripwire
    tripwire = Tripwire(float(dc.get("tripwire_change", 6.0)))
    full_within = float(dc.get("full_rate_within_m", 3.0))  # this close to you: the full rate, still or not
    last_dist = dist = None
    wakes_logged = 0
    period = 1.0 / float(oc.get("update_hz", 30))
    last_det = -1e9
    snap_dir = resolve_path(cfg["logging"]["dir"]) / "snapshots"
    stats = {"n": 0, "det_ms": [], "views": [], "seen": 0, "how": {}}
    t0 = last_log = last_stop_check = time.monotonic()
    stop_file = resolve_path("my_data/tracker/stop")  # stop_tracker.bat makes it, to close a tracker with no window
    stop_file.unlink(missing_ok=True)
    loops = 0
    close = False  # from the last update, used to pick the detection rate
    heartbeat.busy(20)  # the first detections can be slow (the GPU warming up)
    if vr is not None and hc_.get("watchdog", True):
        start_watchdog(float(hc_.get("hang_s", 3)), bool(al.get("buzz", True)), log)
    clean = False  # set when we stop on purpose; anything else (a crash) leaves the watchdog to warn you
    shown_notice = None
    pos, state, alpha = None, "hidden", 0.0
    items = boxes_all = picked = None

    def show_health(now):
        """The tracker's own problems (a camera stopped, detection failing), as a notice in VR."""
        nonlocal shown_notice
        msg = health.message(now)
        key = msg[0] if msg else None
        if key != shown_notice:
            if msg:
                log.warning("%s: %s", msg[1], " ".join(msg[2]))
                if vr is not None:
                    vr.set_image("health", render_notice(notice_dir / f"notice_health_{abs(hash(key)) % 1000}.png", msg[1], msg[2]))
            elif shown_notice is not None:
                log.info("Tracker problem cleared")
            shown_notice = key
        if vr is not None:
            if msg:
                T = np.eye(4)
                T[:3, 3] = [0.0, -0.2, -1.2]
                T[:3, :3] = [[1, 0, 0], [0, np.cos(0.15), np.sin(0.15)], [0, -np.sin(0.15), np.cos(0.15)]]
                vr.place_on_head("health", T, 0.9)
            else:
                vr.place_on_head("health", None, 0)
        return msg

    try:
        while True:
            tick = time.perf_counter()
            heartbeat.beat()
            # detection runs at detector.rate_hz (a few times a second is plenty for a cat); the overlays,
            # edge arrow and OSC offset follow your head at overlay.update_hz using its last position
            fresh = time.monotonic() - last_det >= det_period
            if not fresh and det_period == idle_period and state in ("seen", "lost"):
                quick = [c.latest(rotated=False) for c in cams]
                if tripwire.changed([q[0] if q is not None else None for q in quick]):
                    fresh = True  # its spot changed: look now, not at the next idle tick
            if fresh:
                items = [c.latest(rotated=False) for c in cams]
                stale = health.cameras(items, time.monotonic())
                light.feed(items)
                if saver is not None and saver.on and not dim_said[0] and light.early() is not None:  # once, quietly
                    dim_said[0] = time.monotonic()
                    log.info("Light: the room is dim. Capturing works, but labelling will be slower. More light helps.")
                    voice_say("The room is dim. Capturing works, but labelling will be slower. More light helps.")
                if any(it is None for it in items):  # a camera that hasn't sent its first picture yet
                    show_health(time.monotonic())
                    if vr is not None and vr.quit_requested():
                        log.info("SteamVR is closing; stopping")
                        clean = True
                        break
                    if stop_file.exists():
                        stop_file.unlink(missing_ok=True)
                        log.info("Asked to stop (stop_tracker.bat)")
                        clean = True
                        break
                    time.sleep(0.05)
                    continue
                last_det = time.monotonic()
                td = time.perf_counter()
                try:
                    boxes_all = det([it[0] for it in items])
                    health.detector_ok()
                except Exception:  # noqa: BLE001 - keep running and say so, rather than vanish
                    log.exception("Detection failed")
                    health.detector_failed(time.monotonic())
                    boxes_all = [np.zeros((0, 5)) for _ in items]
                for i in set(stale) | {i for i, c in enumerate(cams) if getattr(c, "state", "ok") == "unplugged"}:
                    boxes_all[i] = boxes_all[i][:0]  # an old picture (or an unplugged camera) says nothing now
                stats["det_ms"].append(1000 * (time.perf_counter() - td))
                X, used, how, picked = locate(rig, [b[b[:, 4] >= strong] for b in boxes_all], lc, bounds)
                how_strong, picked_strong = how, picked
                ref = X if X is not None else (track.pos if track.state != "hidden" else None)
                if ref is not None:
                    h, w = items[0][0].shape[:2]
                    extra = weak_matches(room, intrinsics, boxes_all, picked, ref, lc, w, h)
                    if any(e is not None for e in extra):
                        both = [np.array([p if p is not None else e]) if (p is not None or e is not None) else np.zeros((0, 5))
                                for p, e in zip(picked, extra)]
                        X2, used2, how2, picked2 = locate(rig, both, lc, bounds)
                        if X2 is not None:
                            X, used, how, picked = X2, used2, how2 + "+weak", picked2
                now = time.monotonic()
                pos, state, alpha = track.update(X, now)
                stats["n"] += 1
                stats["views"].append(sum(b is not None for b in picked))
                if state == "seen":
                    stats["seen"] += 1
                if how is not None:
                    stats["how"][how] = stats["how"].get(how, 0) + 1
                if saver is not None:
                    saver(items, [b[b[:, 4] >= strong] for b in boxes_all], rig, lc, bounds, now)  # confident boxes as first labels
                elif hard is not None and state == "seen":
                    hard(items, picked_strong, picked, X, how_strong, rig, room, intrinsics, bounds, now)
                if state == "seen":
                    motion.update(pos, now)
                elif state == "hidden":  # a brief "last seen" doesn't restart its sleep timer; gone for good does
                    motion.update(None, now)
                heading.update(pos if state == "seen" else None, now, gone=state == "hidden")
                if check is not None:
                    if check.on and check.models is None and raw_to_cam is not None and now >= check.next_at:
                        heartbeat.busy(30)  # this step loads the pose model first (a few seconds, once)
                    T = check.step(items, rig, vr, raw_to_cam, now)
                    if T is not None:  # it quietly corrected the anchor (and saved it)
                        raw_to_cam, cam_to_raw = T, np.linalg.inv(T)
                busy = state == "seen" and (motion.speed > float(oc.get("still_speed", 0.1)) or close or
                                            (last_dist is not None and last_dist < full_within))
                tripwire.set([it[0] for it in items], picked if state in ("seen", "lost") else [None] * len(items))
                det_period = fast_period if busy else idle_period

            close = False
            last_dist = dist if dist is not None else last_dist
            dist = level = None
            if vr is not None and vr.quit_requested():
                log.info("SteamVR is closing; stopping")
                clean = True
                break
            problem = show_health(time.monotonic())
            if vr is not None and cam_to_raw is not None:
                vr.update_input()
                M = vr.raw_to_standing()
                hmd = vr.headset()
                shown = smooth(pos, time.monotonic())  # glides between detections
                if shown is not None:
                    to_standing = M @ cam_to_raw
                    p = to_standing[:3, :3] @ shown + to_standing[:3, 3]
                    foot = np.array([shown[0], floor_y + 0.01, shown[2]])
                    ring = to_standing[:3, :3] @ foot + to_standing[:3, 3]
                    hmd_st = (M @ hmd)[:3, 3] if hmd is not None else p + np.array([0, 0, 1.0])
                    dist = horizontal_distance(p, hmd_st) if hmd is not None else None
                    if dist is not None and state in ("seen", "lost"):
                        level = prox.update(dist, motion.speed if state == "seen" else 0.0, time.monotonic())
                    else:
                        prox.reset()
                    close = level is not None
                    # the buzz goes with the warning (the arrow and the red icon): once each time it comes on
                    if close:
                        calm_since = None
                        if buzz_armed and al.get("buzz", True):
                            vr.buzz_pattern(str(al.get("buzz_pattern", "LRLR")), float(al.get("buzz_total_s", 1.0)),
                                            float(al.get("buzz_s", 0.15)), float(al.get("buzz_amplitude", 0.6)))
                        buzz_armed = False
                    kind = "close" if close else motion.kind(time.monotonic(), oc) if state == "seen" else "normal"
                    vr.set_image("icon", icons.get({"close": "icon_close", "rest": "icon_rest", "move": "icon_move"}.get(kind, "icon"), icons["icon"]))
                    vr.place("icon", billboard(p + np.array([0, float(oc.get("icon_lift_m", 0.3)), 0]), hmd_st), alpha)
                    vr.place("ring", flat(ring), alpha)
                    if close:  # its direction as seen from the headset, so the arrow points at it
                        d = np.linalg.inv(M @ hmd) @ np.append(p, 1.0)
                        vr.place_on_head("edge", edge_pose(d[:3], float(al.get("edge_angle_deg", 32)),
                                                           float(al.get("distance_m", 1.0))), float(al.get("alpha", 0.9)))
                    else:
                        vr.place_on_head("edge", None, 0)
                if not close and not buzz_armed:  # ready again once the warning has been off a moment
                    calm_since = calm_since if calm_since is not None else time.monotonic()
                    if time.monotonic() - calm_since >= float(al.get("buzz_rearm_s", 1.0)):
                        buzz_armed = True
                if shown is None:
                    vr.place("icon", None, 0)
                    vr.place("ring", None, 0)
                    vr.place_on_head("edge", None, 0)
                    prox.reset()
                if check is not None and check.needs_reanchor:  # a small notice low in your view until the anchor is redone
                    T = np.eye(4)
                    T[:3, 3] = [0.0, -0.35, -1.2]
                    T[:3, :3] = [[1, 0, 0], [0, np.cos(0.3), np.sin(0.3)], [0, -np.sin(0.3), np.cos(0.3)]]
                    vr.place_on_head("warn", T, 0.85)
                else:
                    vr.place_on_head("warn", None, 0)
                if stream is not None:  # sent from its own thread at vrchat.send_hz with the newest head pose
                    stream.set_cat(shown, alpha > 0, motion.kind(time.monotonic(), oc) if state == "seen" else "normal",
                                   close, raw_to_cam, heading.yaw)
            elif pos is not None and state == "seen":
                log.debug("cat at %s (camera space, %s, %d cameras)", np.round(pos, 2).tolist(), how, used)

            now = time.monotonic()
            if fresh:
                loops += 1
            if fresh and not args.headless and loops % show_every == 0:
                banner = {"hidden": "no cat", "seen": "cat", "lost": "cat last seen"}[state]
                if pos is not None:
                    banner += " at x %.2f  z %.2f  height %.2f m" % (pos[0], pos[2], pos[1])
                if dist is not None:
                    banner += "  |  %.1f m from you%s" % (dist, {"near": "  CLOSE", "underfoot": "  UNDERFOOT"}.get(level, ""))
                if state == "seen":
                    banner += "  |  %.2f m/s" % motion.speed
                if vr is not None and cam_to_raw is None:
                    banner += "  |  NO ANCHOR: press a"
                elif check is not None and check.needs_reanchor:
                    banner += "  |  RE-ANCHOR NEEDED: press a"
                if problem:
                    banner += "  |  " + problem[1].upper()
                if saver is not None and saver.on:
                    banner = saver.progress() + "\n" + banner  # its own line, above the tracker's
                    if dim_said[0] and time.monotonic() - dim_said[0] < 30:
                        banner = "The room is dim: capturing works, but labelling will be slower. More light helps." \
                            + "\n" + banner
                    if saver.asking(time.monotonic()):
                        banner = "NO CAT: " + NOCAT_ASK + "\n" + banner
                    if saver.enough and not said_enough[0]:  # once: then it's the user's call
                        said_enough[0] = True
                        log.info("Enough to train: cat seen in %d moments, in %d spots", saver.seen, len(saver.spots))
                        voice_say(ENOUGH_SAID)
                if last_problem[0]:
                    banner += "\nLast anchor walk didn't work: " + last_problem[0]
                if light.banner():
                    banner = light.banner() + "\n" + banner  # above the tracker's line
                g = with_button(tiles(items, names, boxes_all, picked, None, tile_h, banner, [c.rotation for c in cams]))
                cv2.imshow(win, g)
                if not getattr(on_mouse, "set", False):
                    cv2.setMouseCallback(win, on_mouse)
                    on_mouse.set = True
                key = cv2.waitKey(1) & 0xFF
                if redo_clicked[0]:
                    redo_clicked[0] = False
                    key = ord("a")
                if nocat_clicked[0]:
                    nocat_clicked[0] = False
                    key = ord("n")
                if key == ord("n") and capturing():  # NO CAT: the cat is out of the room (again: it's back)
                    what = saver.press_nocat(time.monotonic())
                    if what == "ask":
                        log.info("NO CAT: %s", NOCAT_ASK)
                        voice_say("Take your cat out and close the door so it can't come back in. Then press N again.")
                    else:
                        log.info("NO CAT %s (%d moments with it so far)", "on: the cat is out of the room"
                                 if what == "on" else "off: the cat is back", saver.nocat_n)
                        voice_say("No cat mode on." if what == "on" else "Normal capture again.")
                if key == 27 and capturing() and saver.cancel_nocat():  # Esc with NO CAT's instruction up: never mind
                    log.info("NO CAT: cancelled")
                    key = -1
                if key in (ord("q"), 27):
                    clean = True
                    break
                if key == ord("s"):
                    snap_dir.mkdir(parents=True, exist_ok=True)
                    p = snap_dir / f"{time.strftime('%Y%m%d-%H%M%S')}_cat.jpg"
                    cv2.imwrite(str(p), g)
                    log.info("Saved %s", p)
                if key == ord("c"):
                    if saver is None or not saver.on:
                        if saver is not None:
                            saver.close()
                        saver = FrameSaver(resolve_path("my_data/captures"), names, float(get(cfg, "cat.capture.every_s", 2.0)),
                           float(get(cfg, "cat.capture.min_free_gb", 5)), log, **enough_args(cfg))
                        saver.cats = int(get(cfg, "cat.label.cats", 1) or 1)
                        said_enough[0] = False
                        log.info("Capturing to %s", saver.dir)
                    else:
                        saver.close()
                        saver.on = False
                if key == ord("a") and vr is not None:
                    vr.place("icon", None, 0)
                    vr.place("ring", None, 0)
                    vr.place_on_head("edge", None, 0)
                    vr.place_on_head("warn", None, 0)
                    T = do_anchor(keeping=raw_to_cam is not None)
                    if T is not None:
                        raw_to_cam, cam_to_raw = T, np.linalg.inv(T)
                        last_problem[0] = None
                        check.reset()
                    heartbeat.beat(force=True)

            if now - last_log > 5:
                n = max(stats["n"], 1)
                log.info("%.0f detections/s, detector %.1f ms | cameras seeing it %.1f/4 | shown %.0f%% of the time | found by %s",
                         n / (now - last_log), np.mean(stats["det_ms"]), np.mean(stats["views"]), 100 * stats["seen"] / n,
                         stats["how"] or "")
                if tripwire.wakes != wakes_logged:
                    log.info("  tripwire: %d early looks (its spot changed between idle detections)",
                             tripwire.wakes - wakes_logged)
                    wakes_logged = tripwire.wakes
                log.info("  colours: %s", colour_report(items, names))
                from cat_tracker.locate import PARTIAL
                if PARTIAL["checked"]:
                    log.info("  partial views counted less: %d of %d moments with 3+ cameras", PARTIAL["down"],
                             PARTIAL["checked"])
                    PARTIAL["checked"] = PARTIAL["down"] = 0
                stats = {"n": 0, "det_ms": [], "views": [], "seen": 0, "how": {}}
                last_log = now
            if args.seconds and now - t0 > args.seconds:
                clean = True
                break
            if now - last_stop_check > 1.0:
                last_stop_check = now
                if stop_file.exists():
                    stop_file.unlink(missing_ok=True)
                    log.info("Asked to stop (stop_tracker.bat)")
                    clean = True
                    break
            took = time.perf_counter() - tick
            if took > 1.0 and loops > 20:  # (for tuning health.hang_s: the watchdog's limit)
                log.warning("Slow update: %.1f s", took)
            spare = period - took
            if spare > 0:
                time.sleep(spare)
    except KeyboardInterrupt:  # Ctrl+C in the console counts as closing it on purpose
        clean = True
    finally:
        if clean:
            heartbeat.stopped()  # the watchdog closes quietly; without this it warns you in VR
        if stream is not None:
            stream.stop()
        if osc is not None:
            osc.close()
        if saver is not None and saver.on:
            saver.close()
        for v in voices:
            v.close()
        if hard is not None:
            hard.close()
        light.log_readings()  # the room light as it ended
        for c in cams:
            c.stop()
        if not args.headless:
            cv2.destroyAllWindows()
        if vr is not None:
            vr.stop()
    log.info("Log: %s", log_file)
    return 0


if __name__ == "__main__":
    from core.runlog import exit_now
    exit_now(main())  # for certain: the cameras are free for the next tool at once
