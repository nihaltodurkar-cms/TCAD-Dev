import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import PyTCAD 1.0
import ".."

Rectangle {
    id: root
    color: Theme.background
    border.color: Theme.border
    property var controller
    property string currentMode: "doping"   // mirrors MplCanvasItem's own default
    // Which process step's checkpoint the "process" mode plot shows.
    // "" means "no explicit selection yet" -- setProcessSource() then
    // leaves ProcessResultStore's own default (the flow's last step) in
    // place rather than forcing one.
    property string currentProcessStepId: ""

    function setViewMode(mode) {
        root.currentMode = mode
        canvas.setMode(mode)
        // "doping" needs structure/mesh data too, so the pre-solve doping
        // preview has something to rasterize before any ResultStore exists.
        if (mode === "structure" || mode === "mesh" || mode === "doping") {
            canvas.setStructureSource(controller.structureForQml, controller.meshModelForQml)
        }
        if (mode === "process") {
            canvas.setProcessSource(controller.processResultForQml, root.currentProcessStepId)
        }
        if (mode === "series") {
            // v0.4: hand the executed sweep (or null before any swept run)
            // to the canvas, then refresh the channel selector from it.
            canvas.setSweepSource(controller.sweepResultForQml)
            sweepChannelBox.model = canvas.availableSweepChannels()
            if (sweepChannelBox.model.length)
                sweepChannelBox.currentIndex =
                    Math.max(0, sweepChannelBox.model.indexOf(canvas._sweep_channel))
        }
    }

    // Called from Main.qml on ProcessPanel.stepSelected -- lets clicking a
    // step in the process list drive which checkpoint the viewport plots,
    // independent of whether "process" mode is currently active.
    function setProcessStep(stepId) {
        root.currentProcessStepId = stepId
        if (root.currentMode === "process") {
            canvas.setProcessSource(controller.processResultForQml, stepId)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.pad

        RowLayout {
            Layout.fillWidth: true
            spacing: 4

            ComboBox {
                id: fieldBox
                Layout.preferredWidth: 200
                model: controller ? controller.fieldNames : []
                onActivated: if (controller) controller.setField(currentText)
                Connections {
                    target: controller
                    function onResultChanged() {
                        fieldBox.model = controller.fieldNames
                        fieldBox.currentIndex =
                            Math.max(0, fieldBox.model.indexOf(controller.currentField))
                    }
                }
            }
            CheckBox {
                text: "log scale"
                onToggled: canvas.logScale = checked
            }
            ComboBox {
                id: sweepChannelBox
                objectName: "sweepChannelSelector"
                visible: root.currentMode === "series"
                Layout.preferredWidth: 150
                model: []
                onActivated: canvas.setSweepChannel(currentText)
            }
            Item { Layout.fillWidth: true }
            Button { text: "Zoom in";  onClicked: canvas.zoom(0.8) }
            Button { text: "Zoom out"; onClicked: canvas.zoom(1.25) }
            Button { text: "Fit";      onClicked: canvas.fit() }
            Button { text: "Reset";    onClicked: canvas.resetView() }
        }

        MplCanvas {
            id: canvas
            objectName: "mplCanvas"
            Layout.fillWidth: true
            Layout.fillHeight: true

            MouseArea {
                anchors.fill: parent
                property real lastX: 0
                property real lastY: 0
                onPressed: (m) => { lastX = m.x; lastY = m.y }
                onPositionChanged: (m) => {
                    if (!pressed) return
                    // drag right -> view moves left, so negate
                    canvas.pan(-(m.x - lastX) / width, -(m.y - lastY) / height)
                    lastX = m.x; lastY = m.y
                }
                onWheel: (w) => canvas.zoom(w.angleDelta.y > 0 ? 0.9 : 1.111)
            }
        }
    }

    // A structure load (example or project) emits structureChanged but not
    // resultChanged, so bindController()'s refresh alone never re-applies
    // the current mode to the canvas -- without this, a freshly-loaded
    // structure left "Doping" mode showing stale "No project loaded" until
    // the mode selector was touched by hand. Re-applying on every edit also
    // keeps the pre-solve doping preview live as regions change.
    Connections {
        target: controller
        function onStructureChanged() {
            if (controller) root.setViewMode(root.currentMode)
        }
    }

    // A fresh process run emits processResultChanged, not structureChanged --
    // without this, running a flow while "Process" mode was already selected
    // left the viewport showing whatever it had before the run (or the
    // "No project loaded" placeholder) until the mode selector was re-touched
    // by hand. Mirrors the structureChanged Connections above.
    Connections {
        target: controller
        function onProcessResultChanged() {
            if (controller && root.currentMode === "process") root.setViewMode(root.currentMode)
        }
    }

    // v0.4: same trap, sweep edition -- a finished swept run emits
    // resultChanged only; without this, "Curves" mode kept showing the
    // previous state until the mode selector was re-touched by hand.
    Connections {
        target: controller
        function onResultChanged() {
            if (controller && root.currentMode === "series") root.setViewMode(root.currentMode)
        }
    }

    Component.onCompleted: if (controller) canvas.bindController(controller)
}
