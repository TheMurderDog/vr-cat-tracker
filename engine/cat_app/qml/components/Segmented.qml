import QtQuick
import QtQuick.Layouts

// A row of big buttons where one is chosen (like a radio group, easy to hit with a laser).
RowLayout {
    id: sg
    property var options: []        // [[value, label], ...]
    property var current
    property real size: 1.0
    property string label: ""
    signal picked(var value)
    spacing: 8 * size
    Text { visible: sg.label !== ""; text: sg.label; color: Theme.text; font.pixelSize: 18 * sg.size
           Layout.preferredWidth: 230 * sg.size; wrapMode: Text.WordWrap }
    Repeater {
        model: sg.options
        BigButton {
            Layout.fillWidth: true
            size: sg.size * 0.85
            implicitWidth: 120 * sg.size
            text: modelData[1]
            primary: sg.current === modelData[0]
            onClicked: sg.picked(modelData[0])
            Accessible.role: Accessible.RadioButton
            Accessible.checked: primary
        }
    }
}
