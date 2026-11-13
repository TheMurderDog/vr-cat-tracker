"""Graphics card memory, load, temperature and clock limits, for the tracker log. When cat detection slows
down, these show whether another program is filling the card's memory or keeping it busy.

Reads NVIDIA's NVML library, which comes with the graphics driver (nvml.dll on Windows), through ctypes:
nothing to install. Without it (another make of card, or no driver), read() returns None and nothing is logged.
"""

import ctypes
import os
import sys

# clock limit reasons (nvmlClocksEventReasons), the ones worth naming
LIMITS = {0x4: "power limit", 0x8: "hardware slowdown", 0x20: "too hot (driver)", 0x40: "too hot (hardware)",
          0x80: "power brake"}


class _Memory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class _Util(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


def _load():
    names = ["libnvidia-ml.so.1"]
    if sys.platform == "win32":
        root = os.environ.get("SystemRoot", r"C:\Windows")
        names = [os.path.join(root, "System32", "nvml.dll"),
                 os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "NVIDIA Corporation", "NVSMI", "nvml.dll")]
    for n in names:
        try:
            return ctypes.CDLL(n)
        except OSError:
            continue
    return None


class GpuStats:
    def __init__(self, index=0):
        self.lib = None
        self.handle = ctypes.c_void_p()
        lib = _load()
        if lib is None:
            return
        try:
            if lib.nvmlInit_v2() != 0 or lib.nvmlDeviceGetHandleByIndex_v2(int(index), ctypes.byref(self.handle)) != 0:
                return
        except Exception:  # noqa: BLE001 - only for the log, so it must not stop the tracker
            return
        self.lib = lib

    def read(self):
        """{"used_gb", "total_gb", "busy", "temp_c", "mhz", "limits"} or None. Each value can be None alone."""
        if self.lib is None:
            return None
        lib, h = self.lib, self.handle
        out = {"used_gb": None, "total_gb": None, "busy": None, "temp_c": None, "mhz": None, "limits": []}
        try:
            m = _Memory()
            if lib.nvmlDeviceGetMemoryInfo(h, ctypes.byref(m)) == 0:
                out["used_gb"], out["total_gb"] = m.used / 2**30, m.total / 2**30
            u = _Util()
            if lib.nvmlDeviceGetUtilizationRates(h, ctypes.byref(u)) == 0:
                out["busy"] = int(u.gpu)
            t = ctypes.c_uint()
            if lib.nvmlDeviceGetTemperature(h, 0, ctypes.byref(t)) == 0:  # 0: the GPU itself
                out["temp_c"] = int(t.value)
            c = ctypes.c_uint()
            if lib.nvmlDeviceGetClockInfo(h, 0, ctypes.byref(c)) == 0:  # 0: graphics clock
                out["mhz"] = int(c.value)
            r = ctypes.c_ulonglong()
            fn = getattr(lib, "nvmlDeviceGetCurrentClocksEventReasons", None) or \
                getattr(lib, "nvmlDeviceGetCurrentClocksThrottleReasons", None)
            if fn is not None and fn(h, ctypes.byref(r)) == 0:
                out["limits"] = [name for bit, name in LIMITS.items() if r.value & bit]
        except Exception:  # noqa: BLE001 - only for the log, so it must not stop the tracker
            return None
        return out


def describe(s):
    """One line for the log, e.g. "13.9 of 16.0 GB memory used, 97% busy, 71 C, 2610 MHz"."""
    if not s:
        return ""
    parts = []
    if s["used_gb"] is not None:
        parts.append(f"{s['used_gb']:.1f} of {s['total_gb']:.1f} GB memory used")
    if s["busy"] is not None:
        parts.append(f"{s['busy']}% busy")
    if s["temp_c"] is not None:
        parts.append(f"{s['temp_c']} C")
    if s["mhz"] is not None:
        parts.append(f"{s['mhz']} MHz")
    if s["limits"]:
        parts.append("held back by: " + ", ".join(s["limits"]))
    return ", ".join(parts)
