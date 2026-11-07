"""Check and fix the cat boxes in a capture session, one image at a time.

From the camera core folder:  python -m cat_tracker.label                 every session with unchecked images, newest first
                      python -m cat_tracker.label --session 20261030-201500
Mouse: click on the cat to snap a box to it (the stock model, on an enlarged crop there: cat_tracker.snap); drag on an
       empty spot to draw a box; drag a box's corner or side to resize it, its middle to move it; right-click a box to
       delete it; the wheel zooms around the cursor and the middle button drags the zoomed view. A green dot marks the
       exact cursor point. Above the picture: the TRANSPARENCY sliders (blue box, boxes, hint) and the Help button
       (also ?); beside it: a brightness slider (display only). All words go in the bar under the picture.
Keys (WASD, for gamers):  space = the boxes are right, next;  S = no cat in it (clears the boxes), next;
       D = not sure: skip it (left out of training: skipped.txt; decide later with space or S), next;
       W = copy the blue box (the same camera's previous picture, if you checked it) as a green one, and stay;
       A = back one;  Z = undo;  H = the hint on or off;  Q or Esc = save and quit.
While zoomed, the next picture opens centred on its box (or the hint). A picture with more boxes than cats
(label.cats) is flagged and Space waits until one per cat is left; --review-extra goes through only those.
Hint: on a picture with no box, a magenta crosshair (and a faint outline about cat size) where the other cameras place
the cat at that moment (2 or more of their boxes, triangulated with the room calibration). Only a hint: click there to
snap a box if it's really visible.
Space on a picture with no box saves it as "no cat", except where the hint shows the other cameras see the cat:
there it asks you to box it, or press S (no cat) or D (not sure) on purpose.
Every image you decide counts as checked (listed in checked.txt), so you can stop and come back.
Only checked images are used for training. A session not autolabelled yet is first (prepare: cat_tracker.autolabel,
progress in the window; --no-autolabel skips it). Boxes it added are orange until you move on.
"""

import argparse
import json
import time

import cv2
import numpy as np

from cat_tracker import label_view as lv
from core.config import resolve_path
from capture.camera import outlined_text

WIN = "Label the cat"
KEEP, NO_CAT, SKIP, REUSE, BACK = (ord(" "), 13), (ord("s"), ord("x")), (ord("d"),), (ord("w"),), (ord("a"), 8)
REDO = (ord("r"),)
QUIT, JUMP, UNDO, HINT, HELP = (ord("q"), 27), (ord("j"),), (ord("z"),), (ord("h"),), (ord("?"), ord("/"))
SESSIONS = (9,)  # Tab
STEP_BACK, STEP_FWD, RANGE, UNDO_STRETCH = (ord(","),), (ord("."),), (ord("n"),), (ord("u"),)  # step without deciding; a no-cat stretch
HELD_GAP_S = 0.6  # a decide key again this soon is the key held down (Windows repeats after 0.25-1 s, default 0.5)
REPRESS_S = 0.12  # after a stop, a pause this long (the key let go and pressed again) goes on; repeats come faster
_now = time.monotonic
ARROW_LEFT, ARROW_RIGHT = 0x250000, 0x270000  # waitKeyEx codes on Windows
HOLD_KEYS = {"keep": (0x20, 0x0D), "nocat": (0x53, 0x58)}  # Windows key codes: Space, Enter / S, X


def _key_down(vk):
    """Whether the key is down right now (Windows), or None where that can't be read."""
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except (AttributeError, OSError):
        return None


def read_key(ms):
    """A key (low 8 bits, 255 for none); the left and right arrows come back as , and ."""
    kx = cv2.waitKeyEx(ms)
    if kx == ARROW_RIGHT:
        return STEP_FWD[0]
    if kx == ARROW_LEFT:
        return STEP_BACK[0]
    return kx & 0xFF
BLUE, GREEN, ORANGE = (255, 80, 0), (0, 255, 0), (0, 165, 255)


def read_boxes(p, w, h):
    out = []
    if p.is_file():
        for line in p.read_text(encoding="utf-8").split("\n"):
            v = line.split()
            if len(v) == 5:
                cx, cy, bw, bh = (float(a) for a in v[1:])
                out.append([(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h])
    return out


def write_boxes(p, boxes, w, h):
    p.write_text("\n".join("0 %.6f %.6f %.6f %.6f" % ((b[0] + b[2]) / 2 / w, (b[1] + b[3]) / 2 / h,
                                                     (b[2] - b[0]) / w, (b[3] - b[1]) / h) for b in boxes),
                 encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Fix cat boxes in a capture session")
    ap.add_argument("--session")
    ap.add_argument("--start", type=int, help="image number to start at (default: first unchecked)")
    ap.add_argument("--sessions", "--review", action="store_true", help="open on the sessions screen")
    ap.add_argument("--no-autolabel", action="store_true",
                    help="don't fill in boxes first (when the model boxed something that isn't the cat)")
    ap.add_argument("--review-extra", action="store_true",
                    help="go through only the pictures with more boxes than cats (label.cats), decided or not")
    args = ap.parse_args()
    if args.no_autolabel:
        NO_AUTOLABEL.append(True)
    root = resolve_path("my_data/captures")
    sessions = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    if args.review_extra:
        for ses in [p for p in reversed(sessions) if (p / "images").is_dir()]:
            if label_session(ses, review_extra=True) == "quit":
                break
        cv2.destroyAllWindows()
        return 0
    if args.session:
        first = (root / args.session, None, False, args.start)
    elif args.sessions:
        first = None
    else:  # the newest session with pictures to check (the tracker's -hard ones included), else the sessions screen
        todo = [p for p in reversed(sessions) if (p / "images").is_dir() and unchecked(p)]
        first = (todo[0], None, False, args.start) if todo else None
    tool(root, first)
    cv2.destroyAllWindows()
    return 0


NO_AUTOLABEL = []  # --no-autolabel
_HELPER = []  # TRAIN A HELPER (cat_tracker.helper): one per tool run, its training goes on across sessions


def prepare(ses):
    """Autolabel ses first if it needs it (autolabel.needs_run), showing progress in the window. Decided and skipped
    pictures are never touched. A failure only means no extra boxes: the session opens all the same."""
    from cat_tracker import autolabel
    from cat_tracker import sessions as sess
    if NO_AUTOLABEL or not autolabel.needs_run(ses, sess.setup_since()):
        return
    own = ses.name[len("labels-"):] if ses.name.startswith("labels-") else ses.name

    def show(done, total):
        img = np.full((260, 900, 3), 26, np.uint8)
        cv2.putText(img, f"Preparing boxes for {own}...", (30, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (240, 240, 240),
                    2, cv2.LINE_AA)
        line = f"moment {done} of {total}" if total else "loading the model"
        cv2.putText(img, line, (30, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 210, 255), 2, cv2.LINE_AA)
        if total:
            cv2.rectangle(img, (30, 150), (870, 170), (70, 70, 70), -1)
            cv2.rectangle(img, (30, 150), (30 + int(840 * done / total), 170), (80, 220, 80), -1)
        cv2.putText(img, "Filling in boxes the model missed, from the other cameras. Only once per session.",
                    (30, 215), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (150, 150, 150), 1, cv2.LINE_AA)
        cv2.imshow(WIN, img)
        cv2.waitKey(1)

    print(f"Preparing boxes for {own} (autolabel, once per session)...")
    show(0, 0)
    try:
        autolabel.main(["--session", ses.name], progress=show, root=ses.parent)
    except Exception as e:  # noqa: BLE001
        print(f"Couldn't prepare the boxes ({e}). Opening the session without them.")


def session_rows(root):
    from cat_tracker import sessions as sess
    rows = []
    for r in sess.all_sessions(root):
        if r["pictures"]:
            r["_path"] = root / r["session"]
            rows.append(r)
    return rows


def tool(root, first=None):
    """The labelling tool: pictures, and the sessions screen (SESSIONS / Tab) to move between sessions."""
    import shutil
    from cat_tracker import label_sessions as ls
    from cat_tracker import sessions as sess
    from core.config import resolve_path as rp
    open_window()
    copies = []  # practice copies made: all thrown away when the tool closes
    try:
        _tool(root, first, copies, ls, sess, rp, shutil)
    finally:
        for c in copies:
            shutil.rmtree(c, ignore_errors=True)


def _tool(root, first, copies, ls, sess, rp, shutil):
    current = first  # (session folder, filter or None, practice, start index)
    can_close = False
    last = None
    filt_chosen = "all"  # the filter last picked: kept until the tool closes or another is picked
    while True:
        if current is None:
            pick = ls.choose(WIN, session_rows(root), can_close=can_close, filt=filt_chosen)
            if pick[0] == "quit":
                return
            if pick[0] == "close":
                filt_chosen = pick[1]
                current = last
                continue
            _, name, filt, practice = pick
            filt_chosen = filt
            ses = root / name
            undecided = unchecked(ses)
            if practice:
                copy = rp("my_data/practice") / f"labels-{name}"
                if copy.exists():
                    shutil.rmtree(copy)
                shutil.copytree(ses, copy)
                copies.append(copy)
                current = (copy, filt if (filt != "all" or not undecided) else None, True, None)
            else:
                review_it = filt != "all" or not undecided
                if review_it:  # a review can change decided pictures: back them up first
                    dest = rp("my_data/backups") / f"labels-{name}-{time.strftime('%Y%m%d-%H%M%S')}"
                    shutil.copytree(ses / "labels", dest / "labels")
                    for fn in ("checked.txt", "skipped.txt", "auto.json", "confirmed.txt"):
                        if (ses / fn).is_file():
                            shutil.copy2(ses / fn, dest / fn)
                current = (ses, filt if review_it else None, False, None)
        ses, filt, practice, start = current
        prepare(ses)  # autolabel first, once per session
        result = label_session(ses, start, amend=filt, practice=practice)
        if not practice:
            sess.info(ses, sess.setup_since())
        last = current
        if isinstance(result, tuple) and result[0] == "sessions":
            last = (ses, filt, practice, result[1])
            current, can_close = None, True
            continue
        if practice:
            shutil.rmtree(ses, ignore_errors=True)
        if result == "quit":
            return
        current, can_close = None, False  # this session is done: the sessions screen


def _read_set(p):
    return set(p.read_text(encoding="utf-8").split()) if p.is_file() else set()


def unchecked(ses):
    """Images not decided yet: neither checked nor skipped."""
    done = _read_set(ses / "checked.txt") | _read_set(ses / "skipped.txt")
    return sum(p.stem not in done for p in (ses / "images").glob("*.jpg"))


_WATCHED = []


def open_window():
    cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
    if not _WATCHED:
        from tools.window import quit_when_closed
        quit_when_closed(WIN)  # closing the window quits, as q does
        _WATCHED.append(True)


def key_groups(prev, hint=False, hints_on=True):
    return [("Decide, then next", [("Space", "boxes are right"), ("S", "no cat"), ("D", "not sure: skip")]),
            ("Move", [("A", "back"), (", .", "step, no decision"), ("N", "no-cat stretch"), ("U", "undo stretch"),
                      ("Q", "save and quit")]),
            ("Boxes", [("Click the cat", "a box snaps to it"), ("Drag", "draw / fix, if it's off"), ("Right-click", "delete"),
                       ("Z", "undo")] + ([("W", "copy the blue box")] if prev else [])
             + ([("H", "hint off" if hints_on else "hint on")] if hint else [])),
            ("View", [("Wheel", "zoom"), ("Middle-drag", "move around")])]


def too_many(lab, w, h, cats):
    return len(read_boxes(lab, w, h)) > cats


def label_session(ses, start=None, review_extra=False, amend=None, practice=False):
    from tools.keycaps import key_bar
    images = sorted((ses / "images").glob("*.jpg"))
    checked_file = ses / "checked.txt"
    checked = _read_set(checked_file)
    skipped_file = ses / "skipped.txt"  # not sure: left out of training (only checked images are used)
    skipped = _read_set(skipped_file)
    from cat_tracker import settings as _settings
    from core.config import get as _get
    cats = int(_get(_settings.load(), "cat.label.cats", 1) or 1)  # boxes allowed per picture: one per cat
    if review_extra:  # only the pictures with more boxes than cats
        images = [p for p in images if too_many(ses / "labels" / f"{p.stem}.txt", 1280, 720, cats)]
        print(f"{len(images)} pictures in {ses.name} have more boxes than cats ({cats})")
        if not images:
            return "done"
    confirmed_file = ses / "confirmed.txt"  # CHECK THIS pictures and possible mistakes you've decided: done with
    confirmed = _read_set(confirmed_file)
    from cat_tracker.collect import nocat_flagged
    nocat_check = nocat_flagged(ses)  # NO CAT pictures (capture) where the model still saw something cat-like
    if amend:  # review: already-decided pictures too, by filter
        auto0 = json.loads((ses / "auto.json").read_text(encoding="utf-8")) if (ses / "auto.json").is_file() else {}

        def nb(p_):
            return len(read_boxes(ses / "labels" / f"{p_.stem}.txt", 1280, 720))
        from cat_tracker import sessions as _s0
        _since, _own = _s0.setup_since(), ses.name[len("labels-"):] if ses.name.startswith("labels-") else ses.name
        hint_check = lv.Hints(ses) if amend == "mistake" and (not _since or _own[:15] >= _since) else None
        keep = {"all": lambda p_: True,
                "mistake": lambda p_: p_.stem in checked and nb(p_) == 0 and p_.stem not in confirmed and (
                    p_.stem in nocat_check or (hint_check is not None and hint_check.ok
                                               and hint_check.at(p_.stem) is not None)),
                "cat": lambda p_: p_.stem in checked and nb(p_) > 0,
                "nocat": lambda p_: p_.stem in checked and nb(p_) == 0,
                "skipped": lambda p_: p_.stem in skipped,
                "check": lambda p_: auto0.get(p_.stem) == "check" and p_.stem not in confirmed,
                "extra": lambda p_: nb(p_) > cats}[amend]
        images = [p_ for p_ in images if keep(p_)]
        print(f"{len(images)} pictures in {ses.name} ({amend})")
        if not images:
            return "done"
    reviewed = set()
    i = start if start is not None else 0 if (review_extra or amend) else \
        next((k for k, p in enumerate(images) if p.stem not in checked | skipped), 0)
    auto_file = ses / "auto.json"
    auto = json.loads(auto_file.read_text(encoding="utf-8")) if auto_file.is_file() else {}
    from cat_tracker import autolabel
    from cat_tracker import sessions as _s0
    older = [autolabel.method_of(ses) == "outline" and any(st not in checked for st in auto)
             and autolabel.needs_run(ses, _s0.setup_since())]  # R redoes them (opening does too, normally)
    prefs = lv.load_prefs()
    state = {"boxes": [], "drag": None, "undo": [], "snap": None, "note": "", "hover": None, "wh": (1280, 720),
             "mouse": None, "pan": None, "help": False}
    zoom = [lv.Zoom(1280, 720)]
    snapper = []  # the model for clicks, loaded on the first click
    from cat_tracker import sessions as _sess
    since = _sess.setup_since()
    own = ses.name[len("labels-"):] if ses.name.startswith("labels-") else ses.name  # a practice copy's session
    # the hint needs the room calibration these pictures were taken with: only the current setup's sessions
    hints = lv.Hints(ses) if not since or own[:15] >= since else lv.Hints.__new__(lv.Hints)
    if not getattr(hints, "ok", False):
        hints.ok = False
    from cat_tracker import helper as hp
    if not _HELPER:
        _HELPER.append(hp.Helper(resolve_path("my_data/captures")))
    helper = _HELPER[0]
    used_here = [hp.load_used().get(ses.name, set())]  # this session's pictures a helper learned from
    fill = {"queue": [], "det": None, "n": 0, "backup": None, "since_save": 0}  # the helper's suggestions, a few per frame
    save = lambda: lv.save_prefs(prefs)  # noqa: E731

    def snap_at(img, x, y, prev):  # prev: boxes whose size says how big to search (else about a cat far away)
        """A box snapped to the cat around a click, or None."""
        from cat_tracker import settings, snap
        if not snapper:
            state["note"] = "loading the model for clicks..."
            snapper.append(snap.make_detector(settings.load()))
        ref = (prev or state["boxes"] or [None])[0]  # a size to search around: a box nearby, else about a cat far away
        half = max(40.0, 0.6 * max(ref[2] - ref[0], ref[3] - ref[1])) if ref else 60.0
        box, score = snap.crop_box(snapper[0], img, [x - half, y - half, x + half, y + half], grow=1.0, max_dist=0.6)
        return box

    def on_mouse(ev, u, v, flags, _):
        z = zoom[0]
        top = lv.SLIDER_BAR_H
        busy = state["drag"] or state["pan"]
        if (v < top or sliders.active) and not busy and not bright.active:  # the transparency bar and Help
            state["mouse"] = None
            sliders.mouse(ev, u, v)
            return
        v = v - top
        sliders.helper_hover = False
        if (u >= z.w or bright.active) and not busy and v < z.h:  # the brightness slider beside the picture
            state["mouse"] = None
            bright.mouse(ev, u - z.w, v)
            return
        if z.h <= v < z.h + lv.TIMELINE_H and not busy and timeline[0] is not None:  # the timeline: jump
            state["mouse"] = None
            if ev == cv2.EVENT_LBUTTONDOWN or (ev == cv2.EVENT_MOUSEMOVE and flags & cv2.EVENT_FLAG_LBUTTON):
                n = len(tl_seq[0])
                j = timeline[0].index(u, n)
                if j is not None and tl_seq[0][j] != tl_seq[1]:
                    state["goto"] = j
            return
        if v >= z.h and not busy:  # the text and the keys under the picture
            state["mouse"] = None
            return
        u, v = min(max(u, 0), z.w - 1), min(max(v, 0), z.h - 1)  # a drag that leaves the picture keeps going
        state["mouse"] = (u, v)
        if ev == cv2.EVENT_MBUTTONDOWN:  # the middle button drags the zoomed view
            state["pan"] = (u, v)
            return
        if ev == cv2.EVENT_MBUTTONUP:
            state["pan"] = None
            return
        if state["pan"] and ev == cv2.EVENT_MOUSEMOVE:
            pu, pv = state["pan"]
            z.pan(u - pu, v - pv)
            state["pan"] = (u, v)
            return
        x, y = z.to_img(u, v)
        tol = lv.GRAB_PX / z.z
        d = state["drag"]
        if ev == cv2.EVENT_LBUTTONDOWN:
            h = lv.hit(state["boxes"], x, y, tol)
            state["drag"] = {"start": (x, y), "cur": (x, y), "hit": h,
                             "orig": list(state["boxes"][h[0]]) if h else None, "before": [list(b) for b in state["boxes"]]}
        elif ev == cv2.EVENT_MOUSEMOVE:
            if d:
                d["cur"] = (x, y)
                if d["hit"]:  # resizing or moving a box, live
                    k, handle = d["hit"]
                    state["boxes"][k] = lv.edit(d["orig"], handle, x - d["start"][0], y - d["start"][1], *state["wh"])
            else:
                state["hover"] = lv.hit(state["boxes"], x, y, tol)
        elif ev == cv2.EVENT_LBUTTONUP and d:
            state["drag"] = None
            (x0, y0) = d["start"]
            moved = max(abs(x - x0), abs(y - y0)) * z.z > 3
            if d["hit"] and "move" not in d["hit"][1]:
                # a corner or side was grabbed: always an edit, however small (a 2-pixel nudge used to count as a
                # click, which snapped the box back to the model's shape)
                if state["boxes"][d["hit"][0]] != d["before"][d["hit"][0]]:
                    state["undo"].append(d["before"])
            elif d["hit"] and moved:
                state["undo"].append(d["before"])  # moved: one undo step
            elif not moved:
                if d["hit"]:
                    state["boxes"] = d["before"]
                state["snap"] = (x, y)  # a click (inside a box or on an empty spot): snap a box to the cat there
            else:
                new, why = lv.add_box(state["boxes"], [min(x0, x), min(y0, y), max(x0, x), max(y0, y)], cats)
                if why:
                    state["note"] = why
                else:
                    state["undo"].append(d["before"])
                    state["boxes"] = new
        elif ev == cv2.EVENT_RBUTTONDOWN:
            k = lv.hit(state["boxes"], x, y, tol)
            if k:
                state["undo"].append([list(b) for b in state["boxes"]])
                del state["boxes"][k[0]]
        elif ev == cv2.EVENT_MOUSEWHEEL:
            z.wheel(u, v, 1 if flags > 0 else -1)  # the wheel turn is in flags' high word: its sign is the direction

    help_state = {"sliders": None, "y": 0, "scroll": 0, "h": 0}
    HELP_VIEW_H = 900  # the help window's height; the wheel scrolls the rest

    def on_help_mouse(ev, u, v, flags, _):
        if ev == cv2.EVENT_MOUSEWHEEL:
            help_state["scroll"] = int(min(max(help_state["scroll"] - (60 if flags > 0 else -60), 0),
                                           max(help_state["h"] - HELP_VIEW_H, 0)))
            return
        v = v + help_state["scroll"]
        sl = help_state["sliders"]
        if sl is not None and (help_state["y"] <= v < help_state["y"] + lv.SLIDER_BAR_H or sl.active):
            sl.mouse(ev, u, v - help_state["y"])

    open_window()
    sliders = lv.Sliders(prefs, 1280 + lv.SIDE_W, save)
    bright = lv.Brightness(prefs, 720, save)
    cv2.setMouseCallback(WIN, on_mouse)
    k = None
    hold = {"t": -9.0, "key": None, "blocked": False, "up": {}, "state": False}  # a decide key held down (held)
    rng = {"start": None, "apply": None, "last": None, "skip": set(), "old": {}}  # the N ... N no-cat stretch
    hist_file = ses / "stretches.json"  # every no-cat stretch, newest last, with what it changed: UNDO STRETCH

    def load_hist():
        try:
            return json.loads(hist_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def save_hist(hh):
        hist_file.write_text(json.dumps(hh, indent=1), encoding="utf-8")

    def undo_stretch(cur_boxes):
        """Undo the latest stretch: each picture back as it was, unless you changed it since (kept). A note says."""
        hh = load_hist()
        if not hh:
            state["note"] = "No stretch to undo."
            return
        e = hh.pop()
        restored = boxes_back = kept = 0
        for st, (text, was_checked, was_skipped, was_confirmed) in e["pictures"].items():
            p_ = ses / "labels" / f"{st}.txt"
            now_boxes = cur_boxes if st == images[i].stem else read_boxes(p_, 1280, 720)
            if not (st in checked and st not in skipped and not now_boxes):  # changed since: yours stays
                kept += 1
                continue
            p_.write_text(text, encoding="utf-8")
            nbox[st] = len(read_boxes(p_, 1280, 720))
            boxes_back += nbox[st] > 0
            (checked.add if was_checked else checked.discard)(st)
            (skipped.add if was_skipped else skipped.discard)(st)
            (confirmed.add if was_confirmed else confirmed.discard)(st)
            if not was_checked:
                reviewed.discard(st)
            rng["skip"].discard(st)
            restored += 1
        checked_file.write_text("\n".join(sorted(checked)), encoding="utf-8")
        skipped_file.write_text("\n".join(sorted(skipped)), encoding="utf-8")
        confirmed_file.write_text("\n".join(sorted(confirmed)), encoding="utf-8")
        save_hist(hh)
        if images[i].stem in e["pictures"]:
            state["boxes"] = lv.dedupe(read_boxes(lab, w, h))
        rng["last"] = None
        state["note"] = (f"Undid stretch {e['from']} to {e['to']}: restored {restored} picture"
                         f"{'s' if restored != 1 else ''}" + (f", {boxes_back} box{'es' if boxes_back != 1 else ''} back" if boxes_back else "")
                         + (f". {kept} you changed since {'was' if kept == 1 else 'were'} kept" if kept else "") + "."
                         + (f" {len(hh)} more to undo." if hh else ""))

    def watch_keys():
        """Called every frame: notes each decide key seen let go since its last press."""
        for g, vks in HOLD_KEYS.items():
            downs = [_key_down(vk) for vk in vks]
            if None in downs:
                hold["state"] = False
                return
            hold["state"] = True
            if not any(downs):
                hold["up"][g] = True

    def held(group):
        """True when this keypress is the key still held down (an auto-repeat), not a new press. On Windows by the
        key's real state: let go at any moment since its last press means a new press, however quick the taps.
        Elsewhere by timing (repeats come faster than taps)."""
        now = _now()
        gap, same = now - hold["t"], hold["key"] == group
        hold["t"], hold["key"] = now, group
        if hold.get("state"):
            up = hold["up"].get(group, True)
            hold["up"][group] = False
            if not same or up:
                hold["blocked"] = False
                return False
            return True
        if hold["blocked"]:  # stopped: a new press (a short pause after the repeats) goes on
            if same and gap < REPRESS_S:
                return True
            hold["blocked"] = False
            return False
        return same and gap < HELD_GAP_S

    # the timeline: per camera, its pictures in order (images are sorted camera by camera)
    seq = {}
    for j, p in enumerate(images):
        seq.setdefault(p.stem.rsplit("_", 1)[0], []).append(j)
    nbox = {p.stem: len(read_boxes(ses / "labels" / f"{p.stem}.txt", 1280, 720)) for p in images}
    hint_at = {}  # stem -> hint or not, worked out a few per frame for the camera on screen
    timeline = [None]
    tl_seq = [[], None]  # this camera's pictures and this one, for clicks on the timeline

    def tl_status(st):
        if st in skipped:
            return "skipped"
        if st in checked:
            return "cat" if nbox.get(st) else "nocat"
        return "auto" if auto.get(st) else "todo"

    def tl_mark(st):
        """The row under the ticks, only where it needs you: 1 (magenta) undecided, no box, the other cameras see the
        cat; 2 (red) marked no cat, not confirmed, the other cameras see it (a possible mistake); else 0."""
        if st in nocat_check and st in checked and st not in confirmed and not nbox.get(st):
            return 2  # saved as no cat while NO CAT was on, but the model saw something there
        if not hint_at.get(st) or nbox.get(st) or st in skipped:
            return 0
        if st in checked:
            return 2 if st not in confirmed else 0
        return 1


    while 0 <= i < len(images):
        img = cv2.imread(str(images[i]))
        h, w = img.shape[:2]
        state["wh"] = (w, h)
        cam = images[i].stem.rsplit("_", 1)[0]
        if zoom[0].w != w or zoom[0].h != h:
            zoom[0] = lv.Zoom(w, h)
        lab = ses / "labels" / f"{images[i].stem}.txt"
        state["boxes"] = lv.dedupe(read_boxes(lab, w, h))
        state["undo"], state["hover"], state["drag"], state["pan"] = [], None, None, None
        kind = auto.get(images[i].stem) if images[i].stem not in checked else None
        first = [list(b) for b in state["boxes"]]
        # the same camera's previous image, if it was checked: it often hasn't moved
        prev = []
        if i > 0 and images[i - 1].stem.rsplit("_", 1)[0] == cam and images[i - 1].stem in checked:
            prev = read_boxes(ses / "labels" / f"{images[i - 1].stem}.txt", w, h)
        state["note"] = state.pop("next_note", "")
        hint = hints.at(images[i].stem) if hints.ok else None
        undecided = images[i].stem not in checked and images[i].stem not in skipped
        # decided no cat and not confirmed yet (a no-cat stretch confirms: no suggestion comes back there)
        saved_no_cat = images[i].stem in checked and not state["boxes"] and images[i].stem not in confirmed
        if images[i].stem in checked and images[i].stem in confirmed and not state["boxes"]:
            hint = None  # confirmed no cat: no hint, no box snapped at it
        if not state["boxes"] and hint is not None and images[i].stem not in skipped:
            # the other cameras see it here: snap a box at the hint by itself (as a click there would), shown orange
            # to check; nothing found keeps the hint alone (and Space stays guarded)
            hb = hint[1] or [hint[0][0] - 40, hint[0][1] - 40, hint[0][0] + 40, hint[0][1] + 40]
            box = snap_at(img, *hint[0], [hb])
            if box is not None and not lv.too_small(box):
                # a suggestion, orange: nothing is saved until Space (S keeps "no cat")
                state["boxes"], first, kind = [box], [list(box)], "mistake" if saved_no_cat else "hint"
        z = zoom[0]
        if z.z > 1:  # zoomed in: follow the cat into this picture (its box, else the hint)
            target = state["boxes"][0] if state["boxes"] else None
            if target is not None:
                z.centre_on((target[0] + target[2]) / 2, (target[1] + target[3]) / 2)
            elif hint is not None:
                z.centre_on(*hint[0])
        cam_seq = seq.get(cam, [i])
        tl_seq[:] = [cam_seq, i]
        if timeline[0] is None or timeline[0].w != w + lv.SIDE_W:
            timeline[0] = lv.Timeline(w + lv.SIDE_W)
        bar_for = lambda: key_bar(w + lv.SIDE_W, key_groups(prev, hint is not None, prefs["hints"]))  # noqa: E731
        bar = bar_for()
        bright.h = h
        while True:
            if not practice:  # (a practice copy never feeds training: no helper there)
                helper.refresh()
                helper.poll()
                sliders.helper = helper.label()
            if helper.result is not None:
                rec, helper.result = helper.result, None
                if rec.get("state") == "done" and rec.get("promoted") is False:
                    state["note"] = ("This helper isn't better than your current model yet, so it isn't used: "
                                     f"{rec.get('why', '')}. Label more and try again.")
                elif rec.get("state") == "done":
                    snapper.clear()  # clicks use the new helper from now on
                    fill["det"] = None
                    used_here[0] = hp.load_used().get(ses.name, set())
                    todo = [j for j, p_ in enumerate(images) if p_.stem not in checked | skipped | confirmed
                            and not nbox.get(p_.stem)]
                    moments = {}
                    for j in todo:  # one moment (all its cameras) at a time: another camera can confirm a box
                        moments.setdefault(images[j].stem.rsplit("_", 1)[1], []).append(j)
                    fill["queue"] = list(moments.values())
                    fill["n"] = 0
                    state["note"] = (f"Helper trained on {rec.get('pictures', 0)} pictures in {rec.get('minutes', 0)} "
                                     f"min: adding its suggestions to {len(todo)} pictures...")
                else:
                    state["note"] = f"The helper didn't finish ({rec.get('why', 'unknown')}). Labelling is unchanged."
            if fill["queue"]:
                if fill["det"] is None:
                    from cat_tracker import settings as _st, snap as _snap
                    fill["det"] = _snap.make_detector(_st.load(), size=960, score=0.2)  # the newest helper
                if fill["backup"] is None:  # once per session: its labels and auto boxes, before any are added
                    import shutil
                    fill["backup"] = resolve_path("my_data/backups") / f"{time.strftime('%Y%m%d-%H%M%S')}_helper_{ses.name}"
                    shutil.copytree(ses / "labels", fill["backup"] / "labels")
                    if auto_file.is_file():
                        shutil.copy2(auto_file, fill["backup"] / "auto.json")
                group = fill["queue"].pop(0)  # one moment a frame (up to 4 pictures, about 100 ms)
                num = images[group[0]].stem.rsplit("_", 1)[1]
                cams_ = list(getattr(hints, "names", []))
                found, sizes = {}, {}
                for j in group:
                    st = images[j].stem
                    if j == i or st in checked or st in skipped or st in confirmed or nbox.get(st):
                        continue  # decided meanwhile, or on screen now: never touched
                    pic = cv2.imread(str(images[j]))
                    got = hp.best_box(fill["det"], pic) if pic is not None else None
                    if got is not None:
                        c_ = cams_.index(st.rsplit("_", 1)[0]) if st.rsplit("_", 1)[0] in cams_ else -1 - len(found)
                        found[c_], sizes[c_] = got, (st, pic.shape[1], pic.shape[0])
                others = {}
                for k, n_ in enumerate(cams_):  # the boxes already there at this moment (yours or auto ones)
                    if k not in found:
                        b_ = read_boxes(ses / "labels" / f"{n_}_{num}.txt", 1280, 720)
                        if b_:
                            others[k] = b_[0]
                ok_ = hints.ok and all(c_ >= 0 for c_ in found)
                for c_, (box_, kind_) in hp.choose(found, others, hints.rig if ok_ else None,
                                                   hints.I if ok_ else None).items():
                    st, pw, ph = sizes[c_]
                    write_boxes(ses / "labels" / f"{st}.txt", [box_], pw, ph)
                    auto[st], nbox[st] = kind_, 1
                    fill["n"] += 1
                    fill["since_save"] += 1
                if fill["since_save"] >= 20 or not fill["queue"]:
                    auto_file.write_text(json.dumps(auto, indent=1), encoding="utf-8")
                    fill["since_save"] = 0
                if not fill["queue"]:
                    state["note"] = (f"Helper ready: suggested boxes for {fill['n']} pictures (orange: check them). "
                                     f"Backup: my_data\\backups\\{fill['backup'].name}")
            if sliders.helper_clicked:
                sliders.helper_clicked = False
                state["note"] = helper.start()
            if state["snap"] is not None:
                (sx, sy), state["snap"] = state["snap"], None
                box = snap_at(img, sx, sy, prev)
                if box is None:
                    state["note"] = "no cat found there: drag a box instead"
                else:
                    keep = [b for b in state["boxes"] if not (b[0] <= sx <= b[2] and b[1] <= sy <= b[3])]
                    new, why = lv.add_box(keep, box, cats)  # replaces a box under the click (a near miss)
                    if why:
                        state["note"] = why
                    else:
                        state["undo"].append([list(b) for b in state["boxes"]])
                        state["boxes"] = new
                        state["note"] = "snapped (Z undoes it)"
            z = zoom[0]
            view = bright.apply(z.view(img))  # brighter or darker on screen only
            view = lv.draw_boxes(view, z, prev, [BLUE] * len(prev), prefs["blue_pct"])  # exactly the saved box, drawn as the green ones
            cols = [ORANGE if kind is not None and b in first else GREEN for b in state["boxes"]]
            view = lv.draw_boxes(view, z, state["boxes"], cols, prefs["box_pct"])
            hv = state["drag"]["hit"] if state["drag"] and state["drag"]["hit"] else state["hover"]
            if hv and hv[0] < len(state["boxes"]):
                view = lv.draw_handles(view, z, state["boxes"][hv[0]], hv[1])
            if hint is not None and prefs["hints"] and not state["boxes"]:
                view = lv.draw_hint(view, z, hint, prefs["hint_pct"])
            d = state["drag"]
            if d and not d["hit"]:
                p1, p2 = z.to_screen(*d["start"]), z.to_screen(*d["cur"])
                cv2.rectangle(view, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), (0, 200, 255), 1)
            view = lv.cursor_dot(view, state["mouse"])
            # all the words go under the picture
            extra = len(state["boxes"]) > cats
            if extra:
                line2, col2 = f"{len(state['boxes'])} boxes for {cats} cat{'s' if cats > 1 else ''}: keep one per cat " \
                              "(right-click the wrong one)", (80, 80, 255)
            elif state["note"]:
                line2, col2 = state["note"], (0, 255, 255)
            elif rng["start"] is not None:  # the step being done, all the time it lasts
                n_ = abs(i - rng["start"]) + 1
                line2, col2 = (f"No-cat stretch: started at {images[rng['start']].stem} ({n_} picture"
                               f"{'s' if n_ > 1 else ''} so far). Move to the last no-cat picture, then press N again. "
                               "Esc cancels."), (255, 200, 80)
            elif saved_no_cat and images[i].stem in nocat_check:
                line2, col2 = ("Saved as no cat (NO CAT was on while capturing), but the model saw something cat-like "
                               "here. Box her if she's there, or S keeps no cat."), (80, 80, 255)
            elif saved_no_cat and hint is not None:
                line2, col2 = ("Saved as no cat, but other cameras see her here." +
                               (" The orange box is a suggestion: Space keeps it, S keeps no cat." if state["boxes"]
                                else " Box her if she's there, or S keeps no cat."), (80, 80, 255))
            elif images[i].stem in skipped:
                line2, col2 = "SKIPPED: not used for training (Space or S decides after all)", (0, 200, 255)
            elif kind is not None:
                line2, col2 = "auto box: " + {"cross": "from another camera", "filled": "from nearby moments",
                                              "unsure": "the model was unsure here",
                                              "check": "CHECK THIS: the model wasn't sure",
                                              "hint": "snapped at the hint by itself: check it fits"}.get(kind, kind) + \
                    " - is the cat really visible here?" + ("   (R: redo this session's older auto boxes)" if older[0] else
                                                            ""), ORANGE
            elif hint is not None and prefs["hints"] and not state["boxes"]:
                line2, col2 = "magenta cross: where the other cameras place the cat (a hint, not a box)", (255, 0, 255)
            elif prev:
                line2, col2 = "W copies the blue box from the previous picture", BLUE
            else:
                line2, col2 = "click on the cat to snap a box to it", (170, 170, 170)
            if sliders.helper_hover and sliders.helper:
                line2, col2 = hp.EXPLAIN, (0, 210, 255)
            done = sum(p.stem in checked or p.stem in skipped for p in images)
            if amend:
                left = f"reviewed {len(reviewed)} / {len(images)}   ({ses.name}, {amend})"
            else:
                left = f"{done} / {len(images)} decided" + ("  (reviewing pictures with too many boxes)" if review_extra else "")
            if practice:
                left = "PRACTICE COPY: changes aren't saved to training   " + left
            right = ("OLDER AUTO BOXES: R redoes them   " if older[0] else "") +                 f"{images[i].stem}   skipped {len(skipped)}" + (f"   zoom {z.z:.1f}x" if z.z > 1 else "")
            if images[i].stem in used_here[0]:
                right = "IN A HELPER   " + right
            info = lv.info_bar(w + lv.SIDE_W, left, right, line2, col2)
            if practice:  # a red band, so a practice copy is never mistaken for the real thing
                info[:4] = (60, 60, 230)
            sliders.w = w + lv.SIDE_W
            if hints.ok:  # the hint row, a few pictures per frame (about 1 ms each)
                for j in [j for j in cam_seq if images[j].stem not in hint_at][:12]:
                    hint_at[images[j].stem] = hints.at(images[j].stem) is not None
            stems = [images[j].stem for j in cam_seq]
            band = None
            if rng["start"] is not None and rng["start"] in cam_seq:
                band = (cam_seq.index(rng["start"]), cam_seq.index(i))
            sliders.undo_on = hist_file.is_file() and hist_file.stat().st_size > 2  # not just []
            tl = timeline[0].draw([tl_status(s) for s in stems], [tl_mark(s) for s in stems], cam_seq.index(i), band,
                                  [s in used_here[0] for s in stems])
            frame = cv2.vconcat([sliders.draw(), cv2.hconcat([view, bright.draw()]), tl, info, bar])
            cv2.imshow(WIN, frame)
            if sliders.sessions_clicked:
                sliders.sessions_clicked = False
                k = SESSIONS[0]
                break
            if sliders.help_clicked:
                sliders.help_clicked = False
                state["help"] = not state["help"]
                if not state["help"]:
                    cv2.destroyWindow(lv.HELP_WIN)
            if state["help"]:
                page, help_state["sliders"], help_state["y"] = lv.help_page(prefs)
                help_state["h"] = page.shape[0]
                if page.shape[0] > HELP_VIEW_H:  # the part in view; the wheel scrolls
                    sc = help_state["scroll"]
                    page = page[sc:sc + HELP_VIEW_H].copy()
                    cv2.putText(page, "the wheel scrolls", (page.shape[1] - 170, HELP_VIEW_H - 12),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1, cv2.LINE_AA)
                if help_state.get("open"):
                    try:
                        if cv2.getWindowProperty(lv.HELP_WIN, cv2.WND_PROP_VISIBLE) < 1:  # closed with its X
                            state["help"], help_state["open"] = False, False
                    except cv2.error:
                        state["help"], help_state["open"] = False, False
                if state["help"]:
                    cv2.imshow(lv.HELP_WIN, page)
                    if not help_state.get("open"):
                        cv2.setMouseCallback(lv.HELP_WIN, on_help_mouse)
                        help_state["open"] = True
            elif help_state.get("open"):
                help_state["open"] = False
            k = read_key(20)
            watch_keys()
            if state.get("goto") is not None:  # a click on the timeline
                break
            if k == 27 and rng["start"] is not None:  # Esc: cancels the stretch (it doesn't quit)
                rng["start"] = None
                state["note"] = "No-cat stretch cancelled (Esc). Nothing changed."
                continue
            if k in RANGE:
                if rng["start"] is None:
                    rng["start"] = i
                    state["note"] = ""
                elif rng["start"] == i:
                    rng["start"] = None
                    state["note"] = "No-cat stretch cancelled: N on the picture it started at. Nothing changed."
                elif images[rng["start"]].stem.rsplit("_", 1)[0] != cam:  # (moving can't leave the camera; a click
                    rng["start"] = i                                       # on the sessions screen might)
                    state["note"] = "That was another camera's stretch: it starts here now instead."
                else:
                    rng["apply"] = tuple(sorted((rng["start"], i)))
                    break
                continue
            if sliders.undo_clicked:
                sliders.undo_clicked = False
                k = UNDO_STRETCH[0]
            if k in UNDO_STRETCH or (k in UNDO and not state["undo"] and rng["last"]):
                undo_stretch(state["boxes"])
                continue
            if k in KEEP + NO_CAT:  # held down: stop where it matters, until it's let go and pressed again
                group = "keep" if k in KEEP else "nocat"
                if held(group):
                    why = None
                    if group == "nocat" and state["boxes"]:
                        why = "this one has a box"
                    elif group == "nocat" and hint is not None:
                        why = "the other cameras see the cat here"
                    elif group == "keep" and not state["boxes"]:
                        why = "no box here"
                    elif group == "keep" and hint is not None:
                        why = "the other cameras see the cat here, check the box"
                    elif group == "keep" and kind == "check":
                        why = "a CHECK THIS box"
                    if why:
                        hold["blocked"] = True
                        state["note"] = f"Stopped: {why}. Press {'Space' if group == 'keep' else 'S'} again to go on."
                        continue
            if k in REDO and older[0]:
                break  # redo this session's older auto boxes (below), then show this picture again
            if k in REDO:
                state["note"] = "this session's auto boxes are already today's method"
                continue
            if k in HINT:
                prefs["hints"] = not prefs["hints"]
                save()
                bar = bar_for()
                continue
            if k in HELP:
                sliders.help_clicked = True
                continue
            if k in UNDO and state["undo"]:
                state["boxes"] = state["undo"].pop()
                continue
            if k in REUSE:  # W: the blue box becomes a green one, here; Space then moves on
                if not prev:
                    state["note"] = "no blue box to copy here"
                else:
                    state["undo"].append([list(b) for b in state["boxes"]])
                    state["boxes"] = [list(b) for b in prev][:cats]
                    state["note"] = "copied the blue box: Space if it's right"
                continue
            if k in KEEP and len(state["boxes"]) > cats:
                state["note"] = ""
                continue  # the warning under the picture says why
            if k in KEEP and not state["boxes"] and hint is not None:
                # Space on an empty picture would save "no cat", but the other cameras see it here: say so instead
                state["note"] = "Other cameras see the cat here. Box it, S = no cat, D = not sure."
                continue
            if k in KEEP + NO_CAT + SKIP + BACK + QUIT + JUMP + SESSIONS + STEP_BACK + STEP_FWD:
                break
        if state.get("goto") is not None:  # jump there on the timeline, deciding nothing
            j = cam_seq[state.pop("goto")]
            state["boxes"] = lv.dedupe(state["boxes"])
            write_boxes(lab, state["boxes"], w, h)
            nbox[images[i].stem] = len(state["boxes"])
            i = j
            continue
        if rng["apply"] is not None:  # the second N: everything in the stretch becomes no cat, whatever it was
            a_, b_ = rng["apply"]
            rng["apply"] = rng["start"] = None
            had_box = had_cat = was_skipped = 0
            rng["old"] = {}
            for j in range(a_, b_ + 1):
                st = images[j].stem
                p_ = ses / "labels" / f"{st}.txt"
                text = p_.read_text(encoding="utf-8") if p_.is_file() else ""
                rng["old"][st] = (text, st in checked, st in skipped, st in confirmed)  # for Z
                n_ = len(state["boxes"]) if j == i else nbox.get(st, 0)
                had_box += n_ > 0
                had_cat += n_ > 0 and st in checked
                was_skipped += st in skipped
                write_boxes(p_, [], w, h)
                nbox[st] = 0
                checked.add(st)
                skipped.discard(st)
                confirmed.add(st)  # decided by you: no hint suggestion comes back, off the review lists
                reviewed.add(st)
            state["boxes"] = []
            confirmed_file.write_text("\n".join(sorted(confirmed)), encoding="utf-8")
            checked_file.write_text("\n".join(sorted(checked)), encoding="utf-8")
            skipped_file.write_text("\n".join(sorted(skipped)), encoding="utf-8")
            rng["last"] = list(rng["old"])
            rng["skip"] |= set(rng["last"])
            hh = load_hist()
            hh.append({"from": images[a_].stem, "to": images[b_].stem,
                       "pictures": {st: list(v) for st, v in rng["old"].items()}})
            save_hist(hh)
            n_all = b_ - a_ + 1
            extra_ = [f"{had_box} had a box (deleted)" if had_box else "",
                      f"{had_cat} of them you had marked cat" if had_cat else "",
                      f"{was_skipped} {'was' if was_skipped == 1 else 'were'} skipped" if was_skipped else ""]
            state["next_note"] = (f"Marked all {n_all} no cat" + (": " + ", ".join(x for x in extra_ if x) if any(extra_)
                                                                    else "") + ". Z undoes it.")
            i = b_ if b_ + 1 >= len(images) else b_ + 1
            continue
        if k in SESSIONS:  # the sessions screen; this picture's changes are kept as they are, undecided
            state["boxes"] = lv.dedupe(state["boxes"])
            write_boxes(lab, state["boxes"], w, h)
            return ("sessions", i)
        if k in REDO:
            print(f"Redoing {ses.name}'s auto boxes with today's method (your decided pictures stay as they are)...")
            autolabel.main(["--session", ses.name])
            auto = json.loads(auto_file.read_text(encoding="utf-8")) if auto_file.is_file() else {}
            older[0] = False
            continue  # the same picture again, with its new box
        if k in NO_CAT:
            state["boxes"] = []
        state["boxes"] = lv.dedupe(state["boxes"])
        write_boxes(lab, state["boxes"], w, h)
        nbox[images[i].stem] = len(state["boxes"])
        if k in KEEP + NO_CAT + SKIP:
            reviewed.add(images[i].stem)
            # a CHECK THIS box or a "no cat" the other cameras doubt, now decided by you: it leaves those filters
            if auto.get(images[i].stem) == "check" or (saved_no_cat and (hint is not None
                                                                          or images[i].stem in nocat_check)):
                confirmed.add(images[i].stem)
                confirmed_file.write_text("\n".join(sorted(confirmed)), encoding="utf-8")
        if k in KEEP + NO_CAT + SKIP:
            rng["last"], rng["old"] = None, {}  # decided: Z no longer undoes the stretch
        if k in KEEP + NO_CAT:  # only a decision marks it checked; quit, jump and back don't
            checked.add(images[i].stem)
            skipped.discard(images[i].stem)
        elif k in SKIP:  # not sure: out of training, but its boxes are kept as they are
            skipped.add(images[i].stem)
            checked.discard(images[i].stem)
        skipped_file.write_text("\n".join(sorted(skipped)), encoding="utf-8")
        checked_file.write_text("\n".join(sorted(checked)), encoding="utf-8")
        if k in QUIT:
            break
        nxt = i + (-1 if k in BACK + STEP_BACK else (10 if k in JUMP else 1))
        if rng["start"] is not None and k in BACK + STEP_BACK + STEP_FWD + JUMP and nxt not in cam_seq:
            state["next_note"] = ("This camera's pictures end here: press N to end the stretch here, or Esc."
                                  if nxt > i else "This camera's pictures start here.")
            nxt = min(max(nxt, cam_seq[0]), cam_seq[-1])  # a stretch stays in one camera
        i = nxt
        if k in KEEP + NO_CAT + SKIP:  # past the pictures a stretch just marked
            while i < len(images) and images[i].stem in rng["skip"]:
                i += 1
        i = max(i, 0)
    if state["help"]:
        try:
            cv2.destroyWindow(lv.HELP_WIN)
        except cv2.error:
            pass
    print(f"{len(checked)} of {len(images)} images checked in {ses}")
    if k in QUIT:
        cv2.destroyAllWindows()
        return "quit"
    return "done"  # on to the next session in the same window


if __name__ == "__main__":
    raise SystemExit(main())
