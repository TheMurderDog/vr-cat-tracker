"""The watchdog doesn't call the tracker frozen because one heartbeat read failed (the file being replaced),
but still does once the last good heartbeat is older than hang_s. Run from engine/:
python tests/test_watchdog_blip.py (no SteamVR needed)."""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("openvr", types.ModuleType("openvr"))  # the watchdog's SteamVR side isn't used here
from cat_tracker.watchdog import steady, verdict  # noqa: E402


def main():
    good = {"pid": 7, "t": 100.0, "state": "running"}
    hb = steady(good, None)
    assert verdict(hb, 7, True, 15, 100.5) == "ok"
    hb = steady(None, hb)  # a read failed while the file was replaced
    assert verdict(hb, 7, True, 15, 101.0) == "ok", "one failed read is not a freeze"
    assert verdict(hb, 7, True, 15, 116.0) == "frozen", "a real freeze still shows after hang_s"
    assert verdict(steady(None, None), 7, True, 15, 101.0) == "frozen", "no heartbeat at all: as before"
    assert verdict(hb, 7, False, 15, 101.0) == "stopped", "the process gone: as before"
    print("ok: watchdog ignores a single failed heartbeat read")


if __name__ == "__main__":
    main()
