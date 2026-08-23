import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    color: Theme.panel
    border.color: Theme.border
    property var propertiesModel

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.pad

        Label {
            text: "PROPERTIES"
            color: Theme.textDim
            font.pixelSize: 11
            font.letterSpacing: 1
        }

        ListView {
            id: rows
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: propertiesModel
            delegate: RowLayout {
                width: rows.width
                spacing: Theme.pad
                Label {
                    text: model.key
                    color: Theme.textDim
                    elide: Text.ElideRight
                    Layout.preferredWidth: rows.width * 0.45
                }
                Label {
                    text: model.value
                    color: Theme.text
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }
        }
    }
}
