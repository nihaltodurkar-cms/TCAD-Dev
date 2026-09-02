pragma Singleton
import QtQuick

// PyTCAD design system.
//
// One place defines every colour, spacing, radius and type size the UI
// uses, in dark and light variants.  Restrained scientific-instrument
// principle: neutral surfaces carry the structure, colour is reserved
// for STATE (running / error / success / accent) so it stays meaningful.
//
// All pre-v0.5 token names (pad, radius, mono, background, panel,
// panelAlt, border, text, textDim, accent, running, error, ok, dark)
// remain valid -- older components keep rendering while they migrate.
QtObject {
    id: theme

    property bool dark: true

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

    // ---- surfaces ------------------------------------------------------
    readonly property color background:  dark ? "#171b20" : "#eef1f4"
    readonly property color panel:       dark ? "#1f242b" : "#ffffff"
    readonly property color panelAlt:    dark ? "#262c34" : "#eceff2"
    readonly property color panelRaised: dark ? "#2b323a" : "#f7f9fa"
    readonly property color sunken:      dark ? "#14181d" : "#e2e6ea"

    // ---- lines & text ---------------------------------------------------
    readonly property color border:       dark ? "#343c46" : "#c9d0d8"
    readonly property color borderStrong: dark ? "#454f5b" : "#a8b2bc"
    readonly property color text:         dark ? "#dde3e9" : "#1a2129"
    readonly property color textDim:      dark ? "#8d99a5" : "#5a6572"
    readonly property color textFaint:    dark ? "#5c6873" : "#8894a0"
    readonly property color focus:        dark ? "#5aa2e6" : "#2f7fd4"

    // ---- state colours --------------------------------------------------
    readonly property color accent:       dark ? "#4a90d9" : "#2f7fd4"
    readonly property color accentSoft:   dark ? "#2a3b4d" : "#dbe9f7"
    readonly property color running:      dark ? "#d9a441" : "#b57f14"
    property color error:                 dark ? "#e05c56" : "#c0392b"
    readonly property color ok:           dark ? "#61bd6d" : "#2e8b44"

    // selection highlight inside lists
    readonly property color selection:    dark ? "#31506e" : "#cfe2f5"

    // ---- type ------------------------------------------------------------
    readonly property string mono: '"DejaVu Sans Mono", "Consolas", monospace'
    readonly property string family: '"Inter", "Segoe UI", "Ubuntu", "Cantarell", sans-serif'

    // ---- motion ----------------------------------------------------------
    // A single shared timing scale keeps every hover/press/collapse
    // transition in the app feeling like one consistent instrument
    // rather than a pile of ad-hoc durations.
    readonly property int animFast: 110
    readonly property int animMed:  200
    readonly property int animSlow: 360
    readonly property int easeOut:  Easing.OutCubic
    readonly property int easeInOut: Easing.InOutQuad

    // ---- depth & glow ------------------------------------------------------
    readonly property color hoverOverlay: dark ? Qt.rgba(1, 1, 1, 0.06) : Qt.rgba(0, 0, 0, 0.045)
    readonly property color pressOverlay: dark ? Qt.rgba(1, 1, 1, 0.11) : Qt.rgba(0, 0, 0, 0.08)
    readonly property color shadow:       dark ? Qt.rgba(0, 0, 0, 0.55) : Qt.rgba(0, 0, 0, 0.18)
    readonly property color accentGlow:   dark ? Qt.rgba(0.345, 0.651, 1.0, 0.35)
                                                : Qt.rgba(0.184, 0.498, 0.831, 0.30)

    function toggle() { theme.dark = !theme.dark }
}
