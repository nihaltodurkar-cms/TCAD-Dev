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

    function setViewMode(mode) {
        root.currentMode = mode
        canvas.setMode(mode)
        // "doping" needs structure/mesh data too, so the pre-solve doping
        // preview has something to rasterize before any ResultStore exists.
        if (mode === "structure" || mode === "mesh" || mode === "doping") {
            canvas.setStructureSource(controller.structureForQml, controller.meshModelForQml)
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

    Component.onCompleted: if (controller) canvas.bindController(controller)
}
