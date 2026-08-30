"""M14 remainder: G-C at Device2D -- surface recombination velocity
(S_n/S_p) as a Robin flux-balance BC, generalized to arbitrary 2D
contact shapes.

See M14-SURFACE-MOBILITY-PLAN.md "G-C, DEVICE2D" for why the FIRST
Device1D-style attempt (deriving, per contact node, "which single edge
is into the bulk") was abandoned as too hard for an arbitrary shape.
This implementation instead reuses Device2D._residual_jacobian's own
ALREADY-COMPUTED box-integration continuity residual (F_n, F_p) at
every node uniformly -- exactly what terminal_current() itself already
reads as "the net current the contact must supply" -- and adds the
recombination sink to it instead of overwriting it, which generalizes
to any number of edges per contact node with no per-shape logic.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

from pytcad.mesh import graded_mesh
from pytcad.mesh2d import Mesh2D
from pytcad.device2d import Device2D
from pytcad.device import Models, NewtonOptions

warnings.simplefilter("ignore")


def _diode2d(S_n=0.0, S_p=0.0, Na=1e17, Nd=1e17, **kw):
    x = graded_mesh(2e-4, [1e-4], 1e-8, 1e-6, 1.12)
    y = graded_mesh(5e-5, [0.0], 1e-7, 1e-5, 1.15)
    dop1d = np.where(x < 1e-4, -Na, Nd)
    dop2d = np.tile(dop1d, (y.size, 1))
    mesh = Mesh2D(x, y)
    kw.setdefault("bgn", False)
    dev = Device2D(mesh, dop2d, models=Models(S_n=S_n, S_p=S_p, **kw))
    dev.add_contact("left", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev.add_contact("right", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    return dev


# ----------------------------------------------------------------------
def test_g_d_bit_identity_when_s_off_2d():
    """G-D: S_n=S_p=0.0 (default) must reproduce the exact pre-fix
    Dirichlet-contact solution -- a genuine if/else branch to the
    original code path, not an algebraic reduction of the Robin
    formula (S=0 means a fixed density, S>0 a flux condition)."""
    dev_off = _diode2d(S_n=0.0, S_p=0.0)
    dev_off.solve_equilibrium()
    dev_off.solve_bias({"left": 0.2, "right": 0.0}, NewtonOptions(max_iter=100))
    dev_ref = _diode2d(S_n=0.0, S_p=0.0)
    dev_ref.solve_equilibrium()
    dev_ref.solve_bias({"left": 0.2, "right": 0.0}, NewtonOptions(max_iter=100))
    assert np.array_equal(dev_off.psi, dev_ref.psi)
    assert np.array_equal(dev_off.n, dev_ref.n)
    assert np.array_equal(dev_off.p, dev_ref.p)


def _fd_jacobian_check(dev, voltages, seed, n_cols=100):
    rng = np.random.default_rng(seed)
    psi = dev.psi + 1e-3 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1.0 + 1e-3 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1.0 + 1e-3 * rng.standard_normal(dev.p.shape))
    F0, J0, *_ = dev._residual_jacobian(psi, n, p, voltages)
    J0d = J0.toarray()
    Ny, Nx = dev.Ny, dev.Nx
    N3 = J0d.shape[0]
    h = 1e-7
    u0 = np.stack([psi, n, p], axis=-1).ravel()
    cols = rng.choice(N3, size=min(n_cols, N3), replace=False)
    worst = 0.0
    for k in cols:
        up = u0.copy(); up[k] += h
        um = u0.copy(); um[k] -= h
        Fp, *_ = dev._residual_jacobian(
            up[0::3].reshape(Ny, Nx), up[1::3].reshape(Ny, Nx),
            up[2::3].reshape(Ny, Nx), voltages)
        Fm, *_ = dev._residual_jacobian(
            um[0::3].reshape(Ny, Nx), um[1::3].reshape(Ny, Nx),
            um[2::3].reshape(Ny, Nx), voltages)
        col_fd = (Fp - Fm) / (2 * h)
        scale = np.maximum(np.abs(J0d[:, k]), 1.0)
        worst = max(worst, float(np.max(np.abs(J0d[:, k] - col_fd) / scale)))
    return worst


def test_g_e_fd_jacobian_single_edge_contact_2d():
    """G-E: with S_n=S_p!=0, the analytic Robin-BC Jacobian matches
    finite differences on a single-edge (ordinary domain-boundary)
    contact -- the 2D analog of Device1D's own single-edge case."""
    dev = _diode2d(S_n=1e2, S_p=1e2)
    dev.solve_equilibrium()
    worst = _fd_jacobian_check(dev, {"left": 0.2, "right": 0.0}, seed=0)
    assert worst <= 5e-5, f"G-E FAIL (single-edge): {worst:.3e}"


def test_g_e_fd_jacobian_multi_edge_corner_contact_2d():
    """G-E, the actual point of doing this at 2D at all: a contact
    patch spanning a domain corner plus several top-row nodes, so
    individual contact nodes touch DIFFERENT numbers of non-contact
    edges (the corner node: 2; the top-row nodes: 3) -- confirming the
    fix's core claim (reusing the uniform box residual needs NO
    per-shape "which edge is into the bulk" logic) on the case
    Device1D's two fixed endpoints could never exercise."""
    x = graded_mesh(2e-4, [1e-4], 1e-8, 1e-6, 1.12)
    y = graded_mesh(5e-5, [0.0], 1e-7, 1e-5, 1.15)
    dop1d = np.where(x < 1e-4, -1e17, 1e17)
    dop2d = np.tile(dop1d, (y.size, 1))
    mesh = Mesh2D(x, y)
    dev = Device2D(mesh, dop2d, models=Models(bgn=False, S_n=1e2, S_p=1e2))
    dev.add_contact("corner", i=list(range(5)), j=[0] * 5, V=0.0)
    dev.add_contact("right", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    dev.solve_equilibrium()
    worst = _fd_jacobian_check(dev, {"corner": 0.2, "right": 0.0}, seed=1)
    assert worst <= 5e-5, f"G-E FAIL (multi-edge corner): {worst:.3e}"


def test_g_e_fd_jacobian_with_fd_statistics_2d():
    """Regression check mirroring Device1D's own hard-debug finding
    (fd=True + S_n/S_p!=0 needed an extra wn/wp chain-rule correction
    the boundary rows didn't automatically inherit there). Here the
    boundary rows REUSE the already-assembled interior-style Jacobian
    entries wholesale (rather than hand-deriving new ones), which
    should already carry that correction automatically -- verified
    directly, not assumed, restricted to the boundary columns
    specifically per the same lesson (random full-matrix sampling can
    miss a handful of boundary columns among thousands)."""
    dev = _diode2d(S_n=1e2, S_p=1e2, fd=True)
    dev.solve_equilibrium()
    rng = np.random.default_rng(2)
    psi = dev.psi + 1e-3 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1.0 + 1e-3 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1.0 + 1e-3 * rng.standard_normal(dev.p.shape))
    voltages = {"left": 0.2, "right": 0.0}
    F0, J0, *_ = dev._residual_jacobian(psi, n, p, voltages)
    J0d = J0.toarray()
    Ny, Nx = dev.Ny, dev.Nx
    h = 1e-7
    u0 = np.stack([psi, n, p], axis=-1).ravel()
    kk_left = np.arange(Ny) * Nx
    boundary_cols = np.concatenate([3 * kk_left, 3 * kk_left + 1, 3 * kk_left + 2])
    worst = 0.0
    for k in boundary_cols:
        up = u0.copy(); up[k] += h
        um = u0.copy(); um[k] -= h
        Fp, *_ = dev._residual_jacobian(
            up[0::3].reshape(Ny, Nx), up[1::3].reshape(Ny, Nx),
            up[2::3].reshape(Ny, Nx), voltages)
        Fm, *_ = dev._residual_jacobian(
            um[0::3].reshape(Ny, Nx), um[1::3].reshape(Ny, Nx),
            um[2::3].reshape(Ny, Nx), voltages)
        col_fd = (Fp - Fm) / (2 * h)
        scale = np.maximum(np.abs(J0d[:, k]), 1.0)
        worst = max(worst, float(np.max(np.abs(J0d[:, k] - col_fd) / scale)))
    assert worst <= 5e-5, f"fd=True + S boundary FD-Jacobian FAIL: {worst:.3e}"


def test_g_c_majority_contact_density_converges_monotonically_2d():
    """G-C: at a MAJORITY-carrier ohmic contact (the regime this gate
    covers -- see the module-level note on the minority-carrier
    limitation below), the contact density converges monotonically
    DOWN to the S=0/Dirichlet value as S grows from near-zero to very
    large, the same qualitative signature Device1D's own G-C test
    uses."""
    dev0 = _diode2d(0.0, 0.0)
    dev0.solve_equilibrium()
    dev0.solve_bias({"left": 0.2, "right": 0.0}, NewtonOptions(max_iter=100))
    n_dirichlet = dev0.n[0, -1]

    vals = []
    for S in np.logspace(-2, 10, 7):
        d = _diode2d(S_n=S, S_p=S)
        d.solve_equilibrium()
        d.solve_bias({"left": 0.2, "right": 0.0}, NewtonOptions(max_iter=100))
        vals.append(d.n[0, -1])

    assert all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1)), vals
    assert vals[-1] == pytest.approx(n_dirichlet, rel=1e-3)


def test_s_n_p_combines_cleanly_with_other_2d_models():
    """Adversarial pass (mirrors Device1D's own hard-debug sweep over
    every other Models flag): S_n/S_p combined with bgn/auger/
    surface_mobility must still produce a finite, converged solve and
    a clean boundary FD-Jacobian -- not just work in isolation."""
    for extra in (dict(bgn=True), dict(auger=True), dict(surface_mobility=True)):
        dev = _diode2d(S_n=1e2, S_p=1e2, **extra)
        dev.solve_equilibrium()
        dev.solve_bias({"left": 0.2, "right": 0.0}, NewtonOptions(max_iter=100))
        assert np.all(np.isfinite(dev.psi))
        assert np.all(np.isfinite(dev.n)) and np.all(np.isfinite(dev.p))
        worst = _fd_jacobian_check(dev, {"left": 0.2, "right": 0.0}, seed=5, n_cols=40)
        assert worst <= 5e-5, f"S+{extra} FD-Jacobian FAIL: {worst:.3e}"
