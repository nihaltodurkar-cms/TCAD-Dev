pragma Singleton
import QtQuick

// Restrained scientific-instrument palette: greys carry the structure,
// colour is reserved for state (running / error / success) so it stays
// meaningful. Dark is the default; light is one flag away.
QtObject {
    property bool dark: true

    readonly property color background:  dark ? "#1e2227" : "#f5f6f7"
    readonly property color panel:       dark ? "#262b31" : "#ffffff"
    readonly property color panelAlt:    dark ? "#2d333a" : "#eceef0"
    readonly property color border:      dark ? "#3a424b" : "#c8cdd3"
    readonly property color text:        dark ? "#e3e7eb" : "#1c2126"
    readonly property color textDim:     dark ? "#9aa4ae" : "#5c666f"
    readonly property color accent:      "#4a90d9"
    readonly property color running:     "#d9a441"
    readonly property color error:       "#d9534f"
    readonly property color ok:          "#5cb85c"

    readonly property int pad: 8
    readonly property int radius: 3
    readonly property string mono: "monospace"
}
