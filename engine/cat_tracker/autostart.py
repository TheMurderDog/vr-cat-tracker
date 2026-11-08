"""What SteamVR runs when it starts (registered by install_autostart.bat): the tracker with no window.

SteamVR starts it from its own folder with the top folder's .venv pythonw.exe, so this moves into engine/
first, then runs cat_tracker.run with the arguments saved in the manifest (--reuse-anchor --headless and
whatever was given to install_autostart.bat). The tracker closes when SteamVR does. With no window,
anything that goes wrong before the log starts is written to my_data/logs/cat_tracker/autostart_error.txt.
When the Cat Tracker app is installed, it goes through cat_app.launch: the tracker runs through cat_app.bridge
and the app starts too (its SteamVR tab). --no-app in the manifest's arguments leaves the app out.
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
        args = [a for a in args if a != "--via-app"]  # (older manifests; the app is now found by itself)
        from cat_app import launch
        return launch.main(["--background"] + (["--no-app"] if "--no-app" in args else []) + ["--"]
                           + [a for a in args if a != "--no-app"])
    except BaseException:  # noqa: BLE001
        p = ENGINE.parent / "my_data" / "logs" / "cat_tracker" / "autostart_error.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
