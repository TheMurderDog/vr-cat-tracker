"""Keep the cameras' idea of SteamVR space lined up with SteamVR itself.

The cameras were calibrated into SteamVR standing space, but SteamVR's space can move afterwards
(by ~30 cm within days, in one setup). The headset is a free
reference: the cameras see your eyes and ears, SteamVR knows where the headset is, and the eyes
and ears sit at a fixed spot relative to the headset. So

    head joints (camera-triangulated) = headset position + headset rotation @ head_offset + shift

`shift` is how far camera space is from SteamVR space; subtract it from triangulated joints (or
add it to SteamVR poses before projecting them into cameras).
"""

import numpy as np

from pose.baseline import K

HEAD = [K[n] for n in ("left_eye", "right_eye", "left_ear", "right_ear")]


def head_point(J):
    """Mean of the seen eyes and ears (needs at least 2), or None."""
    h = J[HEAD]
    h = h[np.isfinite(h).all(axis=1)]
    return h.mean(axis=0) if len(h) >= 2 else None


def solve(head_pts, hmd, head_offset=None, iters=3, prior=None, prior_weight=0.3):
    """head_pts (N,3) camera-triangulated head points, hmd (N,4,4) headset poses at the same times.
    With head_offset given only the shift is solved; otherwise both (needs the head turned through
    a range of directions). If you only turn (yaw), the up-down part of the offset can't be told
    apart from the shift, so `prior` (a typical offset) holds it near that, with prior_weight per
    sample. Outliers (wrong person, headset off) are dropped. Returns
    (head_offset (3,), shift (3,), median residual m, samples kept)."""
    R, p = hmd[:, :3, :3], hmd[:, :3, 3]
    keep = np.ones(len(p), bool)
    o = np.asarray(head_offset, float) if head_offset is not None else None
    for _ in range(iters):
        if o is None:
            A = np.concatenate([R[keep], np.tile(np.eye(3), (keep.sum(), 1, 1))], axis=2).reshape(-1, 6)
            b = (head_pts[keep] - p[keep]).reshape(-1)
            if prior is not None:
                w8 = prior_weight * np.sqrt(keep.sum())
                A = np.vstack([A, np.hstack([w8 * np.eye(3), np.zeros((3, 3))])])
                b = np.concatenate([b, w8 * np.asarray(prior, float)])
            x, *_ = np.linalg.lstsq(A, b, rcond=None)
            oo, w = x[:3], x[3:]
        else:
            oo, w = o, np.median(head_pts[keep] - p[keep] - R[keep] @ o, axis=0)
        r = np.linalg.norm(head_pts - p - R @ oo - w, axis=1)
        keep = r < max(3 * np.median(r[keep]), 0.03)
    if o is None:
        o = oo
    return o, w, float(np.median(r[keep])), int(keep.sum())


class LiveShift:
    """The same, during live tracking: a running estimate from recent frames with the headset on
    and the head seen. Starts from the configured shift; `update` returns the current one."""

    def __init__(self, head_offset, shift, need=200, max_dev=0.6):
        self.o = np.asarray(head_offset, float)
        self.shift = np.asarray(shift, float)
        self.need, self.max_dev = need, max_dev
        self.samples = []

    def add(self, head_pt, hmd):
        """One frame. Returns the implied shift, or None if this frame is unusable."""
        if head_pt is None or hmd is None:
            return None
        w = head_pt - hmd[:3, 3] - hmd[:3, :3] @ self.o
        if np.linalg.norm(w - self.shift) > self.max_dev:  # headset not on the head, or wrong person
            return None
        self.samples.append(w)
        del self.samples[:-2000]
        return w

    def estimate(self, last=None):
        s = np.array(self.samples[-(last or self.need):])
        return np.median(s, axis=0) if len(s) else None
