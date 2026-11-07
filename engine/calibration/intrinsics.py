"""Per-camera intrinsics from ChArUco views: fisheye and rational models, outlier rejection.

All calibration happens on raw sensor frames (before any cameras.rotate rotation), so the same
numbers apply to every frame the capture module delivers.
"""

import json

import cv2
import numpy as np


def make_detector(board, ic):
    """ChArUco detector tuned for wide, slightly soft webcam lenses. With OpenCV's defaults a 34 mm
    square board was only found within about a foot; re-finding missed markers from the board layout
    and tolerating more bit errors roughly tripled the range at the same speed."""
    dp = cv2.aruco.DetectorParameters()
    dp.errorCorrectionRate = float(ic.get("error_correction", 0.8))
    dp.perspectiveRemovePixelPerCell = int(ic.get("pixels_per_cell", 8))
    cp = cv2.aruco.CharucoParameters()
    cp.tryRefineMarkers = bool(ic.get("refine_markers", True))
    return cv2.aruco.CharucoDetector(board, cp, dp)


def detect(detector, board, frame):
    """(object points Nx3, image points Nx2, ids) of ChArUco corners, or None."""
    gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _, _ = detector.detectBoard(gray)
    if ids is None or len(ids) == 0:
        return None
    obj, img = board.matchImagePoints(corners, ids)
    return obj.reshape(-1, 3).astype(np.float64), img.reshape(-1, 2).astype(np.float64), ids.ravel()


def usable(board, view, min_corners):
    """Enough corners and not all on one line (a collinear set says nothing about the lens)."""
    obj, img, ids = view
    if len(ids) < min_corners:
        return False
    return not board.checkCharucoCornersCollinear(ids.reshape(-1, 1).astype(np.int32))


def _calibrate_fisheye(views, size):
    # OpenCV 5.0's fisheye.calibrate fails with an arithm_op size error on Nx1x3 points; 1xNx3 works
    obj = [v[0].reshape(1, -1, 3) for v in views]
    img = [v[1].reshape(1, -1, 2) for v in views]
    flags = cv2.CALIB_RECOMPUTE_EXTRINSIC | cv2.CALIB_FIX_SKEW  # OpenCV 5 moved the fisheye flags to cv2.CALIB_*
    crit = (cv2.TERM_CRITERIA_COUNT + cv2.TERM_CRITERIA_EPS, 200, 1e-9)
    rms, K, D, rvecs, tvecs = cv2.fisheye.calibrate(obj, img, size, None, None, flags=flags, criteria=crit)
    errs = []
    for v, r, t in zip(views, rvecs, tvecs):
        p, _ = cv2.fisheye.projectPoints(v[0].reshape(-1, 1, 3), r, t, K, D)
        errs.append(float(np.sqrt(np.mean(np.sum((p.reshape(-1, 2) - v[1]) ** 2, axis=1)))))
    return rms, K, D.ravel(), np.array(errs)


def _calibrate_rational(views, size):
    obj = [v[0].astype(np.float32) for v in views]
    img = [v[1].astype(np.float32) for v in views]
    flags = cv2.CALIB_RATIONAL_MODEL
    rms, K, D, rvecs, tvecs = cv2.calibrateCamera(obj, img, size, None, None, flags=flags)
    errs = []
    for v, r, t in zip(views, rvecs, tvecs):
        p, _ = cv2.projectPoints(v[0], r, t, K, D)
        errs.append(float(np.sqrt(np.mean(np.sum((p.reshape(-1, 2) - v[1]) ** 2, axis=1)))))
    return rms, K, D.ravel(), np.array(errs)


MODELS = {"fisheye": _calibrate_fisheye, "rational": _calibrate_rational}


def calibrate(views, size, models=("fisheye", "rational"), outlier_factor=3.0, log=None):
    """Calibrate with each model, drop views whose error is over outlier_factor x the median,
    recalibrate, and return the best result as a dict."""
    results = []
    for name in models:
        try:
            keep = list(views)
            rms, K, D, errs = MODELS[name](keep, size)
            bad = errs > outlier_factor * np.median(errs)
            if bad.any() and len(keep) - bad.sum() >= 8:
                keep = [v for v, b in zip(keep, bad) if not b]
                rms, K, D, errs = MODELS[name](keep, size)
            results.append({"model": name, "rms_px": float(rms), "K": K, "D": D, "view_errors": errs,
                            "views_used": len(keep), "views_dropped": len(views) - len(keep)})
            if log:
                log.info("  %-8s RMS %.3f px from %d views (%d dropped as outliers), fx %.1f fy %.1f cx %.1f cy %.1f",
                         name, rms, len(keep), len(views) - len(keep), K[0, 0], K[1, 1], K[0, 2], K[1, 2])
        except cv2.error as e:
            if log:
                log.warning("  %-8s failed: %s", name, str(e).strip().splitlines()[-1])
    if not results:
        raise RuntimeError("every lens model failed to calibrate")
    # The fisheye model has 4 distortion terms against the rational model's 8, so it extrapolates
    # better toward the image edges; it wins unless rational is clearly (over 5%) better.
    return min(results, key=lambda r: r["rms_px"] * (1.05 if r["model"] == "rational" else 1.0))


def stretch_views(views, stretch):
    """The views with the board's height scaled by stretch (its height / width as printed, against the design)."""
    k = np.array([1.0, float(stretch), 1.0])
    return [(v[0] * k, v[1], v[2]) for v in views]


def fit_stretch(views, size, model, outlier_factor=3.0, limit=0.05):
    """How much the printer stretched the board one way: the height/width factor (1.0 = as designed) that fits the
    views best, searched within 1 +- limit with this lens model. An even shrink can't be seen and doesn't matter
    (the lens result is the same at any overall board size); a one-way stretch can, and does.
    The outlier views are chosen once first, so the error being minimised is smooth."""
    from scipy.optimize import minimize_scalar
    fit = MODELS[model]
    keep = list(views)
    _, _, _, errs = fit(keep, size)
    bad = errs > outlier_factor * np.median(errs)
    if bad.any() and len(keep) - bad.sum() >= 8:
        keep = [v for v, b in zip(keep, bad) if not b]

    def rms(a):
        try:
            return fit(stretch_views(keep, a), size)[0]
        except cv2.error:
            return 1e9
    r = minimize_scalar(rms, bounds=(1 - limit, 1 + limit), method="bounded", options={"xatol": 2e-4})
    return float(r.x), float(rms(1.0)), float(r.fun)


def coverage(views, size, grid=(8, 6)):
    """Fraction of image grid cells that contain at least one detected corner."""
    hit = np.zeros(grid[::-1], bool)
    for v in views:
        gx = np.clip((v[1][:, 0] / size[0] * grid[0]).astype(int), 0, grid[0] - 1)
        gy = np.clip((v[1][:, 1] / size[1] * grid[1]).astype(int), 0, grid[1] - 1)
        hit[gy, gx] = True
    return float(hit.mean()), hit


def save(path, cam_name, device_id, size, result):
    data = {
        "camera": cam_name, "device_id": device_id, "image_size": list(size), "model": result["model"],
        "K": result["K"].tolist(), "D": result["D"].tolist(), "rms_px": result["rms_px"],
        "views_used": result["views_used"], "views_dropped": result["views_dropped"],
        "board_stretch": result.get("board_stretch", 1.0),  # printed board height/width against the design
        "stretch_corrected": bool(result.get("stretch_corrected", False)),
        "status": result.get("status", "GOOD" if result.get("good", True) else "REDO"),
        "note": "raw sensor frame (before cameras.rotate)",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    d["K"] = np.array(d["K"], np.float64)
    d["D"] = np.array(d["D"], np.float64)
    return d


def undistort_points(pts, intr):
    """Pixel points (Nx2) to normalized, undistorted camera coordinates (Nx2)."""
    pts = np.asarray(pts, np.float64).reshape(-1, 1, 2)
    if intr["model"] == "fisheye":
        return cv2.fisheye.undistortPoints(pts, intr["K"], intr["D"]).reshape(-1, 2)
    return cv2.undistortPoints(pts, intr["K"], intr["D"]).reshape(-1, 2)


def project(obj, rvec, tvec, intr):
    obj = np.asarray(obj, np.float64).reshape(-1, 1, 3)
    if intr["model"] == "fisheye":
        p, _ = cv2.fisheye.projectPoints(obj, rvec, tvec, intr["K"], intr["D"])
    else:
        p, _ = cv2.projectPoints(obj, rvec, tvec, intr["K"], intr["D"])
    return p.reshape(-1, 2)
