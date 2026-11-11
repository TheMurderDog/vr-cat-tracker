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
    property string settingsPage: "start"
    property bool newAnchor: false   // Settings: walk for a new anchor at the next Start
    readonly property real k: 1.35   // everything bigger than on the desktop

    ColumnLayout {
        anchors.fill: parent; anchors.margins: 22
        spacing: 16

        RowLayout {
            Layout.fillWidth: true
            spacing: 14
            Image { source: catIcon; Layout.preferredWidth: 58; Layout.preferredHeight: 58; smooth: true }
            Text { text: "Cat Tracker"; color: Theme.text; font.pixelSize: 30; font.weight: Font.Bold }
            Item { Layout.fillWidth: true }
            Repeater {
                model: ["Status", "Cameras", "Marker look", "Alerts", "Settings"]
                BigButton { text: modelData; size: 1.1; implicitWidth: modelData === "Marker look" ? 200 : 170
                            primary: vr.page === index; onClicked: vr.page = index
                            Accessible.role: Accessible.PageTab }
            }
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
                    CrashNotice { Layout.fillWidth: true; size: 1.15 }
                    RoomMap { Layout.fillWidth: true; Layout.fillHeight: true; size: 1.2 }
                    Rectangle {  // the app's last message (starting, stopping, a problem); point and click to hide it
                        visible: backend.message !== ""
                        Layout.fillWidth: true; radius: 12; color: Theme.panel2
                        implicitHeight: vrMsg.implicitHeight + 24
                        Text { id: vrMsg; anchors.fill: parent; anchors.margins: 12; text: backend.message
                               color: Theme.text; font.pixelSize: 19; wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight }
                        MouseArea { anchors.fill: parent; onClicked: backend.clearMessage() }
                    }
                }
                GridLayout {
                    Layout.preferredWidth: 470; Layout.maximumWidth: 470; Layout.fillHeight: true
                    columns: 6; rowSpacing: 14; columnSpacing: 14
                    BigButton {
                        Layout.columnSpan: 6; Layout.fillWidth: true; Layout.fillHeight: true; size: vr.k; primary: true
                        text: backend.connected ? "Stop tracker" : (backend.otherTracker ? "Stop background tracker" : "Start tracker")
                        hint: (backend.connected || backend.otherTracker) ? ""
                              : (vr.newAnchor ? "New anchor walk, " : "") + (backend.startOsc ? "sends to VRChat" : "VRChat off") + " (Settings)"
                        enabled: !backend.starting
                        onClicked: {
                            if (backend.connected || backend.otherTracker) {
                                backend.stop()
                            } else {
                                backend.start(vr.newAnchor, backend.startOsc)
                                vr.newAnchor = false
                            }
                        }
                    }
                    BigButton { Layout.columnSpan: 6; Layout.fillWidth: true; Layout.fillHeight: true; size: vr.k
                                text: "Re-anchor"; primary: backend.anchorNeeded
                                hint: backend.anchorNeeded ? "Needed now: walk slowly around the room" : "Only when the app asks you to"
                                enabled: backend.connected && !!backend.status.vr; onClicked: backend.reanchor() }
                    BigButton { Layout.columnSpan: 2; Layout.fillWidth: true; Layout.fillHeight: true; size: 1.15; text: "Test buzz"
                                enabled: backend.connected && !!backend.status.vr; onClicked: backend.testBuzz() }
                    BigButton { Layout.columnSpan: 2; Layout.fillWidth: true; Layout.fillHeight: true; size: 1.15
                                text: backend.status.capture && backend.status.capture.on ? "Stop capture" : "Capture"
                                hint: backend.status.capture && backend.status.capture.on ? backend.status.capture.n + " saved" : "For training"
                                enabled: backend.connected; onClicked: backend.toggleCapture() }
                    BigButton { Layout.columnSpan: 2; Layout.fillWidth: true; Layout.fillHeight: true; size: 1.15; text: "Snapshot"
                                hint: "Pictures"; enabled: backend.connected; onClicked: backend.snapshot() }
                    BigButton { Layout.columnSpan: 6; Layout.fillWidth: true; Layout.fillHeight: true; size: vr.k
                                text: backend.snoozeButtonText
                                hint: backend.snoozed ? backend.snoozeText : "Length: Alerts tab"
                                onClicked: backend.toggleSnooze() }
                    CameraChips { Layout.columnSpan: 6; Layout.fillWidth: true; size: 1.2 }
                }
            }

            // ---- Cameras ----
            ColumnLayout {
                spacing: 12
                Timer { interval: 500; repeat: true; triggeredOnStart: true
                        running: vr.page === 1 && backend.vrTabOpen; onTriggered: backend.wantFrames() }
                Rectangle {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    radius: 16; color: "#0d0f12"
                    Image {
                        anchors.fill: parent; anchors.margins: 8
                        visible: vr.page === 1 && backend.hasFrame && backend.connected
                        source: visible ? "image://cat/frame/" + backend.frameSeq : ""
                        fillMode: Image.PreserveAspectFit; cache: false; asynchronous: false
                    }
                    Text {
                        anchors.centerIn: parent
                        visible: !(backend.hasFrame && backend.connected)
                        text: backend.connected ? "Waiting for the first pictures..." : "Start the tracker on the Status tab to see the cameras."
                        color: Theme.muted; font.pixelSize: 24
                    }
                }
                RowLayout {
                    Layout.fillWidth: true; spacing: 14
                    Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 18
                           text: "Grey boxes are everything the model found; the thick box is the one used for the cat." }
                    CameraChips { Layout.preferredWidth: 640; size: 1.15 }
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
                            Text { text: "Distance from"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
                            FeetPanel { Layout.fillWidth: true; size: 1.05 }
                            Item { Layout.fillHeight: true }
                        }
                    }
                }
            }

            // ---- Settings ----
            ColumnLayout {
                spacing: 14
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 14
                    Repeater {
                        model: [["start", "Starting"], ["wrist", "Wrist widget"], ["map", "Room map"], ["pictures", "Pictures"], ["help", "Help"]]
                        BigButton { Layout.fillWidth: true; size: 1.1; text: modelData[1]
                                    primary: vr.settingsPage === modelData[0]; onClicked: vr.settingsPage = modelData[0] }
                    }
                }
                Rectangle {
                    Layout.fillWidth: true; Layout.fillHeight: true; radius: 16; color: Theme.panel
                    StackLayout {
                        anchors.fill: parent; anchors.margins: 20
                        currentIndex: ["start", "wrist", "map", "pictures", "help"].indexOf(vr.settingsPage)
                        ColumnLayout {
                            spacing: 14
                            Text { text: "When you press Start"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
                            Segmented { Layout.fillWidth: true; size: 1.1; label: "Send to VRChat (OSC)"
                                        options: [[true, "On"], [false, "Off"]]; current: backend.startOsc
                                        onPicked: function(v) { backend.setSetting("start_osc", v) } }
                            Segmented { Layout.fillWidth: true; size: 1.1; label: "Walk for a new anchor"
                                        options: [[false, "No, use the saved one"], [true, "Yes, next start"]]; current: vr.newAnchor
                                        onPicked: function(v) { vr.newAnchor = v } }
                            Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 18
                                   text: "VRChat is remembered for next time, here and on the desktop. A new anchor walk is only needed when the app asks "
                                         + "for it (the Re-anchor button does the same while the tracker runs); it applies to the next Start only. "
                                         + "Clear the floor first." }
                            Item { Layout.fillHeight: true }
                        }
                        WidgetPanel { size: 1.0; compact: true }
                        MapPanel { size: 1.15 }
                        ColumnLayout {
                            spacing: 14
                            Text { text: "SteamVR pictures"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
                            PicturePanel { Layout.fillWidth: true; size: 1.2 }
                            Item { Layout.fillHeight: true }
                        }
                        ColumnLayout {
                            spacing: 14
                            Text { text: "Help"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
                            Text {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 20
                                text: "Point with a controller's laser and pull the trigger to press a button.\n\n"
                                      + "Start runs the tracker with the saved anchor. The first time, it asks you to walk slowly around "
                                      + "the room with the headset on: clear the floor first.\n\n"
                                      + "A tracker started without the app (the desktop test, a capture) has the cameras: press "
                                      + "\"Stop background tracker\" on the Status tab, then Start.\n\n"
                                      + "Logs and folders are on the desktop window's Help page.\n\n"
                                      + "It's a hobby project, not a safety device: the cat's marker shows where the cameras think it is, "
                                      + "and it can miss the cat. See 0_start_here\\DISCLAIMER.md."
                            }
                            Item { Layout.fillHeight: true }
                        }
                    }
                }
            }
        }
    }
}
