"""Has a camera moved since calibration? Compare a fresh frame with the reference frame saved then."""

import cv2
import numpy as np


def tile_shifts(ref, cur, cols=4, rows=3):
    """image_shift on each tile of a cols x rows grid: [(dx, dy, confidence)]."""
    h, w = ref.shape[:2]
    out = []
    for ty in range(rows):
        for tx in range(cols):
            y0, y1, x0, x1 = ty * h // rows, (ty + 1) * h // rows, tx * w // cols, (tx + 1) * w // cols
            out.append(image_shift(ref[y0:y1, x0:x1], cur[y0:y1, x0:x1]))
    return out


def judge(ref, cur, notice_px=2.0, recal_px=5.0, tile_conf=0.3, agree_px=1.0, min_tiles=4):
    """Has this camera moved? A real move shifts every part of the picture the same way; a chair, a blanket or the
    daylight moving changes only some parts. So the picture is cut into 12 tiles, and the shift counts only when at
    least min_tiles clear tiles (confidence tile_conf or more) agree on it within agree_px.
    Returns (verdict, shift_px, dx, dy, agreeing tiles): verdict "ok" (under notice_px), "slight" (notice_px to
    recal_px: it moved a little, not enough to matter), "moved" (over recal_px: recalibrate) or "unsure"."""
    good = [(dx, dy) for dx, dy, c in tile_shifts(ref, cur) if c >= tile_conf]
    if len(good) < min_tiles:
        return "unsure", 0.0, 0.0, 0.0, len(good)
    mdx, mdy = float(np.median([g[0] for g in good])), float(np.median([g[1] for g in good]))
    agree = [g for g in good if np.hypot(g[0] - mdx, g[1] - mdy) <= agree_px]
    if len(agree) < min_tiles:
        return "unsure", 0.0, 0.0, 0.0, len(agree)
    dx, dy = float(np.mean([g[0] for g in agree])), float(np.mean([g[1] for g in agree]))
    shift = float(np.hypot(dx, dy))
    verdict = "ok" if shift <= notice_px else "slight" if shift <= recal_px else "moved"
    return verdict, shift, dx, dy, len(agree)


def image_shift(ref, cur):
    """(dx, dy) in pixels between two frames of the same camera, and a 0-1 confidence."""
    a = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype(np.float32) if ref.ndim == 3 else ref.astype(np.float32)
    b = cv2.cvtColor(cur, cv2.COLOR_BGR2GRAY).astype(np.float32) if cur.ndim == 3 else cur.astype(np.float32)
    # compare edges, not brightness, so daylight changing through the day does not look like movement
    a = cv2.Laplacian(cv2.GaussianBlur(a, (5, 5), 0), cv2.CV_32F)
    b = cv2.Laplacian(cv2.GaussianBlur(b, (5, 5), 0), cv2.CV_32F)
    win = cv2.createHanningWindow(a.shape[::-1], cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(a, b, win)
    return float(dx), float(dy), float(response)
