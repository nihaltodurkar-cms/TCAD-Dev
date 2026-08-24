"""AppController's process-flow surface (v0.3): ProcessStepListModel +
undo-aware CRUD slots, tested headlessly the same way v0.2's structure
controller tests are -- Python-level assertions on the models/state the
Qt properties expose."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication

from gui.controllers.app_controller import AppController


@pytest.fixture(scope="module")
def qapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def test_add_process_step_is_undoable(qapp):
    app = AppController()
    app.addProcessStep("substrate", "Substrate",
                       {"length_cm": 3e-4, "background_doping_cm3": -1e16,
                        "mesh": {"h_min_cm": 2e-8, "h_max_cm": 2e-6, "ratio": 1.15}})
    assert app.processFlowModel.rowCount() == 1
    assert app.isDirty is True
    app.undo()
    assert app.processFlowModel.rowCount() == 0
    assert app.isDirty is False


def test_move_and_duplicate_process_step(qapp):
    app = AppController()
    app.addProcessStep("substrate", "Substrate", {})
    app.addProcessStep("implant", "Implant", {"species": "B"})
    ids = [app.process_flow.steps[i].id for i in range(2)]
    app.moveProcessStep(ids[1], -1)
    # offset=-1 decrements index (same clamped-offset contract as
    # move_region/move_step), so implant (ids[1]) is now at index 0 and
    # substrate (ids[0]) at index 1.
    assert [s.id for s in app.process_flow.steps] == [ids[1], ids[0]]
    app.duplicateProcessStep(ids[0])
    assert len(app.process_flow.steps) == 3
    # duplicateProcessStep(ids[0]) duplicates substrate, which now sits
    # at index 1; the duplicate is inserted right after it at index 2.
    assert app.process_flow.steps[2].parameters == app.process_flow.steps[1].parameters
    assert app.process_flow.steps[2].parameters is not app.process_flow.steps[1].parameters


def test_enable_disable_and_rename_process_step(qapp):
    app = AppController()
    app.addProcessStep("substrate", "Substrate", {})
    step_id = app.process_flow.steps[0].id
    app.setProcessStepEnabled(step_id, False)
    assert app.process_flow.steps[0].enabled is False
    app.renameProcessStep(step_id, "My Substrate")
    assert app.process_flow.steps[0].name == "My Substrate"


def test_run_process_validation_reports_step_scoped_errors(qapp):
    app = AppController()
    app.addProcessStep("implant", "Implant", {"species": "B", "energy_keV": 30.0, "dose_cm2": 1e14})
    ok = app.runProcessValidation()
    assert ok is False
    assert len(app.processValidationErrors) > 0


def test_set_process_step_parameters_is_undoable():
    app = AppController()
    app.addProcessStep("implant", "Implant", {"species": "B"})
    step_id = app.process_flow.steps[0].id
    app.setProcessStepParameters(step_id, {"species": "P", "energy_keV": 50.0})
    assert app.process_flow.steps[0].parameters == {"species": "P", "energy_keV": 50.0}
    app.undo()
    assert app.process_flow.steps[0].parameters == {"species": "B"}


def test_process_step_operation_and_parameters_accessors():
    app = AppController()
    app.addProcessStep("implant", "Implant", {"species": "B", "energy_keV": 30.0})
    step_id = app.process_flow.steps[0].id
    assert app.processStepOperation(step_id) == "implant"
    assert app.processStepParameters(step_id) == {"species": "B", "energy_keV": 30.0}
    assert app.processStepOperation("nonexistent") == ""
    assert app.processStepParameters("nonexistent") == {}


def test_remove_process_step_is_undoable():
    app = AppController()
    app.addProcessStep("substrate", "Substrate", {})
    step_id = app.process_flow.steps[0].id
    app.removeProcessStep(step_id)
    assert app.processFlowModel.rowCount() == 0
    app.undo()
    assert app.processFlowModel.rowCount() == 1
    assert app.process_flow.steps[0].id == step_id


def test_process_derived_quantities_returns_empty_before_a_run(qapp):
    # No process result yet -- must not raise, just return {} (mirrors
    # processStepParameters's not-found -> {} contract).
    app = AppController()
    app.addProcessStep("substrate", "Substrate", {})
    step_id = app.process_flow.steps[0].id
    assert app.processDerivedQuantities(step_id) == {}


def test_process_derived_quantities_for_a_run_flow(qapp):
    """Design section 19's data source: runs a real substrate+implant+anneal
    flow through process_runner.py (same integration path as
    test_process_handoff.py) and checks that processDerivedQuantities()
    returns the exact key set/naming the Derived Quantities panel formats
    against -- junction_depth_um, per-species peak_concentration_cm3_/
    peak_depth_um_/implanted_dose_cm2_, and sheet_resistance_ohm_sq."""
    app = AppController()
    app.addProcessStep("substrate", "Substrate",
                       {"length_cm": 3e-4, "background_doping_cm3": -1e16,
                        "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}})
    app.addProcessStep("implant", "Implant",
                       {"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14})
    app.addProcessStep("anneal", "Anneal",
                       {"temperature_C": 950.0, "time_s": 600.0})
    assert app.runProcessValidation() is True, app.processValidationErrors

    loop = QEventLoop()
    app.processResultChanged.connect(loop.quit)
    app.errorRaised.connect(lambda s, d: (print("ERROR", s, d), loop.quit()))
    QTimer.singleShot(60000, loop.quit)
    app.runProcess()
    loop.exec()

    assert app.hasProcessResult is True, app.status

    final_id = app.process_flow.steps[-1].id
    dq = app.processDerivedQuantities(final_id)

    assert "junction_depth_um" in dq
    assert isinstance(dq["junction_depth_um"], list)
    assert "sheet_resistance_ohm_sq" in dq
    assert dq["sheet_resistance_ohm_sq"] > 0
    # Regression test for a Task 15 real-display finding: sheet_resistance()
    # (gui/services/process_derived.py) returns a bare numpy.float64, and a
    # numpy.float64 left inside a Slot(result="QVariant") dict does not
    # marshal to a JS number across the PySide6/QML boundary -- confirmed
    # with an isolated repro (QML saw typeof "object", stringifying to the
    # literal text "-1"), so DerivedQuantitiesPanel.qml's Math.round(value)
    # rendered "-1 Ω/□" on every step regardless of the real, correctly
    # computed resistance. A plain `> 0`/isinstance(..., float) check above
    # does NOT catch this: numpy.float64 subclasses Python's float, so
    # isinstance passes and the raw Python-side comparison is still `>0`
    # either way -- only the exact type (or an actual QML round-trip)
    # exposes it. `type(x) is float` is deliberately exact, not isinstance.
    assert type(dq["sheet_resistance_ohm_sq"]) is float, (
        f"sheet_resistance_ohm_sq is {type(dq['sheet_resistance_ohm_sq'])}, "
        "not a plain float -- will not marshal to a JS number in QML")

    assert "peak_concentration_cm3_P" in dq
    assert dq["peak_concentration_cm3_P"] > 0
    assert "peak_depth_um_P" in dq
    assert dq["peak_depth_um_P"] >= 0
    assert "implanted_dose_cm2_P" in dq
    # Implanted dose should recover the ~3e14 cm^-2 dose requested above
    # (activation/diffusion redistributes it in depth, not in total dose).
    assert dq["implanted_dose_cm2_P"] == pytest.approx(3e14, rel=0.2)

    # No oxidize step in this flow -- oxide bookkeeping keys must be absent.
    assert "oxide_thickness_um" not in dq
    assert "silicon_consumed_um" not in dq


def test_process_derived_quantities_includes_oxide_bookkeeping(qapp):
    app = AppController()
    app.addProcessStep("substrate", "Substrate",
                       {"length_cm": 3e-4, "background_doping_cm3": -1e16,
                        "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}})
    app.addProcessStep("oxidize", "Oxidize",
                       {"temperature_C": 1000.0, "time_hours": 0.5, "ambient": "dry"})
    assert app.runProcessValidation() is True, app.processValidationErrors

    loop = QEventLoop()
    app.processResultChanged.connect(loop.quit)
    app.errorRaised.connect(lambda s, d: (print("ERROR", s, d), loop.quit()))
    QTimer.singleShot(60000, loop.quit)
    app.runProcess()
    loop.exec()

    assert app.hasProcessResult is True, app.status
    final_id = app.process_flow.steps[-1].id
    dq = app.processDerivedQuantities(final_id)
    assert "oxide_thickness_um" in dq
    assert dq["oxide_thickness_um"] > 0
    assert "silicon_consumed_um" in dq
    assert dq["silicon_consumed_um"] > 0


def test_process_tree_node_shows_real_flow_info_not_the_stale_placeholder(qapp):
    """Final-review finding: the 'process' project-tree node used to
    return the stale v0.1 placeholder ('Process editing arrives in a
    later version') always, and was additionally masked by the
    self.spec is None guard for the common process-only-session case
    (no structure loaded, no device solved -- self.spec is legitimately
    None then). selectNode("process") must show real data derived from
    self.process_flow instead, even with self.spec still None."""
    app = AppController()
    assert app.spec is None
    rows = dict(app._properties_for("process"))
    assert rows.get("Status") == "No process steps yet"

    app.addProcessStep("substrate", "Substrate",
                       {"length_cm": 3e-4, "background_doping_cm3": -1e16,
                        "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}})
    app.addProcessStep("implant", "Implant",
                       {"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14, "tilt_deg": 7.0})
    rows = dict(app._properties_for("process"))
    assert rows.get("Steps") == "2"
    assert rows.get("Enabled steps") == "2"
    assert rows.get("Validation") == "OK"
    assert rows.get("Result") == "Not run yet"


def test_process_validation_error_format_matches_design_section_10(qapp):
    """design section 10's documented format: 'Step 03 -- Implant: <msg>'
    -- a 1-based flow index and the operation's display name, not the raw
    step uuid the code used to emit directly (`f"Step {e.object_id}"`)."""
    app = AppController()
    app.addProcessStep("substrate", "Substrate",
                       {"length_cm": 3e-4, "background_doping_cm3": -1e16,
                        "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}})
    app.addProcessStep("implant", "Implant", {"species": "B"})   # missing dose/energy
    assert app.runProcessValidation() is False
    errors = app.processValidationErrors
    assert any(e.startswith("Step 02 — Implant:") for e in errors), errors
    # And never the raw uuid-hex step id.
    bad_id = app.process_flow.steps[1].id
    assert not any(bad_id in e for e in errors), errors


def test_build_device_from_process_emits_structure_changed(qapp):
    """Final-review finding: buildDeviceFromProcess() cleared
    self.structure/self.mesh_model directly without emitting
    structureChanged, so QML bound to structureForQml/meshModelForQml
    (or anything reading structureMaterial/meshInfo) kept showing stale
    pre-clear data. Confirms the signal now fires as part of the clear."""
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    assert app.structure is not None

    app.addProcessStep("substrate", "Substrate",
                       {"length_cm": 3e-4, "background_doping_cm3": -1e16,
                        "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}})
    assert app.runProcessValidation() is True, app.processValidationErrors

    loop = QEventLoop()
    app.processResultChanged.connect(loop.quit)
    app.errorRaised.connect(lambda s, d: (print("ERROR", s, d), loop.quit()))
    QTimer.singleShot(60000, loop.quit)
    app.runProcess()
    loop.exec()
    assert app.hasProcessResult is True, app.status

    fired = []
    app.structureChanged.connect(lambda: fired.append(True))
    ok = app.buildDeviceFromProcess()
    assert ok is True
    assert app.structure is None
    assert app.mesh_model is None
    assert fired, "buildDeviceFromProcess() must emit structureChanged after clearing"


def test_on_process_failed_clears_a_previous_result(qapp):
    """Final-review finding: _on_process_failed did not clear
    self._process_result, so a run that fails after a previous
    successful run left the OLD ProcessResultStore reachable via
    hasProcessResult/_process_result, silently implying the failed run's
    (nonexistent) data was still current. Exercises the handler directly
    -- process_runner.py's own validation is identical to the GUI's
    (both call validate_flow()), so there is no way to construct a flow
    that passes GUI-side validation and still fails deterministically
    inside the real subprocess without introducing an unrelated bug; the
    cancellation test below instead proves the same clearing behavior
    through a real subprocess run."""
    app = AppController()

    class _FakeStore:
        def step_ids(self):
            return ["s1"]
    app._process_result = _FakeStore()
    assert app.hasProcessResult is True

    app._on_process_failed("boom", "traceback")
    assert app.hasProcessResult is False
    assert app._process_result is None


def test_cancel_after_a_successful_run_clears_the_stale_result(qapp):
    """Real end-to-end version of the same fix: run a flow to a real
    successful completion, then start and immediately cancel a second
    run, and confirm the FIRST run's result is no longer reachable
    (not just that the second run produced nothing)."""
    app = AppController()
    app.addProcessStep("substrate", "Substrate",
                       {"length_cm": 3e-4, "background_doping_cm3": -1e16,
                        "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}})
    app.addProcessStep("implant", "Implant",
                       {"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14})
    assert app.runProcessValidation() is True, app.processValidationErrors

    loop = QEventLoop()
    app.processResultChanged.connect(loop.quit)
    app.errorRaised.connect(lambda s, d: (print("ERROR", s, d), loop.quit()))
    QTimer.singleShot(60000, loop.quit)
    app.runProcess()
    loop.exec()
    assert app.hasProcessResult is True, app.status
    first_result = app._process_result

    loop2 = QEventLoop()
    app.busyChanged.connect(lambda: (not app.busy) and loop2.quit())
    QTimer.singleShot(15000, loop2.quit)
    app.runProcess()
    assert app.busy is True
    # The old result must already be gone the moment the new run started,
    # not just once it finishes/cancels.
    assert app.hasProcessResult is False
    assert app._process_result is not first_result
    app.cancelProcess()
    loop2.exec()

    assert app.busy is False
    assert app.hasProcessResult is False
    assert app._process_result is None


def test_cancel_process_resets_busy_and_leaves_no_result(qapp):
    """Regression test for a Task 15 real-display finding: AppController
    wired self._runner.canceled -> self._on_canceled for the device-solve
    JobRunner, but never connected self._process_runner.canceled to
    anything. A real windowed session showed the concrete consequence:
    calling cancelProcess() on a running flow left self._busy stuck True
    forever (no _on_process_canceled handler ever ran to reset it), which
    then silently blocked every subsequent runProcess() call (runProcess()
    no-ops when self._busy is already True) -- cancel didn't just leave
    stale UI, it wedged the whole Run feature for the rest of the session.
    """
    app = AppController()
    app.addProcessStep("substrate", "Substrate",
                       {"length_cm": 3e-4, "background_doping_cm3": -1e16,
                        "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}})
    app.addProcessStep("implant", "Implant",
                       {"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14})
    assert app.runProcessValidation() is True, app.processValidationErrors

    loop = QEventLoop()
    app.busyChanged.connect(lambda: (not app.busy) and loop.quit())
    QTimer.singleShot(15000, loop.quit)
    app.runProcess()
    assert app.busy is True
    app.cancelProcess()   # cancel essentially immediately, before it can finish
    loop.exec()

    assert app.busy is False, (
        "busy is stuck True -- _process_runner.canceled is not wired to "
        "a handler that resets it")
    assert app.hasProcessResult is False
    assert "canceled" in app.status.lower()

    # The real-world symptom: a stuck-busy controller silently swallows
    # every future run. Confirm a fresh run actually starts now.
    loop2 = QEventLoop()
    app.processResultChanged.connect(loop2.quit)
    app.errorRaised.connect(lambda s, d: (print("ERROR", s, d), loop2.quit()))
    QTimer.singleShot(60000, loop2.quit)
    app.runProcess()
    assert app.busy is True, "runProcess() no-opped -- busy never really cleared"
    loop2.exec()
    assert app.hasProcessResult is True, app.status
