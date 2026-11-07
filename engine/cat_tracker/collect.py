"""Saving camera frames of the cat for training, with the current detector's boxes as first-guess labels.

Each capture session goes in my_data/captures/<date>-<time>/ as images/<camera>_<n>.jpg and
labels/<camera>_<n>.txt (YOLO format: class cx cy w h, all 0-1), plus moments.csv with the time of
each moment. The labels are only the stock model's guesses; 2_label.bat first fills in cameras and
moments it missed (cat_tracker.autolabel), then is where they're checked before training.
"""

import shutil
import time
from concurrent.futures import ThreadPoolExecutor

import cv2

from cat_tracker.locate import _foot, _inside


ENOUGH_SAID = ("That's enough with your cat. Next, pictures without it: take your cat out and close the door so it "
               "can't come back in. Then press N twice for no cat, and move around the room.")
NOCAT_ASK = ("Take your cat out and close the door so it can't come back in. Then press N again (or NO CAT) to start. "
             "Every picture from then on is saved as no cat. Esc: never mind.")
NOCAT_FILE = "nocat_capture.json"  # {picture: the model's best score in it} for pictures taken with NO CAT on
NOCAT_FLAG = 0.4   # a NO CAT picture where the model still saw something this cat-like: "possible mistakes" in 2_label


def nocat_flagged(ses):
    """NO CAT pictures where the model saw something cat-like (to check in 2_label's Possible mistakes)."""
    import json
    try:
        d = json.loads((ses / NOCAT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {st for st, sc in d.items() if sc >= NOCAT_FLAG}


class FrameSaver:
    """enough_moments / enough_spots: a rough guide for when there's enough to train on (docs/technical/
    settings_reference.md): moments where the stock model already boxed the cat in at least one camera, in at least
    that many different spots of the floor (spot_m squares). Training warns under 50 images with the cat and does
    well from a few hundred; about 150 such moments give 300 or more images with it (the cat is usually boxed in 2
    of 4 cameras, and autolabel fills in more), and spread over the floor, not all of it one nap."""

    def __init__(self, root, names, every_s=1.0, min_free_gb=5.0, log=None, enough_moments=150, enough_spots=3,
                 spot_m=0.75):
        self.dir = root / time.strftime("%Y%m%d-%H%M%S")
        (self.dir / "images").mkdir(parents=True, exist_ok=True)
        (self.dir / "labels").mkdir(parents=True, exist_ok=True)
        self.names, self.every, self.min_free = names, every_s, min_free_gb
        self.log = log
        self.n = 0
        self.last = -1e9
        self.on = True
        self._pool = ThreadPoolExecutor(2)
        self.cats = 1          # boxes kept per picture (settings: cat.label.cats; run.py sets it)
        self.seen = 0          # moments where the cat was boxed in at least one camera
        self.nocat = False     # NO CAT (N): the cat is out of the room; pictures saved as decided "no cat"
        self.nocat_n = 0       # moments taken with NO CAT on
        self.nocat_scores = {}
        self.nocat_asked = False  # N pressed once: its instruction stays up until N again (on) or Esc (cancel)
        self.spots = set()     # the floor squares it was seen in
        self.enough_moments, self.enough_spots, self.spot_m = int(enough_moments), int(enough_spots), float(spot_m)

    def press_nocat(self, now):
        """N (or the NO CAT button): "ask" (the first press: what to do first, cat out and door closed; it stays up,
        taking the cat out can take a while), "on" (the next press), or "off" (it was on: the cat is back). It can't
        be switched on without the instruction having been shown. now: unused (kept for callers)."""
        if self.nocat:
            self.nocat = False
            return "off"
        if not self.nocat_asked:
            self.nocat_asked = True
            return "ask"
        self.nocat_asked, self.nocat = False, True
        return "on"

    def cancel_nocat(self):
        """Esc while the instruction is up: never mind. True if there was one to cancel."""
        was, self.nocat_asked = self.nocat_asked, False
        return was

    def asking(self, now):
        """True while the NO CAT instruction waits for its second press."""
        return not self.nocat and self.nocat_asked

    @property
    def enough(self):
        return self.seen >= self.enough_moments and len(self.spots) >= self.enough_spots

    def progress(self):
        """The line for the window's banner."""
        if self.nocat:
            return (f"CAPTURING  NO CAT (the cat is out of the room; N when it's back): {self.nocat_n} moments saved as "
                    f"no cat   with the cat: {self.seen}")
        if self.enough:
            return (f"CAPTURING  with the cat: {self.seen} (enough for a first model)   without: {self.n - self.seen}"
                    "   NEXT: cat out, door closed, then N twice (no cat)")
        spots = "" if len(self.spots) >= self.enough_spots else f", {len(self.spots)}/{self.enough_spots} spots"
        return (f"CAPTURING  with the cat: {self.seen} (about {self.enough_moments} is enough for a first model{spots})   "
                f"without: {self.n - self.seen}")

    def __call__(self, items, boxes_all, rig, lc, bounds, now):
        """Save one frame per camera if it's time. Returns False once the disk is too full."""
        if not self.on or now - self.last < self.every:
            return True
        if shutil.disk_usage(self.dir).free / 1e9 < self.min_free:
            self.on = False
            if self.log:
                self.log.warning("Stopped capturing: under %.0f GB free", self.min_free)
            return False
        self.last = now
        if self.nocat:
            return self._save_nocat(items, boxes_all, now)
        floor_y = float(lc.get("floor_y_m", 0.0))
        any_cat = False
        for c, it in enumerate(items):
            frame = it[0]
            h, w = frame.shape[:2]
            rows = []
            from cat_tracker.label_view import one_per_cat
            for b in one_per_cat(list(boxes_all[c]), self.cats):  # one box per cat, never one inside another
                X = _foot(rig, c, b, floor_y)
                if _inside(X, bounds):  # leave out pictures on the walls
                    if not any_cat:
                        any_cat = True
                        self.spots.add((int(X[0] // self.spot_m), int(X[2] // self.spot_m)))
                    rows.append("0 %.6f %.6f %.6f %.6f" % ((b[0] + b[2]) / 2 / w, (b[1] + b[3]) / 2 / h,
                                                          (b[2] - b[0]) / w, (b[3] - b[1]) / h))
            stem = f"{self.names[c]}_{self.n:06d}"
            self._pool.submit(cv2.imwrite, str(self.dir / "images" / f"{stem}.jpg"), frame.copy(),
                              [cv2.IMWRITE_JPEG_QUALITY, 92])
            (self.dir / "labels" / f"{stem}.txt").write_text("\n".join(rows), encoding="utf-8")
        with open(self.dir / "moments.csv", "a", encoding="utf-8") as f:  # when each moment was taken, for autolabel
            f.write(f"{self.n},{now:.3f}\n")
        self.n += 1
        self.seen += any_cat
        return True

    def _save_nocat(self, items, boxes_all, now):
        """NO CAT on: every camera's picture saved with no box and decided ("no cat"), so 2_label needn't ask. The
        model's best score in each is kept: where it still saw something cat-like (NOCAT_FLAG), the picture isn't
        confirmed and shows in 2_label's Possible mistakes, in case the cat came back."""
        import json
        stems, sure = [], []
        for c, it in enumerate(items):
            frame = it[0]
            stem = f"{self.names[c]}_{self.n:06d}"
            self._pool.submit(cv2.imwrite, str(self.dir / "images" / f"{stem}.jpg"), frame.copy(),
                              [cv2.IMWRITE_JPEG_QUALITY, 92])
            (self.dir / "labels" / f"{stem}.txt").write_text("", encoding="utf-8")
            best = max((float(b[4]) for b in boxes_all[c] if len(b) > 4), default=0.0)
            self.nocat_scores[stem] = round(best, 3)
            stems.append(stem)
            if best < NOCAT_FLAG:
                sure.append(stem)
        for fn, add in (("checked.txt", stems), ("confirmed.txt", sure)):
            if add:
                with open(self.dir / fn, "a", encoding="utf-8") as f:
                    f.write("\n" + "\n".join(add))
        (self.dir / NOCAT_FILE).write_text(json.dumps(self.nocat_scores, indent=1), encoding="utf-8")
        with open(self.dir / "moments.csv", "a", encoding="utf-8") as f:
            f.write(f"{self.n},{now:.3f}\n")
        self.n += 1
        self.nocat_n += 1
        return True

    def close(self):
        self._pool.shutdown(wait=True)
        if self.log:
            self.log.info("Captured %d moments (%d images) to %s", self.n, self.n * len(self.names), self.dir)
