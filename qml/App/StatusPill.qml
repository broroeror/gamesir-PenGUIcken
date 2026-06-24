import QtQuick

// Connection + battery + firmware readout, plus a wrong-mode warning.
Row {
    spacing: 14

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

    // Firmware
    Text {
        visible: bridge.firmware.length > 0
        anchors.verticalCenter: parent.verticalCenter
        text: "fw " + bridge.firmware
        color: Theme.textFaint
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }

    // Wrong-mode warning
    Rectangle {
        visible: bridge.connected && !bridge.modeOk
        anchors.verticalCenter: parent.verticalCenter
        radius: 6; color: "#3A2A14"; border.color: Theme.warn; border.width: 1
        implicitWidth: warnText.implicitWidth + 16; height: 22
        Text {
            id: warnText
            anchors.centerIn: parent
            text: "⚠ Hold the green button ~2s for Xbox mode"
            color: Theme.warn
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        }
    }
}
