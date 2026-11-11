"""Assign the foot trackers by waving them: sit down, wave your left foot, then your right foot.

The tracker that moved the most, by a clear margin, is that foot (calibration.wave, the same rule as picking the
room calibration's tracker). Only SteamVR trackers count, not controllers or the headset, so holding a controller
doesn't get in the way. The result goes to my_data/tracker/feet.json (cat_tracker.feet), which the tracker re-reads
within a few seconds, so it applies without a restart.

Runs in the app (it already talks to SteamVR for the dashboard tab); the screens show `state` and its `text`.
"""

import time

from PySide6.QtCore import QObject, QTimer, Signal

from calibration import wave
from cat_tracker import feet

SETTLE_S = 3.0      # "sit down and keep your feet still" before the first wave
WAVE_S = 8.0        # how long to wait for a wave before asking again
EARLY_S = 1.0       # a clear winner after this long ends the wave early
TRIES = 3           # asks per foot before giving up


class FeetPick(QObject):
    changed = Signal()

    def __init__(self, vr_source, parent=None, save=feet.save, load=feet.load):
        """vr_source(): (openvr module, IVRSystem) while SteamVR is connected, else None."""
        super().__init__(parent)
        self.vr_source = vr_source
        self._save, self._load = save, load
        self.timer = QTimer(self, interval=33, timeout=self.tick)
        self.state = "idle"     # idle, settle, left, right, done, failed
        self.text = ""
        self.found = {}         # side -> serial, picked in this run
        self.tracks = {}
        self.serials = {}       # device number -> serial, for this wave
        self.until = 0.0
        self.started = 0.0
        self.tries = 0

    # ---- SteamVR ----

    def _trackers(self, ovr, sys):
        """[(device number, serial)] of the connected SteamVR trackers not already picked in this run."""
        out = []
        for i in range(ovr.k_unMaxTrackedDeviceCount):
            if not sys.isTrackedDeviceConnected(i) or sys.getTrackedDeviceClass(i) != ovr.TrackedDeviceClass_GenericTracker:
                continue
            try:
                s = sys.getStringTrackedDeviceProperty(i, ovr.Prop_SerialNumber_String)
            except Exception:  # noqa: BLE001
                continue
            if s and s not in self.found.values():
                out.append((i, s))
        return out

    def _positions(self, ovr, sys, indices):
        poses = sys.getDeviceToAbsoluteTrackingPose(ovr.TrackingUniverseRawAndUncalibrated, 0,
                                                    ovr.k_unMaxTrackedDeviceCount)
        out = {}
        for i in indices:
            p = poses[i]
            ok = p.bPoseIsValid and p.eTrackingResult == ovr.TrackingResult_Running_OK
            out[i] = [p.mDeviceToAbsoluteTracking.m[r][3] for r in range(3)] if ok else None
        return out

    # ---- steps ----

    def _set(self, state, text):
        self.state, self.text = state, text
        self.changed.emit()

    def start(self):
        got = self.vr_source()
        if got is None:
            self._set("failed", "Start SteamVR first, then try again.")
            return
        ovr, sys = got
        if not self._trackers(ovr, sys):
            self._set("failed", "No SteamVR trackers are switched on. Switch on your foot trackers, then try again.")
            return
        self.found = {}
        self.until = time.monotonic() + SETTLE_S
        self._set("settle", "Sit down and keep both feet still.")
        self.timer.start()

    def cancel(self):
        self.timer.stop()
        self._set("idle", "")

    def only_one(self):
        """While waiting for the right foot: there's only one foot tracker, keep the left one."""
        if self.state == "right" and self.found.get("left"):
            self._finish()

    def forget(self):
        self.timer.stop()
        self._save({})
        self._set("idle", "")

    def _begin_wave(self, side, hint=""):
        got = self.vr_source()
        if got is None:
            return self._fail("Lost SteamVR. Start it again, then try again.")
        ovr, sys = got
        devs = self._trackers(ovr, sys)
        if not devs:
            if side == "right" and self.found.get("left"):
                return self._finish()
            return self._fail("No SteamVR trackers are switched on.")
        self.tracks = {i: ("tracker", []) for i, _ in devs}
        self.serials = dict(devs)
        self.started = time.monotonic()
        self.until = self.started + WAVE_S
        foot = "LEFT" if side == "left" else "RIGHT"
        self._set(side, (hint + " " if hint else "") + f"Wave your {foot} foot now, the other foot still.")

    def _fail(self, text):
        self.timer.stop()
        self._set("failed", text)

    def _finish(self):
        self.timer.stop()
        self._save(dict(self.found))
        sides = " and ".join(s for s in feet.SIDES if self.found.get(s))
        self._set("done", f"Done: {sides} foot assigned. The distance now comes from whichever is closest to the cat, "
                          "your feet or your headset.")

    def tick(self):
        now = time.monotonic()
        if self.state == "settle":
            if now >= self.until:
                self.tries = 0
                self._begin_wave("left")
            return
        if self.state not in feet.SIDES:
            self.timer.stop()
            return
        got = self.vr_source()
        if got is None:
            return self._fail("Lost SteamVR. Start it again, then try again.")
        ovr, sys = got
        for i, p in self._positions(ovr, sys, list(self.tracks)).items():
            self.tracks[i][1].append(p)
        side = self.state
        pick, why = None, "none"
        if now - self.started >= EARLY_S:
            pick, why = wave.choose(self.tracks, min_path_m=1.5 * wave.MIN_PATH_M)
        if why is not None and now >= self.until:
            pick, why = wave.choose(self.tracks)
            if why is not None:
                self.tries += 1
                if self.tries >= TRIES:
                    if side == "right" and self.found.get("left"):
                        return self._finish()
                    return self._fail("Couldn't tell which tracker moved. Try again, waving the foot further.")
                return self._begin_wave(side, "Two trackers moved about the same." if why == "tie"
                                        else "I didn't see a tracker move.")
        if why is None:
            self.found[side] = self.serials[pick]
            if side == "left":
                self.tries = 0
                self._begin_wave("right", "Got the left foot.")
            else:
                self._finish()

    def assigned(self):
        """Sides saved in feet.json."""
        return sorted(self._load())
