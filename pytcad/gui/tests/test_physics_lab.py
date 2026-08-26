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
         "fd", "incomplete_ion"])
    assert all(r["enabled"] == (r["key"] not in
                                ("field_mobility", "fd",
                                 "incomplete_ion")) for r in rows)
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
