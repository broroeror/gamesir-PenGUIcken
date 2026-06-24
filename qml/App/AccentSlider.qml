import QtQuick

// Minimal styled slider. Emits moved(value) live while dragging.
Item {
    id: s
    property real from: 0
    property real to: 100
    property real value: 0
    property bool integer: true
    signal moved(real value)

    implicitHeight: 18
    readonly property real frac: to > from ? (value - from) / (to - from) : 0

    Rectangle {
        id: track
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width; height: 6; radius: 3; color: Theme.track
        Rectangle {
            height: parent.height; radius: 3; color: Theme.accent
            width: parent.width * Math.max(0, Math.min(1, s.frac))
        }
    }
    Rectangle {
        width: 16; height: 16; radius: 8; color: "white"
        border.color: Theme.accent; border.width: 2
        y: (parent.height - height) / 2
        x: Math.max(0, Math.min(track.width - width, s.frac * track.width - width / 2))
    }
    MouseArea {
        anchors.fill: parent
        function upd(mx) {
            var f = Math.max(0, Math.min(1, mx / track.width))
            var v = s.from + f * (s.to - s.from)
            if (s.integer) v = Math.round(v)
            if (v !== s.value) { s.value = v; s.moved(v) }
        }
        onPressed: upd(mouseX)
        onPositionChanged: if (pressed) upd(mouseX)
    }
}
