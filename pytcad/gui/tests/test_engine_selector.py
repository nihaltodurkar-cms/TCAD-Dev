"""v0.6 Phase 2d: manual solver-engine override (Direct/GPU direct/AMG/
MPI Schwarz), exposed next to the existing pytcad/devsim backend
selector (test_m7_devsim.py's own "AppController backend selector"
section) -- same "controllers hold all UI-facing state" split
test_controllers.py's own docstring describes, so these need no QML.
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication

from gui.controllers.app_controller import AppController
from gui.services.device_spec import ContactSpec, DeviceSpec, DopingSpec, MeshSpec


@pytest.fixture(scope="module")
def qapp():
    yield QCoreApplication.instance() or QCoreApplication([])


def _diode_1d_spec():
    x = np.linspace(0.0, 2e-4, 20)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
                  ContactSpec(name="right", kind="ohmic",
                              nodes={"i": [x.size - 1]}, V=0.0)],
        bias={"left": 0.0, "right": 0.3})


def _resistor_3d_spec(nx=6, ny=6, nz=6):
    x = np.linspace(0.0, 2e-4, nx)
    y = np.linspace(0.0, 1e-4, ny)
    z = np.linspace(0.0, 1e-4, nz)
    doping = np.full((nz, ny, nx), 1e17)
    jj, kk = np.meshgrid(np.arange(ny), np.arange(nz))
    jj, kk = jj.ravel().tolist(), kk.ravel().tolist()
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=3,
                      axes={"x": x.tolist(), "y": y.tolist(), "z": z.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[ContactSpec(name="left", kind="ohmic",
                              nodes={"i": [0] * len(jj), "j": jj, "k": kk}, V=0.0),
                  ContactSpec(name="right", kind="ohmic",
                              nodes={"i": [nx - 1] * len(jj), "j": jj, "k": kk}, V=0.0)],
        bias={"left": 0.05, "right": 0.0})


def test_defaults_to_auto(qapp):
    ctl = AppController()
    assert ctl.selectedEngine == "auto"


def test_engine_options_always_include_auto_and_direct(qapp):
    ctl = AppController()
    ctl.spec = _diode_1d_spec()
    opts = {o["id"]: o for o in ctl.engineOptionsForQml()}
    assert opts["auto"]["enabled"] is True
    assert opts["direct"]["enabled"] is True


def test_mpi_schwarz_option_disabled_for_a_1d_device(qapp):
    ctl = AppController()
    ctl.spec = _diode_1d_spec()
    opts = {o["id"]: o for o in ctl.engineOptionsForQml()}
    assert opts["mpi_schwarz"]["enabled"] is False
    assert "3d" in opts["mpi_schwarz"]["reason"].lower()


def test_mpi_schwarz_option_disabled_with_an_armed_transient(qapp):
    ctl = AppController()
    ctl.spec = _resistor_3d_spec()
    ctl.setTransientConfig("left", "constant", 0.05, 0.0, 0.0, 0.0, 1e-9, 1e-10)
    opts = {o["id"]: o for o in ctl.engineOptionsForQml()}
    assert opts["mpi_schwarz"]["enabled"] is False
    assert "transient" in opts["mpi_schwarz"]["reason"].lower()


def test_set_engine_updates_selected_engine(qapp):
    ctl = AppController()
    ctl.setEngine("gpu_direct")
    assert ctl.selectedEngine == "gpu_direct"


def test_run_attaches_the_selected_engine_to_the_spec(tmp_path, qapp):
    ctl = AppController()
    ctl.spec = _diode_1d_spec()
    ctl.setEngine("direct")

    errors = []
    ctl.errorRaised.connect(lambda s, d: errors.append((s, d)))
    ctl.run()
    t0 = __import__("time").time()
    while ctl.busy and __import__("time").time() - t0 < 120:
        qapp.processEvents(); __import__("time").sleep(0.02)

    assert not errors, errors
    assert ctl.hasResult, ctl.status
    rec = ctl.currentStore().run_record()
    assert rec.numerics["linsolve"] == "direct"


def test_run_refuses_an_engine_incompatible_with_the_current_device(tmp_path, qapp):
    """Defense in depth (same contract test_run_refuses_when_backend_
    choice_goes_stale documents for the backend selector): a forced
    engine that becomes structurally invalid for the loaded device must
    surface as a clean errorRaised, not a crash or a silent fallback."""
    ctl = AppController()
    ctl.spec = _diode_1d_spec()      # 1D -- mpi_schwarz is 3D-only
    ctl.setEngine("mpi_schwarz")

    errors = []
    ctl.errorRaised.connect(lambda s, d: errors.append((s, d)))
    ctl.run()
    t0 = __import__("time").time()
    while ctl.busy and __import__("time").time() - t0 < 120:
        qapp.processEvents(); __import__("time").sleep(0.02)

    assert errors, "an incompatible engine choice must be refused, not silently run"
    assert not ctl.hasResult


def test_engine_selector_present_in_qml():
    from gui import app as gui_app
    from PySide6.QtGui import QGuiApplication
    gapp = QGuiApplication.instance() or QGuiApplication([])
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    selector = root.findChild(object, "engineSelector")
    assert selector is not None
