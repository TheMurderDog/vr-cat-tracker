"""Is the room light still good enough? The camera setup screen checks brightness and grain once, at setup. A room
that was fine then can be dark at night, so the tracker keeps checking while it runs, with the same measures and the
same lines as the setup screen (tools/camera_setup.py, docs/technical/camera_checks.md).

Cheap: one picture per camera every few seconds. Judged over minutes, like the setup screen's checks: a light switched
on or off for a moment doesn't count. A dim room only adds a note to the tracker window (and the log); it doesn't stop
tracking.
"""

import time

import cv2
import numpy as np

from tools.camera_setup import (BRIGHT_ABOVE, CLEAR_AT, DARK_BELOW, DIM_BELOW, GRAINY_AT, NOISY_AT, RED_AT,
                                noise_sigma)

NOTES = {  # (what, what to do): the setup screen's wording, as a line in the tracker window
    "dark": ("too dark", "it may miss the cat. Turn on a light or open a curtain."),
    "dim": ("a bit dark and grainy", "more light helps it see the cat."),
    "bright": ("too bright", "it may miss the cat. Close a curtain, or turn it away from a lamp or window."),
}


def judge(brightness, grain):
    """None (fine), "dim" (yellow), or "dark" / "bright" (red), by the setup screen's lines."""
    if brightness < DARK_BELOW or (grain is not None and grain >= NOISY_AT):
        return "dark"
    if brightness > BRIGHT_ABOVE:
        return "bright"
    if brightness < DIM_BELOW and grain is not None and grain >= GRAINY_AT:
        return "dim"
    return None


class LightWatch:
    def __init__(self, names, log, every_s=5.0, window_s=180.0, log_every_s=300.0):
        self.names, self.log = list(names), log
        self.every_s, self.window_s, self.log_every_s = every_s, window_s, log_every_s
        self.held = [None] * len(self.names)       # each camera's picture from the last call: (frame, seq)
        self.samples = [[] for _ in self.names]    # (time, verdict) per camera, over window_s
        self.raised = [None] * len(self.names)     # the lasting verdict per camera
        self.reading = [None] * len(self.names)    # the last (brightness, grain)
        self.last = self.last_log = None
        self.turn = 0  # the camera checked next: one per look, so the tracker's loop doesn't pause for all of them
        self.cost_ms = []

    def feed(self, items, now=None):
        """items: each camera's latest (frame, t_ns, seq) or None, as the tracker has them (call it on every look).
        Checks one camera in turn, so each is checked about every every_s."""
        now = time.monotonic() if now is None else now
        held, self.held = self.held, [None if it is None else (it[0], it[2]) for it in items]
        if not items or (self.last is not None and now - self.last < self.every_s / len(items)):
            return
        t = time.perf_counter()
        self.last = now
        if self.last_log is None:
            self.last_log = now
        i = self.turn % len(items)
        self.turn = i + 1
        it = items[i]
        if it is not None and it[2] != -1:  # no picture yet, or unplugged: skipped (the health notice covers that)
            g, b = self._grey(it[0])
            grain, h = None, held[i] if i < len(held) else None
            if h is not None and h[1] != it[2] and h[1] != -1 and h[0].shape == it[0].shape:
                # grain from two pictures a moment apart (the tracker's last two looks), as the setup screen does;
                # not when the light or exposure changed between them (that would read as grain)
                g0, b0 = self._grey(h[0])
                if abs(b - b0) <= 0.05 * max(b, 10.0):
                    grain = noise_sigma(g, g0)
            self.reading[i] = (b, grain)
            s = [x for x in self.samples[i] if now - x[0] <= self.window_s] + [(now, judge(b, grain))]
            self.samples[i] = s
            self._decide(i, s)
            self.cost_ms.append((time.perf_counter() - t) * 1000)
        if now - self.last_log >= self.log_every_s:
            self.last_log = now
            self.log_readings()

    @staticmethod
    def _grey(frame):
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        return g, float(cv2.resize(g, (32, 24), interpolation=cv2.INTER_AREA).mean())  # as CameraStats.brightness

    def _decide(self, i, s):
        n = len(s)
        if n < max(6, int(0.5 * self.window_s / self.every_s)):  # half a window seen before it says anything
            return
        share = {k: sum(1 for _, v in s if v == k) / n for k in NOTES}
        red = max(("dark", "bright"), key=lambda k: share[k])
        cur = self.raised[i]
        if share[red] >= RED_AT:
            new = red
        elif share["dark"] + share["dim"] >= RED_AT:  # mostly dim or worse: yellow
            new = "dim"
        elif cur is not None and (share[cur] if cur != "dim" else share["dark"] + share["dim"]) >= CLEAR_AT:
            new = cur  # not yet clearly better: keep it (no flicking between the two)
        else:
            new = None
        if new != cur:
            self.raised[i] = new
            name = self.names[i]
            if new is None:
                self.log.info("Light: %s is fine again (%s)", name, self._fmt(i))
            elif new == "dim":
                self.log.info("Light: %s is %s (%s): %s", name, NOTES[new][0], self._fmt(i), NOTES[new][1])
            else:
                self.log.warning("Light: %s is %s for a few minutes now (%s): %s", name, NOTES[new][0], self._fmt(i),
                                 NOTES[new][1])

    def _fmt(self, i):
        r = self.reading[i]
        if r is None:
            return "no reading"
        return f"brightness {r[0]:.0f}, grain " + ("measuring" if r[1] is None else f"{r[1]:.1f}")

    def log_readings(self):
        parts = [f"{n} {self._fmt(i)}" + (f" ({NOTES[self.raised[i]][0]})" if self.raised[i] else "")
                 for i, n in enumerate(self.names)]
        cost = (f" | check {np.mean(self.cost_ms):.1f} ms per camera, each every {self.every_s:g} s"
                if self.cost_ms else "")
        self.log.info("Light: %s%s", " | ".join(parts), cost)
        self.cost_ms = []

    def early(self, min_samples=3):
        """A first read, before the lasting verdict (which needs minutes): "dark" or "dim" when most of the cameras
        that have min_samples readings so far read that way in most of them, else None. For a one-time notice
        (1_capture), never for warnings."""
        votes = []
        for s in self.samples:
            if len(s) >= min_samples:
                v = [x for _, x in s]
                dark, dim = sum(x == "dark" for x in v), sum(x in ("dark", "dim") for x in v)
                votes.append("dark" if dark > len(v) / 2 else "dim" if dim > len(v) / 2 else None)
        if not votes or len(votes) < max(1, len(self.samples) // 2):
            return None
        for k in ("dark", "dim"):
            if sum(v is not None and (v == k or (k == "dim" and v == "dark")) for v in votes) > len(votes) / 2:
                return k
        return None

    def banner(self):
        """Lines for the tracker window (not VR), or ""."""
        lines = []
        for i, n in enumerate(self.names):
            k = self.raised[i]
            if k:
                what, do = NOTES[k]
                lines.append(f"{n}: {what.upper() if k != 'dim' else what}: {do}")
        return "\n".join(lines)
