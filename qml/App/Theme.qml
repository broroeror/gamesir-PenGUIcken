pragma Singleton
import QtQuick

// Central design tokens, tuned to the GameSir Connect look:
// deep near-black background with a faint red glow, dark translucent cards,
// a single saturated red accent, soft rounded corners.
QtObject {
    // Surfaces
    readonly property color bg:          "#0E0F13"
    readonly property color bgGlow:      "#2A1416"   // top-left reddish wash
    readonly property color card:        "#181A20"
    readonly property color cardBorder:  "#23262E"
    readonly property color cardHover:   "#1E2128"
    readonly property color navBar:      "#14151A"
    readonly property color track:       "#2C2F38"   // slider grooves

    // Accent
    readonly property color accent:      "#E03A2F"
    readonly property color accentDim:   "#8C2B25"
    readonly property color accentGlow:  "#E03A2F"

    // Text
    readonly property color text:        "#F2F3F5"
    readonly property color textDim:     "#9AA0AC"
    readonly property color textFaint:   "#5C616C"

    // States
    readonly property color ok:          "#3CCB7F"
    readonly property color warn:        "#E0B23A"

    // Metrics
    readonly property int radius:        10
    readonly property int radiusSm:      6
    readonly property int pad:           16
    readonly property int gap:           12

    // Type
    readonly property string fontFamily: "Inter, Noto Sans, sans-serif"
    readonly property int fontXL:        20
    readonly property int fontL:         15
    readonly property int fontM:         13
    readonly property int fontS:         11
}
