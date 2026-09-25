"""Compiled nonlocal-BTBT path evaluation (_core.evaluate_paths through
nonlocal_path.evaluate) vs its pure-Python oracle nonlocal_path.
_evaluate_py: every PathEval field np.array_equal, and the two CSR
matrices identical in data/indices/indptr.

Covers 1D (Device1D), 2D (B10's corner junction) and 3D paths -- 3D
matters on its own: its 8-/9-point stencil sums take numpy's pairwise
reduction branch, the 1D/2D ones the sequential branch -- at the
converged potential and at perturbed ones, which flip which paths reach
the delta = 1 crossing and which km^2 branch is active."""
import os, sys, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

import pytcad.device as d1mod
import pytcad.device2d as d2mod
import pytcad.device3d as d3mod
from pytcad import _accel, nonlocal_path
from pytcad import Device1D, Models, NewtonOptions
from pytcad.device3d import Device3D
from pytcad.mesh import graded_mesh
from pytcad.mesh3d import Mesh3D

pytestmark = pytest.mark.skipif(not _accel.HAVE_ACCEL,
                                reason="pytcad._core not built")

X = graded_mesh(1.0e-5, [5.0e-6], h_min=1e-8, h_max=2e-7)
DOP = np.where(X < 5.0e-6, -5e19, 5e19)
NL = Models(bgn=False, srh=True, btbt_nonlocal=True)


def _captured_args(dev, module):
    """Solve to get live paths, then capture the exact evaluate() call."""
    seen = []
    real = module._nl_evaluate

    def spy(*a, **k):
        seen.append((a, k))
        return real(*a, **k)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        module._nl_evaluate = spy
        try:
            dev.solve_equilibrium()
            if isinstance(dev, Device1D):
                dev.solve_bias([-1.0, 0.0], NewtonOptions())
            else:
                dev.solve_bias({"left": -1.0, "right": 0.0})
        finally:
            module._nl_evaluate = real
    assert seen, "no nonlocal evaluation happened"
    a, k = seen[-1]
    assert a[0].n_paths > 0
    return a, k


def _dev1d():
    return Device1D(X, DOP, T=300.0, models=NL), d1mod


def _dev2d():
    from benchmarks import cases
    dev, _ = cases.get("B10").build("quick")
    return dev, d2mod


def _dev3d():
    yz = np.linspace(0.0, 1e-6, 2)
    d = Device3D(Mesh3D(x=X, y=yz, z=yz), np.tile(DOP, (2, 2, 1)), T=300.0,
                 models=NL)
    jj, kk = np.meshgrid(range(2), range(2), indexing="ij")
    j, k = jj.ravel().tolist(), kk.ravel().tolist()
    d.add_contact("left", i=[0] * 4, j=j, k=k, V=0.0)
    d.add_contact("right", i=[X.size - 1] * 4, j=j, k=k, V=0.0)
    return d, d3mod


FIELDS = ("G", "Ik", "Iik", "reached", "length", "fmin", "fmax",
          "ddep_p", "ddep_node", "ddep_col", "ddep_val")


def _assert_identical(got, ref):
    for f in FIELDS:
        a, b = getattr(got, f), getattr(ref, f)
        assert a.dtype == b.dtype, (f, a.dtype, b.dtype)
        assert a.shape == b.shape, (f, a.shape, b.shape)
        same = (a == b) | (np.isnan(a) & np.isnan(b)) if a.dtype.kind == "f" else a == b
        assert np.all(same), (f, np.flatnonzero(~same)[:5])
    for f in ("dG", "dep"):
        a, b = getattr(got, f), getattr(ref, f)
        assert a.shape == b.shape, f
        for attr in ("data", "indices", "indptr"):
            assert np.array_equal(getattr(a, attr), getattr(b, attr)), (f, attr)


@pytest.mark.parametrize("build", [_dev1d, _dev2d, _dev3d], ids=["1d", "2d", "3d"])
def test_ne1_evaluate_bit_identical_to_oracle(build):
    dev, module = build()
    args, kwargs = _captured_args(dev, module)
    paths, psi = args[0], np.asarray(args[1], dtype=float)
    rest = args[2:]
    rng = np.random.default_rng(42)
    reached_states = set()
    for scale in (0.0, 0.5, 3.0, 12.0):
        p = psi + scale * rng.standard_normal(psi.shape)
        ref = nonlocal_path._evaluate_py(paths, p, *rest, **kwargs)
        got = nonlocal_path.evaluate(paths, p, *rest, **kwargs)
        _assert_identical(got, ref)
        reached_states.add((bool(ref.reached.all()), bool(ref.reached.any())))
    # the perturbations must actually have exercised the not-reached branch
    assert len(reached_states) > 1 or not all(r for r, _ in reached_states)


def test_ne2_device_paths_use_the_compiled_evaluate():
    for module in (d1mod, d2mod, d3mod):
        assert module._nl_evaluate is nonlocal_path.evaluate


def test_ne3_malformed_paths_refused():
    dev, module = _dev2d()
    args, kwargs = _captured_args(dev, module)
    paths = args[0]
    import dataclasses
    bad = dataclasses.replace(paths, sidx=paths.sidx.copy())
    bad.sidx[0, 0] = 10 ** 9                              # out-of-range node
    with pytest.raises(IndexError):
        nonlocal_path.evaluate(bad, *args[1:], **kwargs)
    short = dataclasses.replace(paths, seg_len=paths.seg_len[:-1])
    with pytest.raises(ValueError):
        nonlocal_path.evaluate(short, *args[1:], **kwargs)
