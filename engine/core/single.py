"""One camera tool at a time: a tool that opens the cameras first waits until no other one has them.

The lock is an exclusive lock on a file, held by this process until it exits. Windows drops it the moment the process
ends, however it ends (crash, closed window, Task Manager), so a lock left over from a crash can't block anything:
the file itself is only a name, its contents never matter.

It's one lock per Windows user (in %LOCALAPPDATA%\\vr-cat-tracker), not one per copy of the project: two copies (say,
a test copy, while the tracker from another copy starts with SteamVR) use the same cameras, so they share the lock.
Beside it the holder notes who it is (program and folder), so a waiting tool can say who has the cameras.
"""

import os
import sys
import threading
import time
from pathlib import Path

from core.config import DATA

_LOCAL = os.environ.get("LOCALAPPDATA")
LOCK_PATH = (Path(_LOCAL) / "vr-cat-tracker" / "cameras.lock") if _LOCAL else DATA / ".cameras.lock"
WAIT_MESSAGE = "Another cat tracker tool is still open. Close it and I'll start."
WAIT_WINDOW = "Waiting for the cameras"
PROGRAMS = {"run.py": "the cat tracker", "autostart.py": "the cat tracker", "calib_room.py": "room calibration",
            "calib_check.py": "the calibration check", "calib_intrinsics.py": "lens calibration",
            "camera_setup.py": "camera setup", "preview.py": "the camera preview"}
_held = {"fd": None}
_guard = threading.Lock()


def _try_lock(fd):
    if sys.platform == "win32":
        import msvcrt
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _holder_path(p):
    return p.with_name(p.name + ".holder")


def _running(pid):
    """Is this process still running? (On Windows asked without touching it; elsewhere assumed.)"""
    if sys.platform != "win32":
        return True
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k.CloseHandle(h)


def holder_info(path=None):
    """(program, folder) of whoever holds the lock, as its holder noted it, or None if unknown or that process has
    ended (a note left over from a crash)."""
    try:
        pid, prog, folder = (_holder_path(path or LOCK_PATH).read_text(encoding="utf-8").strip().split("|") + ["", ""])[:3]
    except OSError:
        return None
    return (prog, folder) if prog and pid.isdigit() and _running(int(pid)) else None


def holder(path=None):
    """Who holds the lock, "program, in folder", or None (see holder_info)."""
    info = holder_info(path)
    return f"{info[0]}, in {info[1]}" if info else None


def wait_message(path=None, spoken=False, can_stop=False):
    """What a waiting tool says: who has the cameras when known, and how to close it. spoken: short, without folder
    or file names (for the voice). can_stop: the waiting window offers S to ask the tracker to stop."""
    info = holder_info(path)
    if info is None:
        return WAIT_MESSAGE
    prog, folder = info
    who = prog[0].upper() + prog[1:]
    if prog == "the cat tracker":
        if spoken:
            how = "Press S and I'll ask it to stop, or quit SteamVR." if can_stop else \
                "Run stop tracker from step 5, or quit SteamVR."
            return f"{who} is using the cameras. Close it first. {how}"
        return (f"{who} is using the cameras (from {folder}). Close it first: run 5_play_in_vr\\stop_tracker.bat "
                f"there, or quit SteamVR. I'll start as soon as it's closed.")
    if spoken:
        return f"{who} is using the cameras. Close it first, and I'll start."
    return f"{who} is using the cameras (from {folder}). Close it first, and I'll start as soon as it's closed."


def ask_tracker_to_stop(path=None):
    """Ask the tracker that holds the cameras to stop, as stop_tracker.bat does (its stop file). True if asked."""
    info = holder_info(path)
    if not info or info[0] != "the cat tracker" or not info[1]:
        return False
    stop = Path(info[1]) / "my_data" / "tracker" / "stop"
    try:
        stop.parent.mkdir(parents=True, exist_ok=True)
        stop.write_text("stop", encoding="utf-8")
        return True
    except OSError:
        return False


def _wait_window(text, can_stop, asked):
    """The waiting window (camera tools only). Returns the key pressed (lower case) or None."""
    import textwrap

    import cv2
    import numpy as np
    w = 1100
    lines = textwrap.wrap(text, 70, break_on_hyphens=False)
    keys = ("S  ask the tracker to stop      " if can_stop and not asked else "") + "Q  quit"
    img = np.full((120 + 40 * len(lines) + 70, w, 3), 30, np.uint8)
    cv2.putText(img, "WAITING FOR THE CAMERAS", (24, 56), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 220, 255), 2, cv2.LINE_AA)
    y = 110
    for line in lines:
        cv2.putText(img, line, (24, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (240, 240, 240), 2, cv2.LINE_AA)
        y += 40
    if asked:
        cv2.putText(img, "Asked the tracker to stop: a second or two...", (24, y + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.75,
                    (80, 220, 80), 2, cv2.LINE_AA)
    cv2.putText(img, keys, (24, img.shape[0] - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1, cv2.LINE_AA)
    cv2.imshow(WAIT_WINDOW, img)
    k = cv2.waitKey(1) & 0xFF
    return chr(k).lower() if k != 255 else None


def _program():
    main = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    return PROGRAMS.get(main, "another cat tracker tool")


def hold_cameras(log=None, say=None, path=None, timeout_s=None, poll_s=0.5, tell_every_s=15.0, show=False):
    """Take the camera lock for the rest of this process, waiting while another tool holds it.
    say(text), if given, is called with the wait message (e.g. the voice); it's also printed and logged.
    show: the camera tools (not the tracker) show a window while they wait, saying who has the cameras, with S to
    ask the tracker to stop and Q to quit (Q ends this program).
    Returns True once held (at once if this process already holds it), False if timeout_s ran out."""
    with _guard:
        if _held["fd"] is not None:
            return True
        p = path or LOCK_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(p), os.O_RDWR | os.O_CREAT, 0o644)
        start = told = None
        asked = False
        while not _try_lock(fd):
            now = time.monotonic()
            start = start or now
            can_stop = show and not asked and (holder_info(p) or ("",))[0] == "the cat tracker"
            if told is None or now - told >= tell_every_s:
                msg = wait_message(p)
                print(msg, flush=True)
                if log:
                    log.warning(msg)
                if say:
                    say(wait_message(p, spoken=True, can_stop=can_stop))
                told = now
            if timeout_s is not None and now - start >= timeout_s:
                os.close(fd)
                _close_window(show)
                return False
            if show:
                key = _wait_window(wait_message(p), can_stop, asked)
                if key == "s" and can_stop:
                    asked = ask_tracker_to_stop(p)
                    if log:
                        log.info("Asked the tracker to stop (S in the waiting window): %s", "done" if asked else "couldn't")
                elif key in ("q", "\x1b"):
                    if log:
                        log.info("Quit while waiting for the cameras")
                    _close_window(show)
                    os.close(fd)
                    raise SystemExit(0)
            time.sleep(poll_s)
        _close_window(show and start is not None)
        if start is not None and log:
            log.info("The other tool closed; starting (waited %.0f s)", time.monotonic() - start)
        _held["fd"] = fd  # kept open on purpose: the lock lasts until this process exits
        try:  # who has it, for a tool that has to wait (only a hint: the next holder overwrites it)
            _holder_path(p).write_text(f"{os.getpid()}|{_program()}|{DATA.parent}", encoding="utf-8")
        except OSError:
            pass
        return True


def _close_window(show):
    if show:
        try:
            import cv2
            cv2.destroyWindow(WAIT_WINDOW)
            cv2.waitKey(1)
        except Exception:  # noqa: BLE001  (never shown)
            pass


def release_cameras():
    """Give the lock back early (only for tests; normally it simply ends with the process)."""
    with _guard:
        fd, _held["fd"] = _held["fd"], None
        if fd is not None:
            os.close(fd)
