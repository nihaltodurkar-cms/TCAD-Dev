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
        Item { Layout.fillHeight: true }
    }
}
