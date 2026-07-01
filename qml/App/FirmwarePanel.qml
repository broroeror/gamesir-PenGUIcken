import QtQuick

// Firmware update / flash. Pick a version from the local library and flash it
// (firmware-only, so calibration/settings are preserved), or back up the
// controller's current firmware. Drives bridge.flashFirmware / backupFirmware.
Column {
    id: panel
    spacing: 12
    property string status: ""
    property bool statusOk: true
    property string phase: ""
    property string selectedVersion: ""

    function _defaultSelection() {
        var vs = bridge.fwVersions
        if (vs.indexOf(bridge.firmware) >= 0) return bridge.firmware
        return vs.length > 0 ? vs[0] : ""
    }
    Component.onCompleted: selectedVersion = _defaultSelection()
    Connections {
        target: bridge
        function onFwVersionsChanged() {
            if (panel.selectedVersion === "" || bridge.fwVersions.indexOf(panel.selectedVersion) < 0)
                panel.selectedVersion = panel._defaultSelection()
        }
        function onFwProgress(p) { panel.phase = p }
        function onFwStatus(ok, msg) {
            panel.status = msg; panel.statusOk = ok; panel.phase = ""
        }
    }

    Text {
        width: parent.width; wrapMode: Text.WordWrap
        text: "Installed firmware: " + (bridge.firmware.length ? bridge.firmware : "—") +
              ".  Choose a version to flash (settings & calibration are kept), or " +
              "back up the current firmware to your library."
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }

    // version chips
    Flow {
        width: parent.width; spacing: 8
        Repeater {
            model: bridge.fwVersions
            delegate: Rectangle {
                required property string modelData
                readonly property bool sel: panel.selectedVersion === modelData
                readonly property bool installed: bridge.firmware === modelData
                height: 30; radius: 8
                width: vlabel.implicitWidth + 24
                color: sel ? Theme.accent : (chipHov.hovered ? Theme.cardHover : Theme.card)
                border.color: sel ? Theme.accent : Theme.cardBorder; border.width: 1
                opacity: bridge.fwBusy ? 0.5 : 1
                Behavior on color { ColorAnimation { duration: 120 } }
                Text {
                    id: vlabel; anchors.centerIn: parent
                    text: "v" + parent.modelData + (parent.installed ? "  •" : "")
                    color: parent.sel ? "white" : Theme.text
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                HoverHandler { id: chipHov }
                TapHandler { onTapped: if (!bridge.fwBusy) panel.selectedVersion = parent.modelData }
            }
        }
        Text {
            visible: bridge.fwVersions.length === 0
            text: "No firmware in your library yet — use “Back up current firmware”."
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        }
    }

    // actions
    Row {
        spacing: 8
        ConfirmButton {
            enabled: !bridge.fwBusy && panel.selectedVersion.length > 0
            opacity: enabled ? 1 : 0.5
            label: panel.selectedVersion.length ? "Flash v" + panel.selectedVersion : "Flash…"
            confirmLabel: "Flash v" + panel.selectedVersion + "?"
            onConfirmed: bridge.flashFirmware(panel.selectedVersion)
        }
        PillButton {
            label: "Back up current firmware"
            opacity: bridge.fwBusy ? 0.5 : 1
            onClicked: if (!bridge.fwBusy) bridge.backupFirmware("")
        }
    }

    // progress (indeterminate: a sweeping segment while busy) + phase text
    Rectangle {
        visible: bridge.fwBusy
        width: parent.width; height: 8; radius: 4; color: Theme.track; clip: true
        Rectangle {
            id: seg; height: parent.height; radius: 4; color: Theme.accent
            width: parent.width * 0.35
            SequentialAnimation on x {
                running: bridge.fwBusy; loops: Animation.Infinite
                NumberAnimation { from: -seg.width; to: panel.width; duration: 1100; easing.type: Easing.InOutQuad }
            }
        }
    }
    Text {
        visible: bridge.fwBusy
        text: panel.phase.length ? panel.phase : "Working…"
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }
    Text {
        visible: panel.status.length > 0 && !bridge.fwBusy
        width: parent.width; wrapMode: Text.WordWrap
        text: panel.status
        color: panel.statusOk ? Theme.ok : Theme.accent
        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }

    Text {
        width: parent.width; wrapMode: Text.WordWrap
        text: "⚠ Wired only: connect the controller with a USB cable, NOT the 2.4GHz " +
              "dongle. Flashing over the dongle writes to the dongle and bricks it — " +
              "the app will refuse it, but plug in directly to flash."
        color: Theme.warn; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
    }

    Text {
        width: parent.width; wrapMode: Text.WordWrap
        text: "Safe: an interrupted flash isn’t fatal — the controller re-enters its " +
              "loader on the next power-cycle so you can re-flash. Flashing briefly " +
              "disconnects the controller; don’t unplug until it finishes."
        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
        opacity: 0.8
    }
}
