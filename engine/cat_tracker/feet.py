"""Measuring the cat's distance from your feet, not only your head.

With SteamVR foot trackers assigned (the app's "Assign foot trackers": sit down and wave one foot at a time), the
warnings and the distance you see use whichever is closest to the cat: either foot, or the headset. The headset
stays in the comparison, so adding foot trackers can only shorten the distance, not lengthen it. A foot tracker
that is switched off or not tracking is left out until it's back.

The trackers are remembered by serial number in my_data/tracker/feet.json (SteamVR's device numbers change between
starts). The file is re-read when it changes, so assigning feet in the app applies straight away.
"""

import json
import time

import numpy as np

from core.config import resolve_path

FEET_FILE = resolve_path("my_data/tracker/feet.json")
SIDES = ("left", "right")


def load(path=None):
    """{"left": serial, "right": serial} (either may be missing) from feet.json, or {}."""
    try:
        data = json.loads((path or FEET_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {s: str(data[s]) for s in SIDES if isinstance(data, dict) and data.get(s)}


def save(feet, path=None):
    """Writes feet.json ({"left": serial, "right": serial}); an empty dict forgets them."""
    path = path or FEET_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({s: feet[s] for s in SIDES if feet.get(s)}, indent=2), encoding="utf-8")
    tmp.replace(path)


def closest(cat, points):
    """cat: its position; points: {name: position} (same space, metres). Returns (horizontal distance, name) of the
    nearest point, or (None, None) with no points."""
    best = (None, None)
    for name, q in points.items():
        d = float(np.hypot(cat[0] - q[0], cat[2] - q[2]))
        if best[0] is None or d < best[0]:
            best = (d, name)
    return best


class Feet:
    """Follows the assigned foot trackers. positions(vr) gives each tracked foot's position in raw space."""

    def __init__(self, path=None, recheck_s=3.0):
        self.path = path or FEET_FILE
        self.recheck_s = recheck_s
        self.serials = {}
        self.index = {}       # side -> SteamVR device number, while it's connected
        self.mtime = None
        self.next_check = 0.0
        self.tracked = []     # sides tracked in the last positions() call

    def _reload(self):
        try:
            m = self.path.stat().st_mtime
        except OSError:
            m = None
        if m != self.mtime:
            self.mtime = m
            self.serials = load(self.path)
            self.index = {}
            self.next_check = 0.0

    def positions(self, vr, now=None):
        """{"left foot": xyz, "right foot": xyz} in raw space, for the feet that are tracking right now."""
        now = time.monotonic() if now is None else now
        if now >= self.next_check:
            self.next_check = now + self.recheck_s
            self._reload()
            if self.serials:
                self.index = vr.find_serials(self.serials)
        self.tracked = []
        if not self.index:
            return {}
        pos = vr.device_positions(list(self.index.values()))
        out = {}
        for side, i in self.index.items():
            p = pos.get(i)
            if p is not None:
                out[f"{side} foot"] = p
                self.tracked.append(side)
        return out
