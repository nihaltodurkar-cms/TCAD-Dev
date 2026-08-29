"""ResultStore is the format boundary.  Nothing above it may know that
v0.1 stores results as .npz -- so the interface is what is tested, and
two different implementations must satisfy it identically."""
import os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.device_spec import MeshSpec, DopingSpec, ContactSpec, DeviceSpec
from gui.services.result_store import (
    NpzResultStore, SpecResultStore, ScalarField, VectorField, TerminalCurrent)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _spec_2d():
    x = np.linspace(0.0, 2e-4, 12)
    y = np.linspace(0.0, 1e-4, 8)
    jj = list(range(y.size))
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=2, axes={"x": x.tolist(), "y": y.tolist()}),
        doping=DopingSpec(kind="array", values=np.full((y.size, x.size), 1e17).tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic",
                        nodes={"i": [0] * len(jj), "j": jj}, V=0.0),
            ContactSpec(name="right", kind="ohmic",
                        nodes={"i": [11] * len(jj), "j": jj}, V=0.0),
        ],
        bias={"left": 0.05, "right": 0.0},
    )


@pytest.fixture(scope="module")
def npz_2d(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("res")
    job, out = str(tmp / "j.json"), str(tmp / "o.npz")
    _spec_2d().to_json(job)
    proc = subprocess.run([sys.executable, "-m", "gui.services.solver_runner", job, out],
                          cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    return out


def test_npz_store_scalar_fields_carry_units(npz_2d):
    store = NpzResultStore(npz_2d)
    psi = store.scalar_field("potential")
    assert isinstance(psi, ScalarField)
    assert psi.unit == "V"
    assert psi.values.shape == (8, 12)
    assert store.scalar_field("electron_density").unit == "cm^-3"
    assert "doping" in store.available_scalars()


def test_npz_store_mesh_axes(npz_2d):
    axes = NpzResultStore(npz_2d).mesh_axes()
    assert axes.dimensionality == 2
    assert set(axes.axes) == {"x", "y"}
    assert axes.axes["x"].size == 12
    assert axes.axes["y"].size == 8


def test_npz_store_vector_field(npz_2d):
    v = NpzResultStore(npz_2d).vector_field("current_density")
    assert isinstance(v, VectorField)
    assert set(v.components) == {"x", "y"}
    assert v.components["x"].shape == (8, 12)
    assert v.unit == "A/cm^2"


def test_npz_store_terminal_current_is_labeled(npz_2d):
    store = NpzResultStore(npz_2d)
    assert set(store.available_terminals()) == {"left", "right"}
    t = store.terminal_current("left")
    assert isinstance(t, TerminalCurrent)
    assert t.unit == "A/cm"          # never a bare number
    assert np.isfinite(t.value)


def test_missing_field_raises_keyerror(npz_2d):
    with pytest.raises(KeyError):
        NpzResultStore(npz_2d).scalar_field("not_a_field")


def test_spec_store_serves_doping_before_any_solve():
    """The structure must be visualizable before a solve exists -- so a
    DeviceSpec is itself a (read-only, doping-only) ResultStore."""
    store = SpecResultStore(_spec_2d())
    assert store.available_scalars() == ["doping"]
    dop = store.scalar_field("doping")
    assert dop.values.shape == (8, 12)
    assert dop.unit == "cm^-3"
    assert store.mesh_axes().dimensionality == 2
    assert store.available_terminals() == []
    with pytest.raises(KeyError):
        store.scalar_field("potential")
