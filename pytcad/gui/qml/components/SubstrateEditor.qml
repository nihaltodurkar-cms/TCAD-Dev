import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// Editor for a "substrate" process step -- the first step in a flow,
// which establishes the 1D mesh and background doping that every
// later step (implant/anneal/oxidize) then operates on directly.
// There is no separate backend "wafer" object: the substrate step's
// parameters *are* the initial x-axis/doping state, so edits here
// change what later steps start from rather than configuring some
// other persistent entity.
ColumnLayout {
    objectName: "substrateEditor"
    property var controller
    property string stepId: ""
    property var parameters: null   // {length_cm, background_doping_cm3, mesh:{h_min_cm,h_max_cm,ratio}}

    Label { text: "Substrate"; color: Theme.text; font.bold: true }
    Label {
        text: "There is no separate backend \"wafer\" object -- this substrate " +
              "step's parameters define the initial 1D mesh and background " +
              "doping that later steps in the flow build on directly."
        color: Theme.textDim; font.pixelSize: 10; wrapMode: Text.WordWrap
        Layout.fillWidth: true
        // See ImplantEditor.qml's identical comment: a Layout.fillWidth-
        // reported width can exceed this panel's true clipped bounds in
        // this environment; cap it so wrapping stays inside the real edge.
        Layout.maximumWidth: 185
    }

    RowLayout {
        Label { text: "Length [cm]"; Layout.preferredWidth: 130 }
        TextField {
            Layout.fillWidth: true
            text: parameters && parameters.length_cm != null ? parameters.length_cm.toExponential(3) : ""
            onEditingFinished: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {length_cm: parseFloat(text)}))
        }
    }
    RowLayout {
        Label { text: "Bg doping [cm⁻³]"; Layout.preferredWidth: 130 }
        TextField {
            Layout.fillWidth: true
            text: parameters && parameters.background_doping_cm3 != null
                  ? parameters.background_doping_cm3.toExponential(3) : ""
            onEditingFinished: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {background_doping_cm3: parseFloat(text)}))
        }
    }
    RowLayout {
        Label { text: "Mesh h_min [cm]"; Layout.preferredWidth: 130 }
        TextField {
            Layout.fillWidth: true
            text: parameters && parameters.mesh && parameters.mesh.h_min_cm != null
                  ? parameters.mesh.h_min_cm.toExponential(3) : ""
            onEditingFinished: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {mesh: Object.assign({}, parameters.mesh, {h_min_cm: parseFloat(text)})}))
        }
    }
    RowLayout {
        Label { text: "Mesh h_max [cm]"; Layout.preferredWidth: 130 }
        TextField {
            Layout.fillWidth: true
            text: parameters && parameters.mesh && parameters.mesh.h_max_cm != null
                  ? parameters.mesh.h_max_cm.toExponential(3) : ""
            onEditingFinished: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {mesh: Object.assign({}, parameters.mesh, {h_max_cm: parseFloat(text)})}))
        }
    }
    RowLayout {
        Label { text: "Mesh ratio"; Layout.preferredWidth: 130 }
        TextField {
            Layout.fillWidth: true
            text: parameters && parameters.mesh && parameters.mesh.ratio != null
                  ? parameters.mesh.ratio.toString() : ""
            onEditingFinished: if (stepId) controller.setProcessStepParameters(stepId,
                Object.assign({}, parameters, {mesh: Object.assign({}, parameters.mesh, {ratio: parseFloat(text)})}))
        }
    }
}
