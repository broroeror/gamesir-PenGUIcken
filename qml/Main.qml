import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import App 1.0

Window {
    id: win
    width: 1040
    height: 720
    minimumWidth: 840
    minimumHeight: 620
    visible: true
    color: Theme.bg
    title: "GameSir Cyclone 2"

    property int currentTab: 0
    property bool settingsOpen: false
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
            z: 100   // keep the mouse-mode help tooltip above the nav/content below
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

                ControllerPicker { Layout.alignment: Qt.AlignVCenter }

                ProfileBar {}

                Item { Layout.fillWidth: true }

                // Loads/unloads KDE's Game Controller (KWin) plugin so the
                // sticks drive the desktop cursor. Labelled by what it does, with
                // a help icon spelling out the plugin + on/off behaviour.
                Row {
                    visible: bridge.mouseModeAvailable
                    Layout.alignment: Qt.AlignVCenter
                    spacing: 8
                    Text {
                        text: "Sticks → cursor"; color: Theme.textDim
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    HelpIcon {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Toggles KDE's Game Controller (KWin) plugin.\n\n" +
                              "On: the controller's sticks move your mouse pointer " +
                              "and the triggers click — handy from the couch.\n\n" +
                              "Off: the controller acts as a normal gamepad (games " +
                              "still read it directly).\n\n" +
                              "Same setting as System Settings → Game Controller; " +
                              "applied live and remembered."
                    }
                    ToggleSwitch {
                        id: mmSwitch
                        anchors.verticalCenter: parent.verticalCenter
                        checked: bridge.mouseModeOn
                        onToggled: bridge.setMouseMode(mmSwitch.checked)
                    }
                }

                Rectangle {
                    visible: bridge.mouseModeAvailable
                    Layout.alignment: Qt.AlignVCenter
                    width: 1; height: 24; color: Theme.cardBorder
                }

                StatusPill {}

                Rectangle {
                    Layout.alignment: Qt.AlignVCenter
                    width: 34; height: 34; radius: 8
                    color: win.settingsOpen ? Theme.accent
                                            : (gearHov.hovered ? Theme.cardHover : "transparent")
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Text {
                        anchors.centerIn: parent; text: "⚙"; font.pixelSize: 18
                        color: win.settingsOpen ? "white" : Theme.textDim
                    }
                    HoverHandler { id: gearHov }
                    TapHandler { onTapped: win.settingsOpen = !win.settingsOpen }
                }
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

            // Buttons tab (front page): live controller + remap + reset.
            ButtonsPage {
                anchors.fill: parent
                visible: win.currentTab === 0
            }

            // Vibration tab.
            VibrationPage {
                anchors.fill: parent
                visible: win.currentTab === 4
            }

            // Sticks tab.
            AxisConfigPage {
                anchors.fill: parent
                visible: win.currentTab === 1
                isStick: true
                sideKeys: [["Left Stick", "st"], ["Right Stick", "rs"]]
            }

            // Triggers tab.
            AxisConfigPage {
                anchors.fill: parent
                visible: win.currentTab === 3
                isStick: false
                sideKeys: [["Left Trigger", "lt"], ["Right Trigger", "rt"]]
            }

            // Lights tab.
            LightsPage {
                anchors.fill: parent
                visible: win.currentTab === 5
            }

            // Motion tab — stub (gyro/motion isn't in the reverse-engineering yet).
            Item {
                anchors.fill: parent
                visible: win.currentTab === 2
                Card {
                    anchors.centerIn: parent
                    width: 440
                    title: "Motion"
                    Text {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        text: "Motion / gyro isn't supported yet — the controller's motion " +
                              "protocol hasn't been reverse-engineered. This tab is a " +
                              "placeholder until it is."
                        color: Theme.textDim
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontM
                    }
                }
            }
        }
    }

    // -------------------------------------------------- settings overlay
    Rectangle {
        anchors.fill: parent
        visible: win.settingsOpen
        color: Qt.rgba(0, 0, 0, 0.55)
        MouseArea { anchors.fill: parent; onClicked: win.settingsOpen = false }

        Rectangle {
            anchors.centerIn: parent
            width: 480
            height: col.implicitHeight + 40
            radius: Theme.radius
            color: Theme.card
            border.color: Theme.cardBorder; border.width: 1
            MouseArea { anchors.fill: parent }   // swallow clicks so they don't close

            Column {
                id: col
                anchors.fill: parent
                anchors.margins: 20
                spacing: 16

                Item {
                    width: parent.width; height: 26
                    Text {
                        anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                        text: "Settings"; color: Theme.text
                        font.family: Theme.fontFamily; font.pixelSize: Theme.fontL
                        font.weight: Font.DemiBold
                    }
                    Rectangle {
                        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                        width: 26; height: 26; radius: 6
                        color: closeHov.hovered ? Theme.cardHover : "transparent"
                        Text { anchors.centerIn: parent; text: "✕"; color: Theme.textDim; font.pixelSize: 14 }
                        HoverHandler { id: closeHov }
                        TapHandler { onTapped: win.settingsOpen = false }
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Theme.cardBorder }

                Text {
                    text: "Backup & Restore"; color: Theme.text
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    font.weight: Font.DemiBold
                }
                BackupPanel { width: parent.width }

                Rectangle { width: parent.width; height: 1; color: Theme.cardBorder }

                Text {
                    text: "Firmware"; color: Theme.text
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    font.weight: Font.DemiBold
                }
                FirmwarePanel { width: parent.width }

                Rectangle { width: parent.width; height: 1; color: Theme.cardBorder }

                Text {
                    text: "Lighting"; color: Theme.text
                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    font.weight: Font.DemiBold
                }
                ConfirmButton {
                    label: "Restore default lighting"
                    confirmLabel: "Restore default lighting?"
                    onConfirmed: bridge.restoreLighting()
                }
            }
        }
    }
}
