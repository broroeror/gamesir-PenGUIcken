import QtQuick
import QtQuick.Shapes

// Stylised vector Cyclone 2 (Shadow Black), matched to the real controller:
// dark body, a glowing RING around the guide button (Home zone), a small Profile
// LED low-centre, and two long curved grip light bars. The body outline is
// traced from the controller silhouette so control positions match calibration.
// Four RGB zones bind to bridge.lightColors, so this one view drives both the
// Buttons (input highlights) and Lights (zone colours) pages.
Item {
    id: root
    readonly property real aspect: 1.4379
    implicitWidth: 560
    implicitHeight: implicitWidth / aspect

    function btn(name) { return bridge.buttons[name] === true }
    function zone(i) { return bridge.lightColors[i] !== undefined
                              ? bridge.lightColors[i] : "#000000" }
    function isLit(c) { return (c.r + c.g + c.b) > 0.05 }

    // Traced body outline, normalised 0..1 (39 pts). Scaled to px on demand.
    readonly property var bodyPts: [
        [0.2927,0.0],[0.32,0.0026],[0.3491,0.0327],[0.4755,0.0275],[0.6491,0.0327],
        [0.6764,0.0039],[0.7055,0.0],[0.7736,0.0196],[0.8218,0.0601],[0.8564,0.1242],
        [0.8936,0.2497],[0.9509,0.4693],[0.9864,0.6458],[0.9982,0.7464],[0.9982,0.8261],
        [0.9855,0.8967],[0.9645,0.9438],[0.9355,0.9778],[0.8955,0.9974],[0.83,0.915],
        [0.7391,0.7608],[0.69,0.7216],[0.6645,0.7163],[0.3345,0.7163],[0.2982,0.7268],
        [0.26,0.7608],[0.1691,0.915],[0.1036,0.9974],[0.0764,0.9869],[0.0445,0.9582],
        [0.0218,0.919],[0.0064,0.868],[0.0,0.7634],[0.0218,0.5935],[0.0755,0.3595],
        [0.1427,0.1242],[0.1627,0.081],[0.1909,0.0444],[0.2182,0.0235]
    ]
    function bodyPath(w, h) {
        var p = root.bodyPts
        var s = "M " + (p[0][0]*w) + "," + (p[0][1]*h)
        for (var i = 1; i < p.length; i++) s += " L " + (p[i][0]*w) + "," + (p[i][1]*h)
        return s + " Z"
    }

    // ----------------------------------------------------------------- body
    Shape {
        anchors.fill: parent
        antialiasing: true
        ShapePath {
            strokeColor: "#3C414C"
            strokeWidth: 1.5
            fillGradient: LinearGradient {
                x1: 0; y1: 0; x2: 0; y2: root.height
                GradientStop { position: 0.0; color: "#2B2F3A" }
                GradientStop { position: 0.55; color: "#1C1F27" }
                GradientStop { position: 1.0; color: "#101218" }
            }
            PathSvg { path: root.bodyPath(root.width, root.height) }
        }
    }

    // ============================ light zones ============================
    // Curved grip light bar (left, or mirrored to the right grip).
    component GripLight: Shape {
        id: grip
        property color col: "#000000"
        property bool mirror: false
        readonly property bool lit: root.isLit(col)
        anchors.fill: parent
        antialiasing: true
        function fx(nx) { return (mirror ? 1 - nx : nx) * root.width }
        function fy(ny) { return ny * root.height }
        // soft bloom underneath
        ShapePath {
            strokeColor: grip.lit ? Qt.rgba(grip.col.r, grip.col.g, grip.col.b, 0.28)
                                  : "transparent"
            strokeWidth: root.width * 0.06
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            startX: grip.fx(0.19); startY: grip.fy(0.33)
            PathQuad { x: grip.fx(0.17); y: grip.fy(0.83)
                       controlX: grip.fx(0.06); controlY: grip.fy(0.58) }
        }
        // bright core
        ShapePath {
            strokeColor: grip.lit ? grip.col : "#33373F"
            strokeWidth: root.width * 0.022
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            startX: grip.fx(0.19); startY: grip.fy(0.33)
            PathQuad { x: grip.fx(0.17); y: grip.fy(0.83)
                       controlX: grip.fx(0.06); controlY: grip.fy(0.58) }
        }
    }
    GripLight { col: root.zone(0); mirror: false }   // Left grip
    GripLight { col: root.zone(1); mirror: true }    // Right grip

    // Profile LED (small dot, low-centre)
    Item {
        property color col: root.zone(2)
        property bool lit: root.isLit(col)
        x: root.width * 0.50 - width / 2
        y: root.height * 0.405 - height / 2
        width: root.width * 0.028; height: width
        Rectangle {
            anchors.centerIn: parent; width: parent.width * 2.2; height: width
            radius: width / 2; color: parent.col
            opacity: parent.lit ? 0.3 : 0; visible: parent.lit
        }
        Rectangle {
            anchors.fill: parent; radius: width / 2
            color: parent.lit ? parent.col : "#33373F"
            Behavior on color { ColorAnimation { duration: 120 } }
        }
    }

    // Home: glowing ring around the guide button (top-centre)
    Item {
        property color col: root.zone(3)
        property bool lit: root.isLit(col)
        x: root.width * 0.50 - width / 2
        y: root.height * 0.165 - height / 2
        width: root.width * 0.085; height: width
        Rectangle {              // bloom
            anchors.centerIn: parent; width: parent.width * 1.6; height: width
            radius: width / 2; color: parent.col
            opacity: parent.lit ? 0.22 : 0; visible: parent.lit
        }
        Rectangle {              // the ring
            anchors.fill: parent; radius: width / 2; color: "transparent"
            border.color: parent.lit ? parent.col : "#33373F"
            border.width: Math.max(2, width * 0.13)
            Behavior on border.color { ColorAnimation { duration: 120 } }
        }
        Rectangle {              // guide button in the middle
            anchors.centerIn: parent; width: parent.width * 0.46; height: width
            radius: width / 2; color: "#15171D"
            border.color: "#3A3E48"; border.width: 1
        }
    }

    // ============================ controls ============================
    component FaceBtn: Item {
        property real nx: 0
        property real ny: 0
        property string glyph: ""
        property color gcol: "#888"
        property bool on: false
        property real dia: 0.072
        x: root.width * nx - width / 2
        y: root.height * ny - height / 2
        width: root.width * dia; height: width
        Rectangle {
            anchors.fill: parent; radius: width / 2
            color: parent.on ? Theme.accent : "#2A2E38"
            border.color: parent.on ? Qt.lighter(Theme.accent, 1.3) : "#3E4350"
            border.width: Math.max(1, width * 0.04)
            Behavior on color { ColorAnimation { duration: 80 } }
        }
        Text {
            anchors.centerIn: parent; text: parent.glyph
            color: parent.on ? "white" : parent.gcol
            font.family: Theme.fontFamily; font.bold: true
            font.pixelSize: parent.width * 0.46
        }
    }

    component Stick: Item {
        property real nx: 0
        property real ny: 0
        property real ax: 0
        property real ay: 0
        property bool clicked: false
        property real dia: 0.115
        x: root.width * nx - width / 2
        y: root.height * ny - height / 2
        width: root.width * dia; height: width
        Rectangle {
            anchors.fill: parent; radius: width / 2
            color: "#262A33"; border.color: "#3E4350"
            border.width: Math.max(1, width * 0.03)
        }
        Rectangle {
            width: parent.width * 0.56; height: width; radius: width / 2
            color: parent.clicked ? Theme.accent : "#454A56"
            border.color: "#555B68"; border.width: 1
            x: parent.width / 2 - width / 2 + parent.ax * parent.width * 0.20
            y: parent.height / 2 - height / 2 + parent.ay * parent.width * 0.20
            Behavior on color { ColorAnimation { duration: 80 } }
            Behavior on x { NumberAnimation { duration: 40 } }
            Behavior on y { NumberAnimation { duration: 40 } }
        }
    }

    component MiniBtn: Item {
        property real nx: 0
        property real ny: 0
        property bool on: false
        property string glyph: ""
        property real dia: 0.042
        x: root.width * nx - width / 2
        y: root.height * ny - height / 2
        width: root.width * dia; height: width
        Rectangle {
            anchors.fill: parent; radius: width / 2
            color: parent.on ? Theme.accent : "#2A2E38"
            border.color: "#3E4350"
            Behavior on color { ColorAnimation { duration: 80 } }
        }
        Text {
            anchors.centerIn: parent; text: parent.glyph
            color: parent.on ? "white" : "#9AA0AC"
            font.pixelSize: parent.width * 0.5
        }
    }

    // D-pad (cross + direction highlight)
    Item {
        property string dir: bridge.dpad
        property real sz: root.width * 0.11
        x: root.width * 0.355 - sz / 2
        y: root.height * 0.500 - sz / 2
        width: sz; height: sz
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: parent.width * 0.34; height: parent.height; radius: width * 0.2
            color: "#2A2E38"; border.color: "#3E4350"
        }
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width; height: parent.height * 0.34; radius: height * 0.2
            color: "#2A2E38"; border.color: "#3E4350"
        }
        Rectangle {
            visible: parent.dir !== "neutral"
            color: Theme.accent; radius: width * 0.08
            width: parent.width * 0.30; height: parent.height * 0.30
            x: parent.width / 2 - width / 2
               + (parent.dir.indexOf("left") >= 0 ? -parent.width * 0.34
                  : parent.dir.indexOf("right") >= 0 ? parent.width * 0.34 : 0)
            y: parent.height / 2 - height / 2
               + (parent.dir.indexOf("up") >= 0 ? -parent.height * 0.34
                  : parent.dir.indexOf("down") >= 0 ? parent.height * 0.34 : 0)
            Behavior on x { NumberAnimation { duration: 60 } }
            Behavior on y { NumberAnimation { duration: 60 } }
        }
    }

    Stick { nx: 0.235; ny: 0.285; ax: bridge.leftStickX;  ay: bridge.leftStickY
            clicked: root.btn("ls") }
    Stick { nx: 0.627; ny: 0.492; ax: bridge.rightStickX; ay: bridge.rightStickY
            clicked: root.btn("rs") }

    FaceBtn { nx: 0.756; ny: 0.373; glyph: "A"; gcol: "#5BBF6A"; on: root.btn("a") }
    FaceBtn { nx: 0.823; ny: 0.275; glyph: "B"; gcol: "#E06A6A"; on: root.btn("b") }
    FaceBtn { nx: 0.689; ny: 0.275; glyph: "X"; gcol: "#5B96E0"; on: root.btn("x") }
    FaceBtn { nx: 0.755; ny: 0.177; glyph: "Y"; gcol: "#E0C04A"; on: root.btn("y") }

    MiniBtn { nx: 0.425; ny: 0.265; glyph: "❐"; on: root.btn("view") }
    MiniBtn { nx: 0.566; ny: 0.265; glyph: "☰"; on: root.btn("menu") }
}
