"""Shows a notice in VR (and buzzes the controllers) if the cat tracker stops unexpectedly.

When the tracker crashes, is killed or freezes, its overlays disappear with it, and an empty room
looks exactly like a stopped tracker. So the tracker starts this small separate process, which
watches it through cat_tracker/data/heartbeat.json and its process id:

  - the tracker closes on purpose (q, stop_tracker.bat, SteamVR closing): it writes "stopped", and
    this quietly exits too;
  - the tracker's process is gone without that, or its heartbeat is older than hang_s: a notice
    "Cat tracker stopped" in front of you, and one buzz pattern;
  - the notice stays until the tracker runs again (restart_tracker.bat or run.bat), you run
    stop_tracker.bat, or SteamVR closes.

Started by run.py (health.watchdog in config.yaml); not meant to be run by hand.
  python -m cat_tracker.watchdog --pid 1234 [--hang-s 15]
"""

import argparse
import json
import logging
import os
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
HEARTBEAT = HERE / "data" / "heartbeat.json"
STOP = HERE / "data" / "stop"


def pid_alive(pid):
    """True while process pid is running. (On Windows, os.kill(pid, 0) would send it Ctrl+C, so not that.)"""
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_heartbeat(path=HEARTBEAT):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def verdict(hb, pid, alive, hang_s, now):
    """What to do, from the heartbeat and whether the tracker process is alive:
    "exit" (closed on purpose, or a newer tracker took over), "stopped", "frozen" or "ok"."""
    if hb is not None and hb.get("pid") != pid:
        return "exit"
    if hb is not None and hb.get("state") == "stopped":
        return "exit"
    if not alive:
        return "stopped"
    if hb is None or now - float(hb.get("t", 0)) > hang_s:
        return "frozen"
    return "ok"


def main():
    ap = argparse.ArgumentParser(description="Cat tracker watchdog")
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--hang-s", type=float, default=15.0)
    ap.add_argument("--no-buzz", action="store_true")
    args = ap.parse_args()
    log_dir = HERE / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(log_dir / "watchdog.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("watchdog")
    log.info("Watching the cat tracker (pid %d)", args.pid)

    from cat_tracker.notice import render
    from cat_tracker.vrlink import VRLink
    try:
        vr = VRLink()
    except Exception as e:  # noqa: BLE001
        log.error("SteamVR not available (%s); nothing to watch for", e)
        return 1
    if not args.no_buzz:
        vr.setup_haptics(HERE / "input" / "actions.json", log)
    images = {
        "stopped": render(HERE / "data" / "notice_stopped.png", "CAT TRACKER STOPPED",
                          ["She is NOT being tracked.", "Restart it: restart_tracker.bat or run.bat",
                           "Or run stop_tracker.bat to hide this."]),
        "frozen": render(HERE / "data" / "notice_frozen.png", "CAT TRACKER NOT RESPONDING",
                         ["She may NOT be tracked.", "Restart it: restart_tracker.bat or run.bat",
                          "Or run stop_tracker.bat to hide this."]),
    }
    vr.add_overlay("watchdog", images["stopped"], 0.6)
    T = np.eye(4)
    T[:3, 3] = [0.0, -0.1, -1.2]  # a little below the middle of your view, 1.2 m away
    shown = None
    try:
        while True:
            if vr.quit_requested():
                log.info("SteamVR is closing")
                break
            vr.update_input()
            v = verdict(read_heartbeat(), args.pid, pid_alive(args.pid), args.hang_s, time.time())
            if v == "exit":
                log.info("The tracker closed normally, or a new one started; done")
                break
            if v in ("stopped", "frozen"):
                if shown != v:
                    log.warning("Tracker %s: showing the notice", v)
                    vr.set_image("watchdog", images[v])
                    vr.place_on_head("watchdog", T, 0.95)
                    if shown is None and not args.no_buzz:
                        vr.buzz_pattern("LRLRLR", 1.5, 0.2, 0.8)
                    shown = v
                if STOP.exists():  # stop_tracker.bat with no tracker left to read it: hide and finish
                    STOP.unlink(missing_ok=True)
                    log.info("Dismissed with stop_tracker.bat")
                    break
            elif shown is not None:  # it came back from a freeze
                log.info("Tracker responding again")
                vr.place_on_head("watchdog", None, 0)
                shown = None
            time.sleep(0.5)
    finally:
        vr.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
