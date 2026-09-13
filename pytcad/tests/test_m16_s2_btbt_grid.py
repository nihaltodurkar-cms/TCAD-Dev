"""M16-S2 gates: local Kane BTBT (pytcad/btbt.py) ported to structured
Device2D/Device3D via pytcad/btbt_grid.py.  See M16-S2-PLAN.md.

Unlike M34-S6's impact ionization, this generation term depends on psi
alone (no carrier-density dependence, no eps-smoothed |J|), so the
kernel's own FD-Jacobian is the whole story -- G2/G3 probe
`grid_btbt` directly rather than reusing test_m34_s6_impact_2d3d.py's
node-sum/hot-node machinery, which exists to handle a dependency this
model does not have.
"""
import os
import sys
import warnings

import numpy as np
import pytest
from scipy.sparse import coo_matrix

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from pytcad import Device1D, Models, NewtonOptions
from pytcad.btbt import btbt_generation
from pytcad.btbt_grid import grid_btbt
from pytcad.device2d import Device2D
from pytcad.device3d import Device3D
from pytcad.mesh import graded_mesh
from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D

X = graded_mesh(1.0e-5, [5.0e-6], h_min=1e-8, h_max=2e-7)
DOP1D = np.where(X < 5.0e-6, -5e19, 5e19)


def _models(btbt):
    return Models(bgn=False, srh=True, btbt=btbt)


def _dev1(btbt=True):
    return Device1D(X, DOP1D, T=300.0, models=_models(btbt))


def _dev2(btbt=True, y=None):
    y = np.linspace(0.0, 1e-5, 3) if y is None else y
    dop2 = np.tile(DOP1D, (y.size, 1))
    d = Device2D(Mesh2D(X, y), dop2, T=300.0, models=_models(btbt))
    d.add_contact("left", i=[0], j=list(range(y.size)), V=0.0)
    d.add_contact("right", i=[X.size - 1], j=list(range(y.size)), V=0.0)
    return d


def _dev3(btbt=True, y=None, z=None):
    y = np.linspace(0.0, 1e-5, 3) if y is None else y
    z = np.linspace(0.0, 1e-5, 3) if z is None else z
    dop3 = np.broadcast_to(DOP1D, (z.size, y.size, X.size)).copy()
    d = Device3D(Mesh3D(x=X, y=y, z=z), dop3, T=300.0, models=_models(btbt))
    kk, jj = np.meshgrid(range(z.size), range(y.size), indexing="ij")
    d.add_contact("left", i=[0] * jj.size, j=jj.ravel().tolist(),
                  k=kk.ravel().tolist(), V=0.0)
    d.add_contact("right", i=[X.size - 1] * jj.size,
                  j=jj.ravel().tolist(), k=kk.ravel().tolist(), V=0.0)
    return d


def _ramp(dev, vmax, step=0.5):
    bad = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev.solve_equilibrium()
        for v in np.arange(step, vmax + 1e-9, step):
            if isinstance(dev, Device1D):
                dev.solve_bias([-float(v), 0.0], NewtonOptions())
            else:
                dev.solve_bias({"left": -float(v), "right": 0.0})
            if not dev.last_converged:
                bad.append(float(v))
    return bad


def test_g1_grid_kernel_reduces_to_1d_node_field():
    """G1: on a single-axis grid, grid_btbt's F/G reproduce Device1D's
    _ii_compute_E_from_state + btbt_generation node-for-node (exact --
    the same inv=1/count weighting, no eps anywhere in this model)."""
    d1 = _dev1()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d1.solve_bias([-2.0, 0.0], NewtonOptions())
    psi = d1.psi.copy()
    N = len(X)
    axes = [dict(kL=np.arange(N - 1), kR=np.arange(1, N), h=d1.h)]
    G, r, c, v, F_node = grid_btbt(N, axes, psi, d1.VT, d1.LD, d1.R0)
    E_1d = d1._ii_compute_E_from_state(psi)
    assert np.array_equal(F_node, E_1d)
    assert np.max(np.abs(G * d1.R0 - btbt_generation(E_1d))) \
        < 1e-10 * btbt_generation(E_1d).max()


def _fd_check_kernel(N, axes, psi, VT, LD, R0, eps=1e-6, tol=1e-6):
    G0, r, c, v, _ = grid_btbt(N, axes, psi, VT, LD, R0)
    J = coo_matrix((v, (r, c // 3)), shape=(N, N)).toarray()
    maxrel = 0.0
    rng = np.random.default_rng(3)
    probe = rng.choice(N, size=min(N, 12), replace=False)
    for j in probe:
        p2 = psi.copy(); p2[j] += eps
        Gp, *_ = grid_btbt(N, axes, p2, VT, LD, R0)
        p3 = psi.copy(); p3[j] -= eps
        Gm, *_ = grid_btbt(N, axes, p3, VT, LD, R0)
        fd = (Gp - Gm) / (2 * eps)
        an = J[:, j]
        floor = 1e-6 * np.abs(fd).max()
        mask = np.abs(fd) > floor
        if not mask.any():
            continue
        rel = np.abs(fd[mask] - an[mask]) / np.abs(fd[mask])
        maxrel = max(maxrel, rel.max())
    assert maxrel < tol, maxrel


def test_g2_fd_jacobian_2d():
    """G2: FD-Jacobian of grid_btbt, 2D axes, at a reverse-biased state."""
    d2 = _dev2()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d2.solve_bias({"left": -2.0, "right": 0.0})
    Ny, Nx = d2.psi.shape
    N = Ny * Nx
    kLx = (np.arange(Ny)[:, None] * Nx + np.arange(Nx - 1)[None, :]).ravel()
    kRx = kLx + 1
    kSy = (np.arange(Ny - 1)[:, None] * Nx + np.arange(Nx)[None, :]).ravel()
    kNy = kSy + Nx
    axes = [
        dict(kL=kLx, kR=kRx,
             h=np.broadcast_to(d2.hx[None, :], (Ny, Nx - 1)).ravel()),
        dict(kL=kSy, kR=kNy,
             h=np.broadcast_to(d2.hy[:, None], (Ny - 1, Nx)).ravel()),
    ]
    _fd_check_kernel(N, axes, d2.psi.ravel(), d2.VT, d2.LD, d2.R0)


def test_g3_fd_jacobian_3d():
    """G3: FD-Jacobian of grid_btbt, 3D axes."""
    d3 = _dev3()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d3.solve_bias({"left": -2.0, "right": 0.0})
    Nz, Ny, Nx = d3.psi.shape
    N = Nz * Ny * Nx
    idx = np.arange(N).reshape(Nz, Ny, Nx)
    kLx, kRx = idx[:, :, :-1].ravel(), idx[:, :, 1:].ravel()
    kSy, kNy = idx[:, :-1, :].ravel(), idx[:, 1:, :].ravel()
    kDz, kUz = idx[:-1, :, :].ravel(), idx[1:, :, :].ravel()
    axes = [
        dict(kL=kLx, kR=kRx,
             h=np.broadcast_to(d3.hx[None, None, :], (Nz, Ny, Nx - 1)).ravel()),
        dict(kL=kSy, kR=kNy,
             h=np.broadcast_to(d3.hy[None, :, None], (Nz, Ny - 1, Nx)).ravel()),
        dict(kL=kDz, kR=kUz,
             h=np.broadcast_to(d3.hz[:, None, None], (Nz - 1, Ny, Nx)).ravel()),
    ]
    _fd_check_kernel(N, axes, d3.psi.ravel(), d3.VT, d3.LD, d3.R0)


def test_g4_transverse_uniform_2d_reduces_to_1d():
    """G4: a transversely uniform 2D device reproduces Device1D's own
    btbt=True fixed point (exact reduction: transverse edges carry zero
    field by symmetry, so grid_btbt's F is exactly the 1D node field)."""
    d1 = _dev1()
    bad1 = _ramp(d1, 2.0)
    d2 = _dev2()
    bad2 = _ramp(d2, 2.0)
    assert not bad1 and not bad2
    # Device1D caches the PHYSICAL generation (device.py's G_btbt);
    # Device2D/3D cache the already-R0-scaled Gb (matching ii_grid's
    # convention) -- multiply by R0 before comparing.
    g1 = d1._btbt_gs_cache
    g2 = d2._btbt_gs_cache.reshape(d2.psi.shape) * d2.R0
    assert g1.max() > 0.0
    for row in range(g2.shape[0]):
        assert np.max(np.abs(g2[row] - g1)) < 1e-8 * g1.max()
    assert np.allclose(d2.psi, np.broadcast_to(d1.psi, d2.psi.shape),
                        atol=1e-10)


def test_g5_transverse_uniform_3d_reduces_to_1d():
    """G5: Device3D's port, same reduction."""
    d1 = _dev1()
    bad1 = _ramp(d1, 2.0)
    d3 = _dev3()
    bad3 = _ramp(d3, 2.0)
    assert not bad1 and not bad3
    g1 = d1._btbt_gs_cache
    g3 = d3._btbt_gs_cache.reshape(d3.psi.shape) * d3.R0
    assert g1.max() > 0.0
    for k in range(g3.shape[0]):
        for j in range(g3.shape[1]):
            assert np.max(np.abs(g3[k, j] - g1)) < 1e-8 * g1.max()


def test_g6_btbt_false_bit_identity():
    """G6: btbt=False is untouched by the code-motion (hoisting `axes`/
    `live`/`dVf` out of the impact-only guard) -- np.array_equal, not
    'looks the same'."""
    d2 = _dev2(btbt=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d2.solve_bias({"left": -2.0, "right": 0.0})
    psi2, n2, p2 = d2.psi.copy(), d2.n.copy(), d2.p.copy()

    d3 = _dev3(btbt=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d3.solve_bias({"left": -2.0, "right": 0.0})
    psi3, n3, p3 = d3.psi.copy(), d3.n.copy(), d3.p.copy()

    d2b = _dev2(btbt=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d2b.solve_bias({"left": -2.0, "right": 0.0})
    assert np.array_equal(d2b.psi, psi2)
    assert np.array_equal(d2b.n, n2)
    assert np.array_equal(d2b.p, p2)

    d3b = _dev3(btbt=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d3b.solve_bias({"left": -2.0, "right": 0.0})
    assert np.array_equal(d3b.psi, psi3)
    assert np.array_equal(d3b.n, n3)
    assert np.array_equal(d3b.p, p3)


def test_g7_reverse_ramp_current_rises_steeply_2d():
    """G7: M16's own G-C/G-E shape (the Zener current does not plateau
    with increasing reverse bias), reproduced in 2D."""
    d2 = _dev2()
    js = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d2.solve_equilibrium()
        for v in (0.5, 1.0, 1.5, 2.0):
            d2.solve_bias({"left": -v, "right": 0.0})
            assert d2.last_converged
            js.append(abs(d2.terminal_current("left")))
    assert all(b > a for a, b in zip(js, js[1:])), js
    # steep, not a plateau: each 0.5V step still multiplies the current
    # several-fold this close to onset -- M16's own G-C/G-E shape.
    ratios = [b / a for a, b in zip(js, js[1:])]
    assert min(ratios) > 2.0, ratios
