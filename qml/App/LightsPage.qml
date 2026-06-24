import QtQuick
import QtQuick.Layouts

// The Lights tab: per-zone color editing wired live to the controller render,
// effect presets, brightness/speed, a keyframe animation editor, and the global
// power settings. All actions call through `bridge` into the existing gamesir_led
// code. Editing a colour updates the render instantly; "Apply" pushes to the pad.
Item {
    id: page

    property int sel: 0                       // selected zone 0..3
    property var frames: [["#0080FF", "#0080FF", "#0080FF", "#0080FF"]]
    property int curFrame: 0
    property bool playing: true
    property string sleepSel: "10 min"

    Component.onCompleted: syncFromBridge()

    // Pull the page in line with the controller's real lighting state. Runs at
    // startup and whenever the bridge reads a new active slot back.
    function syncFromBridge() {
        frames = bridge.loadedFrames.length > 0 ? bridge.loadedFrames
                                                : [bridge.lightColors.slice()]
        curFrame = 0
        audioSw.checked = bridge.audioReactive
        wakeSw.checked = bridge.pickupWake
        sleepSel = bridge.sleepLabel
        briSlider.value = bridge.brightness
        spdSlider.value = bridge.speed
        selectZone(sel)
    }

    Connections {
        target: bridge
        function onLightingLoaded() { page.syncFromBridge() }
    }

    // ---- helpers -----------------------------------------------------------
    function _h2(x) { var s = Math.round(x * 255).toString(16); return s.length < 2 ? "0" + s : s }
    function colorToHex(c) { return "#" + _h2(c.r) + _h2(c.g) + _h2(c.b) }
    function hexToRgb(h) {
        h = ("" + h).replace("#", "")
        return [parseInt(h.substr(0, 2), 16), parseInt(h.substr(2, 2), 16), parseInt(h.substr(4, 2), 16)]
    }
    function randomVivid() { return colorToHex(Qt.hsva(Math.random(), 1, 1, 1)) }

    function selectZone(z) { sel = z; picker.setColor(bridge.lightColors[z]) }
    function onZoneEdited(c) {
        var hex = colorToHex(c)
        bridge.setLight(sel, hex)
        frames[curFrame][sel] = hex
    }
    function loadFrame(i) {
        for (var z = 0; z < 4; z++) bridge.setLight(z, frames[i][z])
        picker.setColor(bridge.lightColors[sel])
    }
    function addFrame() {
        if (frames.length >= 8) return
        var f = frames.slice(); f.push(bridge.lightColors.slice())
        frames = f; curFrame = frames.length - 1; loadFrame(curFrame)
    }
    function removeFrame() {
        if (frames.length <= 1) return
        var f = frames.slice(); f.splice(curFrame, 1); frames = f
        if (curFrame >= f.length) curFrame = f.length - 1
        loadFrame(curFrame)
    }
    function randomizeFrame() {
        var f = frames.slice(); var fr = f[curFrame].slice()
        for (var z = 0; z < 4; z++) fr[z] = randomVivid()
        f[curFrame] = fr; frames = f; loadFrame(curFrame)
    }
    function applyAnimation() {
        var rgb = []
        for (var i = 0; i < frames.length; i++) {
            var fr = []
            for (var z = 0; z < 4; z++) fr.push(hexToRgb(frames[i][z]))
            rgb.push(fr)
        }
        bridge.applyKeyframes(rgb)
    }
    function togglePlay() { playing = !playing; bridge.setPlayback(playing, curFrame + 1) }

    // ---- small reusable button --------------------------------------------
    component TextButton: Rectangle {
        property string label: ""
        property bool highlight: false
        signal clicked()
        implicitWidth: bt.implicitWidth + 22; implicitHeight: 30; radius: 7
        color: highlight ? Theme.accent : (hh.hovered ? Theme.cardHover : "#20232B")
        border.color: highlight ? Qt.lighter(Theme.accent, 1.2) : Theme.cardBorder
        border.width: 1
        Behavior on color { ColorAnimation { duration: 100 } }
        Text {
            id: bt; anchors.centerIn: parent; text: parent.label
            color: parent.highlight ? "white" : Theme.text
            font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
        }
        HoverHandler { id: hh }
        TapHandler { onTapped: parent.clicked() }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 16

        // ============================ LEFT ============================
        ColumnLayout {
            Layout.fillWidth: false
            Layout.preferredWidth: 250; Layout.maximumWidth: 250
            Layout.fillHeight: true
            spacing: 16

            Card {
                title: "Lighting Profile"; Layout.fillWidth: true
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    text: "Independent of the hardware profile — shared across all four."
                    color: Theme.textFaint; font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                }
                Row {
                    width: parent.width; spacing: 8
                    Repeater {
                        model: 4
                        delegate: TextButton {
                            required property int index
                            label: "" + (index + 1)
                            implicitWidth: 44
                            highlight: bridge.ledSlot === index
                            onClicked: bridge.selectSlot(index)
                        }
                    }
                }
            }

            Card {
                title: "Presets"; Layout.fillWidth: true
                Flow {
                    width: parent.width; spacing: 8
                    Repeater {
                        model: bridge.presetNames
                        delegate: TextButton {
                            required property string modelData
                            label: modelData
                            onClicked: bridge.applyPreset(modelData)
                        }
                    }
                    TextButton { label: "Off"; onClicked: bridge.lightsOff() }
                }
            }

            Card {
                title: "Brightness & Speed"; Layout.fillWidth: true
                Row {
                    width: parent.width
                    Text { text: "Brightness"; color: Theme.textDim
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    Item { width: parent.width - briLbl.width - 70; height: 1 }
                    Text { id: briLbl; text: bridge.brightness + "%"; color: Theme.text
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                }
                AccentSlider {
                    id: briSlider
                    width: parent.width; from: 0; to: 100; value: bridge.brightness
                    onMoved: bridge.setBrightness(value)
                }
                Row {
                    width: parent.width
                    Text { text: "Speed"; color: Theme.textDim
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                    Item { width: parent.width - spdLbl.width - 42; height: 1 }
                    Text { id: spdLbl; text: bridge.speed + ""; color: Theme.text
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                }
                AccentSlider {
                    id: spdSlider
                    width: parent.width; from: 1; to: 20; value: bridge.speed
                    onMoved: bridge.setSpeed(value)
                }
            }

            Card {
                title: "Power"; Layout.fillWidth: true
                Row {
                    width: parent.width
                    Text { text: "Audio reactive"; color: Theme.text
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                           anchors.verticalCenter: parent.verticalCenter }
                    Item { width: parent.width - 130 - audioSw.width; height: 1 }
                    ToggleSwitch { id: audioSw; onToggled: bridge.setAudioReactive(audioSw.checked) }
                }
                Row {
                    width: parent.width
                    Text { text: "Pick-up to wake"; color: Theme.text
                           font.family: Theme.fontFamily; font.pixelSize: Theme.fontM
                           anchors.verticalCenter: parent.verticalCenter }
                    Item { width: parent.width - 130 - wakeSw.width; height: 1 }
                    ToggleSwitch { id: wakeSw; onToggled: bridge.setPickupWake(wakeSw.checked) }
                }
                Text { text: "Sleep when inactive"; color: Theme.textDim
                       font.family: Theme.fontFamily; font.pixelSize: Theme.fontS }
                Flow {
                    width: parent.width; spacing: 6
                    Repeater {
                        model: bridge.sleepOptions
                        delegate: TextButton {
                            required property string modelData
                            label: modelData
                            highlight: page.sleepSel === modelData
                            onClicked: { page.sleepSel = modelData; bridge.setSleepTimeout(modelData) }
                        }
                    }
                }
            }

            Item { Layout.fillHeight: true }
        }

        // ============================ CENTER ============================
        Item {
            id: centerArea
            Layout.fillWidth: true
            Layout.fillHeight: true
            Column {
                anchors.centerIn: parent
                spacing: 14
                ControllerView {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: Math.min(implicitWidth, centerArea.width - 24)
                    height: width / aspect
                }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 6
                    Repeater {
                        model: 4
                        delegate: Rectangle {
                            required property int index
                            width: 96; height: 40; radius: 8
                            color: "#1A1C22"
                            border.color: page.sel === index ? Theme.accent : Theme.cardBorder
                            border.width: page.sel === index ? 2 : 1
                            Row {
                                anchors.centerIn: parent; spacing: 6
                                Rectangle {
                                    width: 16; height: 16; radius: 4
                                    color: bridge.lightColors[index]
                                    border.color: "#555"; border.width: 1
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    text: bridge.lightNames[index]; color: Theme.textDim
                                    font.family: Theme.fontFamily; font.pixelSize: Theme.fontS
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                            }
                            TapHandler { onTapped: page.selectZone(index) }
                        }
                    }
                }
            }
        }

        // ============================ RIGHT ============================
        ColumnLayout {
            Layout.fillWidth: false
            Layout.preferredWidth: 300; Layout.maximumWidth: 300
            Layout.fillHeight: true
            spacing: 16

            Card {
                title: "Zone — " + bridge.lightNames[page.sel]; Layout.fillWidth: true
                ColorPicker {
                    id: picker; width: parent.width
                    onEdited: page.onZoneEdited(c)
                }
                Row {
                    width: parent.width; spacing: 8
                    TextButton { label: "Apply colors"; highlight: true
                                 onClicked: bridge.applyColors() }
                    TextButton { label: "Off"; onClicked: bridge.lightsOff() }
                }
            }

            Card {
                title: "Keyframes"; Layout.fillWidth: true
                Flow {
                    width: parent.width; spacing: 6
                    Repeater {
                        model: page.frames.length
                        delegate: TextButton {
                            required property int index
                            label: "" + (index + 1)
                            implicitWidth: 32
                            highlight: page.curFrame === index
                            onClicked: { page.curFrame = index; page.loadFrame(index) }
                        }
                    }
                    TextButton { label: "+"; implicitWidth: 32
                                 enabled: page.frames.length < 8
                                 opacity: page.frames.length < 8 ? 1 : 0.4
                                 onClicked: page.addFrame() }
                    TextButton { label: "−"; implicitWidth: 32
                                 enabled: page.frames.length > 1
                                 opacity: page.frames.length > 1 ? 1 : 0.4
                                 onClicked: page.removeFrame() }
                }
                Text {
                    width: parent.width
                    text: page.frames.length + " / 8 keyframes — edit zone colors per frame"
                    color: Theme.textFaint; font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontS; wrapMode: Text.WordWrap
                }
                Row {
                    width: parent.width; spacing: 8
                    TextButton { label: "Randomize"; onClicked: page.randomizeFrame() }
                    TextButton { label: page.playing ? "Pause" : "Play"
                                 onClicked: page.togglePlay() }
                }
                TextButton {
                    label: "Apply animation"; highlight: true
                    width: parent.width
                    onClicked: page.applyAnimation()
                }
            }

            Item { Layout.fillHeight: true }
        }
    }
}
