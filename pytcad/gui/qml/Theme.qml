pragma Singleton
import QtQuick

// PyTCAD design system -- "Modern Dev Tool" identity (v2, 2026-09-04
// reskin). Near-black surfaces carry structure; a violet -> blue
// gradient is the one accent used for active/selected state and the
// primary action (Run). All v1 token names remain valid so nothing
// else in the codebase breaks while panels migrate to the new
// cardBg/cardBorder/cardShadow surfaces panel-by-panel (see
// docs/superpowers/specs/2026-09-04-gui-visual-reskin-design.md).
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
    readonly property int radiusCard: 10  // v2: floating-card corner radius

    // ---- surfaces ------------------------------------------------------
    readonly property color background:  dark ? "#0a0b0e" : "#eef1f4"
    readonly property color panel:       dark ? "#0d0e12" : "#ffffff"
    readonly property color panelAlt:    dark ? "#111217" : "#eceff2"
    readonly property color panelRaised: dark ? "#16171d" : "#f7f9fa"
    readonly property color sunken:      dark ? "#050608" : "#e2e6ea"

    // ---- v2: floating-card surfaces -------------------------------------
    readonly property color cardBg:      dark ? "#16171d" : "#ffffff"
    readonly property color cardBorder:  dark ? "#24252c" : "#dde3e9"
    readonly property color cardShadow:  dark ? Qt.rgba(0, 0, 0, 0.4) : Qt.rgba(0, 0, 0, 0.12)

    // ---- lines & text ---------------------------------------------------
    readonly property color border:       dark ? "#1f2026" : "#c9d0d8"
    readonly property color borderStrong: dark ? "#2c2d36" : "#a8b2bc"
    readonly property color text:         dark ? "#e4e4e7" : "#1a2129"
    readonly property color textDim:      dark ? "#a1a1aa" : "#5a6572"
    readonly property color textFaint:    dark ? "#71717a" : "#8894a0"
    readonly property color focus:        dark ? "#8b5cf6" : "#7c3aed"

    // ---- state colours --------------------------------------------------
    readonly property color accent:       dark ? "#8b5cf6" : "#7c3aed"
    readonly property color accentSoft:   dark ? "#241f38" : "#ede9fe"
    readonly property color running:      dark ? "#d9a441" : "#b57f14"
    property color error:                 dark ? "#e05c56" : "#c0392b"
    readonly property color ok:           dark ? "#61bd6d" : "#2e8b44"

    // ---- v2: brand gradient -- identical in both themes, since the
    // accent IS the brand, not a theme-dependent surface.
    readonly property color accentGradientStart: "#8b5cf6"
    readonly property color accentGradientEnd:   "#3b82f6"

    // selection highlight inside lists
    readonly property color selection:    dark ? "#3a2f57" : "#ede9fe"

    // ---- type ------------------------------------------------------------
    readonly property string mono: '"DejaVu Sans Mono", "Consolas", monospace'
    readonly property string family: '"Inter", "Segoe UI", "Ubuntu", "Cantarell", sans-serif'

    // ---- motion ----------------------------------------------------------
    readonly property int animFast: 110
    readonly property int animMed:  200
    readonly property int animSlow: 360
    readonly property int easeOut:  Easing.OutCubic
    readonly property int easeInOut: Easing.InOutQuad

    // ---- depth & glow ------------------------------------------------------
    readonly property color hoverOverlay: dark ? Qt.rgba(1, 1, 1, 0.06) : Qt.rgba(0, 0, 0, 0.045)
    readonly property color pressOverlay: dark ? Qt.rgba(1, 1, 1, 0.11) : Qt.rgba(0, 0, 0, 0.08)
    readonly property color shadow:       dark ? Qt.rgba(0, 0, 0, 0.55) : Qt.rgba(0, 0, 0, 0.18)
    readonly property color accentGlow:   dark ? Qt.rgba(0.545, 0.361, 0.965, 0.35)
                                                : Qt.rgba(0.486, 0.227, 0.929, 0.22)

    function toggle() { theme.dark = !theme.dark }
}
