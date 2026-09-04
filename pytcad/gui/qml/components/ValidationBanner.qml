import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// GUI-IMPROVEMENT-PLAN Phase 4: Visual banner that shows runtime
// validation problems detected by GuiStateValidator.  Keeps the user
// informed about state inconsistencies without blocking their workflow.

Rectangle {
    id: root
    property var validator: stateValidator
    height: validator && validator.problemCount > 0 ? 32 : 0
    // v2.1 correction (DESIGN.md section 3.3): validation problems are
    // a warning, not "running" -- was Theme.running (amber), which
    // collided a caution color with the busy/solver-active signal.
    color: Theme.warning
    opacity: 0.9
    border.color: Qt.darker(Theme.warning, 1.2)

    visible: height > 0

    Behavior on height { NumberAnimation { duration: Theme.animMed; easing.type: Easing.OutCubic } }
    Behavior on opacity { NumberAnimation { duration: Theme.animMed; easing.type: Easing.OutCubic } }

    RowLayout {
        anchors.fill: parent
        anchors.margins: Theme.padSm
        spacing: Theme.padSm

        Label {
            text: "⚠"
            color: "#ffffff"
            font.pixelSize: Theme.fsBody
            Layout.preferredWidth: 20
            Layout.alignment: Qt.AlignVCenter

            SequentialAnimation on opacity {
                running: root.visible
                loops: Animation.Infinite
                NumberAnimation { to: 0.5; duration: 700; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine }
            }
        }

        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            model: validator ? validator.problems : []
            clip: true
            delegate: Label {
                text: modelData.message
                color: "#ffffff"
                font.pixelSize: Theme.fsSmall
                elide: Text.ElideRight
                wrapMode: Text.NoWrap
            }
            currentIndex: -1  // Don't highlight any item
        }

        Button {
            text: "✕"
            flat: true
            font.pixelSize: Theme.fsBody
            Layout.preferredWidth: 24
            Layout.preferredHeight: 24
            ToolTip.visible: hovered
            ToolTip.text: "Clear all warnings"
            onClicked: validator.clearProblems()
        }
    }
}
