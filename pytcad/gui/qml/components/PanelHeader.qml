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
            id: collapseButton
            visible: root.collapsible
            implicitWidth: 22; implicitHeight: 22
            text: root.collapsed ? "▸" : "▾"
            font.pixelSize: Theme.fsSmall
            onClicked: root.toggled()
            ToolTip.visible: hovered
            ToolTip.delay: 400
            ToolTip.text: root.collapsed ? "Expand" : "Collapse"

            background: Rectangle {
                radius: Theme.radiusSm
                color: collapseButton.pressed ? Theme.pressOverlay
                       : collapseButton.hovered ? Theme.hoverOverlay : "transparent"
                Behavior on color { ColorAnimation { duration: Theme.animFast } }
            }
        }
    }

    // bottom hairline, with a thin accent underline that grows in when
    // this panel's contents are expanded -- a small cue that ties the
    // header visually to what's below it.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: Theme.border
    }
    Rectangle {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        height: 2
        width: root.collapsed ? 0 : 28
        color: Theme.accent
        opacity: 0.7
        Behavior on width { NumberAnimation { duration: Theme.animMed; easing.type: Easing.OutCubic } }
    }
}
