"""Saves the moments the detector struggled with, for the next training round, while the tracker runs.

A moment is only saved when she is *sure* from other angles (two or more cameras confidently agree
on her position) and at least one camera that should see her didn't, or only weakly did. So nothing
is saved while she's out of the room, and every saved moment is one the model got partly wrong.
Each tracker run gets one session folder in cat_tracker/captures (<date>-<time>-hard), made only once
the first moment is saved, in the same layout as capture.bat, so label.bat and train.bat take it as is.
The boxes added for the cameras that missed her are marked in auto.json, so label.bat shows them in
orange for you to check. A run stops saving after max_moments, or when the disk gets low.
"""

import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor

import cv2

from cat_tracker.locate import _foot, _inside, outline_box


class HardSaver:
    def __init__(self, root, names, hc, lc, log):
        self.root, self.names, self.log = root, names, log
        self.every = float(hc.get("every_s", 3.0))
        self.max_moments = int(hc.get("max_moments", 150))
        self.min_free = float(hc.get("min_free_gb", 10))
        self.min_strong = int(hc.get("min_sure_cameras", 2))
        self.radius = float(lc.get("outline_radius_m", 0.22))
        self.half_h = float(lc.get("outline_half_height_m", 0.15))
        self.floor_y = float(lc.get("floor_y_m", 0.0))
        self.dir = None
        self.n = 0
        self.last = -1e9
        self.on = True
        self.auto = {}
        self._pool = ThreadPoolExecutor(2)

    def _start(self):
        self.dir = self.root / (time.strftime("%Y%m%d-%H%M%S") + "-hard")
        (self.dir / "images").mkdir(parents=True, exist_ok=True)
        (self.dir / "labels").mkdir(parents=True, exist_ok=True)
        self.log.info("Saving moments the model struggled with to %s (at most %d)", self.dir, self.max_moments)

    def __call__(self, items, strong_picked, final_picked, X, how_strong, rig, room, intrinsics, bounds, now):
        """strong_picked: the confident box used per camera (or None), from the first locate;
        final_picked: after weak boxes were added; X: her position this detection."""
        if not self.on or X is None or now - self.last < self.every:
            return
        if how_strong != "triangulated" or sum(b is not None for b in strong_picked) < self.min_strong:
            return  # not sure enough from the other angles to know she's really there
        h, w = items[0][0].shape[:2]
        rows_all, kinds = [], {}
        for c, it in enumerate(items):
            rows = []
            if strong_picked[c] is not None:
                rows.append(strong_picked[c])
            else:
                guess = outline_box(room["cameras"][c], intrinsics[c], X, self.radius, self.half_h, w, h)
                if guess is None:
                    rows_all.append([])
                    continue  # she's out of this camera's view: nothing missed
                if final_picked[c] is not None:
                    rows.append(final_picked[c])
                    kinds[c] = "unsure"
                else:
                    rows.append(guess)
                    kinds[c] = "cross"
            rows_all.append([b for b in rows if _inside(_foot(rig, c, b, self.floor_y), bounds)])
        if not kinds:
            return  # every camera that could see her did, confidently
        if self.dir is None:
            self._start()
        if shutil.disk_usage(self.dir).free / 1e9 < self.min_free:
            self.on = False
            self.log.warning("Stopped saving hard moments: under %.0f GB free", self.min_free)
            return
        self.last = now
        for c, it in enumerate(items):
            stem = f"{self.names[c]}_{self.n:06d}"
            self._pool.submit(cv2.imwrite, str(self.dir / "images" / f"{stem}.jpg"), it[0].copy(),
                              [cv2.IMWRITE_JPEG_QUALITY, 92])
            (self.dir / "labels" / f"{stem}.txt").write_text(
                "\n".join("0 %.6f %.6f %.6f %.6f" % ((b[0] + b[2]) / 2 / w, (b[1] + b[3]) / 2 / h,
                                                    (b[2] - b[0]) / w, (b[3] - b[1]) / h) for b in rows_all[c]),
                encoding="utf-8")
            if c in kinds:
                self.auto[stem] = kinds[c]
        (self.dir / "auto.json").write_text(json.dumps(self.auto, indent=0), encoding="utf-8")
        with open(self.dir / "moments.csv", "a", encoding="utf-8") as f:
            f.write(f"{self.n},{now:.3f}\n")
        self.n += 1
        if self.n >= self.max_moments:
            self.on = False
            self.log.info("Saved the most hard moments for one run (%d); stopping", self.n)

    def close(self):
        self._pool.shutdown(wait=True)
        if self.dir is not None:
            self.log.info("Saved %d hard moments (%d images) to %s", self.n, self.n * len(self.names), self.dir)
