import QtQuick
import QtQuick.Layouts

// Shared editor for one analog axis pair (the two sticks, or the two triggers).
// `sideKeys` drives the Left/Right sub-tabs and maps to the bridge config keys
// ('st'/'rs' or 'lt'/'rt'). `isStick` swaps the type-specific control (stick
// trajectory vs trigger hair-mode) and the live visualiser. All edits stage via
// the bridge's pending-config queue and land on Save.
Item {
    id: page
    property var sideKeys: [["Left Stick", "st"], ["Right Stick", "rs"]]
    property bool isStick: true
    property string side: sideKeys[0][1]
    property int curveType: 0          // 0..2 preset, 3 custom
    property int typeIdx: 0            // trajectory or hair-mode index

    function seed() {
        var c = bridge.config
        if (!bridge.profile || c[side + "_dz_min"] === undefined) return
        dz.lo = c[side + "_dz_min"]; dz.hi = c[side + "_dz_max"]
        adz.lo = c[side + "_adz_min"]; adz.hi = c[side + "_adz_max"]
        var cv = c[side + "_curve"]
        curveType = cv ? cv.type : 0
        curve.setPoints(cv && cv.points ? cv.points : [[40, 41], [128, 128], [215, 214]])
        typeIdx = isStick ? c[side + "_traj"] : c[side + "_hair"]
    }
    Component.onCompleted: seed()
    onSideChanged: seed()
    Connections { target: bridge; function onConfigLoaded() { page.seed() } }

    function presetClicked(name) {
        curveType = bridge.curveNames.indexOf(name)
        curve.setPoints(bridge.curvePresets[name])
        bridge.setCurve(side, name, [])
    }

    // Stage safe factory defaults for this axis — a one-click recovery if a
    // profile gets into a bad state (e.g. a collapsed deadzone bricked the stick).
    function resetDefaults() {
        var dzMin = isStick ? 10 : 5, dzMax = isStick ? 100 : 95
        dz.lo = dzMin; dz.hi = dzMax; adz.lo = 0; adz.hi = 100
        bridge.setScalar(side + "_dz_min", dzMin); bridge.setScalar(side + "_dz_max", dzMax)
        bridge.setScalar(side + "_adz_min", 0); bridge.setScalar(side + "_adz_max", 100)
        curveType = 0; curve.setPoints(bridge.curvePresets["Linear"])
        bridge.setCurve(side, "Linear", [])
        typeIdx = 0
        if (isStick) bridge.setTraj(side, 0); else bridge.setHair(side, 0)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        anchors.bottomMargin: pbar.visible ? pbar.height + 30 : 20
        spacing: 14

        // ---- Left/Right sub-tabs --------------------------------------------
        Row {
            spacing: 8
            Repeater {
                model: page.sideKeys
                delegate: PillButton {
                    required property var modelData
                    label: modelData[0]
                    highlight: page.side === modelData[1]
                    onClicked: page.side = modelData[1]
                }
            }
        }

        // ---- no-profile hint -------------------------------------------------
        Card {
            visible: !bridge.profile
            Layout.fillWidth: true
            title: "No profile selected"
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: "Pick a profile (1–4) in the top bar to read and edit its settings."
                color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
            }
        }

        RowLayout {
            visible: bridge.profile > 0
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 16

            // ======================== LEFT controls ========================
            ColumnLayout {
                Layout.fillWidth: false
                Layout.preferredWidth: 270; Layout.maximumWidth: 270
                Layout.fillHeight: true
                spacing: 14

                Card {
                    title: "Deadzone"; Layout.fillWidth: true
                    Row {
                        width: parent.width
                        Text { text: "Initial"; color: Theme.textDim
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        Item { width: parent.width - 90; height: 1 }
                        Text { text: dz.lo + "–" + dz.hi; color: Theme.text
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    }
                    RangeSlider {
                        id: dz; width: parent.width; from: 0; to: 100; lo: 0; hi: 100
                        onMoved: { bridge.setScalar(page.side + "_dz_min", lo)
                                   bridge.setScalar(page.side + "_dz_max", hi) }
                    }
                }

                Card {
                    title: "Anti-Deadzone"; Layout.fillWidth: true
                    Row {
                        width: parent.width
                        Text { text: "Initial"; color: Theme.textDim
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                        Item { width: parent.width - 90; height: 1 }
                        Text { text: adz.lo + "–" + adz.hi; color: Theme.text
                               font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    }
                    RangeSlider {
                        id: adz; width: parent.width; from: 0; to: 100; lo: 0; hi: 100
                        onMoved: { bridge.setScalar(page.side + "_adz_min", lo)
                                   bridge.setScalar(page.side + "_adz_max", hi) }
                    }
                }

                Card {
                    title: "Curve Adjustment"; Layout.fillWidth: true
                    Flow {
                        width: parent.width; spacing: 8
                        Repeater {
                            model: bridge.curveNames
                            delegate: PillButton {
                                required property string modelData
                                required property int index
                                label: modelData
                                highlight: page.curveType === index
                                onClicked: page.presetClicked(modelData)
                            }
                        }
                        PillButton {
                            label: "Custom"; highlight: page.curveType === 3
                            onClicked: { page.curveType = 3
                                         bridge.setCurve(page.side, "Custom", curve.points) }
                        }
                    }
                }

                Card {
                    title: page.isStick ? "Stick Trajectory" : "Hair Trigger Mode"
                    Layout.fillWidth: true
                    Flow {
                        width: parent.width; spacing: 8
                        Repeater {
                            model: page.isStick ? ["Circle", "Raw"] : bridge.hairModes
                            delegate: PillButton {
                                required property string modelData
                                required property int index
                                label: modelData
                                highlight: page.typeIdx === index
                                onClicked: {
                                    page.typeIdx = index
                                    if (page.isStick) bridge.setTraj(page.side, index)
                                    else bridge.setHair(page.side, index)
                                }
                            }
                        }
                    }
                }

                PillButton {
                    label: "Reset to defaults"
                    Layout.fillWidth: true
                    onClicked: page.resetDefaults()
                }
                Item { Layout.fillHeight: true }
            }

            // ======================== CENTER curve graph ========================
            Item {
                Layout.fillWidth: true; Layout.fillHeight: true
                Column {
                    anchors.centerIn: parent
                    spacing: 6
                    Text { text: "Output"; color: Theme.textFaint
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                           anchors.horizontalCenter: parent.horizontalCenter }
                    CurveEditor {
                        id: curve
                        width: Math.min(280, page.width * 0.34); height: width
                        onEdited: { page.curveType = 3; bridge.setCurve(page.side, "Custom", pts) }
                    }
                    Text { text: "Input"; color: Theme.textFaint
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                           anchors.horizontalCenter: parent.horizontalCenter }
                }
            }

            // ======================== RIGHT live visual ========================
            ColumnLayout {
                Layout.fillWidth: false
                Layout.preferredWidth: 220; Layout.maximumWidth: 220
                Layout.fillHeight: true
                spacing: 14

                Card {
                    title: "Live"; Layout.fillWidth: true

                    // Stick visualiser
                    Item {
                        visible: page.isStick
                        width: parent.width; height: visible ? width : 0
                        property real ax: page.side === "st" ? bridge.leftStickX : bridge.rightStickX
                        property real ay: page.side === "st" ? bridge.leftStickY : bridge.rightStickY
                        Rectangle {
                            anchors.centerIn: parent
                            width: Math.min(parent.width, parent.height) - 10; height: width
                            radius: width / 2; color: "#15171D"
                            border.color: "#3A3E48"; border.width: 2
                            Rectangle {       // deadzone ring
                                anchors.centerIn: parent
                                width: parent.width * (dz.lo / 100); height: width
                                radius: width / 2; color: "transparent"
                                border.color: Theme.accentDim; border.width: 1
                            }
                            Rectangle {       // live position
                                width: 14; height: 14; radius: 7; color: Theme.accent
                                x: parent.width / 2 - 7 + parent.parent.ax * (parent.width / 2 - 8)
                                y: parent.height / 2 - 7 + parent.parent.ay * (parent.height / 2 - 8)
                            }
                        }
                    }

                    // Trigger visualiser
                    Item {
                        visible: !page.isStick
                        width: parent.width; height: visible ? 150 : 0
                        property real v: page.side === "lt" ? bridge.leftTrigger : bridge.rightTrigger
                        Rectangle {
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: 30; height: parent.height; radius: 15
                            color: "#15171D"; border.color: "#3A3E48"; border.width: 2
                            Rectangle {
                                anchors.bottom: parent.bottom; anchors.bottomMargin: 2
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: parent.width - 6; radius: 12; color: Theme.accent
                                height: (parent.height - 4) * parent.parent.v
                            }
                        }
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: page.isStick
                              ? ("X " + Math.round((page.side === "st" ? bridge.leftStickX : bridge.rightStickX) * 100)
                                 + "%   Y " + Math.round((page.side === "st" ? bridge.leftStickY : bridge.rightStickY) * 100) + "%")
                              : (Math.round((page.side === "lt" ? bridge.leftTrigger : bridge.rightTrigger) * 100) + "%")
                        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                    }
                }
                Item { Layout.fillHeight: true }
            }
        }
    }

    // Bottom-anchored overlay so it stays visible regardless of content height.
    PendingBar {
        id: pbar
        anchors.left: parent.left; anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 20; anchors.rightMargin: 20; anchors.bottomMargin: 20
    }
}
