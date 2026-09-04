pragma Singleton
import QtQuick

// PyTCAD vector icon set (v2 reskin) -- replaces the plain Unicode
// glyphs used through v0.1-v0.6 (see gui/README.md) with small
// colorable SVG icons, so active/hover/dim state can drive icon color
// through the same Theme tokens everything else uses.
//
// Icons.svg(name, color) returns an "image://icons/<name>/<rrggbb>"
// URL, served by gui/services/icon_provider.py's IconImageProvider
// (registered in gui/app.py's create_engine()). It does NOT build a
// "data:image/svg+xml,..." URI directly, even though that's the more
// obvious QML-only approach and is what this file originally did:
// confirmed directly (2026-09-04) that on this machine's QtQuick
// rendering backend, an Image sourced from a data:image/svg+xml URI
// reports status Ready with correct paintedWidth/paintedHeight but
// paints NOTHING -- a real QtSvg-image-plugin bug, not anything wrong
// with the SVG markup itself (QSvgRenderer renders the identical
// markup correctly when driven directly, and the same Image element
// sourced from a data:image/png;base64,... URI in the exact same
// delegate position DOES paint). Rasterizing in Python via that same
// QSvgRenderer and serving the result through an image:// provider
// sidesteps the broken code path while keeping this function's
// signature and every caller (Main.qml's sidebar tabs and toolbar
// buttons) unchanged. See gui/services/icon_provider.py's module
// docstring for the full record.
QtObject {
    id: icons

    // The SVG path markup itself now lives only in
    // gui/services/icon_provider.py (that's where it's actually
    // rendered) -- this list exists so QML/tests can validate a name
    // without needing to reach into Python, and is kept in sync with
    // icon_provider.py's ICON_PATHS keys manually (cross-checked by
    // gui/tests/test_icon_provider.py).
    readonly property var names: [
        "project", "structure", "mesh", "process", "sweeps",
        "probeStation", "telemetry", "bands", "transient", "physicsLab",
        "builder", "run", "stop", "undo", "redo", "sun", "moon"
    ]

    function _toHex(c) {
        function byte(v) {
            var h = Math.max(0, Math.min(255, Math.round(v * 255))).toString(16)
            return h.length < 2 ? "0" + h : h
        }
        return byte(c.r) + byte(c.g) + byte(c.b)
    }

    function svg(name, color) {
        if (icons.names.indexOf(name) === -1) {
            console.warn("Icons.svg: unknown icon name '" + name + "'")
            return ""
        }
        var hex = (typeof color === "string") ? color.replace("#", "") : icons._toHex(color)
        return "image://icons/" + name + "/" + hex
    }
}
