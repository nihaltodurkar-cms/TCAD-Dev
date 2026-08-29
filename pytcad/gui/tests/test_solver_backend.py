"""v0.5.0 task 1: the solver-backend boundary, formalized.

solver_backend.py declares the contract every solver backend must honor:
run a DeviceSpec JSON job, emit an npz result file with the documented
key grammar and a schema stamp.  The homegrown FD/Newton backend
(gui.services.solver_runner) is the reference implementation; its real
CLI output must pass conformance, and validate_result() must reject
structurally broken files at load time (NpzResultStore fail-fast).

Hand-written minimal fixtures elsewhere in the suite are LEGAL inputs:
validation enforces internal consistency (every field has a unit, sweep
blocks are complete, shapes agree with the axes), never an exhaustive
key inventory.
"""
import json
import os, subprocess, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.device_spec import (
    ContactSpec, DeviceSpec, DopingSpec, MeshSpec, SweepSpec,
)
from gui.services.result_store import NpzResultStore
from gui.services.solver_backend import (
    SOLVER_RESULT_SCHEMA_VERSION, ResultSchemaError, validate_result,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ----------------------------------------------------------------------
#  fixtures: tiny real devices solved through the REAL CLI
# ----------------------------------------------------------------------
def _diode_1d_spec(with_sweep=True):
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
        bias={"left": 0.3, "right": 0.0},
        sweep=SweepSpec(contact="left", start=0.0, stop=0.1, step=0.05)
              if with_sweep else None,
    )


def _resistor_2d_spec():
    x = np.linspace(0.0, 2e-4, 10)
    y = np.linspace(0.0, 1e-4, 6)
    jj = list(range(y.size))
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=2,
                      axes={"x": x.tolist(), "y": y.tolist()}),
        doping=DopingSpec(kind="array",
                          values=np.full((y.size, x.size), 1e17).tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic",
                        nodes={"i": [0] * len(jj), "j": jj}, V=0.0),
            ContactSpec(name="right", kind="ohmic",
                        nodes={"i": [x.size - 1] * len(jj), "j": jj}, V=0.0),
        ],
        bias={"left": 0.05, "right": 0.0},
        sweep=SweepSpec(contact="left", start=0.0, stop=0.1, step=0.05),
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
#  conformance: real CLI output carries the full documented grammar
# ----------------------------------------------------------------------
def test_cli_1d_swept_output_conforms(tmp_path):
    proc, out = _run_cli(_diode_1d_spec(), tmp_path, "diode")
    assert proc.returncode == 0, proc.stderr
    validate_result(out)                     # must not raise

    d = np.load(out)
    assert int(d["result__schema"]) == SOLVER_RESULT_SCHEMA_VERSION
    assert int(d["dimensionality"]) == 1
    assert "solved_bias" in d.files
    # scalar fields + unit companions
    for name in ("potential", "electron_density", "hole_density", "doping"):
        assert d[f"field__{name}"].shape == (40,)
        assert str(d[f"unit__{name}"])
    assert str(d["unit__potential"]) == "V"
    assert str(d["unit__electron_density"]) == "cm^-3"
    # vector current density, node-centered, per-axis + unit
    assert set(d["vector__current_density__x"].shape) == {40}
    assert str(d["unit__current_density"]) == "A/cm^2"
    assert "vector__current_density__y" not in d.files   # 1D has no y axis
    # sweep block
    assert int(d["sweep__voltage"].size) == 3
    assert d["sweep__converged"].dtype == bool
    assert str(d["unit__sweep_current"]) == "A/cm^2"
    meta = json.loads(str(d["sweep__meta"]))
    assert meta["contact"] == "left" and meta["dimensionality"] == 1
    assert "sweep__current__device" in d.files


def test_cli_2d_swept_output_conforms(tmp_path):
    proc, out = _run_cli(_resistor_2d_spec(), tmp_path, "resistor")
    assert proc.returncode == 0, proc.stderr
    validate_result(out)

    d = np.load(out)
    assert int(d["result__schema"]) == SOLVER_RESULT_SCHEMA_VERSION
    assert int(d["dimensionality"]) == 2
    n = 6 * 10
    for key in ("field__potential", "axis_x", "axis_y"):
        assert np.asarray(d[key]).size > 1
    assert d["field__potential"].shape == (6, 10)
    # node-averaged flux DENSITY stays per-area at every dimensionality;
    # the per-unit-depth/current units live on terminals and sweep channels
    assert str(d["unit__current_density"]) == "A/cm^2"
    for comp in ("x", "y"):
        assert d[f"vector__current_density__{comp}"].shape == (6, 10)
    # terminals recorded with units
    for t in ("left", "right"):
        assert f"terminal__{t}__value" in d.files
        assert str(d[f"terminal__{t}__unit"]) == "A/cm"
    # swept channels are named after the ohmic contacts
    meta = json.loads(str(d["sweep__meta"]))
    assert meta["contact"] == "left"
    assert "sweep__current__right" in d.files
    assert str(d["unit__sweep_current"]) == "A/cm"


def test_cli_3d_output_conforms(tmp_path):
    """The grammar documents dim in {1,2,3}; the terminal unit switches
    to real amperes at 3D.  Tiny mesh keeps the real solve fast."""
    x = np.linspace(0.0, 2e-4, 6)
    y = np.linspace(0.0, 1e-4, 4)
    z = np.linspace(0.0, 1e-4, 4)
    jj, kk = np.meshgrid(range(y.size), range(z.size), indexing="ij")
    nodes = {"i": [0] * len(jj.ravel()), "j": jj.ravel().tolist(),
             "k": kk.ravel().tolist()}
    right = dict(nodes)
    right["i"] = [x.size - 1] * len(right["i"])
    spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=3,
                      axes={"x": x.tolist(), "y": y.tolist(),
                            "z": z.tolist()}),
        doping=DopingSpec(
            kind="array",
            values=np.full((z.size, y.size, x.size), 1e17).tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic", nodes=nodes, V=0.0),
            ContactSpec(name="right", kind="ohmic", nodes=right, V=0.0),
        ],
        bias={"left": 0.05, "right": 0.0},
    )
    proc, out = _run_cli(spec, tmp_path, "resistor3d")
    assert proc.returncode == 0, proc.stderr
    validate_result(out)

    d = np.load(out)
    assert int(d["result__schema"]) == SOLVER_RESULT_SCHEMA_VERSION
    assert int(d["dimensionality"]) == 3
    assert d["field__potential"].shape == (z.size, y.size, x.size)
    for comp in ("x", "y", "z"):
        assert d[f"vector__current_density__{comp}"].shape == \
            (z.size, y.size, x.size)
    for t in ("left", "right"):
        assert str(d[f"terminal__{t}__unit"]) == "A"   # real amperes at 3D


# ----------------------------------------------------------------------
#  legacy acceptance: hand-written pre-stamp files remain legal
# ----------------------------------------------------------------------
def _minimal_legacy(path, **extra):
    d = {
        "dimensionality": np.array(1),
        "axis_x": np.array([0.0, 1e-4]),
        "field__potential": np.array([0.0, 1.0]),
        "unit__potential": np.array("V"),
        "solved_bias": np.array(False),
    }
    d.update(extra)
    np.savez(str(path) + ".tmp.npz", **d)
    os.replace(str(path) + ".tmp.npz", str(path))
    return str(path)


def test_legacy_file_without_stamp_is_accepted(tmp_path):
    p = _minimal_legacy(tmp_path / "legacy.npz")
    validate_result(p)                       # no stamp -> treated as v1
    store = NpzResultStore(p)                # and loads fine
    assert store.available_scalars() == ["potential"]


def test_future_schema_version_is_rejected(tmp_path):
    p = _minimal_legacy(tmp_path / "future.npz",
                        result__schema=np.array(SOLVER_RESULT_SCHEMA_VERSION + 5))
    with pytest.raises(ResultSchemaError, match="schema"):
        validate_result(p)
    with pytest.raises(ResultSchemaError):
        NpzResultStore(p)


# ----------------------------------------------------------------------
#  negative cases: structural corruption fails fast, with reasons
# ----------------------------------------------------------------------
def _broken(tmp_path, name, mutate):
    d = {
        "dimensionality": np.array(1),
        "axis_x": np.array([0.0, 1e-4]),
        "field__potential": np.array([0.0, 1.0]),
        "unit__potential": np.array("V"),
        "solved_bias": np.array(True),
    }
    mutate(d)
    p = str(tmp_path / f"{name}.npz")
    np.savez(p + ".tmp.npz", **d)
    os.replace(p + ".tmp.npz", p)
    return p


def test_missing_dimensionality_rejected(tmp_path):
    def m(d):
        del d["dimensionality"]
    with pytest.raises(ResultSchemaError, match="dimensionality"):
        validate_result(_broken(tmp_path, "nodim", m))


def test_field_without_unit_rejected(tmp_path):
    def m(d):
        del d["unit__potential"]
    with pytest.raises(ResultSchemaError, match="unit__potential"):
        validate_result(_broken(tmp_path, "nounit", m))


def test_missing_axis_for_dimensionality_rejected(tmp_path):
    def m(d):
        d["dimensionality"] = np.array(2)     # claims 2D, ships no axis_y
    with pytest.raises(ResultSchemaError, match="axis_y"):
        validate_result(_broken(tmp_path, "badaxes", m))


def test_field_shape_disagreeing_with_axes_rejected(tmp_path):
    def m(d):
        d["field__potential"] = np.zeros(7)   # axes say 2 nodes
    with pytest.raises(ResultSchemaError, match="shape"):
        validate_result(_broken(tmp_path, "badshape", m))


def test_incomplete_sweep_block_rejected(tmp_path):
    def m(d):                                  # voltage without converged
        d["sweep__voltage"] = np.array([0.0, 0.5])
        d["sweep__current__device"] = np.array([0.0, 1.0])
        d["unit__sweep_current"] = np.array("A/cm^2")
        d["sweep__meta"] = np.array(json.dumps(
            {"contact": "left", "dimensionality": 1}))
    with pytest.raises(ResultSchemaError, match="sweep__converged"):
        validate_result(_broken(tmp_path, "badsweep", m))


def test_channel_length_mismatch_rejected(tmp_path):
    def m(d):
        d.update({
            "sweep__voltage": np.array([0.0, 0.5]),
            "sweep__converged": np.array([True, True]),
            "sweep__current__device": np.array([0.0, 1.0, 2.0]),   # 3 != 2
            "unit__sweep_current": np.array("A/cm^2"),
            "sweep__meta": np.array(json.dumps(
                {"contact": "left", "dimensionality": 1})),
        })
    with pytest.raises(ResultSchemaError, match="length"):
        validate_result(_broken(tmp_path, "badlen", m))


def test_terminal_without_unit_rejected(tmp_path):
    def m(d):
        d["terminal__left__value"] = np.array(1e-4)
    with pytest.raises(ResultSchemaError, match="terminal__left__unit"):
        validate_result(_broken(tmp_path, "badterm", m))


def test_missing_solved_bias_rejected(tmp_path):
    """The docstring lists solved_bias as always required -- the
    validator must enforce its own documented grammar, or a second
    backend could omit it forever unnoticed."""
    def m(d):
        del d["solved_bias"]
    with pytest.raises(ResultSchemaError, match="solved_bias"):
        validate_result(_broken(tmp_path, "nobias", m))


def test_orphan_terminal_unit_rejected(tmp_path):
    """Symmetry: a terminal__X__unit without a __value is as malformed
    as a value without a unit."""
    def m(d):
        d["terminal__ghost__unit"] = np.array("A")
    with pytest.raises(ResultSchemaError, match="terminal__ghost__value"):
        validate_result(_broken(tmp_path, "orphanterm", m))


def test_non_npz_file_rejected(tmp_path):
    p = str(tmp_path / "garbage.npz")
    with open(p, "w") as fh:
        fh.write("this is not an npz")
    with pytest.raises(ResultSchemaError):
        validate_result(p)


def test_missing_file_rejected(tmp_path):
    with pytest.raises(ResultSchemaError, match="not found|No such file"):
        validate_result(str(tmp_path / "absent.npz"))


# ----------------------------------------------------------------------
#  NpzResultStore integration: fail-fast on open
# ----------------------------------------------------------------------
def test_npz_store_fails_fast_on_corrupt_file(tmp_path):
    p = _broken(tmp_path, "storecorrupt",
                lambda d: d.pop("unit__potential"))
    with pytest.raises(ResultSchemaError):
        NpzResultStore(p)
