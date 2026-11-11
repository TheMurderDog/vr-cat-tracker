"""After the PC went down with the app open, the next start notices (and suggests picture mode); a normal
close doesn't, and the picture mode setting switches the SteamVR tab straight away.
Run from engine/: python tests/test_crash_check.py (no SteamVR needed)."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from cat_app import crash_check  # noqa: E402


def test_crash_check():
    d = Path(tempfile.mkdtemp())
    f = d / "app" / "running.json"
    assert crash_check.start(f, now_boot=1000.0) is False, "first start ever"
    assert json.loads(f.read_text())["boot"] == 1000.0
    crash_check.finish(f)
    assert not f.exists()
    assert crash_check.start(f, now_boot=1000.0) is False, "after a normal close"
    assert crash_check.start(f, now_boot=1030.0) is False, "same start-up of the PC (app closed without tidying up)"
    assert crash_check.start(f, now_boot=5000.0) is True, "the PC started up again while the app was open"
    assert crash_check.start(f, now_boot=5000.0) is False, "only once"
    f.write_text("not json")
    assert crash_check.start(f, now_boot=9000.0) is False, "a broken file is ignored"
    f.write_text(json.dumps({"boot": None}))
    assert crash_check.start(f, now_boot=9000.0) is False
    assert crash_check.boot_time() is None or crash_check.boot_time() > 0


class FakeBackend(QObject):
    settingsChanged = Signal()

    def __init__(self):
        super().__init__()
        self.settings = {"vr_mode": "d3d11", "wrist": {"on": False}}


def test_mode_switch():
    import cat_app.vr_dashboard as vd
    b = FakeBackend()
    logs = []
    dash = vd.VrDashboard(None, None, "icon.png", logs.append, mode="d3d11", backend=b)
    dash.connect_timer.stop()
    assert dash.mode == "d3d11"
    b.settings["vr_mode"] = "file"
    b.settingsChanged.emit()
    assert dash.mode == "file", "picture mode switches straight away"
    dash.mode = "d3d11"  # (as if started with --vr-mode d3d11)
    b.settingsChanged.emit()  # another setting changed: the mode stays
    assert dash.mode == "d3d11"
    b.settings["vr_mode"] = "d3d11"
    b.settingsChanged.emit()
    dash.mode = "file"  # the GPU texture failed and it fell back to picture files
    b.settingsChanged.emit()
    assert dash.mode == "file", "a fallback isn't undone by an unrelated settings change"


def main():
    app = QGuiApplication.instance() or QGuiApplication(["test", "-platform", "offscreen"])  # noqa: F841
    test_crash_check()
    test_mode_switch()
    print("crash check ok")


if __name__ == "__main__":
    main()
