"""Is the tracker itself working? The aim: no marker should mean "no cat seen", not "the tracker stopped looking".
It can't guarantee that. Two parts:

- Health (in the tracker): notices a camera that stopped sending pictures and a detector that keeps
  failing, so the tracker can show a notice in VR and ignore that camera instead of trusting an old picture.
- Heartbeat (in the tracker) + watchdog.py (a separate small process): if the tracker crashes, is
  killed or freezes, its own overlays vanish with it, so the watchdog shows the notice instead.
"""

import json
import os
import time
from pathlib import Path


class Health:
    def __init__(self, hc, names):
        self.names = list(names)
        self.stale_s = float(hc.get("camera_stale_s", 2.0))
        self.det_fail_s = float(hc.get("detector_fail_s", 3.0))
        self.no_frame_since = [None] * len(self.names)
        self.stale = []
        self.det_fail_since = None
        self.det_failures = 0

    def cameras(self, items, now):
        """items: each camera's latest (frame, t_ns, seq) or None; now: time.monotonic().
        Returns the indices of cameras whose newest picture is older than camera_stale_s (or that
        never sent one for that long). Their boxes should be ignored: the picture is out of date."""
        now_ns = time.perf_counter_ns()
        stale = []
        for i, it in enumerate(items):
            if it is None:
                self.no_frame_since[i] = self.no_frame_since[i] if self.no_frame_since[i] is not None else now
                if now - self.no_frame_since[i] > self.stale_s:
                    stale.append(i)
                continue
            self.no_frame_since[i] = None
            if (now_ns - it[1]) / 1e9 > self.stale_s:
                stale.append(i)
        self.stale = stale
        return stale

    def detector_ok(self):
        self.det_fail_since = None

    def detector_failed(self, now):
        self.det_failures += 1
        if self.det_fail_since is None:
            self.det_fail_since = now

    def message(self, now):
        """(key, title, lines) for the notice to show, or None when everything is fine."""
        if self.det_fail_since is not None and now - self.det_fail_since > self.det_fail_s:
            return ("detector", "Cat tracker: detection failing",
                    ["Your pet is NOT being tracked right now.", "See cat_tracker/logs for the error."])
        if self.stale and len(self.stale) == len(self.names):
            return ("all_cameras", "Cat tracker: cameras stopped",
                    ["No camera is sending pictures.", "Your pet is NOT being tracked right now."])
        if self.stale:
            which = ", ".join(self.names[i] for i in self.stale)
            return ("cameras:" + which, "Cat tracker: camera stopped",
                    [f"Not sending pictures: {which}", "Tracking with the other cameras only."])
        return None


class Heartbeat:
    """Writes cat_tracker/data/heartbeat.json about once a second while the tracker runs, and
    "stopped" when it closes on purpose. The watchdog reads it."""

    def __init__(self, path, every_s=1.0):
        self.path = Path(path)
        self.every_s = every_s
        self.last = 0.0
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def beat(self, force=False):
        now = time.monotonic()
        if force or now - self.last >= self.every_s:
            self.last = now
            self._write("running")

    def stopped(self):
        self._write("stopped")

    def _write(self, state):
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({"pid": os.getpid(), "t": time.time(), "state": state}), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:  # the watchdog may be reading it this instant (Windows); the next beat will do
            pass
