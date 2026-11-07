"""Training helpers: a fair test set, comparing models on it, keeping Windows awake, logging the GPU's temperature,
and the overnight run's state (so an interrupted run picks up where it stopped).

Fair test set: whole capture sessions held back, never a slice of a session (a slice looks just like the pictures
next to it: old runs scored 0.99 on it after the first epoch, which says nothing). The sessions are listed in
my_data/training/test_sessions.txt and marked in their session.json ("role": "test"; the sessions screen shows
"TEST SET: not trained on"). A marked session is held back as soon as it's marked, labelled or not, so a half-labelled
test session never slips into training. Mark one with python -m cat_tracker.sessions --test NAME. With none marked,
the first time there are checked sessions from two different days, the smallest one not from the day of the biggest
is chosen and marked, so it stays the same. Until then there is no fair score, and the training says so.
"""

import ctypes
import json
import subprocess
import threading
import time
from pathlib import Path

import numpy as np


# ---- the fair test set ---------------------------------------------------------------------------------------

def checked_sessions(captures):
    """{session name: number of checked pictures} for every session with checked pictures."""
    out = {}
    for ses in sorted(p for p in captures.iterdir() if p.is_dir()):
        ck = ses / "checked.txt"
        if ck.is_file():
            n = len(ck.read_text(encoding="utf-8").split())
            if n:
                out[ses.name] = n
    return out


def setup_since(room_json):
    """When the current camera setup began (the room calibration's time), as a session name prefix
    (YYYYMMDD-HHMMSS), or "" if unknown. Sessions before it were seen from other camera angles."""
    try:
        created = json.loads(Path(room_json).read_text(encoding="utf-8")).get("created", "")
        return time.strftime("%Y%m%d-%H%M%S", time.strptime(created, "%Y-%m-%d %H:%M:%S"))
    except (OSError, ValueError, TypeError):
        return ""


def role_of(ses):
    """A session's role from its session.json ("test" for the fair test set), or None."""
    try:
        return json.loads((Path(ses) / "session.json").read_text(encoding="utf-8")).get("role")
    except (OSError, ValueError, AttributeError):
        return None


def mark_test(ses, listed=None, on=True):
    """Mark (or unmark) a session as the fair test set: its session.json and, if given, the listed file."""
    ses = Path(ses)
    meta = {}
    try:
        meta = json.loads((ses / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if on:
        meta["role"] = "test"
    else:
        meta.pop("role", None)
    (ses / "session.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if listed is not None:
        listed = Path(listed)
        names = set(listed.read_text(encoding="utf-8").split()) if listed.is_file() else set()
        names = names | {ses.name} if on else names - {ses.name}
        listed.parent.mkdir(parents=True, exist_ok=True)
        listed.write_text("".join(n + "\n" for n in sorted(names)), encoding="utf-8")


def marked_tests(captures):
    """Every session marked as test (session.json), from any setup: none of them is ever trained on."""
    if not Path(captures).is_dir():
        return []
    return sorted(p.name for p in Path(captures).iterdir() if p.is_dir() and role_of(p) == "test")


def test_sessions(captures, listed, since=""):
    """The sessions held back for the fair score (and marked if chosen now), or []. Only sessions from the
    current camera setup (named after since) count: old angles shouldn't judge a model meant for the new ones.
    A marked session counts even with nothing labelled yet: it's held back all the same."""
    have = {n: c for n, c in checked_sessions(captures).items() if n >= since}
    names = set(n for n in marked_tests(captures) if n >= since)
    if listed.is_file():
        names |= {n for n in listed.read_text(encoding="utf-8").split() if n in have}
    if names:
        return sorted(names)
    normal = {n: c for n, c in have.items() if not n.endswith("-hard")}
    days = {n[:8] for n in normal}
    if len(days) < 2:
        return []
    biggest_day = max(normal, key=normal.get)[:8]
    others = [n for n in normal if n[:8] != biggest_day and normal[n] >= 40]
    if not others:
        return []
    pick = min(others, key=normal.get)
    mark_test(Path(captures) / pick, listed)
    return [pick]


# ---- comparing two models on the same pictures -----------------------------------------------------------------

def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / max((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter, 1e-9)


def score(predictions, truths, iou_thr=0.5):
    """F1 (and precision, recall) of boxes against the checked boxes: each found cat counts once, a box where there
    is none counts against it (the empty pictures matter too). predictions/truths: one list of boxes per picture."""
    tp = fp = fn = 0
    for pred, gt in zip(predictions, truths):
        used = set()
        for p in pred:
            best = max(((k, _iou(p, g)) for k, g in enumerate(gt) if k not in used), key=lambda t: t[1], default=None)
            if best and best[1] >= iou_thr:
                used.add(best[0])
                tp += 1
            else:
                fp += 1
        fn += len(gt) - len(used)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    return {"f1": f1, "precision": precision, "recall": recall, "cats": tp + fn, "pictures": len(truths)}


def evaluate(model_path, items, cat_class, imgsz=960, conf=0.25, device=None):
    """Score a model (.pt or .onnx) on [(session, image, label file)] with ultralytics, cat class cat_class."""
    from core.ultra import load_yolo
    YOLO = load_yolo()  # with Ultralytics' usage events off (docs/SECURITY.md)

    from cat_tracker.label import read_boxes
    import cv2
    m = YOLO(str(model_path), task="detect")
    preds, truths = [], []
    for _, img, lab in items:
        frame = cv2.imread(str(img))
        h, w = frame.shape[:2]
        r = m.predict(frame, imgsz=imgsz, conf=conf, classes=[cat_class], verbose=False,
                      **({"device": device} if device else {}))[0]
        preds.append(r.boxes.xyxy.cpu().numpy().tolist() if r.boxes is not None else [])
        truths.append(read_boxes(Path(lab), w, h))
    return score(preds, truths)


def decide(old, new, margin=0.01, fair=True):
    """Keep the new model only if it's better by margin (F1). (keep_new, plain reason). Without a fair test set from
    the current camera setup the new model is used: it's trained on what the cameras see now, and an unfair
    comparison mustn't keep an old model made for other angles."""
    if not fair:
        return True, "I couldn't compare fairly yet: capture a short test session on another day"
    if old is None:
        return True, "there was no fine-tuned model yet"
    if new["f1"] >= old["f1"] + margin:
        return True, f"it finds the cat better: score {new['f1']:.2f} against {old['f1']:.2f}"
    if new["f1"] > old["f1"]:
        return False, f"it's only a little better ({new['f1']:.2f} against {old['f1']:.2f}), not enough to switch"
    return False, f"the one you have is as good or better ({old['f1']:.2f} against {new['f1']:.2f})"


# ---- keeping Windows awake ------------------------------------------------------------------------------------

class KeepAwake:
    """While it's active, Windows doesn't go to sleep (the screen may still turn off). Always released at the end."""
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001

    def __enter__(self):
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED)
            self.on = True
        except (AttributeError, OSError):  # not Windows
            self.on = False
        return self

    def __exit__(self, *exc):
        if self.on:
            ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)
        return False


# ---- the GPU's temperature ------------------------------------------------------------------------------------

def gpu_reading(smi="nvidia-smi"):
    """(temperature C, power W) of the first GPU, or None (no nvidia-smi)."""
    import os
    exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
    exe = exe if os.path.isfile(exe) else smi  # the driver's copy, by full path where it's there
    try:
        out = subprocess.run([exe, "--query-gpu=temperature.gpu,power.draw", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        t, p = (float(v) for v in out.strip().splitlines()[0].split(","))
        return t, p
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


class GpuWatch:
    """Logs the GPU's temperature and power every interval_s, and remembers the peak. It doesn't slow or pause
    anything: the card lowers its own clocks as it nears its limit and protects itself. A high peak is still worth
    a word (a clogged or failed fan), so the summary mentions it."""

    def __init__(self, log, warm_c=85.0, interval_s=60.0, read=gpu_reading):
        self.log, self.warm, self.every, self.read = log, warm_c, interval_s, read
        self.max_c = None
        self._stop = threading.Event()
        self._thread = None

    def check(self):
        r = self.read()
        if r is None:
            return None
        self.max_c = r[0] if self.max_c is None else max(self.max_c, r[0])
        return r

    def _run(self):
        while not self._stop.is_set():
            r = self.check()
            if r:
                self.log(f"GPU {r[0]:.0f} C, {r[1]:.0f} W")
            self._stop.wait(self.every)

    def start(self):
        if self.read() is None:
            self.log("No GPU temperature available (nvidia-smi): not logged")
            return self
        self._thread = threading.Thread(target=self._run, name="gpu log", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()

    def summary(self):
        """"GPU peaked at X C", with a hint if that's warm; "" if it wasn't read."""
        if self.max_c is None:
            return ""
        return f"GPU peaked at {self.max_c:.0f} C" + (": running warm, check the fans and dust." if self.max_c > self.warm
                                                      else ".")


# ---- the overnight run's state --------------------------------------------------------------------------------

def load_state(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_state(path, **state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")


def unfinished_run(state_path, runs_dir):
    """The run an interrupted overnight training left (its last.pt), or None."""
    st = load_state(state_path)
    if not st or st.get("finished"):
        return None
    last = Path(runs_dir) / st["run"] / "weights" / "last.pt"
    return last if last.is_file() else None


def summary_text(lines):
    return "\n".join(lines) + "\n"


def mean(xs):
    return float(np.mean(xs)) if xs else 0.0
