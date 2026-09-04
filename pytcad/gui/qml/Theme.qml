pragma Singleton
import QtQuick

// PyTCAD design system -- "Professional Engineering Instrument"
// identity (v2.1, 2026-09-04 correction pass; see ../../DESIGN.md,
// the committed spec this file now implements). Near-black surfaces
// carry structure via borders + luminance steps, not shadowed cards --
// the v2 reskin's cardBg/cardBorder/cardShadow/radiusCard tokens are
// KEPT (values unchanged, so test_theme_tokens.py's pinned values stay
// valid) but are now reserved for the transient overlay layer only
// (popovers/menus/tooltips/modals -- DESIGN.md section 7); no docked
// panel consumes them any more. Violet stays the sole brand/selection
// mark; the violet->blue gradient is no longer used for tab
// indicators or as decoration -- it is reserved for a determinate
// progress-fill only (DESIGN.md section 8). All v1 token names remain
// valid.
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
    readonly property int radiusCard: 10  // overlay-only (popover/menu/modal), never a docked panel

    // ---- surfaces ------------------------------------------------------
    readonly property color background:  dark ? "#0a0b0e" : "#eef1f4"
    readonly property color panel:       dark ? "#0d0e12" : "#ffffff"
    readonly property color panelAlt:    dark ? "#111217" : "#eceff2"
    readonly property color panelRaised: dark ? "#16171d" : "#f7f9fa"
    readonly property color sunken:      dark ? "#050608" : "#e2e6ea"

    // ---- overlay-only surfaces (popovers/menus/tooltips/modals) --------
    // v2.1 correction: DESIGN.md section 2/7 -- no DOCKED panel reads
    // these any more (docked surfaces use panel/panelAlt/panelRaised +
    // border below, flat, no shadow). Kept for the one class of surface
    // that genuinely floats above app content. Names/values unchanged
    // from the v2 reskin so test_theme_tokens.py's pins still hold.
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
    // v2.1 correction (DESIGN.md section 2/3.3): "running" and
    // "warning" used to share one amber token, which collided caution
    // with healthy solver activity. running now gets its own hue (the
    // former brand-gradient's blue endpoint -- "process active" is
    // categorically different from good/bad); the old amber becomes a
    // real, separate `warning` token. Every prior caller of
    // Theme.running for a caution/rejected/stale/unsaved-changes
    // meaning was repointed to Theme.warning (unchanged appearance,
    // correct name); only the genuine busy/in-progress indicators
    // (StatusIndicator's busy dot, the toolbar status label,
    // SolverTelemetryPanel's "running" state) keep Theme.running and
    // pick up its new blue.
    readonly property color accent:       dark ? "#8b5cf6" : "#7c3aed"
    readonly property color accentSoft:   dark ? "#241f38" : "#ede9fe"
    readonly property color running:      dark ? "#3b82f6" : "#1d4eb8"
    readonly property color runningBg:    dark ? "#0f1c33" : "#e0eafb"
    readonly property color warning:      dark ? "#d9a441" : "#b57f14"
    readonly property color warningBg:    dark ? "#2e2410" : "#fbf0da"
    property color error:                 dark ? "#e05c56" : "#c0392b"
    readonly property color errorBg:      dark ? "#341614" : "#fbe4e2"
    readonly property color ok:           dark ? "#61bd6d" : "#2e8b44"
    readonly property color okBg:         dark ? "#142a18" : "#e1f3e7"

    // ---- brand gradient -- identical in both themes, since the accent
    // IS the brand, not a theme-dependent surface. v2.1 correction
    // (DESIGN.md section 8): reserved for exactly one use, a
    // determinate solve-progress fill ("queued" -> "running" read
    // left-to-right) -- no longer applied to tab indicators or any
    // button; those use a flat Theme.accent/Theme.running instead.
    // Values unchanged so test_theme_tokens.py's pins still hold.
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
