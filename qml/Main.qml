import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import App 1.0

Window {
    id: win
    width: 1040
    height: 680
    minimumWidth: 900
    minimumHeight: 600
    visible: true
    color: Theme.bg
    title: "GameSir Cyclone 2"

    property int currentTab: 0
    readonly property var tabs: ["Buttons", "Sticks", "Motion", "Triggers", "Vibration", "Lights"]

    // Faint red glow in the top-left corner, like the first-party app.
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: Qt.rgba(0.16, 0.08, 0.09, 1) }
            GradientStop { position: 0.45; color: Theme.bg }
            GradientStop { position: 1.0; color: Theme.bg }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ---------------------------------------------------------- top bar
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 58
            color: Theme.navBar
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 20
                anchors.rightMargin: 20
                spacing: 18

                // Logo
                RowLayout {
                    spacing: 8
                    Rectangle {
                        width: 26; height: 26; radius: 6; color: Theme.accent
                        Text { anchors.centerIn: parent; text: "G"; color: "white"
                               font.bold: true; font.pixelSize: 16 }
                    }
                    Text {
                        text: "GAMESIR"
                        color: Theme.text
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontL
                        font.weight: Font.Bold
                        font.letterSpacing: 1
                    }
                }

                ProfileBar {}

                Item { Layout.fillWidth: true }

                StatusPill {}
            }
        }

        // ------------------------------------------------------------- nav
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 52
            color: Theme.bg
            Row {
                anchors.centerIn: parent
                spacing: 6
                Repeater {
                    model: win.tabs
                    delegate: NavTab {
                        required property int index
                        required property string modelData
                        label: modelData
                        active: win.currentTab === index
                        onClicked: win.currentTab = index
                    }
                }
            }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width
                        height: 1; color: Theme.cardBorder }
        }

        // --------------------------------------------------------- content
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            // Buttons tab: live controller centered, with side panels (M1 shows
            // the controller; side cards fill in as later sections land).
            RowLayout {
                anchors.fill: parent
                anchors.margins: 20
                spacing: 16
                visible: win.currentTab === 0

                ColumnLayout {
                    Layout.fillWidth: false
                    Layout.minimumWidth: 240
                    Layout.preferredWidth: 240
                    Layout.maximumWidth: 240
                    Layout.fillHeight: true
                    spacing: 16
                    Card {
                        title: "Live input"
                        Layout.fillWidth: true
                        Text {
                            width: parent.width
                            wrapMode: Text.WordWrap
                            text: "Press buttons and move the sticks — the " +
                                  "controller view reflects them in real time."
                            color: Theme.textDim
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontM
                        }
                    }
                    Item { Layout.fillHeight: true }
                }

                // Center controller
                Item {
                    id: centerArea
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Column {
                        anchors.centerIn: parent
                        spacing: 10
                        ControllerView {
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: Math.min(implicitWidth, centerArea.width - 24)
                            height: width / aspect
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "CYCLONE 2"
                            color: Theme.textDim
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontL
                            font.weight: Font.Bold
                            font.letterSpacing: 2
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: false
                    Layout.minimumWidth: 240
                    Layout.preferredWidth: 240
                    Layout.maximumWidth: 240
                    Layout.fillHeight: true
                    spacing: 16
                    Card {
                        title: "Buttons"
                        Layout.fillWidth: true
                        Text {
                            width: parent.width
                            wrapMode: Text.WordWrap
                            text: "Remap and shift-layer assignment land here in a " +
                                  "later milestone."
                            color: Theme.textDim
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontM
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }

            // Lights tab.
            LightsPage {
                anchors.fill: parent
                visible: win.currentTab === 5
            }

            // Placeholder for the not-yet-built sections (Sticks/Motion/Triggers/Vibration).
            Item {
                anchors.fill: parent
                visible: win.currentTab !== 0 && win.currentTab !== 5
                Card {
                    anchors.centerIn: parent
                    width: 420
                    title: win.tabs[win.currentTab]
                    Text {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: "The “" + win.tabs[win.currentTab] + "” section is " +
                              "coming in a later milestone. The foundation " +
                              "(theme, nav, live input, profile switching) is in place."
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontM
                    }
                }
            }
        }
    }
}
