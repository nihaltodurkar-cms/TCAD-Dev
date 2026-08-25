"""M6 UI slice (ARCHITECTURE.md roadmap): surface the backend's
per-region implant windows ("x_range_cm": [lo, hi], in cm) in the
ProcessPanel's ImplantEditor.  The window fields are micrometers --
process engineers think in um, the wire format in cm -- and an EMPTY
pair means "whole domain" (the parameter key is removed entirely,
byte-identical to pre-M6 flows).

Same headless pattern as test_structure_panels.py / test_sweep_panels.py.
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtCore import QMetaObject
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def _implant_editor(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    editor = root.findChild(object, "implantEditor")
    assert editor is not None, "missing implantEditor"
    base = {"species": "P", "energy_keV": 50.0, "dose_cm2": 1e13}
    controller.addProcessStep("implant", "Implant", dict(base))
    step_id = controller.process_flow.steps[-1].id
    # drive the editor directly: ProcessPanel binds parameters off its
    # own list-selection state, which needs a real click; the editor is
    # a plain QObject with writable controller/stepId/parameters props.
    editor.setProperty("stepId", step_id)
    editor.setProperty("parameters", dict(base))
    # NOTE every caller MUST keep the engine referenced for the whole
    # test -- dropping it lets GC destroy the QQmlApplicationEngine and
    # with it the entire QML item tree the wrappers point at.
    return engine, root, controller, editor, step_id


def test_window_fields_write_x_range_cm_in_cm(gapp):
    _engine, _, controller, editor, step_id = _implant_editor(gapp)
    editor.findChild(object, "implantWindowFromField").setProperty("text", "0.5")
    editor.findChild(object, "implantWindowToField").setProperty("text", "1.5")
    QMetaObject.invokeMethod(editor.findChild(
        object, "implantWindowApplyButton"), "clicked")

    params = controller.processStepParameters(step_id)
    rng = params.get("x_range_cm")
    assert rng is not None, "apply did not write x_range_cm"
    assert rng == pytest.approx([5e-5, 1.5e-4]), \
        f"window must land in cm, got {rng}"


def test_empty_window_removes_the_key_entirely(gapp):
    """Absent key == whole domain == byte-identical legacy flow.  The UI
    must REMOVE the key on an empty pair, not write [0, 0] or None."""
    _engine, _, controller, editor, step_id = _implant_editor(gapp)
    controller.setProcessStepParameters(step_id, dict(
        {"species": "P"}, x_range_cm=[0.0, 5e-5]))
    editor.setProperty("parameters",
                       controller.processStepParameters(step_id))
    editor.findChild(object, "implantWindowFromField").setProperty("text", "")
    editor.findChild(object, "implantWindowToField").setProperty("text", "")
    QMetaObject.invokeMethod(editor.findChild(
        object, "implantWindowApplyButton"), "clicked")

    assert "x_range_cm" not in controller.processStepParameters(step_id)


def test_garbage_window_is_rejected_and_fields_revert(gapp):
    """A non-numeric entry must not reach the flow at all -- NaN cannot
    travel through JSON -- and both fields snap back to the LIVE
    parameter values (same revert contract as SweepPanel's arm)."""
    _engine, _, controller, editor, step_id = _implant_editor(gapp)
    controller.setProcessStepParameters(step_id, dict(
        {"species": "P"}, x_range_cm=[1e-4, 2e-4]))
    editor.setProperty("parameters",
                       controller.processStepParameters(step_id))
    editor.findChild(object, "implantWindowFromField").setProperty("text", "abc")
    editor.findChild(object, "implantWindowToField").setProperty("text", "")
    QMetaObject.invokeMethod(editor.findChild(
        object, "implantWindowApplyButton"), "clicked")

    # flow untouched
    assert controller.processStepParameters(step_id)["x_range_cm"] == \
        pytest.approx([1e-4, 2e-4])
    # fields reverted to the live values, in um
    frm = float(editor.findChild(
        object, "implantWindowFromField").property("text"))
    to = float(editor.findChild(
        object, "implantWindowToField").property("text"))
    assert (frm, to) == pytest.approx((1.0, 2.0))


def test_window_survives_the_real_validation_roundtrip(gapp):
    """The written window must be accepted by validate_flow and survive
    a full JSON round-trip of the flow (the wire-format gate)."""
    import json
    from gui.services.process_model import ProcessFlow, validate_flow
    _engine, _, controller, editor, step_id = _implant_editor(gapp)
    # validate_flow demands an enabled substrate FIRST (as any real flow
    # would have); add one at the top so the gate below sees a legal flow
    controller.addProcessStep("substrate", "Substrate", {
        "length_cm": 1e-3, "background_doping_cm3": 1e15,
        "mesh": {"h_min_cm": 1e-7, "h_max_cm": 1e-5, "ratio": 1.2}})
    sub_id = controller.process_flow.steps[-1].id
    controller.moveProcessStep(sub_id, -2)   # implant(0), substrate(1) -> front
    assert [s.operation for s in controller.process_flow.steps][0] == "substrate"
    editor.findChild(object, "implantWindowFromField").setProperty("text", "0")
    editor.findChild(object, "implantWindowToField").setProperty("text", "10")
    QMetaObject.invokeMethod(editor.findChild(
        object, "implantWindowApplyButton"), "clicked")

    flow = controller.process_flow
    assert validate_flow(flow) == []
    restored = ProcessFlow.from_dict(json.loads(json.dumps(flow.to_dict())))
    implant = next(s for s in restored.steps if s.operation == "implant")
    assert implant.parameters["x_range_cm"] == pytest.approx([0.0, 1e-3])
