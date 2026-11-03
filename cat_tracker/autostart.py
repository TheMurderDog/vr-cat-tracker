"""What SteamVR runs when it starts (registered by install_autostart.bat): the tracker with no window.

SteamVR starts it from its own folder with the camera core's .venv pythonw.exe, so this moves into the camera core folder
first, then runs cat_tracker.run with the arguments saved in the manifest (--reuse-anchor --headless and
whatever was given to install_autostart.bat). The tracker closes when SteamVR does. With no window,
anything that goes wrong before the log starts is written to cat_tracker/logs/autostart_error.txt.
"""

import os
import sys
import traceback
from pathlib import Path

FBT = Path(__file__).resolve().parent.parent


def main():
    os.chdir(FBT)
    sys.path.insert(0, str(FBT))
    sys.argv = ["cat_tracker.run"] + sys.argv[1:]
    try:
        from cat_tracker import run
        return run.main()
    except BaseException:  # noqa: BLE001
        p = FBT / "cat_tracker" / "logs" / "autostart_error.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
