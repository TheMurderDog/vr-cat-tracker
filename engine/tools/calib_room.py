"""Place every camera in SteamVR space using a tracker (or controller) with the printed marker on it.

Before running: SteamVR up (your usual way), the tracker (or controller) on the card switched on and tracking, every camera's lens
calibrated (my_data/calibration/intrinsics_<name>.json), the marker printed on stiff card with the tracker fixed
rigidly to it, sticking up past the card's edge so the card doesn't block its sensors.

Run from engine/ (2_calibrate_cameras/2_room_calibration.bat does this):  python -m tools.calib_room
  --resolve    solve again from the last recording, without walking
  --quiet      no voice or beeps
  --practice   a rehearsal for testing: 4 stops per camera, in my_data/practice/room (wiped each time); it reads the
               lens results but never writes the real room calibration

First it asks you to wave the card: the tracker or controller that moves the most is the one used (remembered in
room_device.json for next time and for the check step; calibration.room.device_serial in the settings overrides it).
The cameras open meanwhile, on a worker thread, and each one is used as soon as it's ready.
Walk slowly around the whole room holding the marker toward the cameras, at different heights (floor to head),
stopping for a moment at each spot; tilt the card 20-30 degrees forward or back at about every third stop (if the
tracker only ever turns flat, camera heights can't be pinned down). A stop is kept while the tracker is still and at
least min_spacing_m from the last kept one; it counts for every camera that sees the marker, and a chime marks it.
The voice says which camera needs stops most. It solves by itself when every camera reaches target_per_camera, or,
if no camera has gained a stop for stuck_after_s and each has stuck_min_per_camera, after a short countdown. c solves
now; q asks whether to solve with what you have. A camera that isn't GOOD yet doesn't end the run: the good ones are
kept and marked done, and you walk again for the others, with what each needs shown and said (calibration.room_needs
works it out: more stops, nearer the edges of its view, closer and farther, low and high, tilted). The stops are saved
as you walk (room_recording.json), so after a quit or crash the next run offers to continue them. The result (GOOD or
not, per camera) is shown and spoken; the previous room calibration, reference pictures and recording are copied to
my_data/backups before the first save.
"""

import argparse
import json
import shutil
import threading
import time

import cv2
import numpy as np

from calibration import intrinsics as intr
from calibration import room, room_needs, wave
from calibration.vr import VRPoller
from capture.camera import camera_keys, camera_names, open_cameras, outlined_text, spoken, spoken_list, tile_grid
from core.config import DATA, get, load_config, resolve_path
from core.runlog import start_run

GREEN, YELLOW, RED, WHITE = (80, 220, 80), (0, 210, 255), (80, 80, 255), (240, 240, 240)
MIN_SOLVE = 6  # fewest stops per camera to solve from (q / c / stuck); target_per_camera is the normal finish


def load_intrinsics(data_dir, names):
    out = []
    for name in names:
        p = data_dir / f"intrinsics_{name}.json"
        if not p.is_file():
            raise FileNotFoundError(f"{p} is missing; run calib_intrinsics for the {name} camera first")
        out.append(intr.load(p))
    return out


def missing_lenses(data_dir, names):
    """Cameras with no lens calibration yet."""
    return [n for n in names if not (data_dir / f"intrinsics_{n}.json").is_file()]


def connect_vr(cfg, rc, log):
    """Attach to SteamVR. Returns the poller, or None (logged) when SteamVR isn't running."""
    try:
        vr = VRPoller(get(cfg, "steamvr.tracking_universe", "standing"), int(rc.get("vr_rate_hz", 250)))
    except Exception as e:  # noqa: BLE001  (openvr raises its own errors when SteamVR isn't running)
        log.error("SteamVR isn't running (%s)", e)
        return None
    for d in vr.devices():
        log.info("SteamVR device %d: %s %s", *d)
    return vr


def saved_device(path):
    """The serial of the card's device chosen last time (room_device.json), or None."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return str(json.load(f)["serial"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_device(path, kind, serial):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"kind": kind, "serial": serial}, f, indent=2)


STEAMVR_WAIT = "Waiting for SteamVR to see your base stations and tracker..."
STEAMVR_WAIT_HINT = "Check the base stations are on and the tracker's light is green. This goes on by itself."


def wave_pick(vr, win, voice, size, log, seconds=4.0, rate_hz=60, early_after_s=1.0):
    """Ask for the card's device to be waved, and pick the one that moved the most by a clear margin. It stops as
    soon as one clearly wins (after early_after_s), else after seconds. Returns (index, kind, serial), or None if quit
    (q / Esc)."""
    from tools.calib_intrinsics import big_text, overlay
    blank = np.zeros((size[1], size[0], 3), np.uint8)
    ask = "Wave the tracker or controller on Board B."
    waiting_since = None
    while True:
        every = vr.devices()
        devs = [d for d in every if d[1] in wave.PICKABLE]
        tracked = devs and any(p is not None for p in vr.positions([i for i, _, _ in devs]).values())
        if any(k == "tracker" for _, k, _ in devs) and not any(k == "base station" for _, k, _ in every):
            tracked = False  # a tracker needs base stations: SteamVR hasn't found them yet (just started)
        if devs and not tracked:  # SteamVR is still starting (no base stations yet), or the device isn't tracked
            if waiting_since is None:
                waiting_since = time.monotonic()
                log.info("Waiting for SteamVR to track: %s", [f"{k} {s}" for _, k, s in devs])
            disp = blank.copy()
            big_text(disp, STEAMVR_WAIT, int(size[1] * 0.4), 1.0, YELLOW)
            big_text(disp, STEAMVR_WAIT_HINT, int(size[1] * 0.5), 0.8, WHITE)
            win.show(overlay(disp, "Room calibration", "", "Waiting for SteamVR", "", YELLOW, "q quit"))
            voice.say(STEAMVR_WAIT, force=True, every=12)
            voice.tick()
            if cv2.waitKey(200) & 0xFF in (ord("q"), 27):
                return None
            continue
        if waiting_since is not None:
            log.info("SteamVR is tracking now (waited %.0f s)", time.monotonic() - waiting_since)
            waiting_since = None
        if not devs:
            disp = blank.copy()
            big_text(disp, "Switch on the tracker or controller on Board B", int(size[1] * 0.45), 1.0, YELLOW)
            win.show(overlay(disp, "Room calibration", "", "No tracker or controller found", "", RED, "q quit"))
            voice.say("I can't find a tracker or controller. Switch on the one on Board B.", force=True, every=8)
            voice.tick()
            if cv2.waitKey(200) & 0xFF in (ord("q"), 27):
                return None
            continue
        voice.say(ask, force=True)
        tracks = {i: (k, []) for i, k, _ in devs}
        start = time.monotonic()
        end = start + seconds
        index, why = None, "none"
        while (now := time.monotonic()) < end:
            for i, p in vr.positions(list(tracks)).items():
                tracks[i][1].append(p)
            if now - start >= early_after_s:
                index, why = wave.choose(tracks, min_path_m=1.5 * wave.MIN_PATH_M)  # a clear winner already
                if why is None:
                    break
            disp = blank.copy()
            big_text(disp, ask, int(size[1] * 0.4), 1.1, WHITE)
            win.show(overlay(disp, "Room calibration", "Which device is on Board B?", "Wave it now", "", YELLOW,
                             "q quit"))
            voice.tick(now)
            if cv2.waitKey(max(1, int(1000 / rate_hz))) & 0xFF in (ord("q"), 27):
                return None
        if why is not None:
            index, why = wave.choose(tracks)
        lengths = {i: round(wave.path_length(t[1]), 2) for i, t in tracks.items()}
        log.info("Wave: moved %s m in %.1f s -> %s", {f"{k} {s}": lengths[i] for i, k, s in devs},
                 time.monotonic() - start, index if why is None else why)
        if why is None:
            kind, serial = next((k, s) for i, k, s in devs if i == index)
            return index, kind, serial
        ask = ("Two devices moved about the same. Wave only the one on Board B." if why == "tie" else
               "I didn't see anything move. Wave the tracker or controller on Board B.")


def pick_device(vr, rc, win, voice, size, log, device_file):
    """The card's device, straight away: device_serial from the settings if set; else the one used last time if it's
    switched on; else wave to pick (remembered in device_file). Returns (kind, serial, reused) or None if quit.
    reused: last time's device was taken without waving (the caller lets w choose another)."""
    devs = vr.devices()
    fixed = rc.get("device_serial") or None
    for serial, reused in ((fixed, False), (None if fixed else saved_device(device_file), True)):
        hit = next((d for d in devs if serial and d[2] == serial), None)
        if hit:
            vr.use(hit[0])
            if reused:
                voice.say(f"Using the same {hit[1]} as last time.", force=True)
            return hit[1], hit[2], reused
    if fixed:
        log.warning("device_serial %s isn't switched on; wave to pick instead", fixed)
    return wave_and_use(vr, win, voice, size, log, device_file)


def wave_and_use(vr, win, voice, size, log, device_file):
    got = wave_pick(vr, win, voice, size, log)
    if got is None:
        return None
    index, kind, serial = got
    vr.use(index)
    save_device(device_file, kind, serial)
    voice.click()
    voice.say(f"Got the {kind}.", force=True)  # no pause: straight on
    return kind, serial, False


class DeviceWatch:
    """Notices when the card's tracker or controller stops tracking or turns off (controllers go to sleep when they're
    not held), says so plainly, and follows it again when it comes back, even under a new SteamVR device number."""

    def __init__(self, vr, kind, serial, log, check_every_s=1.0):
        self.vr, self.kind, self.serial, self.log, self.every = vr, kind, serial, log, check_every_s
        self.off, self.next_check = False, 0.0

    def check(self, now, voice):
        """(latest sample or None, None if fine else (instruction, colour)), speaking the problem when needed."""
        s = self.vr.at(time.perf_counter_ns() - 20_000_000)
        if s is not None:
            self.off = False
            return s, None
        if now >= self.next_check:
            self.next_check = now + self.every
            idx = next((i for i, _, sr in self.vr.devices() if sr == self.serial), None)
            if idx is None and not self.off:
                self.log.warning("The %s %s turned off or disconnected", self.kind, self.serial)
            self.off = idx is None
            if idx is not None and idx != self.vr.index:
                self.log.info("The %s %s is back (SteamVR device %d)", self.kind, self.serial, idx)
                self.vr.use(idx)
        if self.off:
            voice.say(f"Your {self.kind} turned off. Switch it back on.", now, every=10)
            return None, (f"Your {self.kind} turned off: switch it back on", RED)
        voice.say(f"{self.kind.capitalize()} lost", now)
        return None, (f"{self.kind.capitalize()} lost: is it on and tracking?", RED)


def backup_previous(data_dir, backups, names):
    """Copy the room calibration, its reference pictures and recording to a dated folder in backups (if any)."""
    files = [data_dir / "room.json", data_dir / "room_recording.json"] + [data_dir / f"reference_{n}.png" for n in names]
    files = [f for f in files if f.is_file()]
    if not files:
        return None
    dest = backups / f"room_{time.strftime('%Y%m%d-%H%M%S')}"
    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(f, dest / f.name)
    return dest


def should_finish_stuck(counts, target, last_gain, now, min_each, quiet_s):
    """True when no camera has gained a stop for quiet_s, every camera has min_each, and some are short of target."""
    return min(counts) < target and min(counts) >= min_each and now - last_gain >= quiet_s


# ---- the recording: saved as you walk, so a crash or quit can be continued ---------------------------------------

def save_recording(path, obs, keys, serial, solved=False):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:  # JSON, not pickle: loading it can never run code
        json.dump({"obs": [[int(o[0])] + [np.asarray(v, np.float64).tolist() for v in o[1:]] for o in obs],
                   "counts": [sum(1 for o in obs if o[0] == s) for s in range(len(keys))],
                   "keys": list(keys), "serial": serial, "solved": bool(solved),
                   "updated": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
    tmp.replace(path)  # never a half-written file


def load_recording(path):
    with open(path, "r", encoding="utf-8") as f:
        rec = json.load(f)
    rec["obs"] = [(int(o[0]), np.asarray(o[1], np.float64), np.asarray(o[2], np.float64), np.asarray(o[3], np.float64))
                  for o in rec["obs"]]
    return rec


def unfinished_recording(path, keys, serial):
    """The last walk's stops if it can be continued: not solved, same cameras, same device. Else None."""
    try:
        rec = load_recording(path)
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None
    if rec.get("solved") or not rec["obs"]:
        return None
    if rec.get("keys", rec.get("names")) not in (None, list(keys)) or rec.get("serial") not in (None, serial):
        return None  # other cameras (older files kept the names, which were the keys then)
    if any(o[0] >= len(keys) for o in rec["obs"]):
        return None
    return rec


REF_AFTER_FRAMES = 30  # a camera's reference picture is taken this many frames in, once its exposure has settled


def recording_refs_dir(rec_path):
    """Each camera's picture from the walk, kept with its stops (room_recording_refs/<key>.png), so a continued walk
    can tell whether a camera has moved since."""
    return rec_path.parent / (rec_path.stem + "_refs")


def check_unmoved(prev, now_refs, keys, names, limit_px, min_conf, done, log, timeout_s=30.0):
    """Compare each camera's picture from the last walk (prev: {slot: image}) with its picture now (now_refs, filled
    in as the cameras open). Returns {slot: reason} for cameras whose old stops must go: moved, or unsure (the view
    changed too much to compare). Cameras with no old picture are kept. Runs until every camera is checked or
    timeout_s; done(slot, reason or None) is called for each as it's decided."""
    from calibration.drift import image_shift
    out, pending = {}, set(prev)
    end = time.monotonic() + timeout_s
    while pending and time.monotonic() < end:
        for slot in sorted(pending):
            if slot not in now_refs:
                continue
            pending.discard(slot)
            dx, dy, conf = image_shift(prev[slot], now_refs[slot])
            shift = float(np.hypot(dx, dy))
            reason = ("moved" if shift > limit_px else None) if conf >= min_conf else "unsure"
            log.info("%s: %.1f px from its picture in the last walk (confidence %.2f)%s", names[slot], shift, conf,
                     f": {reason}, its old stops are dropped" if reason else "")
            if reason:
                out[slot] = reason
            done(slot, reason)
        time.sleep(0.1)
    return out


def save_room(log, out, names, rc, data_dir, refs, keys=None):
    """Write room.json (and reference pictures for the drift check). Returns True if every camera is GOOD."""
    keys = keys or names
    for cam, name, key in zip(out["cameras"], names, keys):
        cam["name"], cam["key"] = name, key  # found by key; the name is a label
    out["universe"] = "standing"
    out["created"] = time.strftime("%Y-%m-%d %H:%M:%S")
    good = all(c["rms_px"] <= float(rc.get("max_rms_px", 3.0)) for c in out["cameras"])
    path = data_dir / "room.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    for i, f in refs.items():
        cv2.imwrite(str(data_dir / f"reference_{keys[i]}.png"), f)
    log.info("\nRoom calibration saved: %s (%s)", path, "every camera FIT GOOD" if good else "see each camera's result")
    return good


def solve_and_save(log, obs, intrinsics, names, rc, data_dir, refs):
    """Solve and save (raises if a camera can't be placed). Returns (good, out)."""
    log.info("\nSolving from %d observations", len(obs))
    out = room.solve(obs, intrinsics, len(names), log=log, names=names)
    return save_room(log, out, names, rc, data_dir, refs), out


FIT = {"GOOD": "FIT GOOD", "OK": "FIT OK", "NOT GOOD": "FIT NOT GOOD"}  # what the labels grade: how well it fits


def result_lines(out, rc, ok_px=None):
    """[(text, colour)] per camera, plus the advice, for the result screen. With ok_px, a camera between max_rms_px
    and ok_px says OK (a little less precise, fine to use)."""
    limit = float(rc.get("max_rms_px", 3.0))
    lines = []
    for c in out["cameras"]:
        label = "GOOD" if c["rms_px"] <= limit else "OK" if ok_px and c["rms_px"] <= ok_px else "NOT GOOD"
        x, y, z = c["position_m"]
        lines.append((f"{c['name']}: {FIT[label]}   {c['rms_px']:.1f} px   {y:.1f} m up",
                      GREEN if label == "GOOD" else YELLOW if label == "OK" else RED))
    if out.get("tilt_spread_deg", 90) < 10:
        lines.append(("Board B barely tilted: camera heights may be off. Walk it again, tilting it now and then.", YELLOW))
    return lines


def and_list(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


# ---- screens ---------------------------------------------------------------------------------------------------

def message_screen(win, voice, title, lines, said, color=YELLOW, size=(1280, 720), keys="any key to close"):
    """A full-screen message, spoken once, until a key is pressed."""
    from tools.calib_intrinsics import big_text, overlay
    disp = np.zeros((size[1], size[0], 3), np.uint8)
    for j, (text, col) in enumerate(lines):
        big_text(disp, text, int(size[1] * 0.2) + 56 * j, 1.0, col)
    win.show(overlay(disp, "Room calibration", "", title, "", color, keys))
    voice.say(said, force=True)
    while cv2.waitKey(50) == -1:
        voice.tick()


def continue_screen(win, voice, size, stops, wait_s=5.0):
    """'Continue the last walk?' Enter / c continues, r starts over; no key continues after wait_s."""
    from tools.calib_intrinsics import big_text, overlay
    voice.say(f"Continuing your last walk, with {stops} stops. Press R to start over.", force=True)
    end = time.monotonic() + wait_s
    while (now := time.monotonic()) < end:
        disp = np.zeros((size[1], size[0], 3), np.uint8)
        big_text(disp, f"Your last walk has {stops} stops kept", int(size[1] * 0.4), 1.1, GREEN)
        big_text(disp, f"Continuing in {int(end - now) + 1} s", int(size[1] * 0.55), 1.0, WHITE)
        win.show(overlay(disp, "Room calibration", "", "Continue the last walk?", "", GREEN,
                         "Enter continue   r start over   q quit"))
        voice.tick(now)
        key = cv2.waitKey(50) & 0xFF
        if key in (13, ord("c")):
            return "continue"
        if key == ord("r"):
            return "start"
        if key in (ord("q"), 27):
            return "quit"
    return "continue"


def tiles_for(opened, names, latest_px, counts, targets, done, focus, tile_h, cfg):
    """One tile per camera: its counter, GOOD once done, a thick yellow frame on the one that needs stops most,
    and 'starting' while it is still opening."""
    w, h = int(cfg["cameras"]["width"]), int(cfg["cameras"]["height"])
    tiles = []
    for slot, name in enumerate(names):
        c = opened.get(slot)
        item = c.latest(rotated=False) if c is not None else None
        img = np.zeros((h, w, 3), np.uint8) if item is None else item[0].copy()
        if latest_px[slot] is not None and c is not None:
            cv2.circle(img, tuple(int(v) for v in latest_px[slot]), 22, GREEN, 4)
        if c is not None and c.rotation is not None:
            img = cv2.rotate(img, c.rotation)
        img = cv2.resize(img, (int(img.shape[1] * tile_h / img.shape[0]), tile_h), interpolation=cv2.INTER_AREA)
        s = tile_h / 640
        if c is None:
            text, col = f"{name}  starting...", WHITE
        elif slot in done:
            text, col = f"{name}  FIT GOOD", GREEN
        else:
            text, col = f"{name}  {counts[slot]}/{targets[slot]}", GREEN if counts[slot] >= targets[slot] else YELLOW
        outlined_text(img, text, (14, int(62 * s)), cv2.FONT_HERSHEY_SIMPLEX, 1.7 * s, col, max(2, int(4 * s)),
                      cv2.LINE_AA)
        if slot == focus:
            cv2.rectangle(img, (0, 0), (img.shape[1] - 1, img.shape[0] - 1), YELLOW, max(6, int(12 * s)))
        elif slot in done:
            cv2.rectangle(img, (0, 0), (img.shape[1] - 1, img.shape[0] - 1), GREEN, max(3, int(4 * s)))
        tiles.append(img)
    return tiles


def main():
    ap = argparse.ArgumentParser(description="Place the cameras in SteamVR space")
    ap.add_argument("--config")
    ap.add_argument("--resolve", action="store_true", help="solve again from the last recording")
    ap.add_argument("--quiet", action="store_true", help="no voice or beeps")
    ap.add_argument("--practice", action="store_true", help="rehearse: 4 stops per camera, nothing real saved")
    args = ap.parse_args()
    cfg = load_config(args.config)
    rc = dict(get(cfg, "calibration.room"))
    log, log_file = start_run("calib_room", cfg)
    lens_dir = resolve_path(get(cfg, "calibration.dir", "my_data/calibration"))
    data_dir = lens_dir
    names = camera_names(cfg)
    rc["_keys"] = camera_keys(cfg)  # what the files are filed under (stays the same when cameras are renamed)
    size = (int(cfg["cameras"]["width"]), int(cfg["cameras"]["height"]))
    from tools import calib_intrinsics as ci
    from tools.voice import Voice
    if args.practice:
        if args.resolve:
            log.error("--practice can't be used with --resolve")
            return 1
        data_dir = DATA / "practice" / "room"  # throwaway: the real room calibration is never read or written
        shutil.rmtree(data_dir, ignore_errors=True)
        data_dir.mkdir(parents=True)
        rc.update(target_per_camera=4)
        ci.PRACTICE = True
        log.info("PRACTICE RUN in %s: 4 stops per camera; only the lens results are read", data_dir)
    voice = Voice(on=not args.quiet and bool(rc.get("voice", True)), volume=float(get(cfg, "calibration.voice_volume", 0.8)),
                  prerender=["Now tilt Board B a little.", STEAMVR_WAIT, "Tracker lost", "Controller lost", "Got the tracker.",
                             "Got the controller.", "Wave the tracker or controller on Board B.",
                             "Solving. Please wait.", "Practice run. Nothing is saved."])
    win = ci.Window("Room calibration")
    try:
        run(args, cfg, rc, log, log_file, lens_dir, data_dir, names, size, voice, win, ci)
        return 0  # every ending (GOOD, not yet, quit, a problem) was shown and spoken; only a crash is an error
    finally:
        cv2.destroyAllWindows()
        voice.close()


def run(args, cfg, rc, log, log_file, lens_dir, data_dir, names, size, voice, win, ci):
    n = len(names)
    keys = rc.get("_keys") or names
    rec_path = data_dir / "room_recording.json"
    max_rms = float(rc.get("max_rms_px", 3.0))
    missing = [names[keys.index(k)] for k in missing_lenses(lens_dir, keys)]
    if missing:
        message_screen(win, voice, "Lens calibration first", [(f"Not done yet: {', '.join(missing)}", YELLOW),
                       ("Run 1_lens_calibration.bat for those cameras, then this again.", WHITE)],
                       f"First do the lens calibration for the {', '.join(missing)} camera.", size=size)
        return 1
    intrinsics = load_intrinsics(lens_dir, keys)

    if args.resolve:
        rec = load_recording(rec_path)
        refs = {i: cv2.imread(str(data_dir / f"reference_{keys[i]}.png")) for i in range(n)}
        log.info("\nSolving from %d observations", len(rec["obs"]))
        out, needs = room_needs.try_solve(rec["obs"], intrinsics, names, size, max_rms, log)
        if out is None:
            message_screen(win, voice, "Couldn't place every camera", [(t, YELLOW) for v in needs.values() for t in v[:1]],
                           "Some cameras need more stops. Run room calibration to continue the walk.", RED, size)
            return 1
        backup_previous(data_dir, DATA / "backups", keys)
        ok = save_room(log, out, names, rc, data_dir, {k: v for k, v in refs.items() if v is not None}, keys)
        if ok:
            save_recording(rec_path, rec["obs"], keys, rec.get("serial"), solved=True)
        show_result(win, voice, out, rc, ok, size, False)
        log.info("Log: %s", log_file)
        return 0 if ok else 1

    from core.single import hold_cameras
    hold_cameras(log, say=lambda t: (voice.say(t, force=True), voice.flush()), show=True)  # a window says who has them
    vr = connect_vr(cfg, rc, log)
    if vr is None:
        message_screen(win, voice, "SteamVR isn't running", [("Start SteamVR, then run this again.", YELLOW)],
                       "Start SteamVR first, then run this again.", RED, size)
        return 1

    # ---- shared state; the cameras open on a worker thread while you wave, each one used as soon as it's ready ----
    lock = threading.Lock()
    obs, last_kept, counts, latest_px, refs = [], {}, [0] * n, [None] * n, {}
    skipped = {"tracker lost": 0, "moving": 0, "same spot": 0}  # why marker sightings were not kept
    every = int(rc.get("detect_every_n_frames", 3))
    still = float(rc.get("still_speed_m_s", 0.05))
    spacing = float(rc.get("min_spacing_m", 0.05))
    marker_id = int(rc["marker_id"])
    latency_ns = int(float(rc.get("frame_latency_ms", 15)) * 1e6)
    detectors = [room.marker_detector(rc) for _ in range(n)]  # one each: detectors are not thread-safe
    state = {"walking": False, "opening": True}
    opened, cam_errors = {}, []

    def hook_for(c):
        k = {"n": 0}

        def hook(frame, t_ns):
            k["n"] += 1
            if c.slot not in refs and k["n"] >= REF_AFTER_FRAMES:
                refs[c.slot] = frame.copy()
            if not state["walking"] or k["n"] % every:
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
            with lock:
                last_kept[c.slot] = pos
                obs.append((c.slot, px, pos, rot))
                counts[c.slot] += 1
        return hook

    def on_open(cam):
        cam.frame_hook = hook_for(cam)
        cam.start()
        opened[cam.slot] = cam

    def opener():
        try:
            _, errs = open_cameras(cfg, log, on_open)
            cam_errors.extend(errs)
        except Exception as e:  # noqa: BLE001
            log.error("Opening the cameras failed: %s", e)
            cam_errors.append((0, -1, str(e)))
        finally:
            state["opening"] = False

    t_start = time.monotonic()
    opening = threading.Thread(target=opener, name="open cameras", daemon=True)
    opening.start()

    def close_all():
        state["walking"] = False
        opening.join(timeout=30)
        for c in list(opened.values()):
            c.frame_hook = None
        for c in list(opened.values()):
            c.stop()
        vr.stop()

    try:
        picked = pick_device(vr, rc, win, voice, size, log, data_dir / "room_device.json")
        if picked is None:
            return 1
        kind, serial, reused = picked
        log.info("Using %s %s (%.1f s after start)", kind, serial, time.monotonic() - t_start)
        vr.start()
        prev = None if ci.PRACTICE else unfinished_recording(rec_path, keys, serial)
        if prev is not None:
            choice = continue_screen(win, voice, size, len(prev["obs"]))
            if choice == "quit":
                return 1
            if choice == "continue":
                obs.extend(prev["obs"])
                for o in prev["obs"]:
                    counts[o[0]] += 1
                log.info("Continuing the last walk: %s stops per camera", counts)
                state["continuing"] = True
                prev_refs = {}
                for s_, k_ in enumerate(keys):  # its pictures from that walk (older walks: the room's reference)
                    for path in (recording_refs_dir(rec_path) / f"{k_}.png", data_dir / f"reference_{k_}.png"):
                        img = cv2.imread(str(path)) if path.is_file() else None
                        if img is not None:
                            prev_refs[s_] = img
                            break

                def drop(slot, reason):  # a camera that moved since: its old stops go, the others' stay
                    if not reason:
                        return
                    with lock:
                        kept = [o for o in obs if o[0] != slot]
                        gone = len(obs) - len(kept)
                        obs[:] = kept
                        counts[slot] = 0
                        last_kept.pop(slot, None)
                    state.setdefault("moved", set()).add(slot)
                    state.setdefault("notices", []).append(
                        f"{spoken(names[slot], True)} has moved since your last walk, so its {gone} old stops were "
                        "dropped. Walk again for it." if reason == "moved" else
                        f"I couldn't tell whether {spoken(names[slot])} moved, so its {gone} old stops were "
                        "dropped to be safe.")
                drift = dict(get(cfg, "calibration.drift", {}) or {})
                state["checking"] = True  # no solving until every camera is checked

                def checker():
                    try:
                        check_unmoved(prev_refs, refs, keys, names, float(drift.get("max_shift_px", 2.0)),
                                      float(drift.get("min_confidence", 0.2)), drop, log)
                    finally:
                        state["checking"] = False
                threading.Thread(target=checker, name="moved since?", daemon=True).start()
        result = walk_rounds(rc, cfg, log, names, size, voice, win, ci, vr, kind, serial, reused, data_dir, rec_path,
                             intrinsics, obs, counts, latest_px, refs, skipped, opened, cam_errors, state, lock,
                             t_start, max_rms)
    finally:
        close_all()
    log.info("Log: %s", log_file)
    return result


def walk_rounds(rc, cfg, log, names, size, voice, win, ci, vr, kind, serial, reused, data_dir, rec_path, intrinsics,
                obs, counts, latest_px, refs, skipped, opened, cam_errors, state, lock, t_start, max_rms):
    """Walk, solve, and if a camera isn't GOOD yet, walk again for just that camera, with what it needs said out loud.
    The stops are never thrown away: they're saved as you walk."""
    n = len(names)
    keys = rc.get("_keys") or names
    target = int(rc.get("target_per_camera", 25))
    targets = [target] * n
    done, hints = set(), []  # done: GOOD once, never asked for stops again
    history = {}             # camera -> its error after each solve, to see whether more stops help it
    last_out = [None]        # the last solve's answer: the next pass starts from it (never trusted alone)
    gave_up = set()          # cameras more stops didn't improve: asked no more, told what to do instead
    rounds = 0               # retry rounds walked so far
    max_rounds = int(rc.get("retry_rounds", 2))
    ok_px = float(rc.get("ok_px", 4.5))
    backed_up = [ci.PRACTICE]  # back up the previous files once, before the first save
    saved_at = [0.0]

    def save(solved=False, force=False):
        if not force and time.monotonic() - saved_at[0] < 2:
            return
        if not backed_up[0]:
            dest = backup_previous(data_dir, DATA / "backups", keys)
            if dest:
                log.info("Previous room calibration copied to %s", dest)
            backed_up[0] = True
            if not state.get("continuing"):  # a new walk: the old walk's pictures go with its stops
                shutil.rmtree(recording_refs_dir(rec_path), ignore_errors=True)
        ref_dir = recording_refs_dir(rec_path)
        for s_, img in list(refs.items()):  # each camera's picture for this walk, once (or anew if it moved)
            path = ref_dir / f"{keys[s_]}.png"
            if not path.is_file() or s_ in state.get("moved", set()):
                ref_dir.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(path), img)
                state.get("moved", set()).discard(s_)
        with lock:
            snapshot = list(obs)
        save_recording(rec_path, snapshot, keys, watch.serial, solved)  # the device in use now
        saved_at[0] = time.monotonic()

    watch = DeviceWatch(vr, kind, serial, log)
    while True:
        how = walk(rc, cfg, log, names, voice, win, ci, vr, watch, reused, data_dir, counts, targets, done, hints,
                   latest_px, skipped, opened, cam_errors, state, t_start, save)
        reused = False
        if obs:
            save(force=True)
        if how == "camera error":
            bad = and_list(names[e[0]] for e in cam_errors)
            message_screen(win, voice, "A camera didn't open", [(f"Didn't open: {bad}", YELLOW),
                           ("Close other programs using the cameras (the cat tracker, fbt, the setup screen), then run this "
                            "again. Your stops are kept.", WHITE)],
                           f"{spoken_list([names[e[0]] for e in cam_errors], True)} didn't open. Close other programs "
                           "using the cameras.", RED, size)
            return 1
        if how == "quit":
            log.info("Quit. %s stops per camera are saved; run this again to continue the walk", counts)
            return 1
        if ci.PRACTICE:  # 4 stops can't place a camera (it takes 6+); the point is the flow
            log.info("Practice done: %s stops (not solved)", counts)
            message_screen(win, voice, "Practice done, nothing is saved",
                           [(f"{names[i]}: {k} stops", GREEN if k >= target else YELLOW) for i, k in enumerate(counts)],
                           "Practice done. Nothing was saved.", GREEN, size)
            return 0
        voice.say("Solving. Please wait.", force=True)
        voice.flush()
        win.show(ci.overlay(np.zeros((size[1], size[0], 3), np.uint8), "Room calibration", "", "Solving ...", "", YELLOW))
        cv2.waitKey(1)
        with lock:
            snapshot = list(obs)
        log.info("\nSolving from %d observations", len(snapshot))
        out, needs = room_needs.try_solve(snapshot, intrinsics, names, size, max_rms, log, start=last_out[0])
        if out is not None:
            last_out[0] = out  # the next pass starts from this answer too
            for c in range(n):
                history.setdefault(c, []).append(float(out["cameras"][c]["rms_px"]))
        done.update(c for c in range(n) if not needs[c])  # GOOD once: done for good, even if it drifts a little
        want = [c for c in range(n) if c not in done]
        for c in want:  # a round of stops that didn't help this camera: more of them won't either
            h = history.get(c, [])
            if len(h) >= 2 and h[-2] - h[-1] < max(0.3, 0.1 * h[-2]):
                if c not in gave_up:
                    log.info("%s: %.2f -> %.2f px with more stops; not asking for more", names[c], h[-2], h[-1])
                gave_up.add(c)
        ask = [c for c in want if c not in gave_up]
        if out is not None and (how == "force" or not ask or rounds >= max_rounds):
            return finish(log, out, snapshot, intrinsics, names, size, rc, data_dir, refs, win, voice, max_rms, ok_px,
                          lambda: save(solved=True, force=True),
                          float(get(cfg, "calibration.intrinsics.max_rms_px", 0.8)))
        if out is None and (how == "force" or not ask or rounds >= max_rounds):
            lines = [(t, YELLOW) for c in range(n) for t in needs[c][:1]] + [("Your stops are kept: run this again "
                                                                               "to continue the walk.", WHITE)]
            message_screen(win, voice, "Couldn't place every camera yet", lines,
                           "Not every camera could be placed yet. Your stops are kept. Run this again to continue.",
                           RED, size)
            return 1
        # walk again, for just the cameras that aren't GOOD and that more stops can still help
        rounds += 1
        for c in range(n):
            targets[c] = counts[c] + EXTRA_STOPS if c in ask else min(targets[c], counts[c])
        hints[:] = [needs[c] for c in ask]
        good = sorted(done)
        first = " ".join(needs[ask[0]][:2])
        said = (f"{spoken_list([names[c] for c in good], True)} {'fits' if len(good) == 1 else 'fit'} well. "
                if good else "") + first
        log.info("Round %d of %d: walking again for %s (%s)", rounds, max_rounds, [names[c] for c in ask],
                 {names[c]: needs[c] for c in ask})
        voice.say(said, force=True)


def finish(log, out, obs, lenses, names, size, rc, data_dir, refs, win, voice, max_rms, ok_px, mark_solved,
           lens_max_rms=0.8):
    """Save the room calibration and say how each camera came out: GOOD, OK (a little less precise, fine to use) or
    NOT GOOD, with what to do about it when more stops can't help (usually that camera's lens calibration)."""
    v = room_needs.verdicts(out, obs, lenses, names, size, max_rms, ok_px, frames=refs, lens_max_rms=lens_max_rms)
    for name, (label, rms, advice) in zip(names, v):
        log.info("  %-6s %s, %.2f px%s", name, FIT[label], rms, f": {advice}" if advice else "")
    usable = all(label != "NOT GOOD" for label, _, _ in v)
    save_room(log, out, names, rc, data_dir, refs, rc.get("_keys"))
    if usable:
        mark_solved()  # the walk is finished: not offered for continuing next time
    lines = result_lines(out, rc, ok_px)
    lines += [(advice, YELLOW) for label, _, advice in v if advice]
    ok_names = [n for n, (label, _, _) in zip(names, v) if label == "OK"]
    bad_names = [n for n, (label, _, _) in zip(names, v) if label == "NOT GOOD"]
    if not ok_names and not bad_names:
        said = "The room calibration fits well. Next, run the calibration check."
    elif not bad_names:
        said = (f"Room calibration is done. {spoken_list(ok_names, True)} {'fits' if len(ok_names) == 1 else 'fit'} OK, a "
                "little less precisely. " + next(a for l, _, a in v if a) + " Or carry on: it works as it is.")
    else:
        said = (f"{spoken_list(bad_names, True)} {"doesn't" if len(bad_names) == 1 else "don't"} fit well enough yet. " +
                next(a for l, _, a in v if l == "NOT GOOD"))
    title = ("Room calibration: FIT GOOD" if not ok_names and not bad_names else
             "Room calibration done: FIT OK" if not bad_names else "Room calibration: FIT NOT GOOD")
    message_screen(win, voice, title, lines, said, GREEN if usable else RED, size)
    return 0 if usable else 1


EXTRA_STOPS = 10  # more stops asked of a camera that isn't GOOD yet, each round


def walk(rc, cfg, log, names, voice, win, ci, vr, watch, reused, data_dir, counts, targets, done, hints, latest_px,
         skipped, opened, cam_errors, state, t_start, save):
    """One round of walking. Returns "solve" (enough stops, c, or stuck), "force" (q then y), "quit" or
    "camera error"."""
    n = len(names)
    target = int(rc.get("target_per_camera", 25))
    min_solve = min(MIN_SOLVE, target)
    stuck_min = min(int(rc.get("stuck_min_per_camera", 12)), target)
    stuck_s = float(rc.get("stuck_after_s", 60))
    still = float(rc.get("still_speed_m_s", 0.05))
    tile_h = int(get(cfg, "preview.tile_height", 640))
    first_round = not hints
    if first_round:
        if ci.PRACTICE:
            voice.say("Practice run. Nothing is saved.", force=True)
        voice.say("Walk slowly around the room with Board B facing the cameras. Stop for a second at each "
                  "spot.", force=True)
    state["walking"] = True
    prev_total, stops, last_capture, full = sum(counts), 0, 0.0, {s for s in range(n) if counts[s] >= targets[s]}
    last_gain = last_log = time.monotonic()
    hint_i, last_hint = 0, time.monotonic()
    finishing_at = None  # stuck: solve at this time unless a stop comes in
    asking = False       # q: "solve with what you have? y / n"
    first_frame_logged = False
    try:
        while True:
            now = time.monotonic()
            from capture.camera import say_camera_events
            for text in say_camera_events(list(opened.values()), None, now):  # unplugged / back: said below
                state.setdefault("notices", []).append(text)
            while state.get("notices"):  # e.g. a camera that moved since the last walk
                notice = state["notices"].pop(0)
                voice.say(notice, now, force=True)
                state["shown"] = (notice, now + 8)
            voice.tick(now)
            if cam_errors and not state["opening"]:
                return "camera error"
            if not first_frame_logged and len(opened) == n:
                first_frame_logged = True
                log.info("All cameras ready %.1f s after start", now - t_start)
            need = [s for s in range(n) if s not in done and counts[s] < targets[s] and s in opened]
            weakest = min(need, key=lambda s: counts[s] - targets[s]) if need else None
            tiles = tiles_for(opened, names, latest_px, counts, targets, done, weakest, tile_h, cfg)
            s, device_problem = watch.check(now, voice)
            total = sum(counts)
            if total > prev_total:  # a stop was kept (it counts for every camera that saw it): chime, no words
                voice.click()
                if now - last_capture > 1.0:
                    stops += 1
                    if stops % 3 == 0:
                        voice.say("Now tilt Board B a little.", now)
                last_capture, prev_total, last_gain, finishing_at = now, total, now, None
                save()
            for c in range(n):
                if c not in done and counts[c] >= targets[c] and c not in full:
                    full.add(c)
                    voice.say(f"{spoken(names[c], True)} is full.", now, force=True)
            shown = state.get("shown")
            if asking:
                instruction, color = "Solve with the stops you have?  y / n", YELLOW
            elif shown and now < shown[1]:
                instruction, color = shown[0], YELLOW
            elif finishing_at is not None:
                instruction, color = f"No new stops for a while: finishing in {max(0, int(finishing_at - now)) + 1} s", YELLOW
            elif device_problem is not None:
                instruction, color = device_problem
            elif s[2] > still:
                instruction, color = "Stop, and hold Board B still", YELLOW
            elif weakest is not None:
                hint = hints[hint_i % len(hints)] if hints else None
                instruction, color = (hint[0] if hint else f"Hold still...   most needed: {names[weakest]}"), GREEN
                if now - last_capture > 6 and now - last_hint > 7:  # nothing kept for a while: say what helps
                    voice.say(" ".join(hint[:2]) if hint else f"Try a spot {spoken(names[weakest])} can see.", now)
                    hint_i, last_hint = hint_i + 1, now
            elif len(opened) < n:
                instruction, color = "Starting the other cameras...", WHITE
            else:
                instruction, color = "All cameras full", GREEN
            active = [c for c in range(n) if c not in done]
            if finishing_at is None and not asking and active and should_finish_stuck(
                    [counts[c] for c in active], max(targets[c] for c in active), last_gain, now, stuck_min, stuck_s):
                finishing_at = now + 10
                voice.say("No new stops for a minute. I'll finish in ten seconds. Keep walking to add more.", now,
                          force=True)
            keys = "y yes   n no" if asking else "c solve now   f fullscreen   q quit" + (
                "   w a different device" if reused and stops == 0 else "")
            win.show(ci.overlay(tile_grid(tiles), "Room calibration", f"{sum(counts)} stops kept" if hints else
                                f"{stops} stops", instruction, "", color, keys))
            key = cv2.waitKey(30) & 0xFF
            if key == ord("f"):
                win.toggle_full()
            if time.monotonic() - last_log > 5:
                log.info("kept so far: %s  (skipped: %s)", " ".join(f"{names[i]} {k}" for i, k in enumerate(counts)),
                         ", ".join(f"{k} {v}" for k, v in skipped.items()))
                last_log = time.monotonic()
            if asking:
                if key == ord("y"):
                    return "force"
                if key in (ord("n"), 27, ord("q")):
                    return "quit"
                continue
            if key == ord("w") and reused and stops == 0:  # last time's device, but another one is on the card
                state["walking"] = False
                got = wave_and_use(vr, win, voice, (int(cfg["cameras"]["width"]), int(cfg["cameras"]["height"])),
                                   log, data_dir / "room_device.json")
                if got is None:
                    return "quit"
                watch.kind, watch.serial = got[0], got[1]
                reused = False
                state["walking"] = True
                continue
            if key in (ord("q"), 27):
                if min(counts) >= min_solve:
                    asking = True
                    voice.say("Solve with the stops you have? Press Y for yes, N for no.", now, force=True)
                    continue
                return "quit"
            ready = len(opened) == n and not state["opening"] and not state.get("checking")
            if ready and ((key == ord("c") and min(counts) >= min_solve) or
                          all(counts[c] >= targets[c] for c in range(n) if c not in done) or
                          (finishing_at is not None and now >= finishing_at)):
                return "solve"
            if key == ord("c"):
                voice.say(f"Every camera needs at least {min_solve} stops first.", now, force=True)
    finally:
        state["walking"] = False


def show_result(win, voice, out, rc, ok, size, practice):
    lines = result_lines(out, rc)
    said = ("The room calibration fits well. Next, run the calibration check." if ok else
            "The room calibration doesn't fit well yet. Walk it again, with more varied and tilted stops.")
    if practice:
        said = "Practice done. " + said
    message_screen(win, voice, "Room calibration: FIT GOOD" if ok else "Room calibration: FIT NOT GOOD", lines, said,
                   GREEN if ok else RED, size)


if __name__ == "__main__":
    from core.runlog import exit_now
    exit_now(main())  # for certain: the cameras are free for the next tool at once
