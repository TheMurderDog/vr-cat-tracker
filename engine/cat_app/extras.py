"""The app's extra features on top of the tracker, kept apart from the hooks in bridge.py:
how much the tracking wobbles, the room heatmap, automatic training captures while it wobbles, and
the buzz strength. Plain Python + numpy, so they can be tested without the tracker.
"""

import json
import math
import time
from pathlib import Path

import numpy as np


class Wobble:
    """How much the cat's raw position (before the tracker's smoothing) jitters, in cm.

    Each detection compares its raw position with the straight line through the two before it (the
    second difference). Walking, even turning, keeps that small; a position that hops about from one
    detection to the next makes it large. Averaged over about `tau_s` so one bad detection doesn't
    count as a wobbly spot. Only horizontal (x, z): the height is the least reliable part anyway.
    """

    def __init__(self, tau_s=2.0, max_gap_s=0.8):
        self.tau, self.max_gap = tau_s, max_gap_s
        self.hist = []          # last two (t, x, z)
        self.value = 0.0        # smoothed wobble, cm
        self.last = None        # this detection's own wobble, cm (None if it couldn't be measured)
        self.t = None

    def update(self, X, now):
        """X: this detection's raw position (3,) or None. Returns the smoothed wobble in cm."""
        self.last = None
        if X is None:
            return self.value
        p = (now, float(X[0]), float(X[2]))
        if self.hist and now - self.hist[-1][0] > self.max_gap:
            self.hist = []
        if len(self.hist) == 2:
            (_, x0, z0), (_, x1, z1) = self.hist
            d2 = math.hypot(p[1] - 2 * x1 + x0, p[2] - 2 * z1 + z0)
            self.last = 100.0 * d2 / 2.0  # /2: a point off by e from the line gives a second difference of up to ~2e
            k = 1.0 if self.t is None else 1 - math.exp(-(now - self.t) / self.tau)
            self.value += k * (self.last - self.value)
            self.t = now
        self.hist = (self.hist + [p])[-2:]
        return self.value

    def reset(self):
        self.hist, self.value, self.last, self.t = [], 0.0, None, None


class Heatmap:
    """Where the cat spends time and where the tracking wobbles, on a grid over the floor (camera space,
    the same as the app's room map). Kept between tracker runs in my_data\\heatmap.json."""

    def __init__(self, path, cell_m=0.15):
        self.path = Path(path)
        self.cell = cell_m
        self.bounds = None
        self.time = self.wob = self.wn = None
        self.dirty = False
        self.last_save = time.monotonic()

    def set_bounds(self, b):
        b = [float(v) for v in b]
        if self.bounds == b:
            return
        old = self._load() if self.bounds is None else None
        self.bounds = b
        nx = max(1, int(math.ceil((b[1] - b[0]) / self.cell)))
        nz = max(1, int(math.ceil((b[3] - b[2]) / self.cell)))
        self.time = np.zeros((nz, nx), np.float32)
        self.wob = np.zeros((nz, nx), np.float32)
        self.wn = np.zeros((nz, nx), np.float32)
        if old and old.get("bounds") == b and old.get("cell") == self.cell:  # same room: carry on
            try:
                for k in ("time", "wob", "wn"):
                    a = np.asarray(old[k], np.float32)
                    if a.shape == self.time.shape:
                        getattr(self, k)[:] = a
            except (KeyError, ValueError, TypeError):
                pass

    def _ij(self, x, z):
        b = self.bounds
        i, j = int((z - b[2]) / self.cell), int((x - b[0]) / self.cell)
        if 0 <= i < self.time.shape[0] and 0 <= j < self.time.shape[1]:
            return i, j
        return None

    def add(self, pos, dt, wobble_cm=None):
        if self.bounds is None or pos is None:
            return
        ij = self._ij(pos[0], pos[2])
        if ij is None:
            return
        self.time[ij] += min(dt, 1.0)
        if wobble_cm is not None:
            self.wob[ij] += wobble_cm
            self.wn[ij] += 1
        self.dirty = True

    def report(self):
        """For the app: the grid as two lists of rows, each 0-1 (time: share of the busiest cell;
        wobble: average wobble in the cell divided by `scale_cm`), plus the numbers to draw it."""
        if self.bounds is None:
            return {"bounds": None}
        t = self.time.astype(float) / max(float(self.time.max()), 1e-6)
        w = np.where(self.wn >= 3, self.wob.astype(float) / np.maximum(self.wn, 1), 0.0)  # 3+ measurements before a cell counts
        return {"bounds": self.bounds, "cell": self.cell,
                "time": np.round(t, 2).tolist(), "wobble_cm": np.round(w, 1).tolist(),
                "seconds": float(self.time.sum())}

    def clear(self):
        if self.time is not None:
            self.time[:] = 0
            self.wob[:] = 0
            self.wn[:] = 0
        self.dirty = True
        self.save(force=True)

    def _load(self):
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def save(self, force=False):
        if self.bounds is None or not (self.dirty or force):
            return
        if not force and time.monotonic() - self.last_save < 60:
            return
        self.last_save = time.monotonic()
        self.dirty = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"bounds": self.bounds, "cell": self.cell, "time": self.time.tolist(),
                                       "wob": self.wob.tolist(), "wn": self.wn.tolist()}), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass


class AutoCapture:
    """Starts the tracker's own training capture (its c key) while the tracking wobbles, and stops it
    again once it settles, so the hard spots get into the next training round (label.bat checks them).
    It leaves a capture you started yourself alone."""

    def __init__(self, press):
        self.press = press      # press(key): sends a key to the tracker, e.g. "c"
        self.active = False     # a capture this started is running
        self.since = None       # wobbly since
        self.calm_since = None
        self.started = 0.0
        self.cooldown_until = 0.0
        self.count = 0

    def step(self, settings, wobble_cm, seen, capture_on, now):
        """Call at every detection. Returns "started", "stopped" or None."""
        ac = settings["auto_capture"]
        thr = float(ac["wobble_cm"])
        if self.active:
            if not capture_on:
                if now - self.started < 3.0:  # the tracker picks up the key on its next update
                    return None
                self.active = False  # stopped by hand (or the disk filled up)
                self.cooldown_until = now + 30
                return None
            calm = not seen or wobble_cm < 0.7 * thr
            self.calm_since = (self.calm_since or now) if calm else None
            if (self.calm_since is not None and now - self.calm_since >= 5.0) or now - self.started >= float(ac["max_s"]) \
                    or not ac["on"]:
                self.press("c")
                self.active = False
                self.cooldown_until = now + 30
                return "stopped"
            return None
        if not ac["on"] or capture_on or now < self.cooldown_until or self.count >= int(ac["max_per_run"]):
            self.since = None
            return None
        if seen and wobble_cm >= thr:
            self.since = self.since or now
            if now - self.since >= 1.5:
                self.press("c")
                self.active, self.started, self.calm_since, self.since = True, now, None, None
                self.count += 1
                return "started"
        else:
            self.since = None
        return None


# The "light to heavy" buzz: one step per distance band, both controllers at once (not the tracker's
# left-right pattern). Each step: (share of the chosen buzz strength, pulse seconds, pulses, gap seconds).
RISING_STEPS = {
    1: (0.35, 0.10, 1, 0.0),    # light: one short tap, it's still a little way off
    2: (0.65, 0.14, 2, 0.12),   # medium: a double tap, it's within the "moving" distance
    3: (1.00, 0.45, 1, 0.0),    # heavy: one long, full-strength buzz, it's underfoot
}


def rising_level(dist, underfoot_m, radius_m):
    """1 (light), 2 (medium) or 3 (heavy) for how close it is."""
    if dist is None:
        return 2
    if dist < underfoot_m:
        return 3
    if dist < max(radius_m, underfoot_m):
        return 2
    return 1


def rising_pulses(level, strength):
    """[(amplitude, seconds, pause after), ...] for one step."""
    share, secs, n, gap = RISING_STEPS[level]
    amp = max(0.08, min(1.0, strength * share))
    return [(amp, secs, gap)] * n


def snooze_icon(path):
    """A small, quiet "buzz muted" sign for the corner of your view: a bell with a line through it."""
    import cv2
    s = 128
    img = np.zeros((s, s, 4), np.uint8)
    col = (235, 235, 235, 255)
    cv2.ellipse(img, (64, 66), (34, 38), 0, 180, 360, col, -1, cv2.LINE_AA)  # dome
    pts = np.array([[30, 66], [98, 66], [108, 88], [20, 88]], np.int32)
    cv2.fillConvexPoly(img, pts, col, cv2.LINE_AA)
    cv2.circle(img, (64, 98), 9, col, -1, cv2.LINE_AA)  # clapper
    cv2.circle(img, (64, 26), 6, col, -1, cv2.LINE_AA)
    cv2.line(img, (22, 112), (108, 18), (0, 0, 0, 255), 16, cv2.LINE_AA)  # the line through it, with a dark edge
    cv2.line(img, (22, 112), (108, 18), (90, 90, 235, 255), 8, cv2.LINE_AA)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return str(path)
