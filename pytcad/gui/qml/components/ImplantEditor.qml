import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// Editor for an "implant" process step. Field set matches the fixed
// schema: species, energy_keV, dose_cm2, tilt_deg.
ColumnLayout {
    objectName: "implantEditor"
    property var controller
    property string stepId: ""
    property var parameters: null   // {species, energy_keV, dose_cm2, tilt_deg}

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
            model: ["B", "P", "As"]
            currentIndex: parameters && parameters.species != null ? model.indexOf(parameters.species) : 0
            onActivated: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {species: currentText}))
        }
    }
    RowLayout {
        Label { text: "Energy [keV]"; Layout.preferredWidth: 90 }
        TextField {
            Layout.fillWidth: true
            text: parameters && parameters.energy_keV != null ? parameters.energy_keV.toString() : ""
            onEditingFinished: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {energy_keV: parseFloat(text)}))
        }
    }
    RowLayout {
        Label { text: "Dose [cm⁻²]"; Layout.preferredWidth: 90 }
        TextField {
            Layout.fillWidth: true
            text: parameters && parameters.dose_cm2 != null ? parameters.dose_cm2.toExponential(2) : ""
            onEditingFinished: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {dose_cm2: parseFloat(text)}))
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
