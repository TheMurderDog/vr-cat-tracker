"""Text notices for SteamVR overlays, drawn as PNG files at run time (overlays show image files)."""

from pathlib import Path

import cv2
import numpy as np


def render(path, title, lines=(), colour=(40, 40, 220)):
    """A 1024x256 notice: a coloured title bar and up to three lines of text. colour is BGR. Returns path."""
    w, h = 1024, 256
    img = np.zeros((h, w, 4), np.uint8)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (30, 30, 30, 230), -1)
    cv2.rectangle(img, (0, 0), (w - 1, 78), (*colour, 255), -1)
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (*colour, 255), 6)
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, title, (20, 56), font, _scale(title, font, 1.6, 3, w - 40),
                (255, 255, 255, 255), 3, cv2.LINE_AA)
    for k, line in enumerate(list(lines)[:3]):
        s = _scale(line, font, 1.05, 2, w - 40)
        cv2.putText(img, line, (20, 125 + 50 * k), font, s, (235, 235, 235, 255), 2, cv2.LINE_AA)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return path


def _scale(text, font, scale, thick, max_w):
    tw = cv2.getTextSize(text, font, scale, thick)[0][0]
    return scale if tw <= max_w else scale * max_w / tw

