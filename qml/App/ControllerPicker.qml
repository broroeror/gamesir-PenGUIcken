import QtQuick
import App 1.0

// Top-bar selector for WHICH connected controller the app drives. Lists
// bridge.controllers and switches via bridge.selectController(id). Shows the
// current controller's name always; the dropdown is only interactive when more
// than one controller is connected (identical models are labelled by USB port).
Item {
    id: root
    property var list: bridge.controllers
    property string current: bridge.selectedController
    property bool multi: list.length > 1
    property bool open: false

    visible: list.length > 0
    implicitWidth: btn.width
    implicitHeight: btn.height
    onListChanged: if (!multi) open = false

    function labelFor(id) {
        for (var i = 0; i < list.length; i++)
            if (list[i].id === id) return list[i].label
        return list.length > 0 ? list[0].label : ""
    }

    Rectangle {
        id: btn
        width: Math.max(120, txt.implicitWidth + (root.multi ? 56 : 32))
        height: 32; radius: 8
        color: (hov.hovered || root.open) ? Theme.cardHover : Theme.card
        border.color: Theme.cardBorder; border.width: 1
        Behavior on color { ColorAnimation { duration: 120 } }
        Row {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left; anchors.leftMargin: 12
            spacing: 8
            Rectangle { width: 8; height: 8; radius: 4; color: Theme.accent
                        anchors.verticalCenter: parent.verticalCenter }
            Text {
                id: txt
                text: root.labelFor(root.current)
                color: Theme.text
                font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
            }
        }
        Text {
            visible: root.multi
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right; anchors.rightMargin: 10
            text: root.open ? "▴" : "▾"; color: Theme.textDim; font.pixelSize: 12
        }
        HoverHandler { id: hov }
        TapHandler { enabled: root.multi; onTapped: root.open = !root.open }
    }

    // Dropdown list — overlays the content below the bar.
    Rectangle {
        visible: root.open && root.multi
        z: 1000
        y: btn.height + 4
        width: Math.max(btn.width, 220)
        height: col.implicitHeight
        radius: 8
        color: Theme.card
        border.color: Theme.cardBorder; border.width: 1
        Column {
            id: col
            width: parent.width
            topPadding: 4; bottomPadding: 4
            Repeater {
                model: root.list
                delegate: Rectangle {
                    required property var modelData
                    x: 4
                    width: col.width - 8
                    height: 30; radius: 6
                    property bool sel: modelData.id === root.current
                    color: sel ? Theme.accent
                                : (ihov.hovered ? Theme.cardHover : "transparent")
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.left: parent.left; anchors.leftMargin: 10
                        text: modelData.label
                        color: parent.sel ? "white" : Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    }
                    HoverHandler { id: ihov }
                    TapHandler {
                        onTapped: { bridge.selectController(modelData.id); root.open = false }
                    }
                }
            }
        }
    }
}
