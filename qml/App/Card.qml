import QtQuick

// A titled panel. Use `title` for the small header row (with optional icon glyph
// via `headerColor`), then put content in `default` children which flow into the
// inner column.
Rectangle {
    id: root
    property string title: ""
    property alias content: body.data
    property int spacing: Theme.gap
    default property alias _children: body.data

    color: Theme.card
    border.color: Theme.cardBorder
    border.width: 1
    radius: Theme.radius
    implicitHeight: layout.implicitHeight + Theme.pad * 2

    Column {
        id: layout
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.gap

        Row {
            visible: root.title.length > 0
            spacing: 8
            Rectangle {            // small accent tick before the title
                width: 4; height: 14; radius: 2
                anchors.verticalCenter: parent.verticalCenter
                color: Theme.accent
            }
            Text {
                text: root.title
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontL
                font.weight: Font.DemiBold
            }
        }

        Column {
            id: body
            width: parent.width
            spacing: root.spacing
        }
    }
}
