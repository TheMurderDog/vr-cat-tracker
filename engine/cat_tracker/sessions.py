"""The labelled pictures, one self-contained folder per session in my_data/captures: images/, labels/, checked.txt
(decided), skipped.txt (not sure), auto.json (boxes the autolabeler added), and session.json, a small summary:
date, where it came from (a capture, the tracker's hard moments, or imported), which camera setup (the current one,
after the last room calibration, or an older one), the counts, and the autolabel method.

  python -m cat_tracker.sessions                      write every session.json and list them
  python -m cat_tracker.sessions --import FOLDER      copy labelled sessions from another captures folder (read
                                                      only there) into my_data/captures as "imported"
"""

import argparse
import json
import shutil
import time
from pathlib import Path

from core.config import resolve_path


def _set(p):
    return set(p.read_text(encoding="utf-8").split()) if p.is_file() else set()


def _boxes(lab):
    if not lab.is_file():
        return 0
    return sum(1 for line in lab.read_text(encoding="utf-8").split("\n") if len(line.split()) == 5)


def info(ses, since="", cats=1):
    """The session's summary (also written to session.json, keeping its source if one was recorded)."""
    old = {}
    try:
        old = json.loads((ses / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    images = sorted(p.stem for p in (ses / "images").glob("*.jpg")) if (ses / "images").is_dir() else []
    checked, skipped = _set(ses / "checked.txt"), _set(ses / "skipped.txt")
    auto = {}
    try:
        auto = json.loads((ses / "auto.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    n_boxes = {s: _boxes(ses / "labels" / f"{s}.txt") for s in images}
    confirmed = _set(ses / "confirmed.txt")  # CHECK THIS pictures and possible mistakes already decided in review
    name = ses.name
    stamp = name[:15]
    try:
        date = time.strftime("%Y-%m-%d %H:%M", time.strptime(stamp, "%Y%m%d-%H%M%S"))
    except ValueError:
        date = ""
    source = old.get("source") or ("tracker's hard moments" if name.endswith("-hard") else "capture")
    try:
        method = json.loads((ses / "autolabel_method.json").read_text(encoding="utf-8")).get("method")
    except (OSError, ValueError):
        method = "outline" if auto else None
    out = {
        "session": name, "date": date, "source": source,
        "camera setup": "current" if since and stamp >= since else "older" if since else "unknown",
        "pictures": len(images),
        "decided": len(checked & set(images)),
        "with cat": sum(1 for s in checked if n_boxes.get(s, 0) > 0),
        "no cat": sum(1 for s in checked if s in n_boxes and n_boxes[s] == 0),
        "skipped": len(skipped & set(images)),
        "undecided": len([s for s in images if s not in checked and s not in skipped]),
        "check this": sum(1 for s, k in auto.items() if k == "check" and s in n_boxes and s not in confirmed),
        "more boxes than cats": sum(1 for v in n_boxes.values() if v > cats),
        "possible mistakes": possible_mistakes(ses, checked - confirmed, n_boxes) if since and stamp >= since else 0,
        "autolabel method": method,
    }
    if old.get("imported_from"):
        out["imported_from"] = old["imported_from"]
    if old.get("role"):
        out["role"] = old["role"]  # "test": the fair test set, never trained on
    try:
        (ses / "session.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    except OSError:
        pass
    return out


def possible_mistakes(ses, checked, n_boxes):
    """Pictures decided as no cat where the other cameras place the cat (current camera setup only)."""
    try:
        from cat_tracker.label_view import Hints
        h = Hints(ses)
        if not h.ok:
            return 0
        from cat_tracker.collect import nocat_flagged
        flagged = nocat_flagged(ses)  # NO CAT pictures where the model saw something cat-like
        return sum(1 for s in checked if n_boxes.get(s, 1) == 0 and (s in flagged or h.at(s) is not None))
    except Exception:  # noqa: BLE001
        return 0


def setup_since():
    from cat_tracker.train_extras import setup_since as since
    return since(resolve_path("my_data/calibration") / "room.json")


def all_sessions(root=None, cats=1):
    root = Path(root) if root else resolve_path("my_data/captures")
    since = setup_since()
    return [info(p, since, cats) for p in sorted(root.iterdir()) if (p / "images").is_dir()] if root.is_dir() else []


def import_sessions(src_root, dst_root=None, log=print):
    """Copy every labelled session (one with a checked.txt) from src_root into dst_root as 'imported'. src_root is
    only read. A session already there is left as it is. Returns the names copied."""
    src_root, dst_root = Path(src_root), Path(dst_root) if dst_root else resolve_path("my_data/captures")
    copied = []
    for ses in sorted(p for p in src_root.iterdir() if (p / "images").is_dir() and (p / "checked.txt").is_file()):
        dst = dst_root / ses.name
        if dst.exists():
            log(f"  {ses.name}: already here, left as it is")
            continue
        shutil.copytree(ses, dst)
        meta = {"source": "imported", "imported_from": str(ses)}
        (dst / "session.json").write_text(json.dumps(meta), encoding="utf-8")
        copied.append(ses.name)
        log(f"  {ses.name}: copied")
    return copied


def main(argv=None):
    ap = argparse.ArgumentParser(description="List the labelled sessions, or import some")
    ap.add_argument("--import", dest="imp", metavar="FOLDER", help="copy labelled sessions from this captures folder")
    ap.add_argument("--test", metavar="NAME", help="mark this session as the fair test set (never trained on)")
    ap.add_argument("--not-test", metavar="NAME", help="unmark it: it can be trained on again")
    args = ap.parse_args(argv)
    from cat_tracker import train_extras as tx
    listed = resolve_path("my_data/training") / "test_sessions.txt"
    for name, on in ((args.test, True), (args.not_test, False)):
        if name:
            ses = resolve_path("my_data/captures") / name
            if not (ses / "images").is_dir():
                print(f"No session called {name} in {ses.parent}")
                return 1
            tx.mark_test(ses, listed, on)
            print(f"{name}: " + ("TEST SET, never trained on" if on else "no longer the test set"))
    if args.imp:
        names = import_sessions(args.imp)
        print(f"Imported {len(names)} sessions into {resolve_path('my_data/captures')}")
    for s in all_sessions():
        print(f"{s['session']:24s} {s['date']:16s} {s['source']:22s} {s['camera setup']:7s} "
              + ("TEST " if s.get("role") == "test" else "     ") +
              f"{s['decided']:5d} decided ({s['with cat']} with cat, {s['no cat']} no cat), {s['skipped']} skipped, "
              f"{s['undecided']} to do")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
