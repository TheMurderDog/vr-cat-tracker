"""2_label's TRAIN A HELPER button: once enough pictures are checked, a quick model is trained from them in the
background (cat_tracker.helper_train, in the training environment), and then suggests boxes for the pictures not
decided yet. Labelling goes on meanwhile. The tracker's model is never changed (3_train.bat does the real training).

What it learns from: every picture you've decided (boxes you checked, and "no cat" pictures), in the current camera
setup's sessions, never the fair test session(s) and never its own suggestions you haven't decided. Each run records
the pictures it used (my_data/training/helper/used.json); 2_label marks them on the timeline, and counts only new ones
towards the next helper.

The button: grey with the count until enough are checked ("HELPER 64/150"), then TRAIN A HELPER with a slow, gentle
glow for a few seconds (then steadily lit), a progress fill while it trains, and the result in the line under the
picture. It glows again only after another batch of newly checked pictures.
"""

import json
import math
import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np

TOP = Path(__file__).resolve().parent.parent.parent
DATA = TOP / "my_data"
TRAIN_PY = TOP / ".venv-train" / "Scripts" / "python.exe"
WORK = DATA / "training" / "helper"
PROGRESS = WORK / "progress.json"
USED = WORK / "used.json"
FIRST = 150     # decided pictures with the cat before the first helper (measured: see helper_train)
AGAIN = 75      # ...and this many new ones before the button glows again (each run builds on the last, with the
                # older ones mixed in, and the gate keeps a worse one out: small steps are safe)
RETRY = 50      # a helper that wasn't better than the model it grew from: this many more before trying again
GLOW_S = 12.0   # the glow lasts this long, then the button stays steadily lit
GLOW_PERIOD_S = 1.8
EXPLAIN = ("TRAIN A HELPER: teaches a quick helper from the pictures you've decided, so it suggests better boxes for "
           "the rest. Your tracker isn't changed.")


def held_back(root):
    """Sessions never trained on: the fair test session(s) (marked in session.json, or listed in test_sessions.txt)."""
    from cat_tracker import train_extras as tx
    names = set(tx.marked_tests(root))
    listed = DATA / "training" / "test_sessions.txt"
    if Path(root).resolve() == (DATA / "captures").resolve() and listed.is_file():
        names |= set(listed.read_text(encoding="utf-8").split())
    return names


def eligible(root, since=None):
    """The sessions a helper learns from: the current camera setup's, not held back. (session folders)"""
    from cat_tracker import train_extras as tx
    root = Path(root)
    if not root.is_dir():
        return []
    if since is None:
        since = tx.setup_since(DATA / "calibration" / "room.json")
    held = held_back(root)
    return [p for p in sorted(root.iterdir()) if p.is_dir() and p.name >= since and p.name not in held]


_SEEN = {}  # label file -> (mtime_ns, size, has a box): only changed files are read again (a recount is ~20 ms)


def decided(ses):
    """{stem: has a box} for every decided picture of a session (checked; skipped ones are left out)."""
    import os
    out = {}
    ck = Path(ses) / "checked.txt"
    if not ck.is_file():
        return out
    for stem in ck.read_text(encoding="utf-8").split():
        lab = Path(ses) / "labels" / f"{stem}.txt"
        try:
            st = os.stat(lab)
        except OSError:
            out[stem] = False
            continue
        key = str(lab)
        seen = _SEEN.get(key)
        if seen is None or seen[:2] != (st.st_mtime_ns, st.st_size):
            try:
                seen = (st.st_mtime_ns, st.st_size, bool(lab.read_text(encoding="utf-8").strip()))
            except OSError:
                seen = (0, 0, False)
            _SEEN[key] = seen
        out[stem] = seen[2]
    return out


def load_used(path=USED):
    """{session: set of stems} used by any helper run so far."""
    try:
        runs = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for run in runs.values():
        for ses, stems in run.get("pictures", {}).items():
            out.setdefault(ses, set()).update(stems)
    return out


def counts(root, used=None, since=None):
    """(decided pictures with the cat not in a helper yet, all decided pictures with the cat), eligible sessions."""
    used = load_used() if used is None else used
    new = total = 0
    for ses in eligible(root, since):
        u = used.get(ses.name, set())
        for stem, cat in decided(ses).items():
            if cat:
                total += 1
                new += stem not in u
    return new, total


def glow(t_ready, now):
    """0..1, the button's glow: a slow pulse for GLOW_S after it became ready, then steady (1)."""
    if t_ready is None:
        return 1.0
    dt = now - t_ready
    if dt >= GLOW_S:
        return 1.0
    return 0.5 + 0.5 * math.cos(2 * math.pi * dt / GLOW_PERIOD_S)  # starts bright, eases down and up again


class Helper:
    def __init__(self, root, train_py=TRAIN_PY, work=WORK, since=None):
        self.root, self.train_py, self.work, self.since = Path(root), Path(train_py), Path(work), since
        self.proc = None
        self.result = None       # the finished run's progress record, once (for the tool to act on)
        self.t_ready = None      # when it last became ready (for the glow)
        self.new = self.total = 0
        self.retry_at = 0         # after a helper that wasn't used: wait for more decided pictures
        self.last_count = -1e9
        self.refresh(force=True)

    @property
    def used_file(self):
        return self.work / "used.json"

    @property
    def progress_file(self):
        return self.work / "progress.json"

    def need(self):
        return max(FIRST if not load_used(self.used_file) else AGAIN, self.retry_at)

    def refresh(self, force=False, now=None):
        """Recount: at once when forced, else about every 5 s in a background thread (reading the sessions' decided
        lists takes tens of milliseconds: the window mustn't stutter), applied on a later call."""
        now = time.monotonic() if now is None else now
        got = getattr(self, "_counted", None)
        if got is not None:
            self._counted = None
            self._apply(got, now)
        if force:
            self._apply(counts(self.root, load_used(self.used_file), self.since), now)
            self.last_count = now
            return
        if now - self.last_count < 5 or getattr(self, "_counting", False):
            return
        self.last_count = now
        self._counting = True

        def work():
            try:
                self._counted = counts(self.root, load_used(self.used_file), self.since)
            finally:
                self._counting = False
        threading.Thread(target=work, daemon=True).start()

    def _apply(self, got, now):
        was = self.ready()
        self.new, self.total = got
        if self.ready() and not was:
            self.t_ready = now

    def ready(self):
        return self.proc is None and self.new >= self.need()

    def running(self):
        return self.proc is not None

    def available(self):
        return self.train_py.is_file()

    def start(self, cmd=None):
        """Start the training in the background. Returns a note for the line under the picture."""
        if not self.available() and cmd is None:
            return "The helper needs the training setup: run 3_first_test\\1_get_stock_model.bat once."
        if self.running():
            return "The helper is already training."
        if not self.ready():
            return f"The helper needs {self.need() - self.new} more decided pictures with the cat first."
        self.work.mkdir(parents=True, exist_ok=True)
        try:
            self.progress_file.unlink()
        except OSError:
            pass
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        log = open(self.work / "helper_train.log", "w", encoding="utf-8")
        cmd = cmd or [str(self.train_py), "-m", "cat_tracker.helper_train"]
        self.proc = subprocess.Popen(cmd, cwd=str(TOP / "engine"), stdout=log, stderr=subprocess.STDOUT,
                                     creationflags=flags)
        log.close()
        return "Training a helper from your decided pictures (about 3 minutes). Keep labelling meanwhile."

    def progress(self):
        try:
            return json.loads(self.progress_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def poll(self):
        """Called every frame. When the run has ended: its record in self.result (once)."""
        if self.proc is None or self.proc.poll() is None:
            return
        rec = self.progress()
        if rec.get("state") != "done":
            rec = dict(rec, state="failed", why=rec.get("why") or f"stopped (exit code {self.proc.returncode})")
        elif rec.get("promoted") is False:
            self.retry_at = self.new + RETRY
        self.proc, self.result, self.t_ready = None, rec, None
        self.refresh(force=True)

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()

    def label(self, now=None):
        """(text, fill 0..1 or None, glow 0..1 or None (None: not lit)) for the button."""
        now = time.monotonic() if now is None else now
        if self.running():
            p = self.progress()
            st = p.get("state", "starting")
            if st == "training":
                return f"HELPER {p.get('epoch', 0)}/{p.get('of', 1)}", p.get("epoch", 0) / max(p.get("of", 1), 1), None
            return {"exporting": "HELPER: saving...", "checking": "HELPER: checking..."}.get(st, "HELPER: starting..."), \
                (0.0 if st == "starting" else 1.0), None
        if self.ready():
            return "TRAIN A HELPER", None, glow(self.t_ready, now)
        return f"HELPER {min(self.new, self.need())}/{self.need()}", None, None


def draw_button(bar, box, text, fill, lit):
    """The button in the top bar: grey when locked; amber, glowing softly, when ready; a progress fill when running."""
    x1, y1, x2, y2 = box
    if fill is not None:  # running: dark, filled left to right in amber
        cv2.rectangle(bar, (x1, y1), (x2, y2), (60, 60, 60), -1)
        cv2.rectangle(bar, (x1, y1), (x1 + int((x2 - x1) * min(max(fill, 0), 1)), y2), (0, 150, 200), -1)
        cv2.rectangle(bar, (x1, y1), (x2, y2), (0, 210, 255), 1)
        col, th = (240, 240, 240), 1
    elif lit is not None:  # ready: amber; the glow brightens the fill and the border (it never goes dark)
        base = np.array((0, 170, 220), np.float32)
        top_ = np.array((120, 235, 255), np.float32)
        c = tuple(int(v) for v in base + (top_ - base) * lit)
        cv2.rectangle(bar, (x1, y1), (x2, y2), c, -1)
        cv2.rectangle(bar, (x1 - 2, y1 - 2), (x2 + 2, y2 + 2), tuple(int(v) for v in top_), 1 + int(round(lit)))
        col, th = (20, 20, 20), 2
    else:  # locked: an outline and the count
        cv2.rectangle(bar, (x1, y1), (x2, y2), (90, 90, 90), 1)
        col, th = (150, 150, 150), 1
    sc = 0.55
    (tw, tht), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, sc, th)
    cv2.putText(bar, text, (x1 + (x2 - x1 - tw) // 2, y2 - (y2 - y1 - tht) // 2 - 1), cv2.FONT_HERSHEY_SIMPLEX, sc, col,
                th, cv2.LINE_AA)


SURE = 0.6       # a helper box this sure is suggested as it is
AGREE_FROM = 0.4  # ...one from 0.4 to 0.6 only when another camera's box at the same moment agrees (CHECK THIS)
AGREE_PX = 20     # agreeing: the two box centres triangulate to one spot within this many pixels
# Measured on the fair test session (a helper from 150 pictures): score >= 0.3 alone found 88.1% of the cats and
# boxed 15.6% of the empty pictures (dimmed: 77.8% / 33.7%); this rule: 88.1% / 12.4% (dimmed: 76.6% / 17.5%).
# Clean pictures' false boxes mostly agree across cameras (something cat-like that two cameras see), dim ones don't.


def best_box(det, img, floor=0.2):
    """(box, score) of a helper detector's best box on a whole picture (score >= floor), or None."""
    boxes = [b for b in det([img])[0] if b[4] >= floor]
    if not boxes:
        return None
    b = max(boxes, key=lambda b: b[4])
    return [float(v) for v in b[:4]], float(b[4])


def agrees(rig, lens, c1, b1, c2, b2, err_px=AGREE_PX):
    """True when the centres of box b1 (camera c1) and b2 (camera c2) triangulate to one spot (reprojection error
    under err_px in both), as the tracker would place one cat."""
    from calibration import intrinsics as intr
    from fusion.triangulate import _dlt
    xy = np.array([intr.undistort_points(np.array([[(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]]), lens[c])[0]
                   for c, b in ((c1, b1), (c2, b2))])
    X = _dlt(rig.P[[c1, c2]], xy, np.ones(2))
    if X is None:
        return False
    for c, q in ((c1, xy[0]), (c2, xy[1])):
        proj, depth = rig.project_norm(c, X[None])
        if depth[0] <= 0 or np.linalg.norm(proj[0] - q) * rig.fx[c] > err_px:
            return False
    return True


def choose(found, others, rig=None, lens=None):
    """The suggestions to make at one moment. found: {camera index: (box, score)} the helper's boxes for the pictures
    that need one; others: {camera index: box} the other cameras' boxes at that moment (yours, or auto ones).
    Returns {camera index: (box, kind)}: "cross" (an ordinary auto box) when sure, "check" (CHECK THIS) when less sure
    but another camera agrees; the rest are left without a box. Without the room calibration (rig None), only sure
    ones."""
    partners = dict(others)
    partners.update({c: b for c, (b, sc) in found.items()})
    out = {}
    for c, (box, score) in found.items():
        if score >= SURE:
            out[c] = (box, "cross")
        elif score >= AGREE_FROM and rig is not None and any(
                agrees(rig, lens, c, box, k, pb) for k, pb in partners.items() if k != c):
            out[c] = (box, "check")
    return out
