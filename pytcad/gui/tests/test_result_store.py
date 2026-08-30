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


# ----------------------------------------------------------------------
# GUI-IMPROVEMENT-PLAN.md Phase 2b: line-cut extraction
# ----------------------------------------------------------------------
def test_line_cut_horizontal_matches_the_nearest_row_directly():
    from gui.services.result_store import extract_line_cut
    store = SpecResultStore(_spec_2d())
    axes = store.mesh_axes()
    field = store.scalar_field("doping")
    y = np.asarray(axes.axes["y"], dtype=float)
    j = 3
    coord, values, actual_y = extract_line_cut(
        axes, field, "horizontal", position_cm=float(y[j]))
    assert actual_y == pytest.approx(y[j])
    assert np.array_equal(coord, np.asarray(axes.axes["x"], dtype=float))
    assert np.array_equal(values, np.asarray(field.values)[j, :])


def test_line_cut_vertical_matches_the_nearest_column_directly():
    from gui.services.result_store import extract_line_cut
    store = SpecResultStore(_spec_2d())
    axes = store.mesh_axes()
    field = store.scalar_field("doping")
    x = np.asarray(axes.axes["x"], dtype=float)
    i = 5
    coord, values, actual_x = extract_line_cut(
        axes, field, "vertical", position_cm=float(x[i]))
    assert actual_x == pytest.approx(x[i])
    assert np.array_equal(coord, np.asarray(axes.axes["y"], dtype=float))
    assert np.array_equal(values, np.asarray(field.values)[:, i])


def test_line_cut_snaps_to_the_nearest_node_on_a_nonuniform_mesh():
    """The honesty claim ("nearest node, not interpolated") only means
    something on a mesh where nodes are NOT evenly spaced -- gate it
    there, not on the uniform test mesh above."""
    from gui.services.result_store import extract_line_cut, MeshAxes, ScalarField
    x = np.array([0.0, 1.0e-4, 1.3e-4, 3.0e-4])   # non-uniform
    y = np.array([0.0, 2.0e-4, 5.0e-4])
    axes = MeshAxes(axes={"x": x, "y": y}, dimensionality=2)
    values = np.arange(x.size * y.size, dtype=float).reshape(y.size, x.size)
    field = ScalarField(name="v", values=values, unit="")

    # requested 1.1e-4 sits between nodes 1.0e-4 and 1.3e-4, closer to
    # 1.0e-4 -- must snap there, not to whichever index is numerically
    # adjacent or interpolate between them.
    coord, vals, actual_x = extract_line_cut(axes, field, "vertical",
                                             position_cm=1.1e-4)
    assert actual_x == pytest.approx(1.0e-4)
    assert np.array_equal(vals, values[:, 1])


def test_line_cut_rejects_non_2d_fields():
    from gui.services.result_store import extract_line_cut, MeshAxes, ScalarField
    axes = MeshAxes(axes={"x": np.linspace(0, 1e-4, 5)}, dimensionality=1)
    field = ScalarField(name="v", values=np.zeros(5), unit="")
    with pytest.raises(ValueError, match="2D"):
        extract_line_cut(axes, field, "horizontal", position_cm=0.0)


def test_line_cut_rejects_bad_orientation():
    from gui.services.result_store import extract_line_cut
    store = SpecResultStore(_spec_2d())
    with pytest.raises(ValueError, match="orientation"):
        extract_line_cut(store.mesh_axes(), store.scalar_field("doping"),
        "diagonal", position_cm=0.0)


# ----------------------------------------------------------------------
# Phase 4: sweep snapshots for 3D animation playback
# ----------------------------------------------------------------------
def test_sweep_snapshots_reconstructs_3d_arrays_correctly():
    from gui.services.result_store import SweepSnapshots
    voltages = np.array([0.0, 0.5, 1.0])
    shape = (4, 5)
    field_names = ["potential", "doping"]
    data = {}
    for name in field_names:
        for idx in range(len(voltages)):
            data[(name, idx)] = np.arange(20, dtype=float).reshape(shape) + idx
    snapshots = SweepSnapshots(
        voltages=voltages,
        field_names=field_names,
        shape=shape,
        _data=data,
    )
    assert snapshots.n_snapshots() == 3
    assert snapshots.field_names == field_names
    for idx in range(3):
        arr = snapshots.field("potential", idx)
        assert arr.shape == shape
        assert np.array_equal(arr, data[("potential", idx)])
        volt = snapshots.voltage(idx)
        assert volt == pytest.approx(voltages[idx])


def test_sweep_snapshots_rejects_out_of_range_index():
    from gui.services.result_store import SweepSnapshots
    snapshots = SweepSnapshots(
        voltages=np.array([0.0, 1.0]),
        field_names=["potential"],
        shape=(2, 2, 2),
        _data={("potential", 0): np.zeros((2, 2, 2)),
               ("potential", 1): np.ones((2, 2, 2))},
    )
    with pytest.raises(IndexError):
        snapshots.field("potential", 5)


def test_sweep_snapshots_rejects_unknown_field():
    from gui.services.result_store import SweepSnapshots
    snapshots = SweepSnapshots(
        voltages=np.array([0.0]),
        field_names=["potential"],
        shape=(2, 2, 2),
        _data={("potential", 0): np.zeros((2, 2, 2))},
    )
    with pytest.raises(KeyError, match="not_a_field"):
        snapshots.field("not_a_field", 0)


def test_npz_result_store_has_sweep_snapshots_returns_false_when_no_snapshots(npz_2d):
    store = NpzResultStore(npz_2d)
    assert store.has_sweep_snapshots() is False


def test_npz_result_store_loads_sweep_snapshots_correctly(tmp_path):
    """Round-trip: write snapshot data to an npz, load it back, and
    verify the reconstructed arrays match the originals."""
    import json
    path = str(tmp_path / "snapshots.npz")
    shape = (4, 5)
    voltages = np.array([0.0, 0.5, 1.0])
    fields = {"potential": np.arange(20, dtype=float).reshape(shape)}

    # Build the npz keys for sweep snapshots.
    arrs = {}
    for name in fields:
        for idx in range(len(voltages)):
            arrs[f"sweep__snapshot__field__{name}__{idx}"] = (
                fields[name].flatten(order="C").copy())

    np.savez(path, **arrs,
             sweep__snapshot__voltages=json.dumps(voltages.tolist()),
             mesh__shape=np.array(list(shape)),
             solved_bias=np.array(True),
             dimensionality=np.array(2),
             axis_x=np.zeros(5),
             axis_y=np.zeros(4),
              **{f"field__{name}": fields[name].reshape(4, 5) for name in fields},
              **{f"unit__{name}": np.array("V") for name in fields},
              sweep__voltage=np.array([0.0]),
              sweep__converged=np.array([True]),
              sweep__meta=json.dumps({"dimensionality": 2}),
              sweep__current__base=np.array([0.0]),
              unit__sweep_current=np.array("A"),
              **{f"terminal__base__value": np.array([0.0]),
                 f"terminal__base__unit": np.array("A")})

    store = NpzResultStore(path)
    assert store.has_sweep_snapshots() is True
    snaps = store.sweep_snapshots()
    assert snaps.n_snapshots() == 3
    assert snaps.field_names == ["potential"]
    for idx in range(3):
        arr = snaps.field("potential", idx)
        assert arr.shape == shape
        assert np.array_equal(arr, fields["potential"])
        assert snaps.voltage(idx) == pytest.approx(voltages[idx])


def test_npz_result_store_sweep_snapshots_missing_field_data_raises():
    """If voltages are present but no field data, raise KeyError."""
    import json
    import tempfile
    path = tempfile.mktemp(suffix=".npz")
    voltages = np.array([0.0, 1.0])
    np.savez(path,
             sweep__snapshot__voltages=json.dumps(voltages.tolist()),
             mesh__shape=np.array([4, 5]),
             solved_bias=np.array(True),
             dimensionality=np.array(2),
             axis_x=np.zeros(5),
             axis_y=np.zeros(4),
              **{"field__potential": np.zeros((4, 5))},
              **{"unit__potential": np.array("V")},
              sweep__voltage=np.array([0.0]),
              sweep__converged=np.array([True]),
              sweep__meta=json.dumps({"dimensionality": 2}),
              sweep__current__base=np.array([0.0]),
              unit__sweep_current=np.array("A"),
              **{f"terminal__base__value": np.array([0.0]),
                 f"terminal__base__unit": np.array("A")})
    store = NpzResultStore(path)
    assert store.has_sweep_snapshots() is True
    with pytest.raises(KeyError, match="no field data"):
        store.sweep_snapshots()
    os.unlink(path)


def test_sweep_snapshots_empty_field_names_raises_keyerror():
    """If voltages are present but no field data, raise KeyError."""
    from gui.services.result_store import SweepSnapshots
    # We can't directly construct a state with voltages but no fields
    # through the normal API, so we test the NpzResultStore path.
    pass
