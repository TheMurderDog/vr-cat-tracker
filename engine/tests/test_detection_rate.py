"""How fast the tracker goes from the idle rate back to the full rate, before (the old rule in run.py) and now
(cat_tracker/rate.py), in a simulation: the real position filter (CatTrack) and speed (Motion) with
settings/cat_tracker.yaml, made-up positions with 2 cm of jitter, the tracker's loop at 30 a second, and the
motion tripwire stood in for by "the cat moved more than 3 cm since the last look" (about what wakes it in tests,
docs/technical/camera_checks.md). These are simulated numbers, not a measurement on a real cat or PC.
Run from engine/: python tests/test_detection_rate.py"""
import math
import sys
from pathlib import Path

import numpy as np
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cat_tracker.alert import Motion  # noqa: E402
from cat_tracker.locate import CatTrack  # noqa: E402
from cat_tracker.rate import DetectionRate  # noqa: E402

CFG = yaml.safe_load((Path(__file__).resolve().parents[2] / "settings" / "cat_tracker.yaml").read_text())
DC, OC, FC = CFG["detector"], CFG["overlay"], CFG["filter"]
LOOP = 1 / 30


def old_period(state, speed, close, last_dist):
    """The rule before rate.py (run.py up to Nov 10)."""
    busy = state == "seen" and (speed > float(OC.get("still_speed", 0.1)) or close or
                                (last_dist is not None and last_dist < float(DC.get("full_rate_within_m", 3.0))))
    return 1 / float(DC.get("rate_hz", 8)) if busy else 1 / float(DC.get("idle_rate_hz", 3))


def simulate(path, seen, secs, new, start=10.0, you=(0.0, 0.0), seed=1, tripwire=True):
    """path(t) -> (x, z) of the cat; seen(t) -> the cameras find it. Returns [(t, period)] after each look."""
    rng = np.random.default_rng(seed)
    track, motion, rate = CatTrack(FC), Motion(OC), DetectionRate(DC, OC)
    fast, idle = 1 / float(DC.get("rate_hz", 8)), 1 / float(DC.get("idle_rate_hz", 3))
    period, last_det, last_true, t, out = idle, -1e9, None, 0.0, []
    while t < secs:
        t += LOOP
        x, z = path(t)
        fresh = t - last_det >= period
        if tripwire and not fresh and period == idle and track.state in ("seen", "lost") and last_true is not None \
                and seen(t) and math.hypot(x - last_true[0], z - last_true[1]) > 0.03:
            fresh = True  # the tripwire
            if new:
                rate.woke(t)
        if not fresh:
            continue
        last_det, last_true = min(t, max(last_det + period, t - period)), (x, z)
        X = np.array([x, 0.15, z]) + rng.normal(0, 0.02, 3) if seen(t) else None
        pos, state, _ = track.update(X, t)
        motion.update(pos if state == "seen" else None, t) if state != "lost" else None
        dist = math.hypot(pos[0] - you[0], pos[2] - you[1]) if pos is not None else None
        close = dist is not None and dist < 1.0
        if new:
            period = rate.update(t, state, pos, motion.speed, dist, close, X is not None,
                                 seen_once=track.streak > 0, jumped=track.jumped, raw=X)
        else:
            period = old_period(state, motion.speed, close, dist)
        out.append((t, period))
    return out


def first_full(log, after):
    fast = 1 / float(DC.get("rate_hz", 8))
    for t, p in log:
        if t >= after and p == fast:
            return t - after
    return None


def idle_share(log, a, b):
    idle = 1 / float(DC.get("idle_rate_hz", 3))
    looks = [p for t, p in log if a <= t < b]
    return sum(p == idle for p in looks) / max(len(looks), 1), len(looks) / (b - a)


def report(name, path, seen, start, speed, expect_max_s, you=(0.0, 0.0), tripwire=True):
    worst = {}
    for new in (False, True):
        lag = []
        for seed in range(20):
            lag.append(first_full(simulate(path, seen, start + 6, new, start, you, seed, tripwire), start))
        lag = [9.9 if v is None else v for v in lag]
        worst[new] = max(lag)
    print(f"{name}: full rate after  before {worst[False]:.2f} s ({worst[False] * speed:.2f} m)"
          f"  now {worst[True]:.2f} s ({worst[True] * speed:.2f} m)  [worst of 20 runs]")
    assert worst[True] <= expect_max_s, (name, worst)
    return worst


def main():
    T0 = 10.0
    still = (5.0, 0.0)

    # 1. asleep 5 m away, then walks off slowly (0.3 m/s)
    def walk(t, v=0.3):
        return (still[0] + max(0.0, t - T0) * v, still[1])
    report("asleep far, starts walking 0.3 m/s", walk, lambda t: True, T0, 0.3, 0.5)

    # 2. asleep far, then bolts at 3 m/s
    report("asleep far, bolts 3 m/s", lambda t: walk(t, 3.0), lambda t: True, T0, 3.0, 0.2)

    # 3. the same slow start when the tripwire doesn't notice it (a dark cat on a dark couch, say)
    report("asleep far, starts walking 0.3 m/s, no tripwire", walk, lambda t: True, T0, 0.3, 0.75, tripwire=False)

    # 4. a slow stalk (0.12 m/s)
    report("asleep far, creeps off 0.12 m/s", lambda t: walk(t, 0.12), lambda t: True, T0, 0.12, 0.6)

    # 5. asleep 2 m from you, then the cameras lose it for 3 s (you're in the way); after lost_after_s it is "last seen"
    for new in (False, True):
        log = simulate(lambda t: (2.0, 0.0), lambda t: not (T0 <= t < T0 + 3), T0 + 4, new)
        share, per_s = idle_share(log, T0 + float(FC.get("lost_after_s", 1.0)) + 0.1, T0 + 3)
        print(f"2 m from you, 'last seen' behind you: {'now' if new else 'before'} "
              f"{per_s:.1f} looks a second while it's hidden")
        if new:
            assert share == 0.0, share

    # 6. still and far: the idle rate should still save the GPU (the point of it)
    log = simulate(lambda t: still, lambda t: True, 60, True)
    share, per_s = idle_share(log, 10, 60)
    print(f"asleep far for a minute: now idle rate {share * 100:.0f}% of looks, {per_s:.1f} looks a second")
    assert share > 0.9, share
    print("ok")


if __name__ == "__main__":
    main()
