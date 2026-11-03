"""Read tracker poses from SteamVR on a background thread, stamped with the same clock as camera frames.

SteamVR must already be running (started the user's own way); this only attaches to it.
"""

import bisect
import threading
import time

import numpy as np
import openvr

CLASS_NAMES = {
    openvr.TrackedDeviceClass_HMD: "headset",
    openvr.TrackedDeviceClass_Controller: "controller",
    openvr.TrackedDeviceClass_GenericTracker: "tracker",
    openvr.TrackedDeviceClass_TrackingReference: "base station",
}


def _prop(vr, i, prop):
    try:
        return vr.getStringTrackedDeviceProperty(i, prop)
    except openvr.OpenVRError:
        return ""


class VRPoller:
    """Polls one device's pose at a fixed rate. Samples are (t_ns, 4x4 pose in metres, valid)."""

    def __init__(self, universe="standing", rate_hz=250):
        self.vr = openvr.init(openvr.VRApplication_Background)  # attaches only, never launches SteamVR
        self.universe = openvr.TrackingUniverseSeated if universe == "seated" else openvr.TrackingUniverseStanding
        self.period = 1.0 / rate_hz
        self.keep = int(rate_hz * 5)  # seconds of pose history kept for lookups
        self.index = None
        self.t = []
        self.poses = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def devices(self):
        out = []
        for i in range(openvr.k_unMaxTrackedDeviceCount):
            if self.vr.isTrackedDeviceConnected(i):
                out.append((i, CLASS_NAMES.get(self.vr.getTrackedDeviceClass(i), "other"),
                            _prop(self.vr, i, openvr.Prop_SerialNumber_String)))
        return out

    def pick(self, serial=None, kind="tracker"):
        for i, k, s in self.devices():
            if (serial and s == serial) or (not serial and k == kind):
                self.index = i
                return i, k, s
        raise RuntimeError(f"no {serial or kind} found in SteamVR (is it switched on and tracking?)")

    def pose_now(self):
        poses = self.vr.getDeviceToAbsoluteTrackingPose(self.universe, 0, openvr.k_unMaxTrackedDeviceCount)
        p = poses[self.index]
        m = np.eye(4)
        m[:3, :4] = np.ctypeslib.as_array(p.mDeviceToAbsoluteTracking.m)
        return m, bool(p.bPoseIsValid) and p.eTrackingResult == openvr.TrackingResult_Running_OK

    def start(self):
        self._thread = threading.Thread(target=self._run, name="vr", daemon=True)
        self._thread.start()

    def _run(self):
        nxt = time.perf_counter()
        while not self._stop.is_set():
            m, ok = self.pose_now()
            t = time.perf_counter_ns()
            with self._lock:
                self.t.append(t)
                self.poses.append((m, ok))
                if len(self.t) > 2 * self.keep:  # only recent history is ever looked up
                    del self.t[:self.keep], self.poses[:self.keep]
            nxt += self.period
            time.sleep(max(0.0, nxt - time.perf_counter()))

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        openvr.shutdown()

    def at(self, t_ns, window_ns=100_000_000):
        """(position at t_ns, speed m/s over +-window) by linear interpolation, or None if not tracked."""
        with self._lock:
            return self._at(self.t, self.poses, t_ns, window_ns)

    @staticmethod
    def _at(t, poses, t_ns, window_ns):
        i = bisect.bisect_left(t, t_ns)
        if i == 0 or i >= len(t):
            return None
        (m0, ok0), (m1, ok1) = poses[i - 1], poses[i]
        if not (ok0 and ok1):
            return None
        a = (t_ns - t[i - 1]) / max(t[i] - t[i - 1], 1)
        pos = (1 - a) * m0[:3, 3] + a * m1[:3, 3]
        rot = m0[:3, :3] if a < 0.5 else m1[:3, :3]
        j0 = bisect.bisect_left(t, t_ns - window_ns)
        j1 = min(bisect.bisect_left(t, t_ns + window_ns), len(t) - 1)
        if j1 <= j0:
            return None
        speed = np.linalg.norm(poses[j1][0][:3, 3] - poses[j0][0][:3, 3]) / ((t[j1] - t[j0]) / 1e9)
        return pos, rot, float(speed)


class VRDevices:
    """Snapshot of every device's pose on demand (the headset for VRChat's head alignment, and
    worn trackers when comparing against them). Attaches to a running SteamVR only."""

    def __init__(self, universe="standing"):
        self.vr = openvr.init(openvr.VRApplication_Background)
        self.universe = openvr.TrackingUniverseSeated if universe == "seated" else openvr.TrackingUniverseStanding
        self.refresh()

    def refresh(self):
        self.kinds = {}
        for i in range(openvr.k_unMaxTrackedDeviceCount):
            if self.vr.isTrackedDeviceConnected(i):
                self.kinds[i] = (CLASS_NAMES.get(self.vr.getTrackedDeviceClass(i), "other"),
                                 _prop(self.vr, i, openvr.Prop_SerialNumber_String))

    def poses(self, kinds=("headset", "tracker")):
        """{device index: (kind, serial, 4x4 pose)} for tracked devices of the given kinds."""
        raw = self.vr.getDeviceToAbsoluteTrackingPose(self.universe, 0, openvr.k_unMaxTrackedDeviceCount)
        out = {}
        for i, (kind, serial) in self.kinds.items():
            p = raw[i]
            if kind in kinds and p.bPoseIsValid and p.eTrackingResult == openvr.TrackingResult_Running_OK:
                m = np.eye(4)
                m[:3, :4] = np.ctypeslib.as_array(p.mDeviceToAbsoluteTracking.m)
                out[i] = (kind, serial, m)
        return out

    def headset(self):
        for kind, _, m in self.poses(("headset",)).values():
            return m
        return None

    def compositor_stats(self):
        """(frames presented, dropped, reprojected) so far for the VR game (VRChat), or None."""
        try:
            import ctypes
            s = openvr.VRCompositor().getCumulativeStats(ctypes.sizeof(openvr.Compositor_CumulativeStats))
            return int(s.m_nNumFramePresents), int(s.m_nNumDroppedFrames), int(s.m_nNumReprojectedFrames)
        except Exception:  # noqa: BLE001 - optional numbers only
            return None

    def stop(self):
        openvr.shutdown()
