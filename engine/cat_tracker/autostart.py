"""What SteamVR runs when it starts (registered by install_autostart.bat): the tracker with no window.

SteamVR starts it from its own folder with the top folder's .venv pythonw.exe, so this moves into engine/
first, then runs cat_tracker.run with the arguments saved in the manifest (--reuse-anchor --headless and
whatever was given to install_autostart.bat). The tracker closes when SteamVR does. With no window,
anything that goes wrong before the log starts is written to my_data/logs/cat_tracker/autostart_error.txt.
With --via-app first (the Cat Tracker app is installed), the tracker runs through cat_app.bridge so the app can see it.
"""

import os
import sys
import traceback
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent


def main():
    os.chdir(ENGINE)
    sys.path.insert(0, str(ENGINE))
    args = sys.argv[1:]
    try:
        if args[:1] == ["--via-app"]:
            sys.argv = ["cat_app.bridge", "--"] + args[1:]
            from cat_app import bridge
            return bridge.main()
        sys.argv = ["cat_tracker.run"] + args
        from cat_tracker import run
        return run.main()
    except BaseException:  # noqa: BLE001
        p = ENGINE.parent / "my_data" / "logs" / "cat_tracker" / "autostart_error.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
