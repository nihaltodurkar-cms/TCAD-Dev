import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    id: root
    color: "transparent"
    border.color: "transparent"
    property var controller

    // v3.0 glassmorphism: icon + label rows with a solid gradient pill
    // for the selected item (matching the reference design), instead
    // of a plain text row with a faint tint. "Project" is now a real
    // row in the model (was previously a separate header Label above
    // the list) so every row gets the same icon+pill treatment.
    readonly property var _rows: ["Project", "Process", "Structure", "Mesh", "Device", "Results"]
    readonly property var _icons: ({
        "Project": "project", "Process": "process", "Structure": "structure",
        "Mesh": "mesh", "Device": "builder", "Results": "telemetry"
    })

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
            spacing: Theme.padXs
            model: root._rows
            currentIndex: 2

            delegate: ItemDelegate {
                required property var modelData
                required property int index
                width: list.width
                height: 32
                highlighted: list.currentIndex === index
                onClicked: {
                    list.currentIndex = index
                    if (root.controller)
                        root.controller.selectNode(modelData.toLowerCase())
                }
                contentItem: Row {
                    spacing: Theme.padSm
                    leftPadding: Theme.padSm
                    Image {
                        anchors.verticalCenter: parent.verticalCenter
                        source: Icons.svg(root._icons[modelData] || "project",
                                          highlighted ? "#ffffff" : Theme.textDim)
                        sourceSize.width: 16
                        sourceSize.height: 16
                        width: 16
                        height: 16
                    }
                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData
                        color: highlighted ? "#ffffff" : Theme.text
                        font.bold: highlighted
                        verticalAlignment: Text.AlignVCenter
                        Behavior on color { ColorAnimation { duration: Theme.animFast } }
                    }
                }
                background: Rectangle {
                    radius: Theme.radiusLg
                    color: highlighted ? "transparent" : (parent.hovered ? Theme.hoverOverlay : "transparent")
                    Behavior on color { ColorAnimation { duration: Theme.animFast } }

                    Rectangle {
                        anchors.fill: parent
                        visible: highlighted
                        radius: parent.radius
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: Theme.accentGradientStart }
                            GradientStop { position: 1.0; color: Theme.accentGradientEnd }
                        }
                    }
                }
            }
        }
    }
}
