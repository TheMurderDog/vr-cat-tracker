"""The sessions screen inside 2_label's window: every labelled session in two lists, "Waiting for labels" (pictures
still to decide) and "Done" (all decided), each a big clickable row with its date, where it came from, the camera
setup and a progress bar. Click a row to open it (a waiting one starts at its first undecided picture; a done one
opens for review, backed up first). The filter chips choose which pictures open; "Practice copy" opens a throwaway
copy (a red band; nothing reaches training); "Open folder" shows the session's folder in Windows Explorer.
The folders on disk never move: the lists are worked out from what's decided.
"""

import cv2
import numpy as np

W, H = 1344, 930
ROW_H, TOP_H = 46, 140
FILTER_CHIPS = [("all", "All"), ("cat", "With cat"), ("nocat", "No cat"), ("skipped", "Skipped"),
                ("check", "Check this"), ("extra", "Too many boxes"), ("mistake", "Possible mistakes")]
FILTER_SAYS = {  # shown under the chips for the one picked (and in the help window)
    "all": "Every picture in the session.",
    "cat": "Pictures with at least one cat box.",
    "nocat": "Pictures you marked as having no cat. These teach the model what isn't a cat.",
    "skipped": "Pictures you skipped with D because you weren't sure. They're left out of training.",
    "check": "Auto boxes you haven't double-checked yet (orange, CHECK THIS: the autolabeler wasn't confident). Each one "
             "you decide here drops off.",
    "extra": "Pictures with more boxes than cats. Keep one per cat.",
    "mistake": "Pictures you marked no cat where the other cameras see her (current setup only). Each one you decide "
               "here drops off.",
}
COUNT_FOR = {"all": "pictures", "cat": "with cat", "nocat": "no cat", "skipped": "skipped", "check": "check this",
             "extra": "more boxes than cats", "mistake": "possible mistakes"}  # the session.json count each filter needs above 0 to list a session
YELLOW, WHITE, DIM, GREEN = (0, 210, 255), (240, 240, 240), (150, 150, 150), (80, 220, 80)


def _txt(img, text, x, y, scale=0.55, col=WHITE, th=1):
    cv2.putText(img, text, (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX, scale, col, th, cv2.LINE_AA)


class Panel:
    """Draws the screen and works out what a click hit. rows: sessions.info() dicts."""

    def __init__(self, rows, can_close=False, filt="all"):
        self.can_close, self.scroll = can_close, 0
        self.rows = sorted(rows, key=lambda r: r["session"], reverse=True)  # newest first
        self.set_filter(filt)
        self.hits = []  # (x1, y1, x2, y2, action)

    def set_filter(self, filt):
        """Only sessions that have something the filter looks for are listed (with All: every session)."""
        self.filt, self.scroll = filt, 0
        key = COUNT_FOR.get(filt, "pictures")
        rows = [r for r in self.rows if r.get(key, 0) > 0]
        self.hidden = len(self.rows) - len(rows)
        waiting = [r for r in rows if r["undecided"] > 0]
        done = [r for r in rows if r["undecided"] == 0 and r["pictures"]]
        self.items = ([("head", f"WAITING FOR LABELS ({len(waiting)})")] + [("row", r) for r in waiting] +
                      [("head", f"DONE ({len(done)})")] + [("row", r) for r in done])
        if not rows:
            self.items = [("head", "Nothing matches this filter.")]

    def draw(self):
        img = np.full((H, W, 3), 26, np.uint8)
        self.hits = []
        _txt(img, "SESSIONS", 20, 36, 0.9, WHITE, 2)
        _txt(img, "Click a session to open it. Waiting ones start at the first picture to decide; done ones open for "
                  "review (backed up first). The wheel scrolls.", 20, 62, 0.5, DIM)
        x = 20
        _txt(img, "OPEN:", x, 96, 0.5, DIM)
        x += 60
        for key, label in FILTER_CHIPS:
            (tw, _), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            on = key == self.filt
            cv2.rectangle(img, (x, 78), (x + tw + 20, 104), YELLOW if on else (70, 70, 70), -1 if on else 1)
            _txt(img, label, x + 10, 96, 0.5, (20, 20, 20) if on else WHITE)
            self.hits.append((x, 78, x + tw + 20, 104, ("filter", key)))
            x += tw + 32
        _txt(img, FILTER_SAYS.get(self.filt, ""), 80, 126, 0.5, YELLOW)
        bx = W - 150
        cv2.rectangle(img, (bx, 18), (W - 20, 50), YELLOW if self.can_close else (60, 60, 60), -1)
        _txt(img, "CLOSE" if self.can_close else "Q: quit", bx + 32, 40, 0.6, (20, 20, 20), 2)
        self.hits.append((bx, 18, W - 20, 50, ("close", None)))
        y = TOP_H - self.scroll
        for kind, it in self.items:
            if kind == "head":
                if TOP_H <= y + 30 <= H:
                    _txt(img, it, 20, y + 30, 0.55, YELLOW)
                y += 40
                continue
            if y + ROW_H > TOP_H and y < H:
                self._row(img, y, it)
            y += ROW_H
        if self.hidden and self.filt != "all":
            n = self.hidden
            _txt(img, f"{n} session{'s' if n != 1 else ''} hidden: nothing matches this filter", 20, H - 12, 0.5, DIM)
        self.max_scroll = max(0, y + self.scroll - H + 40)
        return img

    def _row(self, img, y, r):
        y1, y2 = y + 4, y + ROW_H - 4
        cv2.rectangle(img, (16, y1), (W - 16, y2), (44, 44, 44), -1)
        self.hits.append((16, y1, W - 330, y2, ("open", r["session"])))
        _txt(img, r["date"] or r["session"], 30, y1 + 25, 0.6, WHITE)
        if r.get("role") == "test":
            _txt(img, "TEST SET: not trained on", 230, y1 + 25, 0.5, (255, 200, 80), 2)
        else:
            _txt(img, f"{r['source']}, {r['camera setup']} setup", 230, y1 + 25, 0.5, DIM)
        # progress: decided of all pictures
        done = r["decided"] + r["skipped"]
        px1, px2 = 650, 850
        cv2.rectangle(img, (px1, y1 + 13), (px2, y1 + 25), (70, 70, 70), -1)
        fill = int((px2 - px1) * done / max(r["pictures"], 1))
        cv2.rectangle(img, (px1, y1 + 13), (px1 + fill, y1 + 25), GREEN, -1)
        _txt(img, f"{done} / {r['pictures']} decided", px2 + 12, y1 + 25, 0.5, WHITE)
        if self.filt != "all":  # how many pictures this filter opens here
            label = {"mistake": "maybe wrong", "extra": "too many"}.get(self.filt, dict(FILTER_CHIPS)[self.filt].lower())
            _txt(img, f"{r.get(COUNT_FOR[self.filt], 0)} {label}", 545, y1 + 25, 0.5, YELLOW)
        for k, (label, action) in enumerate((("Practice copy", "practice"), ("Open folder", "folder"))):
            bx1 = W - 320 + k * 155
            cv2.rectangle(img, (bx1, y1 + 6), (bx1 + 145, y2 - 6), (70, 70, 70), 1)
            _txt(img, label, bx1 + 14, y1 + 25, 0.5, WHITE)
            self.hits.append((bx1, y1 + 6, bx1 + 145, y2 - 6, (action, r["session"])))

    def click(self, u, v):
        """What a click at (u, v) means: ("open"|"practice"|"folder"|"filter"|"close", value), or None."""
        for x1, y1, x2, y2, action in reversed(self.hits):  # the buttons are drawn after (over) the row
            if x1 <= u <= x2 and y1 <= v <= y2:
                return action
        return None


def choose(win, rows, can_close=False, filt="all", wait_key=None):
    """Show the screen in win until a session is picked. Returns ("open", name, filter, practice), ("close", filter)
    or ("quit", filter). Opening a folder in Explorer doesn't leave the screen."""
    import os
    panel = Panel(rows, can_close, filt)
    picked = []

    def on_mouse(ev, u, v, flags, _):
        if ev == cv2.EVENT_LBUTTONDOWN:
            a = panel.click(u, v)
            if a:
                picked.append(a)
        elif ev == cv2.EVENT_MOUSEWHEEL:
            panel.scroll = int(min(max(panel.scroll - (60 if flags > 0 else -60), 0), getattr(panel, "max_scroll", 0)))

    cv2.setMouseCallback(win, on_mouse)
    wait_key = wait_key or cv2.waitKey
    root = rows[0].get("_root") if rows else None
    while True:
        cv2.imshow(win, panel.draw())
        k = wait_key(30) & 0xFF
        if k in (ord("q"), 27):
            return ("close", panel.filt) if can_close and k == 27 else ("quit", panel.filt)
        if k == 9 and can_close:  # Tab again: back to the picture
            return ("close", panel.filt)
        while picked:
            kind, value = picked.pop(0)
            if kind == "filter":
                panel.set_filter(value)
            elif kind == "close":
                return ("close", panel.filt) if can_close else ("quit", panel.filt)
            elif kind == "folder":
                path = next((r["_path"] for r in rows if r["session"] == value), None)
                if path:
                    try:
                        os.startfile(str(path))  # Windows Explorer, on that session's folder
                    except (OSError, AttributeError):
                        pass
            elif kind in ("open", "practice"):
                return ("open", value, panel.filt, kind == "practice")
