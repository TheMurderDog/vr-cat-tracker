"""How often the tracker looks for the cat: the full rate (detector.rate_hz) or the slower idle rate
(detector.idle_rate_hz), which saves the GPU while the cat sleeps far from you.

The idle rate is used only when everything says the cat is settled: it's seen, it's slower than still_speed,
it hasn't moved more than wake_move_m since it settled, it's further than full_rate_within_m from you, and nothing
has asked for the full rate for full_rate_hold_s. Anything else goes back to the full rate at once:

- it starts moving, or has moved a little since it settled (one detection is enough, no waiting for its speed
  over the last second to build up)
- it's close to you, or the proximity warning is on
- it's "last seen" (often it's behind you or moving fast); a single look that didn't find it while it was shown
  gets one quick look again
- something was just found while nothing was shown (so a cat coming in is confirmed sooner)
- the position filter set aside a big jump (a fast cat, or a mistake: either way, look more often)
- the motion tripwire saw its spot change between idle looks (tripwire.py)

When unsure, it looks more often: that costs GPU time instead of a later look. The hold keeps it from flicking
between the two rates when its speed hovers around still_speed.
"""

import math


class DetectionRate:
    def __init__(self, dc, oc):
        self.fast = 1.0 / float(dc.get("rate_hz", 8))
        self.idle = 1.0 / float(dc.get("idle_rate_hz", 3))
        self.within = float(dc.get("full_rate_within_m", 3.0))
        self.hold = float(dc.get("full_rate_hold_s", 3.0))
        self.wake_move = float(dc.get("wake_move_m", 0.08))
        self.still_speed = float(oc.get("still_speed", 0.1))
        self.until = -1e9      # the full rate at least until then
        self.rest = None       # where it settled (x, z), while at the idle rate
        self.period = self.idle
        self.reason = "start"  # why the last switch to the full rate happened (for the log)
        self.switches = 0      # idle -> full switches, for the log

    @property
    def idle_now(self):
        return self.period == self.idle

    def _full(self, now, why, hold=None):
        if self.period != self.fast:
            self.switches += 1
            self.reason = why
        self.until = max(self.until, now + (self.hold if hold is None else hold))
        self.rest = None
        self.period = self.fast

    def woke(self, now):
        """The tripwire saw the cat's spot change between idle looks."""
        self._full(now, "tripwire")

    def update(self, now, state, pos, speed, dist, near, found, seen_once=False, jumped=False, raw=None):
        """After each detection. state: the track's "seen", "lost" or "hidden"; pos: its position (camera space)
        or None; speed: Motion.speed; dist: metres from you along the floor (None without VR); near: the
        proximity warning is on; found: this detection placed it; seen_once: something was found while nothing
        is shown yet (it's being confirmed); jumped: the filter set aside a big jump; raw: this detection's own
        position before the filter (the filter is smooth at rest, so it lags a slow start). Returns the period."""
        why, hold = None, None
        if state == "lost":
            why = "last seen"
        elif state == "seen" and not found:
            why, hold = "missed", 0.0  # one quick look again; a longer gap makes it "last seen" (above)
        elif state == "hidden" and (seen_once or found):
            why = "found"
        elif jumped:
            why = "jump"
        elif state == "seen":
            if near:
                why = "close"
            elif dist is not None and dist < self.within:
                why = "near you"
            elif speed > self.still_speed:
                why = "moving"
            elif self.rest is not None and any(
                    p is not None and math.hypot(p[0] - self.rest[0], p[2] - self.rest[1]) > self.wake_move
                    for p in (pos, raw)):
                why = "moved"
        if why is not None:
            self._full(now, why, hold)
            return self.period
        if now < self.until:
            return self.period
        self.period = self.idle
        if state == "seen" and pos is not None:
            if self.rest is None:
                self.rest = (float(pos[0]), float(pos[2]))
        else:
            self.rest = None
        return self.period
