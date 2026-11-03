"""Confidence-weighted multi-camera triangulation of 2D keypoints into SteamVR standing space.

Camera poses come from calibration/data/room.json (rvec/tvec map SteamVR points into each camera)
and lens models from intrinsics_<name>.json. Keypoints are undistorted to normalized image
coordinates first, so the fisheye lenses don't bend the rays.
"""

import cv2
import numpy as np

from calibration import intrinsics as intr


class Rig:
    def __init__(self, room, intrinsics):
        self.intr = intrinsics
        self.P = []
        self.fx = []
        for cam, I in zip(room["cameras"], intrinsics):
            R, _ = cv2.Rodrigues(np.array(cam["rvec"], np.float64))
            self.P.append(np.hstack([R, np.array(cam["tvec"], np.float64).reshape(3, 1)]))
            self.fx.append(float(I["K"][0, 0]))
        self.P = np.array(self.P)  # (cams, 3, 4)
        self.fx = np.array(self.fx)

    def normalize(self, c, kp):
        return intr.undistort_points(kp, self.intr[c])

    def project_norm(self, c, X):
        """Normalized image coordinates of VR-space points (N,3) in camera c, and their depth."""
        Xh = np.hstack([X, np.ones((len(X), 1))])
        pc = Xh @ self.P[c].T
        return pc[:, :2] / pc[:, 2:3], pc[:, 2]


def _dlt(P, xy, w):
    """Weighted DLT for one point. P (n,3,4), xy (n,2) normalized, w (n,)."""
    A = np.empty((2 * len(P), 4))
    A[0::2] = w[:, None] * (xy[:, 0:1] * P[:, 2] - P[:, 0])
    A[1::2] = w[:, None] * (xy[:, 1:2] * P[:, 2] - P[:, 1])
    _, _, vt = np.linalg.svd(A)
    X = vt[-1]
    return X[:3] / X[3] if abs(X[3]) > 1e-12 else None


def triangulate(rig, views, score_thr=0.3, max_err_px=15.0, min_views=2, n_k=26):
    """views: list per camera of (keypoints Kx2 px, scores K) or None.

    Returns (points Kx3, confidence K, views used K, mean reprojection error px K); joints that
    could not be placed have NaN points and 0 confidence.
    """
    cams = [c for c, v in enumerate(views) if v is not None and v[0] is not None]
    n_k = len(views[cams[0]][1]) if cams else n_k
    pts = np.full((n_k, 3), np.nan)
    conf = np.zeros(n_k)
    used = np.zeros(n_k, int)
    err = np.full(n_k, np.nan)
    if len(cams) < min_views:
        return pts, conf, used, err
    norm = {c: rig.normalize(c, views[c][0]) for c in cams}
    for k in range(n_k):
        sel = [c for c in cams if views[c][1][k] > score_thr]
        while len(sel) >= min_views:
            P = rig.P[sel]
            xy = np.array([norm[c][k] for c in sel])
            w = np.array([views[c][1][k] for c in sel])
            X = _dlt(P, xy, w)
            if X is None:
                break
            e = []
            for c in sel:
                proj, depth = rig.project_norm(c, X[None])
                e.append(np.inf if depth[0] <= 0 else np.linalg.norm(proj[0] - norm[c][k]) * rig.fx[c])
            e = np.array(e)
            if e.max() <= max_err_px:
                pts[k], used[k], err[k] = X, len(sel), float(e.mean())
                conf[k] = float(np.mean(w)) * min(1.0, len(sel) / 3)
                break
            sel.pop(int(np.argmax(e)))  # drop the view that disagrees most and try again
    return pts, conf, used, err
