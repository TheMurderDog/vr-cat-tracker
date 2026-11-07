"""When to warn you about it, and how it's moving.

Motion follows its speed from the tracked position, so the marker can show a resting or a moving cat.
Proximity decides the warning: always when it's underfoot, earlier when it (or you) is closing in
fast, and not at all when it's napping a little way off and neither of you is moving toward the other.
"""

import collections
import math

import numpy as np


class Motion:
    """Its horizontal speed (m/s) and how long it has been still. Speed is how far it got over the
    last speed_window_s, so the few-cm jitter of a sleeping cat's position doesn't read as moving."""

    def __init__(self, oc):
        self.window = float(oc.get("speed_window_s", 1.0))
        self.still_speed = float(oc.get("still_speed", 0.08))
        self.hist = collections.deque()
        self.speed = 0.0
        self.still_since = None
        self.moving = False
        self.flip_since = None

    def update(self, pos, now):
        """pos: its filtered position (camera space, metres) at a detection, or None when it isn't seen."""
        if pos is None:
            self.hist.clear()
            self.speed, self.still_since = 0.0, None
            self.moving, self.flip_since = False, None
            return
        self.hist.append((now, float(pos[0]), float(pos[2])))
        while len(self.hist) > 2 and now - self.hist[1][0] >= self.window:
            self.hist.popleft()
        t0, x0, z0 = self.hist[0]
        self.speed = math.hypot(pos[0] - x0, pos[2] - z0) / (now - t0) if now - t0 > 0.1 else 0.0
        if self.speed > self.still_speed:
            self.still_since = None
        elif self.still_since is None:
            self.still_since = now

    def still_for(self, now):
        return 0.0 if self.still_since is None else now - self.still_since

    def kind(self, now, oc):
        """"rest", "move" or "normal", for the icon and CatState. Moving has two thresholds and needs a
        moment above or below them, so position jitter around one speed can't flip it on and off."""
        enter, leave = float(oc.get("move_speed", 0.2)), float(oc.get("move_stop_speed", 0.12))
        fast = self.speed >= (leave if self.moving else enter)
        if fast != self.moving:
            if self.flip_since is None:
                self.flip_since = now
            if now - self.flip_since >= float(oc.get("move_stop_s" if self.moving else "move_start_s",
                                                     1.0 if self.moving else 0.4)):
                self.moving, self.flip_since = fast, None
        else:
            self.flip_since = None
        if self.moving:
            return "move"
        if self.still_for(now) >= float(oc.get("rest_after_s", 120.0)):
            return "rest"
        return "normal"


class Heading:
    """Which way it's going on the floor, from its movement: degrees clockwise seen from above, 0 facing
    -z (the same as osc.room_head). It compares where it was at the start of the last window_s with
    where it is now, each the average of a few detections so jitter cancels out, and only turns once
    it has covered min_move_m; then it eases toward the new direction (smooth_s) instead of snapping.
    Separate from Motion's moving state, so a slow walk turns it too. When it stops it keeps its last
    heading."""

    def __init__(self, oc):
        self.window = float(oc.get("heading_window_s", 1.5))
        self.min_move = float(oc.get("heading_min_move_m", 0.08))
        self.tau = float(oc.get("heading_smooth_s", 0.3))
        self.hist = collections.deque()
        self.yaw = None
        self.t = None

    def update(self, pos, now, gone=False):
        """pos: its position at this detection while it's seen, else None; gone: it's hidden for good
        (the next sighting starts a fresh heading)."""
        if gone:
            self.hist.clear()
            self.yaw = self.t = None
            return
        if pos is None:
            return
        self.hist.append((now, float(pos[0]), float(pos[2])))
        while len(self.hist) > 2 and now - self.hist[1][0] >= self.window:
            self.hist.popleft()
        if self.t is None:
            self.t = now
        if len(self.hist) < 4 or now - self.hist[0][0] < 0.5 * self.window:
            self.t = now
            return
        k = max(1, len(self.hist) // 3)
        a = np.mean([(x, z) for _, x, z in list(self.hist)[:k]], axis=0)
        b = np.mean([(x, z) for _, x, z in list(self.hist)[-k:]], axis=0)
        dx, dz = b - a
        if math.hypot(dx, dz) < self.min_move:
            self.t = now
            return
        target = math.degrees(math.atan2(dx, -dz))
        if self.yaw is None:
            self.yaw = target
        else:
            turn = (target - self.yaw + 180.0) % 360.0 - 180.0
            self.yaw += (1 - math.exp(-(now - self.t) / self.tau)) * turn
            self.yaw = (self.yaw + 180.0) % 360.0 - 180.0
        self.t = now


class Smoother:
    """Eases the shown position toward its newest detection at every update (30 a second), so it
    marker and the snake glide between detections instead of stepping. A big jump is taken at once."""

    def __init__(self, tau_s=0.15, jump_m=1.0):
        self.tau, self.jump = tau_s, jump_m
        self.pos = None
        self.t = None

    def __call__(self, target, now):
        if target is None:
            self.pos = None
            return None
        target = np.asarray(target, float)
        if self.pos is None or np.linalg.norm(target - self.pos) > self.jump:
            self.pos = target.copy()
        else:
            self.pos += (1 - math.exp(-(now - self.t) / self.tau)) * (target - self.pos)
        self.t = now
        return self.pos.copy()


class Proximity:
    """None, "near" (show the arrow and the close icon) or "underfoot" (that, plus a buzz)."""

    def __init__(self, al):
        self.radius = float(al.get("radius_m", 1.0))
        self.underfoot = float(al.get("underfoot_m", 0.5))
        self.ttc = float(al.get("ttc_s", 1.5))
        self.max_warn = float(al.get("max_warn_m", 3.0))
        self.min_closing = float(al.get("min_closing_speed", 0.2))
        self.still_speed = float(al.get("still_speed", 0.15))
        self.smooth = float(al.get("closing_smooth_s", 0.4))
        self.closing = 0.0
        self.sample = None

    def reset(self):
        self.closing, self.sample = 0.0, None

    def update(self, dist, cat_speed, now):
        """dist: horizontal distance from your headset to it (m); cat_speed from Motion."""
        if self.sample is None:
            self.sample = (now, dist)
        elif now - self.sample[0] >= 0.2:  # its position steps at the detection rate, so measure over a little while
            t0, d0 = self.sample
            rate = (d0 - dist) / (now - t0)  # positive while the gap shrinks, whoever is moving
            self.closing += (now - t0) / (self.smooth + now - t0) * (rate - self.closing)
            self.sample = (now, dist)
        if dist < self.underfoot:
            return "underfoot"
        if dist < self.max_warn and self.closing > self.min_closing and dist / self.closing < self.ttc:
            return "near"
        if dist < self.radius and cat_speed > self.still_speed:
            return "near"
        return None
