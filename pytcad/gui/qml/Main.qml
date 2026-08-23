import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "panels"
import "components"

ApplicationWindow {
    id: window
    width: 1280
    height: 820
    visible: true
    title: "PyTCAD"
    color: Theme.background

    menuBar: MenuBar {
        Menu {
            title: "&File"
            MenuItem { text: "Load 2D MOSFET example"
                       onTriggered: appController.loadExample("mosfet_2d") }
            MenuSeparator {}
            MenuItem { text: "Quit"; onTriggered: Qt.quit() }
        }
        Menu {
            title: "&Run"
            MenuItem { text: "Run simulation"
                       enabled: !appController.busy
                       onTriggered: appController.run() }
            MenuItem { text: "Cancel"
                       enabled: appController.busy
                       onTriggered: appController.cancel() }
        }
        Menu {
            title: "&Help"
            MenuItem { text: "About"; onTriggered: aboutDialog.open() }
        }
    }

    header: ToolBar {
        objectName: "mainToolBar"
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Theme.pad
            anchors.rightMargin: Theme.pad
            spacing: Theme.pad

            Button {
                text: "Load example"
                onClicked: appController.loadExample("mosfet_2d")
            }
            ToolSeparator {}
            Button {
                text: "Run"
                enabled: !appController.busy
                onClicked: appController.run()
            }
            Button {
                text: "Stop"
                enabled: appController.busy
                onClicked: appController.cancel()
            }
            BusyIndicator {
                running: appController.busy
                visible: appController.busy
                implicitWidth: 22
                implicitHeight: 22
            }
            Item { Layout.fillWidth: true }
            Label {
                text: appController.status
                color: Theme.textDim
            }
        }
    }

    SplitView {
        anchors.fill: parent
        orientation: Qt.Vertical

        SplitView {
            SplitView.fillHeight: true
            SplitView.minimumHeight: 300
            orientation: Qt.Horizontal

            ProjectTreePanel {
                objectName: "projectTreePanel"
                SplitView.preferredWidth: 210
                SplitView.minimumWidth: 150
                controller: appController
            }

            ViewportPanel {
                objectName: "viewportPanel"
                SplitView.fillWidth: true
                SplitView.minimumWidth: 320
                controller: appController
            }

            PropertiesPanel {
                objectName: "propertiesPanel"
                SplitView.preferredWidth: 280
                SplitView.minimumWidth: 180
                propertiesModel: appController.propertiesModel
            }
        }

        ConsolePanel {
            objectName: "consolePanel"
            SplitView.preferredHeight: 190
            SplitView.minimumHeight: 90
            consoleModel: appController.consoleModel
            statusText: appController.status
            busy: appController.busy
        }
    }

    footer: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Theme.pad
            anchors.rightMargin: Theme.pad
            Label {
                objectName: "statusBarLabel"
                text: appController.status
                color: Theme.textDim
            }
            Item { Layout.fillWidth: true }
            Label {
                text: appController.hasResult ? "results loaded" : "no results"
                color: appController.hasResult ? Theme.ok : Theme.textDim
            }
        }
    }

    ErrorDialog {
        id: errorDialog
    }

    Dialog {
        id: aboutDialog
        modal: true
        title: "About PyTCAD"
        standardButtons: Dialog.Ok
        anchors.centerIn: parent
        Label {
            text: "PyTCAD desktop GUI v0.1\n\n" +
                  "A frontend around the PyTCAD solver.\n" +
                  "This is an early version, not a complete TCAD workbench."
        }
    }

    Connections {
        target: appController
        function onErrorRaised(summary, details) {
            errorDialog.summary = summary
            errorDialog.details = details
            errorDialog.open()
        }
    }
}
