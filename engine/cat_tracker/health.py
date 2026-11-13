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
from collections import deque
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
        # graphics card busy: detection much slower than usual for a while (another program, often a heavy game
        # world, is using the card). A milder hint than the notices below: tracking still runs, only slower.
        self.slow_ms = float(hc.get("gpu_slow_ms", 100))
        self.gpu_hint = bool(hc.get("gpu_hint", True))
        self.det_times = deque()     # (time, ms) of the detections in the last 10 s
        self.first_det = None
        self.busy_since = None
        self.calm_since = None
        self.busy_ms = 0.0           # mean detection time when the hint came on

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

    def detector_time(self, ms, now):
        """How long one detection took (ms). The hint comes on when the last 10 s average gpu_slow_ms or more,
        and goes off after 30 s back under 60% of that. The first 30 s are skipped (the card warms up)."""
        if self.first_det is None:
            self.first_det = now
        self.det_times.append((now, float(ms)))
        while self.det_times and now - self.det_times[0][0] > 10.0:
            self.det_times.popleft()
        if now - self.first_det < 30.0:
            return
        mean = sum(m for _, m in self.det_times) / len(self.det_times)
        if self.busy_since is None:
            if len(self.det_times) >= 2 and mean >= self.slow_ms:
                self.busy_since, self.calm_since, self.busy_ms = now, None, mean
        elif mean < 0.6 * self.slow_ms:
            self.calm_since = now if self.calm_since is None else self.calm_since
            if now - self.calm_since >= 30.0:
                self.busy_since = self.calm_since = None
        else:
            self.calm_since = None

    def hint(self, now):
        """(key, title, lines) for the mild "graphics card busy" hint, or None."""
        if not self.gpu_hint or self.busy_since is None:
            return None
        return ("gpu_busy", "Graphics card busy: tracking slowed",
                ["The cat marker may lag or pause for a moment.",
                 "Lowering your game's graphics settings or resolution can help."])

    def message(self, now):
        """(key, title, lines) for the notice to show, or None when everything is fine."""
        if self.det_fail_since is not None and now - self.det_fail_since > self.det_fail_s:
            return ("detector", "Cat tracker: detection failing",
                    ["Your pet is NOT being tracked right now.", "See my_data/logs/cat_tracker for the error."])
        if self.stale and len(self.stale) == len(self.names):
            return ("all_cameras", "Cat tracker: cameras stopped",
                    ["No camera is sending pictures.", "Your pet is NOT being tracked right now."])
        if self.stale:
            which = ", ".join(self.names[i] for i in self.stale)
            return ("cameras:" + which, "Cat tracker: camera stopped",
                    [f"Not sending pictures: {which}", "Tracking with the other cameras only."])
        return None


class Heartbeat:
    """Writes my_data/tracker/heartbeat.json twice a second while the tracker runs, and "stopped" when it
    closes on purpose. The watchdog reads it. busy(s) tells the watchdog that a known slow step (the first
    detection, loading the pose model) may hold the tracker up for up to s seconds."""

    def __init__(self, path, every_s=0.5):
        self.path = Path(path)
        self.every_s = every_s
        self.last = 0.0
        self.grace_until = 0.0
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def busy(self, seconds):
        self.grace_until = max(self.grace_until, time.time() + float(seconds))
        self.beat(force=True)

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
            now = time.time()
            hb = {"pid": os.getpid(), "t": now, "state": state}
            if self.grace_until > now:
                hb["grace_until"] = self.grace_until
            tmp.write_text(json.dumps(hb), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:  # the watchdog may be reading it this instant (Windows); the next beat will do
            pass
