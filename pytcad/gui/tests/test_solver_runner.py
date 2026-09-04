"""solver_runner is the process boundary: it must produce a complete,
normalized .npz from a DeviceSpec, and must leave NO file at the
canonical output path if it is killed partway (cancellation safety).

Meshes here are deliberately tiny.  A GUI test suite must stay fast, and
the 3D solver core work already established that mesh sizes which are
fine in 1D/2D become pathological when carried up a dimension.
"""
import os, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.device_spec import MeshSpec, DopingSpec, ContactSpec, DeviceSpec

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _diode_1d_spec():
    x = np.linspace(0.0, 2e-4, 40)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
            ContactSpec(name="right", kind="ohmic", nodes={"i": [len(x) - 1]}, V=0.0),
        ],
        bias={"left": 0.3, "right": 0.0},
    )


def _resistor_2d_spec():
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
        bias={"left": 0.05, "right": 0.0},
    )


def _run_cli(spec, tmp_path, name):
    job = str(tmp_path / f"{name}.json")
    out = str(tmp_path / f"{name}.npz")
    spec.to_json(job)
    proc = subprocess.run(
        [sys.executable, "-m", "gui.services.solver_runner", job, out],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300)
    return proc, out


def test_1d_job_produces_normalized_npz(tmp_path):
    proc, out = _run_cli(_diode_1d_spec(), tmp_path, "diode")
    assert proc.returncode == 0, proc.stderr
    assert os.path.exists(out)
    d = np.load(out)

    assert int(d["dimensionality"]) == 1
    assert d["axis_x"].size == 40
    for key in ("potential", "electron_density", "hole_density", "doping"):
        assert d[f"field__{key}"].shape == (40,)
        assert str(d[f"unit__{key}"]) != ""
    assert str(d["unit__potential"]) == "V"
    assert str(d["unit__electron_density"]) == "cm^-3"
    # current density is node-centered, one component in 1D
    assert d["vector__current_density__x"].shape == (40,)
    assert "vector__current_density__y" not in d
    assert bool(d["solved_bias"]) is True
    # Device1D has no terminal_current -- no terminal entries in 1D
    assert not [k for k in d.files if k.startswith("terminal__")]


def test_2d_job_normalizes_terminal_current_units(tmp_path):
    proc, out = _run_cli(_resistor_2d_spec(), tmp_path, "res2d")
    assert proc.returncode == 0, proc.stderr
    d = np.load(out)

    assert int(d["dimensionality"]) == 2
    assert d["field__potential"].shape == (8, 12)      # (Ny, Nx)
    assert d["vector__current_density__x"].shape == (8, 12)
    assert d["vector__current_density__y"].shape == (8, 12)
    # 2D terminal current is per unit depth
    assert str(d["terminal__left__unit"]) == "A/cm"
    assert np.isfinite(float(d["terminal__left__value"]))
    # two contacts of a two-terminal device must nearly cancel
    il = float(d["terminal__left__value"])
    ir = float(d["terminal__right__value"])
    assert abs(il + ir) / max(abs(il), abs(ir)) < 1e-6


def test_equilibrium_only_when_bias_is_none(tmp_path):
    spec = _diode_1d_spec()
    spec.bias = None
    proc, out = _run_cli(spec, tmp_path, "eq_only")
    assert proc.returncode == 0, proc.stderr
    d = np.load(out)
    assert bool(d["solved_bias"]) is False
    assert d["field__potential"].shape == (40,)
    # no current density without a bias solve
    assert "vector__current_density__x" not in d


def test_backend_field_defaults_to_pytcad_for_old_jobs(tmp_path):
    """Additive wire-format field: a job JSON written before "backend"
    existed simply lacks the key and must still dispatch to pytcad."""
    job = str(tmp_path / "old.json")
    out = str(tmp_path / "old.npz")
    d = _diode_1d_spec().to_dict()
    assert "backend" in d      # sanity: the field exists on a fresh spec
    del d["backend"]           # simulate a pre-2c job file
    import json
    json.dump(d, open(job, "w"))
    proc = subprocess.run(
        [sys.executable, "-m", "gui.services.solver_runner", job, out],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(str(np.load(out)["record__meta"]))["backend"] == "pytcad"


def test_backend_field_dispatches_to_devsim(tmp_path):
    # devsim's own __init__ raises RuntimeError (not ImportError) when its
    # native BLAS/LAPACK libraries are missing, so plain importorskip lets
    # that escape as a hard failure on a devsim-installed-but-unusable
    # sandbox -- catch both so a genuinely broken devsim install skips
    # instead of failing this unrelated GUI-dispatch test.
    try:
        import devsim  # noqa: F401
    except ImportError:
        pytest.skip("optional devsim dependency not installed")
    except RuntimeError as exc:
        pytest.skip(f"devsim installed but failed to initialize: {exc}")
    spec = _diode_1d_spec()
    spec.bias = {"left": 0.0, "right": 0.0}    # devsim needs both contacts named
    spec.backend = "devsim"
    proc, out = _run_cli(spec, tmp_path, "devsim_dispatch")
    assert proc.returncode == 0, proc.stderr
    import json
    assert json.loads(str(np.load(out)["record__meta"]))["backend"] == "devsim"


def test_bad_spec_exits_nonzero_with_message(tmp_path):
    spec = _resistor_2d_spec()
    spec.models["field_mobility"] = True      # NotImplementedError in Device2D
    proc, out = _run_cli(spec, tmp_path, "bad")
    assert proc.returncode != 0
    assert not os.path.exists(out)
    assert "field" in proc.stderr.lower() or "NotImplementedError" in proc.stderr


# ---------------------------------------------------------------- v0.6 Phase 2d: engine override
def _tiny_resistor_3d_spec(nx=6, ny=6, nz=6):
    """Uniform-doping, ohmic-only, no-gates 3D slab -- deliberately
    below MPI_SCHWARZ_RANKS*2 nodes on every axis, so
    _pick_mpi_split_axis has no qualifying candidate regardless of
    doping uniformity (see its own node-count filter)."""
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
        contacts=[
            ContactSpec(name="left", kind="ohmic",
                        nodes={"i": [0] * len(jj), "j": jj, "k": kk}, V=0.0),
            ContactSpec(name="right", kind="ohmic",
                        nodes={"i": [nx - 1] * len(jj), "j": jj, "k": kk}, V=0.0),
        ],
        bias={"left": 0.05, "right": 0.0},
    )


def test_engine_field_defaults_to_auto_for_old_jobs(tmp_path):
    """Additive wire-format field (mirrors the "backend" field's own
    pre-2c-job test above): a job JSON written before "engine" existed
    simply lacks the key and must still run the unchanged auto
    heuristic, not raise on a missing key."""
    job = str(tmp_path / "old_engine.json")
    out = str(tmp_path / "old_engine.npz")
    d = _diode_1d_spec().to_dict()
    assert "engine" in d      # sanity: the field exists on a fresh spec
    del d["engine"]           # simulate a pre-2d job file
    import json
    json.dump(d, open(job, "w"))
    proc = subprocess.run(
        [sys.executable, "-m", "gui.services.solver_runner", job, out],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    numerics = json.loads(str(np.load(out)["record__meta"]))["numerics"]
    assert numerics["linsolve"] == "direct"    # this tiny 1D job's auto choice


def test_engine_direct_is_forced_regardless_of_auto_heuristic(tmp_path):
    spec = _diode_1d_spec()
    spec.engine = "direct"
    proc, out = _run_cli(spec, tmp_path, "engine_direct")
    assert proc.returncode == 0, proc.stderr
    import json
    numerics = json.loads(str(np.load(out)["record__meta"]))["numerics"]
    assert numerics["linsolve"] == "direct"


def test_engine_unknown_value_refuses_loudly(tmp_path):
    spec = _diode_1d_spec()
    spec.engine = "quantum_annealing"
    proc, out = _run_cli(spec, tmp_path, "engine_bogus")
    assert proc.returncode != 0
    assert not os.path.exists(out)
    assert "unknown engine" in proc.stderr.lower()


def test_engine_gpu_direct_matches_cupy_availability(tmp_path):
    from pytcad.linsolve import _HAVE_CUPY
    spec = _diode_1d_spec()
    spec.engine = "gpu_direct"
    proc, out = _run_cli(spec, tmp_path, "engine_gpu")
    if _HAVE_CUPY:
        assert proc.returncode == 0, proc.stderr
        import json
        numerics = json.loads(str(np.load(out)["record__meta"]))["numerics"]
        assert numerics["linsolve"] == "gpu_direct"
    else:
        assert proc.returncode != 0
        assert not os.path.exists(out)
        assert "cupy" in proc.stderr.lower()


def test_engine_amg_matches_pyamg_availability(tmp_path):
    from pytcad.linsolve import _HAVE_PYAMG
    spec = _diode_1d_spec()
    spec.engine = "amg"
    proc, out = _run_cli(spec, tmp_path, "engine_amg")
    if _HAVE_PYAMG:
        assert proc.returncode == 0, proc.stderr
        import json
        numerics = json.loads(str(np.load(out)["record__meta"]))["numerics"]
        assert numerics["linsolve"] == "bicgstab"
    else:
        assert proc.returncode != 0
        assert not os.path.exists(out)
        assert "pyamg" in proc.stderr.lower()


def test_engine_mpi_schwarz_refuses_on_a_2d_device(tmp_path):
    """Dimensionality is checked before the mpi4py/mpirun availability
    check (see run_job's override block), so this refuses identically
    regardless of whether MPI is installed in this environment."""
    spec = _resistor_2d_spec()
    spec.engine = "mpi_schwarz"
    proc, out = _run_cli(spec, tmp_path, "engine_mpi_2d")
    assert proc.returncode != 0
    assert not os.path.exists(out)
    assert "3d" in proc.stderr.lower() or "3D" in proc.stderr


def test_engine_mpi_schwarz_refuses_without_a_safe_split_axis(tmp_path):
    """A genuinely too-small-on-every-axis 3D device: whether this
    environment has mpi4py/mpirun or not, the request must still be
    refused (with a different, but equally precise, reason each way)
    rather than silently falling back to a different engine."""
    from gui.services.solver_runner import _HAVE_MPI
    spec = _tiny_resistor_3d_spec()
    spec.engine = "mpi_schwarz"
    proc, out = _run_cli(spec, tmp_path, "engine_mpi_no_axis")
    assert proc.returncode != 0
    assert not os.path.exists(out)
    if _HAVE_MPI:
        assert "safe" in proc.stderr.lower() and "split" in proc.stderr.lower()
    else:
        assert "mpi4py" in proc.stderr.lower() or "mpirun" in proc.stderr.lower()


def test_engine_mpi_schwarz_refuses_with_an_armed_transient(tmp_path):
    from gui.services.device_spec import TransientSpec, WaveformSpec
    spec = _tiny_resistor_3d_spec(nx=12)   # a real qualifying split axis
    spec.engine = "mpi_schwarz"
    spec.transient = TransientSpec(
        contact="left", waveform=WaveformSpec(kind="constant", v0=0.05),
        t_end=1e-9, dt0=1e-10)
    proc, out = _run_cli(spec, tmp_path, "engine_mpi_transient")
    assert proc.returncode != 0
    assert not os.path.exists(out)
    assert "transient" in proc.stderr.lower()


def test_kill_leaves_no_file_at_canonical_path(tmp_path):
    """Cancellation safety: the result is written to <out>.tmp and only
    atomically renamed on success, so a killed run can never leave a
    partial file where a reader would find it."""
    x = np.linspace(0.0, 2e-4, 26)
    y = np.linspace(0.0, 1e-4, 22)
    z = np.linspace(0.0, 1e-4, 22)
    doping = np.full((z.size, y.size, x.size), 1e17)
    jj, kk = np.meshgrid(np.arange(y.size), np.arange(z.size))
    jj, kk = jj.ravel().tolist(), kk.ravel().tolist()
    spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=3,
                      axes={"x": x.tolist(), "y": y.tolist(), "z": z.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic",
                        nodes={"i": [0] * len(jj), "j": jj, "k": kk}, V=0.0),
            ContactSpec(name="right", kind="ohmic",
                        nodes={"i": [x.size - 1] * len(jj), "j": jj, "k": kk}, V=0.0),
        ],
        bias={"left": 0.05, "right": 0.0},
    )
    job = str(tmp_path / "big.json")
    out = str(tmp_path / "big.npz")
    spec.to_json(job)
    proc = subprocess.Popen(
        [sys.executable, "-m", "gui.services.solver_runner", job, out],
        cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(2.0)          # let it get well into the solve
    assert proc.poll() is None, "test mesh finished too fast to test cancellation"
    proc.kill()
    proc.wait(timeout=30)
    assert not os.path.exists(out), "a killed run must leave no canonical result file"
