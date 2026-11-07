"""Key hints drawn as keycaps: each key in its own rounded box, a short plain label beside it, commands spaced apart,
groups (with a dim title) separated by thin dividers. A group is never split across rows: a group that doesn't fit
moves to the next row whole. Used by the setup screen and the calibration wizards."""

import re

import cv2
import numpy as np

FONT = cv2.FONT_HERSHEY_SIMPLEX
YELLOW, WHITE, DIM, CAP = (0, 210, 255), (240, 240, 240), (150, 150, 150), (60, 60, 60)
NAMED = {"space": "Space", "enter": "Enter", "esc": "Esc", "tab": "Tab", "click": "Click"}


def _cap_w(key, scale):
    return cv2.getTextSize(key, FONT, scale, 2)[0][0] + 18


def _item_w(key, label, scale):
    if key is None:
        return cv2.getTextSize(label, FONT, scale, 1)[0][0] + 18
    return _cap_w(key, scale) + 8 + cv2.getTextSize(label, FONT, scale, 1)[0][0] + 22


def _group_w(title, keys, scale):
    w = (cv2.getTextSize(title.upper(), FONT, scale * 0.8, 1)[0][0] + 12) if title else 0
    return w + sum(_item_w(k, lab, scale) for k, lab in keys)


def _keycap(img, x, y, key, scale):
    """A rounded box with the key in it; returns its width. y is the text baseline."""
    (tw, th), _ = cv2.getTextSize(key, FONT, scale, 2)
    w, top, bottom, r = tw + 18, y - th - 9, y + 9, 6
    for cx in (x + r, x + w - r):  # rounded corners: filled circles, then the straight parts
        for cy in (top + r, bottom - r):
            cv2.circle(img, (cx, cy), r, CAP, -1, cv2.LINE_AA)
    cv2.rectangle(img, (x + r, top), (x + w - r, bottom), CAP, -1)
    cv2.rectangle(img, (x, top + r), (x + w, bottom - r), CAP, -1)
    cv2.line(img, (x + r, bottom), (x + w - r, bottom), (25, 25, 25), 2)  # a little depth under the key
    cv2.putText(img, key, (x + 9, y), FONT, scale, YELLOW, 2, cv2.LINE_AA)
    return w


def key_bar(width, groups, scale=0.62, bg=30):
    """groups: [(title or None, [(key or None, label)])]. Returns the bar image (width wide, as tall as needed)."""
    groups = [(t, ks) for t, ks in groups if ks]
    rows, row, x = [], [], 14
    for title, keys in groups:
        w = _group_w(title, keys, scale)
        if row and x + w > width - 14:
            rows.append(row)
            row, x = [], 14
        row.append((title, keys, w))
        x += w + 26
    rows.append(row)
    row_h = int(46 * scale / 0.62)
    img = np.full((10 + row_h * len(rows), width, 3), bg, np.uint8)
    for r, row in enumerate(rows):
        y, x = 10 + r * row_h + int(row_h * 0.62), 14
        for g, (title, keys, w) in enumerate(row):
            if g:  # a thin divider between groups
                cv2.line(img, (x - 14, y - int(row_h * 0.45)), (x - 14, y + int(row_h * 0.15)), (90, 90, 90), 1)
            if title:
                cv2.putText(img, title.upper(), (x, y), FONT, scale * 0.8, DIM, 1, cv2.LINE_AA)
                x += cv2.getTextSize(title.upper(), FONT, scale * 0.8, 1)[0][0] + 12
            for key, label in keys:
                if key is None:
                    cv2.putText(img, label, (x, y), FONT, scale, WHITE, 1, cv2.LINE_AA)
                    x += _item_w(None, label, scale)
                    continue
                x += _keycap(img, x, y, key, scale) + 8
                cv2.putText(img, label, (x, y), FONT, scale, WHITE, 1, cv2.LINE_AA)
                x += cv2.getTextSize(label, FONT, scale, 1)[0][0] + 22
            x += 26
    return img


def keys_from_text(text):
    """The wizards' key hints ("c solve now   f fullscreen   q quit") as one group of (key, label) pairs."""
    out = []
    for part in re.split(r"\s{2,}", text.strip()):
        if not part:
            continue
        if part.lower().startswith("any key"):
            out.append((None, part[0].upper() + part[1:]))
            continue
        key, _, label = part.partition(" ")
        key = NAMED.get(key.lower(), key.upper() if len(key) <= 3 else key)
        out.append((key, label))
    return [(None, out)]
