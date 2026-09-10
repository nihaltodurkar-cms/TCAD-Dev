import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// M38 Phase 4: TCAD-to-SPICE compact-model extraction. Builds a real
// Device1D p-n diode or Device2D n-MOSFET from the geometry below (in
// AppController.compactModel's own subprocess -- see
// gui/services/compact_runner.py), fits workbench/compact.py's Diode
// or MOSFET1 model to the simulated I-V, and shows the extracted
// parameters plus the emitted SPICE .MODEL card. Plan:
// M38-PHASE4-PLAN.md.
Rectangle {
    id: root
    objectName: "compactModelPanel"
    color: Theme.panel
    border.color: Theme.border
    property var controller

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.pad

        Label {
            text: "Compact model extraction"
            font.bold: true
            color: Theme.text
            font.pixelSize: Theme.fsHeader
        }

        Label {
            text: "Fits a SPICE-ready Diode/MOSFET1 model to a real " +
                  "TCAD device simulation, run just above in its own " +
                  "subprocess. No external SPICE, no network."
            color: Theme.textFaint
            font.pixelSize: Theme.fsTiny
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        RowLayout {
            Layout.fillWidth: true
            Label { text: "Model kind"; color: Theme.textDim }
            ComboBox {
                id: kindBox
                objectName: "compactKindBox"
                Layout.fillWidth: true
                model: ["Diode (1D p-n)", "MOSFET1 (2D n-channel)"]
            }
        }

        GridLayout {
            id: diodeFields
            visible: kindBox.currentIndex === 0
            columns: 2
            columnSpacing: Theme.pad
            rowSpacing: Theme.padXs
            Layout.fillWidth: true

            Label { text: "Length [um]"; color: Theme.textDim }
            TextField { id: dLField; objectName: "compactDiodeL"; text: "2.0"
                Layout.fillWidth: true; validator: DoubleValidator { bottom: 0.0 } }
            Label { text: "Junction depth [um]"; color: Theme.textDim }
            TextField { id: dXjField; objectName: "compactDiodeXj"; text: "1.0"
                Layout.fillWidth: true; validator: DoubleValidator { bottom: 0.0 } }
            Label { text: "Na [cm^-3]"; color: Theme.textDim }
            TextField { id: dNaField; objectName: "compactDiodeNa"; text: "1e17"
                Layout.fillWidth: true }
            Label { text: "Nd [cm^-3]"; color: Theme.textDim }
            TextField { id: dNdField; objectName: "compactDiodeNd"; text: "1e17"
                Layout.fillWidth: true }
            Label { text: "Area [cm^2]"; color: Theme.textDim }
            TextField { id: dScaleField; objectName: "compactDiodeScale"; text: "1e-4"
                Layout.fillWidth: true }
            Label { text: "Sweep V [start, stop, step]"; color: Theme.textDim }
            RowLayout {
                Layout.fillWidth: true
                TextField { id: dVStart; objectName: "compactDiodeVStart"; text: "0.0"; Layout.fillWidth: true }
                TextField { id: dVStop; objectName: "compactDiodeVStop"; text: "0.76"; Layout.fillWidth: true }
                TextField { id: dVStep; objectName: "compactDiodeVStep"; text: "0.025"; Layout.fillWidth: true }
            }
            Label { text: "Fit window V [min, max]"; color: Theme.textDim }
            RowLayout {
                Layout.fillWidth: true
                TextField { id: dVFitMin; objectName: "compactDiodeVFitMin"; text: "0.35"; Layout.fillWidth: true }
                TextField { id: dVFitMax; objectName: "compactDiodeVFitMax"; text: "0.60"; Layout.fillWidth: true }
            }
        }

        GridLayout {
            id: mosfetFields
            visible: kindBox.currentIndex === 1
            columns: 2
            columnSpacing: Theme.pad
            rowSpacing: Theme.padXs
            Layout.fillWidth: true

            Label { text: "Gate length [um]"; color: Theme.textDim }
            TextField { id: mLgField; objectName: "compactMosfetLg"; text: "1.0"
                Layout.fillWidth: true; validator: DoubleValidator { bottom: 0.0 } }
            Label { text: "Source/drain length [um]"; color: Theme.textDim }
            TextField { id: mLsdField; objectName: "compactMosfetLsd"; text: "0.5"
                Layout.fillWidth: true; validator: DoubleValidator { bottom: 0.0 } }
            Label { text: "Depth [um]"; color: Theme.textDim }
            TextField { id: mDepthField; objectName: "compactMosfetDepth"; text: "1.0"
                Layout.fillWidth: true; validator: DoubleValidator { bottom: 0.0 } }
            Label { text: "Channel Na [cm^-3]"; color: Theme.textDim }
            TextField { id: mNaField; objectName: "compactMosfetNa"; text: "5e16"
                Layout.fillWidth: true }
            Label { text: "Source/drain peak [cm^-3]"; color: Theme.textDim }
            TextField { id: mNsdField; objectName: "compactMosfetNsd"; text: "5e18"
                Layout.fillWidth: true }
            Label { text: "Oxide thickness [nm]"; color: Theme.textDim }
            TextField { id: mToxField; objectName: "compactMosfetTox"; text: "10.0"
                Layout.fillWidth: true; validator: DoubleValidator { bottom: 0.0 } }
            Label { text: "Width [cm]"; color: Theme.textDim }
            TextField { id: mScaleField; objectName: "compactMosfetScale"; text: "1e-4"
                Layout.fillWidth: true }
            Label { text: "Id-Vg [start, stop, step, Vds]"; color: Theme.textDim }
            RowLayout {
                Layout.fillWidth: true
                TextField { id: mVgStart; objectName: "compactMosfetVgStart"; text: "0.5"; Layout.fillWidth: true }
                TextField { id: mVgStop; objectName: "compactMosfetVgStop"; text: "3.01"; Layout.fillWidth: true }
                TextField { id: mVgStep; objectName: "compactMosfetVgStep"; text: "0.25"; Layout.fillWidth: true }
                TextField { id: mVdsLin; objectName: "compactMosfetVdsLin"; text: "0.1"; Layout.fillWidth: true }
            }
            Label { text: "Id-Vd [start, stop]"; color: Theme.textDim }
            RowLayout {
                Layout.fillWidth: true
                TextField { id: mVdStart; objectName: "compactMosfetVdStart"; text: "1.6"; Layout.fillWidth: true }
                TextField { id: mVdStop; objectName: "compactMosfetVdStop"; text: "3.01"; Layout.fillWidth: true }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Button {
                objectName: "runExtractionButton"
                text: root.controller && root.controller.running ? "Running..." : "Run extraction"
                enabled: root.controller ? !root.controller.running : false
                Layout.fillWidth: true
                onClicked: {
                    if (!root.controller) return
                    if (kindBox.currentIndex === 0) {
                        root.controller.runDiode(
                            parseFloat(dScaleField.text), parseFloat(dLField.text),
                            parseFloat(dXjField.text), parseFloat(dNaField.text),
                            parseFloat(dNdField.text), parseFloat(dVStart.text),
                            parseFloat(dVStop.text), parseFloat(dVStep.text),
                            parseFloat(dVFitMin.text), parseFloat(dVFitMax.text), 0.0)
                    } else {
                        root.controller.runMosfet(
                            parseFloat(mScaleField.text), parseFloat(mLgField.text),
                            parseFloat(mLsdField.text), parseFloat(mDepthField.text),
                            parseFloat(mNaField.text), parseFloat(mNsdField.text),
                            parseFloat(mToxField.text), parseFloat(mVgStart.text),
                            parseFloat(mVgStop.text), parseFloat(mVgStep.text),
                            parseFloat(mVdsLin.text), parseFloat(mVdStart.text),
                            parseFloat(mVdStop.text))
                    }
                }
            }
        }

        Label {
            objectName: "compactErrorLabel"
            visible: root.controller ? root.controller.lastError !== "" : false
            color: Theme.warning
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            text: root.controller ? root.controller.lastError : ""
        }

        ColumnLayout {
            id: resultBlock
            // resultJson is a plain string ("" before any result) --
            // parsed once per binding evaluation below, never held as
            // a live object property (see CompactModelController.resultJson's
            // own docstring for why Property(object) was dropped).
            property var result: root.controller && root.controller.resultJson
                                 ? JSON.parse(root.controller.resultJson) : null
            visible: result !== null
            Layout.fillWidth: true
            spacing: Theme.padXs

            Label {
                objectName: "compactResultSummary"
                color: Theme.text
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: {
                    var r = resultBlock.result
                    if (!r) return ""
                    if (r.kind === "diode")
                        return "Diode: Is=" + r.params.Is.toExponential(4) +
                               " A, N=" + r.params.N.toFixed(4) +
                               " (converged=" + r.converged + ")"
                    return "MOSFET1: Vt0=" + r.params.Vt0.toFixed(4) +
                           " V, kp*W_L=" + r.params.kp_WL.toExponential(4) +
                           ", lambda=" + r.params.lam.toFixed(4) +
                           " (rel_rms_error=" + r.params.rel_rms_error.toFixed(4) +
                           ", converged=" + r.converged + ")"
                }
            }

            TextArea {
                objectName: "compactNetlistArea"
                readOnly: true
                wrapMode: TextArea.NoWrap
                Layout.fillWidth: true
                Layout.preferredHeight: 90
                text: resultBlock.result ? resultBlock.result.netlist : ""
            }
        }

        Item { Layout.fillHeight: true }
    }
}
