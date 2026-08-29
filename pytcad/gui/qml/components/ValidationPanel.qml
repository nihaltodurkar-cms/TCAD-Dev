import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ColumnLayout {
    property var controller
    // Which controller property to read the error-list from. Defaults to
    // the v0.2 structure-validation property so StructurePanel.qml's
    // existing call site (no errorsProperty override) keeps working
    // unchanged; ProcessPanel.qml's second instance overrides this to
    // "processValidationErrors" (Task 13). Bracket access on the
    // exposed QObject is valid because every Q_PROPERTY-backed Python
    // property is a plain JS-visible property from QML.
    property string errorsProperty: "structureValidationErrors"

    readonly property var errors: controller ? controller[errorsProperty] : []

    RowLayout {
        Label { text: "VALIDATION"; color: Theme.textDim; font.pixelSize: 11; font.letterSpacing: 1 }
        Item { Layout.fillWidth: true }
        Label {
            text: errors.length === 0 ? "OK" : "FAILED"
            color: errors.length === 0 ? Theme.ok : Theme.error
        }
    }

    ListView {
        Layout.fillWidth: true
        Layout.preferredHeight: 100
        clip: true
        model: errors
        delegate: Label {
            text: "✕ " + modelData
            color: Theme.error
            wrapMode: Text.WordWrap
            width: parent ? parent.width : 200
        }
    }
}
