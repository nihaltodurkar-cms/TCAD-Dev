import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ColumnLayout {
    property var controller

    Label { text: "MESH"; color: Theme.textDim; font.pixelSize: 11; font.letterSpacing: 1 }

    component MeshSpinBox: SpinBox {
        id: control
        from: 2; to: 2000
        background: Rectangle {
            implicitWidth: 70
            implicitHeight: 24
            radius: Theme.radiusSm
            color: control.hovered ? Qt.tint(Theme.sunken, Theme.hoverOverlay) : Theme.sunken
            border.width: control.activeFocus ? 2 : 1
            border.color: control.activeFocus ? Theme.focus
                          : control.hovered ? Theme.borderStrong : Theme.border
            Behavior on color { ColorAnimation { duration: Theme.animFast } }
            Behavior on border.color { ColorAnimation { duration: Theme.animFast } }
        }
    }

    RowLayout {
        Label { text: "Nx"; color: Theme.textDim; Layout.preferredWidth: 40 }
        MeshSpinBox { id: nxBox; objectName: "meshNxBox"; value: 80 }
        Label { text: "Ny"; color: Theme.textDim; Layout.preferredWidth: 40 }
        MeshSpinBox { id: nyBox; objectName: "meshNyBox"; value: 40 }
        Button {
            id: meshApplyButton
            objectName: "meshApplyButton"
            text: "Apply"
            onClicked: if (controller) controller.setMeshNxNy(nxBox.value, nyBox.value)
            background: Rectangle {
                radius: Theme.radiusSm
                color: meshApplyButton.pressed ? Qt.darker(Theme.panelRaised, 1.15)
                       : meshApplyButton.hovered ? Qt.tint(Theme.panelRaised, Theme.hoverOverlay)
                       : Theme.panelRaised
                border.width: 1
                border.color: Theme.border
                Behavior on color { ColorAnimation { duration: Theme.animFast } }
            }
        }
    }

    RowLayout {
        Label { text: "Grading"; color: Theme.textDim; Layout.preferredWidth: 60 }
        ComboBox {
            id: gradingBox
            objectName: "meshGradingBox"
            model: ["uniform", "graded"]
            onActivated: if (controller) controller.setMeshGrading(currentText)
            background: Rectangle {
                implicitWidth: 100
                implicitHeight: 24
                radius: Theme.radiusSm
                color: gradingBox.hovered ? Qt.tint(Theme.sunken, Theme.hoverOverlay) : Theme.sunken
                border.width: gradingBox.activeFocus ? 2 : 1
                border.color: gradingBox.activeFocus ? Theme.focus
                              : gradingBox.hovered ? Theme.borderStrong : Theme.border
                Behavior on color { ColorAnimation { duration: Theme.animFast } }
                Behavior on border.color { ColorAnimation { duration: Theme.animFast } }
            }
        }
    }

    ListView {
        Layout.fillWidth: true
        Layout.preferredHeight: 220
        clip: true
        model: controller ? controller.meshInfo : []
        // A Layout-derived item (RowLayout) must never be a delegate's
        // ROOT sized from its own parent's width: the delegate's width
        // feeds the ListView contentItem's implicit width, which the
        // parent-width binding reads right back -- a binding loop that
        // manifests as runaway delegate churn once the real event loop
        // runs (invisible in tests that never call app.exec()). The
        // fix is the standard one: a plain Item root sized via the
        // ListView.view attached property, with the RowLayout anchored
        // inside as a child, not as the delegate root itself.
        delegate: Item {
            id: meshInfoRow
            required property var modelData
            // route through functions so no label binding ever touches
            // modelData before the delegate context exists (the source of
            // the "Unable to assign [undefined] to QString" spam)
            function rowLabel() {
                return (modelData !== undefined && modelData !== null)
                        ? String(modelData[0]) : ""
            }
            function rowValue() {
                return (modelData !== undefined && modelData !== null)
                        ? String(modelData[1]) : ""
            }
            width: ListView.view ? ListView.view.width : 200
            height: row.implicitHeight
            RowLayout {
                id: row
                anchors.left: parent.left
                anchors.right: parent.right
                Label { text: meshInfoRow.rowLabel(); color: Theme.textDim; Layout.preferredWidth: 140 }
                Label { text: meshInfoRow.rowValue(); color: Theme.text; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            }
        }
    }
}
