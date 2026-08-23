import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ColumnLayout {
    property var controller

    RowLayout {
        Label { text: "VALIDATION"; color: Theme.textDim; font.pixelSize: 11; font.letterSpacing: 1 }
        Item { Layout.fillWidth: true }
        Label {
            text: controller && controller.structureValidationErrors.length === 0 ? "OK" : "FAILED"
            color: controller && controller.structureValidationErrors.length === 0 ? Theme.ok : Theme.error
        }
    }

    ListView {
        Layout.fillWidth: true
        Layout.preferredHeight: 100
        clip: true
        model: controller ? controller.structureValidationErrors : []
        delegate: Label {
            text: "✕ " + modelData
            color: Theme.error
            wrapMode: Text.WordWrap
            width: parent ? parent.width : 200
        }
    }
}
