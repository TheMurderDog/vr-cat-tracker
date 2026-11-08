import QtQuick
import QtQuick.Layouts

// The room map's heatmap, and automatic training captures where the tracking wobbles.
ColumnLayout {
    id: mp
    property real size: 1.0
    readonly property var st: backend.settings
    spacing: 10 * size
    Segmented { size: mp.size; label: "Heatmap on the map"; Layout.fillWidth: true
                options: [["off", "Off"], ["time", "Where the cat spends time"], ["wobble", "Where tracking wobbles"]]
                current: mp.st.map.heat; onPicked: function(v) { backend.setSetting("map.heat", v) } }
    Segmented { size: mp.size; label: "Colour the cat's trail by wobble"; Layout.fillWidth: true
                options: [[true, "On"], [false, "Off"]]; current: mp.st.map.trail_wobble
                onPicked: function(v) { backend.setSetting("map.trail_wobble", v) } }
    Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 14 * mp.size
           text: "Wobble is how much the cat's position jumps around from one detection to the next, before the tracker smooths it. "
                 + "Green is steady, red is jittery. Red spots are where the model may need more training pictures." }
    Segmented { size: mp.size; label: "Capture for training when it wobbles"; Layout.fillWidth: true
                options: [[true, "On"], [false, "Off"]]; current: mp.st.auto_capture.on
                onPicked: function(v) { backend.setSetting("auto_capture.on", v) } }
    Stepper { size: mp.size; labelWidth: 230; label: "Counts as wobbly from"; enabled: mp.st.auto_capture.on
              valueText: Math.round(mp.st.auto_capture.wobble_cm) + " cm"
              onMinus: backend.nudgeSetting("auto_capture.wobble_cm", -1); onPlus: backend.nudgeSetting("auto_capture.wobble_cm", 1) }
    Text { Layout.fillWidth: true; wrapMode: Text.WordWrap; color: Theme.muted; font.pixelSize: 14 * mp.size
           text: "Starts the tracker's normal capture after 1.5 s of wobble and stops 5 s after it settles (at most "
                 + Math.round(mp.st.auto_capture.max_s) + " s each, " + mp.st.auto_capture.max_per_run
                 + " a run). It saves room pictures: anyone in view can be in them. They go to my_data\\captures, "
                 + "ready for 4_teach_it_your_cat\\2_label.bat."
                 + (backend.status.auto_capture && backend.status.auto_capture.count ? " This run: " + backend.status.auto_capture.count + " so far." : "") }
    BigButton { text: "Clear the heatmap"; size: mp.size * 0.85; implicitWidth: 230 * mp.size; onClicked: backend.clearHeatmap() }
}
