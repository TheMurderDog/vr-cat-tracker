"""One capture thread per camera: fixed mode (e.g. MJPEG), locked settings, arrival timestamps, live stats.

Works with any UVC camera OpenCV can open. config.yaml holds exposure in milliseconds; how that
reaches the driver depends on the backend (cameras.exposure_units):
  log2_s  Windows DirectShow and Media Foundation take log2 seconds: -7 = 7.8 ms, -8 = 3.9 ms,
          -9 = 2.0 ms. The nearest step is used.
  100us   Linux V4L2 (exposure_time_absolute) takes units of 100 microseconds.
exposure_ms: null leaves the camera on automatic exposure. Every value is logged together with
what the driver reports back, since drivers differ.
"""

import collections
import logging
import math
import threading
import time

import cv2
import numpy as np

BACKENDS = {"msmf": cv2.CAP_MSMF, "dshow": cv2.CAP_DSHOW, "any": cv2.CAP_ANY}
ROTATIONS = {
    "none": None,
    "cw90": cv2.ROTATE_90_CLOCKWISE,
    "ccw90": cv2.ROTATE_90_COUNTERCLOCKWISE,
    "180": cv2.ROTATE_180,
}


def exposure_ms_to_step(ms):
    """Windows (DirectShow / Media Foundation) exposure step for a time in ms."""
    return int(round(math.log2(ms / 1000.0)))


def exposure_step_to_ms(step):
    return 1000.0 * 2.0 ** step


class CameraStats:
    """Rolling numbers for one camera, updated from its capture thread."""

    def __init__(self, nominal_fps, flicker_window):
        self.nominal_dt = 1e9 / nominal_fps
        self.arrivals = collections.deque(maxlen=int(nominal_fps * 2))  # 2 s for live fps
        self.strips = collections.deque(maxlen=flicker_window)
        self.frames = 0
        self.stalls = 0  # arrival gaps longer than 1.5 frames (late or lost frames)
        self.read_failures = 0
        self.duplicates = 0  # repeated frames the backend returned; not counted as frames
        self.max_gap_ms = 0.0
        self.first_ns = None
        self.last_ns = None

    def on_frame(self, t_ns, small_gray):
        if self.last_ns is not None:
            gap = t_ns - self.last_ns
            self.max_gap_ms = max(self.max_gap_ms, gap / 1e6)
            if gap > 1.5 * self.nominal_dt:
                self.stalls += 1
        else:
            self.first_ns = t_ns
        self.last_ns = t_ns
        self.frames += 1
        self.arrivals.append(t_ns)
        # Row means of a tiny grayscale copy. Mains flicker on a rolling-shutter sensor shows up
        # as horizontal bands, so each row band is tracked over time on its own.
        self.strips.append(small_gray.mean(axis=1))

    @property
    def dropped(self):
        """Frames missing compared with what the nominal rate should have delivered so far.

        Counted from elapsed time rather than from gaps, so a late frame followed by an early
        one is not counted as lost. A camera whose clock runs slightly slow (119.9 fps) shows
        up here as a slow, steady trickle.
        """
        if self.frames < 2:
            return 0
        expected = int(round((self.last_ns - self.first_ns) / self.nominal_dt)) + 1
        return max(0, expected - self.frames)

    def fps(self):
        if len(self.arrivals) < 2:
            return 0.0
        return (len(self.arrivals) - 1) * 1e9 / (self.arrivals[-1] - self.arrivals[0])

    def mean_fps(self):
        if self.frames < 2:
            return 0.0
        return (self.frames - 1) * 1e9 / (self.last_ns - self.first_ns)

    def flicker_pct(self):
        """Median over row bands of (temporal std / mean), in percent. Needs a still scene."""
        if len(self.strips) < self.strips.maxlen:
            return None
        s = np.asarray(self.strips, dtype=np.float32)
        mean = s.mean(axis=0)
        ok = mean > 8  # ignore near-black bands
        if not ok.any():
            return None
        return float(np.median(s.std(axis=0)[ok] / mean[ok]) * 100)

    def brightness(self):
        return float(self.strips[-1].mean()) if self.strips else 0.0


def camera_names(cfg):
    """People-facing camera names in slot order (cameras.names in config.yaml), e.g. north/south/east/west.
    Without names, cameras are called cam1, cam2, ..."""
    c = cfg["cameras"] if "cameras" in cfg else cfg
    names = c.get("names") or [f"cam{i + 1}" for i in range(len(c["ids"]))]
    if len(names) != len(c["ids"]) or len(set(names)) != len(names):
        raise ValueError("cameras.names needs one different name per entry in cameras.ids")
    return [str(n) for n in names]


def camera_slot(cfg, which):
    """Slot (0-based) for a camera given by name (e.g. north) or number (1 to the number of cameras)."""
    names = camera_names(cfg)
    w = str(which).strip().lower()
    if w in [n.lower() for n in names]:
        return [n.lower() for n in names].index(w)
    if w.isdigit() and 1 <= int(w) <= len(names):
        return int(w) - 1
    raise ValueError(f"unknown camera {which!r}; use one of: {', '.join(names)}")


class Camera:
    def __init__(self, slot, device_id, cam_cfg, rotation):
        self.slot = slot
        self.device_id = device_id
        self.cfg = cam_cfg
        self.rotation = ROTATIONS[rotation]
        self.name = camera_names(cam_cfg)[slot]  # people-facing name from cameras.names; slots 0-3 in code
        self.log = logging.getLogger(self.name)
        self.cap = None
        self.stats = CameraStats(cam_cfg["fps"], int(cam_cfg.get("flicker_window_frames", 360)))
        self.readback = {}
        self._lock = threading.Lock()
        self._latest = None  # (frame, t_ns, seq)
        self._stop = threading.Event()
        self._thread = None
        self._pending = []  # (prop, value) set from the capture thread to avoid racing the driver
        self.frame_hook = None  # optional fn(frame, t_ns) called on the capture thread for every new frame

    # ---- setup --------------------------------------------------------------

    def open(self):
        c = self.cfg
        backend = BACKENDS[c.get("backend", "any")]
        cap = cv2.VideoCapture(self.device_id, backend)
        if not cap.isOpened():
            raise RuntimeError(f"camera id {self.device_id} did not open on {c.get('backend')}")
        # FOURCC before size and fps, or DirectShow may pick an uncompressed mode that can't do high fps
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*c.get("fourcc", "MJPG")))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, c["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, c["height"])
        cap.set(cv2.CAP_PROP_FPS, c["fps"])
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap = cap
        self.apply_controls()
        self.read_back()
        mode = self.readback
        want = (c["width"], c["height"], c["fps"])
        got = (int(mode["width"]), int(mode["height"]), round(mode["fps"]))
        if c.get("require_exact_mode", True) and (got[:2] != want[:2] or self.readback["fourcc"] != c.get("fourcc", "MJPG")):
            # Device ids shift when other cameras (a VR headset's passthrough camera, a laptop webcam) are
            # plugged in; a device that can't do the configured mode is not one of the tracking cameras,
            # so it is refused rather than silently used with the wrong calibration.
            cap.release()
            self.cap = None
            raise RuntimeError(f"id {self.device_id} gives {got[0]}x{got[1]} {self.readback['fourcc']}, not "
                               f"{want[0]}x{want[1]} {c.get('fourcc', 'MJPG')}; not a tracking camera "
                               "(ids may have shifted: run probe_cameras)")
        if got != want:
            self.log.warning("%s asked for %sx%s@%s, driver reports %sx%s@%s", self.name, *want, *got)

    def apply_controls(self):
        c, cap = self.cfg, self.cap
        if c.get("exposure_ms") is not None:
            ms = float(c["exposure_ms"])
            units = c.get("exposure_units", "log2_s")
            value = exposure_ms_to_step(ms) if units == "log2_s" else ms * 10.0 if units == "100us" else ms
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, float(c.get("auto_exposure_off_value", 0.25)))
            cap.set(cv2.CAP_PROP_EXPOSURE, value)
            self.log.info("%s (id %d): exposure %.1f ms requested -> %s %g%s", self.name, self.device_id, ms, units,
                          value, f" ({exposure_step_to_ms(value):.2f} ms)" if units == "log2_s" else "")
        else:
            self.log.info("%s (id %d): automatic exposure (cameras.exposure_ms is not set)", self.name, self.device_id)
        if c.get("gain") is not None:
            cap.set(cv2.CAP_PROP_GAIN, float(c["gain"]))
        if c.get("white_balance_k") is not None:
            cap.set(cv2.CAP_PROP_AUTO_WB, 0)
            cap.set(cv2.CAP_PROP_WB_TEMPERATURE, float(c["white_balance_k"]))

    def read_back(self):
        cap = self.cap
        fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
        self.readback = {
            "width": cap.get(cv2.CAP_PROP_FRAME_WIDTH),
            "height": cap.get(cv2.CAP_PROP_FRAME_HEIGHT),
            "fps": cap.get(cv2.CAP_PROP_FPS),
            "fourcc": "".join(chr((fourcc >> 8 * i) & 0xFF) for i in range(4)) if fourcc > 0 else "?",
            "auto_exposure": cap.get(cv2.CAP_PROP_AUTO_EXPOSURE),
            "exposure": cap.get(cv2.CAP_PROP_EXPOSURE),
            "gain": cap.get(cv2.CAP_PROP_GAIN),
            "auto_wb": cap.get(cv2.CAP_PROP_AUTO_WB),
            "wb_k": cap.get(cv2.CAP_PROP_WB_TEMPERATURE),
            "backend": cap.getBackendName(),
        }
        self.log.info("%s readback: %s", self.name, self.readback)
        return self.readback

    # ---- runtime ------------------------------------------------------------

    def start(self):
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def _run(self):
        cap, st = self.cap, self.stats
        seq, prev_sig = 0, None
        while not self._stop.is_set():
            if self._pending:
                with self._lock:
                    pending, self._pending = self._pending, []
                for prop, value in pending:
                    if prop == "settings_dialog":
                        cap.set(cv2.CAP_PROP_SETTINGS, 1)
                    else:
                        cap.set(prop, value)
                self.read_back()
            # With DirectShow, grab() can return at once and retrieve() is what waits for the next
            # frame (seen on UVC webcams), so the arrival time is taken after read().
            # It therefore includes the JPEG decode, a roughly constant 1-3 ms.
            ok, frame = cap.read()
            t_ns = time.perf_counter_ns()
            if not ok or frame is None:
                st.read_failures += 1
                self.log.warning("%s read failed (%d so far)", self.name, st.read_failures)
                time.sleep(0.01)
                continue
            # An exact repeat of the previous image is the backend handing back its old buffer.
            # Real frames always differ a little from sensor noise; if the duplicate count climbs
            # while fps drops, check that the lens isn't covered.
            sig = frame[::24, ::24].tobytes()
            if sig == prev_sig:
                st.duplicates += 1
                continue
            prev_sig = sig
            small = cv2.resize(frame, (32, 24), interpolation=cv2.INTER_AREA)
            st.on_frame(t_ns, cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
            seq += 1
            with self._lock:
                self._latest = (frame, t_ns, seq)
            if self.frame_hook is not None:
                self.frame_hook(frame, t_ns)

    def latest(self, rotated=True):
        """Most recent (frame, t_ns, seq) or None. Rotation to upright happens here, off the capture thread."""
        with self._lock:
            item = self._latest
        if item is None:
            return None
        frame, t_ns, seq = item
        if rotated and self.rotation is not None:
            frame = cv2.rotate(frame, self.rotation)
        return frame, t_ns, seq

    def queue_set(self, prop, value=None):
        with self._lock:
            self._pending.append((prop, value))

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self.cap is not None:
            self.cap.release()


def open_cameras(cfg, log):
    """Open every camera in config.yaml in turn. Returns (cameras, errors)."""
    c = cfg["cameras"]
    cams, errors = [], []
    for slot, device_id in enumerate(c["ids"]):
        rot = c.get("rotate", "none")
        rotation = rot[slot] if isinstance(rot, list) else rot
        cam = Camera(slot, device_id, c, rotation)
        try:
            cam.open()
            cams.append(cam)
        except Exception as e:
            log.error("%s camera (id %d) failed to open: %s", cam.name, device_id, e)
            errors.append((slot, device_id, str(e)))
        time.sleep(float(c.get("open_delay_s", 0.5)))
    return cams, errors
