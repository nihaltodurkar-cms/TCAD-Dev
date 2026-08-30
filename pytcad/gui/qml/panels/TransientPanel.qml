import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// M17 phase 3: configure the time-domain waveform Run() will attach to
// the solve. Pure presentation -- every value goes straight into
// AppController.setTransientConfig()/clearTransientConfig(); validation
// lives in the controller, same split SweepPanel.qml already uses:
// numeric values are checked immediately at arm time, contact-name
// validity is checked at Run time against the loaded device.
Rectangle {
    id: root
    color: Theme.panel
    border.color: Theme.border
    property var controller
    // Set when the controller rejects an arm attempt. The fields are
    // then reverted to the LIVE armed values, mirroring SweepPanel's
    // lastArmRejected/revertToArmed pair exactly.
    property bool lastArmRejected: false

    function revertToArmed() {
        if (!root.controller) return
        var cfg = root.controller.transientConfig()
        if (!cfg) return
        var names = root.controller.sweepContactNames
        var idx = names.indexOf ? names.indexOf(cfg.contact) : -1
        if (idx >= 0) contactBox.currentIndex = idx
        var kidx = kindBox.model.indexOf(cfg.kind)
        if (kidx >= 0) kindBox.currentIndex = kidx
        v0Field.text = String(cfg.v0)
        v1Field.text = String(cfg.v1)
        t0Field.text = String(cfg.t0)
        t1Field.text = String(cfg.t1)
        tEndField.text = String(cfg.t_end)
        dt0Field.text = String(cfg.dt0)
    }

    // Field labels depend on the selected waveform kind -- the four
    // numeric fields are the same TextFields regardless of kind, only
    // their meaning (and hence their label) changes.
    function t0Label(kind) {
        if (kind === "step") return "Switch time [s]"
        if (kind === "ramp") return "Start time [s]"
        if (kind === "pulse") return "Pulse start [s]"
        return "t0 [s] (unused)"
    }
    function t1Label(kind) {
        if (kind === "ramp") return "End time [s]"
        if (kind === "pulse") return "Pulse width [s]"
        return "t1 [s] (unused)"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.pad

        Label {
            text: "Transient (time-domain) run"
            font.bold: true
            color: Theme.text
            font.pixelSize: Theme.fsHeader
        }

        Label {
            text: "One stimulus contact follows the waveform below; every " +
                  "other contact holds its configured DC bias for the " +
                  "whole run."
            color: Theme.textFaint
            font.pixelSize: Theme.fsTiny
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }

        Label { text: "Contact"; color: Theme.textDim }
        ComboBox {
            id: contactBox
            objectName: "transientContactBox"
            Layout.fillWidth: true
            model: root.controller ? root.controller.sweepContactNames : []
            ToolTip.visible: hovered
            ToolTip.delay: 400
            ToolTip.text: "Which terminal follows the waveform; every other terminal holds its configured voltage."
            Connections {
                target: root.controller
                function onStructureChanged() {
                    var names = root.controller.sweepContactNames
                    contactBox.model = names
                    if (names.indexOf(contactBox.currentText) < 0)
                        contactBox.currentIndex = names.length ? 0 : -1
                }
                function onErrorRaised(summary, details) {
                    if (summary === "Invalid transient configuration") {
                        root.lastArmRejected = true
                        root.revertToArmed()
                    }
                }
                function onTransientChanged() {
                    root.lastArmRejected = false
                }
            }
        }

        Label { text: "Waveform"; color: Theme.textDim }
        ComboBox {
            id: kindBox
            objectName: "transientKindBox"
            Layout.fillWidth: true
            model: ["step", "ramp", "pulse", "constant"]
            ToolTip.visible: hovered
            ToolTip.delay: 400
            ToolTip.text: "step: instant switch. ramp: linear transition. pulse: temporary excursion. constant: no time dependence (a sanity/no-op run)."
        }

        Label { text: "Start bias v0 [V]"; color: Theme.textDim }
        TextField {
            id: v0Field
            objectName: "transientV0Field"
            Layout.fillWidth: true
            text: "0.0"
            validator: DoubleValidator {}
        }
        Label { text: "End bias v1 [V]"; color: Theme.textDim }
        TextField {
            id: v1Field
            objectName: "transientV1Field"
            Layout.fillWidth: true
            text: "0.0"
            validator: DoubleValidator {}
            enabled: kindBox.currentText !== "constant"
        }
        Label { text: t0Label(kindBox.currentText); color: Theme.textDim }
        TextField {
            id: t0Field
            objectName: "transientT0Field"
            Layout.fillWidth: true
            text: "0.0"
            validator: DoubleValidator {}
            enabled: kindBox.currentText !== "constant"
        }
        Label { text: t1Label(kindBox.currentText); color: Theme.textDim }
        TextField {
            id: t1Field
            objectName: "transientT1Field"
            Layout.fillWidth: true
            text: "0.0"
            validator: DoubleValidator {}
            enabled: kindBox.currentText === "ramp" || kindBox.currentText === "pulse"
        }

        Label { text: "Run duration t_end [s]"; color: Theme.textDim }
        TextField {
            id: tEndField
            objectName: "transientTEndField"
            Layout.fillWidth: true
            text: "1e-9"
            validator: DoubleValidator { bottom: 0.0 }
            ToolTip.visible: hovered
            ToolTip.delay: 400
            ToolTip.text: "Total simulated time [s]. Pick a few multiples of the physical timescale you expect (e.g. a dielectric relaxation or transit time)."
        }
        Label { text: "Initial step dt0 [s]"; color: Theme.textDim }
        TextField {
            id: dt0Field
            objectName: "transientDt0Field"
            Layout.fillWidth: true
            text: "1e-11"
            validator: DoubleValidator { bottom: 0.0 }
            ToolTip.visible: hovered
            ToolTip.delay: 400
            ToolTip.text: "Starting time step [s]; the solver adapts it (grows on easy Newton solves, shrinks and retries on failure)."
        }

        RowLayout {
            Layout.fillWidth: true
            Button {
                objectName: "applyTransientButton"
                text: "Arm transient"
                Layout.fillWidth: true
                onClicked: if (root.controller)
                    root.controller.setTransientConfig(
                        contactBox.currentText, kindBox.currentText,
                        parseFloat(v0Field.text), parseFloat(v1Field.text),
                        parseFloat(t0Field.text), parseFloat(t1Field.text),
                        parseFloat(tEndField.text), parseFloat(dt0Field.text))
            }
            Button {
                objectName: "clearTransientButton"
                text: "Clear"
                enabled: root.controller ? root.controller.hasTransientConfig : false
                onClicked: if (root.controller) root.controller.clearTransientConfig()
            }
        }

        Label {
            objectName: "transientStatusLabel"
            color: root.controller && root.controller.hasTransientConfig
                   ? Theme.ok : Theme.textDim
            text: root.controller && root.controller.hasTransientConfig
                  ? "transient armed" : "no transient run configured"
        }

        Label {
            objectName: "transientRejectNote"
            visible: root.lastArmRejected
            color: Theme.running
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            font.italic: true
            text: "Last arm attempt was rejected -- the fields show the currently armed configuration."
        }

        Item { Layout.fillHeight: true }
    }
}
