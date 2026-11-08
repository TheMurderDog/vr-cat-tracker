"""What SteamVR runs for the Cat Tracker app when it starts (registered by cat_tracker.install_autostart when the app
is installed): the app with no window, only its tab in the SteamVR dashboard. It closes when SteamVR does.

SteamVR starts it from its own folder with the top folder's .venv pythonw.exe, so this moves into engine/ first.
Anything that goes wrong before the app's log starts is written to my_data/logs/cat_app/autostart_error.txt.
"""

import os
import sys
import traceback
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent


def main():
    os.chdir(ENGINE)
    sys.path.insert(0, str(ENGINE))
    sys.argv = ["cat_app.main", "--background"] + sys.argv[1:]
    try:
        from cat_app import main as app_main
        return app_main.main()
    except BaseException:  # noqa: BLE001
        p = ENGINE.parent / "my_data" / "logs" / "cat_app" / "autostart_error.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
