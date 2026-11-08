import QtQuick
import QtQuick.Layouts

// A value with big - and + buttons: easier than a slider with a laser pointer.
RowLayout {
    id: st
    property string label
    property string valueText
    property real size: 1.0
    property real labelWidth: 130
    signal minus()
    signal plus()
    spacing: 10 * size
    Text { text: st.label; color: Theme.text; font.pixelSize: 18 * st.size; Layout.preferredWidth: st.labelWidth * st.size
           wrapMode: Text.WordWrap; opacity: st.enabled ? 1 : 0.5 }
    BigButton { text: "−"; size: st.size; implicitWidth: 76 * st.size; onClicked: st.minus(); Accessible.name: "Less " + st.label }
    Text { text: st.valueText; color: Theme.text; font.pixelSize: 20 * st.size; font.weight: Font.DemiBold
           horizontalAlignment: Text.AlignHCenter; Layout.preferredWidth: 150 * st.size }
    BigButton { text: "+"; size: st.size; implicitWidth: 76 * st.size; onClicked: st.plus(); Accessible.name: "More " + st.label }
}
