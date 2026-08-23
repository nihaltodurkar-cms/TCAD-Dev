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
    title: "PyTCAD" + (appController.isDirty ? " *" : "")
    color: Theme.background

    Shortcut { sequence: "Ctrl+Z"; onActivated: if (appController.canUndo) appController.undo() }
    Shortcut { sequence: "Ctrl+Y"; onActivated: if (appController.canRedo) appController.redo() }
    Shortcut { sequence: "Ctrl+S"; onActivated: projectDialog.openFor("save") }

    menuBar: MenuBar {
        Menu {
            title: "&File"
            MenuItem { text: "Load 2D MOSFET example"
                       onTriggered: appController.loadExample("mosfet_2d") }
            MenuItem { text: "Load 2D MOSFET (Structure)"
                       onTriggered: appController.loadStructureExample("mosfet_2d_structure") }
            MenuSeparator {}
            MenuItem { text: "Save Project..."; onTriggered: projectDialog.openFor("save") }
            MenuItem { text: "Load Project..."; onTriggered: projectDialog.openFor("load") }
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
            ToolSeparator {}
            Button {
                text: "Load structure example"
                onClicked: appController.loadStructureExample("mosfet_2d_structure")
            }
            ComboBox {
                id: viewModeBox
                objectName: "viewModeSelector"
                model: ["Structure", "Doping", "Mesh", "Results"]
                onActivated: {
                    var m = {"Structure": "structure", "Doping": "doping",
                            "Mesh": "mesh", "Results": "doping"}[currentText]
                    viewport.setViewMode(m)
                }
            }
            ToolButton {
                text: "Undo"
                enabled: appController.canUndo
                onClicked: appController.undo()
            }
            ToolButton {
                text: "Redo"
                enabled: appController.canRedo
                onClicked: appController.redo()
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
                id: viewport
                objectName: "viewportPanel"
                SplitView.fillWidth: true
                SplitView.minimumWidth: 320
                controller: appController
            }

            StructurePanel {
                objectName: "structurePanel"
                SplitView.preferredWidth: 260
                SplitView.minimumWidth: 200
                controller: appController
            }

            MeshPanel {
                objectName: "meshPanel"
                SplitView.preferredWidth: 220
                SplitView.minimumWidth: 160
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

    // Path-entry Save/Load, not a native file picker -- a real OS file
    // dialog is explicitly deferred to v0.3 (see gui/README.md's
    // "Planned" section). This is still a genuine, working round trip
    // through the same saveProject()/loadProject() slots the tests
    // exercise; it was previously reachable only from Python, with no
    // UI path to it at all (found while verifying the app on a real
    // display).
    Dialog {
        id: projectDialog
        property string mode: "save"   // "save" | "load"
        modal: true
        title: mode === "save" ? "Save Project" : "Load Project"
        anchors.centerIn: parent
        standardButtons: Dialog.Cancel

        function openFor(m) {
            mode = m
            pathField.text = pathField.text || (Qt.platform.os === "windows" ? "C:/tmp/project.json" : "/tmp/project.json")
            open()
        }

        ColumnLayout {
            width: 320
            RowLayout {
                Label { text: "Path"; Layout.preferredWidth: 60 }
                TextField { id: pathField; Layout.fillWidth: true }
            }
            RowLayout {
                visible: projectDialog.mode === "save"
                Label { text: "Name"; Layout.preferredWidth: 60 }
                TextField { id: nameField; Layout.fillWidth: true; text: "My Project" }
            }
        }

        footer: DialogButtonBox {
            Button {
                text: projectDialog.mode === "save" ? "Save" : "Load"
                onClicked: {
                    if (projectDialog.mode === "save")
                        appController.saveProject(pathField.text, nameField.text)
                    else
                        appController.loadProject(pathField.text)
                    projectDialog.close()
                }
            }
            Button { text: "Cancel"; onClicked: projectDialog.close() }
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

    onClosing: (close) => {
        if (appController.isDirty) {
            close.accepted = false
            closeConfirmDialog.open()
        }
    }

    Dialog {
        id: closeConfirmDialog
        modal: true
        title: "Unsaved changes"
        anchors.centerIn: parent
        standardButtons: Dialog.Cancel
        footer: DialogButtonBox {
            Button { text: "Don't Save"; onClicked: { closeConfirmDialog.close(); Qt.quit() } }
            Button { text: "Cancel"; onClicked: closeConfirmDialog.close() }
        }
        Label { text: "This project has unsaved changes. Close anyway?" }
    }
}
