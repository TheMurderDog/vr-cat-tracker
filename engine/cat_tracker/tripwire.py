"""A cheap motion tripwire for the cat's spot while the tracker is at its idle rate.

While the cat is still, the detector runs only a few times a second (it's mostly asleep, and that saves the GPU).
A cat that bolts would then go unseen for up to one idle interval. So between detections, each camera's picture
around the cat's last box is compared with how it looked at the last detection, on a tiny grey copy (averaging
hundreds of pixels per cell makes sensor noise and the light's flicker vanish). When it changes, the detector is
run at once. A person walking past or a light switched on wakes it too: that only costs one extra detection.
"""

import cv2
import numpy as np

CELLS = 16           # the spot is compared as CELLS x CELLS averages
GROW = 1.6           # around the cat's last box, this much bigger (it can leave the box quickly)
CHANGE = 6.0         # mean absolute change (grey levels, 0-255) over the cells that counts as movement


def _crop(frame, box, w, h):
    x1, y1, x2, y2 = box[:4]
    cx, cy, bw, bh = (x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) * GROW, (y2 - y1) * GROW
    bw, bh = max(bw, 48), max(bh, 48)
    a, b = int(max(cx - bw / 2, 0)), int(max(cy - bh / 2, 0))
    c, d = int(min(cx + bw / 2, w)), int(min(cy + bh / 2, h))
    if c - a < 8 or d - b < 8:
        return None
    g = frame[b:d, a:c]
    if g.ndim == 3:
        g = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, (CELLS, CELLS), interpolation=cv2.INTER_AREA).astype(np.float32), (a, b, c, d)


class Tripwire:
    def __init__(self, change=CHANGE):
        self.change = float(change)
        self.refs = []   # per camera: (cells, region) at the last detection, or None
        self.wakes = 0

    def set(self, frames, boxes):
        """At a detection: the cat's box in each camera (None where it wasn't seen) and the pictures."""
        self.refs = []
        for f, b in zip(frames, boxes):
            if f is None or b is None:
                self.refs.append(None)
                continue
            h, w = f.shape[:2]
            got = _crop(f, b, w, h)
            self.refs.append(got)

    def changed(self, frames):
        """True when the cat's spot looks different in any camera now: run the detector."""
        for f, ref in zip(frames, self.refs):
            if f is None or ref is None:
                continue
            cells, (a, b, c, d) = ref
            g = f[b:d, a:c]
            if g.ndim == 3:
                g = cv2.cvtColor(g, cv2.COLOR_BGR2GRAY)
            now = cv2.resize(g, (CELLS, CELLS), interpolation=cv2.INTER_AREA).astype(np.float32)
            diff = np.abs(now - cells)
            diff -= np.median(diff)  # the whole spot brighter or darker (exposure, a light): not movement
            if float(np.mean(np.abs(diff))) >= self.change:
                self.wakes += 1
                return True
        return False
