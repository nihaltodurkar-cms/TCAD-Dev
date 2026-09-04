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

        // v2 reskin: the stats block reads as a small card-grid (one
        // tile per mesh axis) instead of bare mono-font label lines --
        // same controller.meshStats data as before, only the display
        // changed (spec section 8, item 1: this is the panel the user
        // named explicitly as feeling cramped/basic).
        Label {
            // Matches the app's existing section-subheader convention
            // (StructurePanel's "CONTACTS"/"GATES", SweepPanel's
            // "FAMILY (batch)"/"MOS C-V", MeshEditor's own "MESH") --
            // Theme.fsSmall, not bold, not the panel-title weight.
            text: "MESH STATISTICS"
            color: Theme.textDim
            font.pixelSize: Theme.fsSmall
            font.letterSpacing: 1
        }

        Label {
            objectName: "meshStatsNoControllerLabel"
            visible: !controller
            text: "No controller"
            color: Theme.textFaint
            font.pixelSize: Theme.fsSmall
        }
        Label {
            objectName: "meshStatsNoDataLabel"
            visible: !!controller && !controller.meshStats
            text: "No mesh data"
            color: Theme.textFaint
            font.pixelSize: Theme.fsSmall
        }

        GridLayout {
            objectName: "meshStatsGrid"
            visible: !!controller && !!controller.meshStats
            Layout.fillWidth: true
            columns: 2
            columnSpacing: Theme.padSm
            rowSpacing: Theme.padSm

            Rectangle {
                objectName: "meshStatsTotalTile"
                Layout.fillWidth: true
                Layout.columnSpan: 2
                radius: Theme.radiusLg
                color: Theme.cardBg
                border.color: Theme.cardBorder
                implicitHeight: totalCol.implicitHeight + Theme.padSm * 2

                Column {
                    id: totalCol
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.margins: Theme.padSm
                    spacing: 2
                    Label {
                        text: "TOTAL NODES"
                        color: Theme.textFaint
                        font.pixelSize: Theme.fsTiny
                        font.letterSpacing: 1
                    }
                    Label {
                        text: controller && controller.meshStats ? String(controller.meshStats.node_count) : "0"
                        color: Theme.text
                        font.pixelSize: Theme.fsHeader
                        font.family: Theme.mono
                        font.bold: true
                    }
                }
            }

            Repeater {
                model: controller && controller.meshStats && controller.meshStats.axes ? Object.keys(controller.meshStats.axes) : []
                delegate: Rectangle {
                    objectName: "meshStatsAxisTile"
                    required property string modelData
                    Layout.fillWidth: true
                    radius: Theme.radiusLg
                    color: Theme.cardBg
                    border.color: Theme.cardBorder
                    implicitHeight: axisCol.implicitHeight + Theme.padSm * 2

                    Column {
                        id: axisCol
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.margins: Theme.padSm
                        spacing: 2
                        Label {
                            text: modelData.toUpperCase() + " AXIS"
                            color: Theme.textFaint
                            font.pixelSize: Theme.fsTiny
                            font.letterSpacing: 1
                        }
                        Label {
                            text: (controller.meshStats.axes[modelData].size || 0) + " nodes"
                            color: Theme.text
                            font.pixelSize: Theme.fsBody
                            font.family: Theme.mono
                            font.bold: true
                        }
                        Label {
                            text: (controller.meshStats.axes[modelData].min * 1e4).toFixed(2) + " – " +
                                  (controller.meshStats.axes[modelData].max * 1e4).toFixed(2) + " µm"
                            color: Theme.textDim
                            font.pixelSize: Theme.fsTiny
                            font.family: Theme.mono
                        }
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
