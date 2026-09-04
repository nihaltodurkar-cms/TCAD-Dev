import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import ".."

// Process Flow panel (v0.3): lists ProcessFlow.steps via
// controller.processFlowModel and lets the user reorder / toggle /
// duplicate / remove steps, plus add a new step of one of the four
// fixed operations (substrate/implant/anneal/oxidize).
//
// Delegate follows RegionList.qml's exact pattern -- see that file's
// long comment for the full history. Short version: in this
// Qt/PySide/Wayland build, ListView.view.width (and anchoring a
// delegate's contentItem to parent.right) unreliably reports a value
// larger than the panel's true visible/clipped bounds, which produced
// overlapping text and invisible buttons. The fix that stuck: the
// contentItem is a single Row anchored ONLY to parent.left, and every
// child gets a small fixed pixel width -- never Layout.fillWidth and
// never a width computed from the ListView's own width.
Rectangle {
    id: root
    objectName: "processPanel"
    color: Theme.panel
    border.color: Theme.border
    property var controller
    property string selectedStepId: ""
    signal stepSelected(string stepId)

    // Routing state for the per-operation editors below. These are NOT
    // plain property bindings on purpose: processStepOperation()/
    // processStepParameters() are Slot calls (Task 7's plain accessors),
    // and Qt Quick's binding dependency tracker cannot see inside a Slot
    // call the way it sees a Property read -- a binding expression like
    // `controller.processStepParameters(root.selectedStepId)` would only
    // re-evaluate when `selectedStepId` itself changes, NOT when the same
    // step's parameters are edited in place via setProcessStepParameters
    // (which fires controller.structureChanged, not a change to
    // selectedStepId). So this refreshes explicitly, imperatively, off
    // both triggers.
    property string selectedOperation: ""
    property var selectedParameters: null

    function _refreshSelection() {
        if (controller && root.selectedStepId) {
            root.selectedOperation = controller.processStepOperation(root.selectedStepId)
            root.selectedParameters = controller.processStepParameters(root.selectedStepId)
        } else {
            root.selectedOperation = ""
            root.selectedParameters = null
        }
    }

    onSelectedStepIdChanged: root._refreshSelection()
    onControllerChanged: root._refreshSelection()
    Component.onCompleted: root._refreshSelection()
    Connections {
        target: controller
        function onStructureChanged() { root._refreshSelection() }
    }

    // Default parameter dicts per operation, matching the fixed schemas
    // from the design spec (design spec section 5):
    //   substrate = {length_cm, background_doping_cm3, mesh:{h_min_cm,h_max_cm,ratio}}
    //   implant   = {species, energy_keV, dose_cm2, tilt_deg,
//                x_range_cm? [lo, hi] cm -- M6 optional window}
    //   anneal    = {temperature_C, time_s}
    //   oxidize   = {temperature_C, time_hours, ambient}
    function _defaultParams(operation) {
        if (operation === "substrate") {
            return {
                length_cm: 1e-3,
                background_doping_cm3: 1e15,
                mesh: { h_min_cm: 1e-7, h_max_cm: 1e-5, ratio: 1.2 }
            }
        }
        if (operation === "implant") {
            return { species: "B", energy_keV: 30, dose_cm2: 1e13, tilt_deg: 7 }
        }
        if (operation === "anneal") {
            return { temperature_C: 1000, time_s: 30 }
        }
        if (operation === "oxidize") {
            return { temperature_C: 1000, time_hours: 0.5, ambient: "dry" }
        }
        return {}
    }

    function _addStep(operation, label) {
        controller.addProcessStep(operation, label, root._defaultParams(operation))
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.pad

        RowLayout {
            Layout.fillWidth: true
            // Matches SweepPanel's "Voltage sweep" panel-title styling
            // (bold, Theme.fsHeader) for consistency across panels.
            Label {
                text: "PROCESS FLOW"
                color: Theme.textDim
                font.bold: true
                font.pixelSize: Theme.fsHeader
                Layout.fillWidth: true
            }
        }

        Label {
            text: "Steps run top to bottom to build the 1D substrate stack."
            color: Theme.textDim
            font.pixelSize: 10
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        // Final-review Critical finding: runProcess()/cancelProcess()/
        // buildDeviceFromProcess() (AppController, Task 8) had ZERO
        // callers anywhere in the real QML tree -- a user could compose a
        // process flow but had no way to ever execute it or hand it off
        // to a device solve. Run/Stop mirror the main toolbar's own
        // device-solve Run/Stop buttons (Main.qml) exactly, including
        // sharing the same `controller.busy` flag (runProcess()/run() both
        // set it), so a process run and a device solve can't race each
        // other from this UI either.
        RowLayout {
            Layout.fillWidth: true
            Button {
                objectName: "processRunButton"
                text: "Run Process"
                enabled: controller ? !controller.busy : false
                onClicked: controller.runProcess()
            }
            Button {
                objectName: "processStopButton"
                text: "Stop"
                enabled: controller ? controller.busy : false
                onClicked: controller.cancelProcess()
            }
            BusyIndicator {
                running: controller ? controller.busy : false
                visible: controller ? controller.busy : false
                implicitWidth: 20
                implicitHeight: 20
            }
        }

        // Process -> Device(1D) handoff (design section 14): exactly two
        // voltage fields, matching Device1D's two ohmic ends -- not a
        // general contact editor. Bound directly to
        // controller.leftContactV/rightContactV (plain float Qt
        // properties with setters, Task 8), which buildDeviceFromProcess()
        // reads when constructing the DeviceSpec's bias.
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Left V"; Layout.preferredWidth: 46 }
            TextField {
                objectName: "leftContactVField"
                Layout.preferredWidth: 60
                text: controller ? controller.leftContactV.toString() : "0"
                onEditingFinished: if (controller) controller.leftContactV = parseFloat(text)
            }
            Label { text: "Right V"; Layout.preferredWidth: 50 }
            TextField {
                objectName: "rightContactVField"
                Layout.preferredWidth: 60
                text: controller ? controller.rightContactV.toString() : "0"
                onEditingFinished: if (controller) controller.rightContactV = parseFloat(text)
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Button {
                objectName: "buildDeviceFromProcessButton"
                text: "Build Device from Process"
                enabled: controller ? controller.hasProcessResult : false
                onClicked: controller.buildDeviceFromProcess()
            }
        }

        // Add-step controls: four small buttons, one per fixed operation,
        // rather than a popup Menu -- keeps this simple and avoids any
        // extra popup-positioning surface area given the layout history
        // above.
        Flow {
            Layout.fillWidth: true
            spacing: 4
            Button {
                text: "+ Substrate"
                onClicked: root._addStep("substrate", "Substrate")
            }
            Button {
                text: "+ Implant"
                onClicked: root._addStep("implant", "Implant")
            }
            Button {
                text: "+ Anneal"
                onClicked: root._addStep("anneal", "Anneal")
            }
            Button {
                text: "+ Oxidize"
                onClicked: root._addStep("oxidize", "Oxidize")
            }
        }

        ListView {
            id: list
            objectName: "processStepList"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: controller ? controller.processFlowModel : null
            delegate: ItemDelegate {
                id: stepDelegate
                width: ListView.view ? ListView.view.width : 0
                height: 32
                highlighted: model.stepId === root.selectedStepId
                onClicked: { root.selectedStepId = model.stepId; root.stepSelected(model.stepId) }
                // Single left-anchored Row, every child a fixed pixel
                // width -- see file header comment / RegionList.qml.
                //
                // Task 15 (real-display verification) finding: this row
                // originally totaled ~296px (checkbox 28 + name 100 +
                // operation 52 + four 20-22px buttons + spacing/margin).
                // At a real 1280x900 window, this panel's six SplitView
                // siblings' combined preferred widths exceed the window
                // width, so the SplitView compresses this panel well below
                // its own SplitView.preferredWidth of 260 -- down to
                // roughly its 200px SplitView.minimumWidth (~182px of
                // usable inner width after Theme.pad margins) in practice.
                // The move-up/down, duplicate, and remove buttons were
                // entirely clipped and invisible as a result. Confirmed by
                // a real grabWindow() screenshot before this fix. The
                // now-redundant per-row operation label (name already
                // mirrors it, e.g. "Substrate"/"Implant") was dropped and
                // the remaining widths tightened so the row fits in ~153px
                // -- comfortably under the ~182px compressed budget above,
                // not just the wider preferred-width case.
                contentItem: Row {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 4
                    spacing: 3
                    CheckBox {
                        checked: model.enabled
                        width: 18; height: 24
                        onToggled: controller.setProcessStepEnabled(model.stepId, checked)
                    }
                    Text {
                        text: (index + 1) + ". " + model.name
                        color: Theme.text
                        font.pixelSize: 12
                        width: 46; height: 20
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                        ToolTip.text: model.operation
                        ToolTip.visible: nameHover.hovered
                        HoverHandler { id: nameHover }
                    }
                    Button {
                        text: "▲"; flat: true
                        enabled: index > 0
                        width: 18; height: 24
                        leftPadding: 1; rightPadding: 1
                        ToolTip.text: "Move up"; ToolTip.visible: hovered
                        onClicked: controller.moveProcessStep(model.stepId, -1)
                    }
                    Button {
                        text: "▼"; flat: true
                        enabled: index < list.count - 1
                        width: 18; height: 24
                        leftPadding: 1; rightPadding: 1
                        ToolTip.text: "Move down"; ToolTip.visible: hovered
                        onClicked: controller.moveProcessStep(model.stepId, +1)
                    }
                    Button {
                        text: "⧉"; flat: true
                        width: 18; height: 24
                        leftPadding: 1; rightPadding: 1
                        ToolTip.text: "Duplicate"; ToolTip.visible: hovered
                        onClicked: controller.duplicateProcessStep(model.stepId)
                    }
                    Button {
                        text: "x"; flat: true
                        width: 16; height: 24
                        leftPadding: 1; rightPadding: 1
                        ToolTip.text: "Remove"; ToolTip.visible: hovered
                        onClicked: controller.removeProcessStep(model.stepId)
                    }
                }
                background: Rectangle {
                        color: highlighted ? Theme.accentSoft : "transparent"
                        Behavior on color { ColorAnimation { duration: Theme.animFast } }
                    }
            }
        }

        // Per-operation step editors: all four are always instantiated
        // and gated purely by `visible`, mirroring StructurePanel.qml's
        // always-instantiated-but-data-may-be-null pattern for its own
        // per-selection editors (RegionList/DopingEditor, ContactList/
        // ContactEditor, GateList/GateEditor).
        SubstrateEditor {
            Layout.fillWidth: true
            visible: root.selectedOperation === "substrate"
            controller: root.controller
            stepId: root.selectedStepId
            parameters: root.selectedParameters
        }
        ImplantEditor {
            Layout.fillWidth: true
            visible: root.selectedOperation === "implant"
            controller: root.controller
            stepId: root.selectedStepId
            parameters: root.selectedParameters
        }
        AnnealEditor {
            Layout.fillWidth: true
            visible: root.selectedOperation === "anneal"
            controller: root.controller
            stepId: root.selectedStepId
            parameters: root.selectedParameters
        }
        OxidizeEditor {
            Layout.fillWidth: true
            visible: root.selectedOperation === "oxidize"
            controller: root.controller
            stepId: root.selectedStepId
            parameters: root.selectedParameters
        }

        // Design section 19: per-step derived quantities (junction depth,
        // peak concentration/depth/dose per species, sheet resistance,
        // oxide bookkeeping), refreshed off the selected step and off a
        // fresh process run (see DerivedQuantitiesPanel.qml).
        DerivedQuantitiesPanel {
            Layout.fillWidth: true
            controller: root.controller
            stepId: root.selectedStepId
        }

        // Process-flow validation, mirroring StructurePanel.qml's
        // ValidationPanel but reading processValidationErrors instead of
        // the (default) structureValidationErrors.
        ValidationPanel {
            objectName: "processValidationPanel"
            Layout.fillWidth: true
            controller: root.controller
            errorsProperty: "processValidationErrors"
        }
    }
}
