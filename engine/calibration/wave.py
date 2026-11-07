"""Pick the SteamVR device on the marker card by waving it: the one that moved the most, by a clear margin, wins.

Pure logic (no SteamVR here), so it can be tested: calib_room samples every device's position for a few seconds,
then calls choose().
"""

import numpy as np

PICKABLE = ("tracker", "controller")  # the headset and base stations are never the card's device
MIN_PATH_M = 0.4   # the winner must have moved at least this far in total (a real wave, not hand tremor)
CLEAR_RATIO = 2.0  # ...and at least this many times further than the next device


def path_length(positions):
    """Total distance travelled along a list of positions (None = not tracked at that moment, skipped)."""
    pts = [np.asarray(p, float) for p in positions if p is not None]
    return float(sum(np.linalg.norm(b - a) for a, b in zip(pts, pts[1:])))


def choose(tracks, min_path_m=MIN_PATH_M, ratio=CLEAR_RATIO):
    """tracks: {device: (kind, [positions])}. Returns (device, None) for a clear winner, else (None, why) with why
    "none" (nothing moved enough) or "tie" (two moved about the same). Headsets and base stations are ignored."""
    lengths = sorted(((path_length(pos), dev) for dev, (kind, pos) in tracks.items() if kind in PICKABLE),
                     key=lambda x: x[0], reverse=True)
    if not lengths or lengths[0][0] < min_path_m:
        return None, "none"
    if len(lengths) > 1 and lengths[0][0] < ratio * lengths[1][0]:
        return None, "tie"
    return lengths[0][1], None
