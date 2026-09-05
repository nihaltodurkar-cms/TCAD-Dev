import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import ".."

// QML architecture cleanup: extracted from Main.qml's inline
// `header: ToolBar {...}` block (previously ~235 lines of button/
// combobox wiring mixed into the window-shell file). Pure structural
// extraction -- every objectName, id, binding, signal handler, and
// styling rule is unchanged from before the extraction. The only new
// thing is the `viewport` property: Main.qml's toolbar used to reach
// the ViewportPanel instance implicitly via its `viewport` id
// (a same-file forward reference, valid because QML property bindings
// resolve lazily, not at parse time); a separate file can't do that,
// so Main.qml now passes it in explicitly (`MainToolBar { viewport:
// viewport }` -- the right-hand `viewport` still resolves in Main.qml's
// own scope to its ViewportPanel's id, exactly as it always did).
ToolBar {
    id: root
    property var viewport

    // Faint drop shadow to lift the toolbar above the workbench --
    // a small depth cue that makes the chrome read as "above" the
    // content instead of flush with it.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.bottom
        height: 6
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.shadow }
            GradientStop { position: 1.0; color: "transparent" }
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.padLg
        anchors.rightMargin: Theme.padLg
        spacing: Theme.padSm

        Button {
            id: runButton
            objectName: "runButton"
            display: AbstractButton.IconOnly
            text: "▶"
            ToolTip.visible: hovered
            ToolTip.delay: 500
            // Workflow-friction pass: disabled (with an explanatory
            // tooltip) instead of clickable-then-erroring -- mirrors
            // run()'s own "Nothing to run" early-return check via
            // hasDeviceToRun, so the dead-end error dialog is no
            // longer the only feedback a user with nothing loaded
            // gets from pressing Run.
            ToolTip.text: appController.hasDeviceToRun
                          ? "Solve the current device"
                          : "Load an example (File menu) or build a structure first"
            enabled: !appController.busy && appController.hasDeviceToRun
            onClicked: appController.run()
            background: Rectangle {
                radius: Theme.radiusSm
                color: !runButton.enabled ? "transparent"
                       : runButton.pressed ? Qt.darker(Theme.ok, 1.15)
                       : runButton.hovered ? Theme.ok : Qt.rgba(Theme.ok.r, Theme.ok.g, Theme.ok.b, 0.85)
                Behavior on color { ColorAnimation { duration: Theme.animFast } }
                scale: runButton.pressed ? 0.92 : 1.0
                Behavior on scale { NumberAnimation { duration: Theme.animFast; easing.type: Easing.OutCubic } }
            }
            contentItem: Image {
                source: Icons.svg("run", runButton.enabled ? "#ffffff" : Theme.textFaint)
                sourceSize.width: 13
                sourceSize.height: 13
                fillMode: Image.PreserveAspectFit
                horizontalAlignment: Image.AlignHCenter
                verticalAlignment: Image.AlignVCenter
            }
        }
        Button {
            id: stopButton
            display: AbstractButton.IconOnly
            text: "■"
            enabled: appController.busy
            ToolTip.visible: hovered
            ToolTip.delay: 500
            ToolTip.text: "Cancel the running solve"
            onClicked: appController.cancel()
            background: Rectangle {
                radius: Theme.radiusSm
                color: !stopButton.enabled ? "transparent"
                       : stopButton.pressed ? Qt.darker(Theme.error, 1.15)
                       : stopButton.hovered ? Theme.error : Qt.rgba(Theme.error.r, Theme.error.g, Theme.error.b, 0.85)
                Behavior on color { ColorAnimation { duration: Theme.animFast } }
                scale: stopButton.pressed ? 0.92 : 1.0
                Behavior on scale { NumberAnimation { duration: Theme.animFast; easing.type: Easing.OutCubic } }
            }
            contentItem: Image {
                source: Icons.svg("stop", stopButton.enabled ? "#ffffff" : Theme.textFaint)
                sourceSize.width: 12
                sourceSize.height: 12
                fillMode: Image.PreserveAspectFit
                horizontalAlignment: Image.AlignHCenter
                verticalAlignment: Image.AlignVCenter
            }
        }
        ComboBox {
            id: backendBox
            objectName: "backendSelector"
            // v0.6 Phase 2c: DEVSIM is 1D-two-terminal-only, so this
            // must not even appear for the Structure/Device-Builder
            // (2D) path -- not merely show devsim disabled there.
            visible: appController.canSelectBackend
            Layout.preferredWidth: 110
            textRole: "label"
            valueRole: "id"
            model: appController.canSelectBackend
                   ? appController.backendOptionsForQml() : []
            delegate: ItemDelegate {
                width: backendBox.width
                text: modelData.label
                enabled: modelData.enabled
                ToolTip.visible: hovered && !modelData.enabled
                ToolTip.text: modelData.reason
            }
            onActivated: appController.setBackend(
                model[currentIndex].id)
            Connections {
                target: appController
                function onStructureChanged() {
                    if (appController.canSelectBackend)
                        backendBox.model = appController.backendOptionsForQml()
                }
            }
        }
        ComboBox {
            id: engineBox
            objectName: "engineSelector"
            // v0.6 Phase 2d: which linear-solve engine (Direct/GPU
            // direct/AMG/MPI Schwarz) the pytcad backend forces --
            // "Auto" (default) reproduces solver_runner.run_job's
            // existing node-count/dimensionality heuristic unchanged.
            Layout.preferredWidth: 130
            textRole: "label"
            valueRole: "id"
            model: appController.engineOptionsForQml()
            delegate: ItemDelegate {
                width: engineBox.width
                text: modelData.label
                enabled: modelData.enabled
                ToolTip.visible: hovered && !modelData.enabled
                ToolTip.text: modelData.reason
            }
            ToolTip.visible: hovered
            ToolTip.delay: 600
            ToolTip.text: "Force which solver engine Run uses (Auto picks by device size/shape)"
            onActivated: appController.setEngine(
                model[currentIndex].id)
            Connections {
                target: appController
                function onStructureChanged() {
                    engineBox.model = appController.engineOptionsForQml()
                }
            }
        }
        ToolSeparator {}
        Button {
            id: undoButton
            display: AbstractButton.IconOnly
            text: "↶"
            enabled: appController.canUndo
            ToolTip.visible: hovered
            ToolTip.delay: 500
            ToolTip.text: "Undo (Ctrl+Z)"
            onClicked: appController.undo()
            background: Rectangle {
                radius: Theme.radiusSm
                color: undoButton.pressed ? Theme.pressOverlay
                       : undoButton.hovered ? Theme.hoverOverlay : "transparent"
                Behavior on color { ColorAnimation { duration: Theme.animFast } }
            }
            contentItem: Image {
                source: Icons.svg("undo", undoButton.enabled ? Theme.text : Theme.textFaint)
                sourceSize.width: 14
                sourceSize.height: 14
                fillMode: Image.PreserveAspectFit
                horizontalAlignment: Image.AlignHCenter
                verticalAlignment: Image.AlignVCenter
            }
        }
        Button {
            id: redoButton
            display: AbstractButton.IconOnly
            text: "↷"
            enabled: appController.canRedo
            ToolTip.visible: hovered
            ToolTip.delay: 500
            ToolTip.text: "Redo (Ctrl+Y)"
            onClicked: appController.redo()
            background: Rectangle {
                radius: Theme.radiusSm
                color: redoButton.pressed ? Theme.pressOverlay
                       : redoButton.hovered ? Theme.hoverOverlay : "transparent"
                Behavior on color { ColorAnimation { duration: Theme.animFast } }
            }
            contentItem: Image {
                source: Icons.svg("redo", redoButton.enabled ? Theme.text : Theme.textFaint)
                sourceSize.width: 14
                sourceSize.height: 14
                fillMode: Image.PreserveAspectFit
                horizontalAlignment: Image.AlignHCenter
                verticalAlignment: Image.AlignVCenter
            }
        }
        ToolSeparator {}
        ComboBox {
            id: viewModeBox
            objectName: "viewModeSelector"
            implicitContentWidthPolicy: ComboBox.WidestText
            model: ["Structure", "Doping", "Mesh", "Process", "Curves",
                    "C-V", "Transient", "AC", "Line Cut", "Bands",
                    "Recombination", "Convergence", "Results"]
            ToolTip.visible: hovered
            ToolTip.delay: 600
            ToolTip.text: "What the viewport shows"
            onActivated: {
                var m = {"Structure": "structure", "Doping": "doping",
                        "Mesh": "mesh", "Process": "process",
                        "Curves": "series", "C-V": "cv",
                        "Transient": "transient", "AC": "ac",
                        "Line Cut": "cut",
                        "Bands": "bands",
                        "Recombination": "recombination",
                        "Convergence": "convergence",
                        "Results": "doping"}[currentText]
                root.viewport.setViewMode(m)
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
            id: themeButton
            text: Theme.dark ? "☀" : "🌙"
            ToolTip.visible: hovered
            ToolTip.delay: 500
            ToolTip.text: "Toggle light/dark (Ctrl+D)"
            onClicked: { spin.start(); Theme.toggle(); root.viewport.syncTheme() }
            background: Rectangle {
                radius: Theme.radiusSm
                color: themeButton.pressed ? Theme.pressOverlay
                       : themeButton.hovered ? Theme.hoverOverlay : "transparent"
                Behavior on color { ColorAnimation { duration: Theme.animFast } }
            }
            contentItem: Image {
                source: Icons.svg(Theme.dark ? "sun" : "moon", Theme.text)
                sourceSize.width: 15
                sourceSize.height: 15
                fillMode: Image.PreserveAspectFit
                horizontalAlignment: Image.AlignHCenter
                verticalAlignment: Image.AlignVCenter
                rotation: 0
                RotationAnimation on rotation {
                    id: spin
                    from: 0; to: 360
                    duration: Theme.animSlow
                    easing.type: Easing.OutCubic
                }
            }
        }
    }
}
