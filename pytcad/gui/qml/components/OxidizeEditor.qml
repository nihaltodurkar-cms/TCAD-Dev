import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// Editor for an "oxidize" process step. Fixed schema: temperature_C,
// time_hours, ambient (dry/wet).
ColumnLayout {
    objectName: "oxidizeEditor"
    property var controller
    property string stepId: ""
    property var parameters: null   // {temperature_C, time_hours, ambient}

    Label { text: "Oxidize"; color: Theme.text; font.bold: true }
    // Non-dismissable bookkeeping-only warning (design spec section 16):
    // oxidation in this backend never touches the wafer's x-axis or
    // doping profile -- it only reports the oxide thickness and silicon
    // consumed as informational numbers.
    Label {
        text: "Oxidation is bookkeeping-only in this backend: it reports oxide " +
              "thickness and Si consumed, but does not alter the wafer's x-axis " +
              "or doping profile."
        color: Theme.running
        font.pixelSize: 10
        font.bold: true
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
        // See ImplantEditor.qml's identical comment: a Layout.fillWidth-
        // reported width can exceed this panel's true clipped bounds in
        // this environment; cap it so wrapping stays inside the real edge.
        Layout.maximumWidth: 185
    }

    RowLayout {
        Label { text: "Temperature [°C]"; Layout.preferredWidth: 120 }
        TextField {
            Layout.fillWidth: true
            text: parameters && parameters.temperature_C != null ? parameters.temperature_C.toString() : ""
            onEditingFinished: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {temperature_C: parseFloat(text)}))
        }
    }
    RowLayout {
        Label { text: "Time [hours]"; Layout.preferredWidth: 120 }
        TextField {
            Layout.fillWidth: true
            text: parameters && parameters.time_hours != null ? parameters.time_hours.toString() : ""
            onEditingFinished: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {time_hours: parseFloat(text)}))
        }
    }
    RowLayout {
        Label { text: "Ambient"; Layout.preferredWidth: 120 }
        ComboBox {
            model: ["dry", "wet"]
            currentIndex: parameters && parameters.ambient != null ? model.indexOf(parameters.ambient) : 0
            onActivated: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {ambient: currentText}))
        }
    }
}
