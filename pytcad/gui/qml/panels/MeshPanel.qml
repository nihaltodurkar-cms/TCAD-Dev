import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import ".."

Rectangle {
    color: Theme.panel
    border.color: Theme.border
    property var controller

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.pad
        MeshEditor { controller: parent.parent.controller; Layout.fillWidth: true }

        // Phase 3c: mesh statistics panel
        Label {
            text: "Mesh statistics"
            color: Theme.textDim
            font.pixelSize: 10
            font.bold: true
        }
        Column {
            Layout.fillWidth: true
            spacing: 2
            Label {
                text: controller ? controller.meshStats ? "Nodes: " + controller.meshStats.node_count : "No mesh data" : "No controller"
                color: Theme.text
                font.pixelSize: 10
                font.family: Theme.mono
            }
            Repeater {
                model: controller && controller.meshStats && controller.meshStats.axes ? Object.keys(controller.meshStats.axes) : []
                Label {
                    text: modelData + ": " + (controller.meshStats.axes[modelData].size || 0) + " nodes ("
                        + (controller.meshStats.axes[modelData].min * 1e4).toFixed(2) + " to "
                        + (controller.meshStats.axes[modelData].max * 1e4).toFixed(2) + " um)"
                    color: Theme.textDim
                    font.pixelSize: 10
                    font.family: Theme.mono
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
