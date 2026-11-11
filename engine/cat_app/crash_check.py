"""Notices when the PC restarted while the app was running (a crash, a power cut, or a restart with the
app still open), so the app can suggest picture mode on its next start.

The app writes a small file when it starts and deletes it when it closes. If the file is still there at
the next start and the PC has started up since, the PC went down with the app open. The app can't tell a
crash from a restart this way, so its message says "if it crashed".
Needs only the standard library.
"""

import json
import sys
import time
from pathlib import Path

SAME_BOOT_S = 120.0  # boot times this close count as the same start-up (the clock reading wobbles a little)


def boot_time():
    """When the PC last started (seconds since 1970), or None if it can't be read."""
    try:
        if sys.platform == "win32":
            import ctypes
            k = ctypes.windll.kernel32
            k.GetTickCount64.restype = ctypes.c_ulonglong
            return time.time() - k.GetTickCount64() / 1000.0
        with open("/proc/stat", encoding="ascii") as f:
            for line in f:
                if line.startswith("btime"):
                    return float(line.split()[1])
    except (OSError, ValueError, AttributeError):
        pass
    return None


def start(path, now_boot=None):
    """Call once when the app starts. Returns True if the last run was still open when the PC went down.
    Then marks this run as open (until finish())."""
    path = Path(path)
    now_boot = boot_time() if now_boot is None else now_boot
    went_down = False
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        b = old.get("boot")
        went_down = b is not None and now_boot is not None and abs(float(b) - now_boot) > SAME_BOOT_S
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"started": time.time(), "boot": now_boot}), encoding="utf-8")
    except OSError:
        pass
    return went_down


def finish(path):
    """Call when the app closes normally."""
    try:
        Path(path).unlink()
    except OSError:
        pass
