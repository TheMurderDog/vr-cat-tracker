import QtQuick
import QtQuick.Layouts

// Foot trackers: assign them by waving, so the distance is measured from whichever is closest to the cat, your
// feet or your headset (cat_tracker.feet). Used on the desktop and (bigger) in the VR tab.
ColumnLayout {
    id: fp
    property real size: 1.0
    property bool compact: false
    readonly property var f: backend.feet
    readonly property var pick: backend.feetPick
    spacing: 10 * size
    Text { visible: !fp.compact; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 14 * fp.size
           text: "With SteamVR foot trackers, the warnings and the distance use whichever is closest to the cat: either foot or "
                 + "your headset, when the cameras see the cat. So a cat by your feet can count as close while your head is further away. "
                 + "To assign them: sit down, press the button, and wave each foot when asked. SteamVR has to be running." }
    Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.text; font.pixelSize: 17 * fp.size
           text: fp.f.text }
    Rectangle {  // the wave steps, big, while they run (and the result after)
        visible: fp.pick.state !== "idle"
        Layout.fillWidth: true; radius: 12 * fp.size
        color: fp.pick.state === "failed" ? "#3a2a12" : fp.pick.state === "done" ? "#163024" : Theme.panel2
        border.width: 2; border.color: fp.pick.state === "failed" ? Theme.warn : fp.pick.state === "done" ? Theme.ok : Theme.accent
        implicitHeight: stepText.implicitHeight + 28 * fp.size
        Text { id: stepText; anchors.fill: parent; anchors.margins: 14 * fp.size; wrapMode: Text.WordWrap
               text: fp.pick.text; color: Theme.text; font.pixelSize: (fp.pick.busy ? 24 : 18) * fp.size
               font.weight: fp.pick.busy ? Font.Bold : Font.Normal }
    }
    Flow {
        Layout.fillWidth: true; spacing: 10 * fp.size
        BigButton { visible: !fp.pick.busy; size: fp.size * 0.9; implicitWidth: 260 * fp.size; primary: fp.f.assigned.length === 0
                    text: fp.f.assigned.length ? "Assign again" : "Assign foot trackers"; hint: "Sit down, then wave each foot"
                    onClicked: backend.startFeetPick() }
        BigButton { visible: !fp.pick.busy && fp.f.assigned.length > 0; size: fp.size * 0.9; implicitWidth: 220 * fp.size
                    text: "Forget them"; hint: "Back to the headset only"
                    onClicked: backend.forgetFeet() }
        BigButton { visible: fp.pick.state === "right"; size: fp.size * 0.9; implicitWidth: 260 * fp.size
                    text: "I have only one"; hint: "Keep the left foot"
                    onClicked: backend.feetOnlyOne() }
        BigButton { visible: fp.pick.busy; size: fp.size * 0.9; implicitWidth: 200 * fp.size
                    text: "Cancel"; onClicked: backend.cancelFeetPick() }
    }
}
