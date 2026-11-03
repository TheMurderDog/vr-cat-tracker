"""Check and fix the cat boxes in a capture session, one image at a time.

From the camera core folder:  python -m cat_tracker.label                 every session with unchecked images, newest first
                      python -m cat_tracker.label --session 20261030-201500
Mouse: drag to draw a box around her, right-click a box to delete it.
Keys:  space or enter = keep and go to the next image, backspace = back one, z = undo the last box
       you drew or deleted, r = use the previous image's boxes instead (shown blue: the same camera's
       image just before, if you checked it; for when she hasn't moved) and go to the next image,
       x = no cat in this image (clears the boxes) and next, j = skip ahead 10, q = save and quit.
Every image you move past counts as checked (listed in checked.txt), so you can stop and come back.
Only checked images are used for training. Boxes added by autolabel.bat are orange until you move on.
"""

import argparse
import json

import cv2

from core.config import resolve_path

WIN = "Label the cat (drag = box, right-click = delete, z = undo, r = reuse blue box, space = next, x = no cat, backspace = back, q = quit)"


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
    args = ap.parse_args()
    root = resolve_path("cat_tracker/captures")
    sessions = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    if args.session:
        todo = [root / args.session]
    else:  # every session with images still to check, newest first (the tracker's -hard ones included)
        todo = [p for p in reversed(sessions) if (p / "images").is_dir() and unchecked(p)]
        if not todo:
            print(f"Nothing left to check in {root}. Capture more: capture.bat, or play with the tracker running")
            return 0
        print("Sessions to check, newest first: " + ", ".join(f"{p.name} ({unchecked(p)})" for p in todo))
    for ses in todo:
        if not (ses / "images").is_dir():
            print(f"No capture session {ses}")
            return 1
        print(f"Checking {ses.name}")
        if label_session(ses, args.start) == "quit":
            break
    cv2.destroyAllWindows()
    return 0


def unchecked(ses):
    ck = ses / "checked.txt"
    done = set(ck.read_text(encoding="utf-8").split()) if ck.is_file() else set()
    return sum(p.stem not in done for p in (ses / "images").glob("*.jpg"))


def label_session(ses, start=None):
    images = sorted((ses / "images").glob("*.jpg"))
    checked_file = ses / "checked.txt"
    checked = set(checked_file.read_text(encoding="utf-8").split()) if checked_file.is_file() else set()
    i = start if start is not None else next((k for k, p in enumerate(images) if p.stem not in checked), 0)
    auto_file = ses / "auto.json"
    auto = json.loads(auto_file.read_text(encoding="utf-8")) if auto_file.is_file() else {}
    state = {"boxes": [], "drag": None, "cur": None, "undo": []}

    def on_mouse(ev, x, y, flags, _):
        s = scale[0]
        x, y = x / s, y / s
        if ev == cv2.EVENT_LBUTTONDOWN:
            state["drag"], state["cur"] = (x, y), (x, y)
        elif ev == cv2.EVENT_MOUSEMOVE and state["drag"]:
            state["cur"] = (x, y)
        elif ev == cv2.EVENT_LBUTTONUP and state["drag"]:
            (x0, y0), state["drag"] = state["drag"], None
            if abs(x - x0) > 6 and abs(y - y0) > 6:
                state["undo"].append(list(state["boxes"]))
                state["boxes"].append([min(x0, x), min(y0, y), max(x0, x), max(y0, y)])
        elif ev == cv2.EVENT_RBUTTONDOWN:
            state["undo"].append(list(state["boxes"]))
            state["boxes"] = [b for b in state["boxes"] if not (b[0] <= x <= b[2] and b[1] <= y <= b[3])]

    scale = [1.0]
    cv2.namedWindow(WIN)
    cv2.setMouseCallback(WIN, on_mouse)
    k = None
    while 0 <= i < len(images):
        img = cv2.imread(str(images[i]))
        h, w = img.shape[:2]
        lab = ses / "labels" / f"{images[i].stem}.txt"
        state["boxes"] = read_boxes(lab, w, h)
        state["undo"] = []
        kind = auto.get(images[i].stem) if images[i].stem not in checked else None
        first = [list(b) for b in state["boxes"]]
        # the same camera's previous image, if it was checked: she often hasn't moved
        prev = []
        if i > 0 and images[i - 1].stem.rsplit("_", 1)[0] == images[i].stem.rsplit("_", 1)[0] \
                and images[i - 1].stem in checked:
            prev = read_boxes(ses / "labels" / f"{images[i - 1].stem}.txt", w, h)
        while True:
            view = img.copy()
            for b in state["boxes"]:
                orange = kind is not None and b in first  # added by autolabel, not yet looked at
                cv2.rectangle(view, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), (0, 165, 255) if orange else (0, 255, 0), 2)
            if kind is not None:
                cv2.putText(view, "auto box: " + {"cross": "from another camera", "filled": "from nearby moments",
                                                 "unsure": "the model was unsure here"}.get(kind, kind)
                            + " - is she really visible here?", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2, cv2.LINE_AA)
            for b in prev:
                cv2.rectangle(view, (int(b[0]) - 3, int(b[1]) - 3), (int(b[2]) + 3, int(b[3]) + 3), (255, 80, 0), 3, cv2.LINE_AA)
            hint = ("r = reuse the blue box from the previous frame" if prev else
                    "no blue box: previous frame is another camera, not checked yet, or had no box" if i > 0 else "")
            cv2.putText(view, hint, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 80, 0) if prev else (200, 200, 200), 2, cv2.LINE_AA)
            if state["drag"]:
                (x0, y0), (x1, y1) = state["drag"], state["cur"]
                cv2.rectangle(view, (int(x0), int(y0)), (int(x1), int(y1)), (0, 200, 255), 1)
            done = sum(p.stem in checked for p in images)
            cv2.putText(view, f"{i + 1}/{len(images)}  {images[i].stem}  checked {done}", (10, h - 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
            cv2.imshow(WIN, view)
            k = cv2.waitKey(20) & 0xFF
            if k == ord("z") and state["undo"]:
                state["boxes"] = state["undo"].pop()
                continue
            if k == ord("r") and not prev:
                continue  # nothing to reuse here
            if k in (ord(" "), 13, ord("x"), ord("r"), ord("j"), 8, ord("q"), 27):
                break
        if k == ord("x"):
            state["boxes"] = []
        if k == ord("r"):
            state["boxes"] = [list(b) for b in prev]
        write_boxes(lab, state["boxes"], w, h)
        if k in (ord(" "), 13, ord("x"), ord("r")):  # only a decision marks it checked; q, j and backspace don't
            checked.add(images[i].stem)
        checked_file.write_text("\n".join(sorted(checked)), encoding="utf-8")
        if k in (ord("q"), 27):
            break
        i += -1 if k == 8 else (10 if k == ord("j") else 1)
        i = max(i, 0)
    print(f"{len(checked)} of {len(images)} images checked in {ses}")
    if k in (ord("q"), 27):
        cv2.destroyAllWindows()
        return "quit"
    return "done"  # on to the next session in the same window


if __name__ == "__main__":
    raise SystemExit(main())
