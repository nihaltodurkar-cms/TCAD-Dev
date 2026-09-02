import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// Physics Lab (v0.5.0 M4): the educational surface.  Everything shown
// here comes from the real ModelCatalog and the real RunRecord of the
// last solve -- no mock data anywhere.
Rectangle {
    id: root
    color: Theme.panel
    border.color: Theme.border
    property var lab: physicsLab
    signal plotConvergenceRequested()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.pad

        Label {
            text: "Physics Lab"
            font.bold: true
            color: Theme.text
        }

        Label {
            text: lab && lab.selectedDetail() ? lab.selectedDetail().title : ""
            color: Theme.accent
            font.bold: true
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
        }

        // -- catalog list -------------------------------------------------
        ListView {
            id: catalogList
            objectName: "labCatalogList"
            Layout.fillWidth: true
            Layout.preferredHeight: 150
            clip: true
            model: lab.catalogModel
            delegate: RowLayout {
                width: catalogList.width
                spacing: 4
                CheckBox {
                    checked: model.enabled
                    onToggled: lab.setModelEnabled(model.key, checked)
                    ToolTip.visible: hovered
                    ToolTip.text: model.applicability
                }
                Label {
                    text: model.title
                    color: Theme.text
                    font.pixelSize: 11
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                    MouseArea {
                        anchors.fill: parent
                        onClicked: lab.selectModel(model.key)
                    }
                }
            }
        }

        // -- detail pane for the selected model ---------------------------
        ColumnLayout {
            visible: lab.selectedDetail() !== null
            Layout.fillWidth: true
            spacing: 2

            Label { text: "Equations"; color: Theme.textDim; font.pixelSize: 10 }
            Repeater {
                model: lab.selectedDetail() ? lab.selectedDetail().equations : []
                Label {
                    text: modelData
                    color: Theme.text
                    font.family: Theme.mono
                    font.pixelSize: 10
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }

            Label { text: "References"; color: Theme.textDim; font.pixelSize: 10 }
            Repeater {
                model: lab.selectedDetail() ? lab.selectedDetail().references : []
                Label {
                    text: "• " + modelData
                    color: Theme.text
                    font.pixelSize: 10
                    wrapMode: Text.WordWrap
                    Layout.fillWidth: true
                }
            }

            Label {
                visible: lab.selectedDetail() && lab.selectedDetail().limitations !== ""
                text: lab.selectedDetail() ? lab.selectedDetail().limitations : ""
                color: Theme.running
                font.pixelSize: 10
                font.italic: true
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        CheckBox {
            id: equilibriumOnlyBox
            objectName: "equilibriumOnlyCheckBox"
            text: "Equilibrium only (no bias solve)"
            checked: lab.equilibriumOnly
            onToggled: lab.setEquilibriumOnly(checked)
            ToolTip.visible: hovered
            ToolTip.delay: 500
            ToolTip.text: "Required for Density Gradient (dg): Device1D." +
                          "solve_bias refuses dg=True unconditionally " +
                          "(M20 is equilibrium-only). Runs solve_equilibrium() " +
                          "only, skipping the bias solve regardless of the " +
                          "contact voltages set elsewhere."
        }

        Button {
            objectName: "compareModelsButton"
            text: "Compare: all models off"
            Layout.fillWidth: true
            enabled: appController.hasResult && !appController.busy
            onClicked: appController.runModelComparison()
            ToolTip.visible: hovered
            ToolTip.delay: 500
            ToolTip.text: "Re-solve the last-run device with every " +
                          "catalog model disabled; overlays dashed in " +
                          "Curves mode."
        }

        Button {
            objectName: "compareBackendsButton"
            text: "Compare: other backend"
            Layout.fillWidth: true
            enabled: appController.hasResult && !appController.busy
                     && appController.canSelectBackend
            onClicked: appController.runBackendComparison()
            ToolTip.visible: hovered
            ToolTip.delay: 500
            ToolTip.text: "Re-solve the last-run device with the OTHER " +
                          "solver backend (pytcad<->devsim), same " +
                          "physics; overlays dashed in Curves mode. " +
                          "Only available for devsim-compatible 1D devices."
        }

        Label {
            objectName: "comparisonStatusLabel"
            visible: appController.hasComparison
            color: Theme.textDim
            font.pixelSize: Theme.fsSmall
            text: appController.hasComparison
                  ? "overlay: " + appController.comparisonLabelForQml : ""
        }

        Item { Layout.fillHeight: true }

        Button {
            objectName: "showConvergenceButton"
            text: "Plot convergence"
            Layout.fillWidth: true
            enabled: lab.hasRunRecord()
            onClicked: root.plotConvergenceRequested()
        }

        // Phase 3b: per-stage continuation record table
        Label {
            text: "Continuation stages"
            color: Theme.textDim
            font.pixelSize: 10
            font.bold: true
        }
        ListView {
            id: continuationStageTable
            objectName: "continuationStageTable"
            Layout.fillWidth: true
            // Bound off the ListView's own `model` (a real notifying
            // property), not a fresh lab.continuationData() call -- a
            // plain Slot() has no NOTIFY signal, so a binding that calls
            // it directly is evaluated once and frozen. The Connections
            // below is what keeps `model` itself current across runs.
            Layout.preferredHeight: model && model.length ? Math.min(120, model.length * 20 + 10) : 0
            clip: true
            visible: !!model && model.length > 0
            model: lab ? lab.continuationData() : []
            Connections {
                target: appController
                function onResultChanged() {
                    continuationStageTable.model = lab ? lab.continuationData() : []
                }
            }
            delegate: RowLayout {
                width: continuationStageTable.width
                spacing: 4
                Label {
                    text: " #" + (model.index + 1)
                    color: Theme.text
                    font.pixelSize: 10
                    font.family: Theme.mono
                }
                Label {
                    text: "V=" + String(model.parameter).slice(0, 6) + " V"
                    color: Theme.text
                    font.pixelSize: 10
                    font.family: Theme.mono
                }
                Label {
                    text: model.nodes ? "N=" + model.nodes : ""
                    color: Theme.textDim
                    font.pixelSize: 10
                    font.family: Theme.mono
                }
                Label {
                    text: model.accepted ? "✓" : "✗"
                    color: model.accepted ? Theme.ok : Theme.running
                    font.pixelSize: 10
                    font.bold: true
                    Behavior on color { ColorAnimation { duration: Theme.animFast } }
                }
            }
        }

        // Phase 3d: provenance trace view
        Label {
            text: "Provenance trace"
            color: Theme.textDim
            font.pixelSize: 10
            font.bold: true
        }
        ListView {
            id: provenanceTraceView
            objectName: "provenanceTraceView"
            Layout.fillWidth: true
            // See the continuationStageTable comment above: bound off
            // the ListView's own notifying `model` property, kept
            // current by the Connections below, rather than calling
            // the non-notifying lab.provenanceRows() Slot() directly.
            Layout.preferredHeight: model && model.length ? Math.min(150, model.length * 18 + 10) : 0
            clip: true
            visible: !!model && model.length > 0
            model: lab ? lab.provenanceRows() : []
            Connections {
                target: appController
                function onResultChanged() {
                    provenanceTraceView.model = lab ? lab.provenanceRows() : []
                }
            }
            delegate: RowLayout {
                width: provenanceTraceView.width
                spacing: 4
                Label {
                    text: modelData[0] + ":"
                    color: Theme.textDim
                    font.pixelSize: 10
                    font.family: Theme.mono
                    Layout.preferredWidth: 100
                }
                Label {
                    text: modelData[1]
                    color: Theme.text
                    font.pixelSize: 10
                    font.family: Theme.mono
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                }
            }
        }
    }
}
