import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ColumnLayout {
    objectName: "contactEditor"
    property var controller
    property string contactId: ""
    property var contactData: null   // {name, edge, voltage}

    Label { text: "Contact"; color: Theme.textDim; font.pixelSize: 11 }
    Label { text: contactData ? contactData.name + "  (edge: " + contactData.edge + ")" : ""
           color: Theme.text }

    RowLayout {
        Label { text: "V [V]"; color: Theme.textDim; Layout.preferredWidth: 60 }
        ValidatedTextField {
            objectName: "contactVoltageField"
            Layout.fillWidth: true
            text: contactData ? contactData.voltage.toString() : "0.0"
            onEditingFinished: if (contactId) controller.setContactVoltage(contactId, parseFloat(text))
        }
    }
}
