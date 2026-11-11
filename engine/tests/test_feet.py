"""Foot trackers: the distance is from the nearest of the headset and the assigned feet, and waving assigns them.
Run from engine/: python tests/test_feet.py (no SteamVR needed)."""
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cat_tracker import feet  # noqa: E402


def test_closest_and_reload():
    cat = [1.0, 0.2, 0.0]
    assert feet.closest(cat, {}) == (None, None)
    d, frm = feet.closest(cat, {"head": [3.0, 1.7, 0.0], "left foot": [1.5, 0.1, 0.0]})
    assert frm == "left foot" and abs(d - 0.5) < 1e-9, (d, frm)
    d, frm = feet.closest(cat, {"head": [1.2, 1.7, 0.0], "left foot": [1.5, 0.1, 0.0]})
    assert frm == "head", "the headset still counts: feet can only make it nearer"

    path = Path(tempfile.mkdtemp()) / "feet.json"
    f = feet.Feet(path, recheck_s=0.0)

    class FakeVR:
        def find_serials(self, serials):
            return {side: {"LHR-L": 3, "LHR-R": 4}[s] for side, s in serials.items()}

        def device_positions(self, indices):
            return {i: [0.0, 0.1, float(i)] for i in indices if i != 4}  # the right foot isn't tracking

    assert f.positions(FakeVR(), now=1.0) == {}, "nothing assigned: headset only"
    feet.save({"left": "LHR-L", "right": "LHR-R"}, path)
    got = f.positions(FakeVR(), now=2.0)
    assert list(got) == ["left foot"] and f.tracked == ["left"], got
    feet.save({}, path)
    time.sleep(0.01)
    path.touch()
    assert f.positions(FakeVR(), now=3.0) == {}, "forgotten: back to the headset"


def test_wave_assigns_left_then_right():
    from PySide6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])  # noqa: F841
    from cat_app import feet_pick

    class Pose:
        def __init__(self, p):
            self.bPoseIsValid, self.eTrackingResult = True, 1
            self.mDeviceToAbsoluteTracking = types.SimpleNamespace(m=[[1, 0, 0, p[0]], [0, 1, 0, p[1]], [0, 0, 1, p[2]]])

    ovr = types.SimpleNamespace(k_unMaxTrackedDeviceCount=6, TrackedDeviceClass_GenericTracker=3,
                                Prop_SerialNumber_String=1, TrackingUniverseRawAndUncalibrated=2, TrackingResult_Running_OK=1)
    moving = {"dev": None}
    t = [0.0]

    class Sys:
        def isTrackedDeviceConnected(self, i):
            return i in (0, 2, 3, 4)

        def getTrackedDeviceClass(self, i):
            return {0: 1, 2: 2, 3: 3, 4: 3}[i]  # headset, controller, two trackers

        def getStringTrackedDeviceProperty(self, i, prop):
            return {0: "HMD", 2: "CTRL", 3: "LHR-L", 4: "LHR-R"}[i]

        def getDeviceToAbsoluteTrackingPose(self, *a):
            t[0] += 0.05
            import math
            return [Pose([0.4 * math.sin(t[0] * 12) if i == moving["dev"] or i == 2 else 0.0, 0, 0]) for i in range(6)]

    saved = {}
    pick = feet_pick.FeetPick(lambda: (ovr, Sys()), save=lambda d: saved.update(d) or saved, load=lambda: dict(saved))
    clock = [100.0]
    feet_pick.time.monotonic = lambda: clock[0]
    pick.start()
    assert pick.state == "settle", pick.text
    clock[0] += feet_pick.SETTLE_S + 0.1
    pick.tick()
    assert pick.state == "left", pick.state
    moving["dev"] = 3  # the controller (2) waving too doesn't count: only trackers do
    for _ in range(60):
        clock[0] += 0.033
        pick.tick()
        if pick.state != "left":
            break
    assert pick.state == "right" and pick.found == {"left": "LHR-L"}, (pick.state, pick.found)
    moving["dev"] = 4
    for _ in range(60):
        clock[0] += 0.033
        pick.tick()
        if pick.state != "right":
            break
    assert pick.state == "done" and saved == {"left": "LHR-L", "right": "LHR-R"}, (pick.state, saved)

    # nothing moves: it asks again, then gives up without saving anything new
    saved.clear()
    moving["dev"] = None
    pick.start()
    clock[0] += feet_pick.SETTLE_S + 0.1
    pick.tick()
    for _ in range(2000):
        clock[0] += 0.05
        pick.tick()
        if pick.state not in ("left",):
            break
    assert pick.state == "failed" and not saved, (pick.state, saved)
    pick.timer.stop()


def main():
    test_closest_and_reload()
    test_wave_assigns_left_then_right()
    print("ok: feet")


if __name__ == "__main__":
    main()
