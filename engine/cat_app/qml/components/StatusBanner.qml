import QtQuick
import QtQuick.Layouts

// The one-line plain-English status, coloured by how much it needs your attention.
Rectangle {
    id: s
    property real size: 1.0
    radius: 14 * size
    color: Theme.panel
    border.color: Theme.levelColour(backend.level); border.width: 2 * size
    implicitHeight: col.implicitHeight + 32 * size
    Accessible.role: Accessible.StaticText
    Accessible.name: backend.headline + ". " + backend.detail
    RowLayout {
        anchors.fill: parent; anchors.margins: 16 * s.size
        spacing: 16 * s.size
        Rectangle {
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: 6 * s.size
            width: 22 * s.size; height: width; radius: width / 2
            color: Theme.levelColour(backend.level)
            // a slow blink (two redraws a second) rather than a smooth fade, which would redraw the window
            // and the VR tab 60 times a second for as long as it lasts
            property bool dim: false
            opacity: dim ? 0.35 : 1
            Timer {
                interval: 600; repeat: true
                running: backend.level === "alert" || backend.starting
                onTriggered: parent.dim = !parent.dim
                onRunningChanged: if (!running) parent.dim = false
            }
        }
        ColumnLayout {
            id: col
            Layout.fillWidth: true
            spacing: 6 * s.size
            Text {
                Layout.fillWidth: true
                text: backend.headline
                color: Theme.text; font.pixelSize: 26 * s.size; font.weight: Font.Bold
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                text: backend.detail
                color: Theme.muted; font.pixelSize: 16 * s.size
                wrapMode: Text.WordWrap
            }
            Text {
                visible: backend.snoozed
                Layout.fillWidth: true
                text: backend.snoozeText
                color: Theme.warn; font.pixelSize: 14 * s.size
                wrapMode: Text.WordWrap
            }
        }
    }
}
