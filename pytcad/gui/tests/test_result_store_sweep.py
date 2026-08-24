"""v0.4 sweep-series access on NpzResultStore.

Sweep results are kept CONCEPTUALLY SEPARATE from single-run results:
they live under their own sweep__* npz keys, surface through dedicated
accessors, and never leak into available_scalars()/available_terminals().
A non-converged sweep point is preserved in the converged mask but its
current values read back as NaN -- so no consumer (including naive
plotting code) can mistake it for valid data.

The writer/reader key contract is additionally checked end-to-end
against a real solver_runner subprocess output.
"""
import json
import os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.device_spec import (
    MeshSpec, DopingSpec, ContactSpec, DeviceSpec, SweepSpec,
)
from gui.services.result_store import NpzResultStore, SpecResultStore

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ----------------------------------------------------------------------
#  fixtures
# ----------------------------------------------------------------------
def _swept_npz(path):
    """Mimic solver_runner's exact key convention, including one
    deliberately non-converged point (index 2)."""
    d = {
        "dimensionality": np.array(1),
        "axis_x": np.linspace(0.0, 1e-4, 5),
        "field__potential": np.arange(5.0),
        "unit__potential": np.array("V"),
        "solved_bias": np.array(True),
        "sweep__voltage": np.array([0.0, 0.1, 0.2, 0.3]),
        "sweep__converged": np.array([True, True, False, True]),
        "unit__sweep_current": np.array("A/cm^2"),
        "sweep__meta": np.array(json.dumps({
            "contact": "left", "start": 0.0, "stop": 0.3,
            "step": 0.1, "dimensionality": 1})),
        "sweep__current__device": np.array([1e-6, 2e-5, -999.0, 3e-4]),
    }
    np.savez(str(path) + ".tmp.npz", **d)
    os.replace(str(path) + ".tmp.npz", str(path))
    return path


def _plain_npz(path):
    """A pre-v0.4 single-run result: no sweep keys at all."""
    d = {
        "dimensionality": np.array(1),
        "axis_x": np.linspace(0.0, 1e-4, 5),
        "field__doping": np.arange(5.0),
        "unit__doping": np.array("cm^-3"),
        "solved_bias": np.array(False),
    }
    np.savez(str(path) + ".tmp.npz", **d)
    os.replace(str(path) + ".tmp.npz", str(path))
    return path


# ----------------------------------------------------------------------
#  separation from single-run results
# ----------------------------------------------------------------------
def test_plain_result_has_no_sweep(tmp_path):
    store = NpzResultStore(_plain_npz(tmp_path / "plain.npz"))
    assert store.has_sweep() is False
    with pytest.raises(KeyError, match="sweep"):
        store.sweep_result()


def test_sweep_keys_never_leak_into_single_run_listings(tmp_path):
    store = NpzResultStore(_swept_npz(tmp_path / "swept.npz"))
    # scalar/vector/terminal listings must be untouched by sweep keys
    assert store.available_scalars() == ["potential"]
    assert store.available_terminals() == []
    with pytest.raises(KeyError):
        store.vector_field("anything")
    # and the selected-point field stays readable under the same API
    f = store.scalar_field("potential")
    assert f.unit == "V"
    assert f.values.shape == (5,)


def test_sweep_result_raises_when_absent_is_explicit(tmp_path):
    store = NpzResultStore(_plain_npz(tmp_path / "plain.npz"))
    with pytest.raises(KeyError):
        store.sweep_result()


# ----------------------------------------------------------------------
#  sweep content: units, parameters, convergence
# ----------------------------------------------------------------------
def test_sweep_result_preserves_units_and_parameters(tmp_path):
    store = NpzResultStore(_swept_npz(tmp_path / "swept.npz"))
    sw = store.sweep_result()

    assert sw.contact == "left"
    assert sw.unit == "A/cm^2"
    assert sw.meta["start"] == 0.0
    assert sw.meta["stop"] == 0.3
    assert sw.meta["step"] == 0.1
    assert sw.meta["dimensionality"] == 1


def test_convergence_mask_preserved_per_point(tmp_path):
    store = NpzResultStore(_swept_npz(tmp_path / "swept.npz"))
    sw = store.sweep_result()
    assert sw.voltages.shape == (4,)
    assert list(sw.converged) == [True, True, False, True]
    assert sw.n_points() == 4
    assert sw.n_valid() == 3


def test_non_converged_points_read_as_nan_not_values(tmp_path):
    """The bogus -999 sentinel written for point 2 must NEVER come back:
    invalid points are NaN'd at the accessor boundary so even a naive
    consumer cannot plot or average them as if they were data."""
    store = NpzResultStore(_swept_npz(tmp_path / "swept.npz"))
    vals = store.sweep_result().channels["device"]
    assert np.isnan(vals[2])
    assert vals[0] == pytest.approx(1e-6)
    assert vals[3] == pytest.approx(3e-4)


def test_multiple_channels_all_get_nan_treatment(tmp_path):
    p = _swept_npz(tmp_path / "multi.npz")
    d = dict(np.load(p))
    d["sweep__current__right"] = np.array([1.0, 2.0, -777.0, 4.0])
    np.savez(p, **d)

    sw = NpzResultStore(p).sweep_result()
    assert sorted(sw.channels) == ["device", "right"]
    assert np.isnan(sw.channels["right"][2])
    assert not np.isnan(sw.channels["right"][1])


# ----------------------------------------------------------------------
#  interface symmetry across stores
# ----------------------------------------------------------------------
def test_spec_store_reports_no_sweep():
    spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": [0.0, 1e-4]}),
        doping=DopingSpec(kind="array", values=[1e17, 1e17]),
    )
    store = SpecResultStore(spec)
    assert store.has_sweep() is False
    with pytest.raises(KeyError, match="sweep"):
        store.sweep_result()


# ----------------------------------------------------------------------
#  writer/reader contract against a REAL solver run
# ----------------------------------------------------------------------
def test_real_solver_output_reads_back_as_sweep_result(tmp_path):
    spec = DeviceSpec(
        mesh=MeshSpec(
            dimensionality=1,
            axes={"x": np.linspace(0.0, 2e-4, 30).tolist()}),
        doping=DopingSpec(
            kind="array",
            values=np.where(np.linspace(0, 2e-4, 30) < 1e-4,
                            -1e17, 1e17).tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic",
                        nodes={"i": [0]}, V=0.0),
            ContactSpec(name="right", kind="ohmic",
                        nodes={"i": [29]}, V=0.0),
        ],
        bias={"right": 0.0},
        sweep=SweepSpec(contact="left", start=0.0, stop=0.2, step=0.1),
    )
    job = str(tmp_path / "job.json")
    out = str(tmp_path / "out.npz")
    spec.to_json(job)
    proc = subprocess.run(
        [sys.executable, "-m", "gui.services.solver_runner", job, out],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr

    sw = NpzResultStore(out).sweep_result()
    assert sw.contact == "left"
    assert sw.voltages.tolist() == pytest.approx([0.0, 0.1, 0.2])
    assert bool(sw.converged.all())
    assert sw.channels["device"].shape == (3,)
    assert np.isfinite(sw.channels["device"]).all()
    # selected-point fields coexist on the same file
    assert "doping" in NpzResultStore(out).available_scalars()
