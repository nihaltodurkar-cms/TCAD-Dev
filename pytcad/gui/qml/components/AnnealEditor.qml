import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// Editor for an "anneal" process step. Fixed schema: temperature_C,
// time_s only -- no species field (design spec section 9: anneal
// diffuses whatever dopant is already present, it doesn't introduce
// a new one).
ColumnLayout {
    objectName: "annealEditor"
    property var controller
    property string stepId: ""
    property var parameters: null   // {temperature_C, time_s}

    Label { text: "Anneal"; color: Theme.text; font.bold: true }

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
        Label { text: "Time [s]"; Layout.preferredWidth: 120 }
        TextField {
            Layout.fillWidth: true
            text: parameters && parameters.time_s != null ? parameters.time_s.toString() : ""
            onEditingFinished: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {time_s: parseFloat(text)}))
        }
    }
}
