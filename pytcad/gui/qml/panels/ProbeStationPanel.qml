import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."
import "../components"

// Virtual Probe Station: DC/RF device characterization. A sweep-type
// selector plus point/bias/current-limit inputs drive `probeStation`
// (AppController.probeStation, ProbeStationController) -- "Load demo"
// synthesizes a curve in-process, "Run" would dispatch to a real solver
// backend (not yet wired -- see probe_station_controller.py's honest
// NotImplementedError stub). A simple polyline canvas stands in for a
// real plotting widget, matching this panel's own scope; the extraction
// results render as a plain list, same shape as PhysicsLabPanel's
// catalog/detail lists.
Rectangle {
    id: root
    color: Theme.panel
    border.color: Theme.border
    property var controller: probeStation

    property var sweepTypes: ["transfer", "output", "breakdown"]
    property int rfTabIndex: 1

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PanelHeader { title: "Virtual Probe Station"; Layout.fillWidth: true }

        TabBar {
            id: modeTabs
            Layout.fillWidth: true
            TabButton { text: "DC" }
            TabButton { text: "RF" }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: modeTabs.currentIndex

            // ---- DC sweep ----------------------------------------------
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.margins: Theme.pad
                    spacing: Theme.padSm

                    Label { text: "Sweep type"; color: Theme.textDim; font.pixelSize: Theme.fsSmall }
                    ComboBox {
                        id: sweepTypeBox
                        objectName: "probeSweepTypeBox"
                        Layout.fillWidth: true
                        model: root.sweepTypes
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "Start"; Layout.preferredWidth: 44; color: Theme.textDim }
                        ValidatedTextField {
                            id: startField
                            objectName: "probeStartField"
                            fieldName: "probe_start"
                            Layout.fillWidth: true
                            text: "0.0"
                            validator: DoubleValidator {}
                        }
                        Label { text: "Stop"; Layout.preferredWidth: 34; color: Theme.textDim }
                        ValidatedTextField {
                            id: stopField
                            objectName: "probeStopField"
                            fieldName: "probe_stop"
                            Layout.fillWidth: true
                            text: "1.5"
                            validator: DoubleValidator {}
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        Label { text: "Points"; Layout.preferredWidth: 44; color: Theme.textDim }
                        ValidatedTextField {
                            id: pointsField
                            objectName: "probePointsField"
                            fieldName: "probe_points"
                            Layout.fillWidth: true
                            text: "200"
                            validator: IntValidator { bottom: 2; top: 5000 }
                        }
                        Label { text: "Fixed bias"; Layout.preferredWidth: 64; color: Theme.textDim }
                        ValidatedTextField {
                            id: fixedBiasField
                            objectName: "probeFixedBiasField"
                            fieldName: "probe_fixed_bias"
                            Layout.fillWidth: true
                            text: "0.05"
                            validator: DoubleValidator {}
                            ToolTip.visible: hovered
                            ToolTip.delay: 400
                            ToolTip.text: "The OTHER terminal's held voltage (e.g. Vd for a Vg sweep)."
                        }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        visible: sweepTypeBox.currentText === "breakdown"
                        Label { text: "I limit [A]"; Layout.preferredWidth: 64; color: Theme.textDim }
                        ValidatedTextField {
                            id: currentLimitField
                            objectName: "probeCurrentLimitField"
                            fieldName: "probe_current_limit"
                            Layout.fillWidth: true
                            text: "1e-6"
                            validator: DoubleValidator {}
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Button {
                            objectName: "probeLoadDemoButton"
                            text: "Load demo"
                            Layout.fillWidth: true
                            onClicked: if (root.controller)
                                root.controller.loadDemo(sweepTypeBox.currentText)
                        }
                        Button {
                            objectName: "probeRunButton"
                            text: "Run"
                            Layout.fillWidth: true
                            enabled: root.controller ? !root.controller.isBusy : false
                            onClicked: if (root.controller)
                                root.controller.runSweep(sweepTypeBox.currentText, {
                                    "start": parseFloat(startField.text),
                                    "stop": parseFloat(stopField.text),
                                    "points": parseInt(pointsField.text),
                                    "fixed_bias": parseFloat(fixedBiasField.text),
                                    "current_limit": parseFloat(currentLimitField.text)
                                })
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.padSm
                        StatusIndicator {
                            busy: root.controller ? root.controller.isBusy : false
                            hasResult: root.controller ? root.controller.sweepX.length > 0 : false
                        }
                        Label {
                            objectName: "probeStatusLabel"
                            text: root.controller ? root.controller.status : ""
                            color: Theme.textDim
                            font.pixelSize: Theme.fsSmall
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                    }
                }

                // -- plot area --------------------------------------------
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 160
                    Layout.leftMargin: Theme.pad
                    Layout.rightMargin: Theme.pad
                    color: Theme.sunken
                    border.color: Theme.border

                    Canvas {
                        id: sweepCanvas
                        objectName: "probeSweepCanvas"
                        anchors.fill: parent
                        anchors.margins: 4
                        property var xs: root.controller ? root.controller.sweepX : []
                        property var ys: root.controller ? root.controller.sweepY : []
                        onXsChanged: requestPaint()
                        onYsChanged: requestPaint()
                        onPaint: {
                            var ctx = getContext("2d")
                            ctx.reset()
                            var xs = sweepCanvas.xs, ys = sweepCanvas.ys
                            if (!xs || xs.length < 2) return
                            var xmin = Math.min.apply(null, xs), xmax = Math.max.apply(null, xs)
                            var ymin = Math.min.apply(null, ys), ymax = Math.max.apply(null, ys)
                            if (xmax <= xmin) xmax = xmin + 1
                            if (ymax <= ymin) ymax = ymin + 1
                            ctx.strokeStyle = Theme.accent
                            ctx.lineWidth = 1.5
                            ctx.beginPath()
                            for (var i = 0; i < xs.length; i++) {
                                var px = (xs[i] - xmin) / (xmax - xmin) * width
                                var py = height - (ys[i] - ymin) / (ymax - ymin) * height
                                if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                            }
                            ctx.stroke()
                        }
                    }
                    Label {
                        anchors.centerIn: parent
                        visible: !(root.controller && root.controller.sweepX.length > 0)
                        text: "No sweep loaded"
                        color: Theme.textFaint
                        font.pixelSize: Theme.fsSmall
                    }
                }

                // -- extraction results -------------------------------------
                Label {
                    text: "EXTRACTED QUANTITIES"
                    color: Theme.textDim; font.pixelSize: 11; font.letterSpacing: 1
                    Layout.leftMargin: Theme.pad
                    Layout.topMargin: Theme.padSm
                }
                ListView {
                    id: extractionList
                    objectName: "probeExtractionList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.margins: Theme.pad
                    clip: true
                    model: root.controller ? root.controller.extractionModel : []
                    delegate: RowLayout {
                        width: extractionList.width
                        Label {
                            text: modelData.name
                            color: Theme.text
                            font.pixelSize: Theme.fsSmall
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                        Label {
                            text: modelData.display
                            color: Theme.accent
                            font.pixelSize: Theme.fsSmall
                            font.family: Theme.mono
                        }
                    }
                }
            }

            // ---- RF sub-tab ----------------------------------------------
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.margins: Theme.pad
                    spacing: Theme.padSm

                    Label {
                        text: "Unity current-gain frequency (fT) from a small-signal " +
                              "H21 (or Y21/Y11) sweep."
                        color: Theme.textFaint
                        font.pixelSize: Theme.fsTiny
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Button {
                            objectName: "probeLoadDemoRFButton"
                            text: "Load demo RF"
                            Layout.fillWidth: true
                            onClicked: if (root.controller) root.controller.loadDemoRF()
                        }
                        Button {
                            objectName: "probeRunRFButton"
                            text: "Run RF"
                            Layout.fillWidth: true
                            enabled: root.controller ? !root.controller.isBusy : false
                            onClicked: if (root.controller) root.controller.runRF({})
                        }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 160
                    Layout.leftMargin: Theme.pad
                    Layout.rightMargin: Theme.pad
                    color: Theme.sunken
                    border.color: Theme.border

                    Canvas {
                        id: rfCanvas
                        objectName: "probeRfCanvas"
                        anchors.fill: parent
                        anchors.margins: 4
                        property var xs: root.controller ? root.controller.rfFreq : []
                        property var ys: root.controller ? root.controller.rfH21 : []
                        onXsChanged: requestPaint()
                        onYsChanged: requestPaint()
                        onPaint: {
                            // log-log |H21| vs f, the standard fT roll-off plot.
                            var ctx = getContext("2d")
                            ctx.reset()
                            var xs = rfCanvas.xs, ys = rfCanvas.ys
                            if (!xs || xs.length < 2) return
                            var lx = xs.map(function (v) { return v > 0 ? Math.log10(v) : NaN })
                            var ly = ys.map(function (v) { return v > 0 ? Math.log10(v) : NaN })
                            var xmin = Math.min.apply(null, lx), xmax = Math.max.apply(null, lx)
                            var ymin = Math.min.apply(null, ly), ymax = Math.max.apply(null, ly)
                            if (xmax <= xmin) xmax = xmin + 1
                            if (ymax <= ymin) ymax = ymin + 1
                            ctx.strokeStyle = Theme.accent
                            ctx.lineWidth = 1.5
                            ctx.beginPath()
                            var started = false
                            for (var i = 0; i < lx.length; i++) {
                                if (isNaN(lx[i]) || isNaN(ly[i])) continue
                                var px = (lx[i] - xmin) / (xmax - xmin) * width
                                var py = height - (ly[i] - ymin) / (ymax - ymin) * height
                                if (!started) { ctx.moveTo(px, py); started = true } else ctx.lineTo(px, py)
                            }
                            ctx.stroke()
                        }
                    }
                    Label {
                        anchors.centerIn: parent
                        visible: !(root.controller && root.controller.rfFreq.length > 0)
                        text: "No RF sweep loaded"
                        color: Theme.textFaint
                        font.pixelSize: Theme.fsSmall
                    }
                }

                Label {
                    text: "EXTRACTED QUANTITIES"
                    color: Theme.textDim; font.pixelSize: 11; font.letterSpacing: 1
                    Layout.leftMargin: Theme.pad
                    Layout.topMargin: Theme.padSm
                }
                ListView {
                    id: rfList
                    objectName: "probeRfExtractionList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.margins: Theme.pad
                    clip: true
                    model: root.controller ? root.controller.rfModel : []
                    delegate: RowLayout {
                        width: rfList.width
                        Label {
                            text: modelData.name
                            color: Theme.text
                            font.pixelSize: Theme.fsSmall
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                        Label {
                            text: modelData.display
                            color: Theme.accent
                            font.pixelSize: Theme.fsSmall
                            font.family: Theme.mono
                        }
                    }
                }
            }
        }
    }

    BusyOverlay {
        anchors.fill: parent
        running: root.controller ? root.controller.isBusy : false
        stageText: "Running probe sweep…"
    }
}
