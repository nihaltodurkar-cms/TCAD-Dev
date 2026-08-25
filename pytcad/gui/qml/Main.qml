import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "panels"
import "components"

ApplicationWindow {
    id: window
    width: 1440
    height: 900
    minimumWidth: 1080
    minimumHeight: 680
    visible: true
    title: "PyTCAD" + (appController.isDirty ? " *" : "")
    color: Theme.background
    font.family: Theme.family

    // Set by the close-confirmation dialog's "Save" button: after the save
    // dialog is accepted and the project actually saves, quit instead of
    // just closing the dialog. Cleared on any path that doesn't end in quit.
    property bool pendingQuitAfterSave: false

    // dock collapse state (animated below)
    property bool propsCollapsed: false
    property bool consoleCollapsed: false

    Shortcut { sequence: "Ctrl+Z"; onActivated: if (appController.canUndo) appController.undo() }
    Shortcut { sequence: "Ctrl+Y"; onActivated: if (appController.canRedo) appController.redo() }
    Shortcut { sequence: "Ctrl+S"; onActivated: saveFileDialog.open() }
    Shortcut { sequence: "Ctrl+D"; onActivated: { Theme.toggle(); viewport.syncTheme() } }

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
            MenuItem {
                objectName: "openDeckAction"
                text: "Open Deck..."
                onTriggered: openDeckDialog.open()
            }
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
            title: "&View"
            MenuItem {
                text: Theme.dark ? "Light theme" : "Dark theme"
                onTriggered: { Theme.toggle(); viewport.syncTheme() }
            }
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
            anchors.leftMargin: Theme.padLg
            anchors.rightMargin: Theme.padLg
            spacing: Theme.padSm

            Button {
                display: AbstractButton.IconOnly
                text: "▶"
                ToolTip.visible: hovered
                ToolTip.delay: 500
                ToolTip.text: "Solve the current device"
                enabled: !appController.busy
                onClicked: appController.run()
            }
            Button {
                display: AbstractButton.IconOnly
                text: "■"
                enabled: appController.busy
                ToolTip.visible: hovered
                ToolTip.delay: 500
                ToolTip.text: "Cancel the running solve"
                onClicked: appController.cancel()
            }
            ToolSeparator {}
            Button {
                display: AbstractButton.IconOnly
                text: "↶"
                enabled: appController.canUndo
                ToolTip.visible: hovered
                ToolTip.delay: 500
                ToolTip.text: "Undo (Ctrl+Z)"
                onClicked: appController.undo()
            }
            Button {
                display: AbstractButton.IconOnly
                text: "↷"
                enabled: appController.canRedo
                ToolTip.visible: hovered
                ToolTip.delay: 500
                ToolTip.text: "Redo (Ctrl+Y)"
                onClicked: appController.redo()
            }
            ToolSeparator {}
            ComboBox {
                id: viewModeBox
                objectName: "viewModeSelector"
                implicitContentWidthPolicy: ComboBox.WidestText
                model: ["Structure", "Doping", "Mesh", "Process", "Curves",
                        "Bands", "Recombination", "Convergence", "Results"]
                ToolTip.visible: hovered
                ToolTip.delay: 600
                ToolTip.text: "What the viewport shows"
                onActivated: {
                    var m = {"Structure": "structure", "Doping": "doping",
                            "Mesh": "mesh", "Process": "process",
                            "Curves": "series", "Bands": "bands",
                            "Recombination": "recombination",
                            "Convergence": "convergence",
                            "Results": "doping"}[currentText]
                    viewport.setViewMode(m)
                }
            }
            Item { Layout.fillWidth: true }
            BusyIndicator {
                running: appController.busy
                visible: appController.busy
                implicitWidth: 20
                implicitHeight: 20
            }
            Label {
                text: appController.status
                color: appController.busy ? Theme.running : Theme.textDim
                font.pixelSize: Theme.fsSmall
                elide: Text.ElideRight
                Layout.maximumWidth: 340
            }
            ToolSeparator {}
            ToolButton {
                text: Theme.dark ? "☀" : "🌙"
                ToolTip.visible: hovered
                ToolTip.delay: 500
                ToolTip.text: "Toggle light/dark (Ctrl+D)"
                onClicked: { Theme.toggle(); viewport.syncTheme() }
            }
        }
    }

    SplitView {
        id: mainSplit
        anchors.fill: parent
        orientation: Qt.Vertical

        SplitView {
            id: topSplit
            SplitView.fillHeight: true
            SplitView.minimumHeight: 300
            orientation: Qt.Horizontal

            // ---- LEFT: tabbed workbench dock ---------------------------
            Rectangle {
                objectName: "workbenchDock"
                color: Theme.panel
                border.color: Theme.border
                SplitView.preferredWidth: 310
                SplitView.minimumWidth: 240

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    TabBar {
                        id: workbenchTabs
                        objectName: "workbenchTabs"
                        Layout.fillWidth: true
                        contentHeight: 30

                        Repeater {
                            model: [
                                { "label": "Project",   "icon": "⌂" },
                                { "label": "Structure", "icon": "▤" },
                                { "label": "Mesh",      "icon": "▦" },
                                { "label": "Process",   "icon": "⚗" },
                                { "label": "Sweeps",    "icon": "∿" },
                                { "label": "Physics Lab", "icon": "⚛" },
                                { "label": "Builder",   "icon": "✎" }
                            ]
                            delegate: TabButton {
                                required property var modelData
                                text: modelData.icon + "\u2009" + modelData.label
                                width: Math.max(implicitWidth, 44)
                                font.pixelSize: Theme.fsSmall
                            }
                        }
                    }

                    StackLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        currentIndex: workbenchTabs.currentIndex

                        // Every panel stays instantiated (StackLayout keeps
                        // them alive), so QML bindings and headless tests
                        // reach them exactly as before -- only visibility
                        // changes per tab.
                        ProjectTreePanel {
                            objectName: "projectTreePanel"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            controller: appController
                        }
                        StructurePanel {
                            objectName: "structurePanel"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            controller: appController
                        }
                        MeshPanel {
                            objectName: "meshPanel"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            controller: appController
                        }
                        ProcessPanel {
                            objectName: "processPanel"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            controller: appController
                            onStepSelected: (stepId) => viewport.setProcessStep(stepId)
                        }
                        SweepPanel {
                            objectName: "sweepPanel"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            controller: appController
                        }
                        PhysicsLabPanel {
                            objectName: "physicsLabPanel"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            onPlotConvergenceRequested: viewport.setViewMode("convergence")
                        }
                        DeviceTemplatesPanel {
                            objectName: "deviceTemplatesPanel"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                        }
                    }
                }
            }

            // ---- CENTER: viewport --------------------------------------
            ViewportPanel {
                id: viewport
                objectName: "viewportPanel"
                SplitView.fillWidth: true
                SplitView.minimumWidth: 320
                controller: appController

                BusyOverlay {
                    anchors.fill: parent
                    running: appController.busy
                    stageText: appController.status
                }
            }

            // ---- RIGHT: collapsible properties dock ---------------------
            Rectangle {
                objectName: "propertiesDock"
                color: Theme.panelAlt
                border.color: Theme.border
                SplitView.preferredWidth: window.propsCollapsed ? 26 : 280
                SplitView.minimumWidth: 26
                Behavior on SplitView.preferredWidth {
                    NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
                }

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    ToolButton {
                        objectName: "propertiesCollapseButton"
                        Layout.alignment: Qt.AlignHCenter
                        Layout.topMargin: Theme.padXs
                        text: window.propsCollapsed ? "◀" : "▶"
                        font.pixelSize: Theme.fsSmall
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: window.propsCollapsed ? "Show properties"
                                                            : "Hide properties"
                        onClicked: window.propsCollapsed = !window.propsCollapsed
                    }

                    PropertiesPanel {
                        objectName: "propertiesPanel"
                        visible: !window.propsCollapsed
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        propertiesModel: appController.propertiesModel
                    }
                }
            }
        }

        // ---- BOTTOM: collapsible console --------------------------------
        Rectangle {
            objectName: "consoleDock"
            color: Theme.panel
            border.color: Theme.border
            SplitView.preferredHeight: window.consoleCollapsed ? 26 : 190
            SplitView.minimumHeight: 26
            Behavior on SplitView.preferredHeight {
                NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
            }

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                Rectangle {
                    id: consoleGrip
                    Layout.fillWidth: true
                    implicitHeight: 24
                    color: Theme.panelAlt

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: Theme.padLg
                        anchors.rightMargin: Theme.padSm
                        spacing: Theme.padSm

                        Text {
                            text: "SIMULATION CONSOLE"
                            color: Theme.textDim
                            font.pixelSize: Theme.fsSmall
                            font.letterSpacing: 1.2
                            font.bold: true
                            Layout.fillWidth: true
                        }
                        Rectangle {
                            width: 8; height: 8; radius: 4
                            visible: appController.busy
                            color: Theme.running
                        }
                        ToolButton {
                            objectName: "consoleCollapseButton"
                            implicitWidth: 22; implicitHeight: 22
                            text: window.consoleCollapsed ? "▲" : "▼"
                            font.pixelSize: Theme.fsSmall
                            ToolTip.visible: hovered
                            ToolTip.delay: 500
                            ToolTip.text: window.consoleCollapsed ? "Expand console"
                                                                  : "Collapse console"
                            onClicked: window.consoleCollapsed = !window.consoleCollapsed
                        }
                    }
                }

                ConsolePanel {
                    objectName: "consolePanel"
                    visible: !window.consoleCollapsed
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    consoleModel: appController.consoleModel
                    statusText: appController.status
                    busy: appController.busy
                }
            }
        }
    }

    footer: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Theme.padLg
            anchors.rightMargin: Theme.padLg
            spacing: Theme.padLg
            Label {
                objectName: "statusBarLabel"
                text: appController.status
                color: Theme.textDim
                font.pixelSize: Theme.fsSmall
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
            Label {
                text: appController.hasResult ? "● results loaded" : "○ no results"
                color: appController.hasResult ? Theme.ok : Theme.textFaint
                font.pixelSize: Theme.fsSmall
            }
            Label {
                text: Theme.dark ? "dark" : "light"
                color: Theme.textFaint
                font.pixelSize: Theme.fsTiny
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
            text: "PyTCAD desktop GUI v0.5\n\n" +
                  "A Semiconductor Workbench around the PyTCAD engines.\n" +
                  "Every number shown is computed by the real pipeline."
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
    FileDialog {
        id: openDeckDialog
        objectName: "openDeckDialog"
        title: "Open Deck"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Deck files (*.deck *.txt)", "All files (*)"]
        onAccepted: {
            var xhr = new XMLHttpRequest()
            xhr.open("GET", selectedFile.toString())
            xhr.onreadystatechange = function () {
                if (xhr.readyState === XMLHttpRequest.DONE)
                    appController.runDeck(xhr.responseText)
            }
            xhr.send()
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
