"""Line the cameras up with SteamVR's raw tracking space, using your head as the reference.

The camera core's room calibration placed the cameras in SteamVR standing space as it was that day; standing
space moves after that (one setup measured a ~30 cm shift; play space tools move it all the time). Raw
space doesn't. So, as the camera core's fusion/align.py does for the shift alone, we pair where the cameras see
your eyes and ears with where SteamVR puts your headset, here in raw space, and fit the turn
(around the vertical) and offset between the two while you walk around for a few seconds.

    head seen by cameras = R_yaw @ (headset position + headset rotation @ head offset) + t

The fit is saved, so later runs reuse it: the walk-around is a one-time setup step. Raw space is tied
to the base stations, so SteamVR room setup and play space moves don't affect it; only a moved camera,
moved base station, or SteamVR rebuilding its base station map does. AnchorCheck (below) watches for
that while you play, fixes what it can quietly, and only asks for a new walk-around when it must.
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


WAIT_SAY = "Clear the floor first. Then put on your headset and walk slowly, only where it's clear."
START_SAY = "Good. Keep walking slowly around the room."
WORN_MOVE_M = 0.25  # the headset must have moved this far while worn before the walk counts (not still on a desk)


def wait_for_headset(vr, log, show=None, say=None, cap_s=600.0, now=time.monotonic):
    """Wait until SteamVR says the headset is tracked, on someone's head (its proximity sensor) and moving: only then
    do head sightings line up with it. True when ready, False on q / closing or after cap_s."""
    t0, start, said = now(), None, False
    while now() - t0 < cap_s:
        hmd = vr.headset()
        worn = hmd is not None and vr.worn()
        if worn:
            if start is None:
                start = hmd[:3, 3].copy()
            elif np.linalg.norm(hmd[:3, 3] - start) >= WORN_MOVE_M:
                log.info("Headset on and moving: starting the anchor walk")
                return True
        else:
            start = None
        if not said and say is not None:
            say(WAIT_SAY)
            said = True
        text = ("Headset on: now walk slowly around the room" if worn else
                "Waiting for the headset: clear the floor, put it on, then walk slowly where it's clear")
        if show is not None and show(None, None, text) is False:
            return False
        time.sleep(0.05)
    return False


def collect(cfg, cams, rig, vr, log, show=None, say=None):
    """Run the camera core's pose model until enough head sightings are paired with the raw headset pose (only
    while it's worn). Returns (raw_pts, cam_pts) arrays, or (None, reason in plain words) on timeout / q."""
    pc, fc, ac = cfg["pose"], cfg["fusion"], cfg["cat"]["anchor"]
    o = np.asarray(fc.get("headset_to_head_m", [0.0, 0.0, 0.05]), float)
    need, timeout = int(ac.get("samples", 300)), float(ac.get("timeout_s", 90))
    log.info("Loading the camera core's pose model for the anchor (headset on, walk slowly around the room)...")
    models = baseline.PoseModels(pc, device=f"cuda:{int(cfg.get('gpu', {}).get('device_id', 0))}")
    per_cam = [baseline.CameraPose(models, pc) for _ in cams]
    raw_pts, cam_pts = [], []
    last_seq = [-1] * len(cams)
    if not wait_for_headset(vr, log, (lambda it, vw, text: show(it, vw, text)) if show else None, say):
        del models, per_cam
        return None, "stopped before the walk began"
    if say is not None:
        say(START_SAY)
    t0 = last_log = time.monotonic()
    try:
        while len(raw_pts) < need:
            if time.monotonic() - t0 > timeout:
                log.warning("Anchor timed out with %d of %d head sightings", len(raw_pts), need)
                return None, (f"the cameras only saw your head {len(raw_pts)} of {need} times in {timeout:.0f} s. "
                              "Walk slowly where two or more cameras see you")
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
            if head is not None and hmd is not None and vr.worn():  # taken off for a moment: those don't count
                raw_pts.append(hmd[:3, 3] + hmd[:3, :3] @ o)
                cam_pts.append(head)
            now = time.monotonic()
            if now - last_log > 2:
                log.info("  anchor: %d / %d head sightings", len(raw_pts), need)
                last_log = now
            if show is not None and show(items, views, f"Anchoring: keep walking slowly ({100 * len(raw_pts) // need}%)") \
                    is False:
                return None, "stopped"
            time.sleep(1 / 30)  # 30 sightings a second is plenty while walking
    finally:
        del models, per_cam
    return np.array(raw_pts), np.array(cam_pts)


def run(cfg, cams, rig, vr, log, show=None, say=None):
    """Wait for the headset, collect, fit, and save only a good fit (the old anchor is backed up first). Returns
    (the 4x4 raw->camera transform, None), or (None, why it didn't work, in plain words)."""
    ac = cfg["cat"]["anchor"]
    raw, cam = collect(cfg, cams, rig, vr, log, show, say)
    if raw is None:
        return None, cam
    T, resid, kept, spread = fit_yaw(raw, cam)
    log.info("Anchor: median error %.0f mm over %d sightings, walked %.2f m across", 1000 * resid, kept, spread)
    if spread < float(ac.get("min_spread_m", 0.8)):
        why = (f"you only moved {spread:.1f} m across; walk around more of the room "
               f"(at least {float(ac.get('min_spread_m', 0.8)):.1f} m)")
        log.warning("Anchor not saved: %s", why)
        return None, why
    if resid > float(ac.get("max_residual_m", 0.06)):
        why = (f"the headset and what the cameras saw didn't line up (off by {100 * resid:.0f} cm). "
               "Keep the headset on the whole walk, with nobody else in the room")
        log.warning("Anchor not saved: %s", why)
        return None, why
    backup(cfg)
    save(cfg, T, resid, kept, spread, universe_id=_universe(vr))
    return T, None


def backup(cfg):
    """Copy the saved anchor to my_data/backups before a new one replaces it."""
    import shutil
    from core.config import resolve_path
    p = _path(cfg)
    if p.is_file():
        dest = resolve_path("my_data/backups") / f"anchor_{time.strftime('%Y%m%d-%H%M%S')}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)


def _universe(vr):
    try:
        return vr.universe_id() if vr is not None else None
    except Exception:  # noqa: BLE001
        return None


def _path(cfg):
    from core.config import resolve_path
    return resolve_path(cfg["cat"]["anchor"].get("file", "my_data/tracker/anchor.json"))


def save(cfg, T, resid, kept, spread, universe_id=None):
    """A fresh anchor from a walk-around."""
    p = _path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"raw_to_camera": T.tolist(), "median_error_m": resid, "samples": kept, "spread_m": spread,
                   "universe_id": universe_id, "saved": time.strftime("%Y-%m-%d %H:%M:%S")}, f, indent=2)


def update(cfg, T=None, **fields):
    """Change a saved anchor in place (a quiet correction, or the base station map id), keeping the rest."""
    info = load_info(cfg) or {}
    if T is not None:
        info["raw_to_camera"] = np.asarray(T, float).tolist()
        info["corrected"] = time.strftime("%Y-%m-%d %H:%M:%S")
    info.update(fields)
    p = _path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)


def load_info(cfg):
    """Everything saved with the anchor, or None."""
    p = _path(cfg)
    if not p.is_file():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def load(cfg, log=None):
    """The saved anchor's 4x4, or None (none saved, or one saved with a fit error over max_residual_m: those
    lined the cat up wrong, so the walk runs again; the file stays and is backed up when a new one replaces it)."""
    info = load_info(cfg)
    if not info or "raw_to_camera" not in info:
        return None
    limit = float(cfg["cat"]["anchor"].get("max_residual_m", 0.06))
    if float(info.get("median_error_m", 0) or 0) > limit:
        if log is not None:
            log.warning("The saved anchor is off by %.0f cm (over %.0f cm): doing the walk again",
                        100 * float(info["median_error_m"]), 100 * limit)
        return None
    return np.array(info["raw_to_camera"], float)


class AnchorCheck:
    """While the tracker runs: every few minutes (only while you wear the headset), pairs a few head
    sightings with the headset again and measures how far the saved anchor is off. The anchor is stable:
    raw tracking space is tied to the base stations, so SteamVR room setup and play space moves never
    touch it. So this stays quiet and fixes what it can by itself:

    - off by a little (fix_min_m to fix_max_m), the same way in two checks in a row: the anchor is shifted
      by that much and saved. No notice.
    - off in a way a shift can't fix (the room's turn changed): the sightings from your normal moving
      around are pooled, and once there are refit_samples of them covering min_spread_m it redoes the whole
      anchor from them. No notice.
    - only when neither works does `needs_reanchor` turn True (`off` is the same thing) with a one-line
      `reason`, and the tracker shows a notice asking for a walk-around.

    At startup `startup(vr)` compares SteamVR's base station map with the one the anchor was made in. A
    different map means raw space itself changed, so it asks for a re-anchor straight away, unless the
    first check shows the anchor still fits (then the new map is just remembered).
    The camera core's pose model is loaded on the first check and kept; each sighting is one person
    detection and one pose run per camera, so it costs little next to the cat detector."""

    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log
        kc = cfg["cat"].get("anchor_check", {}) or {}
        ac = cfg["cat"].get("anchor", {}) or {}
        self.on = bool(kc.get("enabled", True))
        self.every = float(kc.get("every_s", 180))
        self.recheck = float(kc.get("recheck_s", 20))
        self.first_after = float(kc.get("first_after_s", 30))
        self.need = int(kc.get("samples", 20))
        self.window = float(kc.get("window_s", 20))
        self.fix_min = float(kc.get("fix_min_m", 0.03))
        self.fix_max = float(kc.get("fix_max_m", 0.30))
        self.agree = float(kc.get("agree_m", 0.04))
        self.max_scatter = float(kc.get("max_scatter_m", 0.08))
        self.min_spread = float(ac.get("min_spread_m", 0.8))
        self.refit_samples = int(kc.get("refit_samples", 100))
        self.max_resid = float(ac.get("max_residual_m", 0.06))
        self.o = np.asarray(cfg["fusion"].get("headset_to_head_m", [0.0, 0.0, 0.05]), float)
        self.models = self.per_cam = None
        self.next_at = time.monotonic() + self.first_after
        self.started = None
        self.raw, self.cam = [], []
        self.needs_reanchor, self.reason = False, ""
        self.error_m = None
        self.corrected_m = 0.0      # how far quiet corrections have moved the anchor this run
        self._map_changed = None    # (saved id, current id) while a base station map change is unconfirmed
        self._clear_fixes()

    @property
    def off(self):  # older name, still read by the tracker and the app
        return self.needs_reanchor

    def _clear_fixes(self):
        self.pending = None          # offset seen by the last check, waiting for a second check to agree
        self.fixes_in_a_row = 0      # shifts that didn't hold: a sign the turn is off, not just the position
        self.big_in_a_row = 0
        self.good_in_a_row = 0
        self.pool_raw, self.pool_cam = [], []

    def _ask(self, reason):
        if not self.needs_reanchor or reason != self.reason:
            self.log.warning("Anchor: re-anchor needed: %s", reason)
        self.needs_reanchor, self.reason = True, reason

    def _fine(self):
        if self.needs_reanchor:
            self.log.info("Anchor check: the anchor fits again, notice cleared")
        self.needs_reanchor, self.reason = False, ""
        self._clear_fixes()

    def startup(self, vr):
        """Call once after the saved anchor is loaded."""
        info = load_info(self.cfg) or {}
        saved, now_id = info.get("universe_id"), _universe(vr)
        if now_id is None:
            return
        if saved is None:  # an anchor from before the map id was saved: remember it now
            update(self.cfg, universe_id=now_id)
        elif int(saved) != int(now_id):
            self._map_changed = (saved, now_id)
            self._ask("SteamVR's base station map changed since the anchor was made (base stations moved?)")

    def _load(self, n):
        pc = self.cfg["pose"]
        self.models = baseline.PoseModels(pc, device=f"cuda:{int(self.cfg.get('gpu', {}).get('device_id', 0))}")
        self.per_cam = [baseline.CameraPose(self.models, pc) for _ in range(n)]

    def step(self, items, rig, vr, raw_to_cam, now):
        """Call at each detection. Adds at most one head sighting while a check is running.
        Returns a corrected 4x4 raw->camera anchor when it fixed one (already saved), else None."""
        if not self.on or raw_to_cam is None or now < self.next_at:
            return None
        if self.started is None:
            self.started, self.raw, self.cam = now, [], []
        if self.models is None:
            try:
                self._load(len(items))
            except Exception as e:  # noqa: BLE001
                self.log.warning("Anchor check off: the camera core's pose model didn't load (%s)", e)
                self.on = False
                return None
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
            T2 = self._judge(np.array(self.raw), np.array(self.cam), raw_to_cam, vr)
            # while something is off or unconfirmed, check again soon, so a fix takes a minute or two, not 15
            unsettled = self.pool_raw or self.pending is not None or self._map_changed or self.needs_reanchor
            self.started, self.next_at = None, now + (self.recheck if unsettled else self.every)
            return T2
        if now - self.started > self.window:  # not enough sightings (headset off, out of view): try later
            self.started, self.next_at = None, now + self.every
        return None

    def _pool(self, raw, cam):
        self.pool_raw.extend(raw)
        self.pool_cam.extend(cam)
        del self.pool_raw[:-1500], self.pool_cam[:-1500]

    def _judge(self, raw, cam, T, vr):
        r = cam - (raw @ T[:3, :3].T + T[:3, 3])
        off_vec = np.median(r, axis=0)
        err = float(np.median(np.linalg.norm(r, axis=1)))
        # Is this really the headset's head? Judged against the best turn and offset for these sightings
        # alone, not against the saved anchor: if the room's turn changed, residuals against the saved
        # anchor vary with where you stand and would look like scatter. Sightings that still scatter after
        # their own fit weren't the headset's head (someone else in view, headset not on).
        Ts = fit_yaw(raw, cam, iters=1)[0]
        scatter = float(np.median(np.linalg.norm(cam - (raw @ Ts[:3, :3].T + Ts[:3, 3]), axis=1)))
        self.error_m = err
        if scatter > self.max_scatter:
            self.log.info("Anchor check: sightings too scattered to judge (%.0f mm off, %.0f mm scatter); "
                          "someone else in view, or the headset not on your head?", 1000 * err, 1000 * scatter)
            return None
        self.log.info("Anchor check: %.0f mm off (scatter %.0f mm)", 1000 * err, 1000 * scatter)

        if err <= self.fix_min:
            if self._map_changed is not None:
                self.log.info("Anchor check: SteamVR's base station map changed but the anchor still fits; keeping it")
                update(self.cfg, universe_id=self._map_changed[1])
                self._map_changed = None
                self._fine()
                return None
            self.good_in_a_row += 1
            if not self.pool_raw or self.good_in_a_row >= 3:  # settled: fits wherever you've been lately
                self._fine()
            else:  # fits here after a shift, but a wrong turn only shows elsewhere: keep collecting
                self._pool(raw, cam)
            return None
        self.good_in_a_row = 0

        # off: pool the sightings, and redo the whole anchor from them once you've moved around enough
        self._pool(raw, cam)
        if len(self.pool_raw) >= self.refit_samples:
            T2, resid, kept, spread = fit_yaw(np.array(self.pool_raw), np.array(self.pool_cam))
            if spread >= self.min_spread and resid <= self.max_resid:
                self.log.info("Anchor: redone quietly from your normal moving around (%.0f mm error, %d sightings, "
                              "%.2f m across)", 1000 * resid, kept, spread)
                save(self.cfg, T2, resid, kept, spread, universe_id=_universe(vr))
                self._map_changed = None
                self.corrected_m += err
                self._fine()
                return T2

        if err <= self.fix_max:
            self.big_in_a_row = 0
            if self.pending is not None and np.linalg.norm(off_vec - self.pending) <= self.agree:
                shift = (off_vec + self.pending) / 2
                T2 = T.copy()
                T2[:3, 3] += shift
                self.corrected_m += float(np.linalg.norm(shift))
                self.fixes_in_a_row += 1
                self.pending = None
                update(self.cfg, T2)
                self.log.info("Anchor: shifted by %.0f mm to match your head (fix %d in a row)",
                              1000 * float(np.linalg.norm(shift)), self.fixes_in_a_row)
                if self.fixes_in_a_row >= 3:
                    self._ask("the room's turn looks off and moving around hasn't fixed it yet")
                return T2
            self.pending = off_vec
            return None

        self.pending = None
        self.big_in_a_row += 1
        if self.big_in_a_row >= 2:  # two checks in a row, so one odd check never asks
            self._ask("the anchor is %.0f cm off (cameras or base stations moved?)" % (100 * err))
        return None

    def reset(self):
        """After a new anchor: clear the notice and check again later."""
        self.needs_reanchor, self.reason, self.started = False, "", None
        self._map_changed = None
        self._clear_fixes()
        self.next_at = time.monotonic() + self.every
