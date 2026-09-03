import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."
import "../components"

// Band Diagram Viewer: Ec/Ev/EFn/EFp vs. position, read from the
// current result's band__* arrays (stamped by solver_runner.py's
// extract_result() from the SOLVED Device1D's own band_diagram()
// method -- see band_diagram_controller.py's module docstring for why
// this must be computed in the solver subprocess rather than here).
// 1D-only: Device2D/Device3D have no band_diagram() method yet, so a
// 2D/3D result shows the honest "not available" message below instead
// of a blank or crashing plot.
Rectangle {
    id: root
    color: Theme.panel
    border.color: Theme.border
    property var controller: appController ? appController.bandDiagram : null

    property bool showEc: true
    property bool showEv: true
    property bool showEFn: true
    property bool showEFp: true

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        PanelHeader { title: "Band Diagram"; Layout.fillWidth: true }

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Theme.pad
            spacing: Theme.pad

            CheckBox {
                objectName: "bandShowEcCheck"
                text: "Ec"
                checked: root.showEc
                onToggled: root.showEc = checked
            }
            CheckBox {
                objectName: "bandShowEvCheck"
                text: "Ev"
                checked: root.showEv
                onToggled: root.showEv = checked
            }
            CheckBox {
                objectName: "bandShowEFnCheck"
                text: "EFn"
                checked: root.showEFn
                onToggled: root.showEFn = checked
            }
            CheckBox {
                objectName: "bandShowEFpCheck"
                text: "EFp"
                checked: root.showEFp
                onToggled: root.showEFp = checked
            }
            Item { Layout.fillWidth: true }
        }

        // -- plot area --------------------------------------------------
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.leftMargin: Theme.pad
            Layout.rightMargin: Theme.pad
            color: Theme.sunken
            border.color: Theme.border

            Canvas {
                id: bandCanvas
                objectName: "bandDiagramCanvas"
                anchors.fill: parent
                anchors.margins: 4
                property var xs: root.controller ? root.controller.x : []
                property var ec: root.controller ? root.controller.ec : []
                property var ev: root.controller ? root.controller.ev : []
                property var efn: root.controller ? root.controller.efn : []
                property var efp: root.controller ? root.controller.efp : []
                property bool showEc: root.showEc
                property bool showEv: root.showEv
                property bool showEFn: root.showEFn
                property bool showEFp: root.showEFp
                onXsChanged: requestPaint()
                onEcChanged: requestPaint()
                onEvChanged: requestPaint()
                onEfnChanged: requestPaint()
                onEfpChanged: requestPaint()
                onShowEcChanged: requestPaint()
                onShowEvChanged: requestPaint()
                onShowEFnChanged: requestPaint()
                onShowEFpChanged: requestPaint()

                function drawCurve(ctx, xs, ys, xmin, xmax, ymin, ymax, color) {
                    ctx.strokeStyle = color
                    ctx.lineWidth = 1.5
                    ctx.beginPath()
                    for (var i = 0; i < xs.length; i++) {
                        var px = (xs[i] - xmin) / (xmax - xmin) * width
                        var py = height - (ys[i] - ymin) / (ymax - ymin) * height
                        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py)
                    }
                    ctx.stroke()
                }

                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    var xs = bandCanvas.xs
                    if (!xs || xs.length < 2) return
                    var xmin = Math.min.apply(null, xs), xmax = Math.max.apply(null, xs)
                    if (xmax <= xmin) xmax = xmin + 1

                    var curves = []
                    if (bandCanvas.showEc) curves.push(bandCanvas.ec)
                    if (bandCanvas.showEv) curves.push(bandCanvas.ev)
                    if (bandCanvas.showEFn) curves.push(bandCanvas.efn)
                    if (bandCanvas.showEFp) curves.push(bandCanvas.efp)
                    var ymin = Infinity, ymax = -Infinity
                    for (var c = 0; c < curves.length; c++) {
                        for (var i = 0; i < curves[c].length; i++) {
                            var v = curves[c][i]
                            if (v < ymin) ymin = v
                            if (v > ymax) ymax = v
                        }
                    }
                    if (!isFinite(ymin) || !isFinite(ymax)) return
                    if (ymax <= ymin) ymax = ymin + 1
                    var margin = 0.05 * (ymax - ymin)
                    ymin -= margin; ymax += margin

                    if (bandCanvas.showEc)
                        drawCurve(ctx, xs, bandCanvas.ec, xmin, xmax, ymin, ymax, Theme.accent)
                    if (bandCanvas.showEv)
                        drawCurve(ctx, xs, bandCanvas.ev, xmin, xmax, ymin, ymax, Theme.error)
                    if (bandCanvas.showEFn)
                        drawCurve(ctx, xs, bandCanvas.efn, xmin, xmax, ymin, ymax, Theme.ok)
                    if (bandCanvas.showEFp)
                        drawCurve(ctx, xs, bandCanvas.efp, xmin, xmax, ymin, ymax, Theme.running)
                }
            }

            Label {
                anchors.left: parent.left
                anchors.bottom: parent.bottom
                anchors.margins: 4
                visible: root.controller && root.controller.available
                text: "position [cm] →"
                color: Theme.textFaint
                font.pixelSize: Theme.fsTiny
            }
            Label {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.margins: 4
                visible: root.controller && root.controller.available
                text: "energy [eV]"
                color: Theme.textFaint
                font.pixelSize: Theme.fsTiny
            }

            Label {
                objectName: "bandUnavailableLabel"
                anchors.centerIn: parent
                anchors.margins: Theme.pad
                width: parent.width - 2 * Theme.pad
                visible: !(root.controller && root.controller.available)
                text: root.controller ? root.controller.unavailableReason
                      : "No result loaded yet."
                color: Theme.textFaint
                font.pixelSize: Theme.fsSmall
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }
        }

        // -- legend -------------------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Theme.pad
            spacing: Theme.pad
            visible: root.controller && root.controller.available

            Repeater {
                model: [
                    { "label": "Ec", "color": Theme.accent },
                    { "label": "Ev", "color": Theme.error },
                    { "label": "EFn", "color": Theme.ok },
                    { "label": "EFp", "color": Theme.running }
                ]
                delegate: RowLayout {
                    required property var modelData
                    spacing: 4
                    Rectangle { width: 10; height: 2; color: modelData.color }
                    Label { text: modelData.label; color: Theme.textDim; font.pixelSize: Theme.fsTiny }
                }
            }
        }
    }
}
