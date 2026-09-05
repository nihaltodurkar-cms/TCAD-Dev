import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import QtQuick.Effects
import QtQuick.Window
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

    // v2 reskin: launch filling the screen so panels (the Mesh panel
    // was named explicitly) aren't cramped by the fixed 1440x900
    // default -- the width/height/minimum* values above remain as the
    // fallback. Guarded against the offscreen QPA platform: Qt's
    // offscreen platform has no real screen to maximize against, and
    // gui/tests' headless runs (QT_QPA_PLATFORM=offscreen, set in
    // conftest.py) must keep getting the deterministic default size.
    Component.onCompleted: {
        if (Qt.platformName !== "offscreen")
            window.visibility = Window.Maximized
    }

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
            MenuItem { text: "Load 1D diode example"
                       onTriggered: appController.loadExample("diode_1d") }
            MenuItem { text: "Load 2D resistor example"
                       onTriggered: appController.loadExample("resistor_2d") }
            MenuItem { text: "Load 3D resistor example"
                       onTriggered: appController.loadExample("resistor_3d") }
            MenuItem { text: "Load 3D MOSFET example"
                       onTriggered: appController.loadExample("mosfet_3d") }
            MenuItem { text: "Load 3D FinFET (tri-gate)"
                       onTriggered: appController.loadExample("finfet_3d") }
            MenuItem { text: "Load 3D PN junction"
                       onTriggered: appController.loadExample("pn_junction_3d") }
            MenuItem { text: "Load 3D BJT (NPN)"
                       onTriggered: appController.loadExample("bjt_3d") }
            MenuItem { text: "Load 3D MOS capacitor"
                       onTriggered: appController.loadExample("moscap_3d") }
            MenuItem { text: "Load 3D JFET"
                       onTriggered: appController.loadExample("jfet_3d") }
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
                       enabled: !appController.busy && appController.hasDeviceToRun
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

    // QML architecture cleanup: extracted to components/MainToolBar.qml
    // (previously ~235 lines of inline button/combobox wiring here).
    // `viewport` below still resolves to this file's own ViewportPanel
    // id, exactly as the toolbar's internal bindings always referenced
    // it -- see MainToolBar.qml's header comment for why it now needs
    // to be passed in explicitly.
    header: MainToolBar {
        id: mainToolBar
        objectName: "mainToolBar"
        viewport: viewport
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
            // v2.1 correction (DESIGN.md section 2/7): docked panels are
            // not cards -- flat panel surface + border, no shadow.
            Rectangle {
                objectName: "workbenchDock"
                color: Theme.panel
                border.color: Theme.border
                SplitView.preferredWidth: 360
                SplitView.minimumWidth: 280

                ColumnLayout {
                    anchors.fill: parent
                    spacing: 0

                    TabBar {
                        id: workbenchTabs
                        objectName: "workbenchTabs"
                        Layout.fillWidth: true
                        contentHeight: 32

                        Repeater {
                            model: [
                                { "label": "Project",   "icon": "project" },
                                { "label": "Structure", "icon": "structure" },
                                { "label": "Mesh",      "icon": "mesh" },
                                { "label": "Process",   "icon": "process" },
                                { "label": "Sweeps",    "icon": "sweeps" },
                                { "label": "Probe Station", "icon": "probeStation" },
                                { "label": "Telemetry", "icon": "telemetry" },
                                { "label": "Bands", "icon": "bands" },
                                { "label": "Transient", "icon": "transient" },
                                { "label": "AC", "icon": "ac" },
                                { "label": "Physics Lab", "icon": "physicsLab" },
                                { "label": "Builder",   "icon": "builder" }
                            ]
                            delegate: TabButton {
                                id: tabDelegate
                                required property var modelData
                                width: Math.max(implicitWidth, 64)
                                font.pixelSize: Theme.fsSmall
                                // v2.1 correction (DESIGN.md section 9,
                                // Tab): selected label brightens to
                                // Theme.text (paired with the accent
                                // underline below), not a blue tint --
                                // color alone no longer needs to carry
                                // the "selected" signal since the
                                // underline already does.
                                readonly property color tabColor: tabDelegate.checked ? Theme.text
                                                                   : tabDelegate.hovered ? Theme.text
                                                                   : tabDelegate.activeFocus ? Theme.focus : Theme.textDim
                                contentItem: Row {
                                    spacing: Theme.padXs
                                    anchors.centerIn: parent
                                    Image {
                                        objectName: "sidebarTabIcon"
                                        anchors.verticalCenter: parent.verticalCenter
                                        source: Icons.svg(tabDelegate.modelData.icon, tabDelegate.tabColor)
                                        sourceSize.width: 15
                                        sourceSize.height: 15
                                        width: 15
                                        height: 15
                                        smooth: true
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: tabDelegate.modelData.label
                                        font.pixelSize: tabDelegate.font.pixelSize
                                        font.bold: tabDelegate.checked
                                        color: tabDelegate.tabColor
                                        elide: Text.ElideRight
                                        Behavior on color { ColorAnimation { duration: Theme.animFast } }
                                    }
                                }
                                background: Rectangle {
                                    // v2.1 correction: radius capped at
                                    // radiusSm (3px, DESIGN.md section 6)
                                    // -- was radiusLg (6px).
                                    radius: Theme.radiusSm
                                    color: tabDelegate.checked ? Theme.accentSoft
                                           : tabDelegate.hovered ? Theme.hoverOverlay : "transparent"
                                    Behavior on color { ColorAnimation { duration: Theme.animFast } }
                                }
                            }
                        }

                        // Accent bar that glides beneath the active tab,
                        // tying tab selection to a single continuous
                        // piece of motion. v2.1 correction (DESIGN.md
                        // section 2/9, Tab component): a gradient on a
                        // tab indicator encodes nothing -- flat
                        // Theme.accent underline instead, matching the
                        // spec's "flat 2px accent underline (no
                        // gradient)" rule.
                        Rectangle {
                            id: tabIndicator
                            height: 2
                            radius: 0
                            y: workbenchTabs.height - height
                            x: workbenchTabs.currentItem ? workbenchTabs.currentItem.x : 0
                            width: workbenchTabs.currentItem ? workbenchTabs.currentItem.width : 0
                            color: Theme.accent
                            Behavior on x { NumberAnimation { duration: Theme.animMed; easing.type: Easing.OutCubic } }
                            Behavior on width { NumberAnimation { duration: Theme.animMed; easing.type: Easing.OutCubic } }
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
                        ProbeStationPanel {
                            objectName: "probeStationPanel"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            controller: appController.probeStation
                        }
                        SolverTelemetryPanel {
                            objectName: "solverTelemetryPanel"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                        }
                        BandDiagramPanel {
                            objectName: "bandDiagramPanel"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                        }
                        TransientPanel {
                            objectName: "transientPanel"
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            controller: appController
                        }
                        ACPanel {
                            objectName: "acPanel"
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

            // ---- CENTER: viewport -----------------------------------------
            // v2.1 correction (DESIGN.md section 2/10): the viewport is
            // elevation 0, the darkest, highest-contrast surface in the
            // app ("content beats chrome, always") -- it is flush
            // against the surrounding chrome, not inset as a floating
            // card with a margin/border/radius. The SplitView.*
            // attached properties stay on this wrapper since a
            // SplitView's direct children carry them.
            Rectangle {
                id: viewportFrame
                SplitView.fillWidth: true
                SplitView.minimumWidth: 320
                color: Theme.background

                ViewportPanel {
                    id: viewport
                    objectName: "viewportPanel"
                    anchors.fill: parent
                    controller: appController

                    BusyOverlay {
                        anchors.fill: parent
                        running: appController.busy
                        stageText: appController.status
                    }
                }
            }

            // ---- RIGHT: collapsible properties dock ---------------------
            Rectangle {
                objectName: "propertiesDock"
                color: Theme.panel
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
                objectName: "solverEngineLabel"
                visible: appController.hasResult && text.length > 0
                text: appController.solverEngineLabel
                color: Theme.textFaint
                font.pixelSize: Theme.fsTiny
            }
            Label {
                text: Theme.dark ? "dark" : "light"
                color: Theme.textFaint
                font.pixelSize: Theme.fsTiny
            }
            // GUI-IMPROVEMENT-PLAN Phase 4: visual state indicators
            StatusIndicator {
                busy: appController.busy
                hasResult: appController.hasResult
                isDirty: appController.isDirty
                hasError: stateValidator && stateValidator.problemCount > 0
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
