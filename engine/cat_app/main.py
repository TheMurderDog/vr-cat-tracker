"""Cat Tracker app: the desktop window, plus a tab in the SteamVR dashboard and an optional wrist widget.

Run from engine (5_play_in_vr\\app\\2_open_app.bat does this):
  python -m cat_app.main                 the window, and the SteamVR tab while SteamVR runs
  python -m cat_app.main --background    no window: only the SteamVR tab, and it closes with SteamVR (how
                                         SteamVR starts it, see cat_tracker.install_autostart)
  python -m cat_app.main --demo          made-up data, to look at the screens without the tracker or SteamVR
  python -m cat_app.main --no-vr         no SteamVR tab
  python -m cat_app.main --vr-picture out.png    save a picture of the SteamVR tab and quit
Only one copy runs: opening it again shows the window of the one already running.
"""

import argparse
import faulthandler
import sys
import threading
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtQuickControls2 import QQuickStyle

from cat_app import link
from cat_app.backend import ASSETS, Backend, Images
from core.config import resolve_path

HERE = Path(__file__).resolve().parent
LOGS = resolve_path("my_data/logs/cat_app")
LOG = LOGS / "app.log"
ICON = ASSETS / "cat.png"


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


class FreezeCheck:
    """If the app stops responding for 4 seconds, writes what every thread was doing to freeze.log."""

    def __init__(self):
        self.beat = time.monotonic()
        self.path = LOGS / "freeze.log"
        threading.Thread(target=self.watch, name="freeze-check", daemon=True).start()

    def tick(self):
        self.beat = time.monotonic()

    def watch(self):
        dumped = False
        while True:
            time.sleep(1.0)
            stuck = time.monotonic() - self.beat
            if stuck > 4 and not dumped:
                dumped = True
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with open(self.path, "a", encoding="utf-8") as f:
                        f.write(f"\n==== {time.strftime('%Y-%m-%d %H:%M:%S')} window not responding for {stuck:.0f} s\n")
                        f.flush()
                        faulthandler.dump_traceback(file=f, all_threads=True)
                    log(f"The app froze for a moment; details in {self.path}")
                except OSError:
                    pass
            elif stuck < 2:
                dumped = False


class OneCopy:
    """Only one copy of the app runs (two would fight over the SteamVR tab). The running one keeps a small
    shared memory block; a second copy writes "show" into it and closes, and the first shows its window."""

    def __init__(self):
        self.block = None
        try:
            self.block = link.Block(link.APP, create=True)
            self.first = True
        except FileExistsError:
            self.first = False

    def ask_to_show(self):
        b = link.open_block(link.APP)
        if b is None:
            return False
        link.write_json(b, {"show": time.time()})
        b.close()
        return True

    def asked(self):
        if self.block is None:
            return False
        seq, data = self.block.read()
        return data is not None and seq > 0  # (0: nobody has written yet)


def main():
    ap = argparse.ArgumentParser(description="Cat Tracker app")
    ap.add_argument("--background", action="store_true",
                    help="no window, only the SteamVR tab; closes when SteamVR does (how SteamVR starts it)")
    ap.add_argument("--demo", action="store_true", help="made-up data, no tracker needed")
    ap.add_argument("--no-vr", action="store_true", help="no SteamVR dashboard tab")
    ap.add_argument("--no-optimize", action="store_true",
                    help="the old, always-busy behaviour (for comparing in perf.log)")
    ap.add_argument("--vr-mode", choices=("d3d11", "file"),
                    help="how the SteamVR tab's picture reaches SteamVR: d3d11 (a GPU texture, like other overlay "
                         "apps) or file; default: vr_mode in my_data/app/app_settings.json (d3d11)")
    ap.add_argument("--vr-picture", help="save a picture of the SteamVR tab to this file and quit")
    ap.add_argument("--window-picture", help="save a picture of the desktop window (each page) and quit")
    args = ap.parse_args()
    one = None
    if not (args.vr_picture or args.window_picture or args.demo):
        one = OneCopy()
        if not one.first:
            if not args.background and one.ask_to_show():
                print("The Cat Tracker app is already running: showing its window")
            return 0

    # Qt's software renderer for the window and the VR tab: a few simple screens don't need the graphics
    # card, and keeping this app off it entirely means it can't upset the graphics driver (both blue
    # screens on 2026-11-04 were inside the NVIDIA driver while the GPU-drawn VR tab was connected)
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)
    QQuickStyle.setStyle("Fusion")
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Cat Tracker")
    app.setWindowIcon(QIcon(str(ICON)))
    app.setQuitOnLastWindowClosed(not args.background)

    freeze = FreezeCheck()
    beat = QTimer(interval=1000, timeout=freeze.tick)
    beat.start()

    backend = Backend()
    backend.demo = args.demo
    backend.optimize = not args.no_optimize
    engine = QQmlApplicationEngine()
    engine.addImageProvider("cat", Images(backend))
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("catIcon", QUrl.fromLocalFile(str(ICON)))
    log("Cat Tracker app starting" + (" in the background (SteamVR tab only)" if args.background else "")
        + (" (demo)" if args.demo else ""))

    if args.vr_picture:
        from cat_app.vr_dashboard import render_preview
        backend.poll()
        render_preview(engine, HERE / "qml" / "VrPanel.qml", args.vr_picture)
        return 0

    from PySide6.QtGui import QWindow
    win = {"w": None}

    def on_visibility(v):
        backend.setDesktopVisible(v not in (QWindow.Visibility.Minimized, QWindow.Visibility.Hidden))

    def show_window():
        """The desktop window (made the first time it's needed: in the background it may never be)."""
        if win["w"] is None:
            engine.load(QUrl.fromLocalFile(str(HERE / "qml" / "Main.qml")))
            if not engine.rootObjects():
                log("The window couldn't be loaded (see the errors above)")
                return None
            win["w"] = engine.rootObjects()[0]
            win["w"].visibilityChanged.connect(on_visibility)
        w = win["w"]
        w.show()
        if w.visibility() == QWindow.Visibility.Minimized:
            w.showNormal()
        w.raise_()
        w.requestActivate()
        return w

    if args.background:
        backend.setDesktopVisible(False)
    elif show_window() is None:
        return 1
    window = win["w"]

    if one is not None:  # another copy asked for the window
        QTimer(app, interval=1000, timeout=lambda: one.asked() and show_window()).start()

    dash = None
    vr_mode = args.vr_mode or backend._settings.get("vr_mode", "d3d11")  # noqa: SLF001
    if not args.no_vr and not args.window_picture:
        log(f"SteamVR pictures: {vr_mode}" + (" (no graphics card use by the app)" if vr_mode == "file" else ""))
        try:
            from cat_app.vr_dashboard import VrDashboard
            dash = VrDashboard(engine, HERE / "qml" / "VrPanel.qml", ICON, log, mode=vr_mode, backend=backend,
                               optimize=not args.no_optimize, quit_with_steamvr=args.background)
        except Exception:  # noqa: BLE001 - the desktop window still works without it
            log("No SteamVR tab:\n" + traceback.format_exc())
    if args.background and dash is None:
        log("Started in the background, but there's no SteamVR tab to show: closing")
        return 1

    if args.window_picture:
        out = Path(args.window_picture)
        pages = [0, 1, 2, 3, 4]

        def shoot():
            if not pages:
                app.quit()
                return
            p = pages.pop(0)
            window.setProperty("page", p)
            QTimer.singleShot(700, lambda p=p: (window.grabWindow().save(str(out.with_name(f"{out.stem}_{p}{out.suffix}"))), shoot()))
        QTimer.singleShot(1200, shoot)

    # every 10 s, what the app costs, into perf.log
    perf_log = LOGS / "perf.log"

    def perf_report():
        where = ("window shown" if backend.desktop_visible else "window minimised") + ", " + \
                ("VR tab open" if backend.vr_visible else "VR tab closed") + ", " + \
                ("tracker connected" if backend.connected else "tracker not connected") + \
                (", OLD behaviour (--no-optimize)" if args.no_optimize else "")
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} app | {where} | {backend.meter.report()}"
        try:
            perf_log.parent.mkdir(parents=True, exist_ok=True)
            with open(perf_log, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
    perf_timer = QTimer(interval=10000, timeout=perf_report)
    perf_timer.start()

    def cleanup():
        if dash is not None:
            dash.close()
        if one is not None and one.block is not None:
            one.block.close()
    app.aboutToQuit.connect(cleanup)
    return app.exec()


if __name__ == "__main__":
    from core.runlog import exit_now
    exit_now(main())
