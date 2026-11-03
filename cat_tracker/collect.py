"""Saving camera frames of the cat for training, with the current detector's boxes as first-guess labels.

Each capture session goes in cat_tracker/captures/<date>-<time>/ as images/<camera>_<n>.jpg and
labels/<camera>_<n>.txt (YOLO format: class cx cy w h, all 0-1), plus moments.csv with the time of
each moment. The labels are only the stock model's guesses; autolabel.bat fills in cameras and
moments it missed, and label.bat is where they're checked before training.
"""

import shutil
import time
from concurrent.futures import ThreadPoolExecutor

import cv2

from cat_tracker.locate import _foot, _inside


class FrameSaver:
    def __init__(self, root, names, every_s=1.0, min_free_gb=5.0, log=None):
        self.dir = root / time.strftime("%Y%m%d-%H%M%S")
        (self.dir / "images").mkdir(parents=True, exist_ok=True)
        (self.dir / "labels").mkdir(parents=True, exist_ok=True)
        self.names, self.every, self.min_free = names, every_s, min_free_gb
        self.log = log
        self.n = 0
        self.last = -1e9
        self.on = True
        self._pool = ThreadPoolExecutor(2)

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
        floor_y = float(lc.get("floor_y_m", 0.0))
        for c, it in enumerate(items):
            frame = it[0]
            h, w = frame.shape[:2]
            rows = []
            for b in boxes_all[c]:
                if _inside(_foot(rig, c, b, floor_y), bounds):  # leave out pictures on the walls
                    rows.append("0 %.6f %.6f %.6f %.6f" % ((b[0] + b[2]) / 2 / w, (b[1] + b[3]) / 2 / h,
                                                          (b[2] - b[0]) / w, (b[3] - b[1]) / h))
            stem = f"{self.names[c]}_{self.n:06d}"
            self._pool.submit(cv2.imwrite, str(self.dir / "images" / f"{stem}.jpg"), frame.copy(),
                              [cv2.IMWRITE_JPEG_QUALITY, 92])
            (self.dir / "labels" / f"{stem}.txt").write_text("\n".join(rows), encoding="utf-8")
        with open(self.dir / "moments.csv", "a", encoding="utf-8") as f:  # when each moment was taken, for autolabel
            f.write(f"{self.n},{now:.3f}\n")
        self.n += 1
        return True

    def close(self):
        self._pool.shutdown(wait=True)
        if self.log:
            self.log.info("Captured %d moments (%d images) to %s", self.n, self.n * len(self.names), self.dir)
