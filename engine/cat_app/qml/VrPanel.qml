import QtQuick
import QtQuick.Layouts
import "components"

// The SteamVR dashboard tab. Drawn off screen and shown in VR; you use it with the controller's laser
// pointer like the rest of the SteamVR dashboard. Big buttons, nothing to type.
Rectangle {
    id: vr
    width: 1280; height: 800
    color: Theme.bg
    property int page: 0
    property string group: "cat"
    readonly property real k: 1.35   // everything bigger than on the desktop

    ColumnLayout {
        anchors.fill: parent; anchors.margins: 22
        spacing: 16

        RowLayout {
            Layout.fillWidth: true
            spacing: 14
            Image { source: catIcon; Layout.preferredWidth: 58; Layout.preferredHeight: 58; smooth: true }
            Text { text: "Cat Tracker"; color: Theme.text; font.pixelSize: 34; font.weight: Font.Bold }
            Item { Layout.fillWidth: true }
            BigButton { text: "Status"; size: 1.2; implicitWidth: 200; primary: vr.page === 0; onClicked: vr.page = 0 }
            BigButton { text: "Marker look"; size: 1.2; implicitWidth: 240; primary: vr.page === 1; onClicked: vr.page = 1 }
            BigButton { text: "Alerts"; size: 1.2; implicitWidth: 200; primary: vr.page === 2; onClicked: vr.page = 2 }
        }

        StackLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            currentIndex: vr.page

            // ---- Status ----
            RowLayout {
                spacing: 18
                ColumnLayout {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    spacing: 14
                    StatusBanner { Layout.fillWidth: true; size: 1.15 }
                    RoomMap { Layout.fillWidth: true; Layout.fillHeight: true; size: 1.2 }
                }
                GridLayout {
                    Layout.preferredWidth: 470; Layout.maximumWidth: 470; Layout.fillHeight: true
                    columns: 2; rowSpacing: 14; columnSpacing: 14
                    BigButton {
                        Layout.columnSpan: 2; Layout.fillWidth: true; Layout.fillHeight: true; size: vr.k; primary: true
                        text: backend.connected ? "Stop tracker" : (backend.otherTracker ? "Stop background tracker" : "Start tracker")
                        enabled: !backend.starting
                        onClicked: (backend.connected || backend.otherTracker) ? backend.stop() : backend.start(true, false)
                    }
                    BigButton { Layout.columnSpan: 2; Layout.fillWidth: true; Layout.fillHeight: true; size: vr.k
                                text: "Re-anchor"; primary: backend.anchorNeeded
                                hint: backend.anchorNeeded ? "Needed now: walk slowly around the room" : "Only when the app asks you to"
                                enabled: backend.connected && !!backend.status.vr; onClicked: backend.reanchor() }
                    BigButton { Layout.fillWidth: true; Layout.fillHeight: true; size: vr.k; text: "Test buzz"
                                enabled: backend.connected && !!backend.status.vr; onClicked: backend.testBuzz() }
                    BigButton { Layout.fillWidth: true; Layout.fillHeight: true; size: vr.k
                                text: backend.status.capture && backend.status.capture.on ? "Stop capture" : "Capture"
                                hint: backend.status.capture && backend.status.capture.on ? backend.status.capture.n + " saved" : "For training"
                                enabled: backend.connected; onClicked: backend.toggleCapture() }
                    BigButton { Layout.columnSpan: 2; Layout.fillWidth: true; Layout.fillHeight: true; size: vr.k
                                text: backend.snoozeButtonText
                                hint: backend.snoozed ? backend.snoozeText : "How long: Alerts tab"
                                onClicked: backend.toggleSnooze() }
                    CameraChips { Layout.columnSpan: 2; Layout.fillWidth: true; size: 1.2 }
                }
            }

            // ---- Marker look ----
            ColumnLayout {
                spacing: 14
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14
                    Repeater {
                        model: [["cat", "Cat icon"], ["warning", "Warning icon"], ["ring", "Floor ring"], ["arrow", "Edge arrow"]]
                        BigButton { Layout.fillWidth: true; size: 1.2; text: modelData[1]
                                    primary: vr.group === modelData[0]; onClicked: vr.group = modelData[0] }
                    }
                }
                StyleEditor {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    vr: true; size: 1.2
                    group: vr.group
                    title: vr.group === "cat" ? "Cat icon" : vr.group === "warning" ? "Warning icon" : vr.group === "ring" ? "Floor ring" : "Edge arrow"
                    note: vr.group === "warning" ? "Shown when the cat is close. Stays red unless you pick a colour."
                         : vr.group === "ring" ? "The ring on the floor under the cat."
                         : vr.group === "arrow" ? "At the edge of your view when the cat is close." : "Floats above the cat."
                }
            }

            // ---- Alerts ----
            RowLayout {
                spacing: 18
                Rectangle {
                    Layout.fillWidth: true; Layout.fillHeight: true; radius: 16; color: Theme.panel
                    ColumnLayout {
                        anchors.fill: parent; anchors.margins: 18; spacing: 10
                        Text { text: "Warnings and buzz"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
                        AlertsPanel { Layout.fillWidth: true; size: 1.1; compact: true }
                        Item { Layout.fillHeight: true }
                    }
                }
                ColumnLayout {
                    Layout.preferredWidth: 560; Layout.maximumWidth: 560; Layout.fillHeight: true
                    spacing: 18
                    Rectangle {
                        Layout.fillWidth: true; radius: 16; color: Theme.panel
                        implicitHeight: snz.implicitHeight + 36
                        ColumnLayout {
                            id: snz
                            anchors.fill: parent; anchors.margins: 18; spacing: 10
                            Text { text: "Snooze length"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
                            SnoozePanel { Layout.fillWidth: true; size: 1.05; compact: true }
                        }
                    }
                    Rectangle {
                        Layout.fillWidth: true; Layout.fillHeight: true; radius: 16; color: Theme.panel
                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 18; spacing: 10
                            Text { text: "Wrist widget"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
                            Segmented { Layout.fillWidth: true; size: 1.05; options: [[true, "On"], [false, "Off"]]
                                        current: backend.settings.wrist.on; onPicked: function(v) { backend.setSetting("wrist.on", v) } }
                            Segmented { Layout.fillWidth: true; size: 1.05; enabled: backend.settings.wrist.on
                                        options: [["left", "Left"], ["right", "Right"], ["head", "View"], ["room", "Room"]]
                                        current: backend.settings.wrist.attach; onPicked: function(v) { backend.setSetting("wrist.attach", v) } }
                            Segmented { Layout.fillWidth: true; size: 1.05; enabled: backend.settings.wrist.on
                                        options: [[false, "Can move"], [true, "Locked"]]
                                        current: backend.settings.wrist.locked; onPicked: function(v) { backend.setSetting("wrist.locked", v) } }
                            Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 16
                                   text: "Grab it with your other hand's grip to move it; thumbstick up or down while holding to resize. What it shows is set on the desktop." }
                            Item { Layout.fillHeight: true }
                        }
                    }
                }
            }
        }
    }
}
