"""Line the cameras up with SteamVR's raw tracking space, using your head as the reference.

the camera core's room calibration placed the cameras in SteamVR standing space as it was that day; standing
space moves after that (one setup measured a ~30 cm shift; play space tools move it all the time). Raw
space doesn't. So, as the camera core's fusion/align.py does for the shift alone, we pair where the cameras see
your eyes and ears with where SteamVR puts your headset, here in raw space, and fit the turn
(around the vertical) and offset between the two while you walk around for a few seconds.

    head seen by cameras = R_yaw @ (headset position + headset rotation @ head offset) + t

The fit is saved, so later runs can reuse it (until the base stations or cameras move).
"""

import json
import math
import time

import numpy as np

from fusion import align
from fusion.triangulate import triangulate
from pose import baseline


def fit_yaw(raw_pts, cam_pts, iters=4):
    """Best R (turn around y only) and t with cam = R @ raw + t. Outliers are dropped.
    Returns (4x4 raw->camera, median residual m, samples kept, horizontal spread m)."""
    keep = np.ones(len(raw_pts), bool)
    for _ in range(iters):
        a, b = raw_pts[keep], cam_pts[keep]
        ac, bc = a - a.mean(axis=0), b - b.mean(axis=0)
        th = math.atan2(np.sum(ac[:, 2] * bc[:, 0] - ac[:, 0] * bc[:, 2]), np.sum(ac[:, 0] * bc[:, 0] + ac[:, 2] * bc[:, 2]))
        c, s = math.cos(th), math.sin(th)
        R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
        t = b.mean(axis=0) - R @ a.mean(axis=0)
        r = np.linalg.norm(cam_pts - raw_pts @ R.T - t, axis=1)
        keep = r < max(3 * np.median(r[keep]), 0.03)
    T = np.eye(4)
    T[:3, :3], T[:3, 3] = R, t
    xz = raw_pts[keep][:, [0, 2]]
    spread = float(np.linalg.norm(xz.max(axis=0) - xz.min(axis=0))) if len(xz) else 0.0
    return T, float(np.median(r[keep])), int(keep.sum()), spread


def collect(cfg, cams, rig, vr, log, show=None):
    """Run the camera core's pose model until enough head sightings are paired with the raw headset pose.
    Returns (raw_pts, cam_pts) arrays, or None on timeout / q."""
    pc, fc, ac = cfg["pose"], cfg["fusion"], cfg["cat"]["anchor"]
    o = np.asarray(fc.get("headset_to_head_m", [0.0, 0.0, 0.05]), float)
    need, timeout = int(ac.get("samples", 300)), float(ac.get("timeout_s", 90))
    log.info("Loading the camera core's pose model for the anchor (headset on, walk slowly around the room)...")
    models = baseline.PoseModels(pc, device=f"cuda:{int(cfg.get('gpu', {}).get('device_id', 0))}")
    per_cam = [baseline.CameraPose(models, pc) for _ in cams]
    raw_pts, cam_pts = [], []
    last_seq = [-1] * len(cams)
    t0 = last_log = time.monotonic()
    try:
        while len(raw_pts) < need:
            if time.monotonic() - t0 > timeout:
                log.warning("Anchor timed out with %d of %d head sightings", len(raw_pts), need)
                return None
            items = [c.latest(rotated=False) for c in cams]
            if not any(it is not None and it[2] != last_seq[i] for i, it in enumerate(items)):
                time.sleep(0.002)
                continue
            for i, it in enumerate(items):
                if it is not None:
                    last_seq[i] = it[2]
            for i, it in enumerate(items):  # cheap enough here: the cat detector isn't running yet
                if it is not None and per_cam[i].needs_detect():
                    per_cam[i].detect(it[0])
            run = [i for i, it in enumerate(items) if it is not None and per_cam[i].bbox is not None]
            views = [None] * len(cams)
            if run:
                for i, (kp, sc) in zip(run, models.pose_batch([items[i][0] for i in run], [per_cam[i].bbox for i in run])):
                    kp, sc = per_cam[i].update(items[i][0].shape, kp, sc)
                    views[i] = (kp, sc) if kp is not None else None
            J, _, _, _ = triangulate(rig, views, float(fc.get("keypoint_score", 0.3)),
                                     float(fc.get("max_reprojection_px", 15)), int(fc.get("min_views", 2)))
            head = align.head_point(J)
            hmd = vr.headset()
            if head is not None and hmd is not None:
                raw_pts.append(hmd[:3, 3] + hmd[:3, :3] @ o)
                cam_pts.append(head)
            now = time.monotonic()
            if now - last_log > 2:
                log.info("  anchor: %d / %d head sightings", len(raw_pts), need)
                last_log = now
            if show is not None and show(items, views) is False:
                return None
            time.sleep(1 / 30)  # 30 sightings a second is plenty while walking
    finally:
        del models, per_cam
    return np.array(raw_pts), np.array(cam_pts)


def run(cfg, cams, rig, vr, log, show=None):
    """Collect, fit and save. Returns the 4x4 raw->camera transform, or None."""
    ac = cfg["cat"]["anchor"]
    got = collect(cfg, cams, rig, vr, log, show)
    if got is None:
        return None
    T, resid, kept, spread = fit_yaw(*got)
    log.info("Anchor: median error %.0f mm over %d sightings, walked %.2f m across", 1000 * resid, kept, spread)
    if spread < float(ac.get("min_spread_m", 0.8)):
        log.warning("You only moved %.2f m across; walk around more so the room's turn can be pinned down", spread)
        return None
    if resid > float(ac.get("max_residual_m", 0.06)):
        log.warning("Anchor error %.0f mm is high (headset on? anyone else in the room?); using it anyway", 1000 * resid)
    save(cfg, T, resid, kept, spread)
    return T


def _path(cfg):
    from core.config import resolve_path
    return resolve_path(cfg["cat"]["anchor"].get("file", "cat_tracker/data/anchor.json"))


def save(cfg, T, resid, kept, spread):
    p = _path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"raw_to_camera": T.tolist(), "median_error_m": resid, "samples": kept, "spread_m": spread,
                   "saved": time.strftime("%Y-%m-%d %H:%M:%S")}, f, indent=2)


def load(cfg):
    p = _path(cfg)
    if not p.is_file():
        return None
    with open(p, "r", encoding="utf-8") as f:
        return np.array(json.load(f)["raw_to_camera"], float)


class AnchorCheck:
    """While the tracker runs: every few minutes, pairs a few head sightings with the headset again and
    measures how far the saved anchor is off. If the cameras or base stations have moved, the cat
    marker is off by about the same amount, so `off` turns True and the tracker shows a warning.
    the camera core's pose model is loaded on the first check and kept; each sighting is one person detection and
    one pose run per camera, so it costs little next to the cat detector."""

    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log
        kc = cfg["cat"].get("anchor_check", {}) or {}
        self.on = bool(kc.get("enabled", True))
        self.every = float(kc.get("every_s", 180))
        self.need = int(kc.get("samples", 20))
        self.window = float(kc.get("window_s", 20))
        self.warn = float(kc.get("warn_m", 0.10))
        self.max_scatter = float(kc.get("max_scatter_m", 0.08))
        self.o = np.asarray(cfg["fusion"].get("headset_to_head_m", [0.0, 0.0, 0.05]), float)
        self.models = self.per_cam = None
        self.next_at = time.monotonic() + float(kc.get("first_after_s", 30))
        self.started = None
        self.raw, self.cam = [], []
        self.off = False
        self.bad_in_a_row = 0
        self.error_m = None

    def _load(self, n):
        pc = self.cfg["pose"]
        self.models = baseline.PoseModels(pc, device=f"cuda:{int(self.cfg.get('gpu', {}).get('device_id', 0))}")
        self.per_cam = [baseline.CameraPose(self.models, pc) for _ in range(n)]

    def step(self, items, rig, vr, raw_to_cam, now):
        """Call at each detection. Adds at most one head sighting while a check is running."""
        if not self.on or raw_to_cam is None or now < self.next_at:
            return
        if self.started is None:
            self.started, self.raw, self.cam = now, [], []
        if self.models is None:
            try:
                self._load(len(items))
            except Exception as e:  # noqa: BLE001
                self.log.warning("Anchor check off: the camera core's pose model didn't load (%s)", e)
                self.on = False
                return
        hmd = vr.headset() if vr.worn() else None  # a headset left on the desk still reports a pose
        if hmd is not None:
            fc = self.cfg["fusion"]
            views = [None] * len(items)
            run = [i for i, it in enumerate(items) if self.per_cam[i].detect(it[0])]  # fresh box every time
            if run:
                for i, (kp, sc) in zip(run, self.models.pose_batch([items[i][0] for i in run],
                                                                   [self.per_cam[i].bbox for i in run])):
                    kp, sc = self.per_cam[i].update(items[i][0].shape, kp, sc)
                    views[i] = (kp, sc) if kp is not None else None
            J, _, _, _ = triangulate(rig, views, float(fc.get("keypoint_score", 0.3)),
                                     float(fc.get("max_reprojection_px", 15)), int(fc.get("min_views", 2)))
            head = align.head_point(J)
            if head is not None:
                self.raw.append(hmd[:3, 3] + hmd[:3, :3] @ self.o)
                self.cam.append(head)
        if len(self.raw) >= self.need:
            raw = np.array(self.raw)
            r = np.array(self.cam) - (raw @ raw_to_cam[:3, :3].T + raw_to_cam[:3, 3])
            err = float(np.median(np.linalg.norm(r, axis=1)))
            # moved cameras or base stations put every sighting off by about the same amount; sightings
            # that scatter mean the head seen wasn't the headset's (someone else, headset not on), not a bad anchor
            scatter = float(np.median(np.linalg.norm(r - np.median(r, axis=0), axis=1)))
            self.error_m = err
            if scatter > self.max_scatter:
                self.log.info("Anchor check: sightings too scattered to judge (%.0f mm off, %.0f mm scatter); "
                              "someone else in view, or the headset not on your head?", 1000 * err, 1000 * scatter)
            else:
                self.bad_in_a_row = self.bad_in_a_row + 1 if err > self.warn else 0
                was, self.off = self.off, self.bad_in_a_row >= 2  # two checks in a row before warning
                (self.log.warning if err > self.warn else self.log.info)(
                    "Anchor check: the saved anchor is %.0f mm off (scatter %.0f mm)%s", 1000 * err, 1000 * scatter,
                    " - cameras or base stations moved? re-run the anchor (a in the window)" if self.off else "")
                if was and not self.off:
                    self.log.info("Anchor check: back within %.0f mm", 1000 * self.warn)
            self.started, self.next_at = None, now + self.every
        elif now - self.started > self.window:  # not enough sightings (headset off, out of view): try later
            self.started, self.next_at = None, now + self.every

    def reset(self):
        """After a new anchor: clear the warning and check again later."""
        self.off, self.started, self.bad_in_a_row = False, None, 0
        self.next_at = time.monotonic() + self.every
