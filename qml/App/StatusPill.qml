import QtQuick

// Connection + battery + firmware readout, plus a wrong-mode warning.
// `compact` (narrow windows) drops the firmware text and shrinks the wrong-mode
// warning to a bare ⚠ so the settings gear never gets pushed off the bar.
Row {
    property bool compact: false
    spacing: compact ? 8 : 14

    // Connection dot
    Row {
        spacing: 6
        anchors.verticalCenter: parent.verticalCenter
        Rectangle {
            width: 9; height: 9; radius: 5
            anchors.verticalCenter: parent.verticalCenter
            color: bridge.connected ? Theme.ok : Theme.textFaint
        }
        Text {
            text: bridge.connected ? "Connected" : "Searching…"
            color: Theme.textDim
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            anchors.verticalCenter: parent.verticalCenter
        }
    }

    // Battery
    Text {
        visible: bridge.connected
        anchors.verticalCenter: parent.verticalCenter
        text: (bridge.charging ? "⚡ " : "") + bridge.battery + "%"
        color: bridge.battery <= 15 && !bridge.charging ? Theme.accent : Theme.textDim
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }

    // Firmware (hidden when compact to reclaim space)
    Text {
        visible: bridge.firmware.length > 0 && !parent.compact
        anchors.verticalCenter: parent.verticalCenter
        text: "fw " + bridge.firmware
        color: Theme.textFaint
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }

    // Wrong-mode warning: a compact ⚠ chip that never grows the bar (so it can't
    // push the settings gear off-screen); the full guidance shows on hover.
    Item {
        visible: bridge.connected && !bridge.modeOk
        anchors.verticalCenter: parent.verticalCenter
        implicitWidth: 26; implicitHeight: 22
        Rectangle {
            id: warnChip
            anchors.fill: parent
            radius: 6; color: "#3A2A14"; border.color: Theme.warn; border.width: 1
            Text {
                anchors.centerIn: parent
                text: "⚠"
                color: Theme.warn
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
            }
            HoverHandler { id: warnHov }
        }
        Rectangle {
            visible: warnHov.hovered
            z: 1000
            width: 240; height: wtip.implicitHeight + 20
            radius: Theme.radiusSm
            color: Theme.card; border.color: Theme.cardBorder; border.width: 1
            y: warnChip.height + 8
            x: warnChip.width - width       // hug the right edge of the bar
            Text {
                id: wtip
                anchors.fill: parent; anchors.margins: 10
                text: "Not in Xbox mode. Hold the green ● button ~2s to switch " +
                      "to Xbox/XInput mode so the app can read the controller."
                color: Theme.text; wrapMode: Text.WordWrap
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                lineHeight: 1.2
            }
        }
    }
}
