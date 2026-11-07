"""Place every camera in SteamVR space from a tracker with a printed ArUco marker on it.

Each observation is: the marker centre seen in one camera's image, and the tracker's SteamVR pose
at that moment. Unknowns: each camera's pose in SteamVR space, and where the marker centre sits
in the tracker's own frame (one offset shared by all cameras). Solved by robust least squares.
"""

import cv2
import numpy as np
from scipy.optimize import least_squares

from calibration import intrinsics as intr


def _cam_from_vr(rvec, tvec, X):
    R, _ = cv2.Rodrigues(rvec)
    return X @ R.T + tvec  # rvec/tvec map VR-space points into the camera frame


def initial_pose(obs_xyz, obs_norm):
    """Camera pose from 3D points (VR space) and their undistorted normalized image points."""
    obj = np.ascontiguousarray(obs_xyz, np.float64).reshape(-1, 1, 3)
    img = np.ascontiguousarray(obs_norm, np.float64).reshape(-1, 1, 2)
    # The marker offset (the tracker can sit 10-20 cm from the marker) is ignored here, so points can be off by a
    # lot more than pixel noise: widen the threshold until most points agree. The full solve then fixes it.
    best = None
    for thr in (0.01, 0.03, 0.06, 0.1):
        ok, rvec, tvec, inl = cv2.solvePnPRansac(obj, img, np.eye(3), None, reprojectionError=thr,
                                                 iterationsCount=500, flags=cv2.SOLVEPNP_EPNP)
        if ok and inl is not None and len(inl) >= 6:
            best = (rvec, tvec, inl)
            if len(inl) >= 0.6 * len(obj):
                break
    if best is None:
        raise RuntimeError("could not get a first pose estimate")
    rvec, tvec, inl = best
    ok, rvec, tvec = cv2.solvePnP(obj[inl.ravel()], img[inl.ravel()], np.eye(3), None, rvec, tvec,
                                  useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE)
    return rvec.ravel(), tvec.ravel()


COLLAPSED_M = 0.005   # a marker offset this close to 0 is the solver stuck where it started, not a real card
STARTS_M = 0.15       # the other starting guesses for the offset: 15 cm along each tracker axis, both ways


def _score(out, outlier_px=10.0):
    """How well a solution fits (lower is better): squared errors, each capped at outlier_px, so a few wild
    stops can't decide it."""
    e = np.minimum(out["obs_errors_px"], outlier_px)
    return float(np.sum(e ** 2))


def solve_best(obs, intrinsics, n_cams, start=None, loss_scale_px=3.0, outlier_px=10.0, names=None,
               offset_prior_m=0.1):
    """solve_once from several starting points, keeping the best fit: the usual start (marker offset 0),
    the offset 15 cm along each tracker axis, and, when given, the previous pass's answer (start: a solve
    result for the same cameras). The fit can get stuck where it started (on Nov 4 a second pass ended with
    the offset at exactly 0 mm and every camera at 6-8 px, while the same stops fit at about 3 px from the
    first pass's answer), so one start is never trusted. A solution whose offset collapsed to about 0 only
    wins if nothing else fits."""
    starts = [(None, (0.0, 0.0, 0.0))] + [(None, tuple(STARTS_M * s * np.eye(3)[k])) for k in range(3) for s in (1, -1)]
    if start is not None and len(start.get("cameras", [])) == n_cams:
        starts.insert(0, ([(c["rvec"], c["tvec"]) for c in start["cameras"]], tuple(start["marker_offset_m"])))
    tried = []
    for init, off in starts:
        try:
            out = solve_once(obs, intrinsics, n_cams, loss_scale_px, outlier_px, None, names, offset_prior_m,
                             init=init, offset0=off)
        except RuntimeError:
            if init is None and off == (0.0, 0.0, 0.0):
                raise  # a camera can't be placed at all: say why
            continue
        collapsed = float(np.linalg.norm(out["marker_offset_m"])) < COLLAPSED_M
        tried.append((collapsed, _score(out, outlier_px), len(tried), out))
    return min(tried, key=lambda t: t[:3])[3]


def solve(obs, intrinsics, n_cams, loss_scale_px=3.0, outlier_px=10.0, log=None, names=None, offset_prior_m=0.1,
          drop_factor=3.0, drop_min_px=5.0, start=None):
    """Solve (from several starts: solve_best), drop each camera's observations over drop_factor x its
    median error (and over drop_min_px; a misread marker or a bumped stop), then solve again from that
    answer. Same result format as solve_once, plus "dropped" per camera. start: the previous pass's result,
    to start from (it's kept only if it fits better)."""
    first = solve_best(obs, intrinsics, n_cams, start, loss_scale_px, outlier_px, names, offset_prior_m)
    e = first.pop("obs_errors_px")
    cams = np.array([o[0] for o in obs])
    keep = np.ones(len(obs), bool)
    for c in range(n_cams):
        sel = cams == c
        keep &= ~(sel & (e > max(drop_factor * np.median(e[sel]), drop_min_px)))
    if log and (~keep).any():
        log.info("  Dropped %d of %d observations as outliers and solved again", (~keep).sum(), len(obs))
    kept = [o for o, k in zip(obs, keep) if k]
    out = solve_once(kept, intrinsics, n_cams, loss_scale_px, outlier_px, None, names, offset_prior_m,
                     init=[(c["rvec"], c["tvec"]) for c in first["cameras"]], offset0=tuple(first["marker_offset_m"]))
    if log:  # the same solve again, only for its log lines
        out = solve_once(kept, intrinsics, n_cams, loss_scale_px, outlier_px, log, names, offset_prior_m,
                         init=[(c["rvec"], c["tvec"]) for c in out["cameras"]], offset0=tuple(out["marker_offset_m"]))
    if log and float(np.linalg.norm(out["marker_offset_m"])) < COLLAPSED_M:
        log.warning("  The marker offset came out at about 0 mm: this solve is likely stuck. Walk again, tilting "
                    "Board B now and then.")
    out.pop("obs_errors_px")
    for c, cam in enumerate(out["cameras"]):
        cam["dropped"] = int(((cams == c) & ~keep).sum())
    return out


def solve_once(obs, intrinsics, n_cams, loss_scale_px=3.0, outlier_px=10.0, log=None, names=None, offset_prior_m=0.1,
               init=None, offset0=(0.0, 0.0, 0.0)):
    """obs: list of (cam_index, pixel xy (2,), tracker position (3,), tracker rotation (3,3)).
    init: [(rvec, tvec)] per camera to start from (else a first estimate from the stops); offset0: the marker
    offset to start from (metres, tracker frame).

    Returns dict with per-camera rvec/tvec (VR -> camera), the marker offset in the tracker frame,
    and per-camera reprojection errors in pixels.
    """
    cams = np.array([o[0] for o in obs])
    px = np.array([o[1] for o in obs], np.float64)
    pos = np.array([o[2] for o in obs], np.float64)
    rot = np.array([o[3] for o in obs], np.float64)
    norm = np.zeros_like(px)
    for c in range(n_cams):
        sel = cams == c
        if sel.any():
            norm[sel] = intr.undistort_points(px[sel], intrinsics[c])
    # first pass: ignore the marker offset (a few cm) to get every camera roughly placed
    x0 = []
    names = names or [f"cam{i + 1}" for i in range(n_cams)]
    for c in range(n_cams):
        sel = cams == c
        if sel.sum() < 6:
            raise RuntimeError(f"{names[c]} camera saw the marker in only {sel.sum()} still moments; need at least 6")
        r, t = (np.ravel(init[c][0]), np.ravel(init[c][1])) if init else initial_pose(pos[sel] + np.einsum(
            "nij,j->ni", rot[sel], np.asarray(offset0, np.float64)), norm[sel])
        x0 += [*r, *t]
    x0 = np.array(x0 + [float(v) for v in offset0])
    fx = np.array([intrinsics[c]["K"][0, 0] for c in range(n_cams)])

    def residuals(x):
        off = x[-3:]
        world = pos + np.einsum("nij,j->ni", rot, off)
        res = np.zeros((len(obs), 2))
        for c in range(n_cams):
            sel = cams == c
            r, t = x[6 * c:6 * c + 3], x[6 * c + 3:6 * c + 6]
            pc = _cam_from_vr(r, t, world[sel])
            res[sel] = (pc[:, :2] / pc[:, 2:3] - norm[sel]) * fx[c]  # in (approximate) pixels
        # Weak pull of the marker offset toward zero, worth 1 px per offset_prior_m. If the tracker
        # only ever turns about one axis (a tripod), the offset along that axis can't be told apart
        # from moving every camera, and without this the solver drifts off by metres.
        return np.concatenate([res.ravel(), x[-3:] / offset_prior_m])

    # Spread of tracker orientations: if one tracker axis never tilts, the offset along it is unknown
    axis_spread = [float(np.degrees(np.max(np.arccos(np.clip(rot[:, :, k] @ (m / np.linalg.norm(m)), -1, 1)))))
                   for k in range(3) for m in [rot[:, :, k].mean(axis=0)]]
    if log and min(axis_spread) < 10:
        log.warning("  The tracker barely tilted (one axis stayed within %.0f deg), so camera heights may be off by "
                    "the marker-to-tracker distance. Re-record with the tracker tilted 20-30 deg at some stops.",
                    min(axis_spread))
    sol = least_squares(residuals, x0, loss="huber", f_scale=loss_scale_px, x_scale="jac")
    res = sol.fun[:-3].reshape(-1, 2)
    out = {"cameras": [], "marker_offset_m": sol.x[-3:].tolist(), "tilt_spread_deg": min(axis_spread),
           "obs_errors_px": np.linalg.norm(res, axis=1)}
    for c in range(n_cams):
        sel = cams == c
        e = np.linalg.norm(res[sel], axis=1)
        r, t = sol.x[6 * c:6 * c + 3], sol.x[6 * c + 3:6 * c + 6]
        R, _ = cv2.Rodrigues(r)
        centre = -R.T @ t
        out["cameras"].append({"rvec": r.tolist(), "tvec": t.tolist(), "position_m": centre.tolist(),
                               "observations": int(sel.sum()),
                               "rms_px": float(np.sqrt(np.mean(e[e < outlier_px] ** 2))) if (e < outlier_px).any() else float("inf"),
                               "median_px": float(np.median(e)), "outliers": float(np.mean(e >= outlier_px))})
        if log:
            log.info("  %-6s %d observations, RMS %.2f px without the %.0f%% outliers (over %.0f px), "
                     "at (%.2f, %.2f, %.2f) m", names[c], sel.sum(), out["cameras"][-1]["rms_px"],
                     100 * out["cameras"][-1]["outliers"], outlier_px, *centre)
    if log:
        log.info("  marker centre in tracker frame: (%.1f, %.1f, %.1f) mm", *(1000 * sol.x[-3:]))
    return out


def cameras_in_order(rm, keys):
    """room.json with its cameras in the settings' slot order, matched by calibration key (files from before keys
    existed: by the name each camera was saved under, which was its key). A camera that's been renamed or moved in
    the order still finds its own calibration. Raises ValueError naming the cameras it has no calibration for."""
    by = {}
    for cam in rm["cameras"]:
        k = cam.get("key", cam.get("name"))
        if k is not None:
            by[str(k)] = cam
    if not by and len(rm["cameras"]) == len(keys):
        return rm  # very old files without names: in slot order
    missing = [k for k in keys if k not in by]
    if missing:
        raise ValueError(f"no room calibration for {', '.join(missing)}")
    return dict(rm, cameras=[by[k] for k in keys])


def project_vr_point(X, cam, intrinsics_c):
    """Pixel position of a VR-space point in one camera (raw sensor frame), or None if behind it."""
    pc = _cam_from_vr(np.array(cam["rvec"]), np.array(cam["tvec"]), np.asarray(X, np.float64).reshape(1, 3))
    if pc[0, 2] <= 0:
        return None
    return intr.project(np.asarray(X, np.float64).reshape(1, 3), np.array(cam["rvec"]), np.array(cam["tvec"]),
                        intrinsics_c)[0]


def marker_detector(rc):
    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, rc["marker_dictionary"]))
    p = cv2.aruco.DetectorParameters()
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return cv2.aruco.ArucoDetector(d, p)


def find_marker(detector, frame, marker_id):
    """Pixel centre of the marker (intersection of its diagonals), or None."""
    gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detector.detectMarkers(gray)
    if ids is None:
        return None
    for c, i in zip(corners, ids.ravel()):
        if i == marker_id:
            p = c.reshape(4, 2).astype(np.float64)
            a1, a2, b1, b2 = p[0], p[2], p[1], p[3]
            da, db = a2 - a1, b2 - b1
            den = da[0] * db[1] - da[1] * db[0]
            if abs(den) < 1e-9:
                return p.mean(axis=0)
            s = ((b1[0] - a1[0]) * db[1] - (b1[1] - a1[1]) * db[0]) / den
            return a1 + s * da
    return None
