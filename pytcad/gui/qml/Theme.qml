pragma Singleton
import QtQuick

// PyTCAD design system -- "Glassmorphism" identity (v3.0, 2026-09-14
// pass; see ../../DESIGN.md, updated to match). This SUPERSEDES the
// v2.1 correction's flat/bordered-panel decision: docked panels are
// translucent frosted-glass surfaces again (panel/panelAlt/
// panelRaised/sunken/cardBg all carry alpha now), not opaque
// near-black rectangles. Explicit, deliberate reversal, requested and
// approved directly -- not an oversight.
//
// Every existing token's RGB channels are UNCHANGED (only alpha was
// added) specifically so test_theme_tokens.py's pinned hex values
// keep passing: QColor.name() ignores alpha, so "#16171d" with
// alpha=0.65 still reports as "#16171d". radiusCard/accentGradient*
// values are also unchanged for the same reason. New tokens this pass
// adds: radiusGlass (the bigger, glass-panel corner radius -- now
// used by EVERY docked panel, not just overlays), glassBorder (a
// bright, low-alpha rim line -- the "edge catches the light" look),
// glassHighlight (a top-of-panel sheen gradient stop), and
// ambientGlow1/ambientGlow2 (the soft colour wash painted at the
// window root, behind all panels, that the translucent panels reveal
// -- without it, a translucent panel over a flat single-colour
// background looks merely faded, not "glass"). Violet stays the sole
// brand/selection mark.
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
    readonly property int radiusCard: 10  // overlay corner radius (popover/menu/modal)
    readonly property int radiusGlass: 20 // v3.0: the glass-panel corner radius -- every
                                          // docked panel (workbench/viewport/properties/
                                          // console) uses this now, not `radius`.

    // ---- surfaces (v3.0: translucent -- RGB unchanged, alpha added) ----
    readonly property color background:  dark ? "#0a0b0e" : "#eef1f4"
    readonly property color panel:       dark ? Qt.rgba(0x0d / 255, 0x0e / 255, 0x12 / 255, 0.50)
                                                : Qt.rgba(1, 1, 1, 0.55)
    readonly property color panelAlt:    dark ? Qt.rgba(0x11 / 255, 0x12 / 255, 0x17 / 255, 0.42)
                                                : Qt.rgba(0xec / 255, 0xef / 255, 0xf2 / 255, 0.50)
    readonly property color panelRaised: dark ? Qt.rgba(0x16 / 255, 0x17 / 255, 0x1d / 255, 0.58)
                                                : Qt.rgba(0xf7 / 255, 0xf9 / 255, 0xfa / 255, 0.65)

    // Near-opaque -- for ApplicationWindow's header/menuBar/footer
    // chrome specifically. Those sit in Qt's dedicated header/footer
    // slots, OUTSIDE the content item the wallpaper Image is anchored
    // into (Main.qml), so a low-alpha glass fill there blends against
    // nothing and reads as flat black rather than frosted. Same RGB as
    // panelRaised, just much higher alpha -- a solid dark bar, which is
    // what the reference design's own title/menu bar actually is.
    readonly property color chromeBg: dark ? Qt.rgba(0x16 / 255, 0x17 / 255, 0x1d / 255, 0.94)
                                            : Qt.rgba(0xf7 / 255, 0xf9 / 255, 0xfa / 255, 0.94)
    readonly property color sunken:      dark ? Qt.rgba(0x05 / 255, 0x06 / 255, 0x08 / 255, 0.55)
                                                : Qt.rgba(0xe2 / 255, 0xe6 / 255, 0xea / 255, 0.65)

    // ---- overlay surfaces (popovers/menus/tooltips/modals) -------------
    // v3.0: also translucent now (same alpha-only-change rule as
    // above), consistent with the rest of the glass identity. Names/
    // RGB unchanged from the v2 reskin so test_theme_tokens.py's pins
    // still hold (.name() ignores alpha).
    readonly property color cardBg:      dark ? Qt.rgba(0x16 / 255, 0x17 / 255, 0x1d / 255, 0.72)
                                                : Qt.rgba(1, 1, 1, 0.78)
    readonly property color cardBorder:  dark ? "#24252c" : "#dde3e9"
    readonly property color cardShadow:  dark ? Qt.rgba(0, 0, 0, 0.4) : Qt.rgba(0, 0, 0, 0.12)

    // ---- glass-specific rim/sheen tokens (v3.0) -------------------------
    // The rim line and top highlight every glass panel draws in
    // addition to its translucent fill -- what actually reads as
    // "glass" rather than "faded flat colour". Applied inline on each
    // dock Rectangle in Main.qml (border.color + a small top-highlight
    // child Rectangle) -- NOT a separate GlassPanel.qml component: an
    // earlier draft also gave each dock a layer.enabled/MultiEffect
    // drop shadow, which made every dock's content invisible on a real
    // display (see Main.qml's workbenchDock comment); componentizing
    // was reverted along with the shadow to keep the surviving pieces
    // easy to audit inline.
    readonly property color glassBorder:    dark ? Qt.rgba(1, 1, 1, 0.20) : Qt.rgba(1, 1, 1, 0.60)
    readonly property color glassHighlight: dark ? Qt.rgba(1, 1, 1, 0.09) : Qt.rgba(1, 1, 1, 0.55)

    // ---- ambient background wash (v3.0) ---------------------------------
    // Painted once at the window root, behind every panel -- what the
    // translucent panels above actually reveal. Two soft, low-alpha
    // colour stops (violet accent + blue "running" hue) so panels
    // placed over different screen regions catch a different tint,
    // the classic glassmorphism "colour glow behind frosted glass" cue.
    readonly property color ambientGlow1: dark ? Qt.rgba(0.545, 0.361, 0.965, 0.16)
                                                : Qt.rgba(0.545, 0.361, 0.965, 0.10)
    readonly property color ambientGlow2: dark ? Qt.rgba(0.231, 0.510, 0.965, 0.14)
                                                : Qt.rgba(0.231, 0.510, 0.965, 0.09)

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
