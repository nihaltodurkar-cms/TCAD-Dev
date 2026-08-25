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
                // the family stepper follows the same contact registry
                if (familySteppedBox.model !== names)
                    familySteppedBox.model = names
                if (names.indexOf(familySteppedBox.currentText) < 0)
                    familySteppedBox.currentIndex = names.length ? 0 : -1
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

        // ---- batch families: N curves at stepped terminal biases ----
        Label {
            text: "FAMILY (batch)"
            color: Theme.textDim; font.pixelSize: 11; font.letterSpacing: 1
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Step"; Layout.preferredWidth: 46 }
            ComboBox {
                id: familySteppedBox
                objectName: "familySteppedBox"
                Layout.fillWidth: true
                model: root.controller ? root.controller.sweepContactNames : []
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "V"; Layout.preferredWidth: 12 }
            TextField {
                id: famStart
                objectName: "familyStartField"; Layout.fillWidth: true
                text: "0.0"; validator: DoubleValidator {}
            }
            TextField {
                id: famStop
                objectName: "familyStopField"; Layout.fillWidth: true
                text: "1.0"; validator: DoubleValidator {}
            }
            TextField {
                id: famStep
                objectName: "familyStepField"; Layout.fillWidth: true
                text: "0.5"; validator: DoubleValidator {}
            }
        }
        Button {
            objectName: "runFamilyButton"
            Layout.fillWidth: true
            enabled: root.controller && !root.controller.busy
                     && root.controller.hasResult
            text: "Run family"
            onClicked: {
                var fs = root.controller.familySweep
                fs.configureFamily(familySteppedBox.currentText,
                                   parseFloat(famStart.text),
                                   parseFloat(famStop.text),
                                   parseFloat(famStep.text))
                fs.runFamily(contactBox.currentText,
                             parseFloat(startField.text),
                             parseFloat(stopField.text),
                             parseFloat(stepField.text))
            }
        }
        Label {
            objectName: "familyStatusLabel"
            color: root.controller && root.controller.familySweep.hasCurves
                   ? Theme.ok : Theme.textDim
            font.pixelSize: Theme.fsSmall
            text: root.controller && root.controller.familySweep.hasCurves
                  ? root.controller.familySweep.curves.length + " curve(s) ready"
                  : "no family yet"
        }


        // ---- C-V: quasi-static MOS capacitance sweep ----------------
        Label {
            text: "MOS C-V"
            color: Theme.textDim; font.pixelSize: 11; font.letterSpacing: 1
        }
        RowLayout {
            Layout.fillWidth: true
            Label { text: "Nsub"; Layout.preferredWidth: 40 }
            TextField {
                id: cvNsub
                objectName: "cvNsubField"; Layout.fillWidth: true
                text: "-1e17"; validator: DoubleValidator {}
                ToolTip.visible: hovered; ToolTip.delay: 400
                ToolTip.text: "Substrate doping [cm^-3], negative for p-type."
            }
            Label { text: "tox nm"; Layout.preferredWidth: 42 }
            TextField {
                id: cvTox
                objectName: "cvToxField"; Layout.preferredWidth: 56
                text: "5.0"; validator: DoubleValidator {}
            }
        }
        Button {
            objectName: "runCVButton"
            Layout.fillWidth: true
            text: "Run C-V"
            onClicked: if (root.controller) root.controller.cv.runCV(
                parseFloat(cvNsub.text), parseFloat(cvTox.text),
                -2.0, 2.0, 0.05)
        }

        Item { Layout.fillHeight: true }
    }
}
