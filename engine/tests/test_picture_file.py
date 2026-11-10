"""Picture mode (--vr-mode file) sends SteamVR a new picture only when it changed, and takes turns between two
files. Run from engine/: python tests/test_picture_file.py (no SteamVR needed)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QColor, QGuiApplication, QImage  # noqa: E402

import cat_app.vr_dashboard as dash  # noqa: E402


class FakeOverlay:
    def __init__(self):
        self.sent = []

    def setOverlayFromFile(self, handle, path):
        assert Path(path).is_file(), "the picture is written before SteamVR is told about it"
        self.sent.append(Path(path).name)


def picture(color):
    img = QImage(64, 40, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(color))
    return img


def main():
    app = QGuiApplication.instance() or QGuiApplication(["test", "-platform", "offscreen"])  # noqa: F841
    dash.TMP = Path(tempfile.mkdtemp())
    ov, pic = FakeOverlay(), dash.PictureFile("vr_tab")
    assert pic.send(ov, 1, picture("red"))
    assert not pic.send(ov, 1, picture("red")), "the same picture again is skipped"
    assert pic.send(ov, 1, picture("blue"))
    assert pic.send(ov, 1, picture("red"))
    assert ov.sent == ["vr_tab_0.png", "vr_tab_1.png", "vr_tab_0.png"], ov.sent
    pic.forget()  # a new overlay: send it even though it looks the same
    assert pic.send(ov, 1, picture("red"))
    print("ok")


if __name__ == "__main__":
    main()
