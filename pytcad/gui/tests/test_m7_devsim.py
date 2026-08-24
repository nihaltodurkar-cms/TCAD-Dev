"""M7 acceptance tests: DEVSIM backend (ARCHITECTURE.md revised roadmap,
milestone M7).

The validation gate: the SAME pn-diode DeviceSpec solved by BOTH the
pytcad backend and the DEVSIM backend must agree on the equilibrium
potential profile (same nodes, same silicon physics, different
discretization engines), and both built-in-potential drops must match
the analytic value.  Skipped cleanly when devsim is not installed.
"""
import json, os, subprocess, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

devsim_spec = pytest.importorskip(
    "devsim", reason="optional devsim dependency not installed")

from gui.services.solver_backend import validate_result
from workbench.solvers.base import backend_ids, get_backend


@pytest.fixture(scope="module")
def diode_job(tmp_path_factory):
    # a SYMMETRIC abrupt 1D junction: the analytic built-in potential is
    # known, and the pytcad backend solves it natively too
    from gui.services.device_spec import (
        ContactSpec, DeviceSpec, DopingSpec, MeshSpec,
    )
    x = np.linspace(0.0, 2e-4, 60)
    doping = np.where(x < 1e-4, -1e18, 1e18)
    spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
            ContactSpec(name="right", kind="ohmic",
                        nodes={"i": [x.size - 1]}, V=0.0),
        ],
        bias={"left": 0.0, "right": 0.0},
    )
    d = tmp_path_factory.mktemp("m7")
    job = str(d / "diode.json")
    spec.to_json(job)
    return job


@pytest.fixture(scope="module")
def run_both(diode_job, tmp_path_factory):
    out = {}
    for bid in ("pytcad", "devsim"):
        path = str(tmp_path_factory.mktemp(bid) / "result.npz")
        get_backend(bid).run(__import__(
            "workbench.solvers.base", fromlist=["SolveRequest"]
        ).SolveRequest(job_json_path=diode_job, out_npz_path=path))
        out[bid] = np.load(path)
    return out


def test_devsim_registered():
    assert "devsim" in backend_ids()


def test_devsim_output_is_schema_valid(diode_job, tmp_path_factory):
    from gui.services.solver_backend import validate_result
    out = str(tmp_path_factory.mktemp("vs") / "r.npz")
    get_backend("devsim").run(
        __import__("workbench.solvers.base",
                   fromlist=["SolveRequest"]).SolveRequest(
            job_json_path=diode_job, out_npz_path=out))
    validate_result(out)


def test_both_backends_stamp_v2_and_backend_id(run_both):
    for bid, d in run_both.items():
        assert int(d["result__schema"]) == 2
        assert str(json.loads(str(d["record__meta"]))["backend"]) == bid


def test_cross_backend_equilibrium_potential_agrees(run_both):
    a = np.asarray(run_both["pytcad"]["field__potential"], dtype=float)
    b = np.asarray(run_both["devsim"]["field__potential"], dtype=float)
    assert a.shape == b.shape
    # same equations on the same nodes.  The ENGINES ship slightly
    # different tabulated silicon constants (notably ni), which shifts
    # each solution by a few-tens-of-mV offset -- hence the analytic
    # Vbi gate above plus this absolute bound, not exact equality.
    assert np.allclose(a, b, atol=2.5e-2), \
        f"max |dpsi| = {np.max(np.abs(a - b)):.4g} V"


def test_both_backends_match_analytic_builtin_potential(run_both):
    from pytcad.constants import KB_EV
    ni = 1.5e10
    vbi = 2 * KB_EV * 300 * np.log(1e18 / ni)
    for bid, d in run_both.items():
        psi = np.asarray(d["field__potential"], dtype=float)
        drop = float(psi[-1] - psi[0])
        assert abs(abs(drop) - vbi) < 0.05 * vbi, \
            f"{bid}: |{drop:.4f}| vs Vbi {vbi:.4f} V"


def test_devsim_refuses_nonzero_bias_honestly(diode_job, tmp_path):
    from gui.services.device_spec import DeviceSpec
    from workbench.solvers.base import SolveRequest
    spec = DeviceSpec.from_json(diode_job)
    spec.bias = {"left": 0.0, "right": 0.3}
    job2 = str(tmp_path / "biased.json")
    spec.to_json(job2)
    with pytest.raises(ValueError, match="EQUILIBRIUM only"):
        get_backend("devsim").run(SolveRequest(
            job_json_path=job2, out_npz_path=str(tmp_path / "b.npz")))
