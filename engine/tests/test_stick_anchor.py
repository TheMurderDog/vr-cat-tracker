"""The stick anchor goes to head mode on a stick push or a play-space move, anchors once the head has been
steady after settle_s, ignores a brushed stick, stays anchored while walking for real, and the cat's offset
from the anchor matches its offset from the head at the anchor moment. Run from engine/:
python tests/test_stick_anchor.py (no SteamVR needed)."""
import math
import sys
import types
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("openvr", types.ModuleType("openvr"))  # osc.py doesn't need SteamVR for this
from cat_tracker.osc import head_offset  # noqa: E402
from cat_tracker.stick_anchor import StickAnchor, flat_pose, yaw_of  # noqa: E402

DT = 1 / 60


def run(sa, t, secs, head, stick=0.0, M=None):
    """Feeds secs of updates; head(t) gives the headset pose. Returns (t, last result)."""
    out = None
    for _ in range(int(round(secs / DT))):
        t += DT
        out = sa.update(t, head(t), stick, M if M is not None else np.eye(4))
    return t, out


def main():
    for yaw in (0.0, 30.0, -135.0, 179.0):
        assert abs(yaw_of(flat_pose(1.0, 2.0, yaw)) - yaw) < 1e-6, "flat_pose and yaw_of agree"
    sa = StickAnchor({"enabled": True, "refresh_s": 0})
    still = lambda t: flat_pose(0.5, -1.0, 40.0, 1.6)  # noqa: E731
    t, out = run(sa, 0.0, 0.5, still)
    assert out is None, "not yet: settle + average"
    t, out = run(sa, t, 0.5, still)
    assert out is not None, "anchored after about 0.8 s of a steady head"
    cat = np.array([1.5, 0.15, -2.0])
    a, b = head_offset(cat, out), head_offset(cat, still(t))
    assert np.allclose(a, b, atol=1e-6), "same offset from the anchor as from the head at that moment"

    t, out = run(sa, t, 0.05, still, stick=0.9)
    assert out is not None, "a brushed stick (under stick_min_s) doesn't count"
    t, out = run(sa, t, 0.2, still, stick=0.9)
    assert out is None, "a held stick drops to head mode"
    t, out = run(sa, t, 0.2, still, stick=0.1)
    assert out is None, "inside the deadzone, but settle_s hasn't passed"
    t, out = run(sa, t, 1.0, still)
    assert out is not None, "anchors again once settled and steady"

    walk = lambda t: flat_pose(0.5 + 0.8 * t, -1.0, 40.0 + 60 * math.sin(t), 1.6)  # noqa: E731
    t, out = run(sa, t, 2.0, walk)
    assert out is not None, "walking and turning for real keeps the anchor"

    M = np.eye(4)
    M[0, 3] = 0.3
    t, out = run(sa, t, DT, still, M=M)
    assert out is None, "SteamVR's play space moved: head mode"

    t, out = run(sa, t, 3.0, walk)
    assert out is None, "no anchor while the head keeps moving (no time limit)"
    t, out = run(sa, t, 1.0, still, stick=None)
    assert out is None, "can't read the sticks: stays in head mode"

    sa = StickAnchor({"enabled": True, "refresh_s": 2.0})
    t, out = run(sa, 0.0, 1.0, still)
    assert out is not None
    first = sa.anchored_at
    t, out = run(sa, t, 2.1, still)
    assert out is None, "a short drop to head mode after refresh_s while steady"
    t, out = run(sa, t, 1.0, still)
    assert out is not None and sa.anchored_at > first, "then anchored again"

    assert StickAnchor({}).update(1.0, still(1.0), 0.0) is None, "off by default"
    print("test_stick_anchor: ok")


if __name__ == "__main__":
    main()
