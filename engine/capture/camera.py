"""One capture thread per camera: fixed mode (e.g. MJPEG), locked settings, arrival timestamps, live stats.

Works with any UVC camera OpenCV can open. settings/cameras.yaml holds exposure in milliseconds; how that
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
from core.single import hold_cameras

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


BLOCKY_LIMIT = 2.2  # broken frames: over this, the picture's bottom third shows JPEG blocks (see jpeg_blocky)


def jpeg_blocky(frame):
    """How blocky the bottom third of a picture is: steps across 8-pixel JPEG block edges against steps inside the
    blocks (every fourth row, green channel, so it costs well under a millisecond). About 1 for a good frame. A
    camera short of USB bandwidth compresses the end of each frame (the bottom) much harder, or loses it: blocks
    and smears that come and go. Measured on the test setup's cameras: good frames 1.0-1.7, broken ones about 3."""
    h = frame.shape[0]
    g = (frame[2 * h // 3::4, :, 1] if frame.ndim == 3 else frame[2 * h // 3::4]).astype(np.int16)
    dx = np.abs(np.diff(g, axis=1))
    edge = float(dx[:, 7::8].mean())
    inside = float(np.delete(dx, np.s_[7::8], axis=1).mean())
    return edge / max(inside, 0.5)


UNPLUG_AFTER_S = 2.0    # no new frame for this long: the camera is treated as unplugged, and its device released
RESCAN_EVERY_S = 2.0    # while unplugged, how often Windows' device list is checked for it (off the frame loop)


def unplugged_frame(width, height, name, missing=False):
    """What an unplugged (or not yet found) camera shows instead of a picture, in any tool: dark, with its state."""
    img = np.full((height, width, 3), 25, np.uint8)
    s = height / 720
    lines = [(f"{name}: {'not found yet' if missing else 'unplugged'}", (80, 80, 255), 1.6),
             ("waiting for it...", (240, 240, 240), 1.1),
             ("Check its cable, and close other programs using it: it joins by itself." if missing else
              "Plug it back in: it reconnects by itself.", (180, 180, 180), 0.8)]
    y = int(height * 0.42)
    for text, colour, scale in lines:
        sc = scale * s
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, sc, max(2, int(3 * sc)))
        outlined_text(img, text, ((width - tw) // 2, y), cv2.FONT_HERSHEY_SIMPLEX, sc, colour, max(2, int(3 * sc)),
                      cv2.LINE_AA)
        y += int(th * 2.0)
    return img


class CameraStats:
    """Rolling numbers for one camera, updated from its capture thread."""

    def __init__(self, nominal_fps, flicker_window):
        self.nominal_dt = 1e9 / nominal_fps
        self.arrivals = collections.deque(maxlen=int(nominal_fps * 2))  # 2 s for live fps
        self.strips = collections.deque(maxlen=max(int(flicker_window), 600))  # ~5 s at 120 fps, 20 s at 30
        self.strip_ns = collections.deque(maxlen=self.strips.maxlen)
        self.frames = 0
        self.stalls = 0  # arrival gaps longer than 1.5 frames (late or lost frames)
        self.read_failures = 0
        self.duplicates = 0  # repeated frames the backend returned; not counted as frames
        self.broken = 0  # frames dropped because their bottom was damaged (see jpeg_blocky); not counted as frames
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
        self.strip_ns.append(t_ns)

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

    def flicker_pct(self, seconds=4.0, lights=(100.0, 120.0)):
        """How much the room light flickers in the picture: peak-to-peak brightness swing in percent, at the
        frequency mains lights flicker at (100 or 120 Hz) as this camera samples it. A camera at 122 fps sees a
        120 Hz light as a slow 2 Hz pulse; at exactly 120 fps it would see none (a still band, harmless). Measured by
        lock-in over the last few seconds, per row band (rolling shutter), median over the bands: something moving
        in the picture isn't at that exact frequency, so it doesn't count. None until there are enough frames, or
        when the light's pulse is too slow to tell apart (under 0.3 Hz)."""
        if len(self.strips) < 60:
            return None
        ns, strips = list(self.strip_ns), list(self.strips)  # copies: the capture thread keeps adding to both
        n = min(len(ns), len(strips))
        ns, strips = ns[len(ns) - n:], strips[len(strips) - n:]
        t = (np.asarray(ns, dtype=np.float64) - ns[-1]) / 1e9
        keep = t > -seconds
        if keep.sum() < 60 or -t[keep][0] < 1.5:
            return None
        t = t[keep]
        s = np.asarray(strips, dtype=np.float32)[keep]
        fps = (len(t) - 1) / (t[-1] - t[0])
        mean = s.mean(axis=0)
        ok = mean > 8  # ignore near-black bands
        if not ok.any():
            return None
        best = None
        for light in lights:
            alias = abs(light - fps * round(light / fps))  # what the camera's frame rate makes of it
            if alias < 0.3 or alias > fps / 2 - 0.5:
                continue
            if 1.0 / alias > (t[-1] - t[0]):  # not even one whole pulse in the window
                continue
            w = np.exp(-2j * np.pi * alias * t)[:, None]
            amp = 2 * np.abs(((s - mean) * w).mean(axis=0))  # the swing at that frequency, per band
            pp = float(np.median(2 * amp[ok] / mean[ok]) * 100)
            best = pp if best is None else max(best, pp)
        return best

    def brightness(self):
        return float(self.strips[-1].mean()) if self.strips else 0.0


def camera_names(cfg):
    """People-facing camera names in slot order (cameras.names in settings/cameras.yaml), e.g. north/south/east/west.
    Without names, cameras are called cam1, cam2, ..."""
    c = cfg["cameras"] if "cameras" in cfg else cfg
    names = c.get("names") or [f"cam{i + 1}" for i in range(len(c["ids"]))]
    if len(names) != len(c["ids"]) or len(set(names)) != len(names):
        raise ValueError("cameras.names needs one different name per entry in cameras.ids")
    return [str(n) for n in names]


def camera_keys(cfg):
    """Each camera's calibration key, in slot order: what its lens and room results are filed under (my_data/
    calibration/intrinsics_<key>.json, reference_<key>.png, and the key in room.json). The setup screen keeps a
    camera's key when it's renamed or reordered, so neither ever costs a calibration; the name is only a label.
    Settings without cameras.keys (from before it existed) use the names, which is what the files were called."""
    c = cfg["cameras"] if "cameras" in cfg else cfg
    names = camera_names(c)
    keys = c.get("keys")
    if not keys:
        return names
    keys = [str(k) for k in keys]
    if len(keys) != len(names) or len(set(keys)) != len(keys):
        raise ValueError("cameras.keys needs one different key per camera (the setup screen keeps them)")
    return keys


def spoken(name, start=False):
    """A camera as said in a sentence, for any name: "the North camera"; "camera 1" for a bare number or a name
    like cam1; "the porch camera" for a name that already says camera; "this camera" with no name. start=True
    capitalises it for the start of a sentence."""
    import re
    n = str(name or "").strip()
    m = re.fullmatch(r"(?i)(?:cam(?:era)?[\s_-]*)?(\d+)", n)
    if not n:
        out = "this camera"
    elif m:
        out = f"camera {int(m.group(1))}"
    elif re.search(r"(?i)\b(cam|camera|webcam)$", n):
        out = f"the {n}"
    else:
        out = f"the {n} camera"
    return out[0].upper() + out[1:] if start else out


def say_camera_events(cams, voice, now=None, log=None):
    """Say once when a camera is unplugged or comes back (every tool with a voice calls this in its loop)."""
    said = []
    for c in cams:
        for what, _ in (c.pop_events() if hasattr(c, "pop_events") else []):
            text = (f"{spoken(c.name, True)} was unplugged. Plug it back in and it reconnects by itself."
                    if what == "unplugged" else
                    f"{spoken(c.name, True)} isn't there yet. Check its cable, and close other programs using it." if what == "missing"
                    else f"{spoken(c.name, True)} is back.")
            said.append(text)
            if voice is not None:
                voice.say(text, now, force=True)
    return said


def spoken_list(names, start=False):
    """Several cameras in a sentence: "the North camera and camera 2"."""
    items = [spoken(n) for n in names]
    text = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
    return text[0].upper() + text[1:] if start else text


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
        self.fps = fps_list(cam_cfg)[slot]
        # with cameras.fps: auto (experimental), the camera's normal speed to fall back to if the lower one misbehaves
        self.full_fps = (fps_list({"ids": cam_cfg["ids"], "fps": cam_cfg["fps_full"]})[slot]
                         if cam_cfg.get("fps_full") is not None else None)
        self.stats = CameraStats(self.fps, int(cam_cfg.get("flicker_window_frames", 360)))
        self.readback = {}
        self._lock = threading.Lock()
        self._latest = None  # (frame, t_ns, seq)
        self._stop = threading.Event()
        self._thread = None
        self._pending = []  # (prop, value) set from the capture thread to avoid racing the driver
        self._speed_told = False  # the speed it really gives is logged once, after its first 2 s
        self.frame_hook = None  # optional fn(frame, t_ns) called on the capture thread for every new frame
        self.blocky_limit = float(cam_cfg.get("blocky_limit", BLOCKY_LIMIT))  # frames damaged on the way are dropped
        self.state = "ok"     # "ok", or "unplugged" while it waits to come back by itself
        self.events = []      # ("unplugged" or "back", time): tools that speak say it once (pop_events)
        self.unplug_after_s = float(cam_cfg.get("unplug_after_s", UNPLUG_AFTER_S))
        self.autofocus_stuck = False  # the setup screen's focus lock found its autofocus can't be switched off

    # ---- setup --------------------------------------------------------------

    def open(self):
        self._open()
        if self.full_fps is not None and self.full_fps != self.fps:
            problem = self._frames_problem()
            if problem:
                self.log.warning("%s: at %d fps %s; using its normal %d fps instead", self.name, self.fps, problem,
                                 self.full_fps)
                self.cap.release()
                self.fps = self.full_fps
                self.stats = CameraStats(self.fps, int(self.cfg.get("flicker_window_frames", 360)))
                self._open()

    def _frames_problem(self, seconds=2.0, need=5):
        """Why the frames at the lower speed can't be trusted, or None: none arrive, they're black or frozen, or
        they aren't the calibrated size (a different sensor crop would make the calibration silently wrong)."""
        c, frames, t0 = self.cfg, [], time.perf_counter()
        while time.perf_counter() - t0 < seconds and len(frames) < need:
            ok, f = self.cap.read()
            if ok and f is not None:
                frames.append(f)
        if len(frames) < need:
            return f"only {len(frames)} frames arrived in {seconds:.0f} s"
        if any(f.shape[1] != c["width"] or f.shape[0] != c["height"] for f in frames):
            return f"frames are {frames[-1].shape[1]}x{frames[-1].shape[0]}, not the calibrated {c['width']}x{c['height']}"
        if max(float(f.mean()) for f in frames) < 3:
            return "the frames are black"
        if len({f[::24, ::24].tobytes() for f in frames}) == 1:
            return "the picture is frozen"
        return None

    def _open(self):
        c = self.cfg
        backend = BACKENDS[c.get("backend", "any")]
        hold_cameras(self.log)  # wait while another tool still has the cameras
        cap = cv2.VideoCapture(self.device_id, backend)
        if not cap.isOpened():
            raise RuntimeError(f"camera id {self.device_id} did not open on {c.get('backend')}")
        # FOURCC before size and fps, or DirectShow may pick an uncompressed mode that can't do high fps
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*c.get("fourcc", "MJPG")))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, c["width"])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, c["height"])
        cap.set(cv2.CAP_PROP_FPS, self.fps)  # many drivers keep their own speed anyway; that's fine
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.cap = cap
        self.apply_controls()
        self.read_back()
        mode = self.readback
        want = (c["width"], c["height"], self.fps)
        got = (int(mode["width"]), int(mode["height"]), round(mode["fps"]))
        if c.get("require_exact_mode", True) and (got[:2] != want[:2] or self.readback["fourcc"] != c.get("fourcc", "MJPG")):
            # Device ids shift when other cameras (a VR headset's passthrough camera, a laptop webcam) are
            # plugged in; a device that can't do the configured mode is not one of the tracking cameras,
            # so it is refused rather than silently used with the wrong calibration.
            cap.release()
            self.cap = None
            raise RuntimeError(f"id {self.device_id} gives {got[0]}x{got[1]} {self.readback['fourcc']}, not "
                               f"{want[0]}x{want[1]} {c.get('fourcc', 'MJPG')}; not a tracking camera "
                               "(ids may have shifted: run 1_connect_cameras\\1_set_up_cameras.bat)")
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
        from capture import focus  # a focus saved by the setup screen: autofocus off, and that value (checked)
        try:
            key = camera_keys(c)[self.slot]
        except (ValueError, IndexError):
            key = self.name
        want = focus.saved(c, key)
        self.autofocus_stuck = want == "stuck"
        if want == "stuck":
            self.log.warning("%s: %s", self.name, focus.STUCK)
        elif want is not None and want != "ring":  # "ring": a focus-ring camera, nothing to set
            ok, got = focus.apply(cap, want)
            if ok:
                self.log.info("%s: autofocus off, focus %g (saved by the setup screen)", self.name, want)
            else:
                self.log.warning("%s: the saved focus %g didn't take (reads %s): its autofocus may still be on",
                                 self.name, want, got)
        else:
            try:
                af = float(cap.get(cv2.CAP_PROP_AUTOFOCUS))
            except cv2.error:
                af = -1.0
            if af == 1.0:  # many focus-ring cameras report this too: only a note (the setup screen's k finds out)
                self.log.info("%s: the driver reports autofocus on (focus-ring cameras often do; nothing locked)",
                              self.name)

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

    def pop_events(self):
        """("unplugged" or "back", time) since the last call, for a tool to say once."""
        with self._lock:
            out, self.events = self.events, []
        return out

    def _wait_for_return(self, missing=False):
        """Unplugged (or missing from the start): release the device, then every RESCAN_EVERY_S look for it in
        Windows' device list (on its old USB port, or on a new one when it's the only new camera) and open it.
        Returns when it's there, or when stopped."""
        self.state = "missing" if missing else "unplugged"
        with self._lock:
            self._latest = None
            self.events.append((self.state, time.monotonic()))
        if missing:
            self.log.warning("%s isn't there yet (unplugged, or another program is using it): it joins when it can",
                             self.name)
        else:
            self.log.warning("%s stopped sending pictures (unplugged?): waiting for it to come back", self.name)
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:  # noqa: BLE001
            pass
        while not self._stop.wait(RESCAN_EVERY_S):
            try:
                from capture.devices import list_devices
                ids, problems = resolve_ids(self.cfg, devices=list_devices())  # now: no waiting inside
            except Exception:  # noqa: BLE001  (the device list can't be read for a moment)
                continue
            if self.slot in problems or self.slot >= len(ids):
                continue
            self.device_id = ids[self.slot]
            try:
                self._open()
                ok, frame = self.cap.read()
            except Exception:  # noqa: BLE001  (another program has it, or it's still waking up)
                ok = False
            if ok and frame is not None:
                self.state = "ok"
                with self._lock:
                    self.events.append(("back", time.monotonic()))
                self.log.info("%s is back (id %d)", self.name, self.device_id)
                return True
            try:
                self.cap.release()
            except Exception:  # noqa: BLE001
                pass
        return False

    def _run(self):
        cap, st = self.cap, self.stats
        seq, prev_sig = 0, None
        last_new = time.monotonic()
        if self.state == "missing":  # not there when the tool started: wait for it, then go on as normal
            if not self._wait_for_return(missing=True):
                return
            cap, last_new = self.cap, time.monotonic()
        while not self._stop.is_set():
            if time.monotonic() - last_new > self.unplug_after_s:  # no new picture for a while: unplugged
                if not self._wait_for_return():
                    return
                cap, prev_sig, last_new = self.cap, None, time.monotonic()
                continue
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
                if st.read_failures in (1, 10, 100) or st.read_failures % 1000 == 0:
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
            last_new = time.monotonic()
            if jpeg_blocky(frame) > self.blocky_limit:  # damaged on the way (USB): never passed on to anything
                st.broken += 1
                if st.broken in (1, 10, 100) or st.broken % 1000 == 0:
                    self.log.warning("%s: %d damaged frames dropped so far (blocky bottom: short of USB bandwidth? "
                                     "Try a USB port on another controller, not a hub shared with another camera)",
                                     self.name, st.broken)
                continue
            small = cv2.resize(frame, (32, 24), interpolation=cv2.INTER_AREA)
            st.on_frame(t_ns, cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
            seq += 1
            with self._lock:
                self._latest = (frame, t_ns, seq)
            if not self._speed_told and st.first_ns is not None and t_ns - st.first_ns > 2e9:
                self._speed_told = True
                self.tell_speed(st.fps())
            if self.frame_hook is not None:
                self.frame_hook(frame, t_ns)

    def tell_speed(self, real):
        """Log the speed asked for and the speed the camera really gives. Many cameras offer only their top speed at
        a size and ignore the one asked for; the newest frame is used either way, so it's kept, with no warning."""
        if abs(real - self.fps) <= 0.15 * self.fps:
            self.log.info("%s: %d fps, as asked", self.name, self.fps)
        else:
            # a measurement only, nothing is changed: many cameras give only their top speed at a size (checked:
            # 120 distinct pictures a second at 1280x720), and the tracker takes the newest one either way
            self.log.debug("%s: the camera's own speed is about %.0f a second (asked %d); nothing to change",
                           self.name, real, self.fps)

    def latest(self, rotated=True):
        """Most recent (frame, t_ns, seq) or None. Rotation to upright happens here, off the capture thread.
        While unplugged: a picture saying so (seq -1, never a new frame), so every tool shows it without asking."""
        if self.state in ("unplugged", "missing"):
            w, h = int(self.cfg["width"]), int(self.cfg["height"])
            if rotated and self.rotation in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
                w, h = h, w
            img = unplugged_frame(w, h, self.name, missing=self.state == "missing")
            if not rotated and self.rotation is not None:  # raw frame: the tool rotates it upright itself
                back = {cv2.ROTATE_90_CLOCKWISE: cv2.ROTATE_90_COUNTERCLOCKWISE,
                        cv2.ROTATE_90_COUNTERCLOCKWISE: cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180: cv2.ROTATE_180}
                img = cv2.rotate(img, back[self.rotation])
            return img, time.perf_counter_ns(), -1
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


def excluded(c, name, path):
    """True if cameras.exclude has a pattern found in this device's name or path (ignoring case): never open it."""
    text = f"{name or ''} {path or ''}".lower()
    return any(str(p).lower() in text for p in (c.get("exclude") or []) if str(p).strip())


def resolve_ids(cfg, log=None, devices=None):
    """The OpenCV id to open for each camera slot now, and a problem message per slot that can't be opened.

    With cameras.backend: dshow and cameras.devices saved (one device path per camera, by the setup screen), each
    camera is found by its path, so plugging a headset in or out (which shifts every id after it) doesn't swap
    cameras. Ids alone are used when the device list can't be read, or for other backends (their order differs).
    An excluded device (cameras.exclude) is never opened. Returns (ids, {slot: message})."""
    from capture.devices import list_devices  # Windows-only ctypes code, loaded only when needed

    c = cfg["cameras"] if "cameras" in cfg else cfg
    ids, names = list(c["ids"]), camera_names(c)
    saved = list(c.get("devices") or [])
    problems = {}
    if c.get("backend", "any") != "dshow":
        return ids, problems
    if devices is None:
        devs = list_devices()
        wanted = [w for w in saved[:len(ids)] if w]
        end = time.monotonic() + float(c.get("find_wait_s", 8))
        told = False
        # Right after another tool closes, Windows can take a few seconds to list its cameras again: wait for them
        # rather than calling them unplugged
        while devs is not None and wanted and not all(w in [p for _, p in devs] for w in wanted)                 and time.monotonic() < end:
            if not told and log:
                log.info("Waiting for Windows to list every camera...")
                told = True
            time.sleep(0.5)
            devs = list_devices()
    else:
        devs = devices
    if devs is None:
        return ids, problems
    paths = [p for _, p in devs]
    for slot, device_id in enumerate(ids):
        want = saved[slot] if slot < len(saved) else None
        if want and want in paths:
            ids[slot] = paths.index(want)
            if ids[slot] != device_id and log:
                log.info("%s camera is now id %d (was %d): matched by its USB device", names[slot], ids[slot], device_id)
        elif want:  # its USB device is gone: never guess by its old number (identical cameras would swap silently)
            problems[slot] = (f"{names[slot]} camera wasn't found: not plugged in, or on a new USB port. Run "
                              "1_connect_cameras\\1_set_up_cameras.bat (it finds a moved camera, or lets you say "
                              "which picture it is)")
            continue
        if 0 <= ids[slot] < len(devs) and excluded(c, *devs[ids[slot]]):
            problems[slot] = (f"{names[slot]} camera (id {ids[slot]}) is {devs[ids[slot]][0]}, which cameras.exclude "
                              "says never to open. Run 1_connect_cameras\\1_set_up_cameras.bat")
    # One camera moved to another USB port: its saved device is gone and exactly one camera Windows lists is one we
    # don't know. Identical cameras can't be told apart any other way, so with exactly one of each it's that one.
    missing = [s for s in range(len(ids)) if s < len(saved) and saved[s] and saved[s] not in paths]
    unknown = [k for k, (n, pth) in enumerate(devs) if pth and pth not in saved and not excluded(c, n, pth)]  # real cameras only
    if len(missing) == 1 and len(unknown) == 1:
        slot = missing[0]
        ids[slot] = unknown[0]
        problems.pop(slot, None)
        if log:
            log.info("%s camera is on a new USB port (id %d): the only new camera, so it keeps its settings",
                     names[slot], ids[slot])
    return ids, problems


AUTO_FPS = 30  # what the cat tracker asks for with the experimental cameras.fps: auto, and the lowest it ever asks for
MIN_FPS = AUTO_FPS  # why 30: docs/technical/architecture.md (measured: 15 fps costs ~9 cm on a sprinting cat)


def fps_list(cfg):
    """cameras.fps as one speed per camera slot: a single number for all, or a list, one per camera."""
    c = cfg["cameras"] if "cameras" in cfg else cfg
    f = c.get("fps", 30)
    return [int(x) for x in f] if isinstance(f, list) else [int(f)] * len(c["ids"])


def rotations(cfg):
    """cameras.rotate as one value per camera slot (it may be a single value for all, or a list). Strings, since
    YAML reads an unquoted 180 as a number."""
    c = cfg["cameras"] if "cameras" in cfg else cfg
    rot = c.get("rotate", "none")
    return [str(r) for r in rot] if isinstance(rot, list) else [str(rot)] * len(c["ids"])


def outlined_text(img, text, org, font, scale, color, thickness=1, line_type=cv2.LINE_AA):
    """cv2.putText with a black outline, so the text reads on a bright wall or a dark corner alike.
    Same arguments as cv2.putText; every camera window draws its text with this. OpenCV 5 caps how thick text gets,
    so the outline is the text drawn in black shifted a few pixels every way, then the colour on top."""
    r = max(2, round(scale * 3))
    x, y = org
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            if (dx or dy) and dx * dx + dy * dy <= r * r:
                cv2.putText(img, text, (x + dx, y + dy), font, scale, (0, 0, 0), thickness, line_type)
    cv2.putText(img, text, org, font, scale, color, thickness, line_type)


def label_tile(img, name, height):
    """A camera picture scaled to height with its name top left: how every multi-camera window shows a camera."""
    s = height / img.shape[0]
    img = cv2.resize(img, (max(1, int(img.shape[1] * s)), height), interpolation=cv2.INTER_AREA)
    outlined_text(img, name, (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return img


def tile_grid(tiles):
    """Camera tiles of one height in the windows' layout: 2 x 2 for four cameras, otherwise one row.
    Turned cameras make narrower tiles, so a shorter row is padded with black on the right."""
    if not tiles:
        return None
    rows = [np.hstack(r) for r in ([tiles[:2], tiles[2:]] if len(tiles) == 4 else [tiles])]
    width = max(r.shape[1] for r in rows)
    return np.vstack([np.pad(r, ((0, 0), (0, width - r.shape[1]), (0, 0))) for r in rows])


def open_cameras(cfg, log, on_open=None):
    """Open every camera in settings/cameras.yaml in turn. Returns (cameras, errors).
    on_open(cam), if given, is called as each one opens (e.g. to start using it before the rest are ready).
    A camera that isn't there (unplugged, not listed yet, or another program has it) is returned anyway, waiting:
    its picture says so, and it joins by itself when it's there. Only a device cameras.exclude forbids is an error."""
    c = cfg["cameras"]
    cams, errors = [], []
    if not c.get("ids"):
        log.error("No cameras chosen yet: run 1_connect_cameras\\1_set_up_cameras.bat first and save (s).")
        return cams, [(None, None, "no cameras chosen yet")]
    ids, problems = resolve_ids(cfg, log)
    for slot, (device_id, rotation) in enumerate(zip(ids, rotations(cfg))):
        if slot in problems and "cameras.exclude" in problems[slot]:
            log.error(problems[slot])
            errors.append((slot, device_id, problems[slot]))
            continue
        cam = Camera(slot, device_id, c, rotation)
        if slot in problems:
            log.warning("%s; starting without it: it joins when it's there", problems[slot])
            cam.state = "missing"
        else:
            try:
                cam.open()
            except Exception as e:  # noqa: BLE001  (busy, or gone again): wait for it like a missing one
                log.warning("%s camera (id %d) didn't open (%s); it joins when it can", cam.name, device_id, e)
                cam.state = "missing"
        cams.append(cam)
        if on_open is not None:
            on_open(cam)
        if cam.state == "ok":
            time.sleep(float(c.get("open_delay_s", 0.5)))
    return cams, errors


def wait_for_any(cams, log, seconds=15.0):
    """At start: wait up to seconds for at least one camera to be there; if none is, say plainly what to check.
    Returns True if one is there (the rest join as they appear)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if any(c.state == "ok" for c in cams):
            return True
        time.sleep(0.2)
    log.error("No camera found after %.0f s. Check the cameras are plugged in (straight into the PC, not a shared hub), "
              "and that no other program has them (the setup screen or another step). Still waiting for them.", seconds)
    return False
