import QtQuick
import QtQuick.Layouts

// How long the Snooze button on the main screen mutes the warning buzz. The button itself is on the
// main screen; while it's snoozed, a small dim "buzz muted" sign sits low in the corner of your view.
ColumnLayout {
    id: sp
    property real size: 1.0
    property bool compact: false
    spacing: 10 * size
    Segmented {
        size: sp.size; Layout.fillWidth: true
        label: sp.compact ? "" : "Snooze for"
        options: sp.compact ? [[15, "15m"], [30, "30m"], [60, "1h"], [120, "2h"], [-1, "Until on"]]
                            : [[15, "15 min"], [30, "30 min"], [60, "1 hour"], [120, "2 hours"], [-1, "Until on"]]
        current: backend.settings.snooze_minutes
        onPicked: function(v) { backend.setSetting("snooze_minutes", v) }
    }
    Text {
        Layout.fillWidth: true; wrapMode: Text.WordWrap
        visible: backend.snoozed
        text: backend.snoozeText
        color: Theme.warn; font.pixelSize: 15 * sp.size; font.weight: Font.DemiBold
    }
}
