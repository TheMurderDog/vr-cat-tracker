"""Has a camera moved since calibration? Compare a fresh frame with the reference frame saved then."""

import cv2
import numpy as np


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
