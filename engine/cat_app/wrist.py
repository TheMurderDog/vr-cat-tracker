"""The wrist widget: a small panel in VR with the cat at a glance (WristWidget.qml).

It sits on your left or right wrist, in your view, or at a fixed spot in the room. With the other
hand you can grab it (grip) and put it somewhere else, and resize it with the thumbstick while you
hold it; once it's where you want it, Lock stops it being moved. It fades out unless you look at it.

Like the dashboard tab it's drawn by Qt on the CPU and handed to SteamVR as one Direct3D 11 texture.
Attached to a controller or your head, SteamVR moves it with you, so this only has to check now and
then (about 30 times a second) whether you're looking at it or grabbing it.
"""

import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

from core.config import resolve_path

from cat_app.vr_dashboard import APP_KEY, PictureFile, describe

KEY = APP_KEY + ".wrist"
SIZE = (640, 320)
HERE = Path(__file__).resolve().parent
TMP_DIR = resolve_path("my_data/app")


class _Done(Exception):
    pass


def m44(m34):
    m = np.eye(4)
    m[:3, :4] = np.ctypeslib.as_array(m34.m)
    return m


def m34(openvr, T):
    m = openvr.HmdMatrix34_t()
    for i in range(3):
        for j in range(4):
            m.m[i][j] = float(T[i, j])
    return m


def rot_x(deg):
    a = math.radians(deg)
    R = np.eye(4)
    R[1, 1], R[1, 2], R[2, 1], R[2, 2] = math.cos(a), -math.sin(a), math.sin(a), math.cos(a)
    return R


def default_offset(attach):
    """Where it starts, relative to what it's attached to (metres; -z is forward)."""
    T = np.eye(4)
    if attach in ("left", "right"):
        # above the back of the hand, towards the wrist, tilted to face up and back at your eyes
        T = rot_x(-70.0)
        T[:3, 3] = [0.0, 0.05, 0.12]
    elif attach == "head":
        T[:3, 3] = [0.20, -0.17, -0.65]   # low and to the right of the middle of your view
    return T


def fade_alpha(T_widget, T_hmd, start_deg, use_fade=True):
    """1 while you look at it (within start_deg of the middle of your view) and it faces you, fading
    to 0 over the next 15 degrees, or as it turns away from you."""
    if not use_fade:
        return 1.0
    eye, fwd = T_hmd[:3, 3], -T_hmd[:3, 2]
    to_w = T_widget[:3, 3] - eye
    d = np.linalg.norm(to_w)
    if d < 1e-6:
        return 1.0
    ang = math.degrees(math.acos(max(-1.0, min(1.0, float(fwd @ to_w) / d))))
    a = 1.0 - (ang - start_deg) / 15.0
    facing = float(T_widget[:3, 2] @ (-to_w / d))  # its face (+z) towards your eyes
    f = (facing - 0.05) / 0.3
    return float(max(0.0, min(1.0, a)) * max(0.0, min(1.0, f)))


def arrow_angle(T_widget, cat):
    """Which way the cat is, for the arrow on the widget's face: degrees clockwise, 0 = towards the panel's
    top edge. "Ahead" is the way the panel points along the floor (its top edge, and away from its face),
    so on your wrist it's the way your hand points, like a compass you hold. None if the cat is right there."""
    d = np.asarray(cat, float) - T_widget[:3, 3]
    f = T_widget[:3, 1] - T_widget[:3, 2]
    fx, fz, dx, dz = float(f[0]), float(f[2]), float(d[0]), float(d[2])
    if math.hypot(fx, fz) < 1e-6 or math.hypot(dx, dz) < 0.05:
        return None
    rx, rz = -fz, fx  # the panel's right along the floor (x right, y up, -z ahead)
    return math.degrees(math.atan2(dx * rx + dz * rz, dx * fx + dz * fz))


class WristWidget:
    def __init__(self, dash, openvr, vr, ov, engine, backend, log):
        from cat_app.vr_dashboard import OffscreenQml
        self.dash, self.openvr, self.vr, self.ov = dash, openvr, vr, ov
        self.backend, self.log = backend, log
        self.panel = OffscreenQml(engine, HERE / "qml" / "WristWidget.qml", dash, backend, size=SIZE)
        self.handle = ov.createOverlay(KEY, "Cat Tracker wrist widget")
        self.d3d = None
        self.mode = dash.mode
        self.picture = PictureFile("wrist")
        self.alpha = -1.0
        self.shown = False
        self.placed = None          # (attach, offset bytes, device index) last given to SteamVR
        self.width = None
        self.grab = None            # while grabbed: {"hand": 0/1, "rel": 4x4}
        self.last_frame = 0.0
        self.last_tick = time.monotonic()
        self.raw_to_std = None      # (when read, 4x4): SteamVR raw space -> standing space
        self.hand_angle = None      # (hand mode, angle or None) last given to the panel
        self.input = None
        self._setup_input()
        self.apply()

    # ---- controllers ----

    def _setup_input(self):
        """SteamVR Input: grip on either hand grabs, the thumbstick resizes (cat_app/input/actions.json).
        Under the app's own app key, so its bindings don't get mixed up with the tracker's. When SteamVR
        started the app, the key is already registered; otherwise it's registered for this session only."""
        o = self.openvr
        try:
            apps = o.VRApplications()
            if apps.isApplicationInstalled(APP_KEY):
                apps.identifyApplication(os.getpid(), APP_KEY)
                raise _Done
            man = TMP_DIR / "cat_tracker_app.vrmanifest"
            man.parent.mkdir(parents=True, exist_ok=True)
            man.write_text(json.dumps({"source": "builtin", "applications": [{
                "app_key": APP_KEY, "launch_type": "binary", "binary_path_windows": sys.executable,
                "is_dashboard_overlay": True, "action_manifest_path": str(HERE / "input" / "actions.json"),
                "strings": {"en_us": {"name": "Cat Tracker app", "description": "The cat tracker's window and VR tab"}}}]}),
                encoding="utf-8")
            apps.addApplicationManifest(str(man), True)  # temporary: not kept by SteamVR after it closes
            apps.identifyApplication(os.getpid(), APP_KEY)
        except _Done:
            pass
        except Exception as e:  # noqa: BLE001
            self.log(f"Wrist widget: couldn't register the app with SteamVR ({describe(e)}); grabbing may not work")
        try:
            inp = o.VRInput()
            inp.setActionManifestPath(str(HERE / "input" / "actions.json"))
            self.aset = inp.getActionSetHandle("/actions/catapp")
            self.a_grab = inp.getActionHandle("/actions/catapp/in/grab")
            self.a_size = inp.getActionHandle("/actions/catapp/in/resize")
            self.hands = [inp.getInputSourceHandle(p) for p in ("/user/hand/left", "/user/hand/right")]
            self.active = (o.VRActiveActionSet_t * 1)()
            self.active[0].ulActionSet = self.aset
            self.input = inp
        except Exception as e:  # noqa: BLE001
            self.input = None
            self.log(f"Wrist widget: no controller input ({describe(e)}); it shows, but can't be grabbed")

    def _buttons(self):
        """[(grab held, grab just pressed, grab just released, stick y) for left, right]."""
        out = []
        if self.input is None:
            return [(False, False, False, 0.0)] * 2
        try:
            self.input.updateActionState(self.active)
        except Exception:  # noqa: BLE001
            return [(False, False, False, 0.0)] * 2
        for h in self.hands:
            try:
                d = self.input.getDigitalActionData(self.a_grab, h)
                a = self.input.getAnalogActionData(self.a_size, h)
                held = bool(d.bActive and d.bState)
                out.append((held, held and bool(d.bChanged), (not held) and bool(d.bChanged), float(a.y) if a.bActive else 0.0))
            except Exception:  # noqa: BLE001
                out.append((False, False, False, 0.0))
        return out

    # ---- where it is ----

    def _settings(self):
        return self.backend.settings["wrist"]

    def _device(self, attach):
        o = self.openvr
        if attach == "head":
            return o.k_unTrackedDeviceIndex_Hmd
        if attach in ("left", "right"):
            role = o.TrackedControllerRole_LeftHand if attach == "left" else o.TrackedControllerRole_RightHand
            return self.vr.getTrackedDeviceIndexForControllerRole(role)
        return None

    def _offset(self, attach, poses=None):
        off = self._settings()["offsets"].get(attach)
        if off is not None:
            return np.array(off, float)
        if attach == "room" and poses is not None:  # first time: in front of you, facing you
            H = self._pose(poses, self.openvr.k_unTrackedDeviceIndex_Hmd)
            if H is not None:
                fwd = -H[:3, 2]
                fwd[1] = 0
                fwd /= max(np.linalg.norm(fwd), 1e-6)
                z = -fwd
                y = np.array([0.0, 1.0, 0.0])
                x = np.cross(y, z)
                T = np.eye(4)
                T[:3, 0], T[:3, 1], T[:3, 2] = x, y, z
                T[:3, 3] = H[:3, 3] + 0.6 * fwd - np.array([0, 0.25, 0])
                return T
        return default_offset(attach)

    def _pose(self, poses, idx):
        o = self.openvr
        if idx is None or idx == o.k_unTrackedDeviceIndexInvalid:
            return None
        p = poses[idx]
        if not p.bPoseIsValid:
            return None
        return m44(p.mDeviceToAbsoluteTracking)

    def _place(self, attach, T, idx):
        key = (attach, T.round(4).tobytes(), idx)
        if key == self.placed:
            return
        self.placed = key
        o = self.openvr
        if attach == "room":
            self.ov.setOverlayTransformAbsolute(self.handle, o.TrackingUniverseStanding, m34(o, T))
        elif idx is not None and idx != o.k_unTrackedDeviceIndexInvalid:
            self.ov.setOverlayTransformTrackedDeviceRelative(self.handle, idx, m34(o, T))

    def apply(self):
        """Settings changed (or first time): size and position."""
        w = self._settings()
        if self.grab is None and w["width_m"] != self.width:
            self.width = w["width_m"]
            self.ov.setOverlayWidthInMeters(self.handle, float(self.width))
        self.placed = None
        self.panel.dirty = True

    # ---- every tick ----

    def tick(self, now):
        w = self._settings()
        dt, self.last_tick = now - self.last_tick, now
        o = self.openvr
        poses = self.vr.getDeviceToAbsoluteTrackingPose(o.TrackingUniverseStanding, 0, o.k_unMaxTrackedDeviceCount)
        attach = w["attach"]
        idx = self._device(attach)
        A = self._pose(poses, idx) if attach != "room" else np.eye(4)
        hands = [self._pose(poses, self._device(h)) for h in ("left", "right")]
        btn = self._buttons()

        if self.grab is not None:
            g = self.grab
            held, _, released, stick = btn[g["hand"]]
            H = hands[g["hand"]]
            if abs(stick) > 0.2:  # resize while holding
                self.width = float(min(0.40, max(0.06, self.width * math.exp(1.2 * stick * dt))))
                self.ov.setOverlayWidthInMeters(self.handle, self.width)
            if not held or H is None:
                if H is not None:
                    world = H @ g["rel"]
                    off = world if attach == "room" else (np.linalg.inv(A) @ world if A is not None else None)
                    if off is not None:
                        self.backend.setSetting(f"wrist.offsets.{attach}", off.round(5).tolist())
                self.backend.setSetting("wrist.width_m", round(self.width, 3))
                self.grab = None
                self.panel.root.setProperty("grabbed", False)
                self.panel.dirty = True
                self.placed = None
            T_world = (H @ g["rel"]) if H is not None else None
        else:
            off = self._offset(attach, poses)
            if attach == "room" and attach not in w["offsets"]:
                self.backend.setSetting("wrist.offsets.room", off.round(5).tolist())
            self._place(attach, off, idx)
            T_world = off if attach == "room" else (A @ off if A is not None else None)
            # grab: the other hand's grip, close to it
            if not w["locked"] and T_world is not None and self.alpha > 0.3:
                for k, (held, pressed, _, _) in enumerate(btn):
                    if not pressed or hands[k] is None or attach == ("left", "right")[k]:
                        continue
                    if np.linalg.norm(hands[k][:3, 3] - T_world[:3, 3]) < 0.10 + self.width / 2:
                        rel = np.linalg.inv(hands[k]) @ T_world
                        self.grab = {"hand": k, "rel": rel}
                        self.ov.setOverlayTransformTrackedDeviceRelative(self.handle, self._device(("left", "right")[k]),
                                                                         m34(o, rel))
                        self.placed = ("grab",)
                        self.panel.root.setProperty("grabbed", True)
                        self.panel.dirty = True
                        break

        self._arrow(attach, T_world, now)

        # fade unless you look at it (never while you hold it)
        Hm = self._pose(poses, o.k_unTrackedDeviceIndex_Hmd)
        if self.grab is not None:
            alpha = 1.0
        elif T_world is None or Hm is None:
            alpha = 0.0
        else:
            alpha = fade_alpha(T_world, Hm, float(w["fade_angle"]), bool(w["fade"]))
        self._set_alpha(alpha)
        if self.shown and (self.panel.dirty or now - self.last_frame > 5.0) and now - self.last_frame > 0.1:
            self._upload(now)

    def _arrow(self, attach, T_world, now):
        """On a wrist or in the room, the arrow points to the cat from the widget, the way the widget
        points (in your view it stays the way your head faces, from the app's status)."""
        hand = attach != "head" or self.grab is not None
        angle = None
        if hand and T_world is not None and self.shown:
            cat = ((self.backend._status or {}).get("cat") or {}).get("pos_raw")
            if cat is not None:
                if self.raw_to_std is None or now - self.raw_to_std[0] > 2.0:  # moves only if you recentre
                    self.raw_to_std = (now, m44(self.vr.getRawZeroPoseToStandingAbsoluteTrackingPose()))
                R = self.raw_to_std[1]
                angle = arrow_angle(T_world, R[:3, :3] @ np.asarray(cat, float) + R[:3, 3])
        new = (hand, None if angle is None else float(round(angle)))
        old = self.hand_angle
        if old is not None and new[0] == old[0] and new[1] is not None and old[1] is not None \
                and abs((new[1] - old[1] + 180) % 360 - 180) <= 3:
            return  # hardly moved: don't redraw for it
        if new != old:
            self.hand_angle = new
            root = self.panel.root
            root.setProperty("handMode", hand)
            root.setProperty("handAngle", -1000.0 if new[1] is None else new[1])  # -1000: no arrow
            self.panel.dirty = True

    def _set_alpha(self, a):
        if a <= 0.02:
            if self.shown:
                self.ov.hideOverlay(self.handle)
                self.shown = False
            self.alpha = 0.0
            return
        if abs(a - self.alpha) > 0.03 or a == 1.0 and self.alpha != 1.0:
            self.ov.setOverlayAlpha(self.handle, float(a))
            self.alpha = a
        if not self.shown:
            self.ov.showOverlay(self.handle)
            self.shown = True
            self.panel.dirty = True

    def _upload(self, now):
        import ctypes
        o = self.openvr
        img = self.panel.render()
        self.last_frame = now
        if self.mode == "d3d11":
            try:
                if self.d3d is None:
                    from cat_app.d3d11_texture import D3D11Texture
                    self.d3d = D3D11Texture(img.width(), img.height(), self.vr.getDXGIOutputInfo())
                pixels = (ctypes.c_char * img.sizeInBytes()).from_buffer(img.bits())
                self.d3d.upload(ctypes.addressof(pixels), img.bytesPerLine())
                del pixels
                tex = o.Texture_t()
                tex.handle = self.d3d.handle
                tex.eType = o.TextureType_DirectX
                tex.eColorSpace = o.ColorSpace_Auto
                self.ov.setOverlayTexture(self.handle, tex)
                return
            except Exception as e:  # noqa: BLE001
                self.log(f"Wrist widget: Direct3D 11 texture didn't work ({describe(e)}); using a picture file")
                self.mode = "file"
                self._close_d3d()
        self.picture.send(self.ov, self.handle, img)

    def set_mode(self, mode):
        self.mode = mode
        if mode == "file":
            self._close_d3d()
        self.picture.forget()
        self.panel.dirty = True

    def _close_d3d(self):
        if self.d3d is not None:
            try:
                self.d3d.close()
            except Exception:  # noqa: BLE001
                pass
            self.d3d = None

    def close(self):
        try:
            self.ov.destroyOverlay(self.handle)
        except Exception:  # noqa: BLE001
            pass
        self._close_d3d()
        self.panel.close()
        self.panel.deleteLater()
