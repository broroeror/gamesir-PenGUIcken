import QtQuick

// Styled on/off switch. Emits toggled(checked) on tap.
Item {
    id: sw
    property bool checked: false
    signal toggled(bool checked)

    implicitWidth: 42; implicitHeight: 23

    Rectangle {
        anchors.fill: parent; radius: height / 2
        color: sw.checked ? Theme.accent : Theme.track
        Behavior on color { ColorAnimation { duration: 120 } }
    }
    Rectangle {
        width: parent.height - 6; height: width; radius: width / 2; color: "white"
        y: 3
        x: sw.checked ? parent.width - width - 3 : 3
        Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
    }
    TapHandler { onTapped: { sw.checked = !sw.checked; sw.toggled(sw.checked) } }
}
