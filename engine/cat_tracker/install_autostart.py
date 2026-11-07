"""Register the cat tracker with SteamVR so it starts (with no window) whenever SteamVR does.

  python -m cat_tracker.install_autostart            register; extra arguments go to the tracker, e.g. --osc
  python -m cat_tracker.install_autostart --remove   stop it starting with SteamVR
SteamVR must be running. It needs a saved anchor (run 5_play_in_vr/run_tracker.bat once and do the walk-around), since
there is no window to anchor in. It shows up in SteamVR's Settings > Startup / Shutdown > Choose
startup overlay apps, where it can be switched off too.
"""

import json
import sys
from pathlib import Path

import openvr

from cat_tracker import settings
from cat_tracker.anchor import _path as anchor_path

HERE = Path(__file__).resolve().parent
APP_KEY = "camera_core.cat_tracker"
MANIFEST = HERE / "cat_tracker.vrmanifest"


def main():
    args = sys.argv[1:]
    remove = "--remove" in args
    args = [a for a in args if a != "--remove"]
    try:
        openvr.init(openvr.VRApplication_Utility)
    except openvr.OpenVRError as e:
        print(f"SteamVR isn't running ({e}). Start it and try again.")
        return 1
    try:
        apps = openvr.VRApplications()
        if remove:
            if apps.isApplicationInstalled(APP_KEY):
                apps.setApplicationAutoLaunch(APP_KEY, False)
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
            "arguments": " ".join([f'"{HERE / "autostart.py"}"'] + tracker_args),
            "is_dashboard_overlay": True,
            "action_manifest_path": str(HERE / "input" / "actions.json"),
            "strings": {"en_us": {"name": "Cat tracker",
                                  "description": "Shows where the cat is, from the room cameras"}},
        }
        MANIFEST.write_text(json.dumps({"source": "builtin", "applications": [app]}, indent=2), encoding="utf-8")
        if apps.isApplicationInstalled(APP_KEY):
            apps.removeApplicationManifest(str(MANIFEST))
        apps.addApplicationManifest(str(MANIFEST))
        apps.setApplicationAutoLaunch(APP_KEY, True)
        print(f"Registered. The cat tracker now starts with SteamVR ({' '.join(tracker_args)}).")
        print("Logs are in my_data\\logs\\cat_tracker. To undo: 5_play_in_vr\\start_with_steamvr\\remove_autostart.bat")
        return 0
    finally:
        openvr.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
