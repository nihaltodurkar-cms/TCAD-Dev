"""M17 phase 3: GUI wiring for transient (time-domain) simulation.

Contract under test:
  - WaveformSpec/TransientSpec (gui/services/device_spec.py) validate
    and round-trip through DeviceSpec's JSON boundary, same shape as
    SweepSpec.
  - solver_runner.run_transient() dispatches to pytcad.transient (1D)
    or pytcad.transient2d (2D) -- the ALREADY-GATED M17 phase 1/2
    solvers, never reimplemented here -- and run_job() stamps a
    schema-v3 transient__* block that validate_result()/NpzResultStore
    read back correctly.
  - AppController's transient config slots/properties mirror the sweep
    config ones (arm/clear/read-back, mutual exclusion with an armed
    sweep, pre-flight validation before Run starts a subprocess).
"""
import os, subprocess, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.device_spec import (
    ContactSpec, DeviceSpec, DopingSpec, MeshSpec, TransientSpec,
    WaveformSpec,
)
from gui.services.result_store import NpzResultStore
from gui.services.solver_backend import (
    SOLVER_RESULT_SCHEMA_VERSION, ResultSchemaError, validate_result,
)
from gui.tests.test_solver_backend import _diode_1d_spec, _resistor_2d_spec, _run_cli


# ----------------------------------------------------------------------
#  WaveformSpec / TransientSpec: validation and JSON round-trip
# ----------------------------------------------------------------------
def test_waveform_spec_rejects_bad_kind():
    with pytest.raises(ValueError, match="kind"):
        WaveformSpec(kind="triangle").validate()


def test_waveform_spec_rejects_degenerate_ramp_and_pulse():
    with pytest.raises(ValueError, match="ramp"):
        WaveformSpec(kind="ramp", t0=1.0, t1=1.0).validate()
    with pytest.raises(ValueError, match="pulse"):
        WaveformSpec(kind="pulse", t1=0.0).validate()


def test_transient_spec_validate_values_rejects_nonpositive_t_end_dt0():
    wf = WaveformSpec(kind="step", v0=0.0, v1=1.0, t0=0.0)
    with pytest.raises(ValueError, match="t_end"):
        TransientSpec(contact="a", waveform=wf, t_end=0.0, dt0=1e-9).validate_values()
    with pytest.raises(ValueError, match="dt0"):
        TransientSpec(contact="a", waveform=wf, t_end=1e-9, dt0=0.0).validate_values()


def test_transient_spec_validate_rejects_unregistered_contact():
    wf = WaveformSpec(kind="step", v0=0.0, v1=1.0, t0=0.0)
    tr = TransientSpec(contact="ghost", waveform=wf, t_end=1e-9, dt0=1e-11)
    with pytest.raises(ValueError, match="not a registered contact"):
        tr.validate(["anode", "cathode"])


def test_device_spec_transient_round_trips_through_json(tmp_path):
    spec = _diode_1d_spec(with_sweep=False)
    spec.transient = TransientSpec(
        contact="left",
        waveform=WaveformSpec(kind="ramp", v0=0.0, v1=0.3, t0=0.0, t1=1e-9),
        t_end=2e-9, dt0=1e-11, theta=1.0)
    path = str(tmp_path / "spec.json")
    spec.to_json(path)
    loaded = DeviceSpec.from_json(path)
    assert loaded.transient.contact == "left"
    assert loaded.transient.waveform.kind == "ramp"
    assert loaded.transient.waveform.v1 == pytest.approx(0.3)
    assert loaded.transient.t_end == pytest.approx(2e-9)
    # a spec with no transient configured still round-trips to None,
    # same optional-field contract sweep/region_materials already have
    plain = _diode_1d_spec(with_sweep=False)
    plain.to_json(path)
    assert DeviceSpec.from_json(path).transient is None


# ----------------------------------------------------------------------
#  solver_runner / schema-v3: real CLI round-trip, 1D and 2D
# ----------------------------------------------------------------------
def test_cli_1d_transient_stamps_schema_v3_and_reads_back(tmp_path):
    spec = _diode_1d_spec(with_sweep=False)
    spec.transient = TransientSpec(
        contact="left",
        waveform=WaveformSpec(kind="step", v0=0.3, v1=0.0, t0=0.0),
        t_end=1e-9, dt0=1e-11)
    proc, out = _run_cli(spec, tmp_path, "diode_transient_1d")
    assert proc.returncode == 0, proc.stderr

    version = validate_result(out)
    assert version == SOLVER_RESULT_SCHEMA_VERSION == 3

    store = NpzResultStore(out)
    assert store.has_transient()
    tr = store.transient_result()
    assert tr.contact == "left"
    assert tr.n_points() >= 2
    # 1D reports BOTH named contacts -- neither is a single "device"
    # channel the way sweep__current__device is.
    assert set(tr.channels) == {"left", "right"}
    assert tr.unit == "A/cm^2"
    for vals in tr.channels.values():
        assert vals.shape == tr.times.shape
    assert not store.has_sweep()


def test_cli_2d_transient_stamps_schema_v3_and_reads_back(tmp_path):
    spec = _resistor_2d_spec()
    spec.sweep = None
    spec.transient = TransientSpec(
        contact="left",
        waveform=WaveformSpec(kind="step", v0=0.05, v1=0.15, t0=0.0),
        t_end=1e-10, dt0=1e-12)
    proc, out = _run_cli(spec, tmp_path, "resistor_transient_2d")
    assert proc.returncode == 0, proc.stderr

    assert validate_result(out) == 3
    tr = NpzResultStore(out).transient_result()
    assert set(tr.channels) == {"left", "right"}
    assert tr.unit == "A/cm"


def test_transient_result_absent_on_a_plain_run(tmp_path):
    """A result with no transient block reports has_transient()=False
    and transient_result() raises -- same protocol-with-defaults shape
    has_sweep()/sweep_result() already established."""
    spec = _diode_1d_spec(with_sweep=False)
    proc, out = _run_cli(spec, tmp_path, "diode_plain")
    assert proc.returncode == 0, proc.stderr
    store = NpzResultStore(out)
    assert not store.has_transient()
    with pytest.raises(KeyError):
        store.transient_result()


def test_solver_backend_rejects_incomplete_transient_block(tmp_path):
    """validate_result() enforces the transient block is all-or-nothing,
    same as the sweep block -- a hand-corrupted file missing
    transient__meta must be rejected, not silently half-read."""
    from gui.tests.test_solver_backend import _minimal_legacy
    p = _minimal_legacy(
        tmp_path / "badtransient.npz",
        **{"transient__times": np.array([0.0, 1e-9]),
           "unit__transient_current": np.array("A/cm^2"),
           "transient__current__left": np.array([0.0, 1.0])})
    with pytest.raises(ResultSchemaError, match="transient__meta"):
        validate_result(p)


# ----------------------------------------------------------------------
#  AppController wiring
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtGui import QGuiApplication
    yield QGuiApplication.instance() or QGuiApplication([])


def _controller_with_diode(qapp):
    from gui.controllers.app_controller import AppController
    c = AppController()
    c.loadExample("diode_1d")
    return c


def test_set_and_clear_transient_config(qapp):
    c = _controller_with_diode(qapp)
    assert not c.hasTransientConfig
    c.setTransientConfig("anode", "step", 0.0, 0.6, 0.0, 0.0, 1e-9, 1e-11)
    assert c.hasTransientConfig
    cfg = c.transientConfig()
    assert cfg["contact"] == "anode" and cfg["kind"] == "step"
    assert cfg["v1"] == pytest.approx(0.6)
    c.clearTransientConfig()
    assert not c.hasTransientConfig
    assert c.transientConfig() is None


def test_set_transient_config_rejects_invalid_values(qapp):
    c = _controller_with_diode(qapp)
    errors = []
    c.errorRaised.connect(lambda s, d: errors.append((s, d)))
    c.setTransientConfig("anode", "step", 0.0, 0.6, 0.0, 0.0, 0.0, 1e-11)
    assert not c.hasTransientConfig
    assert errors and errors[0][0] == "Invalid transient configuration"


def test_run_rejects_sweep_and_transient_armed_together(qapp):
    c = _controller_with_diode(qapp)
    c.setSweepConfig("anode", 0.0, 0.5, 0.1)
    c.setTransientConfig("anode", "step", 0.0, 0.6, 0.0, 0.0, 1e-9, 1e-11)
    errors = []
    c.errorRaised.connect(lambda s, d: errors.append((s, d)))
    c.run()
    assert not c.busy
    assert any(s == "Cannot run a sweep and a transient run together"
              for s, d in errors)


def test_run_rejects_transient_on_unregistered_contact(qapp):
    c = _controller_with_diode(qapp)
    c.setTransientConfig("ghost", "step", 0.0, 0.6, 0.0, 0.0, 1e-9, 1e-11)
    errors = []
    c.errorRaised.connect(lambda s, d: errors.append((s, d)))
    c.run()
    assert not c.busy
    assert any(s == "Transient run cannot run on this device" for s, d in errors)
