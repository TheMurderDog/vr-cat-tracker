"""Stick-aware play-space anchor for the VRChat avatar (experimental, off unless vrchat.stick_anchor.enabled).

Without it, CatAhead / CatRight are measured from the live headset, so the avatar redraws the cat from your
head every update, and small head-tracking errors show up as the cat swinging a little when you look around.

With it, the tracker works out when your VRChat play space is standing still and sends the cat's position
measured from one fixed headset pose (the "stamp") instead. The avatar freezes a point in the world at that
moment and draws the cat from it, so turning your head or walking around for real doesn't move that point.

  head mode   a thumbstick is pushed (VRChat moves or turns you), a button is pressed (A/B/X/Y, trigger,
              menu: grabbing the play space, a menu, anything; not the grip, where many hands rest, or a
              trackpad), or SteamVR's play space moves. The cat is measured
              from the live headset, as without this feature. So you decide when it lets go.
  settling    the sticks were let go: wait settle_s, then for the headset to be steady (turning slower than
              still_turn_dps and moving slower than still_move_mps) for average_s. No time limit: if it
              doesn't get steady, it stays in head mode.
  anchored    the stamp is the headset's average pose over that steady moment, flat on the floor.
              CatAnchorMode is true and every offset is measured from the stamp.

Someone who joins the instance while you're anchored picks up the anchor at your next stick push (or set
refresh_s to re-anchor every so often while you stand still; each re-anchor can shift the cat slightly).
VRChat teleports, seats and moving platforms move you without a button or stick, so it can't see them; the
next press fixes the anchor.
"""

import collections
import math

import numpy as np

DEFAULTS = {
    "enabled": False,
    "stick_deadzone": 0.2,     # a stick counts as pushed past this (0..1); a pressed button counts as 1
    "stick_min_s": 0.1,        # pushed at least this long, so a brushed stick doesn't count
    "settle_s": 0.3,           # after the sticks are let go, before looking for a steady head
    "still_turn_dps": 15.0,    # steady: headset turning slower than this (degrees a second)...
    "still_move_mps": 0.15,    # ...and moving slower than this (metres a second, along the floor)
    "average_s": 0.5,          # steady this long; the anchor is the average pose over it
    "refresh_s": 0.0,          # while anchored and steady, re-anchor this often (0 = off)
    "playspace_move_m": 0.03,  # SteamVR's play space moved more than this (OVR Advanced Settings and the like)...
    "playspace_turn_deg": 1.0,  # ...or turned more than this, counts as moving (0 = off)
    "lost_sticks_s": 1.0,      # sticks unreadable this long (controller off, SteamVR Input gone): head mode
}


def flat_pose(x, z, yaw_deg, y=0.0):
    """4x4 pose at (x, y, z) facing yaw (degrees clockwise from above, 0 = facing -z), no tilt."""
    a = math.radians(yaw_deg)
    fwd = np.array([math.sin(a), 0.0, -math.cos(a)])
    T = np.eye(4)
    T[:3, 2] = -fwd  # OpenVR: a pose looks down its -z
    T[:3, 1] = [0.0, 1.0, 0.0]
    T[:3, 0] = np.cross(T[:3, 1], T[:3, 2])
    T[:3, 3] = [x, y, z]
    return T


def yaw_of(T):
    """Heading of a pose in degrees (clockwise from above, 0 = facing -z), or None looking straight up/down."""
    f = -T[:3, 2]
    if math.hypot(f[0], f[2]) < 1e-6:
        return None
    return math.degrees(math.atan2(f[0], -f[2]))


def _wrap(d):
    return (d + 180.0) % 360.0 - 180.0


class StickAnchor:
    """Decides head mode or anchored, from the sticks and the headset. update() once per OSC send."""

    def __init__(self, cfg=None, log=None):
        c = dict(DEFAULTS)
        c.update(cfg or {})
        self.c, self.log = c, log
        self.enabled = bool(c["enabled"])
        self.stamp = None              # 4x4 raw-space pose the cat is measured from while anchored
        self.anchored_at = None
        self.last_move = None          # when it last counted as moving
        self.pushed_since = None       # when the sticks went past the deadzone
        self.steady = []               # (t, x, z, yaw) while steady, for the average
        self.hist = collections.deque()  # recent (t, x, z, yaw) for the head speed
        self.last_M = None
        self.refreshing = False
        self.lost_since = None         # when the sticks stopped being readable

    @property
    def anchored(self):
        return self.stamp is not None

    def _say(self, msg, *a):
        if self.log is not None:
            self.log.info("Stick anchor: " + msg, *a)

    def _drop(self, now, why, *a):
        if self.stamp is not None:
            self._say("head mode (" + why + ")", *a)
        self.stamp = None
        self.anchored_at = None
        self.last_move = now
        self.steady = []

    def _speed(self, now, x, z, yaw):
        """(m/s, deg/s) over about the last 0.1 s, or None until there's enough history."""
        self.hist.append((now, x, z, yaw))
        while len(self.hist) > 2 and now - self.hist[1][0] >= 0.1:
            self.hist.popleft()
        t0, x0, z0, y0 = self.hist[0]
        dt = now - t0
        if dt < 0.05:
            return None
        return math.hypot(x - x0, z - z0) / dt, abs(_wrap(yaw - y0)) / dt

    def update(self, now, hmd_raw, stick, raw_to_standing=None):
        """now: seconds; hmd_raw: 4x4 headset pose in raw space or None; stick: the larger thumbstick
        push 0..1 (1 while a button is pressed), or None when the controllers can't be read; raw_to_standing: SteamVR's current 4x4.
        Returns the stamp (4x4, raw space) while anchored, else None."""
        if not self.enabled:
            return None
        if stick is None:  # can't see the sticks: after a moment, anchoring could hold the cat still while VRChat moves you
            if self.lost_since is None:
                self.lost_since = now
            if now - self.lost_since >= float(self.c["lost_sticks_s"]):
                self._drop(now, "can't read the thumbsticks")
                return None
            return self.stamp
        self.lost_since = None
        if self.last_move is None:
            self.last_move = now

        # moving: a stick held past the deadzone, or SteamVR's play space shifted (OVR Advanced Settings etc.)
        pushed = stick > float(self.c["stick_deadzone"])
        if pushed:
            if self.pushed_since is None:
                self.pushed_since = now
        else:
            self.pushed_since = None
        if pushed and now - self.pushed_since >= float(self.c["stick_min_s"]):
            self._drop(now, "stick or button %.2f", stick)
        pm, pt = float(self.c["playspace_move_m"]), float(self.c["playspace_turn_deg"])
        if raw_to_standing is not None and (pm > 0 or pt > 0):
            # measured from where it last stood, so slow drags add up and tracking noise doesn't
            if self.last_M is None:
                self.last_M = np.array(raw_to_standing, float)
            d = np.linalg.norm(raw_to_standing[:3, 3] - self.last_M[:3, 3])
            r = self.last_M[:3, :3].T @ raw_to_standing[:3, :3]
            ang = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(r) - 1) / 2))))
            if (pm > 0 and d > pm) or (pt > 0 and ang > pt):
                self._drop(now, "play space moved %.2f m, %.1f deg", d, ang)
                self.last_M = np.array(raw_to_standing, float)

        if hmd_raw is None:
            self.steady = []
            return self.stamp
        yaw = yaw_of(hmd_raw)
        if yaw is None:
            self.steady = []
            return self.stamp
        x, z = float(hmd_raw[0, 3]), float(hmd_raw[2, 3])
        sp = self._speed(now, x, z, yaw)
        still = sp is not None and sp[0] < float(self.c["still_move_mps"]) and sp[1] < float(self.c["still_turn_dps"])

        if self.stamp is not None:  # anchored: walking and turning for real is fine; only refresh when steady
            rs = float(self.c["refresh_s"])
            if rs > 0 and still and now - self.anchored_at >= rs:
                self._drop(now, "refresh")
                self.refreshing = True
            return self.stamp

        if now - self.last_move < float(self.c["settle_s"]) or pushed:
            self.steady = []
            return None
        if not still:
            self.steady = []
            return None
        self.steady.append((now, x, z, yaw))
        if now - self.steady[0][0] < float(self.c["average_s"]):
            return None
        xs = np.mean([s[1] for s in self.steady])
        zs = np.mean([s[2] for s in self.steady])
        a = np.radians([s[3] for s in self.steady])
        ya = math.degrees(math.atan2(np.mean(np.sin(a)), np.mean(np.cos(a))))
        self.stamp = flat_pose(xs, zs, ya, float(hmd_raw[1, 3]))
        self.anchored_at = now
        self._say("anchored%s after %.1f s (head %.2f m/s, %.0f deg/s)",
                  " again" if self.refreshing else "", now - self.last_move, sp[0], sp[1])
        self.refreshing = False
        self.steady = []
        return self.stamp
