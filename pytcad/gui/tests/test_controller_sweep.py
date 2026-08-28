"""AppController's v0.4 sweep surface, tested headlessly like every other
controller surface: Python-level assertions on state/properties, with
JobRunner.start monkeypatched so no subprocess launches.

Covers the full controller contract of the sweep path: configuration
slots, validation-before-start (a bad sweep must block the run and raise
errorRaised), spec attachment/clearing on Run (a cleared config must
never leave a stale sweep on the spec), result-side hasSweep /
sweepResultForQml exposure, contact-name candidates for the QML panel,
and the sweep stage status.
"""
import json
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication

from gui.controllers.app_controller import AppController
from gui.services.device_spec import (
    ContactSpec, DeviceSpec, DopingSpec, MeshSpec, SweepSpec,
)


@pytest.fixture(scope="module")
def qapp():
    yield QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def app(qapp):
    c = AppController()
    c.loadStructureExample("mosfet_2d_structure")
    return c


def _capture_start(app):
    captured = {}
    app._runner.start = lambda spec: captured.__setitem__("spec", spec)
    return captured


# ----------------------------------------------------------------------
#  configuration slots
# ----------------------------------------------------------------------
def test_sweep_config_roundtrip(app):
    assert app.hasSweepConfig is False
    app.setSweepConfig("drain", 0.0, 0.6, 0.2)
    assert app.hasSweepConfig is True
    app.clearSweepConfig()
    assert app.hasSweepConfig is False


def test_sweep_contact_names_from_structure(app):
    names = app.sweepContactNames
    for expected in ("source", "drain", "body", "gate"):
        assert expected in names


def test_sweep_contact_names_fall_back_to_spec(qapp):
    c = AppController()
    assert c.sweepContactNames == []
    c.spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": [0.0, 1e-4]}),
        doping=DopingSpec(kind="array", values=[1e17, 1e17]),
        contacts=[
            ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
            ContactSpec(name="right", kind="ohmic", nodes={"i": [1]}, V=0.0),
        ])
    assert c.sweepContactNames == ["left", "right"]


# ----------------------------------------------------------------------
#  run() wiring
# ----------------------------------------------------------------------
def test_run_attaches_sweep_to_built_spec(app):
    app.setSweepConfig("drain", 0.0, 0.6, 0.2)
    captured = _capture_start(app)
    app.run()
    assert "spec" in captured
    assert captured["spec"].sweep == SweepSpec(contact="drain", start=0.0,
                                               stop=0.6, step=0.2)
    # a swept solve IS a biased solve: bias must still be present too
    assert captured["spec"].bias is not None


def test_invalid_sweep_contact_blocks_run_and_raises(app):
    app.setSweepConfig("base", 0.0, 0.6, 0.2)      # no such contact
    errors = []
    app.errorRaised.connect(lambda s, d: errors.append((s, d)))
    started = []
    app._runner.start = lambda spec: started.append(spec)
    app.run()
    assert not started
    assert not app.busy
    assert errors and "sweep" in errors[0][0].lower()
    assert "base" in errors[0][1]


def test_clearing_sweep_leaves_no_stale_sweep_on_spec(app):
    """A previous run's sweep must not survive a clearSweepConfig():
    run() assigns the CURRENT config (None included) every time."""
    app.setSweepConfig("drain", 0.0, 0.6, 0.2)
    captured = _capture_start(app)
    app.run()
    assert captured["spec"].sweep is not None
    app._set_busy(False)               # the patched start never "completes"

    app.clearSweepConfig()
    captured2 = _capture_start(app)
    app.run()
    assert captured2["spec"].sweep is None


def test_run_without_any_config_is_single_bias_as_before(app):
    captured = _capture_start(app)
    app.run()
    assert captured["spec"].sweep is None


# ----------------------------------------------------------------------
#  results side
# ----------------------------------------------------------------------
def _write_npz(path, with_sweep=True):
    d = {
        "dimensionality": np.array(1),
        "axis_x": np.linspace(0.0, 1e-4, 4),
        "field__potential": np.arange(4.0),
        "unit__potential": np.array("V"),
        "field__doping": np.arange(4.0),
        "unit__doping": np.array("cm^-3"),
        "solved_bias": np.array(True),
    }
    if with_sweep:
        d.update({
            "sweep__voltage": np.array([0.0, 0.5]),
            "sweep__converged": np.array([True, True]),
            "unit__sweep_current": np.array("A/cm^2"),
            "sweep__meta": np.array(json.dumps(
                {"contact": "left", "start": 0.0, "stop": 0.5,
                 "step": 0.5, "dimensionality": 1})),
            "sweep__current__device": np.array([0.0, 1e-3]),
        })
    np.savez(str(path) + ".tmp.npz", **d)
    os.replace(str(path) + ".tmp.npz", str(path))
    return str(path)


def test_finished_swept_result_exposes_hasSweep_and_object(app, tmp_path):
    fired = []
    app.resultChanged.connect(lambda: fired.append(1))
    app._on_finished(_write_npz(str(tmp_path / "ctrl_sweep_test.npz")))
    assert app.hasResult is True
    assert app.hasSweep is True
    sw = app.sweepResultForQml
    assert sw is not None
    assert sw.contact == "left"
    assert list(sw.channels) == ["device"]
    assert fired, "resultChanged must fire so QML bindings refresh"


def test_finished_plain_result_has_no_sweep(app, tmp_path):
    app._on_finished(_write_npz(str(tmp_path / "ctrl_plain_test.npz"),
                                 with_sweep=False))
    assert app.hasSweep is False
    assert app.sweepResultForQml is None


def test_before_any_result_hasSweep_is_false(qapp):
    c = AppController()
    assert c.hasSweep is False
    assert c.sweepResultForQml is None


# ----------------------------------------------------------------------
#  status / stage
# ----------------------------------------------------------------------
def test_sweep_stage_sets_status(app):
    app._on_stage("sweep")
    assert "sweep" in app.status.lower()


def test_existing_stage_mapping_unchanged(app):
    app._on_stage("equilibrium")
    assert "equilibrium" in app.status.lower()
    app._on_stage("bias")
    assert "bias" in app.status.lower()
