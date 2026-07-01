import QtQuick

// Profile 1-4 selector. Highlights the controller's *actual* active profile
// (bridge.profile) and switches on tap (bridge.setProfile).
Row {
    id: root
    // Compact mode shrinks the pills ("P1".."P4") so the top bar fits at narrow
    // window widths; full "Profile N" labels are shown when there's room.
    property bool compact: false
    spacing: compact ? 5 : 8
    Repeater {
        model: 4
        delegate: Rectangle {
            required property int index
            property int n: index + 1
            property bool active: bridge.profile === n
            width: root.compact ? 40 : 92; height: 32; radius: 8
            color: active ? Theme.accent
                          : (hov.hovered ? Theme.cardHover : Theme.card)
            border.color: active ? Qt.lighter(Theme.accent, 1.2) : Theme.cardBorder
            border.width: 1
            Behavior on color { ColorAnimation { duration: 120 } }
            Text {
                anchors.centerIn: parent
                text: root.compact ? ("P" + parent.n) : ("Profile " + parent.n)
                color: parent.active ? "white" : Theme.textDim
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontM
                font.weight: parent.active ? Font.DemiBold : Font.Normal
            }
            HoverHandler { id: hov }
            TapHandler { onTapped: bridge.setProfile(parent.n) }
        }
    }
}
