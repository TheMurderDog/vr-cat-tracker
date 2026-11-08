"""The app-tracker link (cat_app.link): blocks round-trip, a reader skips unchanged data, a second tracker is refused
while the first is running, and blocks left by an ended tracker are taken over. Run from engine/:
python tests/test_app_link.py (standard library only)."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cat_app import link  # noqa: E402


def main():
    blocks = link.make_all()
    try:
        status = blocks[link.STATUS]
        link.write_json(status, {"t": time.time(), "cat": {"state": "seen"}})
        app = link.open_block(link.STATUS)
        assert app is not None
        _, data = app.read()
        assert json.loads(data)["cat"]["state"] == "seen"
        assert app.read()[1] is None, "nothing new: no data"
        try:
            link.make_all()
            raise AssertionError("a second tracker was not refused")
        except FileExistsError:
            pass
        ask = link.open_block(link.ASK)
        link.write_json(ask, {"cmds": [[1, "buzz"]]})
        assert json.loads(blocks[link.ASK].read()[1])["cmds"] == [[1, "buzz"]]
        assert not status.write(b"x" * (1 << 17)), "too big for the block"
        # an ended tracker: status older than 3 s, so the next one takes the blocks over
        link.write_json(status, {"t": time.time() - 10})
        again = link.make_all()
        for b in again.values():
            b.close()
        app.close()
        ask.close()
    finally:
        for b in blocks.values():
            b.close()
    assert link.open_block(link.STATUS) is None, "blocks removed when the tracker side closes"
    print("ok: app-tracker link")


if __name__ == "__main__":
    main()
