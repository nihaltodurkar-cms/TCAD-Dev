import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

ColumnLayout {
    property var controller

    Label { text: "MESH"; color: Theme.textDim; font.pixelSize: 11; font.letterSpacing: 1 }

    RowLayout {
        Label { text: "Nx"; color: Theme.textDim; Layout.preferredWidth: 40 }
        SpinBox { id: nxBox; from: 2; to: 2000; value: 80 }
        Label { text: "Ny"; color: Theme.textDim; Layout.preferredWidth: 40 }
        SpinBox { id: nyBox; from: 2; to: 2000; value: 40 }
        Button {
            text: "Apply"
            onClicked: if (controller) controller.setMeshNxNy(nxBox.value, nyBox.value)
        }
    }

    RowLayout {
        Label { text: "Grading"; color: Theme.textDim; Layout.preferredWidth: 60 }
        ComboBox {
            model: ["uniform", "graded"]
            onActivated: if (controller) controller.setMeshGrading(currentText)
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
            width: ListView.view ? ListView.view.width : 200
            height: row.implicitHeight
            RowLayout {
                id: row
                anchors.left: parent.left
                anchors.right: parent.right
                Label { text: modelData ? modelData[0] : ""; color: Theme.textDim; Layout.preferredWidth: 140 }
                Label { text: modelData ? modelData[1] : ""; color: Theme.text; Layout.fillWidth: true; wrapMode: Text.WordWrap }
            }
        }
    }
}
