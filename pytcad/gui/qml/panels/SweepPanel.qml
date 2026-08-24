import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// v0.4: configure the voltage sweep Run() will attach to the solve.
// Pure presentation -- every value goes straight into
// AppController.setSweepConfig()/clearSweepConfig(); validation and
// error reporting live in the controller (an invalid sweep raises
// errorRaised at Run time, not here).
Rectangle {
    id: root
    color: Theme.panel
    border.color: Theme.border
    property var controller

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.pad

        Label {
            text: "Voltage sweep"
            font.bold: true
            color: Theme.text
        }

        Label { text: "Contact"; color: Theme.textDim }
        ComboBox {
            id: contactBox
            objectName: "sweepContactBox"
            Layout.fillWidth: true
            model: root.controller ? root.controller.sweepContactNames : []
            Connections {
                target: root.controller
                // Candidates change with structure edits, project loads,
                // and process handoff; keep a still-valid selection.
                function onStructureChanged() {
                    var names = root.controller.sweepContactNames
                    contactBox.model = names
                    if (names.indexOf(contactBox.currentText) < 0)
                        contactBox.currentIndex = names.length ? 0 : -1
                }
            }
        }

        Label { text: "Start [V]"; color: Theme.textDim }
        TextField {
            id: startField
            objectName: "sweepStartField"
            Layout.fillWidth: true
            text: "0.0"
            validator: DoubleValidator {}
        }
        Label { text: "Stop [V]"; color: Theme.textDim }
        TextField {
            id: stopField
            objectName: "sweepStopField"
            Layout.fillWidth: true
            text: "1.0"
            validator: DoubleValidator {}
        }
        Label { text: "Step [V]"; color: Theme.textDim }
        TextField {
            id: stepField
            objectName: "sweepStepField"
            Layout.fillWidth: true
            text: "0.1"
            validator: DoubleValidator {}
        }

        RowLayout {
            Layout.fillWidth: true
            Button {
                objectName: "applySweepButton"
                text: "Arm sweep"
                Layout.fillWidth: true
                onClicked: if (root.controller)
                    root.controller.setSweepConfig(
                        contactBox.currentText,
                        parseFloat(startField.text),
                        parseFloat(stopField.text),
                        parseFloat(stepField.text))
            }
            Button {
                objectName: "clearSweepButton"
                text: "Clear"
                enabled: root.controller ? root.controller.hasSweepConfig : false
                onClicked: if (root.controller) root.controller.clearSweepConfig()
            }
        }

        Label {
            objectName: "sweepStatusLabel"
            color: root.controller && root.controller.hasSweepConfig
                   ? Theme.ok : Theme.textDim
            text: root.controller && root.controller.hasSweepConfig
                  ? "sweep armed" : "no sweep configured"
        }

        Item { Layout.fillHeight: true }
    }
}
