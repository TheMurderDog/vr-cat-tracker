import QtQuick
import QtQuick.Controls

// A large, high-contrast button. Big enough to hit easily with a SteamVR laser pointer.
Button {
    id: b
    property color tone: Theme.panel2
    property color toneText: Theme.text
    property bool primary: false
    property real size: 1.0           // 1 on the desktop, about 1.6 in VR
    property string hint: ""          // second, smaller line
    implicitHeight: (hint ? 76 : 58) * size
    implicitWidth: 180 * size
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: text
    Accessible.description: hint
    contentItem: Item {
      implicitWidth: col.implicitWidth; implicitHeight: col.implicitHeight
      Column {
        id: col
        spacing: 2 * b.size
        anchors.centerIn: parent
        Text {
            text: b.text
            width: b.width - 24 * b.size
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: 19 * b.size; font.weight: Font.DemiBold
            color: b.primary ? Theme.accentText : b.toneText
            opacity: b.enabled ? 1 : 0.45
            elide: Text.ElideRight
        }
        Text {
            visible: b.hint !== ""
            text: b.hint
            width: b.width - 24 * b.size
            horizontalAlignment: Text.AlignHCenter
            font.pixelSize: 13.5 * b.size
            color: b.primary ? Theme.accentText : Theme.muted
            opacity: b.enabled ? 0.85 : 0.4
            elide: Text.ElideRight
        }
      }
    }
    background: Rectangle {
        radius: 12 * b.size
        color: b.primary ? Theme.accent : b.tone
        opacity: b.enabled ? 1 : 0.5
        border.width: b.visualFocus || b.hovered ? 3 * b.size : 1
        border.color: b.hovered || b.visualFocus ? Theme.accent : Theme.line
        Rectangle {  // pressed feedback
            anchors.fill: parent; radius: parent.radius
            color: "white"; opacity: b.down ? 0.18 : (b.hovered ? 0.06 : 0)
        }
    }
}
