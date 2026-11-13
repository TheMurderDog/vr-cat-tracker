"""The app's side of things: reads the tracker's status (cat_app.link), starts and stops the tracker, and
keeps the app's settings and the marker look. One Backend object is shared by the desktop window and the
SteamVR dashboard tab, so both always show the same thing."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtQuick import QQuickImageProvider

from cat_app import app_settings, link, marker_style, perf
from core.config import resolve_path

ENGINE = Path(__file__).resolve().parent.parent
TOP = ENGINE.parent
APP_DATA = resolve_path("my_data/app")
TRACKER_DATA = resolve_path("my_data/tracker")
ASSETS = ENGINE / "cat_tracker" / "assets"


def tracker_python():
    """The project's Python, without a console window on Windows."""
    scripts = TOP / ".venv" / ("Scripts" if os.name == "nt" else "bin")
    for name in (("pythonw.exe", "python.exe") if os.name == "nt" else ("python",)):
        if (scripts / name).exists():
            return scripts / name
    return Path(sys.executable)


def qimage_to_rgba(img):
    import numpy as np  # only needed for Marker look previews (see marker_style)
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    arr = np.frombuffer(img.constBits(), np.uint8, img.bytesPerLine() * h).reshape(h, img.bytesPerLine())
    return arr[:, : w * 4].reshape(h, w, 4).copy()


def rgba_to_qimage(arr):
    import numpy as np
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()


class Images(QQuickImageProvider):
    """image://cat/frame/<n> is the newest camera picture; image://cat/preview/<group>/<n> a marker preview."""

    def __init__(self, backend):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.backend = backend

    def requestImage(self, ident, size, requested):  # noqa: N802
        parts = ident.split("/")
        img = None
        if parts[0] == "frame":
            img = self.backend._frame
        elif parts[0] == "preview" and len(parts) > 1:
            img = self.backend.preview_image(parts[1])
        if img is None or img.isNull():
            img = QImage(4, 4, QImage.Format.Format_RGBA8888)
            img.fill(0)
        if size is not None:
            try:
                size.setWidth(img.width())
                size.setHeight(img.height())
            except AttributeError:
                pass
        return img


class Backend(QObject):
    statusChanged = Signal()
    frameChanged = Signal()
    styleChanged = Signal()
    messageChanged = Signal()
    settingsChanged = Signal()
    heatChanged = Signal()
    vrVisibleChanged = Signal()
    feetChanged = Signal()
    crashNoticeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.style_path = APP_DATA / "marker_style.json"
        self._style = marker_style.load(self.style_path)
        if not self.style_path.exists():
            marker_style.save(self.style_path, self._style)
        self._status = {}
        self._connected = False
        self._last_ok = 0.0
        self._starting_until = 0.0
        self._frame = None
        self._frame_seq = 0
        self._frames_wanted = 0.0
        self._trail = []
        self._message = ""
        self._crash_notice = False  # the PC went down while the app was open last time (see crash_check)
        self._previews = {}
        self._asset_cache = {}
        self._preview_rev = 0
        self._blocks = {}            # the tracker's shared memory blocks while it runs (cat_app.link)
        self._ask = {"cmds": []}     # what this app wants from the tracker, and the buttons pressed
        self._ask_written = 0.0
        self._last_change = 0.0      # when the tracker's status last changed
        self._status_seq = -1
        # Footprint: poll the tracker 5 times a second only while the window or the VR tab is on screen
        # (otherwise every 2 s), and only tell the screens to redraw when what they show has changed.
        # --no-optimize turns both off, to compare.
        self.optimize = True
        self.desktop_visible = True
        self.vr_visible = False
        self._shown_key = None
        self.meter = perf.Meter()
        self.timer = QTimer(self, interval=200, timeout=self.poll)
        self.timer.start()
        self._save_timer = QTimer(self, singleShot=True, interval=150, timeout=self._save_style)
        # the app's own settings (alerts, snooze, map, wrist widget): my_data\app\app_settings.json
        self.settings_path = APP_DATA / "app_settings.json"
        self._settings = app_settings.load(self.settings_path)
        self._settings_timer = QTimer(self, singleShot=True, interval=250, timeout=self._save_settings)
        self._snooze_tick = QTimer(self, interval=30000, timeout=self.settingsChanged.emit)  # the countdown text
        if app_settings.snoozed(self._settings):
            self._snooze_tick.start()
        self._heat = {}
        self._heat_busy = False
        self._heat_at = 0.0
        # foot trackers: assigned by waving (cat_app.feet_pick), used by the tracker for the distance
        from cat_app.feet_pick import FeetPick
        self.vr_source = lambda: None  # main.py points this at the SteamVR tab's connection
        self.feet_pick = FeetPick(lambda: self.vr_source(), self)
        self.feet_pick.changed.connect(self.feetChanged.emit)
        self.feet_pick.changed.connect(self.statusChanged.emit)  # the assigned feet shown on the screens

    # ---- the link to the tracker (shared memory) ----

    def _block(self, name):
        b = self._blocks.get(name)
        if b is None:
            b = link.open_block(name)
            if b is not None:
                self._blocks[name] = b
        return b

    def _drop_link(self):
        for b in self._blocks.values():
            b.close()
        self._blocks = {}
        self._status_seq = -1

    def _write_ask(self, force=False):
        """Tell the tracker what's wanted (refreshed once a second, so it stops sending when the app closes)."""
        now = time.time()
        if not force and now - self._ask_written < 1.0:
            return
        b = self._block(link.ASK)
        if b is None:
            return
        on_screen = self.desktop_visible or self.vr_visible
        self._ask["status_until"] = now + 3.0 if on_screen else 0
        self._ask["frames_until"] = now + 2.0 if time.monotonic() < self._frames_wanted else 0
        self._ask["heat_until"] = now + 8.0 if (on_screen and self._settings["map"]["heat"] != "off") else 0
        self._ask["cmds"] = self._ask["cmds"][-10:]
        link.write_json(b, self._ask)
        self._ask_written = now

    demo = False  # --demo: made-up status, to look at the screens without the tracker

    def _demo_status(self):
        import math
        t = time.monotonic()
        x, z = 0.4 * math.cos(t / 6), 0.6 * math.sin(t / 6) + 0.3
        hx, hz = -0.6, 0.2
        d = math.hypot(x - hx, z - hz)
        return {"bridge": True, "running": True, "vr": True, "anchoring": False, "frame_seq": 0,
                "anchor": {"have": True, "off": False},
                "cat": {"state": "seen", "pos": [x, 0.15, z], "pos_raw": [x, 0.15, z], "kind": "move", "speed": 0.3, "dist": d,
                        "level": "near" if d < 0.9 else None, "alpha": 1.0, "from": "left foot",
                        "wobble_cm": max(0.0, 12 - 14 * math.hypot(x - 0.35, z - 0.75))},
                "alert": {"now": {"underfoot_m": 1.0, "radius_m": 1.8, "max_warn_m": 4.0, "buzz_amplitude": 0.6, "buzz": True},
                          "config": {"underfoot_m": 1.0, "radius_m": 1.8, "max_warn_m": 4.0, "buzz_amplitude": 0.6, "buzz": True}},
                "auto_capture": {"active": False, "count": 0},
                "feet": {"assigned": ["left", "right"], "tracked": ["left", "right"]},
                "head": {"pos": [hx, 1.6, hz], "fwd": [0.8, 0.2]},
                "room": {"bounds": [-1.9, 1.9, -1.6, 2.1], "cameras": [[-1.75, -1.45], [1.75, -1.45], [1.75, 1.95], [-1.75, 1.95]]},
                "cameras": {"names": ["front_left", "front_right", "back_right", "back_left"], "stale": [2] if int(t / 8) % 3 == 2 else []},
                "problem": None, "hint": None, "capture": {"on": False, "n": 0}}

    def _interval(self):
        if not self.optimize:
            return 200
        if not (self.desktop_visible or self.vr_visible):
            return 2000
        if not self._connected and not self.starting:
            return 1000  # tracker not running: just watch for it to appear
        return 200

    def setDesktopVisible(self, shown):
        self.desktop_visible = bool(shown)
        self._retime()

    def setVrVisible(self, shown):
        if bool(shown) != self.vr_visible:
            self.vr_visible = bool(shown)
            self._retime()
            self.vrVisibleChanged.emit()

    @Property(bool, notify=vrVisibleChanged)
    def vrTabOpen(self):
        """True while the SteamVR dashboard shows the cat tab (its Cameras page asks for pictures only then)."""
        return self.vr_visible

    # ---- foot trackers ----

    @Property("QVariantMap", notify=feetChanged)
    def feetPick(self):
        """The wave-to-assign steps: state (idle, settle, left, right, done, failed) and what to tell you."""
        return {"state": self.feet_pick.state, "text": self.feet_pick.text,
                "busy": self.feet_pick.state in ("settle", "left", "right")}

    @Property("QVariantMap", notify=statusChanged)
    def feet(self):
        """Which foot trackers are assigned and tracking, and what the distance is measured from right now."""
        f = self._status.get("feet") or {}
        assigned = f.get("assigned") if self._connected else self.feet_pick.assigned()
        tracked = f.get("tracked") or [] if self._connected else []
        frm = ((self._status.get("cat") or {}).get("from") or "") if self._connected else ""
        if not assigned:
            text = "No foot trackers assigned: the distance is from your headset."
        else:
            names = " and ".join(assigned)
            if not self._connected:
                text = f"Assigned: {names} foot. Used while the tracker runs."
            elif not tracked:
                text = f"Assigned: {names} foot, but not tracking (switched off?). Using your headset for now."
            else:
                text = f"Assigned: {names} foot ({' and '.join(tracked)} tracking)."
        return {"assigned": assigned or [], "tracked": tracked, "from": frm, "text": text}

    @Slot()
    def startFeetPick(self):
        self.feet_pick.start()

    @Slot()
    def cancelFeetPick(self):
        self.feet_pick.cancel()

    @Slot()
    def feetOnlyOne(self):
        self.feet_pick.only_one()

    @Slot()
    def forgetFeet(self):
        self.feet_pick.forget()
        self.statusChanged.emit()

    def _retime(self):
        if self.timer.interval() != self._interval():
            self.timer.setInterval(self._interval())
            if self._interval() < 2000:
                self.poll()  # straight away, so a window that just appeared isn't out of date

    @staticmethod
    def _rounded(x, nd):
        if isinstance(x, float):
            return round(x, nd)
        if isinstance(x, list):
            return [Backend._rounded(v, nd) for v in x]
        if isinstance(x, dict):
            return {k: Backend._rounded(v, 1 if k in ("head", "speed", "dist") else nd) for k, v in x.items()
                    if k not in ("frame_seq", "pid", "started", "style_version", "wobble_cm", "buzz")}
        return x

    def _emit_status(self):
        """Tell the screens to redraw, but only if something they show changed (to 2 cm, 0.1 m for you)."""
        self.meter.count("status checks")
        self._retime()  # the polling speed depends on whether the tracker is connected
        key = json.dumps([self._connected, self.starting, self.otherTracker, self._rounded(self._status, 2)],
                         sort_keys=True)
        if self.optimize and key == self._shown_key:
            return
        self._shown_key = key
        self.meter.count("screen updates")
        self.statusChanged.emit()

    def poll(self):
        if self.demo:
            self._status = self._demo_status()
            self._connected = True
            self._update_trail()
            self._emit_status()
            self._maybe_fetch_heat()
            return
        st = self._block(link.STATUS)
        data = None
        if st is not None:
            seq, data = st.read()
            if data is not None:
                self._last_change = time.monotonic()
        if data is not None:
            try:
                old_alert = self._status.get("alert")
                self._status = json.loads(data)
                if self._status.get("alert") != old_alert:
                    self.settingsChanged.emit()  # alertValues shows the tracker's own values
                self._connected = True
                self._last_ok = time.monotonic()
                self._update_trail()
            except ValueError:
                pass
        elif self._connected and time.monotonic() - self._last_change > 3.0:
            # no change for 3 s (it writes at least once a second): it has ended
            self._connected = False
            self._status = {}
            self._drop_link()
        elif not self._connected and st is not None and time.monotonic() - self._last_change > 3.0:
            self._drop_link()  # an ended tracker's leftover blocks: let go of them
        if self._connected:
            self._write_ask()
            self._maybe_fetch_heat()
            if time.monotonic() < self._frames_wanted and self._status.get("frame_seq", 0) != self._frame_seq:
                self._read_frame()
        self._emit_status()

    def _maybe_fetch_heat(self):
        """The room heatmap, every 5 s while a map is on screen and the heat layer is on."""
        now = time.monotonic()
        if (self._settings["map"]["heat"] == "off" or not self._connected
                or now - self._heat_at < 5.0 or not (self.desktop_visible or self.vr_visible)):
            return
        self._heat_at = now
        if self.demo:
            self._heat = self._demo_heat()
            self.heatChanged.emit()
            return
        b = self._block(link.HEAT)
        if b is None:
            return
        _, data = b.read()
        if data:
            try:
                h = json.loads(data)
            except ValueError:
                return
            if h != self._heat:
                self._heat = h
                self.heatChanged.emit()

    def _demo_heat(self):
        import math
        b, c = [-1.9, 1.9, -1.6, 2.1], 0.15
        nx, nz = int(math.ceil(3.8 / c)), int(math.ceil(3.7 / c))
        t = [[round(max(0.0, 1 - math.hypot(b[0] + (j + .5) * c - 0.0, b[2] + (i + .5) * c - 0.3) / 0.9), 2)
              for j in range(nx)] for i in range(nz)]
        w = [[round(max(0.0, 12 - 14 * math.hypot(b[0] + (j + .5) * c - 0.35, b[2] + (i + .5) * c - 0.75)), 1)
              if t[i][j] > 0 else 0.0 for j in range(nx)] for i in range(nz)]
        return {"bounds": b, "cell": c, "time": t, "wobble_cm": w, "seconds": 600.0}

    @Property("QVariantMap", notify=heatChanged)
    def heat(self):
        return self._heat

    def _read_frame(self):
        b = self._block(link.FRAME)
        if b is None:
            return
        _, data = b.read()
        if data:
            img = QImage.fromData(data, "JPG")
            if not img.isNull():
                self._frame = img
                self._frame_seq = self._status.get("frame_seq", 0)
                self.meter.count("camera pictures")
                self.frameChanged.emit()

    def _update_trail(self):
        cat = self._status.get("cat") or {}
        now = time.monotonic()
        if cat.get("state") == "seen" and cat.get("pos"):
            p = cat["pos"]
            if not self._trail or abs(self._trail[-1][1] - p[0]) + abs(self._trail[-1][2] - p[2]) > 0.02:
                self._trail.append((now, p[0], p[2], float(cat.get("wobble_cm") or 0.0)))
        self._trail = [t for t in self._trail if now - t[0] < 30][-120:]

    # ---- what the screens show ----

    def _heartbeat(self):
        """A tracker started without the app (run_tracker.bat, or SteamVR without the app) can't be seen
        through the link; its heartbeat file says if it runs.
        Read at most twice a second (the screens ask for it many times per update)."""
        now = time.monotonic()
        if now - getattr(self, "_hb_at", -10) < 0.5:
            return self._hb
        self._hb_at = now
        self._hb = self._read_heartbeat()
        return self._hb

    def _read_heartbeat(self):
        try:
            hb = json.loads((TRACKER_DATA / "heartbeat.json").read_text(encoding="utf-8"))
            return hb.get("state") == "running" and time.time() - float(hb.get("t", 0)) < 5
        except (OSError, ValueError):
            return False

    @Property("QVariantMap", notify=statusChanged)
    def status(self):
        return self._status

    @Property(bool, notify=statusChanged)
    def connected(self):
        return self._connected

    @Property(bool, notify=statusChanged)
    def otherTracker(self):
        """A tracker is running that this app didn't start (SteamVR autostart or run.bat)."""
        return not self._connected and self._heartbeat()

    @Property(bool, notify=statusChanged)
    def starting(self):
        return not self._connected and time.monotonic() < self._starting_until

    @Property(str, notify=statusChanged)
    def level(self):
        """ok, info, warn, alert or off: the colour of the status banner."""
        s = self._status
        if not self._connected:
            return "info" if self.starting or self.otherTracker else "off"
        if s.get("error"):
            return "alert"
        if s.get("problem"):
            return "alert"
        cat = s.get("cat") or {}
        if cat.get("level"):
            return "alert"
        if s.get("anchoring") or (s.get("anchor") or {}).get("off") or (s.get("vr") and not (s.get("anchor") or {}).get("have")):
            return "warn"
        if s.get("hint"):
            return "warn"
        return "ok"

    @Property(str, notify=statusChanged)
    def headline(self):
        s = self._status
        if not self._connected:
            if self.starting:
                return "Starting the tracker..."
            if self.otherTracker:
                return "The tracker is running in the background"
            return "The tracker isn't running"
        if s.get("error") and s.get("finished"):
            return "The tracker stopped"
        if s.get("anchoring"):
            return "Anchoring: headset on, walk slowly around the room"
        if s.get("problem"):
            return s["problem"][1].replace("Cat tracker: ", "").capitalize()
        if not s.get("running"):
            return "Getting the cameras ready..."
        cat = s.get("cat") or {}
        st, kind, dist, lvl = cat.get("state"), cat.get("kind"), cat.get("dist"), cat.get("level")
        if st == "hidden":
            return "No cat in the room"
        where = f", about {dist:.1f} m from you" if dist is not None else ""
        if lvl == "underfoot":
            return f"Cat underfoot{where}!"
        if lvl:
            return f"Cat close{where}"
        if st == "lost":
            return f"Cat last seen{where}"
        doing = {"rest": "napping", "move": "on the move"}.get(kind, "")
        return f"Cat seen{where}" + (f", {doing}" if doing else "")

    @Property(str, notify=statusChanged)
    def detail(self):
        s = self._status
        if not self._connected:
            if self.otherTracker:
                return ("It was started without the app (the desktop test, a capture, or with --no-app). "
                        "Press Stop background tracker, then Start, to run it from here.")
            if self.starting:
                return "Opening the cameras and loading the model takes a few seconds."
            return "Press Start. SteamVR should be running first, so the cat can be shown in VR."
        if s.get("error") and s.get("finished"):
            return s["error"].strip().splitlines()[-1]
        if s.get("problem"):
            return " ".join(s["problem"][2])
        bits = []
        if s.get("hint"):
            bits.append("Graphics card busy, so tracking is slower. " + " ".join(s["hint"][2]))
        an = s.get("anchor") or {}
        if s.get("vr") and not an.get("have"):
            bits.append("No anchor yet: clear the floor, put the headset on and walk slowly around the room. "
                        "It waits for you and says when it has enough. It's saved, so this is needed again only if "
                        "a camera or a base station moves.")
            if an.get("why"):
                bits.append(f"Last walk didn't work: {an['why']}. Press Re-anchor to try again.")
        elif an.get("off"):
            bits.append("The room anchor needs redoing" + (f" ({an['reason']})" if an.get("reason") else "")
                        + ": clear the floor, press Re-anchor and walk slowly around the room with the headset on.")
        elif an.get("last_failed"):
            bits.append("That anchor walk didn't work" + (f" ({an['why']})" if an.get("why") else "")
                        + ", so the previous anchor is still in use. Nothing to do unless the app asks.")
        if not s.get("vr"):
            bits.append("Running without SteamVR (desktop test).")
        cap = s.get("capture") or {}
        if cap.get("on"):
            bits.append(f"Capturing for training: {cap.get('n', 0)} moments saved.")
        return " ".join(bits) or "Cameras sending pictures."

    @Property("QVariantList", notify=statusChanged)
    def cameraList(self):
        cams = self._status.get("cameras") or {}
        names, stale = cams.get("names") or [], set(cams.get("stale") or [])
        return [{"name": n, "ok": i not in stale} for i, n in enumerate(names)]

    @Property("QVariantList", notify=statusChanged)
    def trail(self):
        return [[x, z, w] for _, x, z, w in self._trail]

    @Property(int, notify=frameChanged)
    def frameSeq(self):
        return self._frame_seq

    @Property(bool, notify=frameChanged)
    def hasFrame(self):
        return self._frame is not None

    @Property(str, notify=messageChanged)
    def message(self):
        return self._message

    def _say(self, text):
        self._message = text
        self.messageChanged.emit()

    @Slot()
    def wantFrames(self):
        """Called by the Cameras screen while it's visible."""
        first = time.monotonic() >= self._frames_wanted
        self._frames_wanted = time.monotonic() + 1.5
        if first:
            self._write_ask(force=True)

    # ---- buttons ----

    def _post(self, cmd):
        """Press a button in the tracker (it picks it up within a tenth of a second)."""
        self._ask["cmds"].append([time.time_ns(), cmd])
        self._write_ask(force=True)

    @Property(bool, notify=settingsChanged)
    def startOsc(self):
        """Whether Start sends to VRChat: the last choice made on the desktop window, else what the SteamVR
        autostart uses (6_optional_vrchat\\4_install_autostart_vrchat.bat adds --osc)."""
        v = self._settings.get("start_osc")
        if isinstance(v, bool):
            return v
        try:
            return "--osc" in (ENGINE / "cat_tracker" / "cat_tracker.vrmanifest").read_text(encoding="utf-8")
        except OSError:
            return False

    @Slot()
    def startFromVr(self):
        """The VR tab's Start: the saved anchor, and VRChat on or off as last chosen (it has no tick boxes)."""
        self.start(False, self.startOsc)

    @Slot(bool, bool)
    def start(self, new_anchor=False, osc=False):
        if self._connected:
            return
        if bool(osc) != self.startOsc or self._settings.get("start_osc") is None:
            self.setSetting("start_osc", bool(osc))
        if self._heartbeat():
            self._say("Another cat tracker is already running (it has the cameras). Press Stop first.")
            return
        args = [str(tracker_python()), "-m", "cat_app.bridge", "--"]
        if new_anchor:
            args.append("--new-anchor")
        if osc:
            args.append("--osc")
        flags = 0
        if os.name == "nt":  # its own process: it keeps running if the app closes (Stop, or closing SteamVR, ends it)
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            subprocess.Popen(args, cwd=str(ENGINE), creationflags=flags, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        except OSError as e:
            self._say(f"Couldn't start the tracker: {e}")
            return
        self._starting_until = time.monotonic() + 30
        self._retime()
        self._say("Starting. If it doesn't come up, the log is in my_data\\logs\\cat_app\\bridge.log.")
        self.statusChanged.emit()

    @Slot()
    def stop(self):
        if self._connected:
            self._post("stop")
            self._say("Stopping the tracker.")
        elif self._heartbeat():  # one started without the app: the same as stop_tracker.bat
            TRACKER_DATA.mkdir(parents=True, exist_ok=True)
            (TRACKER_DATA / "stop").write_text("stop", encoding="utf-8")
            self._say("Asked the background tracker to stop. It closes within a couple of seconds.")

    @Property(bool, notify=statusChanged)
    def anchorNeeded(self):
        """Only true when re-anchoring is really needed: no anchor yet, or the tracker says it's off."""
        s = self._status
        an = s.get("anchor") or {}
        return bool(self._connected and s.get("vr") and (an.get("off") or not an.get("have")))

    @Slot()
    def reanchor(self):
        if self._connected:
            self._post("anchor")
            self._say("Re-anchoring: clear the floor first, then put the headset on and walk slowly around the room. "
                      "It says when it has enough. If the walk doesn't work, the previous anchor stays in use.")

    @Slot()
    def toggleCapture(self):
        if self._connected:
            self._post("capture")

    @Slot()
    def snapshot(self):
        if self._connected:
            self._post("snapshot")
            self._say("Saved a snapshot in my_data\\logs\\cameras\\snapshots.")

    @Slot()
    def testBuzz(self):
        if self._connected:
            self._post("buzz")

    @Slot(str)
    def openFolder(self, which):
        p = {"logs": resolve_path("my_data/logs"), "app_logs": resolve_path("my_data/logs/cat_app"),
             "settings": TOP / "settings", "app_data": APP_DATA}.get(which, TOP)
        p.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    # ---- after the PC went down with the app open: suggest picture mode ----

    @Property(bool, notify=crashNoticeChanged)
    def crashNotice(self):
        return self._crash_notice

    def set_crash_notice(self, on):
        if bool(on) != self._crash_notice:
            self._crash_notice = bool(on)
            self.crashNoticeChanged.emit()

    @Slot()
    def usePictureMode(self):
        self.setSetting("vr_mode", "file")
        self.set_crash_notice(False)

    @Slot()
    def dismissCrashNotice(self):
        self.set_crash_notice(False)

    @Slot()
    def clearMessage(self):
        self._say("")

    # ---- the app's settings: alerts, buzz, snooze, map, wrist widget ----

    @Property("QVariantMap", notify=settingsChanged)
    def settings(self):
        return self._settings

    def _put(self, new):
        new = app_settings.clamp(new)
        if new == self._settings:
            return
        self._settings = new
        if app_settings.snoozed(new):
            self._snooze_tick.start()
        else:
            self._snooze_tick.stop()
        self.settingsChanged.emit()
        self._settings_timer.start()

    @Slot(str, "QVariant")
    def setSetting(self, path, value):
        """path like "wrist.on", "map.heat", "alert.underfoot_m", "buzz_style"."""
        new = json.loads(json.dumps(self._settings))
        d = new
        keys = path.split(".")
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        if value is None and keys[0] == "alert":
            d.pop(keys[-1], None)
        else:
            d[keys[-1]] = value
        self._put(new)

    @Slot(str, float)
    def nudgeSetting(self, path, step):
        cur = self.alertValues.get(path.split(".")[-1]) if path.startswith("alert.") else None
        if cur is None:
            d = self._settings
            for k in path.split("."):
                d = d.get(k) if isinstance(d, dict) else None
            cur = d
        if isinstance(cur, (int, float)) and not isinstance(cur, bool):
            self.setSetting(path, round(float(cur) + step, 3))

    def _save_settings(self):
        app_settings.save(self.settings_path, self._settings)

    @Property("QVariantMap", notify=settingsChanged)
    def alertValues(self):
        """The warning distances and buzz strength in use: your changes, else settings\\cat_tracker.yaml."""
        a = self._status.get("alert") or {}
        cfg = a.get("config") or {}
        fallback = {"underfoot_m": 1.0, "radius_m": 1.8, "buzz_amplitude": 0.6, "buzz": True, "max_warn_m": 4.0}
        out = {k: (cfg.get(k) if cfg.get(k) is not None else v) for k, v in fallback.items()}
        out.update(self._settings["alert"])
        out["changed"] = bool(self._settings["alert"])
        out["known"] = bool(cfg)
        return out

    @Slot()
    def resetAlerts(self):
        new = json.loads(json.dumps(self._settings))
        new["alert"] = {}
        self._put(new)

    @Slot(float)
    def snooze(self, minutes):
        """Mutes the warning buzz for this many minutes; -1 until you switch it back on; 0 switches it back on.
        The arrow and the red icon still show."""
        self.setSetting("snooze_until", -1.0 if minutes < 0 else (time.time() + 60 * minutes if minutes > 0 else 0.0))

    @Slot()
    def toggleSnooze(self):
        """The Snooze button on the main screens: snoozes for the length chosen in the settings, or
        switches the buzz back on."""
        self.snooze(0 if self.snoozed else float(self._settings["snooze_minutes"]))

    @Property(str, notify=settingsChanged)
    def snoozeButtonText(self):
        if self.snoozed:
            return "Buzz back on"
        m = int(self._settings["snooze_minutes"])
        return ("Snooze buzz" if m < 0 else
                f"Snooze buzz {m // 60} hour{'s' if m >= 120 else ''}" if m >= 60 else f"Snooze buzz {m} min")

    @Property(bool, notify=settingsChanged)
    def snoozed(self):
        return app_settings.snoozed(self._settings)

    @Property(str, notify=settingsChanged)
    def snoozeText(self):
        u = self._settings["snooze_until"]
        if u < 0:
            return "Buzz snoozed until you switch it back on"
        left = u - time.time()
        if left <= 0:
            return ""
        return f"Buzz snoozed for {max(1, round(left / 60))} more min"

    @Property("QVariantMap", notify=statusChanged)
    def wristInfo(self):
        """What the wrist widget shows: the cat's distance, which way it is from where you're facing (degrees,
        clockwise, 0 = straight ahead), what it's doing, and any problem."""
        import math
        s = self._status
        cat, head = s.get("cat") or {}, s.get("head") or {}
        out = {"dist": None, "angle": None, "level": self.level, "state": "", "problem": "", "from": ""}
        if not self._connected:
            out["state"] = "Tracker off"
            return out
        st = cat.get("state")
        if st in ("seen", "lost") and cat.get("pos"):
            out["dist"] = cat.get("dist")
            if (s.get("feet") or {}).get("assigned") and cat.get("from"):  # only worth saying once feet are in use
                out["from"] = "from " + ("your head" if cat["from"] == "head" else "your " + cat["from"])
            if head.get("pos") and head.get("fwd"):
                fx, fz = head["fwd"]
                dx, dz = cat["pos"][0] - head["pos"][0], cat["pos"][2] - head["pos"][2]
                if math.hypot(fx, fz) > 1e-6 and math.hypot(dx, dz) > 1e-6:
                    a = math.degrees(math.atan2(dz, dx) - math.atan2(fz, fx))
                    out["angle"] = round((a + 180) % 360 - 180)
        lvl = cat.get("level")
        out["state"] = ("Underfoot!" if lvl == "underfoot" else "Close" if lvl else
                        "Last seen" if st == "lost" else "No cat" if st in (None, "hidden") else
                        {"rest": "Napping", "move": "On the move"}.get(cat.get("kind"), "Seen"))
        if s.get("problem"):
            out["problem"] = s["problem"][1].replace("Cat tracker: ", "").capitalize()
        elif (s.get("anchor") or {}).get("off"):
            out["problem"] = "Re-anchor needed"
        elif s.get("vr") and not (s.get("anchor") or {}).get("have"):
            out["problem"] = "No anchor yet"
        elif s.get("hint"):
            out["problem"] = "Graphics card busy"
        return out

    @Slot()
    def clearHeatmap(self):
        if self._connected and not self.demo:
            self._post("clear_heatmap")
        self._heat = {}
        self._heat_at = 0.0
        self.heatChanged.emit()

    # ---- marker style ----

    @Property("QVariantMap", notify=styleChanged)
    def style(self):
        return self._style

    @Property("QVariantList", constant=True)
    def palette(self):
        return marker_style.PALETTE

    @Property("QVariantMap", constant=True)
    def limits(self):
        return {"shade": list(marker_style.LIMITS["shade"]), "size": list(marker_style.LIMITS["size"]),
                "opacity": {g: list(v) for g, v in marker_style.LIMITS["opacity"].items()}}

    @Property(int, notify=styleChanged)
    def previewRev(self):
        return self._preview_rev

    @Slot(str, str, "QVariant")
    def setStyle(self, group, key, value):
        if group not in self._style:
            return
        new = json.loads(json.dumps(self._style))
        new[group][key] = value
        new = marker_style.clamp_style(new)
        if new == self._style:
            return
        self._style = new
        if key in ("colour", "shade"):
            self._previews.pop(group, None)
            self._preview_rev += 1
        self.styleChanged.emit()
        self._save_timer.start()

    @Slot(str, str, float)
    def nudgeStyle(self, group, key, step):
        """+/- buttons (easier than sliders with a laser pointer)."""
        if group in self._style:
            self.setStyle(group, key, round(float(self._style[group][key]) + step, 3))

    @Slot(str)
    def resetStyle(self, group):
        new = json.loads(json.dumps(self._style))
        new[group] = dict(marker_style.DEFAULTS[group])
        self._style = marker_style.clamp_style(new)
        self._previews.pop(group, None)
        self._preview_rev += 1
        self.styleChanged.emit()
        self._save_timer.start()

    def _save_style(self):
        marker_style.save(self.style_path, self._style)

    def _asset(self, group):
        if group not in self._asset_cache:
            name = marker_style.GROUPS[group]["files"][0]
            img = QImage(str(ASSETS / name))
            self._asset_cache[group] = qimage_to_rgba(img) if not img.isNull() else None
        return self._asset_cache[group]

    def preview_image(self, group):
        if group not in marker_style.GROUPS:
            return None
        if group not in self._previews:
            src = self._asset(group)
            if src is None:
                return None
            self._previews[group] = rgba_to_qimage(marker_style.restyle(src, self._style[group]))
        return self._previews[group]
