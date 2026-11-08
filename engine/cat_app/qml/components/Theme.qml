pragma Singleton
import QtQuick

// Colours and sizes shared by the desktop window and the VR tab.
QtObject {
    readonly property color bg: "#16181d"
    readonly property color panel: "#20242b"
    readonly property color panel2: "#2a2f38"
    readonly property color line: "#363c47"
    readonly property color text: "#f2f3f5"
    readonly property color muted: "#a9b0bb"
    readonly property color accent: "#f0973c"      // the cat's orange
    readonly property color accentText: "#1b1205"
    readonly property color ok: "#3fb27f"
    readonly property color info: "#4a8fe0"
    readonly property color warn: "#e0a83a"
    readonly property color alert: "#e5484d"
    readonly property color off: "#5b626d"
    function levelColour(level) {
        return level === "ok" ? ok : level === "warn" ? warn : level === "alert" ? alert : level === "info" ? info : off
    }
}
