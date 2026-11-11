"""Sends the cat's position to VRChat as avatar parameters over OSC, for the avatar's cat prop.

Its position is sent as an offset from your head, flat along the floor, so it is right however the
play space, thumbstick, turns or teleports have moved you in VRChat:
  /avatar/parameters/CatAhead   float -1..1  metres ahead of the headset (its facing, ignoring tilt) / range_m
  /avatar/parameters/CatRight   float -1..1  metres to the headset's right / range_m
  /avatar/parameters/CatVisible bool         it is seen, or was seen recently (same fade as the overlay)
  /avatar/parameters/CatState   int          0 normal, 1 resting (still 2 minutes or more), 2 moving (same as the icons)
  /avatar/parameters/CatNear    bool         the tracker is warning you about it (the edge arrow is showing)
  /avatar/parameters/CatUp      float 0..1   how high its feet are above the floor, metres / range_m: its middle's
                                height minus locate.body_height_m, 0 below vrchat.height_snap_m. Only when 2+
                                cameras see it; one camera puts it on the floor (vrchat.send_height: false = off)
And in the room's own fixed floor frame (the camera calibration: SteamVR standing space at the time
the cameras were calibrated, y up, so it never moves with play space tools), from the same headset pose sample:
  /avatar/parameters/CatRoomX, CatRoomZ     float -1..1  its position on the floor, metres / range_m
  /avatar/parameters/HeadRoomX, HeadRoomZ   float -1..1  the headset's position on the floor, metres / range_m
  /avatar/parameters/HeadRoomYaw            float -1..1  the headset's heading on the floor, degrees / 180,
                                            clockwise seen from above; 0 faces -Z, 0.5 faces +X
  (so with yaw y: ahead = (sin y, -cos y) and right = (cos y, sin y) in (X, Z))
  /avatar/parameters/CatRoomYaw             float -1..1  the way it's heading, same units and frame as HeadRoomYaw,
                                            from its movement; kept when it stops (alert.Heading)
  /avatar/parameters/CatHeadingKnown        bool         it has moved enough since it was last found to know it
With vrchat.stick_anchor enabled (experimental, see stick_anchor.py), one more:
  /avatar/parameters/CatAnchorMode          bool         true: CatAhead, CatRight and HeadRoomX/Z/Yaw are measured
                                            from a fixed anchor pose (the headset's pose when the play space last
                                            came to rest) instead of the live headset, and the avatar draws the cat
                                            from a point it froze in the world when this turned true
All of them are sent together send_hz times a second (60), changed or not, from their own thread, each
time with the headset pose read at that moment, so a detection running in the main loop never holds
them up. The packets are written here (OSC 1.0 over UDP),
so nothing needs installing.
"""

import socket
import struct
import threading
import time

import numpy as np


def _pad(b):
    return b + b"\0" * (4 - len(b) % 4)


def message(address, value):
    """One OSC message: a float, or a bool (OSC's T/F tags, which VRChat reads as a bool parameter)."""
    if isinstance(value, bool):
        return _pad(address.encode()) + _pad(b",T" if value else b",F")
    if isinstance(value, int):
        return _pad(address.encode()) + _pad(b",i") + struct.pack(">i", value)
    return _pad(address.encode()) + _pad(b",f") + struct.pack(">f", float(value))


def room_head(hmd_room):
    """(x, z, yaw degrees clockwise from above, 0 = facing -z) of a headset pose in the room frame (y up)."""
    f = -hmd_room[:3, 2]
    if np.hypot(f[0], f[2]) < 1e-6:
        return None
    return float(hmd_room[0, 3]), float(hmd_room[2, 3]), float(np.degrees(np.arctan2(f[0], -f[2])))


def head_offset(cat_raw, hmd_raw):
    """(ahead, right) in metres from the headset to the cat, both in SteamVR raw space (y up)."""
    f = -hmd_raw[:3, 2]
    f = np.array([f[0], 0.0, f[2]])
    n = np.linalg.norm(f)
    if n < 1e-6:  # looking straight up or down: no heading to measure from
        return None
    f /= n
    r = np.array([-f[2], 0.0, f[0]])  # f x up
    d = cat_raw - hmd_raw[:3, 3]
    return float(d @ f), float(d @ r)


class OscCat:
    def __init__(self, vc, lc=None):
        """vc: the vrchat settings; lc: the locate settings (floor height and body height, for CatUp)."""
        lc = lc or {}
        self.addr = (vc.get("host", "127.0.0.1"), int(vc.get("port", 9000)))
        self.range = float(vc.get("range_m", 4.0))
        self.send_height = bool(vc.get("send_height", True))
        self.snap = float(vc.get("height_snap_m", 0.1))
        self.floor_y = float(lc.get("floor_y_m", 0.0))
        self.body_h = float(lc.get("body_height_m", 0.15))
        self.last_up = 0.0
        self.prefix = vc.get("prefix", "/avatar/parameters/")
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.last_offset = (0.0, 0.0)
        self.last_cat_room = (0.0, 0.0)
        self.last_head_room = (0.0, 0.0, 0.0)
        self.last_cat_yaw = 0.0

    def _send(self, name, value):
        try:
            self.sock.sendto(message(self.prefix + name, value), self.addr)
        except OSError:
            pass  # nothing listening yet (VRChat closed); UDP, so just try again next time

    STATES = {"normal": 0, "rest": 1, "move": 2}

    def _unit(self, metres):
        return max(-1.0, min(1.0, metres / self.range))

    def height(self, middle_y):
        """Metres from the floor up to its feet, from the height of its middle in the room frame (y up).
        Small values count as the floor, so a cat on the floor doesn't bob with the triangulation."""
        up = float(middle_y) - self.floor_y - self.body_h
        return up if up >= self.snap else 0.0

    def send(self, offset, visible, kind="normal", near=False, now=0.0, cat_room=None, head_room=None, cat_yaw=None,
             anchored=None, up=None):
        """Every parameter goes out on every send (OscStream, 60 a second), changed or not, so the avatar
        recovers at once when VRChat resets its parameters (an FBT recalibration, an avatar reload).
        While it's hidden, its last offset and room position are repeated, and the last headset pose
        while the headset isn't tracked. cat_room: it (x, z) in the room frame; head_room: room_head()
        of the pose the offset is measured from; anchored: CatAnchorMode, or None to leave it out;
        up: height() in metres, or None to repeat the last one."""
        visible = bool(visible and offset is not None)
        if visible:
            self.last_offset = tuple(self._unit(v) for v in offset)
            if cat_room is not None:
                self.last_cat_room = tuple(self._unit(v) for v in cat_room)
            if up is not None:
                self.last_up = max(0.0, self._unit(up))
        if head_room is not None:
            x, z, yaw = head_room
            self.last_head_room = (self._unit(x), self._unit(z), yaw / 180.0)
        ahead, right = self.last_offset
        self._send("CatAhead", ahead)
        self._send("CatRight", right)
        self._send("CatVisible", visible)
        self._send("CatState", self.STATES.get(kind, 0) if visible else 0)
        self._send("CatNear", bool(visible and near))
        if self.send_height:
            self._send("CatUp", self.last_up)
        self._send("CatRoomX", self.last_cat_room[0])
        self._send("CatRoomZ", self.last_cat_room[1])
        self._send("HeadRoomX", self.last_head_room[0])
        self._send("HeadRoomZ", self.last_head_room[1])
        self._send("HeadRoomYaw", self.last_head_room[2])
        if cat_yaw is not None:
            self.last_cat_yaw = cat_yaw / 180.0
        self._send("CatRoomYaw", self.last_cat_yaw)
        self._send("CatHeadingKnown", cat_yaw is not None)
        if anchored is not None:
            self._send("CatAnchorMode", bool(anchored))

    def close(self):
        self.send(None, False)
        self.sock.close()


class OscStream:
    """Sends at send_hz from a thread of its own. The main loop hands it its latest position with
    set_cat(); each send reads the headset pose right then and uses that one pose for every parameter."""

    def __init__(self, osc, vr, hz, log=None, anchor=None):
        """anchor: a stick_anchor.StickAnchor, or None to measure from the live headset only."""
        self.osc, self.vr, self.period, self.log, self.anchor = osc, vr, 1.0 / hz, log, anchor
        self.lock = threading.Lock()
        self.cat = (None, False, "normal", False, None, None)
        self.running = True
        self.thread = threading.Thread(target=self._run, name="osc", daemon=True)
        self.thread.start()

    def set_cat(self, cat_cam, visible, kind, near, raw_to_cam, yaw=None):
        """cat_cam: its shown position in the room (camera) frame, or None; raw_to_cam: the anchor;
        yaw: its heading in degrees (alert.Heading), or None while it isn't known."""
        with self.lock:
            self.cat = (None if cat_cam is None else np.array(cat_cam, float), bool(visible), kind, bool(near),
                        None if raw_to_cam is None else np.array(raw_to_cam, float), yaw)

    def _run(self):
        nxt = time.perf_counter()
        warned = False
        while self.running:
            try:
                with self.lock:
                    cat_cam, visible, kind, near, raw_to_cam, yaw = self.cat
                hmd = self.vr.headset()  # the newest pose, read for this send
                ref, anchored = hmd, None
                if self.anchor is not None and self.anchor.enabled:
                    stamp = self.anchor.update(time.monotonic(), hmd, self.vr.sticks(), self.vr.raw_to_standing())
                    anchored = stamp is not None
                    if anchored:
                        ref = stamp  # measured from the anchor pose, which the avatar froze in the world
                off = cat_room = head_room = up = None
                if ref is not None and raw_to_cam is not None:
                    head_room = room_head(raw_to_cam @ ref)
                    if cat_cam is not None:
                        cam_to_raw = np.linalg.inv(raw_to_cam)
                        off = head_offset(cam_to_raw[:3, :3] @ cat_cam + cam_to_raw[:3, 3], ref)
                        cat_room = (float(cat_cam[0]), float(cat_cam[2]))
                        up = self.osc.height(cat_cam[1])
                self.osc.send(off, visible, kind, near, time.monotonic(), cat_room=cat_room, head_room=head_room,
                              cat_yaw=yaw, anchored=anchored, up=up)
            except Exception as e:  # noqa: BLE001  keep sending; one bad pose read shouldn't stop the avatar
                if self.log is not None and not warned:
                    self.log.warning("OSC send failed (%s); still trying", e)
                    warned = True
            nxt += self.period
            spare = nxt - time.perf_counter()
            if spare > 0:
                time.sleep(spare)
            else:
                nxt = time.perf_counter()  # fell behind (the PC was busy): start the beat again from now

    def stop(self):
        self.running = False
        self.thread.join(timeout=1.0)
