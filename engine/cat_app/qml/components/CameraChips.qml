import QtQuick

// One chip per camera: green when it's sending pictures, red when it stopped.
Flow {
    id: f
    property real size: 1.0
    spacing: 8 * size
    Repeater {
        model: backend.cameraList
        Rectangle {
            height: 34 * f.size; width: label.implicitWidth + 40 * f.size; radius: height / 2
            color: Theme.panel2; border.color: modelData.ok ? Theme.ok : Theme.alert; border.width: 2
            Accessible.role: Accessible.StaticText
            Accessible.name: modelData.name + (modelData.ok ? " working" : " not sending pictures")
            Rectangle { x: 12 * f.size; anchors.verticalCenter: parent.verticalCenter; width: 10 * f.size; height: width; radius: width / 2
                        color: modelData.ok ? Theme.ok : Theme.alert }
            Text { id: label; x: 28 * f.size; anchors.verticalCenter: parent.verticalCenter
                   text: modelData.name + (modelData.ok ? "" : " (stopped)")
                   color: Theme.text; font.pixelSize: 14.5 * f.size }
        }
    }
    Text {
        visible: backend.cameraList.length === 0
        text: "Cameras show here once the tracker runs."
        color: Theme.muted; font.pixelSize: 14.5 * f.size
    }
}
