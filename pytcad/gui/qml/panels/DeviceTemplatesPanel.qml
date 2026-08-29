import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// Device Builder (v0.5.0 M5): parametric templates that build real
// devices into the existing Structure workbench -- no second editing
// path, just a fast front door.
Rectangle {
    id: root
    color: Theme.panel
    border.color: Theme.border
    property var builder: deviceBuilder

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.pad

        Label { text: "Device Builder"; font.bold: true; color: Theme.text }

        ComboBox {
            id: templateBox
            objectName: "templateBox"
            Layout.fillWidth: true
            model: root.builder.templateIds
            onActivated: root.builder.selectTemplate(currentText)
        }

        Label {
            text: root.builder.selectedParams().length + " parameters"
            color: Theme.textDim
            font.pixelSize: 10
        }

        // parameter editors for the selected template; the Repeater's
        // model re-evaluates whenever paramsChanged fires.
        Connections {
            target: root.builder
            function onParamsChanged() { paramColumn.rebuild() }
        }

        ColumnLayout {
            id: paramColumn
            objectName: "templateParamColumn"
            Layout.fillWidth: true
            spacing: 2

            property var entries: root.builder.selectedParams()
            function rebuild() {
                entries = root.builder.selectedParams()
            }
            Component.onCompleted: rebuild()

            Repeater {
                model: paramColumn.entries
                delegate: RowLayout {
                    width: parent.width
                    Label {
                        text: modelData.label
                        color: Theme.textDim
                        font.pixelSize: 10
                        elide: Text.ElideRight
                    }
                    TextField {
                        objectName: "tplParam_" + modelData.name
                        property string pname: modelData.name
                        text: modelData.value
                        font.pixelSize: 10
                        Layout.fillWidth: true
                        onEditingFinished:
                            root.builder.setParameterValue(pname, text)
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }

        Button {
            objectName: "buildTemplateButton"
            text: "Build device"
            Layout.fillWidth: true
            onClicked: root.builder.build()
        }
    }
}
