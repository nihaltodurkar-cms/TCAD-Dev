import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ColumnLayout {
    objectName: "gateEditor"
    property var controller
    property string gateId: ""
    property var gateData: null   // {name, tox, vfbMode, vfbValue, voltage}

    Label { text: "Gate"; color: Theme.textDim; font.pixelSize: 11 }
    Label { text: gateData ? gateData.name : ""; color: Theme.text }

    RowLayout {
        Label {
            text: "tox [nm]"; color: Theme.textDim; Layout.preferredWidth: 80
            HoverHandler { id: hTox }
            ToolTip.visible: hTox.hovered; ToolTip.delay: 400
            ToolTip.text: "Gate-oxide thickness. Below ~2 nm direct tunneling leakage appears -- not modeled here."
        }
        ValidatedTextField {
            objectName: "gateToxField"
            Layout.fillWidth: true
            text: gateData ? (gateData.tox * 1e7).toString() : ""
            onEditingFinished: if (gateId) controller.setGateToxCm(gateId, parseFloat(text) / 1e7)
        }
    }

    RowLayout {
        Label {
            text: "V [V]"; color: Theme.textDim; Layout.preferredWidth: 80
            HoverHandler { id: hGV }
            ToolTip.visible: hGV.hovered; ToolTip.delay: 400
            ToolTip.text: "Gate voltage vs body. Above threshold it inverts the surface and forms a channel."
        }
        ValidatedTextField {
            objectName: "gateVoltageField"
            Layout.fillWidth: true
            text: gateData ? gateData.voltage.toString() : ""
            onEditingFinished: if (gateId) controller.setGateVoltage(gateId, parseFloat(text))
        }
    }

    RowLayout {
        Label { text: "Vfb mode"; color: Theme.textDim; Layout.preferredWidth: 80 }
        ThemedComboBox {
            id: modeBox
            objectName: "gateVfbModeBox"
            Layout.preferredWidth: 120
            model: ["computed", "manual"]
            currentIndex: gateData && gateData.vfbMode === "manual" ? 1 : 0
            onActivated: if (gateId) controller.setGateVfbMode(
                gateId, currentText, manualField.text ? parseFloat(manualField.text) : 0.0)
        }
    }
    RowLayout {
        visible: modeBox.currentText === "manual"
        Label { text: "Vfb [V]"; color: Theme.textDim; Layout.preferredWidth: 80 }
        ValidatedTextField {
            id: manualField
            objectName: "gateVfbValueField"
            Layout.fillWidth: true
            // Python None crosses to QML as undefined, not null (PySide's
            // QVariant() mapping) -- `!= null` (loose) catches both;
            // `!== null` alone let `undefined.toString()` through and
            // threw a TypeError whenever a gate was in "computed" mode.
            text: gateData && gateData.vfbValue != null ? gateData.vfbValue.toString() : ""
            onEditingFinished: if (gateId) controller.setGateVfbMode(gateId, "manual", parseFloat(text))
        }
    }
}
