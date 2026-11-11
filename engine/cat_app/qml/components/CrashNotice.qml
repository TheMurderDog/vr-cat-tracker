import QtQuick
import QtQuick.Layouts

// Shown after the PC went down while the app was open (crash_check): suggests picture mode.
Rectangle {
    id: cn
    property real size: 1.0
    readonly property bool picture: backend.settings.vr_mode === "file"
    visible: backend.crashNotice
    radius: 12 * size
    color: "#3a2a12"; border.width: 2; border.color: Theme.warn
    implicitHeight: col.implicitHeight + 24 * size
    ColumnLayout {
        id: col
        anchors.fill: parent; anchors.margins: 12 * cn.size
        spacing: 10 * cn.size
        Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 17 * cn.size
               text: cn.picture
                     ? "Your PC started up again while the app was still open last time, already in picture mode. If it crashed or froze, "
                       + "see \"If your PC crashes\" in 5_play_in_vr\\README.md."
                     : "Your PC started up again while the app was still open last time. If it crashed or froze, picture mode may help: "
                       + "the app then uses no graphics card for its VR pictures. You can switch back under \"SteamVR pictures\" in the settings." }
        RowLayout {
            spacing: 10 * cn.size
            BigButton { visible: !cn.picture; primary: true; size: cn.size * 0.85; implicitWidth: 230 * cn.size
                        text: "Use picture mode"; onClicked: backend.usePictureMode() }
            BigButton { size: cn.size * 0.85; implicitWidth: 150 * cn.size
                        text: cn.picture ? "OK" : "Not now"; onClicked: backend.dismissCrashNotice() }
            Item { Layout.fillWidth: true }
        }
    }
}
