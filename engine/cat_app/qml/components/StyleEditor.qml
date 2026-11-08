import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Colour, shade, size and opacity of one of the cat's markers, with a live preview.
// vr: true uses big +/- steppers instead of sliders (easier with a laser pointer).
Rectangle {
    id: ed
    property string group: "cat"
    property string title: "Cat icon"
    property string note: ""
    property bool vr: false
    property real size: 1.0
    readonly property var st: backend.style[group] || ({})
    readonly property var lim: backend.limits
    radius: 14 * size
    color: Theme.panel
    implicitHeight: lay.implicitHeight + 32 * size

    function pct(v) { return Math.round(v * 100) + "%" }
    function shadeText(v) { return Math.abs(v) < 0.01 ? "normal" : (v > 0 ? "lighter " : "darker ") + Math.round(Math.abs(v) * 100) + "%" }

    ColumnLayout {
        id: lay
        anchors.fill: parent; anchors.margins: 16 * ed.size
        spacing: 12 * ed.size

        RowLayout {
            Layout.fillWidth: true
            spacing: 16 * ed.size
            Rectangle {  // preview, on a checkerboard-ish dark tile, at the chosen size and opacity
                Layout.preferredWidth: 120 * ed.size; Layout.preferredHeight: 120 * ed.size
                radius: 10 * ed.size; color: "#0d0f12"; border.color: Theme.line
                Image {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 8, 64 * ed.size * (ed.st.size || 1)); height: width
                    source: "image://cat/preview/" + ed.group + "/" + backend.previewRev
                    opacity: ed.st.opacity === undefined ? 1 : ed.st.opacity
                    fillMode: Image.PreserveAspectFit; cache: false; smooth: true
                    Accessible.name: ed.title + " preview"
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 4 * ed.size
                Text { text: ed.title; color: Theme.text; font.pixelSize: 22 * ed.size; font.weight: Font.Bold }
                Text { visible: ed.note !== ""; text: ed.note; color: Theme.muted; font.pixelSize: 14 * ed.size
                       wrapMode: Text.WordWrap; Layout.fillWidth: true }
                Text {
                    text: (ed.st.colour ? "Colour " + ed.st.colour : "Original colour") + " · " + ed.shadeText(ed.st.shade || 0)
                          + " · size " + ed.pct(ed.st.size || 1) + " · opacity " + ed.pct(ed.st.opacity === undefined ? 1 : ed.st.opacity)
                    color: Theme.muted; font.pixelSize: 14 * ed.size; wrapMode: Text.WordWrap; Layout.fillWidth: true
                }
            }
        }

        // colour swatches
        Flow {
            Layout.fillWidth: true
            spacing: 8 * ed.size
            Button {
                id: orig
                width: 108 * ed.size; height: (ed.vr ? 60 : 48) * ed.size
                hoverEnabled: true
                Accessible.name: "Original colour"
                onClicked: backend.setStyle(ed.group, "colour", null)
                contentItem: Text { text: "Original"; color: Theme.text; font.pixelSize: 15 * ed.size
                                    horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                background: Rectangle { radius: 10 * ed.size; color: Theme.panel2
                    border.width: !ed.st.colour ? 4 * ed.size : (orig.hovered ? 3 : 1)
                    border.color: !ed.st.colour ? Theme.text : (orig.hovered ? Theme.accent : Theme.line) }
            }
            Repeater {
                model: backend.palette
                Button {
                    id: sw
                    width: (ed.vr ? 60 : 48) * ed.size; height: width
                    hoverEnabled: true
                    Accessible.name: "Colour " + modelData
                    onClicked: backend.setStyle(ed.group, "colour", modelData)
                    background: Rectangle { radius: 10 * ed.size; color: modelData
                        border.width: ed.st.colour === modelData ? 4 * ed.size : (sw.hovered ? 3 : 1)
                        border.color: ed.st.colour === modelData ? Theme.text : (sw.hovered ? Theme.accent : Theme.line) }
                }
            }
        }

        // any colour: a hue slider (desktop only; the swatches are enough in VR)
        RowLayout {
            visible: !ed.vr
            Layout.fillWidth: true
            spacing: 12
            Text { text: "Any colour"; color: Theme.text; font.pixelSize: 16; Layout.preferredWidth: 110 }
            Slider {
                id: hue
                Layout.fillWidth: true
                from: 0; to: 359; stepSize: 1
                Accessible.name: "Colour hue"
                value: ed.st.colour ? Qt.color(ed.st.colour).hsvHue * 360 : 30
                onMoved: backend.setStyle(ed.group, "colour", Qt.hsva(value / 360, 0.75, 0.95, 1).toString())
                background: Rectangle {
                    x: hue.leftPadding; y: hue.topPadding + hue.availableHeight / 2 - height / 2
                    width: hue.availableWidth; height: 14; radius: 7
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0.0; color: Qt.hsva(0, 0.75, 0.95, 1) }
                        GradientStop { position: 0.17; color: Qt.hsva(0.17, 0.75, 0.95, 1) }
                        GradientStop { position: 0.33; color: Qt.hsva(0.33, 0.75, 0.95, 1) }
                        GradientStop { position: 0.5; color: Qt.hsva(0.5, 0.75, 0.95, 1) }
                        GradientStop { position: 0.67; color: Qt.hsva(0.67, 0.75, 0.95, 1) }
                        GradientStop { position: 0.83; color: Qt.hsva(0.83, 0.75, 0.95, 1) }
                        GradientStop { position: 1.0; color: Qt.hsva(1, 0.75, 0.95, 1) }
                    }
                }
            }
        }

        // shade, size, opacity: sliders on the desktop...
        GridLayout {
            visible: !ed.vr
            Layout.fillWidth: true
            columns: 3; columnSpacing: 12; rowSpacing: 4
            Text { text: "Shade"; color: Theme.text; font.pixelSize: 16; Layout.preferredWidth: 110 }
            Slider { Layout.fillWidth: true; from: ed.lim.shade[0]; to: ed.lim.shade[1]; stepSize: 0.05
                     value: ed.st.shade || 0; Accessible.name: "Shade, darker to lighter"
                     onMoved: backend.setStyle(ed.group, "shade", value) }
            Text { text: ed.shadeText(ed.st.shade || 0); color: Theme.muted; font.pixelSize: 15; Layout.preferredWidth: 110 }

            Text { text: "Size"; color: Theme.text; font.pixelSize: 16 }
            Slider { Layout.fillWidth: true; from: ed.lim.size[0]; to: ed.lim.size[1]; stepSize: 0.05
                     value: ed.st.size || 1; Accessible.name: "Size"
                     onMoved: backend.setStyle(ed.group, "size", value) }
            Text { text: ed.pct(ed.st.size || 1); color: Theme.muted; font.pixelSize: 15 }

            Text { text: "Opacity"; color: Theme.text; font.pixelSize: 16 }
            Slider { Layout.fillWidth: true; from: ed.lim.opacity[ed.group][0]; to: ed.lim.opacity[ed.group][1]; stepSize: 0.05
                     value: ed.st.opacity === undefined ? 1 : ed.st.opacity; Accessible.name: "Opacity"
                     onMoved: backend.setStyle(ed.group, "opacity", value) }
            Text { text: ed.pct(ed.st.opacity === undefined ? 1 : ed.st.opacity); color: Theme.muted; font.pixelSize: 15 }
        }

        // ...and big steppers in VR
        ColumnLayout {
            visible: ed.vr
            spacing: 10 * ed.size
            Stepper { size: ed.size; label: "Shade"; valueText: ed.shadeText(ed.st.shade || 0)
                      onMinus: backend.nudgeStyle(ed.group, "shade", -0.1); onPlus: backend.nudgeStyle(ed.group, "shade", 0.1) }
            Stepper { size: ed.size; label: "Size"; valueText: ed.pct(ed.st.size || 1)
                      onMinus: backend.nudgeStyle(ed.group, "size", -0.1); onPlus: backend.nudgeStyle(ed.group, "size", 0.1) }
            Stepper { size: ed.size; label: "Opacity"; valueText: ed.pct(ed.st.opacity === undefined ? 1 : ed.st.opacity)
                      onMinus: backend.nudgeStyle(ed.group, "opacity", -0.1); onPlus: backend.nudgeStyle(ed.group, "opacity", 0.1) }
        }

        BigButton {
            text: "Reset " + ed.title.toLowerCase()
            size: ed.vr ? ed.size : 0.8
            implicitWidth: 260 * size
            Layout.alignment: Qt.AlignRight
            onClicked: backend.resetStyle(ed.group)
        }
    }
}
