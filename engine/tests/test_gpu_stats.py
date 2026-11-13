"""The graphics card line in the tracker log, read from a stand-in for NVIDIA's NVML library.
Run from engine/: python tests/test_gpu_stats.py (no graphics card needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cat_tracker import gpu_stats  # noqa: E402


class FakeNvml:
    def nvmlDeviceGetMemoryInfo(self, h, ref):
        ref._obj.total, ref._obj.used = 16 * 2**30, int(13.9 * 2**30)
        return 0

    def nvmlDeviceGetUtilizationRates(self, h, ref):
        ref._obj.gpu = 97
        return 0

    def nvmlDeviceGetTemperature(self, h, which, ref):
        ref._obj.value = 71
        return 0

    def nvmlDeviceGetClockInfo(self, h, which, ref):
        return 3  # not supported: left out

    def nvmlDeviceGetCurrentClocksEventReasons(self, h, ref):
        ref._obj.value = 0x1 | 0x4  # idle (not named) + power limit
        return 0


def main():
    g = gpu_stats.GpuStats()
    g.lib = FakeNvml()
    s = g.read()
    line = gpu_stats.describe(s)
    assert line == "13.9 of 16.0 GB memory used, 97% busy, 71 C, held back by: power limit", line
    g.lib = None
    assert g.read() is None and gpu_stats.describe(None) == ""
    print("ok: gpu stats")


if __name__ == "__main__":
    main()
