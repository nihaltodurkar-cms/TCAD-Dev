import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ColumnLayout {
    property var controller
    property string selectedRegionId: ""
    signal regionSelected(string regionId)

    RowLayout {
        Label { text: "Regions"; color: Theme.text; font.bold: true; Layout.fillWidth: true }
        Button {
            text: "+"
            onClicked: controller.addRegion("New Region", 0.0, 1e-5, 0.0, 1e-5, 1e17)
        }
    }

    Label {
        text: "Compositing order: later regions paint over earlier ones where they overlap."
        color: Theme.textDim
        font.pixelSize: 10
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }

    ListView {
        id: list
        Layout.fillWidth: true
        Layout.preferredHeight: 140
        clip: true
        model: controller ? controller.regionListModel : null
        delegate: ItemDelegate {
            width: ListView.view ? ListView.view.width : 0
            height: 32
            highlighted: model.regionId === selectedRegionId
            onClicked: { selectedRegionId = model.regionId; regionSelected(model.regionId) }
            // A single left-anchored Row, positioned purely by its own
            // children's widths -- deliberately NOT anchored to
            // parent.right/parent.width anywhere. Found via a real
            // rendered screenshot plus pixel-level measurement of the
            // actual panel boundary: in this Qt/PySide/Wayland build,
            // ListView.view.width (and the plain `list.width` reference)
            // reports a value substantially larger than the panel's true
            // visible/clipped bounds -- confirmed with debug-colored
            // Rectangles that never appeared anywhere on screen despite
            // reporting in-bounds x/width. Anchoring to the right edge of
            // a container whose reported width is wrong pushes content
            // outside the real clip region. A single Row flowing
            // left-to-right from a fixed margin never depends on that
            // unreliable width at all -- also see the matching fix in
            // MeshEditor.qml's delegate for the same root class of issue.
            contentItem: Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 6
                spacing: 4
                Text {
                    text: model.priority
                    color: Theme.textDim
                    font.pixelSize: 10
                    width: 14
                    height: 20
                    verticalAlignment: Text.AlignVCenter
                    horizontalAlignment: Text.AlignRight
                }
                Text {
                    text: model.name
                    color: Theme.text
                    font.pixelSize: 12
                    width: 60
                    height: 20
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                Text {
                    text: model.doping.toExponential(1)
                    color: Theme.textDim
                    font.pixelSize: 9
                    width: 42
                    height: 20
                    verticalAlignment: Text.AlignVCenter
                    elide: Text.ElideRight
                }
                Button {
                    text: "▲"; flat: true
                    enabled: index > 0
                    width: 22; height: 24
                    leftPadding: 2; rightPadding: 2
                    ToolTip.text: "Move up (higher priority)"; ToolTip.visible: hovered
                    onClicked: controller.moveRegion(model.regionId, -1)
                }
                Button {
                    text: "▼"; flat: true
                    enabled: index < list.count - 1
                    width: 22; height: 24
                    leftPadding: 2; rightPadding: 2
                    ToolTip.text: "Move down (lower priority)"; ToolTip.visible: hovered
                    onClicked: controller.moveRegion(model.regionId, +1)
                }
                Button {
                    text: "x"; flat: true
                    width: 20; height: 24
                    leftPadding: 2; rightPadding: 2
                    onClicked: controller.removeRegion(model.regionId)
                }
            }
            background: Rectangle { color: highlighted ? Theme.panelAlt : "transparent" }
        }
    }
}
