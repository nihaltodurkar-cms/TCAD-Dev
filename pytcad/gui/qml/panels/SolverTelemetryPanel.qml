import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."
import "../components"

// Solver Telemetry: live Newton-convergence readout for the solve
// AppController's real JobRunner (self._runner) is driving -- NOT a
// second, independent solver connection. iterationHistory/
// residualHistory come from job_runner.py's stdout-scraped
// iterationChanged/residualChanged signals (cosmetic, best-effort text
// scraping of NewtonOptions(verbose=True) output -- see job_runner.py's
// own comment), so this panel is diagnostic, never load-bearing for
// results. "Load demo" exercises the plot with synthetic data when no
// solve has run yet, same as ProbeStationPanel's demo mode.
Rectangle {
    id: root
    color: Theme.panel
    border.color: Theme.border
    property var controller: appController ? appController.solverTelemetry : null

    readonly property color stateColor: {
        if (!root.controller) return Theme.textFaint
        switch (root.controller.state) {
            case "running":   return Theme.running
            case "converged": return Theme.ok
            case "failed":    return Theme.error
            default:          return Theme.textFaint
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PanelHeader { title: "Solver Telemetry"; Layout.fillWidth: true }

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Theme.pad
            spacing: Theme.padSm

            Rectangle {
                width: 10; height: 10; radius: 5
                color: root.stateColor
            }
            Label {
                objectName: "telemetryStateLabel"
                text: root.controller ? (root.controller.stage.length
                      ? root.controller.stage : root.controller.state) : "idle"
                color: root.stateColor
                font.pixelSize: Theme.fsSmall
                Layout.fillWidth: true
                elide: Text.ElideRight
            }
            Button {
                objectName: "telemetryLoadDemoButton"
                text: "Load demo"
                onClicked: if (root.controller) root.controller.loadDemo()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: Theme.pad
            Layout.rightMargin: Theme.pad
            Layout.bottomMargin: Theme.padSm
            spacing: Theme.pad * 2

            ColumnLayout {
                spacing: 2
                Label { text: "ITERATION"; color: Theme.textDim; font.pixelSize: 10; font.letterSpacing: 1 }
                Label {
                    objectName: "telemetryIterationLabel"
                    text: root.controller ? root.controller.currentIteration : 0
                    color: Theme.text
                    font.pixelSize: Theme.fsTitle
                    font.family: Theme.mono
                }
            }
            ColumnLayout {
                spacing: 2
                Label { text: "|dpsi| RESIDUAL"; color: Theme.textDim; font.pixelSize: 10; font.letterSpacing: 1 }
                Label {
                    objectName: "telemetryResidualLabel"
                    text: root.controller ? root.controller.currentResidualDisplay : "--"
                    color: Theme.accent
                    font.pixelSize: Theme.fsTitle
                    font.family: Theme.mono
                }
            }
        }

        // -- log-scale residual-vs-iteration plot --------------------------
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: Theme.pad
            color: Theme.sunken
            border.color: Theme.border

            Canvas {
                id: residualCanvas
                objectName: "telemetryResidualCanvas"
                anchors.fill: parent
                anchors.margins: 4
                property var xs: root.controller ? root.controller.iterationHistory : []
                property var ys: root.controller ? root.controller.residualHistory : []
                onXsChanged: requestPaint()
                onYsChanged: requestPaint()
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    var xs = residualCanvas.xs, ys = residualCanvas.ys
                    if (!xs || xs.length < 2) return
                    // log10 on the residual axis -- Newton residuals decay
                    // geometrically, a linear axis would flatten everything
                    // past the first couple of iterations.
                    var ly = ys.map(function (v) { return v > 0 ? Math.log10(v) : NaN })
                    var xmin = Math.min.apply(null, xs), xmax = Math.max.apply(null, xs)
                    var ymin = Math.min.apply(null, ly), ymax = Math.max.apply(null, ly)
                    if (xmax <= xmin) xmax = xmin + 1
                    if (ymax <= ymin) ymax = ymin + 1
                    ctx.strokeStyle = Theme.accent
                    ctx.lineWidth = 1.5
                    ctx.beginPath()
                    var started = false
                    for (var i = 0; i < xs.length; i++) {
                        if (isNaN(ly[i])) continue
                        var px = (xs[i] - xmin) / (xmax - xmin) * width
                        var py = height - (ly[i] - ymin) / (ymax - ymin) * height
                        if (!started) { ctx.moveTo(px, py); started = true } else ctx.lineTo(px, py)
                    }
                    ctx.stroke()
                }
            }
            Label {
                anchors.centerIn: parent
                visible: !(root.controller && root.controller.iterationHistory.length > 0)
                text: "No convergence data yet -- run a solve, or Load demo"
                color: Theme.textFaint
                font.pixelSize: Theme.fsSmall
            }
            Label {
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.margins: 4
                visible: root.controller && root.controller.iterationHistory.length > 0
                text: "iteration →"
                color: Theme.textFaint
                font.pixelSize: Theme.fsTiny
            }
            Label {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: 4
                visible: root.controller && root.controller.iterationHistory.length > 0
                text: "log₁₀ |dpsi|"
                color: Theme.textFaint
                font.pixelSize: Theme.fsTiny
            }
        }
    }
}
