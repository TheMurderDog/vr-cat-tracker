"""Starts the tracker for VR, and the Cat Tracker app with it when the app is installed.

Used by 5_play_in_vr\\run_tracker.bat, 6_optional_vrchat\\3_run_with_vrchat.bat, both restart scripts and the
SteamVR autostart (cat_tracker.autostart), so the app opens however the tracker is started:

  python -m cat_app.launch [--background] [--no-app] -- <the tracker's options>

- App installed (PySide6 in .venv): opens the app (or shows the one already running) and runs the tracker
  through cat_app.bridge, so the app is its window. --background: the app shows only its SteamVR tab, and the
  tracker's messages go to my_data/logs/cat_app/bridge.log (for pythonw, which has no console).
- App not installed, or --no-app: runs cat_tracker.run as before, with its own window.
Imports nothing from Qt, so it works without the app.
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent


def app_installed():
    return importlib.util.find_spec("PySide6") is not None and (ENGINE / "cat_app" / "main.py").is_file()


def open_app(background):
    """Opens the app in its own process; if it's already running, that copy shows its window instead."""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    args = [str(pyw if pyw.is_file() else exe), "-m", "cat_app.main"] + (["--background"] if background else [])
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    try:
        subprocess.Popen(args, cwd=str(ENGINE), creationflags=flags, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        return True
    except OSError as e:
        print(f"Couldn't open the Cat Tracker app ({e}); the tracker runs anyway.", flush=True)
        return False


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    own, tracker = (argv[:argv.index("--")], argv[argv.index("--") + 1:]) if "--" in argv else ([], argv)
    background = "--background" in own
    if "--no-app" in own or "--no-app" in tracker or not app_installed():
        sys.argv = ["cat_tracker.run"] + [a for a in tracker if a != "--no-app"]
        from cat_tracker import run
        return run.main()
    open_app(background)
    if not background:
        print("The Cat Tracker app is its window: Stop and Re-anchor are buttons there (in the SteamVR dashboard's "
              "cat tab too).\nThe tracker's messages are below. Closing this window stops the tracker.", flush=True)
    sys.argv = ["cat_app.bridge"] + ([] if background else ["--console"]) + ["--"] + tracker
    from cat_app import bridge
    return bridge.main()


if __name__ == "__main__":
    from core.runlog import exit_now
    exit_now(main())
