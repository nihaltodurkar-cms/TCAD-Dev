import QtQuick
import QtQuick.Controls
import ".."

// Translucent overlay shown over the viewport while a solve is running:
// communicates "working" without hiding the previous result entirely,
// with the current solver stage as a caption.
Rectangle {
    id: root
    property bool running: false
    property string stageText: ""
    readonly property bool dark: Theme.dark
    color: "transparent"
    gradient: Gradient {
        GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, dark ? 0.55 : 0.32) }
        GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, dark ? 0.35 : 0.18) }
    }

    visible: opacity > 0
    opacity: running ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: Theme.animSlow; easing.type: Easing.OutCubic } }

    Column {
        anchors.centerIn: parent
        spacing: Theme.padLg
        scale: root.running ? 1.0 : 0.9
        Behavior on scale { NumberAnimation { duration: Theme.animSlow; easing.type: Easing.OutBack } }

        // Custom ring spinner: a full track plus a bright accent arc that
        // sweeps around it, matched to the accent colour instead of the
        // generic platform BusyIndicator.
        Item {
            id: spinner
            anchors.horizontalCenter: parent.horizontalCenter
            width: 46; height: 46

            Rectangle {
                anchors.fill: parent
                radius: width / 2
                color: "transparent"
                border.width: 3
                border.color: Qt.rgba(1, 1, 1, 0.18)
            }
            Canvas {
                id: arc
                anchors.fill: parent
                rotation: 0
                onPaint: {
                    var ctx = getContext("2d")
                    ctx.reset()
                    var cx = width / 2, cy = height / 2, r = width / 2 - 1.5
                    ctx.lineWidth = 3
                    ctx.lineCap = "round"
                    ctx.strokeStyle = Theme.accent
                    ctx.beginPath()
                    ctx.arc(cx, cy, r, 0, Math.PI * 0.75)
                    ctx.stroke()
                }
                RotationAnimation on rotation {
                    running: root.running
                    loops: Animation.Infinite
                    from: 0; to: 360
                    duration: 900
                }
            }
        }

        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.stageText || "Solving…"
            color: "#ffffff"
            font.pixelSize: Theme.fsBody
            font.bold: true
            style: Text.Outline
            styleColor: Qt.rgba(0, 0, 0, 0.6)

            Behavior on text { PropertyAnimation { duration: 0 } }
        }
        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Newton iterations stream into the console below"
            color: Qt.rgba(1, 1, 1, 0.75)
            font.pixelSize: Theme.fsSmall
            style: Text.Outline
            styleColor: Qt.rgba(0, 0, 0, 0.6)
        }
    }

    // swallow clicks while visible so the user can't edit mid-run state
    MouseArea { anchors.fill: parent; enabled: root.running }
}
