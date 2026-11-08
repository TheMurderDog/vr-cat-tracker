import QtQuick
import QtQuick.Layouts

// Warning distances, the buzz, and snooze. Used on the desktop and (bigger) in the VR tab.
ColumnLayout {
    id: ap
    property real size: 1.0
    property bool compact: false     // VR: fewer words
    readonly property var a: backend.alertValues
    readonly property var st: backend.settings
    spacing: 10 * size
    function m(v) { return (Math.round(v * 10) / 10).toFixed(1) + " m" }

    Stepper { size: ap.size; labelWidth: 230; label: "Warn closer than"; valueText: ap.m(ap.a.underfoot_m)
              onMinus: backend.nudgeSetting("alert.underfoot_m", -0.1); onPlus: backend.nudgeSetting("alert.underfoot_m", 0.1) }
    Text { visible: !ap.compact; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 14 * ap.size
           text: "When the cameras see the cat closer than this, the arrow, the red icon and the buzz come on, even if it's napping." }
    Stepper { size: ap.size; labelWidth: 230; label: "Warn if moving within"; valueText: ap.m(ap.a.radius_m)
              onMinus: backend.nudgeSetting("alert.radius_m", -0.1); onPlus: backend.nudgeSetting("alert.radius_m", 0.1) }
    Text { visible: !ap.compact; Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 14 * ap.size
           text: "Within this distance it warns only while the cat is walking. It also tries to warn early when one of you is closing in fast." }
    Segmented { size: ap.size; label: "Buzz"; Layout.fillWidth: true
                options: [[true, "On"], [false, "Off"]]; current: ap.a.buzz !== false
                onPicked: function(v) { backend.setSetting("alert.buzz", v) } }
    Segmented { size: ap.size; label: "Buzz style"; Layout.fillWidth: true; enabled: ap.a.buzz !== false
                options: ap.compact ? [["once", "Left-right"], ["rising", "Light to heavy"]] : [["once", "Left-right taps"], ["rising", "Light to heavy"]]; current: ap.st.buzz_style
                onPicked: function(v) { backend.setSetting("buzz_style", v) } }
    Text { visible: !ap.compact && ap.a.buzz !== false; Layout.fillWidth: true; wrapMode: Text.WordWrap
           color: Theme.muted; font.pixelSize: 14 * ap.size
           text: ap.st.buzz_style === "rising"
                 ? "Both controllers together: a light tap while the cat is still a little way off, a double tap within the \"moving\" distance, a long full-strength buzz when it's underfoot. If it comes closer while the warning is on, you get the next step up (each step once). Test buzz plays all three."
                 : "The tracker's own buzz: quick taps on the left and right controller, once each time the warning comes on." }
    Stepper { size: ap.size; labelWidth: 230; label: "Buzz strength"; valueText: Math.round(ap.a.buzz_amplitude * 100) + "%"
              enabled: ap.a.buzz !== false
              onMinus: backend.nudgeSetting("alert.buzz_amplitude", -0.1); onPlus: backend.nudgeSetting("alert.buzz_amplitude", 0.1) }
    RowLayout {
        spacing: 10 * ap.size
        BigButton { text: "Test buzz"; size: ap.size * 0.85; enabled: backend.connected && !!backend.status.vr; onClicked: backend.testBuzz() }
        BigButton { text: "Back to my settings"; size: ap.size * 0.85; implicitWidth: 230 * ap.size
                    hint: ap.compact ? "" : "Undo these changes"
                    enabled: ap.a.changed; onClicked: backend.resetAlerts() }
    }
}
