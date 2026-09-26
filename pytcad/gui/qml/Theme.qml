pragma Singleton
import QtQuick

// PyTCAD design system -- ONE scheme, black and white (2026-09-26, the
// user's decision: "no modes, just black and white"). This SUPERSEDES the
// v3.x glassmorphism identity (translucent panels over a coloured
// wallpaper, violet accent and glass rims, ambient colour glows) and the
// light/dark toggle: there is no `dark` property and no toggle() any more.
//
// Chrome is achromatic: white surfaces, black text, grey borders, a black
// accent. The only hues left are the status colours (running, warning,
// error, ok and their backgrounds), which carry meaning. DATA keeps its
// colours -- plot curves, colour maps and region colours are drawn by the
// viewport, not from these tokens. test_theme_tokens.py enforces the
// greys; the native app mirrors these values exactly
// (gui/tests/test_desktop_theme.py).
//
// Token NAMES are kept (panel, glassBorder, accentGradient*, ...) so every
// panel keeps working; their values are now opaque greys.
QtObject {
    id: theme

    readonly property int fsTiny:   10
    readonly property int fsSmall:  11
    readonly property int fsBody:   12
    readonly property int fsHeader: 13
    readonly property int fsTitle:  15

    // vertical rhythm
    readonly property int padXs: 4
    readonly property int padSm: 6
    readonly property int pad: 8          // legacy name = base unit
    readonly property int padLg: 12
    readonly property int padXl: 16
    readonly property int radiusSm: 3     // legacy name below
    readonly property int radius: 3
    readonly property int radiusLg: 6
    readonly property int radiusCard: 10  // overlay corner radius (popover/menu/modal)
    readonly property int radiusGlass: 26 // docked panels' corner radius (name kept from v3.x)
    readonly property real glassBorderWidth: 1.5 // docked panels' rim width (name kept from v3.x)

    // ---- surfaces (opaque) ----------------------------------------------
    readonly property color background:  "#ffffff"
    readonly property color panel:       "#ffffff"
    readonly property color panelAlt:    "#f5f5f5"
    readonly property color panelRaised: "#fafafa"
    // ApplicationWindow's header/menuBar/footer chrome
    readonly property color chromeBg:    "#f2f2f2"
    readonly property color sunken:      "#ebebeb"

    // ---- overlay surfaces (popovers/menus/tooltips/modals) -------------
    readonly property color cardBg:      "#ffffff"
    readonly property color cardBorder:  "#d4d4d4"
    readonly property color cardShadow:  Qt.rgba(0, 0, 0, 0.12)

    // ---- panel rim and sheen (names from v3.x glass) ---------------------
    readonly property color glassBorder:    "#d4d4d4"
    readonly property color glassHighlight: Qt.rgba(1, 1, 1, 0)

    // ---- lines & text ---------------------------------------------------
    readonly property color border:       "#d4d4d4"
    readonly property color borderStrong: "#9e9e9e"
    readonly property color text:         "#000000"
    readonly property color textDim:      "#555555"
    readonly property color textFaint:    "#8c8c8c"
    readonly property color focus:        "#000000"
    // text on an accent (black) fill; not "onAccent": QML reads on<Name> as a signal handler
    readonly property color textOnAccent: "#ffffff"

    // ---- accent (black) and state colours -------------------------------
    // v2.1 (DESIGN.md section 2/3.3): "running" (solver active) and
    // "warning" (caution) are separate hues. The state colours are the only
    // chromatic tokens.
    readonly property color accent:       "#000000"
    readonly property color accentSoft:   "#e8e8e8"
    readonly property color running:      "#1d4eb8"
    readonly property color runningBg:    "#e0eafb"
    readonly property color warning:      "#b57f14"
    readonly property color warningBg:    "#fbf0da"
    property color error:                 "#c0392b"
    readonly property color errorBg:      "#fbe4e2"
    readonly property color ok:           "#2e8b44"
    readonly property color okBg:         "#e1f3e7"

    // ---- the progress fill (DESIGN.md section 8: its one use) -----------
    readonly property color accentGradientStart: "#000000"
    readonly property color accentGradientEnd:   "#707070"

    // selection highlight inside lists
    readonly property color selection:    "#d9d9d9"

    // ---- type ------------------------------------------------------------
    readonly property string mono: '"DejaVu Sans Mono", "Consolas", monospace'
    readonly property string family: '"Inter", "Segoe UI", "Ubuntu", "Cantarell", sans-serif'

    // ---- motion ----------------------------------------------------------
    readonly property int animFast: 110
    readonly property int animMed:  200
    readonly property int animSlow: 360
    readonly property int easeOut:  Easing.OutCubic
    readonly property int easeInOut: Easing.InOutQuad

    // ---- depth -------------------------------------------------------------
    readonly property color hoverOverlay: Qt.rgba(0, 0, 0, 0.05)
    readonly property color pressOverlay: Qt.rgba(0, 0, 0, 0.10)
    readonly property color shadow:       Qt.rgba(0, 0, 0, 0.18)
    readonly property color accentGlow:   Qt.rgba(0, 0, 0, 0.20)
}
