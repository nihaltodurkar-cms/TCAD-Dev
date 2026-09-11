"""M34-S4: the compiled nonlocal-BTBT path tracer is bit-identical to its
Python oracle.

pytcad.nonlocal_path.build_structured does its array work in numpy and
then runs the per-path stepping loop either as `_trace_paths_py` (the
reference) or as `pytcad._core.trace_paths` (core/src/nonlocal/
paths.cpp), chosen per call by PYTCAD_ACCEL -- the M31 P4 convention.
Every output array must match with np.array_equal: the C++ mirrors the
reference operation for operation (sequential sums, the same products,
upper_bound for bisect_right, Python's min/max replacement rule), and
the translation unit is compiled with -ffp-contract=off.

Skips cleanly where the extension is absent or predates the tracer.
"""
import os
import sys
import warnings

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from pytcad import _accel, Models
from pytcad.materials import SILICON
from pytcad.mesh import graded_mesh
from pytcad.nonlocal_path import build_structured

pytestmark = pytest.mark.skipif(
    not (_accel.HAVE_ACCEL and hasattr(_accel.core, "trace_paths")),
    reason="pytcad._core with trace_paths is not built")

VT = 0.025852
EG_EV = SILICON.Eg(300.0)
FIELDS = ("start", "offset", "sidx", "swts", "seg_len", "gidx", "gwts")


def _both(monkeypatch, coords, psi, mask):
    monkeypatch.setenv("PYTCAD_ACCEL", "0")
    ref = build_structured(coords, psi, VT, EG_EV, mask)
    monkeypatch.setenv("PYTCAD_ACCEL", "1")
    got = build_structured(coords, psi, VT, EG_EV, mask)
    return ref, got


def _assert_identical(ref, got):
    for f in FIELDS:
        a, b = getattr(ref, f), getattr(got, f)
        assert a.shape == b.shape, f"{f}: shape {a.shape} vs {b.shape}"
        assert a.dtype == b.dtype, f"{f}: dtype {a.dtype} vs {b.dtype}"
        assert np.array_equal(a, b), f"{f} differs"


@pytest.mark.parametrize("dim", [2, 3])
def test_diagonal_uniform_field(monkeypatch, dim):
    # small grids: the reference is a pure-Python scalar loop and the
    # fast suite runs it too (PYTCAD_ACCEL=0 CI job)
    g = np.linspace(0.0, 1e-5, 13 if dim == 3 else 25)
    u = np.array([0.3, 0.5, 0.81][:dim])
    u = u / np.linalg.norm(u)
    grids = np.meshgrid(*[g] * dim, indexing="ij")
    psi = 3e5 * sum(ui * G for ui, G in zip(u, grids)) / VT
    ref, got = _both(monkeypatch, [g] * dim, psi,
                     np.zeros(psi.shape, dtype=bool))
    assert ref.n_paths > 0
    _assert_identical(ref, got)


def _junction_2d(noise=0.0):
    """A curved 2D junction field on a graded mesh, contacts on the left
    and right columns: field lines bend around the junction's end."""
    x = graded_mesh(2.0e-5, [1.0e-5], h_min=5e-8, h_max=1e-6)
    y = graded_mesh(1.0e-5, [5.0e-6], h_min=1e-7, h_max=1e-6)
    Y, X = np.meshgrid(y, x, indexing="ij")
    psi = 60.0 * np.tanh((X - 1.0e-5) / 5e-7) * 0.5 * (
        1.0 + np.tanh((5.0e-6 - Y) / 1e-6))
    if noise:
        psi = psi + noise * np.random.default_rng(7).standard_normal(psi.shape)
    mask = np.zeros(psi.shape, dtype=bool)
    mask[:, 0] = mask[:, -1] = True
    return (y, x), psi, mask


def test_curved_2d_junction_with_contacts(monkeypatch):
    coords, psi, mask = _junction_2d()
    ref, got = _both(monkeypatch, coords, psi, mask)
    assert ref.n_paths > 0
    _assert_identical(ref, got)


def test_noisy_field_exercises_the_branches(monkeypatch):
    """Noise makes directions change cell to cell, paths hit faces at
    odd angles and the boundary projection fire -- every branch of the
    stepping loop, compared bit for bit."""
    coords, psi, mask = _junction_2d(noise=0.05)
    ref, got = _both(monkeypatch, coords, psi, mask)
    assert ref.n_paths > 0
    _assert_identical(ref, got)


def test_no_candidate_gives_identical_empty_paths(monkeypatch):
    g = np.linspace(0.0, 1e-5, 11)
    psi = np.zeros((11, 11))
    ref, got = _both(monkeypatch, [g, g], psi, np.zeros(psi.shape, bool))
    assert ref.n_paths == got.n_paths == 0
    _assert_identical(ref, got)


def test_real_device2d_state(monkeypatch):
    """The paths of an actual Device2D solution (an L-shaped p+/n+ corner
    junction at equilibrium) are identical on both paths."""
    from pytcad.device2d import Device2D
    from pytcad.mesh2d import Mesh2D
    x = graded_mesh(1.0e-5, [5.0e-6], h_min=1e-8, h_max=2e-7)
    y = graded_mesh(2.0e-6, [1.0e-6], h_min=2e-8, h_max=2e-7)
    Y, X = np.meshgrid(y, x, indexing="ij")
    dop = np.where((X > 5.0e-6) & (Y < 1.0e-6), 5e19, -5e19)
    dev = Device2D(Mesh2D(x, y), dop, T=300.0,
                   models=Models(bgn=False, srh=True, btbt_nonlocal=True))
    dev.add_contact("left", i=[0], j=list(range(y.size)), V=0.0)
    dev.add_contact("right", i=[x.size - 1],
                    j=[j for j in range(y.size) if y[j] < 1.0e-6], V=0.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev.solve_equilibrium()
    monkeypatch.setenv("PYTCAD_ACCEL", "0")
    ref = dev._btbt_nl_build_paths(dev.psi)
    monkeypatch.setenv("PYTCAD_ACCEL", "1")
    got = dev._btbt_nl_build_paths(dev.psi)
    assert ref.n_paths > 0
    _assert_identical(ref, got)


def test_malformed_input_raises_instead_of_reading_out_of_bounds():
    g = np.linspace(0.0, 1e-5, 5)
    psi = np.zeros(25)
    grads = np.zeros((2, 25))
    ok = dict(coords=np.concatenate([g, g]), shape=np.array([5, 5], np.int64),
              psi=psi, grads=grads, cand=np.array([0], np.int64),
              contact=np.zeros(25, bool), VT=VT, Eg_eV=EG_EV,
              screen_Vcm=1e3, margin=1.5, max_steps=10, hmin_all=2.5e-6)
    _accel.core.trace_paths(**ok)                       # well-formed: fine
    with pytest.raises(Exception, match="psi"):
        _accel.core.trace_paths(**{**ok, "psi": np.zeros(24)})
    with pytest.raises(Exception, match="out of range"):
        _accel.core.trace_paths(**{**ok, "cand": np.array([25], np.int64)})
