import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// Design section 19: renders AppController.processDerivedQuantities(stepId)
// as a human-formatted two-column list (label / value with units and, for
// concentrations and doses, unicode-superscript scientific notation) --
// NEVER as raw JSON.stringify(value). Every key processDerivedQuantities()
// can return (app_controller.py, Task 13) has an explicit case below; an
// unrecognized key falls back to String(value) rather than JSON, so even
// a future key added without updating this file degrades to plain text,
// not a JSON blob.
ColumnLayout {
    id: root
    objectName: "derivedQuantitiesPanel"
    property var controller
    property string stepId: ""
    property var quantities: ({})

    function _refresh() {
        root.quantities = (root.stepId && root.controller)
            ? root.controller.processDerivedQuantities(root.stepId) : {}
    }

    onStepIdChanged: root._refresh()
    onControllerChanged: root._refresh()
    Component.onCompleted: root._refresh()
    // processDerivedQuantities() is a Slot call (like processStepParameters()
    // elsewhere in this workbench), invisible to QML's binding dependency
    // tracker -- refreshed explicitly off both stepId changes and
    // processResultChanged (a fresh run can change every step's derived
    // values even when the selected stepId itself doesn't change).
    Connections {
        target: root.controller
        function onProcessResultChanged() { root._refresh() }
    }

    function _toSuperscript(text) {
        var map = {
            "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
            "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
            "-": "⁻"
        }
        var out = ""
        for (var i = 0; i < text.length; i++) {
            out += (map[text[i]] !== undefined) ? map[text[i]] : text[i]
        }
        return out
    }

    // "N.NN x 10^E unit" using toExponential(2), e.g. 4.82e19 -> "4.82e+19"
    // -> mantissa "4.82", exponent "19" -> "4.82 × 10¹⁹ unit".
    function _sciNotation(value, unit) {
        var s = Number(value).toExponential(2)
        var parts = s.split("e")
        var mantissa = parts[0]
        var exp = parseInt(parts[1], 10)
        return mantissa + " × 10" + root._toSuperscript(String(exp)) + " " + unit
    }

    readonly property var _speciesPrefixes: [
        "peak_concentration_cm3_", "peak_depth_um_", "implanted_dose_cm2_"
    ]

    function _speciesOf(key) {
        for (var p = 0; p < root._speciesPrefixes.length; p++) {
            var prefix = root._speciesPrefixes[p]
            if (key.indexOf(prefix) === 0) return key.substring(prefix.length)
        }
        return ""
    }

    function _allSpecies() {
        var seen = {}
        var keys = Object.keys(root.quantities)
        for (var i = 0; i < keys.length; i++) {
            var sp = root._speciesOf(keys[i])
            if (sp) seen[sp] = true
        }
        return Object.keys(seen).sort()
    }

    function _label(key) {
        if (key === "junction_depth_um") {
            var arr = root.quantities[key]
            return (arr && arr.length > 1) ? "Junction depths" : "Junction depth"
        }
        if (key === "sheet_resistance_ohm_sq") return "Sheet resistance"
        if (key === "oxide_thickness_um") return "Oxide thickness"
        if (key === "silicon_consumed_um") return "Silicon consumed"

        var multiSpecies = root._allSpecies().length > 1
        var species = root._speciesOf(key)
        if (key.indexOf("peak_concentration_cm3_") === 0) {
            return "Peak " + species + " concentration"
        }
        if (key.indexOf("peak_depth_um_") === 0) {
            return multiSpecies ? ("Peak " + species + " depth") : "Peak depth"
        }
        if (key.indexOf("implanted_dose_cm2_") === 0) {
            return multiSpecies ? ("Implanted " + species + " dose") : "Implanted dose"
        }
        return key
    }

    function _formatValue(key, value) {
        if (key === "junction_depth_um") {
            if (!value || value.length === 0) return "n/a"
            var parts = []
            for (var i = 0; i < value.length; i++) parts.push(Number(value[i]).toFixed(3) + " µm")
            return parts.join(", ")
        }
        if (key === "sheet_resistance_ohm_sq") {
            return Math.round(value) + " Ω/□"
        }
        if (key === "oxide_thickness_um" || key === "silicon_consumed_um") {
            return Number(value).toFixed(3) + " µm"
        }
        if (key.indexOf("peak_concentration_cm3_") === 0) {
            return root._sciNotation(value, "cm⁻³")
        }
        if (key.indexOf("peak_depth_um_") === 0) {
            return (Number(value) * 1000).toFixed(1) + " nm"
        }
        if (key.indexOf("implanted_dose_cm2_") === 0) {
            return root._sciNotation(value, "cm⁻²")
        }
        return String(value)
    }

    // Display order: junction depth first, then per-species groups
    // (concentration/depth/dose together), sheet resistance, then
    // oxide thickness / silicon consumed last.
    function _orderedKeys() {
        var keys = Object.keys(root.quantities)
        var order = []
        if (keys.indexOf("junction_depth_um") !== -1) order.push("junction_depth_um")
        var speciesNames = root._allSpecies()
        for (var s = 0; s < speciesNames.length; s++) {
            var sp = speciesNames[s]
            for (var p = 0; p < root._speciesPrefixes.length; p++) {
                var k = root._speciesPrefixes[p] + sp
                if (keys.indexOf(k) !== -1) order.push(k)
            }
        }
        if (keys.indexOf("sheet_resistance_ohm_sq") !== -1) order.push("sheet_resistance_ohm_sq")
        if (keys.indexOf("oxide_thickness_um") !== -1) order.push("oxide_thickness_um")
        if (keys.indexOf("silicon_consumed_um") !== -1) order.push("silicon_consumed_um")
        return order
    }

    Label { text: "DERIVED QUANTITIES"; color: Theme.textDim; font.pixelSize: 11; font.letterSpacing: 1 }

    Repeater {
        model: root._orderedKeys()
        delegate: RowLayout {
            Layout.fillWidth: true
            Label {
                text: root._label(modelData)
                color: Theme.textDim
                font.pixelSize: 11
                Layout.preferredWidth: 160
            }
            Label {
                text: root._formatValue(modelData, root.quantities[modelData])
                color: Theme.text
                font.pixelSize: 11
                Layout.fillWidth: true
                // Task 15 (real-display verification) finding: at this
                // app's default SplitView proportions, six side-by-side
                // panels don't all fit their preferred widths in a
                // 1280px-wide window, so this panel (and its siblings)
                // render narrower than intended -- a real screenshot
                // showed values like "1.16 x 10^19 cm^-3" hard-clipped
                // mid-character with no ellipsis. elide degrades that to
                // a legible truncation; ToolTip surfaces the full text
                // (the panel itself widens correctly if the user drags
                // the SplitView handle -- this only fixes the readability
                // of the unavoidable narrow case).
                elide: Text.ElideRight
                ToolTip.text: text
                ToolTip.visible: hoverHandler.hovered
                HoverHandler { id: hoverHandler }
            }
        }
    }

    Label {
        visible: root._orderedKeys().length === 0
        text: "No derived quantities available for this step."
        color: Theme.textDim
        font.pixelSize: 10
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }
}
