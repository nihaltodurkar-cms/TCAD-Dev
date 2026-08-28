import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// Editor for an "implant" process step. Field set matches the fixed
// schema: species, energy_keV, dose_cm2, tilt_deg -- plus the M6
// OPTIONAL per-region window "x_range_cm": [lo, hi] (cm in the wire
// format; micrometers here, because that is what implant windows are
// read in).  An empty From/To pair removes the key entirely: absent ==
// whole domain == byte-identical to pre-M6 flows.
ColumnLayout {
    id: editorRoot
    objectName: "implantEditor"
    property var controller
    property string stepId: ""
    property var parameters: null   // {species, energy_keV, dose_cm2,
                                    //  tilt_deg, x_range_cm?}

    // Write the From/To pair (um) into parameters.x_range_cm (cm).
    // Empty pair -> key removed.  A non-numeric entry is rejected and
    // both fields snap back to the LIVE parameter values (the same
    // revert contract SweepPanel applies to a rejected arm) -- NaN must
    // never reach the flow because it cannot survive JSON.
    function _applyWindow() {
        if (!stepId || !parameters)
            return
        var fromTxt = fromField.text.trim()
        var toTxt = toField.text.trim()
        if (fromTxt === "" && toTxt === "") {
            var stripped = Object.assign({}, parameters)
            delete stripped.x_range_cm
            controller.setProcessStepParameters(stepId, stripped)
            return
        }
        var loUm = parseFloat(fromTxt)
        var hiUm = parseFloat(toTxt)
        if (!(isFinite(loUm) && isFinite(hiUm))) {
            var live = controller.processStepParameters(stepId)
            var rng = live && live.x_range_cm != null ? live.x_range_cm : null
            fromField.text = rng != null ? (rng[0] * 1e4).toString() : ""
            toField.text = rng != null ? (rng[1] * 1e4).toString() : ""
            return
        }
        controller.setProcessStepParameters(stepId, Object.assign(
            {}, parameters, {x_range_cm: [loUm * 1e-4, hiUm * 1e-4]}))
    }

    // Keep the fields honest whenever a different step (or a fresh run)
    // re-populates `parameters` -- without this, stale text from the
    // previously selected implant lingered in the TextFields.
    onParametersChanged: {
        var rng = parameters && parameters.x_range_cm != null
                  ? parameters.x_range_cm : null
        fromField.text = rng != null ? (rng[0] * 1e4).toString() : ""
        toField.text = rng != null ? (rng[1] * 1e4).toString() : ""
    }

    Label { text: "Implantation"; color: Theme.text; font.bold: true }
    Label {
        text: "Model: Gaussian (LSS-table moments)\n" +
              "✓ Dose  ✓ Energy  ✓ Species (B, P, As)  ✓ Tilt (first-order cos scaling)\n" +
              "Not implemented: ✗ Channeling  ✗ Transient enhanced diffusion  ✗ Monte-Carlo damage"
        color: Theme.textDim; font.pixelSize: 10; wrapMode: Text.WordWrap
        Layout.fillWidth: true
        // Task 15 (real-display verification) finding: in this Qt/PySide/
        // Wayland environment, a ColumnLayout child's Layout.fillWidth-
        // reported width can exceed the panel's true visible/clipped
        // bounds by ~15-20px (the same class of over-report documented at
        // length in RegionList.qml/ProcessPanel.qml, there affecting a
        // ListView delegate instead of a wrapped Label). Qt's own wrap
        // metrics were satisfied (contentWidth < the reported width), so
        // no warning was raised, but the wrapped text still visibly ran
        // past the panel's real right edge on screen. Layout.maximumWidth
        // caps this well under the SplitView's observed minimum usable
        // width so wrapping always lands inside the true clipped area.
        Layout.maximumWidth: 185
    }

    RowLayout {
        Label { text: "Species"; Layout.preferredWidth: 90 }
        ComboBox {
            id: speciesBox
            objectName: "implantSpeciesBox"
            model: ["B", "P", "As"]
            currentIndex: parameters && parameters.species != null ? model.indexOf(parameters.species) : 0
            onActivated: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {species: currentText}))
        }
    }
    RowLayout {
        Label { text: "Energy [keV]"; Layout.preferredWidth: 90 }
        TextField {
            objectName: "implantEnergyField"
            Layout.fillWidth: true
            text: parameters && parameters.energy_keV != null ? parameters.energy_keV.toString() : ""
            onEditingFinished: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {energy_keV: parseFloat(text)}))
        }
    }
    RowLayout {
        Label { text: "Dose [cm⁻²]"; Layout.preferredWidth: 90 }
        TextField {
            objectName: "implantDoseField"
            Layout.fillWidth: true
            text: parameters && parameters.dose_cm2 != null ? parameters.dose_cm2.toExponential(2) : ""
            onEditingFinished: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {dose_cm2: parseFloat(text)}))
        }
    }
    RowLayout {
        Label { text: "Window [µm]"; Layout.preferredWidth: 90 }
        TextField {
            id: fromField
            objectName: "implantWindowFromField"
            Layout.fillWidth: true
            placeholderText: "0"
            ToolTip.text: "Implant window start; empty = domain start"
            ToolTip.visible: hovered
        }
        Label { text: "to" ; color: Theme.textDim }
        TextField {
            id: toField
            objectName: "implantWindowToField"
            Layout.fillWidth: true
            placeholderText: "end"
            ToolTip.text: "Implant window end; empty = domain end"
            ToolTip.visible: hovered
        }
    }
    RowLayout {
        Button {
            objectName: "implantWindowApplyButton"
            text: "Apply Window"
            onClicked: editorRoot._applyWindow()
        }
        Label {
            text: "empty pair = whole domain"
            color: Theme.textDim
            font.pixelSize: 10
        }
    }
    RowLayout {
        Label { text: "Tilt [deg]"; Layout.preferredWidth: 90 }
        TextField {
            Layout.fillWidth: true
            // Python None crosses to QML as undefined, not null -- see
            // GateEditor.qml's vfbValue comment. tilt_deg may legitimately
            // be absent client-side even though the backend defaults it
            // to 0.0, so this must be `!= null` (loose), not `!== null`.
            text: parameters && parameters.tilt_deg != null ? parameters.tilt_deg.toString() : "0"
            onEditingFinished: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {tilt_deg: parseFloat(text)}))
        }
    }
}
