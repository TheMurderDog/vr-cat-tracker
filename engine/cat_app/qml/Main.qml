import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "components"

// The desktop window.
ApplicationWindow {
    id: win
    width: 1220; height: 820
    minimumWidth: 900; minimumHeight: 620
    visible: true
    title: "Cat Tracker"
    color: Theme.bg
    property int page: 0

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // navigation
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 230
            color: Theme.panel
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 16
                spacing: 10
                RowLayout {
                    spacing: 10
                    Image { source: catIcon; Layout.preferredWidth: 44; Layout.preferredHeight: 44; smooth: true }
                    Text { text: "Cat Tracker"; color: Theme.text; font.pixelSize: 22; font.weight: Font.Bold }
                }
                Item { Layout.preferredHeight: 10 }
                Repeater {
                    model: [["Home", "Status and controls"], ["Cameras", "What the cameras see"],
                            ["Marker look", "Colour, size, opacity"], ["Alerts & widget", "Buzz, snooze, map, wrist"],
                            ["Help", "Logs and folders"]]
                    BigButton {
                        Layout.fillWidth: true
                        text: modelData[0]; hint: modelData[1]
                        primary: win.page === index
                        onClicked: win.page = index
                        Accessible.role: Accessible.PageTab
                    }
                }
                Item { Layout.fillHeight: true }
                Text {
                    Layout.fillWidth: true
                    text: "Also in SteamVR: open the dashboard and pick the cat tab."
                    color: Theme.muted; font.pixelSize: 13; wrapMode: Text.WordWrap
                }
            }
        }

        StackLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            currentIndex: win.page

            // ---- Home ----
            Loader {  // made only while this page is shown, and dropped when you leave it
                active: win.page === 0
                sourceComponent: Component {
                    Item {
                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 20
                            spacing: 16
                            StatusBanner { Layout.fillWidth: true }
                            CrashNotice { Layout.fillWidth: true }
                            RowLayout {
                                Layout.fillWidth: true; Layout.fillHeight: true
                                spacing: 16
                                RoomMap { Layout.fillWidth: true; Layout.fillHeight: true }
                                ColumnLayout {
                                    Layout.preferredWidth: 300; Layout.maximumWidth: 300; Layout.fillHeight: true
                                    spacing: 10
                                    BigButton {
                                        Layout.fillWidth: true; primary: true
                                        text: backend.connected ? "Stop tracker" : (backend.otherTracker ? "Stop background tracker" : "Start tracker")
                                        hint: backend.connected ? "Closes it and frees the cameras" : (backend.otherTracker ? "Then Start runs it from here" : "Start SteamVR first")
                                        enabled: !backend.starting
                                        onClicked: (backend.connected || backend.otherTracker) ? backend.stop() : backend.start(newAnchor.checked, osc.checked)
                                    }
                                    BigButton { Layout.fillWidth: true; text: "Re-anchor"; primary: backend.anchorNeeded
                                                hint: backend.anchorNeeded ? "Needed now: headset on, walk around" : "Only when the app asks you to"
                                                enabled: backend.connected && !!backend.status.vr; onClicked: backend.reanchor() }
                                    BigButton { Layout.fillWidth: true; text: "Test buzz"; hint: "Vibrates the controllers"
                                                enabled: backend.connected && !!backend.status.vr; onClicked: backend.testBuzz() }
                                    BigButton { Layout.fillWidth: true
                                                text: backend.status.capture && backend.status.capture.on ? "Stop capturing" : "Capture for training"
                                                hint: backend.status.capture && backend.status.capture.on ? backend.status.capture.n + " moments saved" : "Saves pictures to teach it your cat"
                                                enabled: backend.connected; onClicked: backend.toggleCapture() }
                                    BigButton { Layout.fillWidth: true; text: "Snapshot"; enabled: backend.connected; onClicked: backend.snapshot() }
                                    BigButton { Layout.fillWidth: true
                                                text: backend.snoozeButtonText
                                                hint: backend.snoozed ? backend.snoozeText : "How long: Alerts & widget"
                                                onClicked: backend.toggleSnooze() }
                                    Rectangle {
                                        Layout.fillWidth: true; radius: 12; color: Theme.panel
                                        implicitHeight: opts.implicitHeight + 20
                                        ColumnLayout {
                                            id: opts
                                            anchors.fill: parent; anchors.margins: 10
                                            Text { text: "When starting"; color: Theme.muted; font.pixelSize: 14 }
                                            CheckBox { id: newAnchor; checked: false; text: "Walk for a new anchor (only if asked)"
                                                       contentItem: Text { leftPadding: newAnchor.indicator.width + 8; text: newAnchor.text; color: Theme.text; font.pixelSize: 15; verticalAlignment: Text.AlignVCenter } }
                                            CheckBox { id: osc; checked: backend.startOsc; text: "Send to VRChat (OSC)"
                                                       contentItem: Text { leftPadding: osc.indicator.width + 8; text: osc.text; color: Theme.text; font.pixelSize: 15; verticalAlignment: Text.AlignVCenter } }
                                        }
                                    }
                                    Item { Layout.fillHeight: true }
                                }
                            }
                            CameraChips { Layout.fillWidth: true }
                            Rectangle {
                                visible: backend.message !== ""
                                Layout.fillWidth: true; radius: 10; color: Theme.panel2
                                implicitHeight: msg.implicitHeight + 20
                                Text { id: msg; anchors.fill: parent; anchors.margins: 10; text: backend.message
                                       color: Theme.text; font.pixelSize: 15; wrapMode: Text.WordWrap }
                                MouseArea { anchors.fill: parent; onClicked: backend.clearMessage() }
                            }
                        }
                    }
                }
            }

            // ---- Cameras ----
            Loader {  // made only while this page is shown, and dropped when you leave it
                active: win.page === 1
                sourceComponent: Component {
                    Item {
                        Timer { interval: 500; repeat: true; triggeredOnStart: true
                                running: win.page === 1 && win.visible; onTriggered: backend.wantFrames() }
                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 20
                            spacing: 12
                            Text { text: "What the cameras see"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
                            Text { text: "Grey boxes are everything the model found; the thick box is the one used for the cat."
                                   color: Theme.muted; font.pixelSize: 15; wrapMode: Text.WordWrap; Layout.fillWidth: true }
                            Rectangle {
                                Layout.fillWidth: true; Layout.fillHeight: true
                                radius: 14; color: "#0d0f12"
                                Image {
                                    anchors.fill: parent; anchors.margins: 8
                                    visible: backend.hasFrame && backend.connected
                                    source: backend.hasFrame ? "image://cat/frame/" + backend.frameSeq : ""
                                    fillMode: Image.PreserveAspectFit; cache: false; asynchronous: false
                                    Accessible.name: "Camera pictures"
                                }
                                Text {
                                    anchors.centerIn: parent
                                    visible: !(backend.hasFrame && backend.connected)
                                    text: backend.connected ? "Waiting for the first pictures..." : "Start the tracker on the Home page to see the cameras."
                                    color: Theme.muted; font.pixelSize: 17
                                }
                            }
                            CameraChips { Layout.fillWidth: true }
                        }
                    }
                }
            }

            // ---- Marker look ----
            Loader {  // made only while this page is shown, and dropped when you leave it
                active: win.page === 2
                sourceComponent: Component {
                    ScrollView {
                        id: sv
                        clip: true
                        contentWidth: availableWidth
                        ColumnLayout {
                            width: sv.availableWidth - 40
                            x: 20
                            spacing: 16
                            Item { Layout.preferredHeight: 4 }
                            Text { text: "How the cat looks in VR"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
                            Text {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap
                                color: Theme.muted; font.pixelSize: 15
                                text: "Changes show in VR straight away while the tracker runs. The cat and warning icons can't go below half size or fade "
                                      + "out completely, so the marker can't vanish by accident."
                            }
                            StyleEditor { Layout.fillWidth: true; group: "cat"; title: "Cat icon"
                                          note: "Floats above the cat. Also used for its napping and running icons." }
                            StyleEditor { Layout.fillWidth: true; group: "warning"; title: "Warning icon"
                                          note: "Shown instead when the cat is close to you. It stays red unless you pick a colour, so it stands out." }
                            StyleEditor { Layout.fillWidth: true; group: "ring"; title: "Floor ring"
                                          note: "The ring on the floor under the cat. Set opacity to 0% to hide it." }
                            StyleEditor { Layout.fillWidth: true; group: "arrow"; title: "Edge arrow"
                                          note: "Shown at the edge of your view when the cat is close; turn your head to follow it. It can't fade below 40%." }
                            Item { Layout.preferredHeight: 20 }
                        }
                    }
                }
            }

            // ---- Alerts & widget ----
            Loader {  // made only while this page is shown, and dropped when you leave it
                active: win.page === 3
                sourceComponent: Component {
                    ScrollView {
                        id: sv2
                        clip: true
                        contentWidth: availableWidth
                        ColumnLayout {
                            width: sv2.availableWidth - 40
                            x: 20
                            spacing: 16
                            Item { Layout.preferredHeight: 4 }
                            Text { text: "Alerts & widget"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
                            Text {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 15
                                text: "Changes apply straight away while the tracker runs, and are kept in my_data\\app\\app_settings.json. "
                                      + "Your settings\\cat_tracker.yaml stays as it is. The warnings are an extra hint: they come on only when "
                                      + "the cameras see the cat, so keep your play area clear."
                            }
                            Section { Layout.fillWidth: true; title: "Warnings and buzz"
                                      note: backend.alertValues.known ? "" : "Start the tracker to see the values from your settings\\cat_tracker.yaml (these are its usual ones)."
                                      AlertsPanel { Layout.fillWidth: true } }
                            Section { Layout.fillWidth: true; title: "Distance from your feet"
                                      FeetPanel { Layout.fillWidth: true } }
                            Section { Layout.fillWidth: true; title: "Snooze length"
                                      note: "The Snooze button on the Home page mutes the buzz for this long, for when the cat has settled nearby and you know it. The arrow and the red icon still show, and a small dim sign in the corner of your view reminds you it's snoozed."
                                      SnoozePanel { Layout.fillWidth: true } }
                            Section { Layout.fillWidth: true; title: "Wrist widget"
                                      note: "A small panel in VR with the cat at a glance, without opening the dashboard."
                                      WidgetPanel { Layout.fillWidth: true } }
                            Section { Layout.fillWidth: true; title: "Room map"
                                      MapPanel { Layout.fillWidth: true } }
                            Section { Layout.fillWidth: true; title: "SteamVR pictures"
                                      PicturePanel { Layout.fillWidth: true } }
                            Item { Layout.preferredHeight: 20 }
                        }
                    }
                }
            }

            // ---- Help ----
            Loader {  // made only while this page is shown, and dropped when you leave it
                active: win.page === 4
                sourceComponent: Component {
                    Item {
                        ColumnLayout {
                            anchors.fill: parent; anchors.margins: 20
                            spacing: 14
                            Text { text: "Help"; color: Theme.text; font.pixelSize: 26; font.weight: Font.Bold }
                            Text {
                                Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 16
                                text: "Start SteamVR first, then press Start on the Home page. The first time, the tracker asks you to put the "
                                      + "headset on and walk slowly around the room (the anchor): clear the floor first.\n\n"
                                      + "In VR, open the SteamVR dashboard and choose the cat tab at the bottom. Point with a controller's laser and pull the trigger to press a button.\n\n"
                                      + "A tracker started without the app (the desktop test, a capture) has the cameras: press \"Stop background tracker\", then Start.\n\n"
                                      + "It's a hobby project, not a safety device: the cat's marker shows where the cameras think it is, and it can miss the cat. "
                                      + "See 0_start_here\\DISCLAIMER.md."
                            }
                            Flow {
                                Layout.fillWidth: true; spacing: 10
                                BigButton { text: "Logs"; hint: "my_data\\logs"; onClicked: backend.openFolder("logs") }
                                BigButton { text: "App logs"; hint: "my_data\\logs\\cat_app"; onClicked: backend.openFolder("app_logs") }
                                BigButton { text: "App's own files"; hint: "my_data\\app: settings, marker look"; onClicked: backend.openFolder("app_data") }
                                BigButton { text: "Tracker settings"; hint: "settings"; onClicked: backend.openFolder("settings") }
                            }
                            Item { Layout.fillHeight: true }
                        }
                    }
                }
            }
        }
    }
}
