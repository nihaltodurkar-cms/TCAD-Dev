import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// Uniform panel header: small-caps section label on a hairline, with an
// optional collapse toggle for dockable panels.  Replaces the ad-hoc
// "LABEL" Labels scattered through the panels.
Rectangle {
    id: root
    property string title: ""
    property bool collapsible: false
    property bool collapsed: false
    signal toggled()

    implicitHeight: 26
    color: Theme.panelAlt

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.padLg
        anchors.rightMargin: Theme.padSm
        spacing: Theme.padSm

        Text {
            text: root.title.toUpperCase()
            color: Theme.textDim
            font.pixelSize: Theme.fsSmall
            font.letterSpacing: 1.2
            font.bold: true
            Layout.fillWidth: true
            elide: Text.ElideRight
        }

        ToolButton {
            visible: root.collapsible
            implicitWidth: 22; implicitHeight: 22
            text: root.collapsed ? "▸" : "▾"
            font.pixelSize: Theme.fsSmall
            onClicked: root.toggled()
            ToolTip.visible: hovered
            ToolTip.delay: 400
            ToolTip.text: root.collapsed ? "Expand" : "Collapse"
        }
    }

    // bottom hairline
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: Theme.border
    }
}
