import QtQuick

// Compact HSV picker: a saturation/value square + a hue strip. Holds hue/sat/val
// as the source of truth; `color` is derived. Call setColor(c) to seed it from
// an existing color (string or color). Emits edited(color) live while dragging.
Item {
    id: cp
    property real hue: 0      // 0..1
    property real sat: 1
    property real val: 1
    readonly property color color: Qt.hsva(hue, sat, val, 1)
    signal edited(color c)

    implicitHeight: sv.height + hueBar.height + 10

    property color _probe: "#000000"
    function setColor(c) {
        _probe = c
        if (_probe.hsvSaturation > 0.0001 && _probe.hsvValue > 0.0001 && _probe.hsvHue >= 0)
            hue = _probe.hsvHue
        sat = _probe.hsvSaturation
        val = _probe.hsvValue
    }
    function _emit() { cp.edited(cp.color) }

    // saturation (x) / value (y) square
    Rectangle {
        id: sv
        width: parent.width; height: Math.round(parent.width * 0.62)
        radius: 6; clip: true
        color: Qt.hsva(cp.hue, 1, 1, 1)
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "#ffffffff" }
                GradientStop { position: 1.0; color: "#00ffffff" }
            }
        }
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                orientation: Gradient.Vertical
                GradientStop { position: 0.0; color: "#00000000" }
                GradientStop { position: 1.0; color: "#ff000000" }
            }
        }
        Rectangle {                       // thumb
            width: 14; height: 14; radius: 7; color: "transparent"
            border.color: "white"; border.width: 2
            x: cp.sat * parent.width - width / 2
            y: (1 - cp.val) * parent.height - height / 2
        }
        MouseArea {
            anchors.fill: parent
            function upd(mx, my) {
                cp.sat = Math.max(0, Math.min(1, mx / width))
                cp.val = Math.max(0, Math.min(1, 1 - my / height))
                cp._emit()
            }
            onPressed: upd(mouseX, mouseY)
            onPositionChanged: if (pressed) upd(mouseX, mouseY)
        }
    }

    // hue strip
    Rectangle {
        id: hueBar
        anchors.top: sv.bottom; anchors.topMargin: 10
        width: parent.width; height: 14; radius: 7
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.00; color: "#ff0000" }
            GradientStop { position: 0.17; color: "#ffff00" }
            GradientStop { position: 0.33; color: "#00ff00" }
            GradientStop { position: 0.50; color: "#00ffff" }
            GradientStop { position: 0.67; color: "#0000ff" }
            GradientStop { position: 0.83; color: "#ff00ff" }
            GradientStop { position: 1.00; color: "#ff0000" }
        }
        Rectangle {
            width: 6; height: parent.height + 6; radius: 3
            color: "white"; border.color: "#333"; border.width: 1
            x: cp.hue * parent.width - width / 2; y: -3
        }
        MouseArea {
            anchors.fill: parent
            function upd(mx) { cp.hue = Math.max(0, Math.min(1, mx / width)); cp._emit() }
            onPressed: upd(mouseX)
            onPositionChanged: if (pressed) upd(mouseX)
        }
    }
}
