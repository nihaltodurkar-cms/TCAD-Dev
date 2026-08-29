import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

Rectangle {
    color: Theme.panel
    border.color: Theme.border
    property var consoleModel
    property string statusText: ""
    property bool busy: false

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: 4

        ListView {
            id: lines
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: consoleModel
            // follow the tail as new lines arrive
            onCountChanged: positionViewAtEnd()
            delegate: Label {
                width: lines.width
                text: model.line
                color: Theme.text
                font.family: Theme.mono
                font.pixelSize: 11
                wrapMode: Text.NoWrap
            }
        }
    }
}
