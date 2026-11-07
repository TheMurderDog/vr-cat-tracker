"""One Euro filter (Casiez et al. 2012): little smoothing when moving fast, strong smoothing when still."""

import math

import numpy as np


def _alpha(cutoff, dt):
    tau = 1.0 / (2 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)  # works on arrays too


class OneEuro:
    """Filters an (N, D) array (e.g. all joints at once). Each row's speed sets its smoothing, so a
    joint's x, y and z are smoothed alike. Rows with NaN are held at their last value."""

    def __init__(self, min_cutoff=1.5, beta=0.5, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x = None
        self.dx = None
        self.t = None

    def __call__(self, x, t):
        x = np.asarray(x, np.float64)
        if self.x is None:
            self.x, self.dx, self.t = x.copy(), np.zeros_like(x), t
            return self.x.copy()
        dt = max(t - self.t, 1e-4)
        self.t = t
        have = np.isfinite(x).all(axis=1)
        new = have & ~np.isfinite(self.x).all(axis=1)  # joint just reappeared: start from it
        self.x[new], self.dx[new] = x[new], 0.0
        ok = have & ~new
        a_d = _alpha(self.d_cutoff, dt)
        self.dx[ok] = a_d * (x[ok] - self.x[ok]) / dt + (1 - a_d) * self.dx[ok]
        speed = np.linalg.norm(self.dx[ok], axis=1, keepdims=True)
        a = _alpha(self.min_cutoff + self.beta * speed, dt)
        self.x[ok] = a * x[ok] + (1 - a) * self.x[ok]
        return self.x.copy()


class JumpGate:
    """Rejects a joint that leaps further than max_jump_m from where it was last accepted, which is
    usually one camera's confident mistake. After `accept_after` rejections in a row the new place
    is believed (the person really moved, or the old value was the wrong one)."""

    def __init__(self, max_jump_m=0.4, accept_after=5):
        self.max_jump, self.accept_after = max_jump_m, accept_after
        self.last = None
        self.rejected = None

    def __call__(self, x):
        x = np.array(x, np.float64)
        if self.last is None:
            self.last, self.rejected = x.copy(), np.zeros(len(x), int)
            return x
        have = np.isfinite(x).all(axis=1)
        known = np.isfinite(self.last).all(axis=1)
        jump = np.zeros(len(x), bool)
        jump[have & known] = np.linalg.norm(x[have & known] - self.last[have & known], axis=1) > self.max_jump
        jump &= self.rejected < self.accept_after
        self.rejected = np.where(jump, self.rejected + 1, 0)
        x[jump] = np.nan
        ok = np.isfinite(x).all(axis=1)
        self.last[ok] = x[ok]
        return x


def _rotvec(R):
    """Axis * angle (radians) of a rotation matrix."""
    c = (np.trace(R) - 1) / 2
    a = math.acos(max(-1.0, min(1.0, c)))
    if a < 1e-9:
        return np.zeros(3)
    v = np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]])
    n = np.linalg.norm(v)
    if n < 1e-9:  # 180 degrees: take the axis from the symmetric part
        w, V = np.linalg.eigh((R + R.T) / 2)
        return V[:, np.argmax(w)] * a
    return v / n * a


def _rotmat(rv):
    a = np.linalg.norm(rv)
    if a < 1e-12:
        return np.eye(3)
    k = rv / a
    Kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(a) * Kx + (1 - math.cos(a)) * Kx @ Kx


class RotationEuro:
    """One Euro filter for one rotation: steadies small wobble, follows fast turns. Speeds are in
    radians per second, so beta=0.3 lifts the cutoff by 0.3 Hz per rad/s of turning."""

    def __init__(self, min_cutoff=1.0, beta=0.3, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.R = None
        self.speed = 0.0
        self.t = None

    def __call__(self, R, t):
        if R is None:
            return None
        if self.R is None or t - self.t > 0.5:  # first, or back after a gap: start from it
            self.R, self.speed, self.t = R.copy(), 0.0, t
            return self.R.copy()
        dt = max(t - self.t, 1e-4)
        self.t = t
        step = _rotvec(self.R.T @ R)  # from the filtered rotation to the new one, in its own frame
        a_d = _alpha(self.d_cutoff, dt)
        self.speed = a_d * np.linalg.norm(step) / dt + (1 - a_d) * self.speed
        a = _alpha(self.min_cutoff + self.beta * self.speed, dt)
        self.R = self.R @ _rotmat(a * step)
        return self.R.copy()
