import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts

// Front page: live controller render, per-profile button remap (master-detail:
// pick a source on the left, assign a target on the right), and the factory
// default-profile reset. Remap edits stage through the config pending/save queue.
Item {
    id: page
    property string sel: "A"
    property var localRemap: ({})        // staged overrides shown before Save

    function targetOf(src) {
        if (localRemap[src] !== undefined) return localRemap[src]
        var r = bridge.config.remap
        return (r && r[src] !== undefined) ? r[src] : "Default"
    }
    function assign(src, target) {
        var m = Object.assign({}, localRemap); m[src] = target; localRemap = m
        bridge.setRemap(src, target)
    }
    Connections { target: bridge; function onConfigLoaded() { page.localRemap = ({}) } }

    // When the viewport is too short to stack the source list + reset card on the
    // left, the reset card moves under the Assign panel on the right (which has
    // spare height) instead of being pushed off the bottom into the scroll area.
    readonly property bool compact: scroller.availableHeight > 0
                                    && scroller.availableHeight < 520

    // The default-profile reset, shown on the left normally and on the right when
    // compact. One definition, placed in whichever column has the room.
    component ResetCard: Card {
        title: "Default profile"; Layout.fillWidth: true
        Text {
            width: parent.width; wrapMode: Text.WordWrap
            text: "Reset Profile " + bridge.profile + " to its out-of-box factory " +
                  "state — buttons, sticks, triggers, vibration, default lighting."
            color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
        }
        ConfirmButton {
            label: "Reset to default"
            confirmLabel: "Reset Profile " + bridge.profile + "?"
            onConfirmed: bridge.resetProfileToDefault()
        }
    }

    // Scroll fallback: fills the viewport in a tall window (content stretches to
    // height via the Math.max below), and scrolls vertically once the stacked
    // cards no longer fit — so nothing clips at small window sizes.
    QQC.ScrollView {
        id: scroller
        anchors.fill: parent
        anchors.bottomMargin: pbar.visible ? pbar.height + 30 : 0
        contentWidth: availableWidth
        QQC.ScrollBar.horizontal.policy: QQC.ScrollBar.AlwaysOff
        clip: true
        topPadding: 20; bottomPadding: 20; leftPadding: 20; rightPadding: 20

    ColumnLayout {
        width: scroller.availableWidth
        height: Math.max(implicitHeight, scroller.availableHeight)
        spacing: 14

        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 16

            // -------- LEFT: source list + reset --------
            ColumnLayout {
                visible: bridge.profile > 0
                Layout.fillWidth: true
                Layout.minimumWidth: 250; Layout.preferredWidth: 290; Layout.maximumWidth: 340
                Layout.fillHeight: true
                spacing: 14

                Card {
                    title: "Button Mapping"
                    Layout.fillWidth: true; Layout.fillHeight: true
                    Grid {
                        width: parent.width; columns: 2; spacing: 6
                        Repeater {
                            model: bridge.remapSources
                            delegate: Rectangle {
                                required property string modelData
                                width: (parent.width - 6) / 2; height: 30; radius: 6
                                color: page.sel === modelData ? Theme.cardHover : "#1A1C22"
                                border.color: page.sel === modelData ? Theme.accent : Theme.cardBorder
                                border.width: 1
                                Text {
                                    anchors.left: parent.left; anchors.leftMargin: 8
                                    anchors.right: parent.right; anchors.rightMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    elide: Text.ElideRight
                                    text: modelData + "  →  " + page.targetOf(modelData)
                                    color: page.targetOf(modelData) === "Default" ? Theme.textDim : Theme.text
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                }
                                TapHandler { onTapped: page.sel = modelData }
                            }
                        }
                    }
                }

                ResetCard { visible: !page.compact }
            }

            // -------- CENTER: controller + remap indicator --------
            Item {
                id: centerArea
                Layout.fillWidth: true; Layout.fillHeight: true
                Layout.horizontalStretchFactor: 2
                implicitHeight: centerCol.implicitHeight
                Column {
                    id: centerCol
                    width: parent.width
                    y: Math.max(0, (parent.height - implicitHeight) / 2)
                    spacing: 12

                    ControllerView {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: Math.min(implicitWidth, centerArea.width - 24)
                        height: width / aspect
                        highlightSource: bridge.profile > 0 ? page.sel : ""
                        highlightTarget: bridge.profile > 0 ? page.targetOf(page.sel) : ""
                    }

                    // "<source> → <target>" caption under the pad.
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: bridge.profile > 0
                        width: capRow.implicitWidth + 28; height: 34; radius: 8
                        color: "#181A20"; border.color: Theme.cardBorder; border.width: 1
                        Row {
                            id: capRow; anchors.centerIn: parent; spacing: 8
                            Text {
                                text: page.sel; color: Theme.text; font.bold: true
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: "→"; color: Theme.textDim
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                text: page.targetOf(page.sel) === "Default" ? "unmapped"
                                                                            : page.targetOf(page.sel)
                                color: page.targetOf(page.sel) === "Default" ? Theme.textDim : Theme.accent
                                font.bold: page.targetOf(page.sel) !== "Default"
                                font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: bridge.profile === 0
                        width: Math.min(implicitWidth, centerArea.width - 24)
                        horizontalAlignment: Text.AlignHCenter; wrapMode: Text.WordWrap
                        text: "Select a profile (1–4) above to remap buttons."
                        color: Theme.textDim; font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                    }
                }
            }

            // -------- RIGHT: assign target (+ reset when compact) --------
            ColumnLayout {
                visible: bridge.profile > 0
                Layout.fillWidth: true
                Layout.minimumWidth: 200; Layout.preferredWidth: 240; Layout.maximumWidth: 300
                Layout.fillHeight: true
                spacing: 14

                Card {
                    title: "Assign — " + page.sel; Layout.fillWidth: true
                    Flow {
                        width: parent.width; spacing: 6
                        Repeater {
                            model: bridge.remapTargets
                            delegate: PillButton {
                                required property string modelData
                                label: modelData
                                highlight: page.targetOf(page.sel) === modelData
                                onClicked: page.assign(page.sel, modelData)
                            }
                        }
                    }
                }

                ResetCard { visible: page.compact }
                Item { Layout.fillHeight: true }
            }
        }
    }
    }

    PendingBar {
        id: pbar
        anchors.left: parent.left; anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 20; anchors.rightMargin: 20; anchors.bottomMargin: 20
    }
}
