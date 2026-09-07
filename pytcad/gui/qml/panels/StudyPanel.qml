import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// M30 Phase 5: Split/Study Manager.
//
// Configures a parameter-table x deck run matrix (workbench.splits,
// via StudyController) and runs it through a small pool of JobRunners.
// Deliberately plain: a template id, one KEY=value line per base
// parameter, one PARAM = v1, v2, ... line per split axis -- the same
// vocabulary workbench/workflow.py's own deck grammar already uses,
// so what's typed here reads the same way a saved deck would.
Rectangle {
    id: root
    color: Theme.panel
    border.color: Theme.border
    property var controller           // appController.studyManager
    // Named hostController, NOT appController: reusing the outer
    // context property's own name here shadows it within this
    // object's binding scope (confirmed directly -- both this
    // property's own assignment AND the sibling `controller:
    // appController.studyManager` binding above resolved to undefined
    // until renamed).
    property var hostController       // for loadStudyResult()

    // M30 Phase 6: Sweep Matrix Viewer. axisNames/matrixCells are
    // refreshed explicitly (via the Refresh button and on every
    // studyChanged) rather than through an auto-reactive binding --
    // StudyController.matrixCells()/availableDisplayFields() are Slots
    // (they re-read result files from disk), not cheap Properties.
    property var axisNames: root.controller ? Object.keys(root.controller.splitAxes) : []
    property var matrixCellsModel: []
    property var comparisonResult: null   // M30 Phase 7: Run Comparison

    function refreshMatrix() {
        if (!root.controller) return
        if (fieldBox.model.length && fieldBox.currentIndex < 0)
            fieldBox.currentIndex = 0
        matrixCellsModel = (fieldBox.currentText && root.axisNames.length === 2)
            ? root.controller.matrixCells(fieldBox.currentText) : []
    }

    Connections {
        target: root.controller
        function onStudyChanged() {
            fieldBox.model = root.controller.availableDisplayFields()
            root.refreshMatrix()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.pad

        Label {
            text: "Study (parameter splits)"
            font.bold: true
            color: Theme.text
            font.pixelSize: Theme.fsHeader
        }

        Label {
            text: "One device per split-matrix row, solved through its " +
                  "own subprocess. A row the template rejects is shown " +
                  "as a build error and never reaches the solver."
            color: Theme.textFaint
            font.pixelSize: Theme.fsTiny
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Label { text: "Template ID"; color: Theme.textDim }
        TextField {
            id: templateField
            objectName: "studyTemplateField"
            Layout.fillWidth: true
            placeholderText: "e.g. mos_capacitor"
        }

        Label { text: "Base parameters (KEY=value, one per line)"; color: Theme.textDim }
        TextArea {
            id: baseParamsArea
            objectName: "studyBaseParamsArea"
            Layout.fillWidth: true
            Layout.preferredHeight: 60
            placeholderText: "na_cm3=-1e16"
        }

        Label { text: "Splits (PARAM = v1, v2, ..., one per line)"; color: Theme.textDim }
        TextArea {
            id: splitsArea
            objectName: "studySplitsArea"
            Layout.fillWidth: true
            Layout.preferredHeight: 60
            placeholderText: "tox_cm = 7e-7, 8e-7, 9e-7"
        }

        RowLayout {
            spacing: Theme.padSm

            Button {
                id: configureButton
                objectName: "studyConfigureButton"
                text: "Configure"
                onClicked: {
                    var base = {}
                    baseParamsArea.text.split("\n").forEach(function (line) {
                        var t = line.trim()
                        if (!t) return
                        var parts = t.split("=")
                        if (parts.length === 2) {
                            base[parts[0].trim()] = parseFloat(parts[1].trim())
                        }
                    })
                    var splits = {}
                    splitsArea.text.split("\n").forEach(function (line) {
                        var t = line.trim()
                        if (!t) return
                        var parts = t.split("=")
                        if (parts.length === 2) {
                            var name = parts[0].trim()
                            var vals = parts[1].split(",").map(function (v) {
                                return parseFloat(v.trim())
                            }).filter(function (v) { return !isNaN(v) })
                            if (vals.length) splits[name] = vals
                        }
                    })
                    root.controller.configureStudy(templateField.text.trim(), base, splits)
                }
            }

            Button {
                id: runStudyButton
                objectName: "runStudyButton"
                text: "Run"
                enabled: !!(root.controller && !root.controller.running && root.controller.rows.length > 0)
                onClicked: root.controller.runStudy()
            }

            Button {
                id: cancelStudyButton
                objectName: "cancelStudyButton"
                text: "Cancel"
                enabled: !!(root.controller && root.controller.running)
                onClicked: root.controller.cancelStudy()
            }

            Label {
                objectName: "studyStatusLabel"
                color: Theme.textDim
                text: root.controller
                      ? (root.controller.running ? "Running..."
                         : root.controller.rows.length + " row(s)")
                      : ""
            }
        }

        RowLayout {
            visible: root.axisNames.length === 2
            spacing: Theme.padSm

            Label { text: "Matrix field"; color: Theme.textDim }
            ComboBox {
                id: fieldBox
                objectName: "studyFieldBox"
                Layout.preferredWidth: 160
                onCurrentTextChanged: root.refreshMatrix()
            }
            Button {
                objectName: "studyRefreshMatrixButton"
                text: "Refresh"
                onClicked: {
                    if (root.controller)
                        fieldBox.model = root.controller.availableDisplayFields()
                    root.refreshMatrix()
                }
            }
        }

        // 2-axis split matrix as a grid: matrixCells() is already in
        // row-major (axis0, axis1) order (workbench.splits.expand_splits'
        // documented order -- the LAST split key varies fastest), so a
        // flat Repeater with `columns` set to axis1's value count lines
        // up correctly with no reshaping.
        Grid {
            id: matrixGrid
            objectName: "studyMatrixGrid"
            visible: root.axisNames.length === 2
            columns: root.axisNames.length === 2
                     ? (root.controller.splitAxes[root.axisNames[1]] || []).length : 1
            spacing: 2

            Repeater {
                model: root.matrixCellsModel
                delegate: Rectangle {
                    objectName: "studyMatrixCell_" + index
                    width: 68
                    height: 40
                    border.color: Theme.border
                    color: modelData.status === "done"
                           ? Theme.okBg
                           : (modelData.status === "failed" || modelData.status === "build_error")
                             ? Theme.errorBg : Theme.panelAlt

                    Label {
                        anchors.centerIn: parent
                        font.pixelSize: Theme.fsTiny
                        color: Theme.text
                        text: modelData.status === "done"
                              ? Number(modelData.value).toPrecision(3)
                              : modelData.status
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: modelData.status === "done"
                        onClicked: {
                            if (root.hostController)
                                root.hostController.loadStudyResult(modelData.resultPath)
                        }
                    }
                }
            }
        }

        ListView {
            id: studyRowsList
            objectName: "studyRowsList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: root.controller ? root.controller.rows : []
            delegate: RowLayout {
                width: studyRowsList.width
                spacing: Theme.padSm

                Label {
                    Layout.fillWidth: true
                    color: Theme.text
                    font.pixelSize: Theme.fsSmall
                    text: JSON.stringify(modelData.params)
                    elide: Text.ElideRight
                }
                Label {
                    color: modelData.status === "done" ? Theme.ok
                           : (modelData.status === "failed" || modelData.status === "build_error")
                             ? Theme.error : Theme.textDim
                    font.pixelSize: Theme.fsSmall
                    text: modelData.status
                }
                Button {
                    text: "View"
                    visible: modelData.status === "done"
                    onClicked: {
                        if (root.hostController)
                            root.hostController.loadStudyResult(modelData.resultPath)
                    }
                }
            }
        }

        // M30 Phase 7: Run Comparison. Row indices, not a checkbox list
        // -- deliberately plain, mirroring the same "type the row
        // numbers you mean" simplicity as the base-parameter/splits
        // text areas above.
        Label {
            text: "Compare rows (indices, comma-separated)"
            color: Theme.textDim
        }
        RowLayout {
            spacing: Theme.padSm
            TextField {
                id: compareIndicesField
                objectName: "compareIndicesField"
                Layout.preferredWidth: 120
                placeholderText: "0, 1"
            }
            Button {
                objectName: "compareRunButton"
                text: "Compare"
                onClicked: {
                    var idxs = compareIndicesField.text.split(",")
                        .map(function (s) { return parseInt(s.trim(), 10) })
                        .filter(function (n) { return !isNaN(n) })
                    var field = fieldBox.currentText || "potential"
                    root.comparisonResult = root.controller
                        ? root.controller.compareRows(idxs, field, "horizontal", 0.0)
                        : null
                }
            }
            Label {
                objectName: "compareSkippedLabel"
                color: Theme.textFaint
                font.pixelSize: Theme.fsTiny
                text: (root.comparisonResult && root.comparisonResult.skipped
                       && root.comparisonResult.skipped.length)
                      ? root.comparisonResult.skipped.length + " row(s) skipped"
                      : ""
            }
        }

        ListView {
            id: comparisonCurvesList
            objectName: "comparisonCurvesList"
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(120, contentHeight)
            clip: true
            model: root.comparisonResult ? root.comparisonResult.curves : []
            delegate: RowLayout {
                width: comparisonCurvesList.width
                Label {
                    Layout.fillWidth: true
                    color: Theme.text
                    font.pixelSize: Theme.fsSmall
                    text: modelData.label
                    elide: Text.ElideRight
                }
                Label {
                    color: Theme.textDim
                    font.pixelSize: Theme.fsTiny
                    text: modelData.y.length
                          ? ("min=" + Math.min.apply(null, modelData.y).toPrecision(3) +
                             "  max=" + Math.max.apply(null, modelData.y).toPrecision(3))
                          : ""
                }
            }
        }

        ListView {
            id: provenanceDiffList
            objectName: "provenanceDiffList"
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(140, contentHeight)
            clip: true
            model: root.comparisonResult ? root.comparisonResult.provenance : []
            delegate: RowLayout {
                width: provenanceDiffList.width
                Label {
                    Layout.preferredWidth: 100
                    color: modelData.differs ? Theme.warning : Theme.textDim
                    font.pixelSize: Theme.fsTiny
                    font.bold: modelData.differs
                    text: modelData.field
                }
                Label {
                    Layout.fillWidth: true
                    color: modelData.differs ? Theme.text : Theme.textFaint
                    font.pixelSize: Theme.fsTiny
                    text: JSON.stringify(modelData.values)
                    elide: Text.ElideRight
                }
            }
        }
    }
}
