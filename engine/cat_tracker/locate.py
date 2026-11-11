"""From per-camera cat boxes to one 3D position in calibration (camera) space, and keeping it steady.

Two or more cameras: the box centres are triangulated with the camera core's Rig, which drops a view that
disagrees (usually a false hit). One camera: it is almost always on the floor, so the ray through
the bottom middle of its box is met with the floor plane. Anything outside the room or higher than
furniture (pictures on the walls) is thrown out first.
"""

import cv2
import numpy as np

from calibration import intrinsics as intr

from fusion.filters import JumpGate, OneEuro
from fusion.triangulate import triangulate


def floor_point(rig, c, px, floor_y):
    """Where the ray through pixel px of camera c meets the plane y = floor_y, or None."""
    xy = rig.normalize(c, np.array([px], np.float64))[0]
    R, t = rig.P[c][:, :3], rig.P[c][:, 3]
    centre = -R.T @ t
    d = R.T @ np.array([xy[0], xy[1], 1.0])
    if abs(d[1]) < 1e-6:
        return None
    s = (floor_y - centre[1]) / d[1]
    return centre + s * d if s > 0 else None


PARTIAL = {"checked": 0, "down": 0}  # moments with 3+ views, and views down-weighted (for the tracker's log line)


def expected_area(rig, c, X, radius=0.22, half_h=0.15):
    """About how many pixels a cat at X covers in camera c: its outline (a cylinder) projected, scaled by the
    1.21 x 1.31 it's too big on average against real boxes (measured on hand-checked labels). Lens distortion is
    left out: this is only a size check. None if it's behind the camera."""
    a = np.linspace(0, 2 * np.pi, 16, endpoint=False)
    ring = np.stack([X[0] + radius * np.cos(a), np.zeros_like(a), X[2] + radius * np.sin(a)], axis=1)
    pts = np.vstack([ring + [0, X[1] - half_h, 0], ring + [0, X[1] + half_h, 0]])
    xy, depth = rig.project_norm(c, pts)
    if (depth <= 0.1).any():
        return None
    w, h = (xy.max(axis=0) - xy.min(axis=0)) * rig.fx[c]
    return (w / 1.21) * (h / 1.31)


def partial_weights(rig, picked, views, lc):
    """With 3+ cameras seeing it: a camera whose box is much smaller than a cat at the position the others give
    (under partial_ratio of it: furniture or the picture edge hides part of it) counts less in the triangulation,
    by the square of that ratio. Its box centre isn't the cat's centre, and pulled the position by about 4 cm in a
    test on the furnished old test setup (one camera's box cut to a 30-45% slice: 4.1 -> 0.8 cm, 3.4 -> 0.9 cm).
    With only 2 cameras it's left alone: there it helped as often as it hurt."""
    thr = float(lc.get("partial_ratio", 0.6))
    have = [c for c, v in enumerate(views) if v is not None]
    if thr <= 0 or len(have) < 3:
        return views
    PARTIAL["checked"] += 1
    out = list(views)
    for c in have:
        others = [v if k != c else None for k, v in enumerate(views)]
        pts, _, _, _ = triangulate(rig, others, 0.0, float(lc.get("max_reprojection_px", 40)), 2, n_k=1)
        if not np.isfinite(pts[0]).all():
            continue
        a = expected_area(rig, c, pts[0])
        b = picked[c]
        if not a:
            continue
        r = (b[2] - b[0]) * (b[3] - b[1]) / a
        if r < thr:
            out[c] = (views[c][0], views[c][1] * max(r, 0.05) ** 2)
            PARTIAL["down"] += 1
    return out


def room_bounds(rig, margin):
    """Floor area (x min, x max, z min, z max) the cat can be in: the cameras sit on the four walls,
    so the box around them, plus a margin, is the room."""
    centres = np.array([-P[:, :3].T @ P[:, 3] for P in rig.P])
    return (centres[:, 0].min() - margin, centres[:, 0].max() + margin,
            centres[:, 2].min() - margin, centres[:, 2].max() + margin)


def _inside(X, bounds):
    return X is not None and bounds[0] <= X[0] <= bounds[1] and bounds[2] <= X[2] <= bounds[3]


def _foot(rig, c, b, floor_y):
    return floor_point(rig, c, ((b[0] + b[2]) / 2, b[3]), floor_y)


def locate(rig, boxes_all, lc, bounds):
    """boxes_all: per camera an (n, 5) array of [x1, y1, x2, y2, score], best first.
    A box only counts if the floor under it is inside the room: a painting or a poster on a wall
    projects to the floor beyond that wall. Returns (position (3,), cameras used,
    "triangulated" | "floor" | None, the box used per camera or None)."""
    floor_y = float(lc.get("floor_y_m", 0.0))
    max_h = float(lc.get("max_height_m", 0.0))  # 0: no upper limit
    picked = [next((b for b in boxes if _inside(_foot(rig, c, b, floor_y), bounds)), None)
              for c, boxes in enumerate(boxes_all)]
    views = [None if b is None else (np.array([[(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]]), np.array([b[4]]))
             for b in picked]
    if sum(v is not None for v in views) >= int(lc.get("min_views", 2)):
        views = partial_weights(rig, picked, views, lc)
        pts, _, used, _ = triangulate(rig, views, 0.0, float(lc.get("max_reprojection_px", 40)),
                                      int(lc.get("min_views", 2)), n_k=1)
        X = pts[0]
        if np.isfinite(X).all() and _inside(X, bounds) and floor_y - 0.2 <= X[1] and (max_h <= 0 or X[1] <= floor_y + max_h):
            return X, int(used[0]), "triangulated", picked
    seen = [c for c, b in enumerate(picked) if b is not None]
    if not seen:
        return None, 0, None, picked
    c = max(seen, key=lambda k: picked[k][4])
    X = _foot(rig, c, picked[c], floor_y)
    # the bottom of its box is its near edge; its middle is a little further from the camera
    P = rig.P[c]
    away = X - (-P[:, :3].T @ P[:, 3])
    away[1] = 0.0
    X += float(lc.get("floor_depth_m", 0.2)) * away / max(np.linalg.norm(away), 1e-6)
    X[1] += float(lc.get("body_height_m", 0.15))
    return X, 1, "floor", [b if k == c else None for k, b in enumerate(picked)]


def outline_box(room_cam, I, X, radius, half_h, w, h):
    """Pixel box around a vertical cylinder at X as camera c sees it, or None if it's out of view."""
    a = np.linspace(0, 2 * np.pi, 16, endpoint=False)
    ring = np.stack([X[0] + radius * np.cos(a), np.zeros_like(a), X[2] + radius * np.sin(a)], axis=1)
    pts = np.vstack([ring + [0, X[1] - half_h, 0], ring + [0, X[1] + half_h, 0]])
    R, _ = cv2.Rodrigues(np.array(room_cam["rvec"], np.float64))
    if ((pts @ R.T + np.array(room_cam["tvec"]))[:, 2] <= 0.1).any():  # behind the camera
        return None
    p = intr.project(pts, np.array(room_cam["rvec"]), np.array(room_cam["tvec"]), I).reshape(-1, 2)
    x1, y1 = p.min(axis=0)
    x2, y2 = p.max(axis=0)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    if not (0 <= cx < w and 0 <= cy < h):
        return None
    return [max(x1, 0), max(y1, 0), min(x2, w - 1), min(y2, h - 1)]


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / max((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter, 1e-9)


def weak_matches(room, intrinsics, boxes_all, picked, X, lc, w, h):
    """For each camera with no confident box: its weak box (if any) overlapping its outline as
    projected from position X, else None. Lets a camera that half-sees its help instead of flicker."""
    out = [None] * len(boxes_all)
    radius, half_h = float(lc.get("outline_radius_m", 0.22)), float(lc.get("outline_half_height_m", 0.15))
    for c, boxes in enumerate(boxes_all):
        if picked[c] is not None or not len(boxes):
            continue
        guess = outline_box(room["cameras"][c], intrinsics[c], X, radius, half_h, w, h)
        if guess is None:
            continue
        near = [b for b in boxes if iou(b, guess) >= float(lc.get("weak_iou", 0.3))]
        if near:
            out[c] = near[0]
    return out


class CatTrack:
    """Turns noisy detections into what to show: hidden, seen (confirmed, filtered position) or
    lost (last seen position, dimming), with the brightness to show it at."""

    def __init__(self, fc, lost_alpha=0.6):
        self.fc = fc
        self.lost_alpha = lost_alpha
        self.confirm = int(fc.get("confirm_frames", 3))
        self.lost_after = float(fc.get("lost_after_s", 0.6))
        self.fade = float(fc.get("fade_s", 8.0))
        self._reset()

    def _reset(self):
        fc = self.fc
        self.filt = OneEuro(float(fc.get("min_cutoff", 1.0)), float(fc.get("beta", 0.8)), float(fc.get("d_cutoff", 1.0)))
        self.gate = JumpGate(float(fc.get("max_jump_m", 1.0)), int(fc.get("jump_accept_after", 3)))
        self.pos = None
        self.streak = 0
        self.last_seen = None
        self.state = "hidden"

    def update(self, X, now):
        """X: this detection's position or None. Returns (position or None, state, alpha 0-1)."""
        if X is not None:
            X = self.gate(np.asarray(X, np.float64)[None])[0]
        if X is not None and np.isfinite(X).all():
            self.streak += 1
            self.pos = self.filt(X[None], now)[0]
            if self.streak >= self.confirm or self.state != "hidden":
                self.state, self.last_seen = "seen", now
        else:
            self.streak = 0
        if self.state == "hidden":
            return None, "hidden", 0.0
        gone = now - self.last_seen
        if gone <= self.lost_after:
            return self.pos, "seen", 1.0
        if gone > self.lost_after + self.fade:
            self._reset()
            return None, "hidden", 0.0
        self.state = "lost"
        return self.pos, "lost", self.lost_alpha * (1 - (gone - self.lost_after) / self.fade)
