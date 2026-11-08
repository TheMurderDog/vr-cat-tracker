import QtQuick
import QtQuick.Layouts

// The wrist widget: a small panel in VR showing the cat at a glance.
ColumnLayout {
    id: wp
    property real size: 1.0
    property bool compact: false
    readonly property var w: backend.settings.wrist
    spacing: 10 * size
    Segmented { size: wp.size; label: "Wrist widget"; Layout.fillWidth: true
                options: [[true, "On"], [false, "Off"]]; current: wp.w.on
                onPicked: function(v) { backend.setSetting("wrist.on", v) } }
    Segmented { size: wp.size; label: "Where it sits"; Layout.fillWidth: true; enabled: wp.w.on
                options: [["left", "Left wrist"], ["right", "Right wrist"], ["head", "In view"], ["room", "In the room"]]
                current: wp.w.attach; onPicked: function(v) { backend.setSetting("wrist.attach", v) } }
    Segmented { size: wp.size; label: "Position"; Layout.fillWidth: true; enabled: wp.w.on
                options: [[false, "Can grab and move"], [true, "Locked"]]; current: wp.w.locked
                onPicked: function(v) { backend.setSetting("wrist.locked", v) } }
    Text { visible: !wp.compact; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 14 * wp.size
           text: "To move it, reach over with your other hand and hold the grip button on it, then let go where you want it. "
                 + "While holding it, push the thumbstick up or down to make it bigger or smaller. Lock it once it's right." }
    Text { text: "Show"; color: Theme.text; font.pixelSize: 18 * wp.size }
    Flow {
        Layout.fillWidth: true; spacing: 8 * wp.size
        Repeater {
            model: [["distance", "Distance"], ["direction", "Direction"], ["state", "What it's doing"],
                    ["snooze", "Snooze"], ["problems", "Problems"]]
            BigButton { size: wp.size * 0.85; implicitWidth: 170 * wp.size; text: modelData[1]; enabled: wp.w.on
                        primary: !!wp.w.show[modelData[0]]
                        onClicked: backend.setSetting("wrist.show." + modelData[0], !wp.w.show[modelData[0]])
                        Accessible.role: Accessible.CheckBox; Accessible.checked: primary }
        }
    }
    Segmented { size: wp.size; label: "Fade unless you look at it"; Layout.fillWidth: true; enabled: wp.w.on
                options: [[true, "On"], [false, "Off"]]; current: wp.w.fade
                onPicked: function(v) { backend.setSetting("wrist.fade", v) } }
    Stepper { size: wp.size; labelWidth: 230; label: "Starts fading at"; enabled: wp.w.on && wp.w.fade
              valueText: Math.round(wp.w.fade_angle) + "°"
              onMinus: backend.nudgeSetting("wrist.fade_angle", -5); onPlus: backend.nudgeSetting("wrist.fade_angle", 5) }
    Stepper { size: wp.size; labelWidth: 230; label: "Size"; enabled: wp.w.on
              valueText: Math.round(wp.w.width_m * 100) + " cm wide"
              onMinus: backend.nudgeSetting("wrist.width_m", -0.02); onPlus: backend.nudgeSetting("wrist.width_m", 0.02) }
    BigButton { text: "Put it back where it started"; size: wp.size * 0.85; implicitWidth: 300 * wp.size; enabled: wp.w.on
                onClicked: backend.setSetting("wrist.offsets." + wp.w.attach, null) }
}
