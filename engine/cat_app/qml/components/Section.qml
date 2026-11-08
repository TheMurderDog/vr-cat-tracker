import QtQuick
import QtQuick.Layouts

// A panel with a title and an optional note, holding a column of settings.
Rectangle {
    id: sec
    property string title
    property string note: ""
    property real size: 1.0
    default property alias content: inner.data
    radius: 14 * size
    color: Theme.panel
    implicitHeight: lay.implicitHeight + 32 * size
    ColumnLayout {
        id: lay
        anchors.fill: parent; anchors.margins: 16 * sec.size
        spacing: 10 * sec.size
        Text { text: sec.title; color: Theme.text; font.pixelSize: 22 * sec.size; font.weight: Font.Bold }
        Text { visible: sec.note !== ""; text: sec.note; color: Theme.muted; font.pixelSize: 14 * sec.size
               wrapMode: Text.WordWrap; Layout.fillWidth: true }
        ColumnLayout { id: inner; Layout.fillWidth: true; spacing: 10 * sec.size }
    }
}
