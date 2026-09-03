"""M4 acceptance tests: Physics Lab foundation (ARCHITECTURE.md M4).

Contract under test:
  - The lab surfaces the REAL ModelCatalog (5 models, documented
    equations/references) through QML-bindable models -- nothing faked.
  - Toggling a model goes through catalog validation and reaches the
    executed solve: the M2 RunRecord of the next run reports the changed
    config. Defaults equal the wire-format defaults, so untouched runs
    behave exactly as before.
  - The convergence history recorded by M2 is plottable: the viewport's
    "convergence" mode receives real trace data and renders; pre-v2 /
    absent records degrade to an honest placeholder.
"""
import json, os, sys, time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtCore import Q_ARG, Qt
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def _fresh(gapp):
    engine, controller = gui_app.create_engine(gapp)
    return engine, engine.rootObjects()[0], controller


def _catalog_rows(model):
    rows = []
    for r in range(model.rowCount()):
        i = model.index(r, 0)
        rows.append({
            "key": str(model.data(i, Qt.UserRole + 1)),
            "title": str(model.data(i, Qt.UserRole + 2)),
            "enabled": model.data(i, Qt.UserRole + 3),
            "equations": str(model.data(i, Qt.UserRole + 4)),
            "references": str(model.data(i, Qt.UserRole + 5)),
        })
    return rows


# ----------------------------------------------------------------------
#  catalog reflection
# ----------------------------------------------------------------------
def test_panel_present_with_full_catalog(gapp):
    engine, root, ctl = _fresh(gapp)
    assert root.findChild(object, "physicsLabPanel") is not None
    lab = ctl.lab
    rows = _catalog_rows(lab.catalogModel)
    assert [r["key"] for r in rows] == sorted(
        ["doping_mobility", "field_mobility", "srh", "auger", "bgn",
         "tat", "fd", "incomplete_ion", "impact", "btbt",
         "surface_mobility", "dg"])
    assert all(r["enabled"] == (r["key"] not in
                                ("field_mobility", "tat", "fd",
                                 "incomplete_ion",
                                 "impact", "btbt",
                                 "surface_mobility", "dg")) for r in rows)
    caughey = next(r for r in rows if r["key"] == "doping_mobility")
    assert "Caughey" in caughey["references"]


def test_selected_model_detail_carries_equations_and_limitations(gapp):
    engine, root, ctl = _fresh(gapp)
    lab = ctl.lab
    lab.selectModel("field_mobility")
    d = lab.selectedDetail()
    assert any("Canali" in ref for ref in d["references"])
    assert "NotImplementedError" in d["limitations"]
    lab.selectModel("nope")
    assert lab.selectedDetail() is None


# ----------------------------------------------------------------------
#  validation + error surfacing
# ----------------------------------------------------------------------
def test_invalid_toggle_is_rejected_and_reported(gapp):
    engine, root, ctl = _fresh(gapp)
    lab = ctl.lab
    errs = []
    lab.labError.connect(errs.append)

    lab.setModelEnabled("quantum_tunneling", True)
    lab.setModelEnabled("srh", "yes")
    assert errs and len(errs) == 2
    assert lab.model_config["srh"] is True          # unchanged


# ----------------------------------------------------------------------
#  end-to-end: toggle reaches the executed run's RunRecord
# ----------------------------------------------------------------------
def test_toggle_changes_next_run_record(gapp):
    engine, root, ctl = _fresh(gapp)
    lab = ctl.lab
    ctl.loadExample("mosfet_2d"); pump = lambda s: None

    lab.setModelEnabled("auger", False)
    assert lab.model_config["auger"] is False

    loop_done = []
    t0 = time.time()
    ctl.run()
    while ctl.busy and time.time() - t0 < 300:
        gapp.processEvents(); time.sleep(0.02)
    assert not ctl.busy and ctl.hasResult

    rec = ctl.currentStore().run_record()
    assert rec is not None
    assert rec.models["auger"] is False
    assert rec.models["srh"] is True                # untouched flag intact

    # restore and prove it flips back
    lab.setModelEnabled("auger", True)
    assert lab.model_config["auger"] is True


def test_defaults_match_wire_format_until_touched(gapp):
    from gui.services.device_spec import _default_models
    from workbench.core.catalog import ModelCatalog
    engine, root, ctl = _fresh(gapp)
    assert ctl.lab.model_config == _default_models()
    assert ModelCatalog.default_config() == _default_models()


# ----------------------------------------------------------------------
#  convergence history through the viewport
# ----------------------------------------------------------------------
def _wait_run(ctl, gapp):
    t0 = time.time()
    ctl.run()
    while ctl.busy and time.time() - t0 < 300:
        gapp.processEvents(); time.sleep(0.02)


def test_convergence_data_from_real_run(gapp):
    engine, root, ctl = _fresh(gapp)
    lab = ctl.lab
    assert lab.hasRunRecord() is False              # nothing solved yet
    assert lab.convergenceData() is None

    ctl.loadExample("mosfet_2d")
    _wait_run(ctl, gapp)
    assert lab.hasRunRecord() is True

    data = lab.convergenceData()
    stages = [d["stage"] for d in data]
    assert "equilibrium" in stages
    eq = next(d for d in data if d["stage"] == "equilibrium")
    assert len(eq["residuals"]) >= 1 and min(eq["residuals"]) > 0

    # the viewport's convergence mode renders it
    vp = root.findChild(object, "viewportPanel")
    from PySide6.QtCore import QMetaObject
    vp.setProperty("currentMode", "")
    QMetaObject.invokeMethod(vp, "setViewMode", Q_ARG("QVariant", "convergence"))
    pump_ui(gapp, 0.6)
    canvas = [o for o in root.findChildren(object)
              if o.metaObject().className().startswith("MplCanvas")][0]
    img = canvas.renderToImage()
    assert not img.isNull()


def pump_ui(gapp, sec):
    end = time.time() + sec
    while time.time() < end:
        gapp.processEvents(); time.sleep(0.01)


def test_view_mode_selector_offers_convergence(gapp):
    engine, root, _ = _fresh(gapp)
    selector = root.findChild(object, "viewModeSelector")
    assert "Convergence" in list(selector.property("model"))


def test_provenance_rows_after_real_run(gapp):
    engine, root, ctl = _fresh(gapp)
    lab = ctl.lab
    assert lab.provenanceRows() is None          # nothing solved yet
    ctl.loadExample("mosfet_2d")
    _wait_run(ctl, gapp)
    rows = dict(lab.provenanceRows())
    assert rows["Backend"] == "pytcad"
    assert any(k.startswith("model:") for k in rows)


# ----------------------------------------------------------------------
# GUI-IMPROVEMENT-PLAN.md Phase 1c: equilibrium-only Run mode for dg
# ----------------------------------------------------------------------
def _diode_1d_spec():
    """A minimal 1D diode DeviceSpec -- same shape as
    test_family_sweep.py's _diode_base_spec(), reused here rather than
    imported across test files (no shared test-fixture module exists
    yet for this small a spec)."""
    from gui.services.device_spec import (
        ContactSpec, DeviceSpec, DopingSpec, MeshSpec,
    )
    x = np.linspace(0.0, 2e-4, 40)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
                  ContactSpec(name="right", kind="ohmic",
                              nodes={"i": [x.size - 1]}, V=0.0)],
        bias={"left": 0.0, "right": 0.3})


def test_dg_with_equilibrium_only_runs_without_the_solve_bias_refusal(gapp):
    """Before this mode existed, dg=True + Run always crashed: every
    Run path attaches a bias dict, and Device1D.solve_bias refuses
    dg=True unconditionally (M20 is equilibrium-only). This is the
    first GUI-reachable path to the already-landed M20 physics."""
    engine, root, ctl = _fresh(gapp)
    lab = ctl.lab
    ctl.spec = _diode_1d_spec()
    lab.setModelEnabled("dg", True)
    lab.setEquilibriumOnly(True)
    assert lab.equilibriumOnly is True

    errors = []
    ctl.errorRaised.connect(lambda s, d: errors.append((s, d)))
    _wait_run(ctl, gapp)

    assert not errors, f"equilibrium-only dg run raised: {errors}"
    assert ctl.hasResult, ctl.status
    store = ctl.currentStore()
    assert bool(store._d["solved_bias"]) is False, \
        "equilibrium-only must not have run a bias solve"
    rec = store.run_record()
    assert rec.models["dg"] is True


def test_dg_without_equilibrium_only_still_refuses_on_bias(gapp):
    """Regression: the new mode must not accidentally make dg=True
    silently safe for an ordinary biased Run -- the M20 scope limit
    (equilibrium-only) must still be enforced when the toggle is off."""
    engine, root, ctl = _fresh(gapp)
    lab = ctl.lab
    ctl.spec = _diode_1d_spec()
    lab.setModelEnabled("dg", True)
    assert lab.equilibriumOnly is False

    errors = []
    ctl.errorRaised.connect(lambda s, d: errors.append((s, d)))
    _wait_run(ctl, gapp)

    assert not ctl.hasResult
    assert errors, "a biased dg=True run must still fail"
    assert any("solve_bias" in d or "equilibrium-only" in d
               for _s, d in errors), errors


def test_equilibrium_only_refuses_to_combine_with_an_armed_sweep(gapp):
    """A sweep always overrides the bias branch regardless of spec.bias
    (_solve_all checks spec.sweep first) -- equilibrium-only would be
    silently ineffective, not safely inert, if combined with a sweep.
    Caught before the subprocess starts, with an actionable message."""
    engine, root, ctl = _fresh(gapp)
    lab = ctl.lab
    ctl.spec = _diode_1d_spec()
    lab.setEquilibriumOnly(True)
    ctl.setSweepConfig("left", 0.0, 0.3, 0.1)

    errors = []
    ctl.errorRaised.connect(lambda s, d: errors.append(s))
    ctl.run()
    assert errors and "sweep" in errors[0].lower()
    assert not ctl.busy
