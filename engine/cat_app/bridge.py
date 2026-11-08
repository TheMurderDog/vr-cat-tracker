"""Runs the cat tracker (cat_tracker.run, unchanged) for the Cat Tracker app, and lets the app see and control it.

The tracker's code isn't edited. This starts its usual `main()` in this process and listens in on it:

- what it already knows each update (where the cat is, how far it is from you, camera problems, the anchor,
  capturing) goes into a small status report the app reads from shared memory (cat_app.link: no network,
  no listening ports);
- the window it would normally open is caught instead, and the app shows those pictures;
- the app's buttons press the tracker's own keys (a re-anchor, c capture, s snapshot, q quit);
- the cat's overlays use the colour, shade, size and opacity chosen in the app, and change live;
- the app's alert changes (distances, buzz strength and style, snooze) are applied in memory only:
  settings/cat_tracker.yaml is not written.

Started by the app's Start button, or by SteamVR (cat_tracker.install_autostart, when the app is installed).
By hand, from engine:  ..\\.venv\\Scripts\\python.exe -m cat_app.bridge -- --osc
Everything after -- goes to the tracker as its usual options (--new-anchor, --osc, --capture, --no-vr, --headless).
"""

import argparse
import json
import os
import queue
import sys
import threading
import time
import traceback
from pathlib import Path

from core.config import resolve_path

from cat_app import app_settings, link, marker_style, perf
from cat_app.extras import AutoCapture, Heatmap, Wobble, rising_level, rising_pulses, snooze_icon

APP_DATA = resolve_path("my_data/app")  # the app's own files (settings, heatmap, recoloured icons)

LOCK = threading.Lock()
KEYS = queue.Queue()
STATE = {
    "bridge": True,
    "running": False,       # the tracker's main loop has started
    "finished": False,
    "error": None,
    "started": time.time(),
    "vr": False,
    "anchoring": False,
    "anchor": {"have": False, "off": False},
    "cat": {"state": "hidden", "pos": None, "kind": "normal", "speed": 0.0, "dist": None, "level": None, "alpha": 0.0},
    "head": None,
    "room": None,
    "cameras": {"names": [], "stale": []},
    "problem": None,
    "capture": {"on": False, "n": 0},
    "markers": {"edge": False, "warn": False, "health": False},
    "style_version": 0,
    "alert": None,          # the warning distances and buzz strength in use (cat_tracker.yaml + the app's changes)
    "buzz": {"muted": 0, "last_amp": None, "step": None},
    "auto_capture": {"active": False, "count": 0},
}
FRAME = {"img": None, "seq": 0, "real": False, "wanted_until": 0.0}
METER = perf.Meter()
REFS = {"vr": None, "raw_to_cam": None, "saver": None, "check": None, "cfg": None, "prox": [], "al": None,
        "alert_config": None, "buzz_pattern": None}
EPISODE = {"on": False, "step": None, "off_since": None, "last_buzz": 0.0, "last_seen": None}
STYLE = {"style": marker_style.clamp_style({}), "version": 0, "applied": -1, "mtime": None}
SETTINGS = {"s": app_settings.clamp({}), "version": 0, "applied": -1, "mtime": None}
WOBBLE = Wobble()
HEAT = Heatmap(APP_DATA / "heatmap.json")
AUTO = AutoCapture(lambda k: KEYS.put(ord(k)))
STYLED = ("icon", "ring", "edge")  # the overlays the app restyles


def _set(path, value):
    with LOCK:
        d = STATE
        for k in path[:-1]:
            d = d[k]
        d[path[-1]] = value


def _list(x):
    try:
        return [float(v) for v in x]
    except TypeError:
        return None


# ---- marker style ---------------------------------------------------------------------------------

def style_file():
    return APP_DATA / "marker_style.json"


def settings_file():
    return APP_DATA / "app_settings.json"


def watch_style():
    """Picks up the app's changes to the marker look and to its settings (alerts, snooze, ...)."""
    while True:
        try:
            m = style_file().stat().st_mtime if style_file().exists() else None
            if m != STYLE["mtime"]:
                STYLE["mtime"] = m
                STYLE["style"] = marker_style.load(style_file())
                STYLE["version"] += 1
                _set(("style_version",), STYLE["version"])
            m = settings_file().stat().st_mtime if settings_file().exists() else None
            if m != SETTINGS["mtime"]:
                SETTINGS["mtime"] = m
                SETTINGS["s"] = app_settings.load(settings_file())
                SETTINGS["version"] += 1
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)


def styled_path(original):
    """The overlay picture to show for `original`: itself, or a recoloured copy in my_data\\app\\styled."""
    import cv2
    import numpy as np
    g = marker_style.group_for(original)
    if g is None:
        return str(original)
    gs = STYLE["style"][g]
    if not gs.get("colour") and abs(gs.get("shade", 0.0)) < 1e-3:
        return str(original)
    out = APP_DATA / "styled" / f"{Path(str(original)).stem}_{marker_style.key(gs)}.png"
    if not out.exists():
        bgra = cv2.imread(str(original), cv2.IMREAD_UNCHANGED)
        if bgra is None:
            return str(original)
        if bgra.ndim == 2 or bgra.shape[2] == 3:
            bgra = cv2.cvtColor(bgra, cv2.COLOR_BGR2BGRA if bgra.ndim == 3 else cv2.COLOR_GRAY2BGRA)
        rgba = bgra[..., [2, 1, 0, 3]]
        res = marker_style.restyle(np.ascontiguousarray(rgba), gs)
        out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out), res[..., [2, 1, 0, 3]])
    return str(out)


def group_of_overlay(o):
    return marker_style.group_for(o.get("src", o.get("image", "")))


# ---- hooks into the tracker ----------------------------------------------------------------------------

# ---- the app's settings: warning distances, buzz, snooze -----------------------------------------

def apply_settings(vr=None):
    """Puts the app's alert changes into the tracker's alert settings (in memory only; cat_tracker.yaml is
    not written) and into its Proximity checks. Runs on the tracker's own thread."""
    SETTINGS["applied"] = SETTINGS["version"]
    al = REFS["al"]
    if al is None:
        return
    if REFS["alert_config"] is None:
        REFS["alert_config"] = dict(al)  # cat_tracker.yaml's values, to go back to
    base = REFS["alert_config"]
    al.clear()
    al.update(base)
    al.update(SETTINGS["s"]["alert"])
    for p in REFS["prox"]:
        p.radius = float(al.get("radius_m", p.radius))
        p.underfoot = float(al.get("underfoot_m", p.underfoot))
    keys = ("underfoot_m", "radius_m", "max_warn_m", "buzz_amplitude", "buzz")
    _set(("alert",), {"now": {k: al.get(k) for k in keys}, "config": {k: base.get(k) for k in keys}})


def play_rising(vr, level, strength):
    """One step of the "light to heavy" buzz on both controllers, in the background."""
    pulses = rising_pulses(level, strength)

    def play():
        for amp, secs, gap in pulses:
            vr.buzz(secs, amp)
            time.sleep(secs + gap)
    threading.Thread(target=play, name="buzz", daemon=True).start()
    with LOCK:
        STATE["buzz"]["last_amp"] = round(pulses[0][0], 2)
        STATE["buzz"]["step"] = level


def rising_step(al):
    return rising_level(STATE["cat"]["dist"], float(al.get("underfoot_m", 1.0)), float(al.get("radius_m", 1.8)))


def escalate(lvl, now):
    """With the "light to heavy" buzz: once the warning has buzzed, a stronger step each time it comes
    into a closer band (light -> medium -> heavy), each at most once until the warning goes off again."""
    ep = EPISODE
    if lvl:
        ep["off_since"] = None
        ep["on"] = True
        st, vr, al = SETTINGS["s"], REFS["vr"], REFS["al"] or {}
        if ep["step"] is None or st["buzz_style"] != "rising" or vr is None or not al.get("buzz", True):
            return
        step = rising_step(al)
        if step > ep["step"] and now - ep["last_buzz"] > 0.8:
            ep["step"], ep["last_buzz"] = step, now
            if not app_settings.snoozed(st):
                play_rising(vr, step, float(al.get("buzz_amplitude", 0.6)))
    elif ep["on"]:
        ep["off_since"] = ep["off_since"] or now
        if now - ep["off_since"] >= float((REFS["al"] or {}).get("buzz_rearm_s", 1.0)):
            ep["on"], ep["step"] = False, None


SNOOZE_POSE = None


def show_snooze(vr):
    """A small, dim "buzz muted" sign low in the corner of your view while the buzz is snoozed."""
    global SNOOZE_POSE
    on = app_settings.snoozed(SETTINGS["s"])
    if "snooze" not in vr.overlays:
        if not on or REFS.get("snooze_failed"):
            return
        try:
            vr.add_overlay("snooze", snooze_icon(APP_DATA / "snooze.png"), 0.035)
        except Exception as e:  # noqa: BLE001
            print(f"Couldn't add the snooze sign: {e}", flush=True)
            REFS["snooze_failed"] = True
            return
    o = vr.overlays["snooze"]
    if o["shown"] == on:
        return
    if on:
        import numpy as np
        if SNOOZE_POSE is None:  # about 17 degrees left of and below the middle of your view, 1 m away
            T = np.eye(4)
            T[:3, 3] = [-0.30, -0.32, -1.0]
            SNOOZE_POSE = T
        vr.place_on_head("snooze", SNOOZE_POSE, 0.45)
    else:
        vr.place_on_head("snooze", None, 0)


def install_hooks():
    import cv2
    import numpy as np

    # the tracker's camera window: keep the picture for the app instead of opening a window
    def imshow(_win, img):
        with LOCK:
            FRAME["img"] = img
            FRAME["real"] = img is not None and img.shape[0] > 8
            FRAME["seq"] += 1

    def wait_key(_ms=0):
        try:
            return KEYS.get_nowait()
        except queue.Empty:
            return -1

    cv2.imshow = imshow
    cv2.waitKey = wait_key
    cv2.destroyAllWindows = lambda: None
    cv2.namedWindow = lambda *a, **k: None  # no real window: the app is its window
    cv2.setMouseCallback = lambda *a, **k: None
    cv2.getWindowProperty = lambda *a, **k: 1.0
    from tools import window
    window.quit_when_closed = lambda *a, **k: {"shown": False, "closed": False}  # (there's no window to close)

    from cat_tracker import alert, anchor, collect, health, locate, settings, vrlink

    load = settings.load

    def settings_load(*a, **k):
        cfg = load(*a, **k)
        REFS["cfg"] = cfg
        return cfg
    settings.load = settings_load

    # -- SteamVR side --
    V = vrlink.VRLink
    v_init, v_add, v_set, v_place, v_head_place, v_headset, v_quit, v_buzz = (
        V.__init__, V.add_overlay, V.set_image, V.place, V.place_on_head, V.headset, V.quit_requested, V.buzz_pattern)
    REFS["buzz_pattern"] = v_buzz

    def init(self, *a, **k):
        v_init(self, *a, **k)
        REFS["vr"] = self
        _set(("vr",), True)

    def width_for(self, name, o):
        g = group_of_overlay(o)
        return o["base_width"] * (STYLE["style"][g]["size"] if g else 1.0)

    def add_overlay(self, name, image_path, width_m):
        h = v_add(self, name, styled_path(image_path) if name in STYLED else image_path, width_m)
        o = self.overlays[name]
        o["src"], o["base_width"] = str(image_path), float(width_m)
        if name in STYLED:
            self.ov.setOverlayWidthInMeters(h, float(width_for(self, name, o)))
        return h

    def set_image(self, name, image_path):
        o = self.overlays[name]
        if name not in STYLED:
            return v_set(self, name, image_path)
        if o.get("src") != str(image_path):
            o["src"] = str(image_path)
            v_set(self, name, styled_path(image_path))
            self.ov.setOverlayWidthInMeters(o["h"], float(width_for(self, name, o)))
        if name == "icon":
            stem = Path(str(image_path)).stem
            _set(("cat", "kind"), {"cat_close": "close", "cat_rest": "rest", "cat_move": "move"}.get(stem, "normal"))

    def restyle_now(self):
        """New colours or sizes from the app: redraw the cat's overlays (on the tracker's own thread)."""
        STYLE["applied"] = STYLE["version"]
        for name in STYLED:
            o = self.overlays.get(name)
            if o is None:
                continue
            p = styled_path(o["src"])
            self.ov.setOverlayFromFile(o["h"], p)
            o["image"] = p
            self.ov.setOverlayWidthInMeters(o["h"], float(width_for(self, name, o)))

    def place(self, name, T, alpha):
        if STYLE["applied"] != STYLE["version"]:
            restyle_now(self)
        if name in ("icon", "ring"):
            o = self.overlays[name]
            g = group_of_overlay(o)
            if name == "icon":
                _set(("cat", "alpha"), float(alpha))
            if g and alpha > 0:
                alpha = alpha * STYLE["style"][g]["opacity"]
                if alpha <= 0:  # the ring at 0% opacity: hidden
                    return v_place(self, name, None, 0)
        return v_place(self, name, T, alpha)

    def place_on_head(self, name, T, alpha):
        if name in ("edge", "warn", "health"):
            with LOCK:
                STATE["markers"][name] = bool(alpha > 0)
        if name == "edge" and alpha > 0:
            if STYLE["applied"] != STYLE["version"]:
                restyle_now(self)
            alpha = alpha * STYLE["style"]["arrow"]["opacity"]
        return v_head_place(self, name, T, alpha)

    def quit_requested(self):
        """Called once per update by the tracker: a handy moment to apply the app's settings."""
        if SETTINGS["applied"] != SETTINGS["version"]:
            apply_settings(self)
        show_snooze(self)
        return v_quit(self)

    def buzz_pattern(self, hands="LRLR", total_s=1.0, pulse_s=0.15, amplitude=0.6):
        """The tracker's warning buzz (once each time the warning comes on): skipped while snoozed;
        with the "light to heavy" style, replaced by one step on both controllers for how close it is
        (stronger steps follow if it comes closer, see escalate)."""
        st = SETTINGS["s"]
        now = time.monotonic()
        al = REFS["al"] or {}
        EPISODE["step"] = rising_step(al) if st["buzz_style"] == "rising" else 3
        EPISODE["last_buzz"] = now
        if app_settings.snoozed(st):
            with LOCK:
                STATE["buzz"]["muted"] += 1
            return None
        if st["buzz_style"] == "rising":
            return play_rising(self, EPISODE["step"], float(amplitude))
        with LOCK:
            STATE["buzz"]["last_amp"] = round(float(amplitude), 2)
            STATE["buzz"]["step"] = None
        return v_buzz(self, hands, total_s, pulse_s, amplitude)

    def headset(self, *a, **k):
        H = v_headset(self, *a, **k)
        R = REFS["raw_to_cam"]
        if H is not None and R is not None and not a and not k:  # raw space: put it in camera space
            C = R @ H
            fwd = -C[:3, 2]
            _set(("head",), {"pos": [float(C[0, 3]), float(C[1, 3]), float(C[2, 3])], "fwd": [float(fwd[0]), float(fwd[2])]})
        return H

    V.__init__, V.add_overlay, V.set_image, V.place, V.place_on_head, V.headset, V.quit_requested, V.buzz_pattern = (
        init, add_overlay, set_image, place, place_on_head, headset, quit_requested, buzz_pattern)

    # -- the cat --
    ct_update = locate.CatTrack.update

    def track_update(self, X, now):
        pos, state, alpha = ct_update(self, X, now)
        wob = WOBBLE.update(X if state == "seen" else None, now)
        if state == "hidden":
            WOBBLE.reset()
        if state == "seen" and pos is not None:
            with LOCK:
                HEAT.add(pos, now - EPISODE["last_seen"] if EPISODE["last_seen"] else 0.0, WOBBLE.last)
            EPISODE["last_seen"] = now
        else:
            EPISODE["last_seen"] = None
        saver = REFS["saver"]
        r = AUTO.step(SETTINGS["s"], wob, state == "seen", bool(saver is not None and saver.on), now)
        if r:
            print(f"{time.strftime('%H:%M:%S')} auto capture {r} (wobble {wob:.1f} cm)", flush=True)
        HEAT.save()
        with LOCK:
            STATE["cat"]["wobble_cm"] = round(wob, 1) if state == "seen" else None
            STATE["auto_capture"] = {"active": AUTO.active, "count": AUTO.count}
            STATE["running"] = True
            STATE["cat"]["state"] = state
            STATE["cat"]["pos"] = _list(pos) if pos is not None else None
            STATE["cat"]["pos_raw"] = to_raw(pos)  # for the wrist widget's arrow
            if state == "hidden":
                STATE["cat"]["dist"] = None
                STATE["cat"]["level"] = None
        return pos, state, alpha
    locate.CatTrack.update = track_update

    inv_cache = [None, None]  # raw_to_cam it was worked out from, its inverse

    def to_raw(pos):
        """Camera space -> SteamVR's raw space (None without an anchor)."""
        R = REFS["raw_to_cam"]
        if pos is None or R is None:
            return None
        if inv_cache[0] is not R:
            inv_cache[:] = [R, np.linalg.inv(R)]
        Ri = inv_cache[1]
        p = np.asarray(pos, float)[:3]
        return _list(Ri[:3, :3] @ p + Ri[:3, 3])

    m_update, m_kind = alert.Motion.update, alert.Motion.kind

    def motion_update(self, pos, now):
        r = m_update(self, pos, now)
        _set(("cat", "speed"), float(self.speed))
        return r

    def motion_kind(self, now, oc):
        k = m_kind(self, now, oc)
        if REFS["vr"] is None:  # no overlays to read it from
            _set(("cat", "kind"), k)
        return k
    alert.Motion.update, alert.Motion.kind = motion_update, motion_kind

    p_init, p_update, p_reset = alert.Proximity.__init__, alert.Proximity.update, alert.Proximity.reset

    def prox_init(self, al, *a, **k):
        p_init(self, al, *a, **k)
        REFS["prox"].append(self)
        REFS["al"] = al
        SETTINGS["applied"] = -1  # apply the app's distances to it

    def prox_update(self, dist, speed, now):
        lvl = p_update(self, dist, speed, now)
        with LOCK:
            STATE["cat"]["dist"] = float(dist)
            STATE["cat"]["level"] = lvl
        escalate(lvl, now)
        return lvl

    def prox_reset(self):
        _set(("cat", "level"), None)
        return p_reset(self)
    alert.Proximity.__init__, alert.Proximity.update, alert.Proximity.reset = prox_init, prox_update, prox_reset

    # -- health, capture, anchor --
    h_msg, h_cams = health.Health.message, health.Health.cameras

    def message(self, now):
        m = h_msg(self, now)
        _set(("problem",), [m[0], m[1], list(m[2])] if m else None)
        return m

    def cameras(self, items, now):
        s = h_cams(self, items, now)
        with LOCK:
            STATE["cameras"] = {"names": list(self.names), "stale": [int(i) for i in s]}
        return s
    health.Health.message, health.Health.cameras = message, cameras

    fs_init = collect.FrameSaver.__init__

    def saver_init(self, *a, **k):
        fs_init(self, *a, **k)
        REFS["saver"] = self
    collect.FrameSaver.__init__ = saver_init

    a_run, a_load, ac_init = anchor.run, anchor.load, anchor.AnchorCheck.__init__

    def anchor_run(*a, **k):
        _set(("anchoring",), True)
        try:
            out = a_run(*a, **k)  # (T, why)
        finally:
            _set(("anchoring",), False)
        T, why = out if isinstance(out, tuple) else (out, "")
        if T is not None:
            REFS["raw_to_cam"] = np.asarray(T, float)
            _set(("anchor", "have"), True)
        # a walk that didn't work leaves the previous anchor in use (if there was one)
        stopped = bool(why) and str(why).startswith("stopped")
        _set(("anchor", "last_failed"), T is None and not stopped)
        _set(("anchor", "why"), "" if T is not None or stopped else str(why))
        return out

    def anchor_load(*a, **k):
        T = a_load(*a, **k)
        if T is not None:
            REFS["raw_to_cam"] = np.asarray(T, float)
            _set(("anchor", "have"), True)
        return T

    def check_init(self, *a, **k):
        ac_init(self, *a, **k)
        REFS["check"] = self
    anchor.run, anchor.load, anchor.AnchorCheck.__init__ = anchor_run, anchor_load, check_init

    # a quiet anchor correction: the tracker uses the corrected one from then on, and so does the app
    ac_step = anchor.AnchorCheck.step

    def check_step(self, *a, **k):
        T = ac_step(self, *a, **k)
        if T is not None:
            REFS["raw_to_cam"] = np.asarray(T, float)
        return T
    anchor.AnchorCheck.step = check_step


    # the room: camera positions and the floor area, for the app's map (run.py imported room_bounds by name)
    from cat_tracker import run as run_mod
    # the camera picture grid (4 resized frames with boxes drawn) is only worth making while the app's
    # Cameras page is open (or for a snapshot); the rest of the time a tiny stand-in is enough
    tiles = run_mod.tiles

    def tiles_when_watched(*a, **k):
        if time.monotonic() > FRAME["wanted_until"]:
            METER.count("camera grids skipped")
            return np.zeros((2, 2, 3), np.uint8)
        t0 = time.perf_counter()
        g = tiles(*a, **k)
        METER.count("camera grids drawn")
        METER.timed("camera grid", time.perf_counter() - t0)
        return g
    run_mod.tiles = tiles_when_watched

    rb = run_mod.room_bounds

    def room_bounds(rig, margin):
        b = rb(rig, margin)
        with LOCK:
            HEAT.set_bounds(b)
        try:
            centres = [(-P[:, :3].T @ P[:, 3]) for P in rig.P]
            room = {"bounds": [float(v) for v in b], "cameras": [[float(c[0]), float(c[2])] for c in centres]}
        except Exception:  # noqa: BLE001
            room = {"bounds": [float(v) for v in b], "cameras": []}
        _set(("room",), room)
        return b
    run_mod.room_bounds = room_bounds
    return run_mod


def refresh_live():
    """Values read straight off the tracker's objects (capture count, anchor check)."""
    with LOCK:
        s = REFS["saver"]
        STATE["capture"] = {"on": bool(s is not None and s.on), "n": int(s.n) if s is not None else 0}
        c = REFS["check"]
        # "re-anchor truly needed": the anchor work's own flag when it has one, else the older check
        need = getattr(c, "needs_reanchor", None) if c is not None else None
        STATE["anchor"]["off"] = bool(need if need is not None else (c is not None and c.off))
        STATE["anchor"]["reason"] = str(getattr(c, "reason", "") or "") if c is not None else ""


def test_buzz():
    vr = REFS["vr"]
    if vr is None:
        return False
    al = REFS["al"] or ((REFS["cfg"] or {}).get("cat", {}) or {}).get("alert", {}) or {}
    strength = float(al.get("buzz_amplitude", 0.6))
    if vr.input is None:  # haptics are set up only when alert.buzz is on
        vr.buzz(0.2, strength)
        return True
    # what the warning feels like, even while snoozed (you asked for it)
    if SETTINGS["s"]["buzz_style"] == "rising":  # all three steps, light to heavy
        def play():
            for step in (1, 2, 3):
                for amp, secs, gap in rising_pulses(step, strength):
                    vr.buzz(secs, amp)
                    time.sleep(secs + gap)
                time.sleep(0.7)
        threading.Thread(target=play, name="buzz", daemon=True).start()
        return True
    REFS["buzz_pattern"](vr, str(al.get("buzz_pattern", "LRLR")), float(al.get("buzz_total_s", 1.0)),
                         float(al.get("buzz_s", 0.15)), strength)
    return True


# ---- the app's window into it: shared memory (cat_app.link) ------------------------------------------

KEYS_FOR = {"anchor": "a", "capture": "c", "stop": "q"}


def handle(cmd):
    """A button pressed in the app."""
    if cmd == "snapshot":  # needs the real picture grid: ask for it, then press s a moment later
        FRAME["wanted_until"] = max(FRAME["wanted_until"], time.monotonic() + 3.0)
        threading.Timer(0.8, lambda: KEYS.put(ord("s"))).start()
    elif cmd in KEYS_FOR:
        KEYS.put(ord(KEYS_FOR[cmd]))
    elif cmd == "clear_heatmap":
        with LOCK:
            HEAT.clear()
    elif cmd == "buzz":
        test_buzz()


class Serve:
    """Writes the status (5 a second while the app is looking, else once a second), and the camera picture
    and the heatmap only while the app asks for them; reads the app's requests and buttons."""

    def __init__(self, blocks):
        self.b = blocks
        self.ask = {}
        self.done = set()
        self.first = True
        self.frame_seq = -1
        self.heat_at = 0.0

    def read_ask(self):
        _, data = self.b[link.ASK].read()
        if data is None:
            return
        try:
            self.ask = json.loads(data or b"{}")
        except ValueError:
            return
        for cid, cmd in self.ask.get("cmds", []):
            if cid in self.done:
                continue
            self.done.add(cid)
            if not self.first:  # (buttons left in the block by an earlier run don't count)
                try:
                    handle(str(cmd))
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
        self.first = False
        if len(self.done) > 200:
            self.done = {c for c, _ in self.ask.get("cmds", [])}

    def wants(self, key):
        return time.time() < float(self.ask.get(key, 0) or 0)

    def status(self):
        METER.count("status updates")
        refresh_live()
        with LOCK:
            link.write_json(self.b[link.STATUS], {**STATE, "frame_seq": FRAME["seq"], "pid": os.getpid(),
                                                   "t": time.time()})

    def frame(self):
        import cv2
        FRAME["wanted_until"] = time.monotonic() + 3.0
        with LOCK:
            img = FRAME["img"] if FRAME["real"] else None
            seq = FRAME["seq"]
        if img is None or seq == self.frame_seq:
            return
        self.frame_seq = seq
        s = min(1.0, 1280 / img.shape[1])
        if s < 1:
            img = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
        ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if ok:
            self.b[link.FRAME].write(jpg.tobytes())
            METER.count("camera pictures sent")

    def heat(self):
        if time.monotonic() - self.heat_at < 5.0:
            return
        self.heat_at = time.monotonic()
        with LOCK:
            rep = HEAT.report()
        link.write_json(self.b[link.HEAT], rep)

    def loop(self):
        last_status = 0.0
        while True:
            try:
                self.read_ask()
                now = time.monotonic()
                watched = self.wants("status_until")
                if now - last_status >= (0.2 if watched else 1.0):
                    last_status = now
                    self.status()
                if self.wants("frames_until"):
                    self.frame()
                if self.wants("heat_until"):
                    self.heat()
            except Exception:  # noqa: BLE001
                traceback.print_exc()
            time.sleep(0.1)


def main():
    argv = sys.argv[1:]
    passthrough = []
    if "--" in argv:
        i = argv.index("--")
        argv, passthrough = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description="Runs the cat tracker for the Cat Tracker app")
    ap.add_argument("--log", default=str(resolve_path("my_data/logs/cat_app/bridge.log")),
                    help="where this script's own messages go (the tracker's log is in my_data/logs/cat_tracker)")
    args = ap.parse_args(argv)
    Path(args.log).parent.mkdir(parents=True, exist_ok=True)
    f = open(args.log, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stderr = f
    print(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} tracker for the app, options: {' '.join(passthrough)}")

    if "--headless" in passthrough:
        # the app is its window, so the tracker draws its pictures for the app; but with no saved anchor it
        # stays headless and stops, as it would without the app (there's nobody to do the walk)
        from cat_tracker import settings
        from core.config import get
        try:
            have = resolve_path(get(settings.load(), "cat.anchor.file", "my_data/tracker/anchor.json")).is_file()
        except Exception:  # noqa: BLE001
            have = True
        if have:
            passthrough.remove("--headless")

    try:
        blocks = link.make_all()
    except FileExistsError:
        print("Another tracker for the app is already running; not starting a second one")
        return 2
    APP_DATA.mkdir(parents=True, exist_ok=True)
    serve = Serve(blocks)
    threading.Thread(target=watch_style, name="style", daemon=True).start()

    def perf_reports():
        while True:
            time.sleep(30)
            print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} perf (whole tracker process, detection included) | "
                  + METER.report(), flush=True)
    threading.Thread(target=perf_reports, name="perf", daemon=True).start()
    threading.Thread(target=serve.loop, name="app link", daemon=True).start()

    code = 1
    try:
        run_mod = install_hooks()
        sys.argv = ["cat_tracker.run"] + passthrough
        code = run_mod.main() or 0
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    except BaseException:  # noqa: BLE001
        _set(("error",), traceback.format_exc()[-2000:])
        traceback.print_exc()
    finally:
        _set(("running",), False)
        _set(("finished",), True)
        with LOCK:
            HEAT.save(force=True)
        if code and STATE["error"] is None:
            _set(("error",), f"The tracker stopped (code {code}). Its log in my_data\\logs\\cat_tracker says why.")
        serve.status()
        time.sleep(2.0)  # let the app read the final status
        for b in blocks.values():
            b.close()
    return code


if __name__ == "__main__":
    from core.runlog import exit_now
    exit_now(main())  # for certain: the cameras are free for the next tool at once
