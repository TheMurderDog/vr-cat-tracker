import QtQuick

// The room from above: the floor the cameras cover, the cameras, you (with the way you're facing),
// and the cat with its recent trail.
Rectangle {
    id: m
    property real size: 1.0
    radius: 14 * size
    color: Theme.panel
    Accessible.role: Accessible.Graphic
    Accessible.name: "Room map. " + backend.headline

    Connections { target: backend; function onStatusChanged() { cv.requestPaint() } }
    Connections { target: backend; function onStyleChanged() { cv.requestPaint() } }
    Connections { target: backend; function onHeatChanged() { cv.requestPaint() } }
    Connections { target: backend; function onSettingsChanged() { cv.requestPaint() } }
    readonly property string heatMode: backend.settings.map ? backend.settings.map.heat : "off"

    // green (steady) -> yellow -> red (jittery), by wobble in cm
    function wobbleColour(w, a) {
        var t = Math.max(0, Math.min(1, (w - 2) / 8))
        var r = t < 0.5 ? 0.25 + 1.4 * t : 0.95
        var g = t < 0.5 ? 0.75 : 0.75 - 1.3 * (t - 0.5)
        return Qt.rgba(r, g, 0.25, a)
    }

    // heatmap choice, top right: small, but each word is a big enough target for a laser
    Row {
        anchors.right: parent.right; anchors.top: parent.top
        anchors.rightMargin: 12 * m.size; anchors.topMargin: 6 * m.size
        spacing: 4 * m.size
        Text { text: "Heatmap:"; color: Theme.muted; font.pixelSize: 14 * m.size; height: 30 * m.size; verticalAlignment: Text.AlignVCenter }
        Repeater {
            model: [["off", "off"], ["time", "time"], ["wobble", "wobble"]]
            Rectangle {
                width: lbl.implicitWidth + 18 * m.size; height: 30 * m.size; radius: 8 * m.size
                color: m.heatMode === modelData[0] ? Theme.panel2 : "transparent"
                border.color: ma.containsMouse ? Theme.accent : (m.heatMode === modelData[0] ? Theme.line : "transparent")
                Text { id: lbl; anchors.centerIn: parent; text: modelData[1]; font.pixelSize: 14 * m.size
                       color: m.heatMode === modelData[0] ? Theme.text : Theme.muted }
                MouseArea { id: ma; anchors.fill: parent; hoverEnabled: true; onClicked: backend.setSetting("map.heat", modelData[0]) }
                Accessible.role: Accessible.RadioButton; Accessible.name: "Heatmap " + modelData[1]
            }
        }
    }

    Text {
        x: 16 * m.size; y: 12 * m.size
        text: "Room from above"
        color: Theme.muted; font.pixelSize: 15 * m.size
    }
    Text {
        id: legend
        visible: m.heatMode !== "off" && !!backend.heat.bounds
        anchors.left: parent.left; anchors.bottom: parent.bottom
        anchors.leftMargin: 16 * m.size; anchors.bottomMargin: 10 * m.size
        text: m.heatMode === "time" ? "Heatmap: brighter = more time spent there"
                                    : "Heatmap: green = steady tracking, red = jittery (may need more training pictures)"
        color: Theme.muted; font.pixelSize: 13 * m.size
    }
    Canvas {
        id: cv
        anchors.fill: parent; anchors.margins: 16 * m.size; anchors.topMargin: 38 * m.size
        anchors.bottomMargin: (legend.visible ? 34 : 16) * m.size
        onWidthChanged: requestPaint(); onHeightChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var st = backend.status, room = st.room
            var k = m.size
            if (!room || !room.bounds) {
                ctx.fillStyle = Theme.muted; ctx.font = (16 * k) + "px sans-serif"; ctx.textAlign = "center"
                ctx.fillText("The map appears once the tracker runs.", width / 2, height / 2)
                return
            }
            var b = room.bounds, pad = 24 * k
            var w = b[1] - b[0], d = b[3] - b[2]
            var s = Math.min((width - 2 * pad) / w, (height - 2 * pad) / d)
            var ox = (width - w * s) / 2, oz = (height - d * s) / 2
            function X(x) { return ox + (x - b[0]) * s }
            function Z(z) { return oz + (z - b[2]) * s }
            // floor
            ctx.fillStyle = Theme.panel2; ctx.strokeStyle = Theme.line; ctx.lineWidth = 2 * k
            ctx.beginPath(); ctx.rect(X(b[0]), Z(b[2]), w * s, d * s); ctx.fill(); ctx.stroke()
            // 1 m grid
            ctx.strokeStyle = Qt.rgba(1, 1, 1, 0.05); ctx.lineWidth = 1
            for (var gx = Math.ceil(b[0]); gx < b[1]; gx++) { ctx.beginPath(); ctx.moveTo(X(gx), Z(b[2])); ctx.lineTo(X(gx), Z(b[3])); ctx.stroke() }
            for (var gz = Math.ceil(b[2]); gz < b[3]; gz++) { ctx.beginPath(); ctx.moveTo(X(b[0]), Z(gz)); ctx.lineTo(X(b[1]), Z(gz)); ctx.stroke() }
            // heatmap: where the cat spends time, or where the tracking wobbles
            var hm = backend.heat
            if (m.heatMode !== "off" && hm && hm.bounds && hm.time) {
                var hb = hm.bounds, cs = hm.cell
                for (var hi = 0; hi < hm.time.length; hi++) {
                    for (var hj = 0; hj < hm.time[hi].length; hj++) {
                        var hx0 = hb[0] + hj * cs, hz0 = hb[2] + hi * cs
                        if (m.heatMode === "time") {
                            var tv = hm.time[hi][hj]
                            if (tv <= 0.02) continue
                            ctx.fillStyle = Qt.rgba(0.94, 0.59, 0.24, 0.12 + 0.5 * tv)
                        } else {
                            var wv = hm.wobble_cm[hi][hj]
                            if (wv <= 0) continue
                            ctx.fillStyle = m.wobbleColour(wv, 0.22 + 0.4 * Math.min(1, wv / 10))
                        }
                        ctx.fillRect(X(hx0), Z(hz0), cs * s + 0.5, cs * s + 0.5)
                    }
                }
            }
            // cameras
            var names = (st.cameras && st.cameras.names) || [], stale = (st.cameras && st.cameras.stale) || []
            for (var i = 0; i < (room.cameras || []).length; i++) {
                var c = room.cameras[i]
                ctx.fillStyle = stale.indexOf(i) >= 0 ? Theme.alert : Theme.muted
                ctx.beginPath(); ctx.arc(X(c[0]), Z(c[1]), 7 * k, 0, 2 * Math.PI); ctx.fill()
                ctx.font = (12 * k) + "px sans-serif"; ctx.textAlign = "center"
                ctx.fillText(names[i] || ("cam " + (i + 1)), X(c[0]), Z(c[1]) + (c[1] < (b[2] + b[3]) / 2 ? -12 : 22) * k)
            }
            // you
            var head = st.head
            if (head && head.pos) {
                var hx = X(head.pos[0]), hz = Z(head.pos[2])
                var fw = head.fwd, fl = Math.sqrt(fw[0] * fw[0] + fw[1] * fw[1]) || 1
                var a = Math.atan2(fw[1] / fl, fw[0] / fl)
                ctx.fillStyle = Qt.rgba(0.29, 0.56, 0.88, 0.28)
                ctx.beginPath(); ctx.moveTo(hx, hz); ctx.arc(hx, hz, 46 * k, a - 0.5, a + 0.5); ctx.closePath(); ctx.fill()
                ctx.fillStyle = Theme.info
                ctx.beginPath(); ctx.arc(hx, hz, 10 * k, 0, 2 * Math.PI); ctx.fill()
                ctx.fillStyle = Theme.text; ctx.font = (12 * k) + "px sans-serif"; ctx.textAlign = "center"
                ctx.fillText("you", hx, hz + 26 * k)
            }
            // the cat's trail
            var tr = backend.trail
            if (tr.length > 1) {
                ctx.lineWidth = 3 * k; ctx.lineCap = "round"
                if (backend.settings.map && backend.settings.map.trail_wobble) {  // each piece coloured by its wobble
                    for (var j = 1; j < tr.length; j++) {
                        ctx.strokeStyle = m.wobbleColour(tr[j][2] || 0, 0.75)
                        ctx.beginPath(); ctx.moveTo(X(tr[j - 1][0]), Z(tr[j - 1][1])); ctx.lineTo(X(tr[j][0]), Z(tr[j][1])); ctx.stroke()
                    }
                } else {
                    ctx.strokeStyle = Qt.rgba(0.94, 0.59, 0.24, 0.45)
                    ctx.beginPath(); ctx.moveTo(X(tr[0][0]), Z(tr[0][1]))
                    for (var jj = 1; jj < tr.length; jj++) ctx.lineTo(X(tr[jj][0]), Z(tr[jj][1]))
                    ctx.stroke()
                }
            }
            // the cat
            var cat = st.cat
            if (cat && cat.pos && cat.state !== "hidden") {
                var cx = X(cat.pos[0]), cz = Z(cat.pos[2])
                var col = cat.level ? Theme.alert : ((backend.style.cat && backend.style.cat.colour) || Theme.accent)
                ctx.globalAlpha = cat.state === "lost" ? 0.45 : 1
                ctx.fillStyle = col
                ctx.beginPath(); ctx.arc(cx, cz, 13 * k, 0, 2 * Math.PI); ctx.fill()
                ctx.strokeStyle = "white"; ctx.lineWidth = 2.5 * k; ctx.stroke()
                ctx.fillStyle = Theme.text; ctx.font = "bold " + (13 * k) + "px sans-serif"; ctx.textAlign = "center"
                ctx.fillText(cat.state === "lost" ? "cat (last seen)" : "cat", cx, cz - 20 * k)
                ctx.globalAlpha = 1
            }
        }
    }
}
