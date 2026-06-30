import QtQuick

// A small "?" badge that shows an explanatory bubble on hover. Pure QML (the app
// doesn't use QtQuick.Controls), styled to match the dark theme. The bubble is
// drawn below the badge; give the hosting bar a high z so it floats over siblings.
Item {
    id: help
    property string text: ""
    property int bubbleWidth: 260
    // Which side the bubble hugs: by default its right edge aligns with the badge
    // (good near the right of a bar). Set false to align the left edge instead.
    property bool alignRight: true

    implicitWidth: 16
    implicitHeight: 16

    Rectangle {
        id: badge
        anchors.fill: parent
        radius: width / 2
        color: hov.hovered ? Theme.accent : Theme.track
        Behavior on color { ColorAnimation { duration: 120 } }
        Text {
            anchors.centerIn: parent
            text: "?"
            color: hov.hovered ? "white" : Theme.textDim
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontS
            font.bold: true
        }
        HoverHandler { id: hov }
    }

    Rectangle {
        id: bubble
        visible: hov.hovered
        z: 1000
        width: help.bubbleWidth
        height: tip.implicitHeight + 20
        radius: Theme.radiusSm
        color: Theme.card
        border.color: Theme.cardBorder
        border.width: 1
        y: badge.height + 8
        x: help.alignRight ? badge.width - width : 0

        Text {
            id: tip
            anchors.fill: parent
            anchors.margins: 10
            text: help.text
            color: Theme.text
            wrapMode: Text.WordWrap
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontS
            lineHeight: 1.2
        }
    }
}
