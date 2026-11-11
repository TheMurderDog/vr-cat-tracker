"""CatUp: the height sent to the avatar, from the cat's middle (no SteamVR, no network: sends are captured)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cat_tracker.osc import OscCat  # noqa: E402


def sent_up(o, *a, **k):
    out = []
    o._send = lambda n, v: out.append((n, v))
    o.send(*a, **k)
    return [v for n, v in out if n == "CatUp"]


def main():
    o = OscCat({"range_m": 4.0}, {"floor_y_m": 0.0, "body_height_m": 0.15})
    assert o.height(0.15) == 0.0  # standing on the floor
    assert o.height(0.08) == 0.0  # lying down: below the floor counts as the floor
    assert o.height(0.22) == 0.0  # triangulation wobble near the floor snaps to it
    assert abs(o.height(0.60) - 0.45) < 1e-9  # on a sofa seat
    assert sent_up(o, (1.0, 0.0), True, up=0.45) == [0.1125]  # metres / range_m
    assert sent_up(o, None, False) == [0.1125]  # hidden: the last height is repeated
    assert sent_up(o, (1.0, 0.0), True, up=9.0) == [1.0]  # clamped to 0..1
    o = OscCat({"range_m": 4.0, "send_height": False})
    assert sent_up(o, (1.0, 0.0), True, up=0.5) == []  # turned off: not sent
    o = OscCat({}, {"floor_y_m": 0.1})
    assert abs(o.height(0.65) - 0.4) < 1e-9  # measured from the floor setting
    print("test_osc_height: ok")


if __name__ == "__main__":
    main()
