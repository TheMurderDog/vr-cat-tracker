import QtQuick
import QtQuick.Layouts

// How the VR tab and wrist widget reach SteamVR: on the graphics card, or as picture files (picture mode,
// no graphics card use by the app). Switches straight away. Used on the desktop and (bigger) in the VR tab.
ColumnLayout {
    id: pp
    property real size: 1.0
    readonly property bool picture: backend.settings.vr_mode === "file"
    spacing: 10 * size
    Segmented { Layout.fillWidth: true; size: pp.size; label: "Mode"
                options: [["d3d11", "Graphics card"], ["file", "Picture mode"]]; current: backend.settings.vr_mode
                onPicked: function(v) { backend.setSetting("vr_mode", v) } }
    Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 17 * pp.size
           text: pp.picture
                 ? "Picture mode: SteamVR loads the VR tab and wrist widget from picture files, and the app itself uses no graphics card. "
                   + "A button can blink once after you click it, and the cameras' live view updates a few times a second."
                 : "Graphics card: the VR tab and wrist widget go to SteamVR on your graphics card, like other overlay apps. Smoother." }
    Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 15 * pp.size
           text: "If your PC crashes or freezes while you play, try picture mode. More tips: \"If your PC crashes\" in "
                 + "5_play_in_vr\\README.md. The tracker's cat detection is separate and stays on the graphics card." }
}
