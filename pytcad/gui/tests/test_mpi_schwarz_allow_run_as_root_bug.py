"""Regression test for a real, pre-existing bug found while cross-
checking the 3D examples' exploded view against the real GUI:
pn_junction_3d and bjt_3d are large enough (>20,000 nodes) to
auto-route through solver_runner.py's MPI Schwarz engine, and that
path failed OUTRIGHT on this machine:

    mpirun --allow-run-as-root -np 4 python -m ...
    [mpiexec] match_arg: unrecognized argument allow-run-as-root

Root cause: _solve_via_mpi_schwarz() hardcoded "--allow-run-as-root"
unconditionally. That flag is Open MPI-specific (Open MPI refuses to
run as root without it); this machine's `mpirun` is MPICH's Hydra
process manager (confirmed directly: `mpirun --version` prints "HYDRA
build details", never "Open MPI"), which has no such flag at all and
refuses to start with any job given it -- regardless of whether the
process is actually running as root (this machine wasn't: `id -u` is
1000, not 0). So the ORIGINAL bug wasn't really about root at all --
it was an MPI-implementation-specific flag hardcoded for the "wrong"
(but very common, e.g. any conda `mpi4py`+`mpich` install) MPI stack.

Fixed by detecting the actual mpirun implementation once (via its own
--version banner) and only adding the flag for a real Open MPI.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.device_spec import ContactSpec, DeviceSpec, DopingSpec, MeshSpec
from gui.services import solver_runner
from gui.services.solver_runner import _HAVE_MPI, run_job


def test_openmpi_detection_reads_the_version_banner(monkeypatch):
    monkeypatch.setattr(solver_runner, "_mpirun_is_openmpi_cache", None)

    class _FakeCompleted:
        def __init__(self, stdout):
            self.stdout = stdout

    monkeypatch.setattr(
        solver_runner.subprocess, "run",
        lambda *a, **k: _FakeCompleted("HYDRA build details:\n    Version: 4.3.2\n"))
    assert solver_runner._mpirun_is_openmpi() is False

    monkeypatch.setattr(solver_runner, "_mpirun_is_openmpi_cache", None)
    monkeypatch.setattr(
        solver_runner.subprocess, "run",
        lambda *a, **k: _FakeCompleted("mpirun (Open MPI) 4.1.6\n\nReport bugs to ...\n"))
    assert solver_runner._mpirun_is_openmpi() is True


def test_openmpi_detection_is_cached_not_reshelled_out(monkeypatch):
    monkeypatch.setattr(solver_runner, "_mpirun_is_openmpi_cache", None)
    calls = []

    class _FakeCompleted:
        stdout = "HYDRA build details:\n"

    def _fake_run(*a, **k):
        calls.append(1)
        return _FakeCompleted()

    monkeypatch.setattr(solver_runner.subprocess, "run", _fake_run)
    solver_runner._mpirun_is_openmpi()
    solver_runner._mpirun_is_openmpi()
    solver_runner._mpirun_is_openmpi()
    assert len(calls) == 1


def test_mpi_schwarz_command_omits_the_flag_for_mpich(monkeypatch, tmp_path):
    monkeypatch.setattr(solver_runner, "_mpirun_is_openmpi_cache", False)
    seen_cmd = {}

    class _FakeProc:
        returncode = 1     # doesn't matter -- captured before this is read
        stdout = iter(["PYTCAD_STAGE=equilibrium\n"])
        def wait(self): pass

    def _fake_popen(cmd, **kwargs):
        seen_cmd["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(solver_runner.subprocess, "Popen", _fake_popen)
    with pytest.raises(RuntimeError):
        solver_runner._solve_via_mpi_schwarz(str(tmp_path / "job.json"), "x")
    assert "--allow-run-as-root" not in seen_cmd["cmd"]
    assert seen_cmd["cmd"][0] == "mpirun"


def test_mpi_schwarz_command_includes_the_flag_for_openmpi(monkeypatch, tmp_path):
    monkeypatch.setattr(solver_runner, "_mpirun_is_openmpi_cache", True)
    seen_cmd = {}

    class _FakeProc:
        returncode = 1
        stdout = iter(["PYTCAD_STAGE=equilibrium\n"])
        def wait(self): pass

    def _fake_popen(cmd, **kwargs):
        seen_cmd["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(solver_runner.subprocess, "Popen", _fake_popen)
    with pytest.raises(RuntimeError):
        solver_runner._solve_via_mpi_schwarz(str(tmp_path / "job.json"), "x")
    assert "--allow-run-as-root" in seen_cmd["cmd"]


@pytest.mark.skipif(not _HAVE_MPI, reason="mpi4py/mpirun not available")
def test_forced_mpi_schwarz_actually_completes_on_a_real_tiny_device(tmp_path):
    """The end-to-end regression guard: a genuine mpirun subprocess
    invocation, on a small-but-qualifying uniform 3D resistor (forced
    via spec.engine, so this doesn't need a 20,000+-node mesh to
    exercise the real path) -- this is exactly the invocation that
    failed outright before this fix, on any machine whose mpirun is
    MPICH rather than Open MPI."""
    nx, ny, nz = 12, 6, 6
    x = np.linspace(0.0, 2e-4, nx)
    y = np.linspace(0.0, 1e-4, ny)
    z = np.linspace(0.0, 1e-4, nz)
    doping = np.full((nz, ny, nx), 1e17)
    jj, kk = np.meshgrid(np.arange(ny), np.arange(nz))
    jj, kk = jj.ravel().tolist(), kk.ravel().tolist()
    spec = DeviceSpec(
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
        engine="mpi_schwarz",
    )
    job = str(tmp_path / "job.json")
    out = str(tmp_path / "out.npz")
    spec.to_json(job)
    run_job(job, out)     # must not raise
    import json
    meta = json.loads(str(np.load(out)["record__meta"]))
    assert meta["numerics"]["engine"] == "mpi_schwarz"
