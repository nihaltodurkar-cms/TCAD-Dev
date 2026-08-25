import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// v0.4: configure the voltage sweep Run() will attach to the solve.
// Pure presentation -- every value goes straight into
// AppController.setSweepConfig()/clearSweepConfig(); validation lives in
// the controller: numeric values are checked immediately at arm time
// (an invalid sweep raises errorRaised right here, without arming),
// while contact-name validity can only be judged against the loaded
// device and is checked at Run time.
Rectangle {
    id: root
    color: Theme.panel
    border.color: Theme.border
    property var controller
    // Set when the controller rejects an arm attempt (errorRaised with
    // the sweep summary). The fields are then reverted to the LIVE
    // armed values, so what's on screen is always what Run would use.
    property bool lastArmRejected: false

    function revertToArmed() {
        if (!root.controller) return
        var cfg = root.controller.sweepConfig()
        if (!cfg) return
        var names = root.controller.sweepContactNames
        var idx = names.indexOf ? names.indexOf(cfg.contact) : -1
        if (idx >= 0) contactBox.currentIndex = idx
        startField.text = String(cfg.start)
        stopField.text = String(cfg.stop)
        stepField.text = String(cfg.step)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.pad


        Label {
            text: "Voltage sweep"
            font.bold: true
            color: Theme.text
            font.pixelSize: Theme.fsHeader
        }

        Label {
            text: "One warm-started DC solve per point: each Newton run " +
                  "starts from the previous bias's solution."
            color: Theme.textFaint
            font.pixelSize: Theme.fsTiny
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Label { text: "Contact"; color: Theme.textDim }
        ComboBox {
            id: contactBox
            objectName: "sweepContactBox"
            Layout.fillWidth: true
            model: root.controller ? root.controller.sweepContactNames : []
            ToolTip.visible: hovered
            ToolTip.delay: 400
            ToolTip.text: "Which terminal is ramped; every other terminal holds its configured voltage."
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
            function onErrorRaised(summary, details) {
                if (summary === "Invalid sweep configuration") {
                    root.lastArmRejected = true
                    root.revertToArmed()
                }
            }
            function onSweepChanged() {
                root.lastArmRejected = false
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
            ToolTip.visible: hovered
            ToolTip.delay: 400
            ToolTip.text: "First sweep point [V]. Usually the equilibrium, 0 V."
        }
        Label { text: "Stop [V]"; color: Theme.textDim }
        TextField {
            id: stopField
            objectName: "sweepStopField"
            Layout.fillWidth: true
            text: "1.0"
            validator: DoubleValidator {}
            ToolTip.visible: hovered
            ToolTip.delay: 400
            ToolTip.text: "Last sweep point [V]. Forward bias on a diode anode turns it on; reverse bias studies leakage/breakdown."
        }
        Label { text: "Step [V]"; color: Theme.textDim }
        TextField {
            id: stepField
            objectName: "sweepStepField"
            Layout.fillWidth: true
            text: "0.1"
            validator: DoubleValidator {}
            ToolTip.visible: hovered
            ToolTip.delay: 400
            ToolTip.text: "Voltage step between points [V]. Fine steps resolve sharp physics (subthreshold swing) but cost one Newton solve each."
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

        Label {
            objectName: "sweepRejectNote"
            visible: root.lastArmRejected
            color: Theme.running
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            font.italic: true
            text: "Last arm attempt was rejected -- the fields show the currently armed sweep."
        }

        Item { Layout.fillHeight: true }
    }
}
