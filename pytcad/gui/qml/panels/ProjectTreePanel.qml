import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root
    color: Theme.panel
    border.color: Theme.border
    property var controller

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.pad

        Label {
            text: "PROJECT"
            color: Theme.textDim
            font.pixelSize: 11
            font.letterSpacing: 1
        }

        // v0.1 keeps the tree flat-but-nested via a static column: the
        // workflow stages are fixed, and a full QTreeView-style delegate
        // is not worth its complexity until the nodes gain children.
        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: ["Process", "Structure", "Mesh", "Device", "Results"]
            currentIndex: 1

            header: Label {
                text: "Project"
                color: Theme.text
                font.bold: true
                padding: 4
            }

            delegate: ItemDelegate {
                width: list.width
                height: 26
                highlighted: list.currentIndex === index
                onClicked: {
                    list.currentIndex = index
                    if (root.controller)
                        root.controller.selectNode(modelData.toLowerCase())
                }
                contentItem: Label {
                    text: "  " + modelData
                    color: highlighted ? Theme.accent : Theme.text
                    verticalAlignment: Text.AlignVCenter
                }
                background: Rectangle {
                    color: highlighted ? Theme.panelAlt : "transparent"
                    radius: Theme.radius
                }
            }
        }
    }
}
