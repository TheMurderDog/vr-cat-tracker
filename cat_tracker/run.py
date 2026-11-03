"""Cat tracker: cameras -> cat boxes -> 3D position -> SteamVR overlay at the real cat, and an arrow
at the edge of your view pointing to her when she's close.

Run from the camera core folder (SteamVR up your usual way):  python -m cat_tracker.run
  --reuse-anchor  skip the walk-around and use the last saved anchor (cat_tracker/data/anchor.json)
  --no-vr         detect and show her on the desktop only (no SteamVR needed)
  --capture       save frames for training from the start (also c in the window); see label.py
  --seconds N     stop after N seconds
  --osc           also send her position to VRChat for the avatar's cat prop (see osc.py)
  --headless      no window (how SteamVR starts it, see install_autostart.py); needs a saved anchor,
                  and closes when SteamVR does
In the window: q quits, a re-runs the anchor, s saves a snapshot, c starts/stops capturing. Uses the cameras itself, so other camera programs
track.bat can't run at the same time.
"""

import argparse
import json
import time

import cv2
import numpy as np

from capture.camera import camera_names, open_cameras
from cat_tracker import anchor as anc
from cat_tracker.alert import Heading, Motion, Proximity, Smoother
from cat_tracker import settings
from cat_tracker.detector import CatDetector, draw
from cat_tracker.collect import FrameSaver
from cat_tracker.hardframes import HardSaver
from cat_tracker.locate import CatTrack, locate, room_bounds, weak_matches
from cat_tracker.osc import OscCat, OscStream
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


def tiles(items, names, boxes_all, picked, views=None, tile_h=360, banner=None):
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
        s = tile_h / img.shape[0]
        img = cv2.resize(img, (int(img.shape[1] * s), tile_h), interpolation=cv2.INTER_AREA)
        cv2.putText(img, names[i], (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
        out.append(img)
    if not out:
        return None
    grid = np.vstack([np.hstack(out[:2]), np.hstack(out[2:])]) if len(out) == 4 else np.hstack(out)
    if banner:
        cv2.putText(grid, banner, (10, grid.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2, cv2.LINE_AA)
    return grid


def main():
    ap = argparse.ArgumentParser(description="Cat tracker")
    ap.add_argument("--config", help="camera core config.yaml (default: its own)")
    ap.add_argument("--cat-config", help="cat tracker config.yaml (default: cat_tracker/config.yaml)")
    ap.add_argument("--reuse-anchor", action="store_true")
    ap.add_argument("--no-vr", action="store_true")
    ap.add_argument("--seconds", type=float, default=0)
    ap.add_argument("--capture", action="store_true")
    ap.add_argument("--osc", action="store_true", help="send her position to VRChat over OSC")
    ap.add_argument("--headless", action="store_true", help="no window; needs a saved anchor")
    args = ap.parse_args()
    cfg = settings.load(args.config, args.cat_config)
    cc = cfg["cat"]
    dc, lc, fc, oc, al = (cc.get(k, {}) or {} for k in ("detector", "locate", "filter", "overlay", "alert"))
    log, log_file = start_run("cat_tracker", cfg)
    names = camera_names(cfg)
    data_dir = resolve_path(get(cfg, "calibration.dir", "calibration/data"))
    with open(data_dir / "room.json", "r", encoding="utf-8") as f:
        room = json.load(f)
    intrinsics = load_intrinsics(data_dir, names)
    rig = Rig(room, intrinsics)

    baseline.prepare_onnxruntime(get(cfg, "onnxruntime", {}) or {})
    dev = int(get(cfg, "gpu.device_id", 0))
    # the model reports weak boxes too; only confident ones (detector.score) find her on their own,
    # weak ones count where she is expected (another camera's sighting, or where she just was)
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

    cams, errors = open_cameras(cfg, log)
    if errors:
        log.error("Every camera must open (is another program, such as preview.bat, using them? they can't share cameras); stopping")
        for c in cams:
            c.stop()
        if vr is not None:
            vr.stop()
        return 1
    for c in cams:
        c.start()
    time.sleep(1.0)  # first frames
    if get(cfg, "cat.reset_white_balance", True):
        reset_white_balance(cams, cfg["cameras"], log, names)

    tile_h = int(get(cfg, "cat.preview.tile_height", 360))
    show_every = max(1, int(get(cfg, "cat.preview.show_every_n", 2)))
    win = "Cat tracker (q quits, a re-anchors, s saves a snapshot)"

    def show_anchor(items, views):
        g = tiles(items, names, None, [None] * len(items), views, tile_h, "Anchoring: headset on, walk slowly around the room")
        if g is not None:
            cv2.imshow(win, g)
        return (cv2.waitKey(1) & 0xFF) not in (ord("q"), 27)

    def do_anchor():
        T = anc.run(cfg, cams, rig, vr, log, show_anchor)
        if T is None:
            log.error("No anchor: her marker can't be placed in SteamVR until one succeeds (press a to retry)")
        return T

    raw_to_cam = cam_to_raw = None
    if vr is not None:
        raw_to_cam = anc.load(cfg) if args.reuse_anchor else None
        if raw_to_cam is not None:
            log.info("Using the saved anchor from %s", get(cfg, "cat.anchor.file"))
        elif args.headless:
            log.error("No saved anchor, and there's no window to make one in: run run.bat once and do the walk-around")
            for c in cams:
                c.stop()
            vr.stop()
            return 1
        else:
            raw_to_cam = do_anchor()
        cam_to_raw = np.linalg.inv(raw_to_cam) if raw_to_cam is not None else None
        vr.add_overlay("icon", resolve_path(oc["icon"]), oc.get("icon_width_m", 0.28))
        vr.add_overlay("ring", resolve_path(oc["ring"]), oc.get("ring_width_m", 0.55))
        vr.add_overlay("edge", resolve_path(al.get("image", "cat_tracker/assets/edge_arrow.png")), al.get("width_m", 0.07))
        vr.add_overlay("warn", resolve_path(get(cfg, "cat.anchor_check.image", "cat_tracker/assets/anchor_warning.png")), 0.5)
        if al.get("buzz", True):
            vr.setup_haptics(resolve_path("cat_tracker/input/actions.json"), log)

    bounds = room_bounds(rig, float(lc.get("room_margin_m", 0.15)))
    log.info("Room (from the camera positions): x %.2f to %.2f m, z %.2f to %.2f m", *bounds)
    saver = FrameSaver(resolve_path("cat_tracker/captures"), names, float(get(cfg, "cat.capture.every_s", 2.0)),
                           float(get(cfg, "cat.capture.min_free_gb", 5)), log) if args.capture else None
    track = CatTrack(fc, float(oc.get("lost_alpha", 0.6)))
    motion, prox, heading = Motion(oc), Proximity(al), Heading(oc)
    smooth = Smoother(float(oc.get("smooth_s", 0.15)))
    buzz_armed, calm_since = True, None  # one buzz pattern each time the warning comes on, see alert.buzz_rearm_s
    hc = cc.get("hard_frames", {}) or {}
    hard = HardSaver(resolve_path("cat_tracker/captures"), names, hc, lc, log) if hc.get("enabled", True) else None
    check = anc.AnchorCheck(cfg, log) if vr is not None else None
    icons = {k: resolve_path(oc[k]) for k in ("icon", "icon_close", "icon_rest", "icon_move") if oc.get(k)}
    osc = OscCat(cc.get("vrchat", {}) or {}) if args.osc and vr is not None else None
    if args.osc and vr is None:
        log.warning("--osc needs SteamVR (her offset is measured from your headset); not sending")
    stream = None
    if osc is not None:
        send_hz = float((cc.get("vrchat", {}) or {}).get("send_hz", 60))
        stream = OscStream(osc, vr, send_hz, log)
        log.info("Sending her position to VRChat over OSC at %s:%d, %g a second", *osc.addr, send_hz)
    floor_y = float(lc.get("floor_y_m", 0.0))
    # detections per second: the full rate only while she's moving or close to you; she's mostly asleep
    # or out of the room, and then a slower rate is plenty (and saves the GPU)
    fast_period = 1.0 / float(dc.get("rate_hz", 8))
    idle_period = 1.0 / float(dc.get("idle_rate_hz", 3))
    det_period = idle_period
    period = 1.0 / float(oc.get("update_hz", 30))
    last_det = -1e9
    snap_dir = resolve_path(cfg["logging"]["dir"]) / "snapshots"
    stats = {"n": 0, "det_ms": [], "views": [], "seen": 0, "how": {}}
    t0 = last_log = last_stop_check = time.monotonic()
    stop_file = resolve_path("cat_tracker/data/stop")  # stop_tracker.bat makes it, to close a tracker with no window
    stop_file.unlink(missing_ok=True)
    loops = 0
    close = False  # from the last update, used to pick the detection rate
    try:
        while True:
            tick = time.perf_counter()
            # detection runs at detector.rate_hz (a few times a second is plenty for a cat); the overlays,
            # edge arrow and OSC offset follow your head at overlay.update_hz using her last position
            fresh = time.monotonic() - last_det >= det_period
            if fresh:
                items = [c.latest(rotated=False) for c in cams]
                if any(it is None for it in items):
                    time.sleep(0.01)
                    continue
                last_det = time.monotonic()
                td = time.perf_counter()
                boxes_all = det([it[0] for it in items])
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
                elif state == "hidden":  # a brief "last seen" doesn't restart her sleep timer; gone for good does
                    motion.update(None, now)
                heading.update(pos if state == "seen" else None, now, gone=state == "hidden")
                if check is not None:
                    check.step(items, rig, vr, raw_to_cam, now)
                busy = state == "seen" and (motion.speed > float(oc.get("still_speed", 0.1)) or close)
                det_period = fast_period if busy else idle_period

            close = False
            dist = level = None
            if vr is not None and vr.quit_requested():
                log.info("SteamVR is closing; stopping")
                break
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
                    if close:  # her direction as seen from the headset, so the arrow points at her
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
                if check is not None and check.off:  # a small notice low in your view until the anchor is redone
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
                if saver is not None and saver.on:
                    banner += "  |  CAPTURING (%d)" % saver.n
                g = tiles(items, names, boxes_all, picked, None, tile_h, banner)
                cv2.imshow(win, g)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
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
                        saver = FrameSaver(resolve_path("cat_tracker/captures"), names, float(get(cfg, "cat.capture.every_s", 2.0)),
                           float(get(cfg, "cat.capture.min_free_gb", 5)), log)
                        log.info("Capturing to %s", saver.dir)
                    else:
                        saver.close()
                        saver.on = False
                if key == ord("a") and vr is not None:
                    vr.place("icon", None, 0)
                    vr.place("ring", None, 0)
                    vr.place_on_head("edge", None, 0)
                    vr.place_on_head("warn", None, 0)
                    T = do_anchor()
                    if T is not None:
                        raw_to_cam, cam_to_raw = T, np.linalg.inv(T)
                        check.reset()

            if now - last_log > 5:
                n = max(stats["n"], 1)
                log.info("%.0f detections/s, detector %.1f ms | cameras seeing her %.1f/4 | shown %.0f%% of the time | found by %s",
                         n / (now - last_log), np.mean(stats["det_ms"]), np.mean(stats["views"]), 100 * stats["seen"] / n,
                         stats["how"] or "")
                log.info("  colours: %s", colour_report(items, names))
                stats = {"n": 0, "det_ms": [], "views": [], "seen": 0, "how": {}}
                last_log = now
            if args.seconds and now - t0 > args.seconds:
                break
            if now - last_stop_check > 1.0:
                last_stop_check = now
                if stop_file.exists():
                    stop_file.unlink(missing_ok=True)
                    log.info("Asked to stop (stop_tracker.bat)")
                    break
            spare = period - (time.perf_counter() - tick)
            if spare > 0:
                time.sleep(spare)
    finally:
        if stream is not None:
            stream.stop()
        if osc is not None:
            osc.close()
        if saver is not None and saver.on:
            saver.close()
        if hard is not None:
            hard.close()
        for c in cams:
            c.stop()
        if not args.headless:
            cv2.destroyAllWindows()
        if vr is not None:
            vr.stop()
    log.info("Log: %s", log_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
