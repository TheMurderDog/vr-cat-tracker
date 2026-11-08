"""Small built-in meter: this process's CPU use and memory, plus named counters and timers.

Used by the app (my_data\\logs\\cat_app\\perf.log) and the bridge (bridge.log next to it) to report every so often,
so we can see what the UI costs without installing anything. Needs only the standard library.
"""

import ctypes
import os
import time


def memory_mb():
    """This process's working set (the RAM it is using right now), in MB."""
    if os.name == "nt":
        class PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.WinDLL("kernel32")
        psapi = ctypes.WinDLL("psapi")
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return pmc.WorkingSetSize / 2**20
        return 0.0
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20
    except OSError:
        return 0.0


class Meter:
    def __init__(self):
        self.t0 = time.monotonic()
        self.cpu0 = time.process_time()  # all threads of this process
        self.counts = {}
        self.times = {}
        self.cores = os.cpu_count() or 1

    def count(self, name, n=1):
        self.counts[name] = self.counts.get(name, 0) + n

    def timed(self, name, seconds):
        tot, n = self.times.get(name, (0.0, 0))
        self.times[name] = (tot + seconds, n + 1)

    def report(self, extra=""):
        """One line covering the time since the last report, then starts a new period."""
        now, cpu = time.monotonic(), time.process_time()
        dt = max(now - self.t0, 1e-6)
        pct = 100 * (cpu - self.cpu0) / dt  # 100% = one CPU core busy
        parts = [f"cpu {pct:.1f}% of one core ({pct / self.cores:.2f}% of the PC)", f"ram {memory_mb():.0f} MB"]
        if extra:
            parts.append(extra)
        for k in sorted(self.counts):
            parts.append(f"{k} {self.counts[k] / dt:.1f}/s")
        for k in sorted(self.times):
            tot, n = self.times[k]
            parts.append(f"{k} {1000 * tot / max(n, 1):.1f} ms avg")
        self.t0, self.cpu0, self.counts, self.times = now, cpu, {}, {}
        return " | ".join(parts)
