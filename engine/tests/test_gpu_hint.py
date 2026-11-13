"""The "graphics card busy" hint: on when detection stays slow, not for one slow moment or the warm-up, off again
after a calm stretch. Run from engine/: python tests/test_gpu_hint.py (no hardware needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cat_tracker.health import Health  # noqa: E402


def feed(h, t0, seconds, ms, rate=7.0):
    t = t0
    while t < t0 + seconds:
        h.detector_time(ms, t)
        t += 1.0 / rate
    return t


def main():
    h = Health({}, ["a", "b"])
    t = feed(h, 0.0, 25, 900)  # warm-up: slow, but skipped
    assert h.hint(t) is None, "the first 30 s are skipped"
    t = feed(h, t, 60, 30)
    t = feed(h, t, 0.3, 1500, rate=7)  # one slow moment
    assert h.hint(t) is None, "one slow detection is not enough"
    t = feed(h, t, 12, 30)
    t = feed(h, t, 8, 150)  # sustained (a heavy world)
    m = h.hint(t)
    assert m and m[0] == "gpu_busy" and "graphics settings or resolution" in m[2][1], m
    t = feed(h, t, 20, 30)
    assert h.hint(t) is not None, "stays on until 30 s back at normal speed"
    t = feed(h, t, 25, 30)
    assert h.hint(t) is None, "clears after a calm stretch"
    t = feed(h, t, 3, 2500, rate=0.5)  # a full freeze: two 2.5 s detections
    assert h.hint(t) is not None, "long freezes count too"
    h2 = Health({"gpu_hint": False}, ["a"])
    feed(h2, 0, 60, 500)
    assert h2.hint(60) is None, "gpu_hint: false turns it off"
    assert h.message(t) is None, "it is not one of the red notices"
    print("ok: gpu hint")


if __name__ == "__main__":
    main()
