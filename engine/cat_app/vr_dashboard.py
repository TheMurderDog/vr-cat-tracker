"""The SteamVR dashboard tab.

VrPanel.qml is drawn off screen with Qt Quick, copied into a SteamVR dashboard overlay, and SteamVR's
own laser pointer works on it: SteamVR sends the laser's position and trigger clicks as mouse events,
and they are passed to the Qt Quick scene as mouse moves and clicks. So it behaves like SteamVR's
desktop view: point, pull the trigger. No touching.

If SteamVR isn't running, this waits and connects when it starts. If SteamVR closes, the tab goes
away and the desktop window carries on (started in the background, the app closes too).
"""

import ctypes
import hashlib
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import QImage, QMouseEvent, QWheelEvent
from PySide6.QtQml import QQmlComponent
from PySide6.QtQuick import QQuickWindow

from core.config import resolve_path

W, H = 1280, 800
TMP = resolve_path("my_data/app/vr_tab")
APP_KEY = "camera_core.cat_tracker_app"  # the app's SteamVR app key (cat_tracker.install_autostart registers it)
KEY = APP_KEY + ".tab"                  # the dashboard tab's overlay key


def describe(e):
    """One line about an error. pyopenvr's errors have no message, only a class name (OverlayError_InvalidHandle
    and the like), so this names the class, the code and where it came from."""
    text = f"{type(e).__name__}"
    if getattr(e, "error_value", None) is not None:
        text += f" ({int(e.error_value)})"
    if str(e):
        text += f": {e}"
    tb = traceback.extract_tb(e.__traceback__)
    if tb:
        text += f", in {Path(tb[-1].filename).name} line {tb[-1].lineno} ({tb[-1].name})"
    return text


class Repeats:
    """Logs a problem that comes back every update once, with its traceback, then a count at most once a
    minute while it continues, and a line when it stops."""

    def __init__(self, log, what, every_s=60.0):
        self.log, self.what, self.every_s = log, what, every_s
        self.key = None
        self.count = 0
        self.since = 0.0

    def failed(self, e):
        key, now = describe(e), time.monotonic()
        if key != self.key:
            self.ok()
            self.key, self.count, self.since = key, 0, now
            self.log(f"{self.what}: {key}\n" + "".join(traceback.format_exception(e)).rstrip())
            return
        self.count += 1
        if now - self.since >= self.every_s:
            self.log(f"{self.what}: {key} (again {self.count} times in the last {now - self.since:.0f} s)")
            self.count, self.since = 0, now

    def ok(self):
        if self.key is not None:
            if self.count:
                self.log(f"{self.what}: {self.key} (again {self.count} times)")
            self.log(f"{self.what}: working again")
            self.key, self.count = None, 0


class PictureFile:
    """Picture mode (--vr-mode file): SteamVR loads each picture from a file, and the overlay blinks a little
    every time it does. So this skips a picture that looks exactly like the last one sent, and takes turns
    between two files, so a new picture is never written over the one SteamVR may still be reading."""

    def __init__(self, name):
        self.name = name
        self.last = None
        self.turn = 0

    def forget(self):
        """Call when the overlay is new (or was emptied), so the next picture is sent even if it's the same."""
        self.last = None

    def send(self, ov, handle, img):
        """Returns True if a new picture went to SteamVR, False if it was the same as the last one."""
        digest = hashlib.blake2b(img.constBits(), digest_size=16).digest()
        if digest == self.last:
            return False
        TMP.mkdir(parents=True, exist_ok=True)
        p = TMP / f"{self.name}_{self.turn}.png"
        img.save(str(p), "PNG", 1)
        ov.setOverlayFromFile(handle, str(p))
        self.last = digest
        self.turn ^= 1
        return True


class OffscreenQml(QObject):
    """A QML scene in a window that is never shown, drawn by Qt's software renderer into an image, with
    mouse events fed in by hand. No OpenGL and no graphics-card work at all in this process for the tab:
    the only thing that touches the graphics driver is the one Direct3D 11 texture handed to SteamVR."""

    def __init__(self, engine, qml_path, parent=None, backend=None, size=(W, H)):
        super().__init__(parent)
        self.w, self.h = size
        self.win = QQuickWindow()
        self.win.setGeometry(0, 0, self.w, self.h)
        self.comp = QQmlComponent(engine, QUrl.fromLocalFile(str(qml_path)))
        self.root = self.comp.create()
        if self.root is None:
            raise RuntimeError(f"{Path(str(qml_path)).name}: " + "; ".join(e.toString() for e in self.comp.errors()))
        self.root.setParentItem(self.win.contentItem())
        self.root.setWidth(self.w)
        self.root.setHeight(self.h)
        self.dirty = True
        self.busy_until = 0.0  # after a click or hover, keep redrawing briefly for the button's feedback
        # picture mode (calm): every new picture makes SteamVR blink, so pointing alone changes nothing (no hover
        # highlight) and a click is drawn once, after it has settled, instead of for the press and the release
        self.calm = False
        self.settle_at = 0.0
        if backend is not None:
            backend.statusChanged.connect(self._mark)
            backend.styleChanged.connect(self._mark)
            backend.settingsChanged.connect(self._mark)
            backend.heatChanged.connect(self._mark)
            backend.frameChanged.connect(self._mark)    # the Cameras page
            backend.messageChanged.connect(self._mark)
            backend.feetChanged.connect(self._mark)
        self.buttons = Qt.MouseButton.NoButton
        self.last = QPointF(0, 0)

    def _mark(self):
        self.dirty = True

    def needs_frame(self, now):
        if self.calm:
            return self.dirty and now >= self.settle_at
        return self.dirty or now < self.busy_until

    def render(self):
        """The current picture as a QImage in Qt's own 32-bit format (BGRA bytes, top row first). Qt's
        software renderer already draws in this format, so this is normally no extra work."""
        self.dirty = False
        return self.win.grabWindow().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    # ---- input ----
    def mouse(self, kind, x, y, button=Qt.MouseButton.LeftButton):
        p = QPointF(x, y)
        self.last = p
        if kind == "move" and self.calm and self.buttons == Qt.MouseButton.NoButton:
            return  # just pointing: SteamVR draws the laser dot; a hover highlight would only cost a blink
        if kind == "move":
            ev = QMouseEvent(QEvent.Type.MouseMove, p, p, Qt.MouseButton.NoButton, self.buttons, Qt.KeyboardModifier.NoModifier)
        elif kind == "down":
            self.buttons = self.buttons | button
            ev = QMouseEvent(QEvent.Type.MouseButtonPress, p, p, button, self.buttons, Qt.KeyboardModifier.NoModifier)
        else:
            self.buttons = self.buttons & ~button
            ev = QMouseEvent(QEvent.Type.MouseButtonRelease, p, p, button, self.buttons, Qt.KeyboardModifier.NoModifier)
        QCoreApplication.sendEvent(self.win, ev)
        self.dirty = True
        self.busy_until = time.monotonic() + 0.3
        self.settle_at = time.monotonic() + 0.25

    def leave(self):
        QCoreApplication.sendEvent(self.win, QEvent(QEvent.Type.Leave))
        self.mouse("move", -100, -100)

    def wheel(self, dx, dy):
        ev = QWheelEvent(self.last, self.last, QPoint(0, 0), QPoint(int(dx * 120), int(dy * 120)),
                         self.buttons, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
        QCoreApplication.sendEvent(self.win, ev)
        self.dirty = True

    def close(self):
        try:
            self.root.deleteLater()
            self.win.deleteLater()
        except Exception:  # noqa: BLE001
            pass


class VrDashboard(QObject):
    def __init__(self, engine, qml_path, icon_path, log, parent=None, mode="d3d11", backend=None, optimize=True,
                 quit_with_steamvr=False):
        super().__init__(parent)
        self.log = log
        self.quit_with_steamvr = quit_with_steamvr
        self.icon = str(icon_path)
        self.engine, self.qml_path = engine, qml_path
        self.backend = backend
        self.optimize = optimize
        # the off-screen VR tab (a hidden Qt Quick scene) is only made once SteamVR is there; without --no-optimize, it is dropped again when SteamVR closes
        self.panel = None if optimize else OffscreenQml(engine, qml_path, self, backend)
        self.vr = None
        self.ov = None
        self.handle = self.thumb = None
        self.last_frame = 0.0
        self.was_visible = False
        # How the tab's picture reaches SteamVR (--vr-mode):
        #   d3d11  (default) a Direct3D 11 texture, like other overlay apps; falls back to "file" if it fails
        #   file   a picture file SteamVR loads, at most 4 times a second and only when it changed (see PictureFile)
        self.mode = mode
        self.mode_setting = backend.settings.get("vr_mode") if backend is not None else None
        self.d3d = None
        self.picture = PictureFile("vr_tab")
        self.flip_y = True  # SteamVR's overlay mouse y counts up from the bottom
        self.connect_timer = QTimer(self, interval=5000, timeout=self.try_connect)
        self.pump = QTimer(self, interval=11, timeout=self.tick)
        self.no_openvr = False
        self.wrist = None
        self.tab_errors = Repeats(log, "Couldn't update the SteamVR tab")
        self.wrist_errors = Repeats(log, "Wrist widget problem")
        if backend is not None:
            backend.settingsChanged.connect(self._settings_changed)
        self.try_connect()
        if not self.no_openvr:
            self.connect_timer.start()

    @property
    def connected(self):
        return self.vr is not None

    def try_connect(self):
        if self.vr is not None:
            return
        try:
            import openvr
        except ImportError as e:
            self.log(f"openvr isn't installed ({e}); no SteamVR tab")
            self.no_openvr = True
            self.connect_timer.stop()
            return
        try:
            if not openvr.isRuntimeInstalled() or not openvr.isHmdPresent():
                return
            self.openvr = openvr
            self.vr = openvr.init(openvr.VRApplication_Overlay)
        except Exception:  # noqa: BLE001 - SteamVR not running yet: try again later
            self.vr = None
            return
        try:
            ov = openvr.VROverlay()
            self.ov = ov
            if self.panel is None:
                self.panel = OffscreenQml(self.engine, self.qml_path, self, self.backend)
            self.handle, self.thumb = ov.createDashboardOverlay(KEY, "Cat Tracker")
            ov.setOverlayWidthInMeters(self.handle, 2.4)
            ov.setOverlayInputMethod(self.handle, openvr.VROverlayInputMethod_Mouse)
            scale = openvr.HmdVector2_t()
            scale.v[0], scale.v[1] = W, H
            ov.setOverlayMouseScale(self.handle, scale)
            ov.setOverlayFlag(self.handle, openvr.VROverlayFlags_SendVRSmoothScrollEvents, True)
            ov.setOverlayFromFile(self.thumb, self.icon)
            self.panel.dirty = True
            self.picture.forget()
            self._upload()
            self.pump.start()
            self.log("Connected to SteamVR: the Cat Tracker tab is in the dashboard")
            self._settings_changed()
        except Exception as e:  # noqa: BLE001
            self.log(f"Couldn't add the SteamVR dashboard tab: {describe(e)}")
            self.disconnect()

    def _settings_changed(self):
        """The wrist widget comes and goes with its On/Off setting, and picture mode switches straight away."""
        if self.backend is None:
            return
        want = self.backend.settings.get("vr_mode")
        if want != self.mode_setting:  # only when the setting itself changes (not after falling back to "file")
            self.mode_setting = want
            self.set_mode(want)
        if self.vr is None:
            return
        on = bool(self.backend.settings["wrist"]["on"])
        if on and self.wrist is None:
            try:
                from cat_app.wrist import WristWidget
                self.wrist = WristWidget(self, self.openvr, self.vr, self.ov, self.engine, self.backend, self.log)
                self.log("Wrist widget on")
            except Exception as e:  # noqa: BLE001
                self.log(f"Couldn't make the wrist widget: {describe(e)}")
                self.wrist = None
        elif not on and self.wrist is not None:
            self.wrist.close()
            self.wrist = None
        elif self.wrist is not None:
            self.wrist.apply()
        self._set_visible(self.was_visible)

    def set_mode(self, mode):
        """Switch how the pictures reach SteamVR while running: "d3d11" or "file" (see __init__)."""
        if mode not in ("d3d11", "file") or mode == self.mode:
            return
        self.log(f"SteamVR pictures: {mode}" + (" (no graphics card use by the app)" if mode == "file" else ""))
        self.mode = mode
        if mode == "file":
            self._close_d3d()
        self.picture.forget()  # the next picture goes to SteamVR even if it looks the same
        self.last_frame = 0.0
        if self.panel is not None:
            self.panel.dirty = True
        if self.wrist is not None:
            self.wrist.set_mode(mode)

    def disconnect(self):
        self.pump.stop()
        if self.wrist is not None:
            try:
                self.wrist.close()
            except Exception:  # noqa: BLE001
                pass
            self.wrist = None
        try:
            if self.ov is not None and self.handle is not None:
                self.ov.destroyOverlay(self.handle)
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.vr is not None:
                self.openvr.shutdown()
        except Exception:  # noqa: BLE001
            pass
        self.vr = self.ov = self.handle = self.thumb = None
        self._close_d3d()
        self._set_visible(False)
        if self.optimize and self.panel is not None:
            self.panel.close()
            self.panel.deleteLater()
            self.panel = None

    def _visible(self):
        try:
            return self.ov.isDashboardVisible() and self.ov.isActiveDashboardOverlay(self.handle)
        except Exception:  # noqa: BLE001
            return False

    def _upload(self):
        """Hands the tab's picture to SteamVR, the way --vr-mode says (see __init__). The very first version
        sent 4 MB of raw pixels per update between programs, which made SteamVR flicker and, with a struggling
        graphics driver, took the whole PC down; none of these modes do that."""
        openvr = self.openvr
        if self.mode == "d3d11":
            try:
                img = self.panel.render()
                if self.d3d is None:
                    from cat_app.d3d11_texture import D3D11Texture
                    self.d3d = D3D11Texture(img.width(), img.height(), self.vr.getDXGIOutputInfo())
                    self.log(f"SteamVR tab: Direct3D 11 texture on {self.d3d.adapter_name} (the card SteamVR uses)")
                pixels = (ctypes.c_char * img.sizeInBytes()).from_buffer(img.bits())  # Qt's memory, not a copy
                self.d3d.upload(ctypes.addressof(pixels), img.bytesPerLine())
                del pixels
                tex = openvr.Texture_t()
                tex.handle = self.d3d.handle
                tex.eType = openvr.TextureType_DirectX
                tex.eColorSpace = openvr.ColorSpace_Auto
                self.ov.setOverlayTexture(self.handle, tex)
                self.last_frame = time.monotonic()
                return True
            except Exception as e:  # noqa: BLE001
                self.log(f"Direct3D 11 texture didn't work ({describe(e)}); using a picture file instead")
                self.mode = "file"
                self._close_d3d()
        if time.monotonic() - self.last_frame < 0.25:
            return False
        img = self.panel.render()
        self.last_frame = time.monotonic()
        return self.picture.send(self.ov, self.handle, img)

    def _close_d3d(self):
        if self.d3d is not None:
            try:
                self.d3d.close()
            except Exception:  # noqa: BLE001
                pass
            self.d3d = None

    def tick(self):
        openvr = self.openvr
        ev = openvr.VREvent_t()
        try:
            while self.vr.pollNextEvent(ev):
                if ev.eventType == openvr.VREvent_Quit:
                    try:
                        self.vr.acknowledgeQuit_Exiting()
                    except Exception:  # noqa: BLE001
                        pass
                    self.disconnect()
                    if self.quit_with_steamvr:
                        self.log("SteamVR is closing: closing too")
                        QCoreApplication.quit()
                    else:
                        self.log("SteamVR is closing: the tab is gone until it starts again")
                    return
            for _ in range(64):  # never more than this per tick, so the window can't get stuck here
                # pyopenvr returns (has_event, event) here, unlike pollNextEvent's plain True/False
                if not self.ov.pollNextOverlayEvent(self.handle, ev)[0]:
                    break
                t = ev.eventType
                if t in (openvr.VREvent_MouseMove, openvr.VREvent_MouseButtonDown, openvr.VREvent_MouseButtonUp):
                    x = ev.data.mouse.x
                    y = H - ev.data.mouse.y if self.flip_y else ev.data.mouse.y
                    kind = {openvr.VREvent_MouseMove: "move", openvr.VREvent_MouseButtonDown: "down"}.get(t, "up")
                    self.panel.mouse(kind, x, y)
                elif t == openvr.VREvent_ScrollSmooth:
                    self.panel.wheel(ev.data.scroll.xdelta, ev.data.scroll.ydelta)
                elif t in (openvr.VREvent_FocusLeave, openvr.VREvent_OverlayFocusChanged):
                    self.panel.leave()
        except Exception as e:  # noqa: BLE001
            self.log(f"Lost SteamVR ({describe(e)}); trying to reconnect")
            self.disconnect()
            return
        # draw only while the tab is open, at most 20 times a second, and only when something changed
        vis = self._visible()
        now = time.monotonic()
        # while open: redraw only when something changed (at most 20 a second), plus every 0.3 s while the
        # status banner blinks (only for a warning, or while the tracker starts)
        blinking = self.backend is not None and (self.backend.level == "alert" or self.backend.starting) \
            and self.mode != "file"  # in picture mode the banner stays still: each blink would be a reload
        self.panel.calm = self.mode == "file"
        if vis and (self.panel.needs_frame(now) or not self.was_visible or (blinking and now - self.last_frame > 0.3)) \
                and now - self.last_frame > 1 / 20:
            try:
                t0 = time.perf_counter()
                if self._upload() and self.backend is not None:
                    self.backend.meter.count("vr tab frames")
                    self.backend.meter.timed("vr tab frame", time.perf_counter() - t0)
                self.tab_errors.ok()
            except Exception as e:  # noqa: BLE001
                self.tab_errors.failed(e)
        if self.wrist is not None:
            try:
                t0 = time.perf_counter()
                self.wrist.tick(now)
                if self.backend is not None:
                    self.backend.meter.timed("wrist widget tick", time.perf_counter() - t0)
                self.wrist_errors.ok()
            except Exception as e:  # noqa: BLE001
                self.wrist_errors.failed(e)
        self._set_visible(vis)

    def _set_visible(self, vis):
        """Laser events need a quick check (90 a second) only while the tab is open; otherwise 4 a second
        is plenty to notice it opening (or SteamVR closing)."""
        self.was_visible = vis
        if self.backend is not None:
            self.backend.setVrVisible(vis)
        if self.optimize:
            grabbing = self.wrist is not None and self.wrist.grab is not None
            want = 11 if vis or grabbing else 33 if self.wrist is not None else 250
            if self.pump.interval() != want:
                self.pump.setInterval(want)

    def close(self):
        self.connect_timer.stop()
        self.disconnect()
        if self.panel is not None:
            self.panel.close()


def render_preview(engine, qml_path, out_path):
    """Saves a picture of the VR tab (for checking the layout without a headset)."""
    p = OffscreenQml(engine, qml_path)
    for _ in range(3):
        QCoreApplication.processEvents()
        img = p.render()
    img.save(str(out_path))
    p.close()
    return Path(out_path)
