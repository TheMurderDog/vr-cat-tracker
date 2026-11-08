import QtQuick
import QtQuick.Layouts
import "components"

// The wrist widget: the cat at a glance, small enough for a watch-sized panel in VR.
// What it shows is chosen in the app (Alerts & widget). The arrow points to the cat: on a wrist or in the
// room, from the widget the way it points (wrist.py works that out); in your view, the way you're facing.
Rectangle {
    id: ww
    width: 640; height: 320
    property bool grabbed: false
    property bool handMode: false      // set by wrist.py: use handAngle instead of the head-based angle
    property real handAngle: -1000     // -1000: don't know which way
    readonly property var arrowAngle: handMode ? (handAngle > -999 ? handAngle : null) : info.angle
    readonly property var show: backend.settings.wrist.show
    readonly property var info: backend.wristInfo
    readonly property color levelColour: info.level === "alert" ? Theme.alert : info.level === "ok" ? Theme.ok
                                         : info.level === "warn" ? Theme.warn : Theme.off
    color: info.level === "alert" ? "#3a1c20" : Theme.bg
    radius: 34
    border.width: grabbed ? 10 : 4
    border.color: grabbed ? Theme.accent : levelColour

    RowLayout {
        anchors.fill: parent; anchors.margins: 28
        spacing: 26

        Item {  // direction arrow, in a circle
            visible: ww.show.direction
            Layout.preferredWidth: 220; Layout.preferredHeight: 220
            Rectangle { anchors.fill: parent; radius: width / 2; color: Theme.panel; border.color: Theme.line; border.width: 3 }
            Canvas {
                id: arrow
                anchors.fill: parent
                visible: ww.arrowAngle !== undefined && ww.arrowAngle !== null
                rotation: ww.arrowAngle || 0
                property color c: ww.info.level === "alert" ? Theme.alert : Theme.accent
                onCChanged: requestPaint()
                onPaint: {
                    var g = getContext("2d"); g.reset()
                    var w = width, h = height
                    g.fillStyle = c; g.strokeStyle = "#111"; g.lineWidth = 5
                    g.beginPath()
                    g.moveTo(w / 2, h * 0.12); g.lineTo(w * 0.78, h * 0.62); g.lineTo(w * 0.58, h * 0.56)
                    g.lineTo(w * 0.58, h * 0.86); g.lineTo(w * 0.42, h * 0.86); g.lineTo(w * 0.42, h * 0.56)
                    g.lineTo(w * 0.22, h * 0.62); g.closePath(); g.fill(); g.stroke()
                }
            }
            Text { anchors.centerIn: parent; visible: !arrow.visible; text: "?"; color: Theme.muted; font.pixelSize: 90; font.weight: Font.Bold }
        }

        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 6
            Item { Layout.fillHeight: true }
            Text {
                visible: ww.show.distance
                text: ww.info.dist !== undefined && ww.info.dist !== null ? ww.info.dist.toFixed(1) + " m" : "–"
                color: ww.info.level === "alert" ? Theme.alert : Theme.text
                font.pixelSize: 92; font.weight: Font.Bold
            }
            RowLayout {
                visible: ww.show.state
                spacing: 12
                Rectangle { width: 24; height: 24; radius: 12; color: ww.levelColour }
                Text { text: ww.info.state; color: Theme.text; font.pixelSize: 40; font.weight: Font.DemiBold
                       Layout.fillWidth: true; elide: Text.ElideRight }
            }
            Text {
                visible: ww.show.problems && ww.info.problem !== ""
                Layout.fillWidth: true
                text: ww.info.problem; color: Theme.warn; font.pixelSize: 30; elide: Text.ElideRight
            }
            Text {
                visible: ww.show.snooze && backend.snoozed
                Layout.fillWidth: true
                text: "Buzz snoozed"; color: Theme.muted; font.pixelSize: 30; elide: Text.ElideRight
            }
            Item { Layout.fillHeight: true }
        }
    }
}
