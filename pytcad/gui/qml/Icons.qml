pragma Singleton
import QtQuick

// PyTCAD vector icon set (v2 reskin) -- replaces the plain Unicode
// glyphs used through v0.1-v0.6 (see gui/README.md) with small
// colorable SVG icons, so active/hover/dim state can drive icon color
// through the same Theme tokens everything else uses.
//
// Icons.svg(name, color) returns a "data:image/svg+xml,..." URI ready
// for an Image element's `source`. Two things the implementation must
// get right, both covered by gui/tests/test_icons.py:
//
// 1. The WHOLE svg string is passed through encodeURIComponent, not
//    just interpolated -- a literal '#' in a hex color (e.g.
//    "#8b5cf6") is a URL FRAGMENT delimiter, and an unescaped '#'
//    inside a data: URI silently truncates everything after it,
//    rendering a blank/partial icon.
// 2. `color` may be a real QML `color` value (e.g. Theme.accent), not
//    a string -- and Qt's `color.toString()` yields "#AARRGGBB" (8
//    hex digits, alpha-first), which is NOT valid SVG/CSS color
//    syntax. A color object is converted to "rgba(r,g,b,a)" instead
//    of being stringified directly.
QtObject {
    id: icons

    readonly property var _paths: ({
        project:      "<path d='M4 10 L12 4 L20 10 L20 20 L4 20 Z'/><path d='M9 20 V14 H15 V20'/>",
        structure:    "<rect x='4' y='4' width='7' height='7'/><rect x='13' y='4' width='7' height='7'/><rect x='4' y='13' width='7' height='7'/><rect x='13' y='13' width='7' height='7'/>",
        mesh:         "<path d='M3 6 H21 M3 12 H21 M3 18 H21 M7 3 V21 M12 3 V21 M17 3 V21'/>",
        process:      "<path d='M9 3 H15 V7 L18 12 V20 H6 V12 L9 7 Z'/>",
        sweeps:       "<path d='M3 15 Q7 6 11 15 T19 15'/>",
        probeStation: "<circle cx='12' cy='9' r='4'/><path d='M6 21 C6 16 18 16 18 21'/>",
        telemetry:    "<path d='M3 17 L8 10 L12 14 L21 5'/><path d='M15 5 H21 V11'/>",
        bands:        "<path d='M3 8 H21 M3 16 H21 M7 8 V16 M17 8 V16'/>",
        transient:    "<circle cx='12' cy='12' r='8'/><path d='M12 7 V12 L16 14'/>",
        physicsLab:   "<circle cx='12' cy='12' r='1.6' fill='currentColor' stroke='none'/><ellipse cx='12' cy='12' rx='9' ry='3.6'/><ellipse cx='12' cy='12' rx='9' ry='3.6' transform='rotate(60 12 12)'/><ellipse cx='12' cy='12' rx='9' ry='3.6' transform='rotate(120 12 12)'/>",
        builder:      "<path d='M14 3 L21 10 L10 21 L3 21 L3 14 Z'/>",
        run:          "<path d='M6 4 L20 12 L6 20 Z' fill='currentColor' stroke='none'/>",
        stop:         "<rect x='6' y='6' width='12' height='12' fill='currentColor' stroke='none'/>",
        undo:         "<path d='M8 8 H15 A5 5 0 1 1 11 18'/><path d='M8 8 L12 4 M8 8 L12 12'/>",
        redo:         "<path d='M16 8 H9 A5 5 0 1 0 13 18'/><path d='M16 8 L12 4 M16 8 L12 12'/>",
        sun:          "<circle cx='12' cy='12' r='4'/><path d='M12 2 V5 M12 19 V22 M2 12 H5 M19 12 H22 M4.9 4.9 L7 7 M17 17 L19.1 19.1 M19.1 4.9 L17 7 M7 17 L4.9 19.1'/>",
        moon:         "<path d='M20 14.5 A8 8 0 1 1 9.5 4 A6.2 6.2 0 0 0 20 14.5 Z' fill='currentColor' stroke='none'/>"
    })

    // Exported so gui/tests/test_icons.py can check coverage without
    // duplicating this key list.
    readonly property var names: Object.keys(_paths)

    function _toCss(c) {
        return "rgba(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + "," +
               Math.round(c.b * 255) + "," + c.a.toFixed(3) + ")"
    }

    function svg(name, color) {
        var inner = icons._paths[name]
        if (inner === undefined) {
            console.warn("Icons.svg: unknown icon name '" + name + "'")
            return ""
        }
        var css = (typeof color === "string") ? color : icons._toCss(color)
        var colored = inner.split("currentColor").join(css)
        var doc = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' " +
                  "fill='none' stroke='" + css + "' stroke-width='1.8' " +
                  "stroke-linecap='round' stroke-linejoin='round'>" + colored + "</svg>"
        return "data:image/svg+xml," + encodeURIComponent(doc)
    }
}
