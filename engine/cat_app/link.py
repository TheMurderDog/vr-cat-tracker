"""How the app and the tracker talk: a few named blocks of shared memory, no network and no listening ports.

The tracker side (cat_app.bridge) makes the blocks and writes its status, the newest camera picture and the
room heatmap into them. The app reads them, and writes into one more block what it wants (camera pictures,
the heatmap) and the buttons pressed (re-anchor, capture, ...). Either side can start or stop at any time:
the app just sees "the tracker isn't running" while there are no blocks, or while the status stops changing.

Each block: an 8-byte counter, a 4-byte length, then the bytes. The writer makes the counter odd while it
writes and even when done, so a reader never uses half-written bytes. Needs only the standard library.
"""

import json
import os
import struct
import time
from multiprocessing import shared_memory

STATUS = "vr_cat_tracker_status"     # the tracker's status, JSON (bridge writes)
FRAME = "vr_cat_tracker_frame"       # the tracker window's picture, JPEG (bridge writes, only while asked for)
HEAT = "vr_cat_tracker_heat"         # the room heatmap, JSON (bridge writes, only while asked for)
ASK = "vr_cat_tracker_ask"           # what the app wants and the buttons pressed, JSON (the app writes)
SIZES = {STATUS: 1 << 16, FRAME: 6 << 20, HEAT: 1 << 19, ASK: 1 << 14}  # the tracker side makes these
APP = "vr_cat_tracker_app"           # held by the running app; a second copy asks it to show its window
SIZES_APP = {APP: 1 << 12}
_HEAD = struct.Struct("<QI")


def _forget(shm):
    """Python on Linux/macOS would remove a block it only opened when it exits; only its maker removes it.
    (Windows frees a block by itself when the last program using it closes it.)"""
    if os.name != "nt":
        try:
            from multiprocessing import resource_tracker
            resource_tracker.unregister(shm._name, "shared_memory")  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass


def _adopt(shm):
    """A block taken over from an ended tracker: this side removes it when done (Linux/macOS only)."""
    if os.name != "nt":
        try:
            from multiprocessing import resource_tracker
            resource_tracker.register(shm._name, "shared_memory")  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass


class Block:
    def __init__(self, name, create=False):
        self.name = name
        if create:
            self.shm = shared_memory.SharedMemory(name=name, create=True, size={**SIZES, **SIZES_APP}[name])
            self.shm.buf[:_HEAD.size] = _HEAD.pack(0, 0)
        else:
            self.shm = shared_memory.SharedMemory(name=name)
            _forget(self.shm)
        self.owner = create
        self.seq = 0
        self.last_read = -1

    def write(self, data: bytes):
        buf = self.shm.buf
        n = len(data)
        if _HEAD.size + n > len(buf):
            return False
        seq = _HEAD.unpack_from(buf, 0)[0]
        seq = seq + 1 if seq % 2 == 0 else seq + 2  # odd: writing
        _HEAD.pack_into(buf, 0, seq, 0)
        buf[_HEAD.size:_HEAD.size + n] = data
        _HEAD.pack_into(buf, 0, seq + 1, n)  # even: done
        self.seq = seq + 1
        return True

    def read(self, only_new=True):
        """(counter, bytes), or (counter, None) when nothing new since the last read (only_new)."""
        buf = self.shm.buf
        for _ in range(20):
            seq, n = _HEAD.unpack_from(buf, 0)
            if seq % 2:
                time.sleep(0.0005)
                continue
            if only_new and seq == self.last_read:
                return seq, None
            data = bytes(buf[_HEAD.size:_HEAD.size + n])
            if _HEAD.unpack_from(buf, 0)[0] == seq:
                self.last_read = seq
                return seq, data
        return self.last_read, None

    def close(self):
        try:
            self.shm.close()
            if self.owner:
                self.shm.unlink()  # (does nothing on Windows; the block goes when the last handle closes)
        except Exception:  # noqa: BLE001
            pass


def make_all(stale_s=3.0):
    """The tracker side: make every block. On Windows a block lives on while the app still has it open, so
    blocks left by a tracker that has ended (status not updated for stale_s) are taken over. FileExistsError
    if another tracker for the app is running."""
    made = []
    try:
        for name in SIZES:
            try:
                made.append(Block(name, create=True))
            except FileExistsError:
                b = Block(name)
                made.append(b)
                if name == STATUS:
                    _, data = b.read(only_new=False)
                    try:
                        t = float(json.loads(data or b"{}").get("t", 0))
                    except ValueError:
                        t = 0.0
                    if time.time() - t < stale_s:
                        raise FileExistsError("another tracker for the app is running") from None
                b.owner = True  # taken over
                _adopt(b.shm)
    except BaseException:
        for b in made:
            b.close()
        raise
    return {b.name: b for b in made}


def open_block(name):
    """The app side: the block, or None while the tracker isn't running."""
    try:
        return Block(name)
    except (FileNotFoundError, OSError, ValueError):
        return None


def write_json(block, obj):
    return block.write(json.dumps(obj, separators=(",", ":")).encode())
