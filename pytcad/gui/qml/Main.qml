import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "panels"
import "components"

ApplicationWindow {
    id: window
    width: 1280
    height: 820
    visible: true
    title: "PyTCAD" + (appController.isDirty ? " *" : "")
    color: Theme.background

    // Set by the close-confirmation dialog's "Save" button: after the save
    // dialog is accepted and the project actually saves, quit instead of
    // just closing the dialog. Cleared on any path that doesn't end in quit.
    property bool pendingQuitAfterSave: false

    Shortcut { sequence: "Ctrl+Z"; onActivated: if (appController.canUndo) appController.undo() }
    Shortcut { sequence: "Ctrl+Y"; onActivated: if (appController.canRedo) appController.redo() }
    Shortcut { sequence: "Ctrl+S"; onActivated: saveFileDialog.open() }

    menuBar: MenuBar {
        Menu {
            title: "&File"
            MenuItem { text: "Load 2D MOSFET example"
                       onTriggered: appController.loadExample("mosfet_2d") }
            MenuItem { text: "Load 2D MOSFET (Structure)"
                       onTriggered: appController.loadStructureExample("mosfet_2d_structure") }
            MenuSeparator {}
            MenuItem { text: "Save Project As..."; onTriggered: saveFileDialog.open() }
            MenuItem { text: "Open Project..."; onTriggered: openFileDialog.open() }
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
                model: ["Structure", "Doping", "Mesh", "Process", "Curves",
                        "Convergence", "Results"]
                onActivated: {
                    var m = {"Structure": "structure", "Doping": "doping",
                            "Mesh": "mesh", "Process": "process",
                            "Curves": "series",
                            "Convergence": "convergence",
                            "Results": "doping"}[currentText]
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

            ProcessPanel {
                objectName: "processPanel"
                SplitView.preferredWidth: 260
                SplitView.minimumWidth: 200
                controller: appController
                onStepSelected: (stepId) => viewport.setProcessStep(stepId)
            }

            SweepPanel {
                objectName: "sweepPanel"
                SplitView.preferredWidth: 200
                SplitView.minimumWidth: 170
                controller: appController
            }

            PhysicsLabPanel {
                objectName: "physicsLabPanel"
                SplitView.preferredWidth: 230
                SplitView.minimumWidth: 190
                onPlotConvergenceRequested: viewport.setViewMode("convergence")
            }

            DeviceTemplatesPanel {
                objectName: "deviceTemplatesPanel"
                SplitView.preferredWidth: 210
                SplitView.minimumWidth: 180
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

    // Native OS file pickers (QtQuick.Dialogs FileDialog -- the platform's
    // real dialog where one is available, e.g. via the Wayland/GTK portal,
    // falling back to a Qt Quick implementation otherwise). Replaces the
    // earlier typed-path Dialog. The project "name" saved into the file is
    // derived from the chosen filename, since a native picker has no room
    // for a separate name field.
    FileDialog {
        id: saveFileDialog
        objectName: "saveFileDialog"
        title: "Save Project As"
        fileMode: FileDialog.SaveFile
        nameFilters: ["PyTCAD project files (*.json)", "All files (*)"]
        defaultSuffix: "json"
        onAccepted: {
            // Python-side saveProject() converts the file:// URL to a local
            // path (via QUrl.toLocalFile()) -- correct on every platform,
            // unlike stripping "file://" with a regex here would be.
            var path = selectedFile.toString()
            var baseName = path.substring(path.lastIndexOf("/") + 1).replace(/\.json$/i, "")
            appController.saveProject(path, baseName || "Project")
            if (window.pendingQuitAfterSave) {
                window.pendingQuitAfterSave = false
                Qt.quit()
            }
        }
        onRejected: window.pendingQuitAfterSave = false
    }

    FileDialog {
        id: openFileDialog
        objectName: "openFileDialog"
        title: "Open Project"
        fileMode: FileDialog.OpenFile
        nameFilters: ["PyTCAD project files (*.json)", "All files (*)"]
        onAccepted: appController.loadProject(selectedFile.toString())
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
        footer: DialogButtonBox {
            Button {
                text: "Save"
                onClicked: {
                    closeConfirmDialog.close()
                    window.pendingQuitAfterSave = true
                    saveFileDialog.open()
                }
            }
            Button { text: "Don't Save"; onClicked: { closeConfirmDialog.close(); Qt.quit() } }
            Button { text: "Cancel"; onClicked: closeConfirmDialog.close() }
        }
        Label { text: "This project has unsaved changes. Close anyway?" }
    }
}
