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

    Component.onCompleted: if (controller) canvas.bindController(controller)
}
