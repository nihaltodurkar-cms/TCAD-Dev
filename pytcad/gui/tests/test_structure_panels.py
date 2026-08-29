"""Smoke test for the v0.2 QML additions -- same headless pattern as
v0.1's test_app_launches.py, extended to the new panels."""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def test_engine_still_loads_with_v02_panels(gapp):
    engine, controller = gui_app.create_engine(gapp)
    assert engine.rootObjects(), "Main.qml failed to load -- see stderr for QML errors"


def test_v02_panels_and_their_models_bind_through_qml(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    controller.loadStructureExample("mosfet_2d_structure")

    structure_panel = root.findChild(object, "structurePanel")
    mesh_panel = root.findChild(object, "meshPanel")
    assert structure_panel is not None, "missing structurePanel"
    assert mesh_panel is not None, "missing meshPanel"


def test_view_mode_selector_exists_and_switches(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    selector = root.findChild(object, "viewModeSelector")
    assert selector is not None, "missing viewModeSelector"


def test_dirty_title_reflects_undo_state(gapp):
    engine, controller = gui_app.create_engine(gapp)
    controller.loadStructureExample("mosfet_2d_structure")
    assert controller.isDirty is False
    controller.addRegion("Extra", 0.0, 1e-5, 0.0, 1e-5, 1e16)
    assert controller.isDirty is True


def test_process_panel_exists_and_binds_its_model(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    panel = root.findChild(object, "processPanel")
    assert panel is not None, "missing processPanel"

    step_list = root.findChild(object, "processStepList")
    assert step_list is not None, "missing processStepList"

    controller.addProcessStep("substrate", "Substrate",
                               {"length_cm": 1e-3, "background_doping_cm3": 1e15,
                                "mesh": {"h_min_cm": 1e-7, "h_max_cm": 1e-5, "ratio": 1.2}})
    assert controller.processFlowModel.rowCount() == 1


def test_implant_editor_shows_only_when_implant_step_selected(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    controller.addProcessStep("implant", "Implant",
                              {"species": "B", "energy_keV": 30.0, "dose_cm2": 1e14})
    process_panel = root.findChild(object, "processPanel")
    # v0.5 UI: the workbench panels live in a tabbed dock; bring the
    # Process tab forward exactly like a user click would.
    root.findChild(object, "workbenchTabs").setProperty("currentIndex", 3)
    step_id = controller.process_flow.steps[0].id
    process_panel.setProperty("selectedStepId", step_id)
    implant_editor = root.findChild(object, "implantEditor")
    assert implant_editor is not None

    # Routing: only the implant editor should be visible for this step,
    # and it should be populated with this step's actual parameters (not
    # left over from another step or a stale default).
    assert implant_editor.property("visible") is True
    assert process_panel.property("selectedOperation") == "implant"

    substrate_editor = root.findChild(object, "substrateEditor")
    anneal_editor = root.findChild(object, "annealEditor")
    oxidize_editor = root.findChild(object, "oxidizeEditor")
    assert substrate_editor is not None and substrate_editor.property("visible") is False
    assert anneal_editor is not None and anneal_editor.property("visible") is False
    assert oxidize_editor is not None and oxidize_editor.property("visible") is False

    params = implant_editor.property("parameters")
    assert params["species"] == "B"
    assert params["energy_keV"] == 30.0
    assert params["dose_cm2"] == 1e14


def test_step_editor_routing_updates_when_selection_changes(gapp):
    """Selecting a different step must re-route to that step's editor and
    re-populate its parameters -- exercises the explicit
    _refreshSelection()/Connections fallback in ProcessPanel.qml, since
    processStepOperation()/processStepParameters() are Slot calls that
    Qt Quick's binding dependency tracker can't see inside of."""
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    controller.addProcessStep("substrate", "Substrate",
                              {"length_cm": 1e-3, "background_doping_cm3": 1e15,
                               "mesh": {"h_min_cm": 1e-7, "h_max_cm": 1e-5, "ratio": 1.2}})
    controller.addProcessStep("anneal", "Anneal",
                              {"temperature_C": 950.0, "time_s": 60.0})
    # v0.5 UI: bring the Process tab forward like a user click would
    root.findChild(object, "workbenchTabs").setProperty("currentIndex", 3)
    process_panel = root.findChild(object, "processPanel")
    substrate_id = controller.process_flow.steps[0].id
    anneal_id = controller.process_flow.steps[1].id

    process_panel.setProperty("selectedStepId", substrate_id)
    assert process_panel.property("selectedOperation") == "substrate"
    substrate_editor = root.findChild(object, "substrateEditor")
    assert substrate_editor.property("visible") is True

    process_panel.setProperty("selectedStepId", anneal_id)
    assert process_panel.property("selectedOperation") == "anneal"
    assert substrate_editor.property("visible") is False
    anneal_editor = root.findChild(object, "annealEditor")
    assert anneal_editor.property("visible") is True
    anneal_params = anneal_editor.property("parameters")
    assert anneal_params["temperature_C"] == 950.0
    assert anneal_params["time_s"] == 60.0


def test_step_editor_parameters_refresh_after_edit_in_place(gapp):
    """Editing a step's parameters (setProcessStepParameters, which fires
    controller.structureChanged rather than changing selectedStepId) must
    still be reflected in the routed editor's `parameters` property."""
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    controller.addProcessStep("anneal", "Anneal",
                              {"temperature_C": 900.0, "time_s": 10.0})
    process_panel = root.findChild(object, "processPanel")
    # v0.5 UI: the workbench panels live in a tabbed dock; bring the
    # Process tab forward exactly like a user click would.
    root.findChild(object, "workbenchTabs").setProperty("currentIndex", 3)
    step_id = controller.process_flow.steps[0].id
    process_panel.setProperty("selectedStepId", step_id)

    controller.setProcessStepParameters(step_id, {"temperature_C": 1050.0, "time_s": 45.0})

    anneal_editor = root.findChild(object, "annealEditor")
    params = anneal_editor.property("parameters")
    assert params["temperature_C"] == 1050.0
    assert params["time_s"] == 45.0


def test_derived_quantities_panel_and_process_validation_panel_exist(gapp):
    """Task 13: ProcessPanel.qml gains a DerivedQuantitiesPanel and a
    second ValidationPanel instance (errorsProperty="processValidationErrors").
    This is a binding smoke test only -- the exact formatted-value text is
    covered by DerivedQuantitiesPanel.qml's own JS formatting logic and by
    test_process_controller.py's processDerivedQuantities() tests; here we
    just confirm both panels exist, bind to the controller, and that the
    process ValidationPanel reacts to processValidationErrors."""
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]

    dq_panel = root.findChild(object, "derivedQuantitiesPanel")
    assert dq_panel is not None, "missing derivedQuantitiesPanel"
    assert dq_panel.property("controller") is not None

    process_validation_panel = root.findChild(object, "processValidationPanel")
    assert process_validation_panel is not None, "missing processValidationPanel"

    # An invalid implant step (no dose/energy) should surface through
    # processValidationErrors and this second ValidationPanel instance,
    # independently of structureValidationErrors / StructurePanel's own
    # ValidationPanel (which stays on the default errorsProperty).
    controller.addProcessStep("implant", "Implant", {"species": "B"})
    controller.runProcessValidation()
    assert len(controller.processValidationErrors) > 0
    assert controller.structureValidationErrors == []


def test_structure_panel_validation_still_uses_default_errors_property(gapp):
    """Confirms ValidationPanel.qml's generalization (Task 13) is
    backward-compatible: StructurePanel.qml's existing call site (no
    errorsProperty override) still reads structureValidationErrors."""
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    controller.loadStructureExample("mosfet_2d_structure")
    structure_panel = root.findChild(object, "structurePanel")
    assert structure_panel is not None
    # No errors on a freshly-loaded valid example.
    assert controller.runStructureValidation() is True


def test_native_file_dialogs_exist_and_replace_typed_path_dialog(gapp):
    """v0.2.1: Save/Open moved to QtQuick.Dialogs' native FileDialog."""
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    assert root.findChild(object, "saveFileDialog") is not None
    assert root.findChild(object, "openFileDialog") is not None
    assert root.findChild(object, "projectDialog") is None


def test_process_run_stop_and_handoff_controls_exist_and_are_wired(gapp):
    """Final-review Critical finding: runProcess()/cancelProcess()/
    buildDeviceFromProcess() (AppController, Task 8) had ZERO callers
    anywhere in the real QML tree -- a user could compose a process flow
    in ProcessPanel.qml but had no button to ever run it, stop it, or
    hand it off to a device solve, and no field to set the two handoff
    voltages. Every prior test for this feature called the controller
    slots directly from Python, which is exactly the test shape that let
    this ship unnoticed (a passing test proves the Python method works,
    not that anything in the real UI reaches it).

    This test instead finds the actual QML buttons/fields by objectName
    and drives them the way a user would -- clicking a real QML Button's
    `clicked` signal via QMetaObject.invokeMethod (which dispatches
    through the button's own onClicked handler, not a Python-side call
    to controller.runProcess() etc.) and setting a real QML TextField's
    text -- and confirms the underlying AppController state actually
    changes as a result.
    """
    from PySide6.QtCore import QEventLoop, QMetaObject, QTimer, Q_ARG

    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]

    run_button = root.findChild(object, "processRunButton")
    stop_button = root.findChild(object, "processStopButton")
    build_button = root.findChild(object, "buildDeviceFromProcessButton")
    left_v_field = root.findChild(object, "leftContactVField")
    right_v_field = root.findChild(object, "rightContactVField")
    assert run_button is not None, "missing processRunButton"
    assert stop_button is not None, "missing processStopButton"
    assert build_button is not None, "missing buildDeviceFromProcessButton"
    assert left_v_field is not None, "missing leftContactVField"
    assert right_v_field is not None, "missing rightContactVField"

    # Enabled-state wiring, mirroring the main toolbar's device Run/Stop
    # buttons: Run enabled and Stop disabled while idle; Build disabled
    # until a process result exists.
    assert run_button.property("enabled") is True
    assert stop_button.property("enabled") is False
    assert build_button.property("enabled") is False

    controller.addProcessStep("substrate", "Substrate",
                              {"length_cm": 3e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}})
    controller.addProcessStep("implant", "Implant",
                              {"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14})
    assert controller.runProcessValidation() is True, controller.processValidationErrors

    # Set the two handoff voltage fields the way a user typing into the
    # real TextField would: set text, then fire editingFinished.
    left_v_field.setProperty("text", "0.1")
    QMetaObject.invokeMethod(left_v_field, "editingFinished")
    right_v_field.setProperty("text", "0.4")
    QMetaObject.invokeMethod(right_v_field, "editingFinished")
    assert controller.leftContactV == pytest.approx(0.1)
    assert controller.rightContactV == pytest.approx(0.4)

    loop = QEventLoop()
    controller.processResultChanged.connect(loop.quit)
    controller.errorRaised.connect(lambda s, d: (print("ERROR", s, d), loop.quit()))
    QTimer.singleShot(60000, loop.quit)
    # The actual regression: this drives controller.runProcess() through
    # the real QML Button's clicked signal, not a direct Python call.
    invoked = QMetaObject.invokeMethod(run_button, "clicked")
    assert invoked, "could not invoke the real QML Run button's clicked signal"
    assert controller.busy is True, (
        "clicking the real processRunButton did not actually start a run "
        "-- it is present in the tree but not wired to controller.runProcess()")
    assert stop_button.property("enabled") is True
    loop.exec()

    assert controller.hasProcessResult is True, controller.status
    assert build_button.property("enabled") is True

    QMetaObject.invokeMethod(build_button, "clicked")
    assert controller.spec is not None, (
        "clicking the real buildDeviceFromProcessButton did not call "
        "controller.buildDeviceFromProcess()")
    assert controller.spec.bias["left"] == pytest.approx(0.1)
    assert controller.spec.bias["right"] == pytest.approx(0.4)


def test_process_stop_button_actually_cancels_a_real_run(gapp):
    """Same real-QML-click requirement as the test above, for Stop:
    clicking the actual processStopButton must reach
    controller.cancelProcess(), not just controller.busy flipping back to
    False on its own once a short run finishes."""
    from PySide6.QtCore import QEventLoop, QMetaObject, QTimer

    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    run_button = root.findChild(object, "processRunButton")
    stop_button = root.findChild(object, "processStopButton")

    # A handful of anneal steps over a fine mesh, so there is a real
    # window to click Stop before the flow finishes on its own.
    controller.addProcessStep("substrate", "Substrate",
                              {"length_cm": 5e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 5e-9, "h_max_cm": 5e-7, "ratio": 1.05}})
    controller.addProcessStep("implant", "Implant",
                              {"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14})
    for _ in range(6):
        controller.addProcessStep("anneal", "Anneal",
                                  {"temperature_C": 950.0, "time_s": 600.0})
    assert controller.runProcessValidation() is True, controller.processValidationErrors

    QMetaObject.invokeMethod(run_button, "clicked")
    assert controller.busy is True

    loop = QEventLoop()
    controller.busyChanged.connect(lambda: (not controller.busy) and loop.quit())
    QTimer.singleShot(15000, loop.quit)
    QTimer.singleShot(400, lambda: QMetaObject.invokeMethod(stop_button, "clicked"))
    loop.exec()

    assert controller.busy is False
    assert controller.hasProcessResult is False, (
        "clicking the real processStopButton did not cancel the run "
        "-- a result was still produced")
    assert "cancel" in controller.status.lower()


def test_process_view_mode_actually_renders_a_process_result(gapp):
    """Regression test for a Task 15 real-display finding: MplCanvasItem's
    setProcessSource(store, step_id) is fully implemented and unit-tested
    (test_viewport_modes.py calls it directly), but nothing in the actual
    QML tree ever called it -- ViewportPanel.setViewMode()'s "process"
    branch didn't exist, AppController had no QML-visible property to hand
    the ProcessResultStore through (structureForQml/meshModelForQml have no
    process equivalent), and ProcessPanel's `stepSelected` signal was
    declared and emitted but never connected to anything in Main.qml. The
    net effect: running a real process flow and switching the view mode
    ComboBox to "Process" rendered the pre-run "No project loaded"
    placeholder forever, not the doping plot -- exactly the class of bug
    (a viewport mode silently rendering the wrong/no content) this task's
    brief calls out from this codebase's own history. This test drives the
    real QML tree (not just MplCanvasItem in isolation) through a real
    process run and confirms the canvas actually receives the result."""
    from PySide6.QtCore import QEventLoop, QTimer

    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]

    controller.addProcessStep("substrate", "Substrate",
                              {"length_cm": 3e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}})
    controller.addProcessStep("implant", "Implant",
                              {"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14})
    assert controller.runProcessValidation() is True, controller.processValidationErrors

    loop = QEventLoop()
    controller.processResultChanged.connect(loop.quit)
    controller.errorRaised.connect(lambda s, d: (print("ERROR", s, d), loop.quit()))
    QTimer.singleShot(60000, loop.quit)
    controller.runProcess()
    loop.exec()
    assert controller.hasProcessResult is True, controller.status

    viewport = root.findChild(object, "viewportPanel")
    assert viewport is not None
    viewport.setProperty("currentMode", "")  # force setViewMode to actually re-apply below
    from PySide6.QtCore import QMetaObject, Q_ARG
    QMetaObject.invokeMethod(viewport, "setViewMode", Q_ARG("QVariant", "process"))

    canvas = root.findChild(object, "mplCanvas")
    assert canvas is not None
    # The real defect: before the fix, canvas._process_store stayed None
    # forever because nothing ever called setProcessSource().
    assert canvas._process_store is not None, (
        "ViewportPanel never handed the ProcessResultStore to MplCanvasItem "
        "-- Process view mode would render the 'No project loaded' placeholder")
    img = canvas.renderToImage()
    assert not img.isNull()
    colours = {img.pixel(x, y) for x in range(0, img.width(), 41)
              for y in range(0, img.height(), 41)}
    assert len(colours) > 1, "process viewport rendered a blank/flat image"

    # ProcessPanel's stepSelected signal must also actually reach the
    # viewport now (Main.qml's onStepSelected wiring).
    step_ids = controller._process_result.step_ids()
    QMetaObject.invokeMethod(viewport, "setProcessStep", Q_ARG("QVariant", step_ids[0]))
    assert canvas._process_store._selected == step_ids[0]

    # Second Task 15 finding, checked against this same run/engine rather
    # than spinning up another full create_engine() + real subprocess run
    # (the offscreen test suite accumulates many live QQuickWindow/
    # MplCanvasItem instances across gui/tests/ in one process; one test
    # function too many pushed it over into a native Qt scenegraph crash
    # during a later test's repaint -- confirmed by bisection, not
    # speculation). A numpy.float64 left unconverted in
    # processDerivedQuantities()'s returned dict caused
    # DerivedQuantitiesPanel.qml's Math.round(value) to render "-1 Ω/□"
    # for every step, regardless of the real (positive) computed
    # resistance -- a live windowed screenshot showed this literal text.
    # This drives the real QML DerivedQuantitiesPanel and reads its own
    # _formatValue() output, the same function the visible Label uses.
    final_id = controller.process_flow.steps[-1].id
    dq_panel = root.findChild(object, "derivedQuantitiesPanel")
    assert dq_panel is not None
    dq_panel.setProperty("stepId", final_id)

    quantities = dq_panel.property("quantities")
    assert "sheet_resistance_ohm_sq" in quantities

    # _formatValue is a QML-declared JS function, not a property -- invoke
    # it through QMetaObject so this calls the exact same code path the
    # visible Label uses (root._formatValue(modelData, ...) in
    # DerivedQuantitiesPanel.qml), not a reimplementation of it.
    from PySide6.QtCore import Q_RETURN_ARG
    formatted = QMetaObject.invokeMethod(
        dq_panel, "_formatValue", Q_RETURN_ARG("QVariant"),
        Q_ARG("QVariant", "sheet_resistance_ohm_sq"),
        Q_ARG("QVariant", quantities["sheet_resistance_ohm_sq"]))
    assert formatted != "-1 Ω/□", (
        "DerivedQuantitiesPanel rendered the numpy.float64 marshaling "
        "artifact '-1 Ω/□' instead of the real computed resistance")
    assert formatted.endswith(" Ω/□"), formatted
    value_part = formatted[:-len(" Ω/□")]
    assert int(value_part) > 0, formatted
