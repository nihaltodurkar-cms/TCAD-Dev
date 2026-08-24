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
            text: lab.selectedDetail() ? lab.selectedDetail().title : ""
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

        Item { Layout.fillHeight: true }

        Button {
            objectName: "showConvergenceButton"
            text: "Plot convergence"
            Layout.fillWidth: true
            enabled: lab.hasRunRecord()
            onClicked: root.plotConvergenceRequested()
        }
    }
}
