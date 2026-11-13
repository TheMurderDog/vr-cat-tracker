"""The cat near a foot tracker while the headset is off or asleep (no headset pose) must not stop the tracker.

Nov 12: run.py worked out the edge arrow's direction from the headset pose even when there was none, and the
tracker stopped with a ValueError. head_direction() gives None then, and run.py hides the arrow instead.
Simulated poses only: no SteamVR needed.
"""

import sys
import types
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("openvr", types.SimpleNamespace(TrackingUniverseRawAndUncalibrated=2,
                                                       TrackingUniverseStanding=1))

from cat_tracker.vrlink import head_direction  # noqa: E402


def test_no_headset_pose_gives_none():
    assert head_direction(np.eye(4), None, np.array([1.0, 0.0, -1.0])) is None


def test_point_ahead_of_headset():
    hmd = np.eye(4)
    hmd[:3, 3] = [0.0, 1.6, 0.0]
    d = head_direction(np.eye(4), hmd, np.array([0.0, 1.6, -2.0]))
    assert np.allclose(d, [0.0, 0.0, -2.0])


def test_play_space_moved():
    M = np.eye(4)
    M[:3, 3] = [1.0, 0.0, 0.0]  # standing space shifted 1 m from raw
    d = head_direction(M, np.eye(4), np.array([1.0, 0.0, -1.0]))
    assert np.allclose(d, [0.0, 0.0, -1.0])


def test_run_uses_it():
    src = (Path(__file__).resolve().parents[1] / "cat_tracker" / "run.py").read_text(encoding="utf-8")
    assert "np.linalg.inv(M @ hmd)" not in src
    assert "head_direction(M, hmd, p)" in src


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok: the arrow is skipped, not the tracker, while the headset has no pose")
