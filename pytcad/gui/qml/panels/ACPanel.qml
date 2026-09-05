import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// M18 Phase 4: configure the AC/Y-parameter sweep Run() will attach
// to the solve. Pure presentation -- every value goes straight into
// AppController.setACConfig()/clearACConfig(); validation lives in
// the controller, same split TransientPanel.qml/SweepPanel.qml use:
// numeric values are checked immediately at arm time, contact-name
// validity is checked at Run time against the loaded device.
Rectangle {
    id: root
    objectName: "acPanel"
    color: Theme.panel
    border.color: Theme.border
    property var controller
    // Set when the controller rejects an arm attempt. The fields are
    // then reverted to the LIVE armed values, mirroring SweepPanel's
    // lastArmRejected/revertToArmed pair exactly.
    property bool lastArmRejected: false

    function revertToArmed() {
        if (!root.controller) return
        var cfg = root.controller.acConfig()
        if (!cfg) return
        var names = root.controller.sweepContactNames
        var idx = names.indexOf ? names.indexOf(cfg.contact) : -1
        if (idx >= 0) contactBox.currentIndex = idx
        fStartField.text = String(cfg.f_start)
        fStopField.text = String(cfg.f_stop)
        nPointsField.text = String(cfg.n_points)
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: Theme.pad

        Label {
            text: "AC / Y-parameter sweep"
            font.bold: true
            color: Theme.text
            font.pixelSize: Theme.fsHeader
        }

        Label {
            visible: root.controller ? !root.controller.canRunAc : false
            text: "AC analysis is not available for a 3D device."
            color: Theme.warning
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
            font.italic: true
        }

        ColumnLayout {
            visible: root.controller ? root.controller.canRunAc : true
            spacing: Theme.pad
            Layout.fillWidth: true

            Label {
                text: "One port is driven with a unit AC voltage; every " +
                      "other port is AC-grounded. Runs at the device's " +
                      "ordinary equilibrium+bias operating point."
                color: Theme.textFaint
                font.pixelSize: Theme.fsTiny
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            Label { text: "Drive port"; color: Theme.textDim }
            ComboBox {
                id: contactBox
                objectName: "acContactBox"
                Layout.fillWidth: true
                model: root.controller ? root.controller.sweepContactNames : []
                Connections {
                    target: root.controller
                    function onStructureChanged() {
                        var names = root.controller.sweepContactNames
                        contactBox.model = names
                        if (names.indexOf(contactBox.currentText) < 0)
                            contactBox.currentIndex = names.length ? 0 : -1
                    }
                    function onErrorRaised(summary, details) {
                        if (summary === "Invalid AC configuration") {
                            root.lastArmRejected = true
                            root.revertToArmed()
                        }
                    }
                    function onAcChanged() {
                        root.lastArmRejected = false
                    }
                }
            }

            Label { text: "Start frequency [Hz]"; color: Theme.textDim }
            TextField {
                id: fStartField
                objectName: "acFStartField"
                Layout.fillWidth: true
                text: "1.0"
                validator: DoubleValidator { bottom: 0.0 }
            }
            Label { text: "Stop frequency [Hz]"; color: Theme.textDim }
            TextField {
                id: fStopField
                objectName: "acFStopField"
                Layout.fillWidth: true
                text: "1e9"
                validator: DoubleValidator { bottom: 0.0 }
            }
            Label { text: "Points (log-spaced)"; color: Theme.textDim }
            TextField {
                id: nPointsField
                objectName: "acNPointsField"
                Layout.fillWidth: true
                text: "40"
                validator: IntValidator { bottom: 2 }
            }

            RowLayout {
                Layout.fillWidth: true
                Button {
                    objectName: "applyAcButton"
                    text: "Arm AC sweep"
                    Layout.fillWidth: true
                    onClicked: if (root.controller)
                        root.controller.setACConfig(
                            contactBox.currentText,
                            parseFloat(fStartField.text),
                            parseFloat(fStopField.text),
                            parseInt(nPointsField.text))
                }
                Button {
                    objectName: "clearAcButton"
                    text: "Clear"
                    enabled: root.controller ? root.controller.hasACConfig : false
                    onClicked: if (root.controller) root.controller.clearACConfig()
                }
            }

            Label {
                objectName: "acStatusLabel"
                color: root.controller && root.controller.hasACConfig
                       ? Theme.ok : Theme.textDim
                text: root.controller && root.controller.hasACConfig
                      ? "AC sweep armed" : "no AC sweep configured"
            }

            Label {
                objectName: "acRejectNote"
                visible: root.lastArmRejected
                // v2.1 correction (DESIGN.md section 3.3): a rejected arm
                // attempt is a warning, not "running".
                color: Theme.warning
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
                font.italic: true
                text: "Last arm attempt was rejected -- the fields show the currently armed configuration."
            }
        }

        Item { Layout.fillHeight: true }
    }
}
