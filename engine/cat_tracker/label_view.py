"""The labelling screen's picture handling: editable boxes (grab a corner or side to resize, the middle to move),
the mouse-wheel zoom, the boxes drawn at their own opacity, and the labelling preferences kept in my_data.

Pure logic where it can be (hit tests, edits, the zoom transform), so it's tested without a window.
"""

import json

import cv2
import numpy as np

from core.config import DATA

PREFS = DATA / "label_prefs.json"   # the sliders' values, kept between sessions
GRAB_PX = 9                         # how close (on screen) to an edge counts as grabbing it
MIN_BOX = 12                        # a box can't be smaller than this on a side (picture pixels): no specks
DUPLICATE_IOU = 0.8                 # two boxes overlapping this much are the same box: one is dropped
SLIDERS = (("blue_pct", "blue box"), ("box_pct", "boxes"), ("hint_pct", "hint"))
SLIDER_BAR_H = 52                   # the top bar: "TRANSPARENCY", its sliders, and the Help button
SIDE_W = 64                         # the brightness slider beside the picture
INFO_H = 56                         # the text bar under the picture (nothing is written on the picture itself)
HELP_W = 112
HELP_WIN = "Label the cat: help"


def load_prefs():
    try:
        p = json.loads(PREFS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        p = {}
    return {"blue_pct": int(p.get("blue_pct", 50)), "box_pct": int(p.get("box_pct", 100)), "hints": bool(p.get("hints", True)),
            "hint_pct": int(p.get("hint_pct", 60)), "bright_pct": int(p.get("bright_pct", 50))}


def save_prefs(prefs):
    try:
        PREFS.parent.mkdir(parents=True, exist_ok=True)
        PREFS.write_text(json.dumps(prefs), encoding="utf-8")
    except OSError:
        pass  # not remembered: harmless


def hit(boxes, x, y, tol):
    """What's under (x, y), in picture pixels: (box index, handle) or None. handle is a set of edges to move
    ({"l"}, {"t", "r"}, ...) or {"move"} for the inside. The smallest box under the point wins."""
    best = None
    for k, (x1, y1, x2, y2) in enumerate(boxes):
        if not (x1 - tol <= x <= x2 + tol and y1 - tol <= y <= y2 + tol):
            continue
        edges = set()
        if abs(x - x1) <= tol:
            edges.add("l")
        elif abs(x - x2) <= tol:
            edges.add("r")
        if abs(y - y1) <= tol:
            edges.add("t")
        elif abs(y - y2) <= tol:
            edges.add("b")
        if not edges:
            if not (x1 < x < x2 and y1 < y < y2):
                continue
            edges = {"move"}
        area = (x2 - x1) * (y2 - y1)
        if best is None or area < best[2]:
            best = (k, edges, area)
    return None if best is None else (best[0], best[1])


def edit(box, handle, dx, dy, w, h):
    """The box after dragging its handle by (dx, dy), kept inside the picture and at least MIN_BOX."""
    x1, y1, x2, y2 = box
    if "move" in handle:
        dx = min(max(dx, -x1), w - 1 - x2)
        dy = min(max(dy, -y1), h - 1 - y2)
        return [x1 + dx, y1 + dy, x2 + dx, y2 + dy]
    if "l" in handle:
        x1 = min(max(x1 + dx, 0), x2 - MIN_BOX)
    if "r" in handle:
        x2 = max(min(x2 + dx, w - 1), x1 + MIN_BOX)
    if "t" in handle:
        y1 = min(max(y1 + dy, 0), y2 - MIN_BOX)
    if "b" in handle:
        y2 = max(min(y2 + dy, h - 1), y1 + MIN_BOX)
    return [x1, y1, x2, y2]


class Zoom:
    """The part of the picture on screen: zoom 1 (all of it) to 8, around a centre. Screen = picture size."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.z, self.cx, self.cy = 1.0, w / 2, h / 2

    def origin(self):
        vw, vh = self.w / self.z, self.h / self.z
        x0 = min(max(self.cx - vw / 2, 0), self.w - vw)
        y0 = min(max(self.cy - vh / 2, 0), self.h - vh)
        return x0, y0

    def to_img(self, u, v):
        x0, y0 = self.origin()
        return x0 + u / self.z, y0 + v / self.z

    def to_screen(self, x, y):
        x0, y0 = self.origin()
        return (x - x0) * self.z, (y - y0) * self.z

    def _clamp(self):
        x0, y0 = self.origin()
        self.cx, self.cy = x0 + self.w / self.z / 2, y0 + self.h / self.z / 2

    def pan(self, du, dv):
        """Drag the zoomed view by (du, dv) screen pixels (middle mouse)."""
        self.cx -= du / self.z
        self.cy -= dv / self.z
        self._clamp()

    def centre_on(self, x, y):
        self.cx, self.cy = x, y
        self._clamp()

    def wheel(self, u, v, steps):
        """Zoom in (steps > 0) or out around the point under the cursor, which stays where it is."""
        x, y = self.to_img(u, v)
        self.z = float(min(max(self.z * (1.25 ** steps), 1.0), 8.0))
        # keep (x, y) under (u, v)
        x0, y0 = x - u / self.z, y - v / self.z
        self.cx, self.cy = x0 + self.w / self.z / 2, y0 + self.h / self.z / 2

    def view(self, img):
        if self.z == 1.0:
            return img.copy()
        x0, y0 = self.origin()
        crop = img[int(y0):int(y0 + self.h / self.z) + 1, int(x0):int(x0 + self.w / self.z) + 1]
        return cv2.resize(crop, (self.w, self.h), interpolation=cv2.INTER_LINEAR)


def draw_boxes(view, zoom, boxes, colours, pct, width=2, pad=0):
    """Box outlines blended over view at pct opacity (0-100)."""
    if not boxes or pct <= 0:
        return view
    over = view.copy()
    for b, col in zip(boxes, colours):
        p1 = zoom.to_screen(b[0] - pad, b[1] - pad)
        p2 = zoom.to_screen(b[2] + pad, b[3] + pad)
        cv2.rectangle(over, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), col, width, cv2.LINE_AA)
    a = pct / 100.0
    return cv2.addWeighted(over, a, view, 1 - a, 0) if a < 1 else over


def draw_handles(view, zoom, box, handle):
    """The hovered box's grab points (always fully visible), the hovered one bigger and yellow."""
    x1, y1, x2, y2 = box
    pts = {("l", "t"): (x1, y1), ("r", "t"): (x2, y1), ("l", "b"): (x1, y2), ("r", "b"): (x2, y2),
           ("l",): (x1, (y1 + y2) / 2), ("r",): (x2, (y1 + y2) / 2), ("t",): ((x1 + x2) / 2, y1),
           ("b",): ((x1 + x2) / 2, y2)}
    for key, (x, y) in pts.items():
        u, v = zoom.to_screen(x, y)
        on = handle is not None and set(key) == handle
        r = 4 if on else 2  # small marks; the grab area (GRAB_PX) stays as big as before
        cv2.rectangle(view, (int(u) - r, int(v) - r), (int(u) + r, int(v) + r), (0, 255, 255) if on else (255, 255, 255),
                      -1 if on else 1)
    if handle == {"move"}:
        p1, p2 = zoom.to_screen(x1, y1), zoom.to_screen(x2, y2)
        cv2.rectangle(view, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), (0, 255, 255), 1)
    return view


def too_small(box):
    return box[2] - box[0] < MIN_BOX or box[3] - box[1] < MIN_BOX


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / max((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter, 1e-9)


def nested(a, b, share=0.9):
    """Is the smaller of two boxes (almost) all inside the other? (A body box inside a box with the tail.)"""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy >= share * max(small, 1e-9)


def one_per_cat(boxes, cats=1):
    """The model's boxes for a picture, best first, cut to one per cat: a box inside a better one is the same cat
    (the model sometimes boxes the whole cat and, inside it, just the body), and beyond cats the rest go."""
    out = []
    for b in boxes:
        if all(not nested(b, o) and iou(b, o) <= DUPLICATE_IOU for o in out):
            out.append(b)
    return out[:max(1, int(cats))]


def dedupe(boxes):
    """The boxes without (near) duplicates: a later box overlapping an earlier one by DUPLICATE_IOU is dropped."""
    out = []
    for b in boxes:
        if all(iou(b, o) <= DUPLICATE_IOU for o in out):
            out.append(b)
    return out


def add_box(boxes, box, cats=1):
    """boxes with box added: never a speck, never a duplicate, at most one box per cat (the oldest goes)."""
    if too_small(box):
        return boxes, f"too small: boxes need at least {MIN_BOX} pixels a side"
    out = dedupe([b for b in boxes if iou(b, box) <= DUPLICATE_IOU] + [box])
    while len(out) > max(1, int(cats)):
        out.pop(0)
    return out, None


class Sliders:
    """The transparency sliders, drawn in a dark bar above the picture (OpenCV's own trackbars can't be coloured),
    under a TRANSPARENCY heading, with a Help button at the right. The help window draws a copy (same values)."""

    def __init__(self, prefs, width, on_change, help_button=True):
        self.prefs, self.w, self.on_change, self.help_button = prefs, width, on_change, help_button
        self.active = None
        self.help_clicked = False
        self.sessions_clicked = False
        self.undo_clicked = False
        self.undo_on = False  # UNDO STRETCH: lit when there's a no-cat stretch to undo
        self.helper = None    # TRAIN A HELPER: (text, fill, glow) from cat_tracker.helper, or None (not shown)
        self.helper_clicked = False
        self.helper_hover = False

    def _tracks(self):
        n = len(SLIDERS)
        usable = self.w - (2 * HELP_W + UNDO_W + 40 + (HELPER_W + 10 if self.helper else 0) if self.help_button else 0)
        part = usable / n
        for k, (key, label) in enumerate(SLIDERS):
            x0 = int(k * part + 14 + 9 * len(label) + 16)
            yield key, label, int(k * part + 14), x0, int((k + 1) * part - 60)

    def help_box(self):
        return (self.w - HELP_W - 10, 8, self.w - 10, SLIDER_BAR_H - 8)

    def sessions_box(self):
        return (self.w - 2 * HELP_W - 20, 8, self.w - HELP_W - 20, SLIDER_BAR_H - 8)

    def undo_box(self):
        return (self.w - 2 * HELP_W - UNDO_W - 30, 8, self.w - 2 * HELP_W - 30, SLIDER_BAR_H - 8)

    def helper_box(self):
        x = self.undo_box()[0] - 10
        return (x - HELPER_W, 8, x, SLIDER_BAR_H - 8)

    def mouse(self, ev, u, v):
        """Handles a mouse event at (u, v) in the bar. True if it was the sliders' (or the Help button's)."""
        if self.helper and self.help_button:
            x1, y1, x2, y2 = self.helper_box()
            inside = x1 <= u <= x2 and y1 <= v <= y2
            self.helper_hover = inside
            if inside and ev == cv2.EVENT_LBUTTONDOWN:
                self.helper_clicked = True
                return True
        if ev == cv2.EVENT_LBUTTONUP:
            hit, self.active = self.active is not None, None
            return hit
        if ev == cv2.EVENT_LBUTTONDOWN:
            if self.help_button:
                x1, y1, x2, y2 = self.help_box()
                if x1 <= u <= x2 and y1 <= v <= y2:
                    self.help_clicked = True
                    return True
                x1, y1, x2, y2 = self.sessions_box()
                if x1 <= u <= x2 and y1 <= v <= y2:
                    self.sessions_clicked = True
                    return True
                x1, y1, x2, y2 = self.undo_box()
                if x1 <= u <= x2 and y1 <= v <= y2:
                    self.undo_clicked = True  # (greyed: says there's nothing to undo)
                    return True
            for key, _, _, x0, x1 in self._tracks():
                if x0 - 8 <= u <= x1 + 8:
                    self.active = (key, x0, x1)
        if self.active and ev in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_MOUSEMOVE):
            key, x0, x1 = self.active
            self.prefs[key] = int(round(100 * min(max((u - x0) / max(x1 - x0, 1), 0), 1)))
            self.on_change()
            return True
        return False

    def draw(self):
        bar = np.full((SLIDER_BAR_H, self.w, 3), 30, np.uint8)  # the key bar's dark grey
        cv2.putText(bar, "TRANSPARENCY", (14, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1, cv2.LINE_AA)
        y = 36
        for key, label, lx, x0, x1 in self._tracks():
            cv2.putText(bar, label, (lx, y + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1, cv2.LINE_AA)
            cv2.line(bar, (x0, y), (x1, y), (80, 80, 80), 3, cv2.LINE_AA)
            xv = int(x0 + (x1 - x0) * self.prefs[key] / 100)
            cv2.line(bar, (x0, y), (xv, y), (0, 210, 255), 3, cv2.LINE_AA)
            cv2.circle(bar, (xv, y), 7, (0, 210, 255), -1, cv2.LINE_AA)
            cv2.putText(bar, f"{self.prefs[key]}%", (x1 + 12, y + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1,
                        cv2.LINE_AA)
        if self.help_button:
            x1, y1, x2, y2 = self.help_box()
            cv2.rectangle(bar, (x1, y1), (x2, y2), (0, 210, 255), -1)
            cv2.putText(bar, "? HELP", (x1 + 18, y2 - 11), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (20, 20, 20), 2, cv2.LINE_AA)
            x1, y1, x2, y2 = self.sessions_box()
            cv2.rectangle(bar, (x1, y1), (x2, y2), (240, 240, 240), -1)
            cv2.putText(bar, "SESSIONS", (x1 + 10, y2 - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (20, 20, 20), 2, cv2.LINE_AA)
            x1, y1, x2, y2 = self.undo_box()
            on = self.undo_on
            cv2.rectangle(bar, (x1, y1), (x2, y2), (255, 200, 80) if on else (60, 60, 60), -1 if on else 1)
            cv2.putText(bar, "UNDO STRETCH", (x1 + 10, y2 - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.52,
                        (20, 20, 20) if on else (110, 110, 110), 2 if on else 1, cv2.LINE_AA)
            if self.helper:
                from cat_tracker.helper import draw_button
                draw_button(bar, self.helper_box(), *self.helper)
        return bar


class Brightness:
    """A vertical slider beside the picture: the picture on screen brighter or darker (display only: the saved
    pictures and training never change). 50 = as it is."""

    def __init__(self, prefs, height, on_change):
        self.prefs, self.h, self.on_change = prefs, height, on_change
        self.active = False

    def _track(self):
        return 40, self.h - 30  # y top, y bottom

    def mouse(self, ev, u, v):
        if ev == cv2.EVENT_LBUTTONDOWN:
            self.active = True
        if ev == cv2.EVENT_LBUTTONUP:
            self.active = False
            return True
        if self.active and ev in (cv2.EVENT_LBUTTONDOWN, cv2.EVENT_MOUSEMOVE):
            y0, y1 = self._track()
            self.prefs["bright_pct"] = int(round(100 * min(max((y1 - v) / max(y1 - y0, 1), 0), 1)))
            self.on_change()
        return True

    def apply(self, view):
        v = self.prefs.get("bright_pct", 50)
        if v == 50:
            return view
        return cv2.convertScaleAbs(view, alpha=2 ** ((v - 50) / 50.0), beta=0)

    def draw(self):
        col = np.full((self.h, SIDE_W, 3), 30, np.uint8)
        cv2.putText(col, "BRIGHT", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150, 150, 150), 1, cv2.LINE_AA)
        y0, y1 = self._track()
        x = SIDE_W // 2
        cv2.line(col, (x, y0), (x, y1), (80, 80, 80), 3, cv2.LINE_AA)
        yv = int(y1 - (y1 - y0) * self.prefs.get("bright_pct", 50) / 100)
        cv2.line(col, (x, yv), (x, y1), (0, 210, 255), 3, cv2.LINE_AA)
        cv2.circle(col, (x, yv), 7, (0, 210, 255), -1, cv2.LINE_AA)
        cv2.putText(col, f"{self.prefs.get('bright_pct', 50)}%", (12, self.h - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (240, 240, 240), 1, cv2.LINE_AA)
        return col


def info_bar(width, left, right="", line2="", colour2=(200, 200, 200)):
    """The two lines of text under the picture (nothing is written on the picture)."""
    bar = np.full((INFO_H, width, 3), 22, np.uint8)
    cv2.putText(bar, left, (12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240, 240, 240), 1, cv2.LINE_AA)
    if right:
        (tw, _), _ = cv2.getTextSize(right, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.putText(bar, right, (width - tw - 12, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (170, 170, 170), 1, cv2.LINE_AA)
    if line2:
        cv2.putText(bar, line2, (12, 46), cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour2, 1, cv2.LINE_AA)
    return bar


def cursor_dot(view, uv):
    """A small green dot at the exact cursor point, ringed in black so it shows on any background."""
    if uv is None:
        return view
    u, v = int(uv[0]), int(uv[1])
    cv2.circle(view, (u, v), 4, (0, 0, 0), -1, cv2.LINE_AA)
    cv2.circle(view, (u, v), 2, (0, 255, 0), -1, cv2.LINE_AA)
    return view


HELP_TEXT = [
    ("Deciding (then it goes to the next picture)", None),
    ("Space", "the boxes are right. On an empty picture with the magenta hint, Space won't save no cat by mistake."),
    ("S", "no cat in this picture (clears the boxes)."),
    ("D", "not sure: skip it. It's kept, but left out of training."),
    ("A / Q", "back one picture / save and quit (next time you carry on where you stopped)."),
    (", and .", "back / forward one picture without deciding (hold to scrub). J jumps 10 ahead."),
    ("N ... N", "a stretch with no cat: press N on its first picture, move to its last (it shows blue on the"),
    ("", "timeline), press N again: every picture in it becomes no cat, boxes deleted, whatever it was before."),
    ("", "Esc cancels one you've started. Z undoes it right after."),
    ("UNDO STRETCH or U", "undoes the latest stretch, even after more labelling (it's saved with the session); each"),
    ("", "press goes one stretch further back. Pictures you changed since are kept as you left them."),
    ("Timeline", "the strip under the picture: this camera's pictures in order. Green cat, grey no cat, yellow"),
    ("", "skipped, orange auto box, dark to do. Under it, only where it needs you: magenta, to do with the hint"),
    ("", "and no box yet; red, marked no cat but the other cameras see the cat. White: this picture."),
    ("", "Click or drag on it to jump; the arrow keys step (like , and .)."),
    ("Holding S or Space", "stops by itself where it matters: S at a box or the hint, Space at an empty picture,"),
    ("", "the hint or CHECK THIS. Let go and press again to go on."),
    ("Boxes", None),
    ("Click on the cat", "a box snaps to it: the quickest way. Drag only if it's off."),
    ("", "Clicking inside a box that's a bit off snaps a better one."),
    ("Drag on an empty spot", "draws a box yourself. Tiny boxes (under 12 pixels a side) aren't drawn."),
    ("Drag a corner or side", "resizes the box; drag its middle to move it. The small squares show where to grab."),
    ("Right-click in a box", "deletes it.   Z: undo (boxes, edits, deletions)."),
    ("W", "puts a green box where the blue one is. Then Space if it's right."),
    ("One box per cat", "a new box replaces the old one (more cats: label, cats in settings\\cat_tracker.yaml)."),
    ("Seeing better", None),
    ("Mouse wheel", "zooms in around the cursor. Hold the middle mouse button and drag to move the zoomed view."),
    ("Next picture", "while zoomed, the view follows the box (or the hint) into the next picture."),
    ("Bright slider", "on the right of the picture: brighter or darker on screen only. Nothing saved changes."),
    ("H", "the magenta hint on or off."),
    ("Helper", None),
    ("TRAIN A HELPER", "teaches a quick helper from the pictures you've decided, so it suggests better boxes for"),
    ("", "the rest (orange, to check). Your tracker isn't changed. It lights up once enough are decided."),
    ("", "Training takes about 3 minutes; keep labelling meanwhile. A teal line on the timeline: learned from."),
    ("Sessions", None),
    ("SESSIONS or Tab", "every session in two lists, waiting for labels and done. Click one to open it; done ones open"),
    ("", "for review (backed up first). Practice copy: a throwaway copy, nothing reaches training."),
    ("Filter: All", "every picture in the session."),
    ("With cat / No cat", "pictures with a cat box / you marked as no cat (these teach it what isn't a cat)."),
    ("Skipped", "pictures you skipped with D because you weren't sure; left out of training."),
    ("Check this", "auto boxes you haven't double-checked yet. Each one you decide drops off the list."),
    ("Too many boxes", "pictures with more boxes than cats. Keep one per cat."),
    ("Possible mistakes", "marked no cat, but the other cameras see her. Each one you decide drops off."),
    ("How to box", None),
    ("Only what you see", "box the part of the cat you can see, tight around the fur. Never guess hidden parts."),
    ("Tail", "leave a sticking-out tail outside the box; include it only when it's curled against the body."),
    ("Can't tell", "a blur or only a tail tip: D. No cat at all: S."),
]


def help_page(prefs, width=1000):
    """The help window: the kinds of boxes with drawn examples, the transparency sliders (working, the same values
    as the main window), a divider, then every feature in plain words. Returns (image, sliders, sliders' y)."""
    rows = []
    top = np.full((250, width, 3), 36, np.uint8)
    cv2.putText(top, "What's on the picture", (20, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (240, 240, 240), 2, cv2.LINE_AA)
    items = [("green", "a box: the cat is here. Drag its corners or sides to fit it to the cat."),
             ("orange", "filled in for you (autolabel). Check it: is the cat really there, and boxed tightly?"),
             ("blue", "the box from this camera's previous picture. W copies it, if the cat hasn't moved."),
             ("hint", "magenta cross: the other cameras see the cat here. Only a hint: click it to snap a box."),
             ("handles", "small squares on the box under the mouse: grab one to resize, or the middle to move.")]
    for k, (kind, text) in enumerate(items):
        y = 62 + k * 38
        x1, y1, x2, y2 = 24, y - 12, 74, y + 16
        if kind == "green":
            cv2.rectangle(top, (x1, y1), (x2, y2), (0, 255, 0), 2)
        elif kind == "orange":
            cv2.rectangle(top, (x1, y1), (x2, y2), (0, 165, 255), 2)
        elif kind == "blue":
            cv2.rectangle(top, (x1 - 3, y1 - 3), (x2 + 3, y2 + 3), (255, 80, 0), 3)
        elif kind == "hint":
            cx, cy = 49, y + 2
            for a, b in (((cx - 14, cy), (cx - 4, cy)), ((cx + 4, cy), (cx + 14, cy)),
                         ((cx, cy - 12), (cx, cy - 4)), ((cx, cy + 4), (cx, cy + 12))):
                cv2.line(top, a, b, (255, 0, 255), 2, cv2.LINE_AA)
        else:
            cv2.rectangle(top, (x1, y1), (x2, y2), (0, 255, 0), 1)
            for px, py in ((x1, y1), (x2, y1), (x1, y2), ((x1 + x2) // 2, y1), (x2, (y1 + y2) // 2)):
                cv2.rectangle(top, (px - 2, py - 2), (px + 2, py + 2), (255, 255, 255), 1)
            cv2.rectangle(top, (x2 - 4, y2 - 4), (x2 + 4, y2 + 4), (0, 255, 255), -1)
        cv2.putText(top, text, (96, y + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (230, 230, 230), 1, cv2.LINE_AA)
    rows.append(top)
    mid = np.full((40, width, 3), 36, np.uint8)
    cv2.putText(mid, "Transparency: how see-through the blue box, your boxes and the hint are. Lower = fainter. "
                "These are the same sliders:", (20, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (230, 230, 230), 1, cv2.LINE_AA)
    rows.append(mid)
    sl = Sliders(prefs, width, lambda: save_prefs(prefs), help_button=False)
    slider_y = sum(r.shape[0] for r in rows)
    rows.append(sl.draw())
    line = np.full((24, width, 3), 36, np.uint8)
    cv2.line(line, (20, 12), (width - 20, 12), (120, 120, 120), 1)
    rows.append(line)
    body = np.full((30 * len(HELP_TEXT) + 20, width, 3), 36, np.uint8)
    y = 24
    for key, text in HELP_TEXT:
        if text is None:
            cv2.putText(body, key.upper(), (20, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 210, 255), 1, cv2.LINE_AA)
        else:
            cv2.putText(body, key, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 210, 255), 1, cv2.LINE_AA)
            cv2.putText(body, text, (250, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (230, 230, 230), 1, cv2.LINE_AA)
        y += 30
    rows.append(body)
    return cv2.vconcat(rows), sl, slider_y


UNDO_W = 150
HELPER_W = 170  # TRAIN A HELPER (cat_tracker.helper)
TIMELINE_H = 30
TL_COLOURS = {"cat": (80, 200, 80), "nocat": (140, 140, 140), "skipped": (0, 210, 255), "auto": (0, 140, 255),
              "todo": (60, 60, 60), "hint": (255, 0, 255), "mistake": (60, 60, 255),
              "helper": (200, 190, 0)}  # BGR; helper: a thin line, the pictures a helper learned from
TL_LEGEND = [("cat", "cat"), ("nocat", "no cat"), ("skipped", "skipped"), ("auto", "auto box"), ("todo", "to do"),
             ("hint", "box it?"), ("mistake", "maybe wrong")]
TL_STATUS = ["cat", "nocat", "skipped", "auto", "todo"]


class Timeline:
    """The strip under the picture: one tick per picture of this camera, in order, coloured by what's decided; a
    row under it marks the hint (magenta) and possible mistakes (red); white: this picture. Drawn with numpy in one
    go (well under a millisecond for 1,300 pictures). index(u) is the picture under a click."""

    def __init__(self, w):
        self.w = w
        self.legend = self._legend() if w >= 900 else None  # a small window: the strip alone
        self.x1, self.x2 = 10, w - (420 if self.legend is not None else 10)

    def _legend(self):
        img = np.full((TIMELINE_H, 410, 3), 30, np.uint8)
        x = 4
        for key, word in TL_LEGEND:
            cv2.rectangle(img, (x, 10), (x + 9, 19), TL_COLOURS[key], -1)
            cv2.putText(img, word, (x + 13, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (200, 200, 200), 1, cv2.LINE_AA)
            (tw, _), _ = cv2.getTextSize(word, cv2.FONT_HERSHEY_SIMPLEX, 0.36, 1)
            x += tw + 22
        return img

    def _cols(self, n):
        tw = self.x2 - self.x1
        return np.minimum(np.arange(tw) * n // tw, n - 1)

    def x_of(self, j, n):
        return int(self.x1 + (j + 0.5) * (self.x2 - self.x1) / max(n, 1))

    def index(self, u, n):
        if n <= 0:
            return None
        u = min(max(u, self.x1), self.x2 - 1)
        return int((u - self.x1) * n // (self.x2 - self.x1))

    def draw(self, status, marks, cur, band=None, used=None):
        """status: a TL_STATUS name per picture; marks: per picture 0 (none), 1 (hint) or 2 (possible mistake);
        cur: this picture's place; band: (a, b) of an N stretch being chosen, or None; used: per picture, True if a
        helper learned from it (a thin teal line at the bottom)."""
        img = np.full((TIMELINE_H, self.w, 3), 30, np.uint8)
        n = len(status)
        if n:
            pal = np.array([TL_COLOURS[k] for k in TL_STATUS], np.uint8)
            codes = np.array([TL_STATUS.index(s) for s in status])
            idx = self._cols(n)
            img[4:18, self.x1:self.x2] = pal[codes[idx]][None]
            m = np.array(marks)[idx]
            img[20:24, self.x1:self.x2][:, m == 1] = TL_COLOURS["hint"]
            img[20:24, self.x1:self.x2][:, m == 2] = TL_COLOURS["mistake"]
            if used is not None and any(used):
                img[26:29, self.x1:self.x2][:, np.array(used, bool)[idx]] = TL_COLOURS["helper"]
            if band is not None:
                a, b = self.x_of(band[0], n), self.x_of(band[1], n)
                sub = img[2:20, min(a, b) - 1:max(a, b) + 2]
                sub[:] = (sub * 0.5 + np.array([255, 200, 80]) * 0.5).astype(np.uint8)
            x = self.x_of(cur, n)
            cv2.rectangle(img, (x - 1, 0), (x + 1, 26), (255, 255, 255), -1)
        if self.legend is not None:
            img[:, self.w - 410:] = self.legend
        return img


class Pace:  # (not shown any more: its estimate was off, and more discouraging than useful)
    """Time left from your own pace: the average of your last 20 decisions (pauses over a minute don't count)."""

    def __init__(self):
        self.last, self.times = None, []

    def decided(self, now):
        if self.last is not None and now - self.last < 60:
            self.times = (self.times + [now - self.last])[-20:]
        self.last = now

    def left(self, remaining):
        if len(self.times) < 3:
            return ""
        m = remaining * float(np.mean(self.times)) / 60
        return f"about {m:.0f} min left" if m >= 1 else "under a minute left"


class Hints:
    """Where the other cameras place the cat at the same moment, projected into this picture: a hint (crosshair and a
    faint outline about cat size) for a picture with no box. From their boxes in this session (2 or more of them),
    triangulated with the room calibration as the tracker does. None when it can't be worked out."""

    def __init__(self, ses, w=1280, h=720):
        self.ses, self.w, self.h = ses, w, h
        self.ok = False
        try:
            from calibration.room import cameras_in_order
            from capture.camera import camera_keys, camera_names
            from cat_tracker import settings
            from cat_tracker.locate import room_bounds
            from fusion.triangulate import Rig
            from tools.calib_room import load_intrinsics
            cfg = settings.load()
            keys = camera_keys(cfg)
            self.names = camera_names(cfg)
            cal = DATA / "calibration"
            self.room = cameras_in_order(json.loads((cal / "room.json").read_text(encoding="utf-8")), keys)
            self.I = load_intrinsics(cal, keys)
            self.rig = Rig(self.room, self.I)
            self.lc = dict(cfg["cat"]["locate"])
            self.bounds = room_bounds(self.rig, float(self.lc.get("room_margin_m", 0.15)))
            self.ok = True
        except Exception:  # noqa: BLE001  (no calibration, or another camera set: no hints, nothing else changes)
            pass

    def at(self, stem):
        """(centre (u, v), outline box) in picture pixels, or None."""
        if not self.ok:
            return None
        from cat_tracker.label import read_boxes
        from cat_tracker.locate import locate, outline_box
        from calibration import intrinsics as intr
        name, m = stem.rsplit("_", 1)
        if name not in self.names:
            return None
        c = self.names.index(name)
        per = []
        for k, n in enumerate(self.names):
            b = [] if k == c else read_boxes(self.ses / "labels" / f"{n}_{m}.txt", self.w, self.h)
            per.append(np.array([[*bb, 1.0] for bb in b]).reshape(-1, 5))
        if sum(len(p) > 0 for p in per) < 2:
            return None
        X, used, how, _ = locate(self.rig, per, self.lc, self.bounds)
        if X is None or how != "triangulated":
            return None
        cam = self.room["cameras"][c]
        R, _ = cv2.Rodrigues(np.array(cam["rvec"], np.float64))
        if (R @ X + np.array(cam["tvec"]))[2] <= 0.1:
            return None
        p = intr.project(np.array([X]), np.array(cam["rvec"]), np.array(cam["tvec"]), self.I[c]).reshape(-1, 2)[0]
        if not (0 <= p[0] < self.w and 0 <= p[1] < self.h):
            return None
        box = outline_box(cam, self.I[c], X, 0.22 / 1.21 * 1.0, 0.15 / 1.31, self.w, self.h)
        return (float(p[0]), float(p[1])), box


def draw_hint(view, zoom, hint, pct=60, colour=(255, 0, 255)):
    """A thin crosshair and a faint dashed outline: a hint, never a box."""
    (x, y), box = hint
    u, v = zoom.to_screen(x, y)
    over = view.copy()
    for a, b in (((u - 18, v), (u - 5, v)), ((u + 5, v), (u + 18, v)), ((u, v - 18), (u, v - 5)), ((u, v + 5), (u, v + 18))):
        cv2.line(over, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), colour, 2, cv2.LINE_AA)
    if box is not None:
        p1, p2 = zoom.to_screen(box[0], box[1]), zoom.to_screen(box[2], box[3])
        for t in np.linspace(0, 1, 13)[::2]:  # dashed: short pieces along each side
            for (ax, ay), (bx, by) in (((p1[0], p1[1]), (p2[0], p1[1])), ((p2[0], p1[1]), (p2[0], p2[1])),
                                       ((p2[0], p2[1]), (p1[0], p2[1])), ((p1[0], p2[1]), (p1[0], p1[1]))):
                s, e = t, min(t + 1 / 12, 1)
                cv2.line(over, (int(ax + (bx - ax) * s), int(ay + (by - ay) * s)),
                         (int(ax + (bx - ax) * e), int(ay + (by - ay) * e)), colour, 1, cv2.LINE_AA)
    a = max(0, min(pct, 100)) / 100.0
    return cv2.addWeighted(over, a, view, 1 - a, 0)
