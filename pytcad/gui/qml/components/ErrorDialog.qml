import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// Concise reason up front, full traceback behind a disclosure -- a
// numerical failure must never be hidden, but it must not be the first
// thing shouted at the user either.
Dialog {
    id: root
    modal: true
    title: "Simulation failed"
    standardButtons: Dialog.Ok
    anchors.centerIn: parent
    width: Math.min(720, parent ? parent.width - 80 : 720)

    property string summary: ""
    property string details: ""

    onOpened: detailArea.visible = false

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.pad

        Label {
            text: "Reason:"
            color: Theme.textDim
        }
        Label {
            Layout.fillWidth: true
            text: root.summary
            color: Theme.text
            wrapMode: Text.WordWrap
        }
        Button {
            text: detailArea.visible ? "Hide details" : "Show details"
            onClicked: detailArea.visible = !detailArea.visible
        }
        ScrollView {
            id: detailArea
            visible: false
            Layout.fillWidth: true
            Layout.preferredHeight: 240
            TextArea {
                readOnly: true
                text: root.details
                font.family: Theme.mono
                font.pixelSize: 11
                wrapMode: TextArea.NoWrap
            }
        }
    }
}
