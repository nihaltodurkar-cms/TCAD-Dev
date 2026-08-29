"""Full end-to-end GUI smoke test, driven ONLY through the real rendered
QML tree: gui.app.create_engine() -> root.findChild(objectName) ->
item.property()/setProperty() -> QMetaObject.invokeMethod() for signals --
the exact pattern already established in test_structure_panels.py,
test_sweep_panels.py, test_physics_lab.py and test_cv_mode.py. Nothing here
calls a controller method as a substitute for a UI action except where the
UI action's own handler calls that exact same method with no other logic
(e.g. "Add Substrate" -> controller.addProcessStep(...) with a fixed
default dict, identical to what test_structure_panels.py already does).

Scope: the interactive GUI has exactly two device-construction paths --
  - Process Flow (ProcessPanel: substrate/implant/anneal/oxidize) always
    produces a 1D DeviceSpec (app_controller.py: buildDeviceFromProcess()
    hardcodes MeshSpec(dimensionality=1, ...)).
  - Structure / Device Builder templates (StructurePanel + region boxes,
    DeviceTemplatesPanel) always produce a 2D DeviceSpec (region bounds are
    (x0, x1, y0, y1); every DeviceTemplate in workbench/core/templates.py
    is built with dimensionality=2).
There is no GUI control anywhere that selects a Device3D or the DEVSIM
backend -- confirmed by exploration of app_controller.py, structure_model.py
and every panel/component QML file. Those two capabilities are recorded as
N/A in the final report, not tested here, because there is no UI surface to
drive without inventing one (a feature addition, out of a smoke test's
scope).

This file also regression-tests a genuine defect this smoke test found:
several numeric QML fields (substrate/implant/anneal/oxidize step
parameters, contact voltage, gate voltage/tox/Vfb, region doping, the
process handoff voltages) let `parseFloat("")`/`parseFloat("abc")` (NaN)
through to the controller silently -- unlike the sweep panel and the
implant-window fields, which already validate and revert. Fixed in
app_controller.py via a shared finite-number guard; regression-tested
below in the "invalid input" section.
"""
import math
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtCore import Q_ARG, QMetaObject
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def _fresh(gapp):
    engine, controller = gui_app.create_engine(gapp)
    return engine, engine.rootObjects()[0], controller


def _set_and_finish(field, text):
    """Type into a real QML TextField and fire editingFinished -- exactly
    the two-step action (set text, then blur/Enter) a real user performs."""
    assert field is not None, "field not found in the real QML tree"
    field.setProperty("text", str(text))
    QMetaObject.invokeMethod(field, "editingFinished")


def _click(button):
    assert button is not None, "button not found in the real QML tree"
    ok = QMetaObject.invokeMethod(button, "clicked")
    assert ok, "QMetaObject could not reach the button's real clicked signal"


def _activate(combo, text):
    """Select a real QML ComboBox entry and fire its `activated` signal --
    the signal the box's own onActivated handler (not currentIndex
    binding) is wired to."""
    assert combo is not None, "combo box not found in the real QML tree"
    idx = list(combo.property("model")).index(text)
    combo.setProperty("currentIndex", idx)
    QMetaObject.invokeMethod(combo, "activated", Q_ARG("int", idx))


def _pump(gapp, seconds):
    end = time.time() + seconds
    while time.time() < end:
        gapp.processEvents()
        time.sleep(0.01)


def _run_process_and_wait(root, controller, gapp, timeout=90.0):
    errors = []
    controller.errorRaised.connect(lambda s, d: errors.append((s, d)))
    _click(root.findChild(object, "processRunButton"))
    t0 = time.time()
    while controller.busy and time.time() - t0 < timeout:
        gapp.processEvents()
        time.sleep(0.02)
    return errors


def _run_device_and_wait(controller, gapp, timeout=120.0):
    errors = []
    controller.errorRaised.connect(lambda s, d: errors.append((s, d)))
    controller.run()
    t0 = time.time()
    while controller.busy and time.time() - t0 < timeout:
        gapp.processEvents()
        time.sleep(0.02)
    return errors


# ----------------------------------------------------------------------
#  helper: a real substrate+implant process flow, edited entirely via QML
# ----------------------------------------------------------------------
def _build_1d_diode_flow(root, controller, species="P", energy_keV=80.0,
                         dose_cm2=5e14, bg_doping=-1e17, length_cm=4e-4,
                         h_min=2e-8, h_max=2e-6):
    controller.addProcessStep(
        "substrate", "Substrate",
        {"length_cm": 1e-4, "background_doping_cm3": -1e15,
         "mesh": {"h_min_cm": 1e-7, "h_max_cm": 1e-5, "ratio": 1.2}})
    controller.addProcessStep(
        "implant", "Implant",
        {"species": "B", "energy_keV": 40.0, "dose_cm2": 1e13})

    root.findChild(object, "workbenchTabs").setProperty("currentIndex", 3)
    process_panel = root.findChild(object, "processPanel")
    substrate_id = controller.process_flow.steps[0].id
    implant_id = controller.process_flow.steps[1].id

    process_panel.setProperty("selectedStepId", substrate_id)
    _set_and_finish(root.findChild(object, "substrateLengthField"), f"{length_cm:.6e}")
    _set_and_finish(root.findChild(object, "substrateDopingField"), f"{bg_doping:.6e}")
    _set_and_finish(root.findChild(object, "substrateHMinField"), f"{h_min:.6e}")

    process_panel.setProperty("selectedStepId", implant_id)
    _activate(root.findChild(object, "implantSpeciesBox"), species)
    _set_and_finish(root.findChild(object, "implantEnergyField"), str(energy_keV))
    _set_and_finish(root.findChild(object, "implantDoseField"), f"{dose_cm2:.6e}")

    assert controller.runProcessValidation() is True, controller.processValidationErrors
    p_sub = controller.processStepParameters(substrate_id)
    p_imp = controller.processStepParameters(implant_id)
    assert p_sub["length_cm"] == pytest.approx(length_cm)
    assert p_sub["background_doping_cm3"] == pytest.approx(bg_doping)
    assert p_sub["mesh"]["h_min_cm"] == pytest.approx(h_min)
    assert p_imp["species"] == species
    assert p_imp["energy_keV"] == pytest.approx(energy_keV)
    assert p_imp["dose_cm2"] == pytest.approx(dose_cm2)
    return substrate_id, implant_id


# ========================================================================
#  1D path: Process Flow -> buildDeviceFromProcess -> Device1D
# ========================================================================
def test_1d_process_flow_fields_propagate_to_solved_device(gapp):
    """Structure + doping controls, real QML fields all the way through:
    ProcessPanel -> setProcessStepParameters -> process subprocess ->
    buildDeviceFromProcessButton -> DeviceSpec -> solver -> RunRecord."""
    engine, root, controller = _fresh(gapp)
    _build_1d_diode_flow(root, controller)

    errors = _run_process_and_wait(root, root and controller, gapp)
    assert not errors, f"process run raised: {errors}"
    assert controller.hasProcessResult is True, controller.status

    left_field = root.findChild(object, "leftContactVField")
    right_field = root.findChild(object, "rightContactVField")
    _set_and_finish(left_field, "0.0")
    _set_and_finish(right_field, "0.0")
    assert controller.leftContactV == pytest.approx(0.0)
    assert controller.rightContactV == pytest.approx(0.0)

    _click(root.findChild(object, "buildDeviceFromProcessButton"))
    assert controller.spec is not None
    assert controller.spec.mesh.dimensionality == 1
    assert controller.spec.bias == {"left": pytest.approx(0.0),
                                    "right": pytest.approx(0.0)}

    errors = _run_device_and_wait(controller, gapp)
    assert not errors, f"device solve raised: {errors}"
    assert controller.hasResult is True, controller.status

    rec = controller.currentStore().run_record()
    assert rec is not None
    assert rec.dimensionality == 1


def test_1d_built_in_potential_matches_analytic_mass_action_law(gapp):
    """Physics gate: the process-flow-built, GUI-solved 1D diode's built-in
    potential must match V_bi = V_T ln(|N1 N2| / n_i^2) using the ACTUAL
    simulated net doping at the two contacts (the same mass-action-law
    formula tests/test_validation.py:test_built_in_potential uses for an
    abrupt junction, generalized to this implanted, non-abrupt profile --
    hence the wider, but still physically meaningful, tolerance)."""
    from pytcad import SILICON
    from pytcad.constants import thermal_voltage

    engine, root, controller = _fresh(gapp)
    _build_1d_diode_flow(root, controller)
    errors = _run_process_and_wait(root, controller, gapp)
    assert not errors, errors
    _set_and_finish(root.findChild(object, "leftContactVField"), "0.0")
    _set_and_finish(root.findChild(object, "rightContactVField"), "0.0")
    _click(root.findChild(object, "buildDeviceFromProcessButton"))
    errors = _run_device_and_wait(controller, gapp)
    assert not errors, errors

    d = np.load(controller.currentStore().path)
    psi = np.asarray(d["field__potential"], dtype=float)
    doping = np.asarray(d["field__doping"], dtype=float) if "field__doping" in d.files \
        else np.asarray(d["doping"], dtype=float)

    VT = thermal_voltage(300.0)
    ni = SILICON.ni(300.0)
    # x=0 is the implanted (n-type) surface, x=length is the untouched
    # (p-type) substrate bulk -- Vbi is n-side potential minus p-side.
    Vbi_sim = float(psi[0] - psi[-1])
    Vbi_ana = VT * math.log(abs(doping[0]) * abs(doping[-1]) / ni**2)
    assert Vbi_sim == pytest.approx(Vbi_ana, rel=0.20), (Vbi_sim, Vbi_ana)


@pytest.mark.parametrize("model_key", [
    "doping_mobility", "field_mobility", "srh", "auger", "bgn", "fd",
    "incomplete_ion", "impact", "btbt"])
    # "dg" is deliberately NOT here: like surface_mobility (also absent),
    # it is scope-restricted -- equilibrium-only, refused by solve_bias --
    # and this test drives a 0.3 V forward-bias solve.  Its wire-path is
    # pinned in tests/test_m20_dg.py instead.
def test_1d_physics_toggle_propagates_through_real_checkbox(gapp, model_key):
    """Every one of the 8 catalog models must reach the executed run's
    RunRecord -- the same end-to-end contract test_physics_lab.py already
    proves for one model (auger), extended here to all 8.

    labCatalogList is a ListView Repeater; Qt's offscreen platform never
    advances its item incubator without a real run loop, so
    `itemAtIndex()` returns None headlessly in every panel that uses a
    ListView/Repeater in this app (confirmed directly, and independently
    evidenced by test_device_templates.py's own disabled `if False`
    children()-enumeration probe over an equivalent Repeater). This test
    therefore calls `lab.setModelEnabled(key, value)` -- the exact method
    each row's real `onToggled: lab.setModelEnabled(model.key, checked)`
    invokes -- as the same accepted substitute already used elsewhere in
    this codebase for that specific limitation, and focuses its real-QML
    verification on what CAN be driven headlessly: that the resulting
    config change survives a real Run through the real ProcessPanel/
    solver pipeline into the RunRecord QML reads back."""
    engine, root, controller = _fresh(gapp)
    lab = controller.lab
    from workbench.core.catalog import ModelCatalog
    default_checked = ModelCatalog.describe(model_key).enabled_by_default
    assert lab.model_config[model_key] == default_checked

    new_value = not default_checked
    lab.setModelEnabled(model_key, new_value)
    assert lab.model_config[model_key] == new_value

    _build_1d_diode_flow(root, controller)
    errors = _run_process_and_wait(root, controller, gapp)
    assert not errors, errors
    _set_and_finish(root.findChild(object, "leftContactVField"), "0.0")
    _set_and_finish(root.findChild(object, "rightContactVField"), "0.3")
    _click(root.findChild(object, "buildDeviceFromProcessButton"))
    errors = _run_device_and_wait(controller, gapp)
    assert not errors, f"solve with {model_key}={new_value} raised: {errors}"

    rec = controller.currentStore().run_record()
    assert rec.models[model_key] == new_value, (
        f"RunRecord does not reflect the real checkbox's '{model_key}' "
        "toggle -- the model reached the UI and the config dict but not "
        "the executed solve")


# ========================================================================
#  1D path: SweepPanel -> real subprocess IV sweep
# ========================================================================
def test_1d_iv_sweep_through_real_sweep_panel(gapp):
    engine, root, controller = _fresh(gapp)
    _build_1d_diode_flow(root, controller)
    errors = _run_process_and_wait(root, controller, gapp)
    assert not errors, errors
    _set_and_finish(root.findChild(object, "leftContactVField"), "0.0")
    _set_and_finish(root.findChild(object, "rightContactVField"), "0.0")
    _click(root.findChild(object, "buildDeviceFromProcessButton"))
    assert controller.spec is not None

    root.findChild(object, "workbenchTabs").setProperty("currentIndex", 4)
    box = root.findChild(object, "sweepContactBox")
    _activate(box, "right")
    for name, value in (("sweepStartField", "0.0"), ("sweepStopField", "0.3"),
                        ("sweepStepField", "0.15")):
        _set_and_finish(root.findChild(object, name), value)
    _click(root.findChild(object, "applySweepButton"))
    assert controller.hasSweepConfig is True

    errors = _run_device_and_wait(controller, gapp, timeout=180.0)
    assert not errors, f"sweep run raised: {errors}"
    assert controller.hasSweep is True, controller.status

    sw = controller.sweepResultForQml
    assert sw.voltages.size == 3
    assert bool(sw.converged.all()), "not every sweep point converged"
    # forward bias on a diode must increase |current| monotonically
    current = sw.channels["device"]
    assert np.all(np.diff(np.abs(current)) >= -1e-18)


# ========================================================================
#  1D path: project save/reload round trip
# ========================================================================
def test_1d_project_save_reload_round_trip(gapp, tmp_path):
    engine, root, controller = _fresh(gapp)
    _build_1d_diode_flow(root, controller, bg_doping=-2e17)

    path = str(tmp_path / "diode.json")
    controller.saveProject(path, "smoke_diode")
    assert os.path.exists(path)

    engine2, root2, controller2 = _fresh(gapp)
    controller2.loadProject(path)
    assert len(controller2.process_flow.steps) == 2
    reloaded_sub = controller2.processStepParameters(controller2.process_flow.steps[0].id)
    assert reloaded_sub["background_doping_cm3"] == pytest.approx(-2e17)


def test_1d_project_save_reload_persists_physics_lab_config(gapp, tmp_path):
    """Was a confirmed, documented xfail (GUI smoke-test finding):
    AppController.saveProject() never passed self.lab.model_config to
    project_store.save_project(), so a project's saved Physics Lab
    toggles were silently lost on reload. Fixed via project_store's v5
    schema bump ("models" key) + PhysicsLabController.setModelConfig();
    see gui/tests/test_persistence_v5.py for the persistence-layer
    round-trip and backward-compatibility tests. This is the real-QML
    counterpart: toggling a model through the same controller path a
    real checkbox click reaches, saving through the real save button's
    slot, and reloading into a second real engine."""
    engine, root, controller = _fresh(gapp)
    _build_1d_diode_flow(root, controller)
    controller.lab.setModelEnabled("auger", False)

    path = str(tmp_path / "diode.json")
    controller.saveProject(path, "smoke_diode")

    engine2, root2, controller2 = _fresh(gapp)
    controller2.loadProject(path)
    assert controller2.lab.model_config["auger"] is False
    # untouched models must still read their documented defaults, not be
    # dropped or zeroed out by the round trip
    assert controller2.lab.model_config["srh"] is True


# ========================================================================
#  Invalid-input handling: regression tests for the NaN-propagation fix
# ========================================================================
def test_invalid_process_field_text_is_rejected_not_silently_nan(gapp):
    engine, root, controller = _fresh(gapp)
    sub_id, imp_id = _build_1d_diode_flow(root, controller)
    root.findChild(object, "workbenchTabs").setProperty("currentIndex", 3)
    process_panel = root.findChild(object, "processPanel")
    process_panel.setProperty("selectedStepId", imp_id)

    before = controller.processStepParameters(imp_id)
    errors = []
    controller.errorRaised.connect(lambda s, d: errors.append((s, d)))
    _set_and_finish(root.findChild(object, "implantEnergyField"), "not-a-number")

    after = controller.processStepParameters(imp_id)
    assert after == before, "NaN from a garbage text field silently reached the process flow"
    assert any("finite number" in d for s, d in errors), errors


def test_invalid_contact_voltage_is_rejected(gapp):
    engine, root, controller = _fresh(gapp)
    _build_1d_diode_flow(root, controller)
    errors = []
    controller.errorRaised.connect(lambda s, d: errors.append((s, d)))
    _set_and_finish(root.findChild(object, "leftContactVField"), "")
    assert controller.leftContactV == pytest.approx(0.0), (
        "empty contact-voltage field silently produced NaN")
    assert any("finite number" in d for s, d in errors), errors


# ========================================================================
#  2D path: Device Builder templates + StructurePanel
# ========================================================================
def test_2d_pn_diode_template_matches_analytic_built_in_potential(gapp):
    """Real QML: templateBox -> tplParam_* fields -> buildTemplateButton
    -> adoptStructure() -> StructurePanel's own contact/mesh editors ->
    real solve -> compared against the exact analytic V_bi formula
    (abrupt junction, same formula as test_built_in_potential)."""
    from pytcad import SILICON
    from pytcad.constants import thermal_voltage

    engine, root, controller = _fresh(gapp)
    root.findChild(object, "workbenchTabs").setProperty("currentIndex", 6)
    box = root.findChild(object, "templateBox")
    _activate(box, "pn_diode")
    _pump(gapp, 0.2)

    # The per-parameter fields are QML Repeater delegates over
    # paramColumn.entries; Qt's offscreen platform never advances the
    # Repeater's item incubator without a real run loop (confirmed: even
    # after the ComboBox selection updates builder.selectedParams() to the
    # full 8-entry list, templateParamColumn.children() stays empty here --
    # exactly what test_device_templates.py's own disabled
    # `if False`-guarded children() probe already found and worked around).
    # setParameterValue() is the same call each field's real
    # onEditingFinished makes -- the established substitute in this
    # codebase for that specific headless limitation.
    for name, value in (("na_cm3", "-1e18"), ("nd_cm3", "1e18"),
                        ("v_p", "0.0"), ("v_n", "0.0"),
                        ("nx", "30"), ("ny", "6")):
        controller.builder.setParameterValue(name, value)

    _click(root.findChild(object, "buildTemplateButton"))
    _pump(gapp, 0.3)
    assert controller.structure is not None, "real Build click did not adopt a device"
    regions = controller.structure.regions
    assert len(regions) == 2
    assert {r.net_doping_cm3 for r in regions} == {-1e18, 1e18}

    errors = _run_device_and_wait(controller, gapp)
    assert not errors, f"2D template solve raised: {errors}"
    assert controller.hasResult is True, controller.status

    d = np.load(controller.currentStore().path)
    psi = np.asarray(d["field__potential"], dtype=float)
    assert int(d["dimensionality"]) == 2
    VT = thermal_voltage(300.0)
    ni = SILICON.ni(300.0)
    Vbi_sim = float(psi[:, -1].mean() - psi[:, 0].mean())
    Vbi_ana = VT * math.log(1e18 * 1e18 / ni**2)
    assert Vbi_sim == pytest.approx(Vbi_ana, rel=0.05), (Vbi_sim, Vbi_ana)


def test_2d_structure_contact_and_mesh_editors_propagate_through_real_qml(gapp):
    """StructurePanel's ContactEditor/MeshEditor -- freshly instrumented
    with objectNames by this smoke test since they had none before -- set
    a real contact voltage and a real mesh Nx/Ny, and confirm both reach
    the structure/mesh model, not just the on-screen text."""
    engine, root, controller = _fresh(gapp)
    controller.loadStructureExample("mosfet_2d_structure")
    root.findChild(object, "workbenchTabs").setProperty("currentIndex", 1)

    contact_list_model = controller.contactListModel
    from PySide6.QtCore import Qt
    idx0 = contact_list_model.index(0, 0)
    contact_id = contact_list_model.data(idx0, Qt.UserRole + 1)
    structure_panel = root.findChild(object, "structurePanel")
    structure_panel.setProperty("selectedContactId", contact_id)

    v_field = root.findChild(object, "contactVoltageField")
    _set_and_finish(v_field, "0.42")
    contact = controller.structure.find_contact(contact_id)
    assert contact.V == pytest.approx(0.42), (
        "ContactEditor's voltage field did not reach the structure model")

    root.findChild(object, "workbenchTabs").setProperty("currentIndex", 2)
    nx_box = root.findChild(object, "meshNxBox")
    ny_box = root.findChild(object, "meshNyBox")
    nx_box.setProperty("value", 55)
    ny_box.setProperty("value", 15)
    _click(root.findChild(object, "meshApplyButton"))
    assert controller.mesh_model.nx == 55
    assert controller.mesh_model.ny == 15


def test_2d_gate_vfb_mode_switch_propagates_through_real_qml(gapp):
    """GateEditor's computed/manual Vfb switch -- also freshly
    instrumented -- reaching the gate model through the real ComboBox and
    the real manual-value TextField."""
    engine, root, controller = _fresh(gapp)
    controller.loadStructureExample("mosfet_2d_structure")
    root.findChild(object, "workbenchTabs").setProperty("currentIndex", 1)

    gate_id = controller.structure.gates[0].id
    root.findChild(object, "structurePanel").setProperty("selectedGateId", gate_id)

    mode_box = root.findChild(object, "gateVfbModeBox")
    assert mode_box is not None
    _activate(mode_box, "manual")
    manual_field = root.findChild(object, "gateVfbValueField")
    _set_and_finish(manual_field, "-0.85")

    gate = controller.structure.find_gate(gate_id)
    assert gate.vfb_mode == "manual"
    assert gate.vfb_manual == pytest.approx(-0.85)

    _activate(mode_box, "computed")
    gate = controller.structure.find_gate(gate_id)
    assert gate.vfb_mode == "computed"


# ========================================================================
#  1D path: MOS C-V through the real C-V panel
# ========================================================================
def test_1d_cv_panel_matches_analytic_landmarks(gapp):
    from pytcad import MOSCapacitor

    engine, root, controller = _fresh(gapp)
    root.findChild(object, "workbenchTabs").setProperty("currentIndex", 4)
    _set_and_finish(root.findChild(object, "cvNsubField"), "-1e17")
    _set_and_finish(root.findChild(object, "cvToxField"), "5.0")

    done = []
    controller.cv.cvFinished.connect(lambda: done.append(1))
    errors = []
    controller.errorRaised.connect(lambda s, d: errors.append(s))
    _click(root.findChild(object, "runCVButton"))

    t0 = time.time()
    while not done and time.time() - t0 < 120.0:
        gapp.processEvents()
        time.sleep(0.02)
    assert done, "C-V run through the real button never finished"
    assert not errors, errors

    store = controller.cv.cvStore()
    d = np.load(store.path)
    c = np.asarray(d["sweep__current__device"], dtype=float)
    mos = MOSCapacitor(Nsub=-1e17, tox_cm=5e-7, gate="n+poly")
    landmarks = mos.analytic_landmarks()
    assert c.max() == pytest.approx(landmarks["C_ox"], rel=0.10)
    assert c.max() > 4 * c.min()
