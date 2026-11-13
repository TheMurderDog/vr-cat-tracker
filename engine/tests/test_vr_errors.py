"""SteamVR errors that repeat every update are logged once with their name and traceback, then counted, not
written every second. Run from engine/: python tests/test_vr_errors.py (no SteamVR needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cat_app.vr_dashboard as vd  # noqa: E402


class OverlayError_RequestFailed(Exception):  # like pyopenvr's errors: a code, no message  # noqa: N801
    def __init__(self, error_value):
        super().__init__("")
        self.error_value = error_value


def boom():
    raise OverlayError_RequestFailed(23)


def main():
    try:
        boom()
    except Exception as e:  # noqa: BLE001
        text = vd.describe(e)
    assert text.startswith("OverlayError_RequestFailed (23), in test_vr_errors.py line"), text
    assert "(boom)" in text

    clock = [100.0]
    vd.time.monotonic = lambda: clock[0]
    lines = []
    r = vd.Repeats(lines.append, "Wrist widget problem")
    r.ok()
    assert lines == [], "nothing to say while it works"
    for _ in range(90):  # 90 failures over 45 s
        try:
            boom()
        except Exception as e:  # noqa: BLE001
            r.failed(e)
        clock[0] += 0.5
    assert len(lines) == 1 and "Traceback" in lines[0] and "OverlayError_RequestFailed" in lines[0], lines
    for _ in range(40):  # 20 s more: past a minute, one count line
        try:
            boom()
        except Exception as e:  # noqa: BLE001
            r.failed(e)
        clock[0] += 0.5
    assert len(lines) == 2 and "again" in lines[1], lines
    r.ok()
    assert lines[-1] == "Wrist widget problem: working again", lines
    r.ok()
    assert lines[-1] == "Wrist widget problem: working again" and len(lines) == 4, lines
    try:
        raise ValueError("bad picture")
    except Exception as e:  # noqa: BLE001
        r.failed(e)
    assert "ValueError: bad picture" in lines[-1].splitlines()[0], lines[-1]
    print("ok: vr errors")


if __name__ == "__main__":
    main()
