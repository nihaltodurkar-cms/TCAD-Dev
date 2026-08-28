"""Regression tests for the v0.4 final-review findings (I-1..I-6 and the
cheap Minors).  Each test names its finding ID; see the review report.
"""
import json
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication

from gui.services import solver_runner
from gui.services.device_spec import (
    ContactSpec, DeviceSpec, DopingSpec, MeshSpec, SweepSpec,
)
from gui.services.result_store import NpzResultStore


# ----------------------------------------------------------------------
# I-1: sweep contact candidates must refresh after loadExample()
# ----------------------------------------------------------------------
def test_loadExample_refreshes_sweep_panel(gapp=None):
    gapp = QGuiApplication.instance() or QGuiApplication([])
    from gui import app as gui_app
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    controller.loadExample("mosfet_2d")
    box = root.findChild(object, "sweepContactBox")
    model = list(box.property("model"))
    assert "drain" in model and "gate" in model, model


# ----------------------------------------------------------------------
# I-2: loading a project must drop any previous session's spec
# ----------------------------------------------------------------------
def test_loadProject_clears_stale_spec(qapp=None, tmp_path=None):
    qapp = QCoreApplication.instance() or QCoreApplication([])
    from gui.controllers.app_controller import AppController
    app = AppController()
    app.loadExample("mosfet_2d")           # leaves self.spec set
    other = AppController()                # a process-only project
    other.addProcessStep("substrate", "Substrate",
                         {"length_cm": 1e-3, "background_doping_cm3": -1e16,
                          "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6,
                                   "ratio": 1.2}})
    path = str(tmp_path or "/tmp/opencode/i2_proj.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    other.saveProject(path, "ProcOnly")
    assert os.path.exists(path), "fixture project failed to save"

    errors = []
    app.errorRaised.connect(lambda s, d: errors.append(s))
    app.loadProject(path)
    assert app.spec is None, "stale spec survived loadProject"
    started = []
    app._runner.start = lambda spec: started.append(spec)
    app.run()
    assert not started and errors and "Nothing to run" in errors[0]


# ----------------------------------------------------------------------
# I-3: starting a run must clear previous results immediately
# ----------------------------------------------------------------------
def test_run_clears_stale_store(qapp=None):
    qapp = QCoreApplication.instance() or QCoreApplication([])
    from gui.controllers.app_controller import AppController
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")

    class _FakeStore:
        def available_scalars(self):
            return ["potential"]
    app._store = _FakeStore()
    app._runner.start = lambda spec: None   # never completes/fails
    app.run()
    assert app.hasResult is False, \
        "previous results stayed on show while a fresh solve is running"


# ----------------------------------------------------------------------
# I-4: an all-diverged sweep must fall back to equilibrium fields
# ----------------------------------------------------------------------
def test_all_diverged_sweep_returns_equilibrium_fallback():
    x = np.linspace(0.0, 2e-4, 30)
    spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array",
                          values=np.where(x < 1e-4, -1e17, 1e17).tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
            ContactSpec(name="right", kind="ohmic", nodes={"i": [29]}, V=0.0),
        ],
        bias={"right": 0.0},
        sweep=SweepSpec(contact="left", start=0.0, stop=0.3, step=0.1),
    )
    mesh_obj = solver_runner.build_mesh(spec.mesh)
    doping, ntotal = solver_runner.build_doping(spec.doping, spec.mesh.shape())
    device = solver_runner.build_device(spec, mesh_obj, doping, ntotal)
    device.solve_equilibrium()
    fallback = solver_runner.extract_result(device, spec, solved_bias=False)

    hopeless = __import__("pytcad.device", fromlist=["NewtonOptions"]) \
        .NewtonOptions(max_iter=2, tol_update=1e-30, verbose=False)
    fields, series = solver_runner.run_sweep(device, spec, hopeless,
                                             fallback_fields=fallback)
    assert not bool(series["sweep__converged"].any())
    assert fields is fallback, (
        "all-diverged sweep must return the pre-sweep equilibrium snapshot, "
        "never a diverged state presented as a biased result")


# ----------------------------------------------------------------------
# I-5: cancel's pending kill timer must not kill the NEXT run
# ----------------------------------------------------------------------
def test_cancel_kill_timer_spares_next_run(qapp=None):
    qapp = QCoreApplication.instance() or QCoreApplication([])
    from gui.services.job_runner import JobRunner

    runner = JobRunner(module="gui.services.solver_runner")
    runner._proc = __import__("PySide6.QtCore", fromlist=["QProcess"]).QProcess(runner)

    class _FakeSpec:
        def to_json(self, path):
            with open(path, "w") as fh:
                fh.write("{}")
    # a real long-running subprocess as "run #1"
    from PySide6.QtCore import QProcess
    p1 = QProcess(runner)
    p1.start(sys.executable, ["-c", "import time; time.sleep(60)"])
    assert p1.waitForStarted(5000)
    runner._proc = p1
    runner.cancel()

    # "run #2" starts before the 3 s kill grace expires
    p2 = QProcess(runner)
    p2.start(sys.executable, ["-c", "import time; time.sleep(60)"])
    assert p2.waitForStarted(5000)
    runner._proc = p2

    loop = QEventLoop()
    QTimer.singleShot(3500, loop.quit)     # outlive the kill grace
    loop.exec()

    assert p2.state() != QProcess.NotRunning, \
        "the pending kill timer murdered the replacement run"
    p2.kill(); p2.waitForFinished(5000)


# ----------------------------------------------------------------------
# I-6 + M-2: Vth uses the held-terminal bias; gate-only rows gated
# ----------------------------------------------------------------------
def _controller_with_swept_result(tmp_path, spec_bias=None, swept_contact="left"):
    qapp = QCoreApplication.instance() or QCoreApplication([])
    from gui.controllers.app_controller import AppController
    app = AppController()
    contacts = [
        ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
        ContactSpec(name="right", kind="ohmic", nodes={"i": [1]}, V=0.0),
    ]
    if swept_contact == "gate":
        contacts.append(ContactSpec(name="gate", kind="gate",
                                    nodes={"i": [0]}, tox_cm=5e-7,
                                    Vfb=-0.9))
    app.spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": [0.0, 1e-4]}),
        doping=DopingSpec(kind="array", values=[1e17, 1e17]),
        contacts=contacts, bias=spec_bias)
    d = {
        "dimensionality": np.array(1),
        "axis_x": np.array([0.0, 1e-4]),
        "field__potential": np.array([0.0, 1.0]),
        "unit__potential": np.array("V"),
        "field__doping": np.array([1e17, 1e17]),
        "unit__doping": np.array("cm^-3"),
        "solved_bias": np.array(True),
        "sweep__voltage": np.linspace(-1.0, 1.0, 11),
        "sweep__converged": np.array([True] * 11),
        "unit__sweep_current": np.array("A/cm^2"),
        "sweep__meta": np.array(json.dumps(
            {"contact": swept_contact, "start": -1.0, "stop": 1.0,
             "step": 0.2, "dimensionality": 1})),
        # ideal linear turn-on crossing zero at Vg = +0.3
        "sweep__current__device": (np.linspace(-1.0, 1.0, 11) - 0.3) * 1e-3,
    }
    path = str(tmp_path / "review_fix_test.npz")
    np.savez(path + ".tmp.npz", **d)
    os.replace(path + ".tmp.npz", path)
    app._on_finished(path)
    return app


def test_vth_row_uses_held_terminal_bias_as_vds(tmp_path):
    app = _controller_with_swept_result(
        tmp_path, spec_bias={"right": 0.5}, swept_contact="gate")
    rows = dict(app._properties_for("results"))
    # linear curve crosses at 0.3; vds correction subtracts 0.25
    got = float(rows["Sweep Vth (max-gm est.)"].split()[0])
    assert got == pytest.approx(0.05, abs=1e-9), rows["Sweep Vth (max-gm est.)"]


def test_ion_ioff_and_vth_rows_only_for_gate_sweeps(tmp_path):
    app = _controller_with_swept_result(tmp_path, spec_bias={"right": 0.5},
                                        swept_contact="left")
    rows = dict(app._properties_for("results"))
    assert "Sweep Ion/Ioff" not in rows, \
        "an ohmic-contact sweep has no threshold -- row must be absent"
    assert "Sweep Vth (max-gm est.)" not in rows
    assert "Sweep points" in rows and "Sweep Imax (left)" in rows


# ----------------------------------------------------------------------
# M-3: Curves mode with no sweep shows a placeholder, not field data
# ----------------------------------------------------------------------
def test_series_mode_placeholder_without_sweep(gapp=None):
    gapp = QGuiApplication.instance() or QGuiApplication([])
    from gui.visualization.mpl_canvas_item import MplCanvasItem
    item = MplCanvasItem()
    item.setWidth(320); item.setHeight(240)
    item.setMode("series")
    fig = item._build_figure(320, 240)
    texts = " ".join(t.get_text() for t in fig.axes[0].texts)
    assert "No sweep yet" in texts


# ----------------------------------------------------------------------
# M-4 / M-5 / M-6: validation tightening
# ----------------------------------------------------------------------
def test_validate_values_caps_point_count():
    with pytest.raises(ValueError, match="points"):
        SweepSpec(contact="d", start=0.0, stop=1.0, step=1e-9).validate_values()


def test_devicespec_from_dict_uses_strict_sweep_parse():
    d = {"mesh": {"dimensionality": 1, "axes": {"x": [0.0, 1.0]}},
         "doping": {"kind": "array", "values": [1e17, 1e17], "ntotal": None},
         "sweep": {"contact": "d", "start": 0.0}}       # missing stop/step
    with pytest.raises(ValueError, match="sweep"):
        DeviceSpec.from_dict(d)


def test_setSweepConfig_rejects_nan_immediately(qapp=None):
    qapp = QCoreApplication.instance() or QCoreApplication([])
    from gui.controllers.app_controller import AppController
    app = AppController()
    errors = []
    app.errorRaised.connect(lambda s, d: errors.append(s))
    app.setSweepConfig("drain", float("nan"), 1.0, 0.1)
    assert errors, "NaN sweep config must raise immediately"
    assert app.hasSweepConfig is False
