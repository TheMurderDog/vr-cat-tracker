"""Register the cat tracker with SteamVR so it starts (with no window) whenever SteamVR does.

  python -m cat_tracker.install_autostart            register; extra arguments go to the tracker, e.g. --osc
  python -m cat_tracker.install_autostart --no-app   without the Cat Tracker app, even if it's installed
  python -m cat_tracker.install_autostart --remove   stop it (and the app) starting with SteamVR
SteamVR must be running. It needs a saved anchor (run 5_play_in_vr/run_tracker.bat once and do the walk-around), since
there is no window to anchor in. It shows up in SteamVR's Settings > Startup / Shutdown > Choose
startup overlay apps, where it can be switched off too.

With the Cat Tracker app installed (5_play_in_vr/app/1_install_app.bat), the tracker runs through cat_app.bridge so the
app can see it, and the app starts too, with no window: its tab in the SteamVR dashboard. Both close with SteamVR.
(If the app is installed later, the tracker finds it by itself next time: see cat_app.launch.)
"""

import importlib.util
import json
import sys
from pathlib import Path

import openvr

from cat_tracker import settings
from cat_tracker.anchor import _path as anchor_path

HERE = Path(__file__).resolve().parent
APP_KEY = "camera_core.cat_tracker"
UI_KEY = "camera_core.cat_tracker_app"  # the Cat Tracker app (cat_app), when it's installed
MANIFEST = HERE / "cat_tracker.vrmanifest"


def app_installed():
    return importlib.util.find_spec("PySide6") is not None and (HERE.parent / "cat_app" / "main.py").is_file()


def main():
    args = sys.argv[1:]
    remove = "--remove" in args
    no_app = "--no-app" in args
    with_app = not no_app and app_installed()
    args = [a for a in args if a not in ("--remove", "--no-app")]
    try:
        openvr.init(openvr.VRApplication_Utility)
    except openvr.OpenVRError as e:
        print(f"SteamVR isn't running ({e}). Start it and try again.")
        return 1
    try:
        apps = openvr.VRApplications()
        if remove:
            for key in (APP_KEY, UI_KEY):
                if apps.isApplicationInstalled(key):
                    apps.setApplicationAutoLaunch(key, False)
            if apps.isApplicationInstalled(APP_KEY) or apps.isApplicationInstalled(UI_KEY):
                apps.removeApplicationManifest(str(MANIFEST))
            print("The cat tracker won't start with SteamVR any more.")
            return 0
        if not anchor_path(settings.load()).is_file():
            print("No saved anchor yet: run 5_play_in_vr\\run_tracker.bat once and do the walk-around first.")
            return 1
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        tracker_args = ["--reuse-anchor", "--headless"] + [a for a in args if a not in ("--reuse-anchor", "--headless")]
        app = {
            "app_key": APP_KEY,
            "launch_type": "binary",
            "binary_path_windows": str(pythonw),
            "arguments": " ".join([f'"{HERE / "autostart.py"}"'] + (["--no-app"] if no_app else []) + tracker_args),
            "is_dashboard_overlay": True,
            "action_manifest_path": str(HERE / "input" / "actions.json"),
            "strings": {"en_us": {"name": "Cat tracker",
                                  "description": "Shows where the cameras think the cat is"}},
        }
        entries = [app]
        if with_app:
            ui = HERE.parent / "cat_app"
            entries.append({
                "app_key": UI_KEY,
                "launch_type": "binary",
                "binary_path_windows": str(pythonw),
                "arguments": f'"{ui / "autostart.py"}"',
                "is_dashboard_overlay": True,
                "action_manifest_path": str(ui / "input" / "actions.json"),
                "strings": {"en_us": {"name": "Cat Tracker app",
                                      "description": "The cat tracker's tab in the dashboard, and its wrist widget"}},
            })
        MANIFEST.write_text(json.dumps({"source": "builtin", "applications": entries}, indent=2), encoding="utf-8")
        if apps.isApplicationInstalled(APP_KEY) or apps.isApplicationInstalled(UI_KEY):
            apps.removeApplicationManifest(str(MANIFEST))
        apps.addApplicationManifest(str(MANIFEST))
        apps.setApplicationAutoLaunch(APP_KEY, True)
        if with_app:
            apps.setApplicationAutoLaunch(UI_KEY, True)
        print(f"Registered. The cat tracker now starts with SteamVR ({' '.join(tracker_args)}).")
        if with_app:
            print("The Cat Tracker app starts with it: open the SteamVR dashboard and pick the cat tab.")
        print("Logs are in my_data\\logs\\cat_tracker. To undo: 5_play_in_vr\\start_with_steamvr\\remove_autostart.bat")
        return 0
    finally:
        openvr.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
