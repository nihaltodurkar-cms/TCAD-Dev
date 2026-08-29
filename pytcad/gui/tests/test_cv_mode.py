"""C-V analysis mode: the core's validated MOSCapacitor.cv_sweep wired
through the standard job -> subprocess -> schema-v2 npz -> ResultStore
pipeline.  The curve appears in Curves mode with honest units (F/cm^2)
and is gated against the capacitor's own analytic landmarks.
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


CV_PARAMS = {
    "nsub_cm3": -1e17,
    "tox_nm": 5.0,
    "gate": "n+poly",
    "qf_cm2": 1e12,
    "T": 300.0,
    "vstart": -2.0,
    "vstop": 2.0,
    "vstep": 0.05,
}


def test_cv_runner_writes_schema_valid_result(tmp_path):
    from gui.services.moscap_runner import run_job
    import json
    job = str(tmp_path / "cv.json")
    out = str(tmp_path / "cv.npz")
    json.dump(CV_PARAMS, open(job, "w"))
    run_job(job, out)

    from gui.services.solver_backend import validate_result
    validate_result(out)
    d = np.load(out)
    v = np.asarray(d["sweep__voltage"], dtype=float)
    c = np.asarray(d["sweep__current__device"], dtype=float)
    assert len(v) == 81 and len(c) == len(v)
    meta = json.loads(str(d["sweep__meta"]))
    assert meta["contact"] == "gate"
    assert str(d["unit__sweep_current"]) == "F/cm^2"


def test_cv_curve_matches_analytic_landmarks(tmp_path):
    """Cmin/Cmax ordering and the inversion-capacitance plateau must sit
    near MOSCapacitor's own analytic landmarks -- physics gate."""
    import json
    from gui.services.moscap_runner import run_job
    from pytcad import MOSCapacitor
    job = str(tmp_path / "cv.json")
    out = str(tmp_path / "cv.npz")
    json.dump(CV_PARAMS, open(job, "w"))
    run_job(job, out)
    d = np.load(out)
    c = np.asarray(d["sweep__current__device"], dtype=float)
    vg = np.asarray(d["sweep__voltage"], dtype=float)

    mos = MOSCapacitor(Nsub=-1e17, tox_cm=5e-7, gate="n+poly")
    landmarks = mos.analytic_landmarks()
    c_ox = landmarks["C_ox"]
    c_min = landmarks["C_min"]

    assert c.max() == pytest.approx(c_ox, rel=0.10), \
        f"Cmax {c.max():.3e} vs Cox {c_ox:.3e}"
    # one plateau sits at Cox (accumulation), the curve falls toward
    # Cmin in depletion/inversion -- ordering is the physics gate
    assert c.min() == pytest.approx(c_min, rel=0.50), \
        f"Cmin {c.min():.3e} vs C_min {c_min:.3e}"
    assert c.max() > 4 * c.min()


def test_cv_through_the_controller(gapp, tmp_path):
    engine, controller = gui_app.create_engine(gapp)
    cv = controller.cv
    done = []
    cv.cvFinished.connect(lambda: done.append(1))
    errors = []
    controller.errorRaised.connect(lambda s, d: errors.append(s))

    cv.runCV(CV_PARAMS["nsub_cm3"], CV_PARAMS["tox_nm"], CV_PARAMS["vstart"],
             CV_PARAMS["vstop"], CV_PARAMS["vstep"])
    for _ in range(600):
        gapp.processEvents()
        gapp.thread().msleep(100)
        if done:
            break
    assert done, "C-V never finished"
    assert not errors
    store = controller.cv.cvStore()
    assert store.has_sweep()


def test_sweep_panel_exposes_the_cv_ui(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    for name in ("cvNsubField", "cvToxField", "runCVButton"):
        assert root.findChild(object, name) is not None, f"missing {name}"


# ----------------------------------------------------------------------
# GUI-IMPROVEMENT-PLAN.md Phase 1a: dedicated C-V viewport mode
# ----------------------------------------------------------------------
# Before this, cvSweep.cvStore() held a validated result (the two tests
# above) but nothing in ViewportPanel/MplCanvasItem ever read it back
# out -- "Curves" mode is wired to AppController's own I-V SweepResult,
# not CVController's. These gate the missing wiring, not just the data.

def test_cv_mode_before_any_run_shows_placeholder():
    """Regression pin, mirrors test_series_mode_placeholder_without_sweep
    (test_v04_review_fixes.py): "cv" mode must never fall through to
    field/doping rendering when no C-V sweep has run yet."""
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.instance() or QGuiApplication([])
    from gui.visualization.mpl_canvas_item import MplCanvasItem
    item = MplCanvasItem()
    item.setWidth(320); item.setHeight(240)
    item.setMode("cv")
    fig = item._build_figure(320, 240)
    texts = " ".join(t.get_text() for t in fig.axes[0].texts)
    assert "No C-V sweep yet" in texts


def test_cv_mode_renders_the_capacitance_curve(tmp_path):
    """Feeds a real C-V SweepResult (same pipeline
    test_cv_curve_matches_analytic_landmarks already gates numerically)
    through setCvSource() and asserts the RENDERED curve -- not just the
    stored data -- carries the analytic C_ox-scale y-range, with honest
    axis labels (capacitance, not the generic "series" mode wording)."""
    import json
    from gui.services.moscap_runner import run_job
    from gui.services.result_store import NpzResultStore
    from pytcad import MOSCapacitor
    from PySide6.QtGui import QGuiApplication
    QGuiApplication.instance() or QGuiApplication([])
    from gui.visualization.mpl_canvas_item import MplCanvasItem

    job = str(tmp_path / "cv.json")
    out = str(tmp_path / "cv.npz")
    json.dump(CV_PARAMS, open(job, "w"))
    run_job(job, out)
    sweep = NpzResultStore(out).sweep_result()

    item = MplCanvasItem()
    item.setWidth(480); item.setHeight(320)
    item.setMode("cv")
    item.setCvSource(sweep)
    fig = item._build_figure(480, 320)
    ax = fig.axes[0]
    assert ax.lines, "no curve drawn in cv mode"
    ydata = np.asarray(ax.lines[0].get_ydata(), dtype=float)

    landmarks = MOSCapacitor(Nsub=-1e17, tox_cm=5e-7, gate="n+poly") \
        .analytic_landmarks()
    assert ydata.max() == pytest.approx(landmarks["C_ox"], rel=0.10)
    assert ax.get_xlabel() == "Vg [V]"
    assert ax.get_ylabel() == f"C [{sweep.unit}]"
