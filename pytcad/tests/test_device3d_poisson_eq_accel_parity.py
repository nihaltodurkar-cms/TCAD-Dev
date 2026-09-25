"""Compiled Device3D equilibrium-Poisson stencil
(_core.device3d_poisson_eq_stencil) vs its Python oracle
device3d._poisson_eq_stencil_py -- np.array_equal on F and on every COO
array, in order (the CSR built from them is then identical too)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

import pytcad.device3d as d3
from pytcad import _accel

pytestmark = pytest.mark.skipif(not _accel.HAVE_ACCEL,
                                reason="pytcad._core not built")


def _fields(shape, rng, uniform_eps):
    Nz, Ny, Nx = shape
    hx, hy, hz = (rng.uniform(1e-3, 2e-2, m - 1) if m > 1 else np.zeros(0)
                  for m in (Nx, Ny, Nz))
    dVx, dVy, dVz = (rng.uniform(1e-3, 2e-2, m) for m in (Nx, Ny, Nz))
    psi = rng.uniform(-30, 30, shape)
    n, p = rng.lognormal(0, 8, shape), rng.lognormal(0, 8, shape)
    C = rng.uniform(-1e3, 1e3, shape)
    dnp = n + p
    dV = dVz[:, None, None] * dVy[None, :, None] * dVx[None, None, :]
    def et(sh):
        return np.ones(sh) if uniform_eps else rng.uniform(0.2, 3.0, sh)
    return (psi, n, p, C, dnp, dV, et((Nz, Ny, Nx - 1)), et((Nz, Ny - 1, Nx)),
            et((Nz - 1, Ny, Nx)), hx, hy, hz, dVx, dVy, dVz)


@pytest.mark.parametrize("shape", [(5, 4, 3), (3, 7, 9), (2, 2, 2), (1, 4, 5), (4, 1, 3)])
@pytest.mark.parametrize("uniform_eps", [True, False])
def test_pe1_kernel_bit_identical_to_oracle(shape, uniform_eps):
    args = _fields(shape, np.random.default_rng(sum(shape)), uniform_eps)
    ref = d3._poisson_eq_stencil_py(*args)
    got = d3._poisson_eq_stencil_accel(*args)
    for name, r, g in zip(("F", "rows", "cols", "vals"), ref, got):
        assert g.shape == r.shape, name
        assert np.array_equal(g, r), (name, np.flatnonzero(g != r)[:5])


@pytest.mark.parametrize("shape", [(5, 4, 3), (3, 7, 9), (2, 2, 2)])
def test_pe1b_boundary_rows_bit_identical_to_oracle(shape):
    """Gate diagonals appended, contact rows replaced -- with duplicate
    gate rows and gate rows that are ALSO contacts (both must drop)."""
    rng = np.random.default_rng(7 + sum(shape))
    args = _fields(shape, rng, uniform_eps=False)
    N = int(np.prod(shape))
    gate_rows = rng.integers(0, N, size=max(3, N // 4))
    gate_rows[:2] = gate_rows[2]                       # duplicates
    gate_vals = rng.uniform(-5, 5, gate_rows.size)
    contact = np.unique(np.concatenate([rng.integers(0, N, size=max(2, N // 5)),
                                        gate_rows[:1]]))  # overlaps a gate row
    for g, gv, c in ((gate_rows, gate_vals, contact),
                     (gate_rows, gate_vals, None),
                     (None, None, contact)):
        ref = d3._poisson_eq_stencil_py(*args, g, gv, c)
        got = d3._poisson_eq_stencil_accel(*args, g, gv, c)
        for name, r, x in zip(("F", "rows", "cols", "vals"), ref, got):
            assert x.shape == r.shape and np.array_equal(x, r), name


def test_pe1c_out_of_range_boundary_index_refused():
    args = _fields((3, 4, 5), np.random.default_rng(3), False)
    with pytest.raises(IndexError):
        d3._poisson_eq_stencil_accel(*args, np.array([60]), np.array([1.0]), None)
    with pytest.raises(IndexError):
        d3._poisson_eq_stencil_accel(*args, None, None, np.array([-1]))


def test_pe2_production_path_is_compiled():
    assert d3._poisson_eq_stencil is d3._poisson_eq_stencil_accel


def test_pe3_real_device_jacobian_identical(monkeypatch):
    from benchmarks import cases
    dev, run = cases.get("B5").build("quick")
    run()
    psi = np.array(dev.psi, copy=True)
    F_c, J_c = dev._residual_jacobian_poisson(psi)
    monkeypatch.setattr(d3, "_poisson_eq_stencil", d3._poisson_eq_stencil_py)
    F_p, J_p = dev._residual_jacobian_poisson(psi)
    assert np.array_equal(F_c, F_p)
    for a in ("data", "indices", "indptr"):
        assert np.array_equal(getattr(J_c, a), getattr(J_p, a)), a


def test_pe4_mismatched_shapes_refused():
    args = list(_fields((3, 4, 5), np.random.default_rng(1), False))
    args[1] = args[1][:, :, :-1]          # n has the wrong shape
    with pytest.raises(ValueError):
        d3._poisson_eq_stencil_accel(*args)
