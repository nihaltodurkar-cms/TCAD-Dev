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
    color: Qt.rgba(0, 0, 0, dark ? 0.45 : 0.25)

    visible: opacity > 0
    opacity: running ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

    Column {
        anchors.centerIn: parent
        spacing: Theme.padLg

        BusyIndicator {
            anchors.horizontalCenter: parent.horizontalCenter
            running: root.running
            implicitWidth: 42
            implicitHeight: 42
        }
        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.stageText || "Solving…"
            color: "#ffffff"
            font.pixelSize: Theme.fsBody
            font.bold: true
            style: Text.Outline
            styleColor: Qt.rgba(0, 0, 0, 0.6)
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
