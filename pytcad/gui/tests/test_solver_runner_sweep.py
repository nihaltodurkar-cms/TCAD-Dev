"""v0.4 sweep execution in solver_runner.

A SweepSpec must produce per-point voltage/current/convergence series in
the .npz alongside the usual normalized fields (taken at the last
CONVERGED point), while leaving every pre-v0.4 key and behavior intact.

Meshes stay deliberately tiny -- see test_solver_runner.py's note on GUI
suite speed.  The physics itself is validated in pytcad/tests; here we
assert plumbing plus only coarse, backend-consistent physical sanity.
"""
import json
import os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.device_spec import (
    MeshSpec, DopingSpec, ContactSpec, DeviceSpec, SweepSpec,
)
from gui.services import solver_runner
from pytcad.device import NewtonOptions

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ----------------------------------------------------------------------
#  fixtures
# ----------------------------------------------------------------------
def _diode_1d_spec(sweep=None):
    x = np.linspace(0.0, 2e-4, 40)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
            ContactSpec(name="right", kind="ohmic",
                        nodes={"i": [x.size - 1]}, V=0.0),
        ],
        bias={"right": 0.0},
        sweep=sweep,
    )


def _resistor_2d_spec(sweep=None):
    x = np.linspace(0.0, 2e-4, 12)
    y = np.linspace(0.0, 1e-4, 8)
    doping = np.full((y.size, x.size), 1e17)
    jj = list(range(y.size))
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=2, axes={"x": x.tolist(), "y": y.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic",
                        nodes={"i": [0] * len(jj), "j": jj}, V=0.0),
            ContactSpec(name="right", kind="ohmic",
                        nodes={"i": [x.size - 1] * len(jj), "j": jj}, V=0.0),
        ],
        bias={"right": 0.0},
        sweep=sweep,
    )


def _run_cli(spec, tmp_path, name):
    job = str(tmp_path / f"{name}.json")
    out = str(tmp_path / f"{name}.npz")
    spec.to_json(job)
    proc = subprocess.run(
        [sys.executable, "-m", "gui.services.solver_runner", job, out],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300)
    return proc, out


# ----------------------------------------------------------------------
#  1D sweep (channel is the total current density; 1D has no terminals)
# ----------------------------------------------------------------------
def test_1d_sweep_writes_series_keys(tmp_path):
    spec = _diode_1d_spec(SweepSpec(contact="left", start=0.0, stop=0.4, step=0.1))
    proc, out = _run_cli(spec, tmp_path, "diode_sweep")
    assert proc.returncode == 0, proc.stderr
    d = np.load(out)

    assert np.allclose(d["sweep__voltage"], [0.0, 0.1, 0.2, 0.3, 0.4])
    assert d["sweep__converged"].dtype == bool
    assert bool(d["sweep__converged"].all())
    # 1D channel: total current density, explicitly unit-tagged
    assert "sweep__current__device" in d.files
    assert str(d["unit__sweep_current"]) == "A/cm^2"
    meta = json.loads(str(d["sweep__meta"]))
    assert meta["contact"] == "left"
    assert meta["dimensionality"] == 1


def test_1d_forward_sweep_current_is_monotonically_increasing(tmp_path):
    """Coarse physical sanity: forward-biasing the p-side of a pn diode
    must raise the current every step (exact ideality is validated in
    pytcad/tests/test_validation.py, not re-checked here)."""
    spec = _diode_1d_spec(SweepSpec(contact="left", start=0.0, stop=0.5, step=0.1))
    proc, out = _run_cli(spec, tmp_path, "diode_iv")
    assert proc.returncode == 0, proc.stderr
    J = np.load(out)["sweep__current__device"]
    assert np.all(np.diff(J) > 0)


def test_fields_come_from_last_sweep_point(tmp_path):
    """The stored fields must be the LAST ramp point's solution --
    verified against an independent single-bias solve of the identical
    operating point (convention-free: makes no assumption about how
    pytcad references psi_V at contacts)."""
    swept = _diode_1d_spec(SweepSpec(contact="left", start=0.0, stop=0.3, step=0.1))
    proc, out = _run_cli(swept, tmp_path, "diode_swept")
    assert proc.returncode == 0, proc.stderr

    single = _diode_1d_spec()
    single.bias = {"left": 0.3, "right": 0.0}
    proc2, out2 = _run_cli(single, tmp_path, "diode_single")
    assert proc2.returncode == 0, proc2.stderr

    a = np.load(out)["field__potential"]
    b = np.load(out2)["field__potential"]
    assert a.shape == b.shape
    assert np.allclose(a, b)


# ----------------------------------------------------------------------
#  2D sweep (channels are ohmic terminal currents, A/cm)
# ----------------------------------------------------------------------
def test_2d_sweep_terminal_series_charge_conserved_per_point(tmp_path):
    spec = _resistor_2d_spec(SweepSpec(contact="left", start=0.05, stop=0.25, step=0.05))
    proc, out = _run_cli(spec, tmp_path, "res_sweep")
    assert proc.returncode == 0, proc.stderr
    d = np.load(out)

    assert str(d["unit__sweep_current"]) == "A/cm"
    il = d["sweep__current__left"]
    ir = d["sweep__current__right"]
    assert il.shape == ir.shape == (5,)
    for a, b in zip(il, ir):
        assert abs(a + b) / max(abs(a), abs(b)) < 1e-6
    # ohmic channel current grows with the applied two-terminal bias
    assert np.all(np.diff(np.abs(il)) > 0)
    # fields again correspond to the final point: both contacts share
    # the same doping, so their intrinsic-reference offsets cancel and
    # the psi_V DIFFERENCE equals the applied two-terminal bias
    assert float(d["field__potential"][0, 0] - d["field__potential"][0, -1]) \
        == pytest.approx(0.25, abs=1e-6)


# ----------------------------------------------------------------------
#  failure modes
# ----------------------------------------------------------------------
def test_unknown_sweep_contact_fails_fast_with_no_output(tmp_path):
    spec = _resistor_2d_spec(SweepSpec(contact="base", start=0.0, stop=0.1, step=0.05))
    proc, out = _run_cli(spec, tmp_path, "bad_contact")
    assert proc.returncode != 0
    assert not os.path.exists(out)
    assert "PYTCAD_ERROR=" in proc.stderr
    assert "base" in proc.stderr


def test_non_converged_points_are_flagged_not_fatal():
    """A diverging point must be recorded as converged=False and the
    sweep continues -- one bad bias must never lose the whole curve.
    Driven directly (not via subprocess) so NewtonOptions can force
    divergence deterministically."""
    from pytcad.device import Device1D

    spec = _diode_1d_spec(SweepSpec(contact="left", start=0.0, stop=0.3, step=0.1))
    mesh_obj = solver_runner.build_mesh(spec.mesh)
    doping, ntotal = solver_runner.build_doping(spec.doping, spec.mesh.shape())
    device = solver_runner.build_device(spec, mesh_obj, doping, ntotal)
    device.solve_equilibrium()

    hopeless = NewtonOptions(max_iter=2, tol_update=1e-30, verbose=False)
    fields, series = solver_runner.run_sweep(device, spec, hopeless)

    assert not bool(series["sweep__converged"].any())
    assert series["sweep__voltage"].size == 4   # 0..0.3 step 0.1, endpoint inclusive
    assert np.isfinite(series["sweep__current__device"]).all()
