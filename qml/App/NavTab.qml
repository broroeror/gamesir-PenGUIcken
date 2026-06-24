import QtQuick

// A top-nav item: icon glyph + label, with an animated active pill behind it.
Item {
    id: root
    property string label: ""
    property bool active: false
    signal clicked()

    implicitWidth: row.implicitWidth + 28
    implicitHeight: 38

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: root.active ? Theme.accent
                           : (hover.hovered ? Theme.cardHover : "transparent")
        Behavior on color { ColorAnimation { duration: 120 } }
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 7
        Text {
            text: root.label
            anchors.verticalCenter: parent.verticalCenter
            color: root.active ? "white" : Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontM
            font.weight: root.active ? Font.DemiBold : Font.Normal
        }
    }

    HoverHandler { id: hover }
    TapHandler { onTapped: root.clicked() }
}
