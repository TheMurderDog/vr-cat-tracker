"""SteamVR side: the headset pose, the raw-to-standing transform, and the cat's overlays.

Why raw space: play space tools (OVR Advanced Settings and the like) move SteamVR's standing space
around the real room, but raw tracking space stays fixed to the base stations, like the cameras.
The cat's position is kept in raw space and converted to the current standing space every update,
so dragging or turning the play space never moves its marker away from the real cat.
SteamVR must already be running; this attaches to it as an overlay app and never launches it.
"""

import math
import threading
import time

import numpy as np
import openvr

RAW = openvr.TrackingUniverseRawAndUncalibrated
STANDING = openvr.TrackingUniverseStanding


def _m44(m34):
    m = np.eye(4)
    m[:3, :4] = np.ctypeslib.as_array(m34.m)
    return m


def _m34(T):
    m = openvr.HmdMatrix34_t()
    for i in range(3):
        for j in range(4):
            m.m[i][j] = float(T[i, j])
    return m


class VRLink:
    def __init__(self):
        self.sys = openvr.init(openvr.VRApplication_Overlay)
        self.ov = openvr.VROverlay()
        self.overlays = {}
        self.input = None

    def quit_requested(self):
        """True once SteamVR asks overlay apps to close (it's shutting down)."""
        ev = openvr.VREvent_t()
        while self.sys.pollNextEvent(ev):
            if ev.eventType == openvr.VREvent_Quit:
                try:
                    self.sys.acknowledgeQuit_Exiting()
                except Exception:  # noqa: BLE001
                    pass
                return True
        return False

    # ---- controller vibration -------------------------------------------------

    def setup_haptics(self, manifest_path, log=None):
        """SteamVR Input: one vibration output (/actions/cat/out/buzz), bound to both hands by
        input/bindings_*.json. Falls back to the old per-device pulse if SteamVR Input won't take it."""
        try:
            inp = openvr.VRInput()
            inp.setActionManifestPath(str(manifest_path))
            self.aset = inp.getActionSetHandle("/actions/cat")
            self.buzz_action = inp.getActionHandle("/actions/cat/out/buzz")
            self.hands = [inp.getInputSourceHandle(p) for p in ("/user/hand/left", "/user/hand/right")]
            self.active = (openvr.VRActiveActionSet_t * 1)()
            self.active[0].ulActionSet = self.aset
            self.input = inp
        except Exception as e:  # noqa: BLE001
            self.input = None
            if log:
                log.warning("SteamVR Input not available for vibration (%s); using the older controller pulse", e)

    def update_input(self):
        """Keeps the action set active; call every update."""
        if self.input is not None:
            try:
                self.input.updateActionState(self.active)
            except Exception:  # noqa: BLE001
                pass

    def buzz_pattern(self, hands="LRLR", total_s=1.0, pulse_s=0.15, amplitude=0.6):
        """One short pulse per letter (L or R), spread evenly over total_s, played in the background so
        the tracker carries on meanwhile. For getting your attention once, not a constant buzz."""
        step = total_s / max(1, len(hands))

        def play():
            for k, hand in enumerate(hands):
                if k:
                    time.sleep(step)
                self.buzz(pulse_s, amplitude, hand=0 if hand.upper() == "L" else 1)

        threading.Thread(target=play, name="buzz", daemon=True).start()

    def buzz(self, seconds=0.15, amplitude=0.6, frequency=120.0, hand=None):
        """Vibrate both controllers, or one: hand 0 = left, 1 = right."""
        if self.input is not None:
            for h in (self.hands if hand is None else [self.hands[hand]]):
                try:
                    self.input.triggerHapticVibrationAction(self.buzz_action, 0.0, seconds, frequency, amplitude, h)
                except Exception:  # noqa: BLE001
                    pass
            return
        roles = (openvr.TrackedControllerRole_LeftHand, openvr.TrackedControllerRole_RightHand)
        for role in (roles if hand is None else [roles[hand]]):
            i = self.sys.getTrackedDeviceIndexForControllerRole(role)
            if i != openvr.k_unTrackedDeviceIndexInvalid:
                self.sys.triggerHapticPulse(i, 0, min(int(seconds * 1e6), 3999))  # the old API caps a pulse at ~4 ms

    def headset(self, universe=RAW):
        """4x4 headset pose in the given universe, or None if it isn't tracking."""
        p = self.sys.getDeviceToAbsoluteTrackingPose(universe, 0, openvr.k_unMaxTrackedDeviceCount)[
            openvr.k_unTrackedDeviceIndex_Hmd]
        if not (p.bPoseIsValid and p.eTrackingResult == openvr.TrackingResult_Running_OK):
            return None
        return _m44(p.mDeviceToAbsoluteTracking)

    def worn(self):
        """True while the headset's proximity sensor says it's on someone's head."""
        try:
            return self.sys.getTrackedDeviceActivityLevel(openvr.k_unTrackedDeviceIndex_Hmd) == \
                openvr.k_EDeviceActivityLevel_UserInteraction
        except Exception:  # noqa: BLE001
            return True

    def universe_id(self):
        """SteamVR's id for the base station map raw space comes from, or None. It changes when SteamVR
        builds a new map (base stations moved or swapped), which moves raw space; room setup doesn't."""
        try:
            u = self.sys.getUint64TrackedDeviceProperty(openvr.k_unTrackedDeviceIndex_Hmd,
                                                        openvr.Prop_CurrentUniverseId_Uint64)
        except Exception:  # noqa: BLE001
            return None
        return int(u) or None

    def raw_to_standing(self):
        """4x4 that takes raw-space points to the current standing space (changes when the play space moves)."""
        return _m44(self.sys.getRawZeroPoseToStandingAbsoluteTrackingPose())

    # ---- overlays -----------------------------------------------------------

    def add_overlay(self, name, image_path, width_m):
        h = self.ov.createOverlay(f"cat_tracker.{name}", f"Cat tracker {name}")
        self.ov.setOverlayFromFile(h, str(image_path))
        self.ov.setOverlayWidthInMeters(h, float(width_m))
        self.ov.hideOverlay(h)
        self.overlays[name] = {"h": h, "image": str(image_path), "shown": False}
        return h

    def set_image(self, name, image_path):
        o = self.overlays[name]
        if o["image"] != str(image_path):
            self.ov.setOverlayFromFile(o["h"], str(image_path))
            o["image"] = str(image_path)

    def place(self, name, T_standing, alpha):
        """Show overlay `name` at a 4x4 pose in current standing space, or hide it when alpha is 0."""
        o = self.overlays[name]
        if alpha <= 0:
            if o["shown"]:
                self.ov.hideOverlay(o["h"])
                o["shown"] = False
            return
        self.ov.setOverlayTransformAbsolute(o["h"], STANDING, _m34(T_standing))
        self.ov.setOverlayAlpha(o["h"], float(min(1.0, alpha)))
        if not o["shown"]:
            self.ov.showOverlay(o["h"])
            o["shown"] = True

    def place_on_head(self, name, T_head, alpha):
        """Show overlay `name` at a 4x4 pose relative to the headset (it moves with your head), or hide it."""
        o = self.overlays[name]
        if alpha <= 0:
            if o["shown"]:
                self.ov.hideOverlay(o["h"])
                o["shown"] = False
            return
        self.ov.setOverlayTransformTrackedDeviceRelative(o["h"], openvr.k_unTrackedDeviceIndex_Hmd, _m34(T_head))
        self.ov.setOverlayAlpha(o["h"], float(min(1.0, alpha)))
        if not o["shown"]:
            self.ov.showOverlay(o["h"])
            o["shown"] = True

    def stop(self):
        for o in self.overlays.values():
            try:
                self.ov.destroyOverlay(o["h"])
            except openvr.OpenVRError:
                pass
        openvr.shutdown()


def billboard(pos, look_at):
    """Upright pose at pos whose face (+Z) turns toward look_at around the vertical only."""
    f = np.array([look_at[0] - pos[0], 0.0, look_at[2] - pos[2]])
    n = np.linalg.norm(f)
    z = f / n if n > 1e-6 else np.array([0.0, 0.0, 1.0])
    y = np.array([0.0, 1.0, 0.0])
    x = np.cross(y, z)
    T = np.eye(4)
    T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = x, y, z, pos
    return T


def flat(pos):
    """Pose lying flat on the floor at pos, facing up."""
    T = np.eye(4)
    T[:3, :3] = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]  # quad's +Z (its face) turned to point up
    T[:3, 3] = pos
    return T


def edge_pose(d_head, angle_deg, distance_m):
    """Head-relative pose for an arrow at the edge of view, pointing toward d_head (its direction in the
    headset's frame: +x right, +y up, -z ahead). The arrow image points right (+x) before turning."""
    u = np.array([d_head[0], d_head[1]], float)
    n = np.linalg.norm(u)
    u = u / n if n > 1e-6 else np.array([0.0, -1.0])  # straight ahead or behind: point down, where it would be
    a = math.radians(angle_deg)
    pos = distance_m * np.array([math.sin(a) * u[0], math.sin(a) * u[1], -math.cos(a)])
    z = -pos / np.linalg.norm(pos)  # face the eyes
    x = np.array([u[0], u[1], 0.0])
    x -= x.dot(z) * z
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    T = np.eye(4)
    T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = x, y, z, pos
    return T


def horizontal_distance(a, b):
    return math.hypot(a[0] - b[0], a[2] - b[2])
