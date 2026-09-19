"""M44 Slice 3: dimension-generic (2D/3D) structured-grid electron
energy-balance kernel (pytcad/hydro_grid.py), standalone (not yet wired
into Device2D/Device3D -- that is Slice 4). See hydro_grid.py's own
docstring for why this follows ii_grid.py's calling convention rather
than thermal_grid.py's, and M44-HYDRODYNAMIC-PLAN.md Slice 3/4 for the
full record, including the transverse-weight ("w") bug found and fixed
while gating Slice 4: the flux-divergence term along one axis MUST be
weighted by the transverse control-volume width (dVy for an x-edge,
dVx for a y-edge, etc.), same as device2d.py's own Poisson residual
(`dVy[:,None]*div_x + dVx[None,:]*div_y`). The FIRST version of this
test file used an artificially row-uniform `dV` in G3/G4 (tiling
Device1D's own scalar dV identically at every row/layer, rather than
device2d.py's/device3d.py's own row/layer-varying dV = outer(dVy,dVx)),
which accidentally masked the missing weight -- both fixed here.

Gates:
  G1  FD-Jacobian in 2D.
  G2  FD-Jacobian in 3D.
  G3  y-uniform 2D reduction to Device1D's own Slice-1 result, using
      the REAL row-varying dV (boundary rows get a half-width transverse
      CV, same as device2d.py) -- this is what actually exercises the
      transverse-weight fix.
  G4  z-uniform 3D reduction to Device1D's own Slice-1 result, same
      real-dV convention one axis further.
"""
import numpy as np
import pytest

from pytcad.hydro_grid import grid_hydro
from pytcad.mesh2d import control_volume_widths
from pytcad.device2d import _edge_pairs_x as _epx2, _edge_pairs_y as _epy2
from pytcad.device3d import (
    _edge_pairs_x as _epx3, _edge_pairs_y as _epy3, _edge_pairs_z as _epz3)
from pytcad.device import Device1D, Models, NewtonOptions


def _axes_2d(Nx, Ny, rng, base_J=0.05):
    hx = 0.3 + 0.4 * rng.random(Nx - 1)
    hy = 0.3 + 0.4 * rng.random(Ny - 1)
    dVx, dVy = control_volume_widths(hx), control_volume_widths(hy)
    kLx, kRx = _epx2(Nx, Ny)
    kSy, kNy = _epy2(Nx, Ny)
    jj2, ii2 = np.mgrid[0:Ny, 0:Nx - 1]
    hx_e, wx_e = hx[ii2.ravel()], dVy[jj2.ravel()]
    jj, ii = np.mgrid[0:Ny - 1, 0:Nx]
    hy_e, wy_e = hy[jj.ravel()], dVx[ii.ravel()]
    axes = [
        dict(kL=kLx, kR=kRx, h=hx_e, w=wx_e,
            Jn=base_J * rng.standard_normal(kLx.size)),
        dict(kL=kSy, kR=kNy, h=hy_e, w=wy_e,
            Jn=base_J * rng.standard_normal(kSy.size)),
    ]
    dV = np.outer(dVy, dVx).ravel()
    return axes, dV, (hx, hy)


def _axes_3d(Nx, Ny, Nz, rng, base_J=0.05):
    hx = 0.3 + 0.4 * rng.random(Nx - 1)
    hy = 0.3 + 0.4 * rng.random(Ny - 1)
    hz = 0.3 + 0.4 * rng.random(Nz - 1)
    dVx, dVy, dVz = (control_volume_widths(hx), control_volume_widths(hy),
                     control_volume_widths(hz))
    kLx, kRx = _epx3(Nx, Ny, Nz)
    kSy, kNy = _epy3(Nx, Ny, Nz)
    kDz, kUz = _epz3(Nx, Ny, Nz)

    kk, jj, ii = np.mgrid[0:Nz, 0:Ny, 0:Nx - 1]
    hx_e, wx_e = hx[ii.ravel()], dVy[jj.ravel()] * dVz[kk.ravel()]
    kk, jj, ii = np.mgrid[0:Nz, 0:Ny - 1, 0:Nx]
    hy_e, wy_e = hy[jj.ravel()], dVx[ii.ravel()] * dVz[kk.ravel()]
    kk, jj, ii = np.mgrid[0:Nz - 1, 0:Ny, 0:Nx]
    hz_e, wz_e = hz[kk.ravel()], dVx[ii.ravel()] * dVy[jj.ravel()]

    axes = [
        dict(kL=kLx, kR=kRx, h=hx_e, w=wx_e,
            Jn=base_J * rng.standard_normal(kLx.size)),
        dict(kL=kSy, kR=kNy, h=hy_e, w=wy_e,
            Jn=base_J * rng.standard_normal(kSy.size)),
        dict(kL=kDz, kR=kUz, h=hz_e, w=wz_e,
            Jn=base_J * rng.standard_normal(kDz.size)),
    ]
    kk, jj, ii = np.mgrid[0:Nz, 0:Ny, 0:Nx]
    dV = (dVz[kk] * dVy[jj] * dVx[ii]).ravel()
    return axes, dV, (hx, hy, hz)


def _fd_jacobian_check(N, axes, dV, dirichlet_nodes, seed=0, tol=5e-5):
    rng = np.random.default_rng(seed)
    n_lag = 0.5 + 0.5 * rng.random(N)
    theta = 1.0 + 0.5 * rng.random(N)
    theta[dirichlet_nodes] = 1.0
    Qheat_lag = np.abs(rng.standard_normal(N)) * 1e-3
    mu_n0 = 1000.0 * (0.8 + 0.4 * rng.random(N))
    KAPPA0, ALPHA = 3.7, 12.3

    F0, rows, cols, vals = grid_hydro(
        N, axes, dV, n_lag, theta, Qheat_lag, mu_n0, KAPPA0, ALPHA,
        dirichlet_nodes)
    import scipy.sparse as sp
    J = sp.csr_matrix((vals, (rows, cols)), shape=(N, N)).tocsc()

    rng2 = np.random.default_rng(seed + 1)
    cols_test = rng2.choice(N, size=min(40, N), replace=False)
    worst = 0.0
    for c in cols_test:
        eps = 1e-6
        tp, tm = theta.copy(), theta.copy()
        tp[c] += eps; tm[c] -= eps
        Fp, *_ = grid_hydro(N, axes, dV, n_lag, tp, Qheat_lag, mu_n0,
                            KAPPA0, ALPHA, dirichlet_nodes)
        Fm, *_ = grid_hydro(N, axes, dV, n_lag, tm, Qheat_lag, mu_n0,
                            KAPPA0, ALPHA, dirichlet_nodes)
        fd_col = (Fp - Fm) / (2 * eps)
        an_col = np.asarray(J[:, c].todense()).ravel()
        scale = np.abs(an_col).max() + 1e-30
        worst = max(worst, float(np.abs(fd_col - an_col).max() / scale))
    assert worst <= tol, f"FD-Jacobian rel err {worst:.3e} > {tol:.0e}"


def test_g1_fd_jacobian_2d():
    Nx, Ny = 6, 5
    N = Nx * Ny
    rng = np.random.default_rng(0)
    axes, dV, _ = _axes_2d(Nx, Ny, rng)
    dirichlet = np.array([0, Nx - 1, N - Nx, N - 1])
    _fd_jacobian_check(N, axes, dV, dirichlet)


def test_g2_fd_jacobian_3d():
    Nx, Ny, Nz = 5, 4, 3
    N = Nx * Ny * Nz
    rng = np.random.default_rng(1)
    axes, dV, _ = _axes_3d(Nx, Ny, Nz, rng)
    dirichlet = np.array([0, Nx - 1, N - Nx, N - 1])
    _fd_jacobian_check(N, axes, dV, dirichlet)


def _diode1d_hydro_reference(N=41, L=1e-4, Vbias=0.5):
    x = np.linspace(0.0, L, N)
    doping = np.where(x < 0.5 * L, 1e17, -1e17)
    dev = Device1D(x, doping, models=Models(energy_balance=True))
    opts = NewtonOptions()
    dev.solve_equilibrium(opts)
    dev.solve_bias([0.0, Vbias], opts)
    assert dev.last_converged
    return dev


def test_g3_y_uniform_2d_reduction_to_device1d():
    """A y-invariant 2D slab fed through grid_hydro with Device1D's own
    converged Slice-1 state (tiled along y, zero transverse current),
    using device2d.py's OWN row-varying dV = outer(dVy,dVx) (boundary
    rows get a HALF-width transverse control volume, interior rows get
    the FULL width -- not an artificially uniform dV), must give
    (near) zero residual at every interior node -- this is what
    actually exercises the transverse-weight ("w") fix; an earlier
    version of this test used a uniform dV and passed even with that
    bug present."""
    dev = _diode1d_hydro_reference()
    Nx = dev.N
    Ny = 3

    theta = np.tile(dev.Tn / dev.T, Ny)
    n_lag = np.tile(dev.n, Ny)
    mu_n0 = np.tile(dev.mu_n0, Ny)

    hx = dev.h
    hy = np.array([0.9, 1.1])   # DELIBERATELY non-uniform transverse spacing
    dVx, dVy = control_volume_widths(hx), control_volume_widths(hy)
    kLx, kRx = _epx2(Nx, Ny)
    kSy, kNy = _epy2(Nx, Ny)
    jj2, ii2 = np.mgrid[0:Ny, 0:Nx - 1]
    hx_e, wx_e = hx[ii2.ravel()], dVy[jj2.ravel()]
    jj, ii = np.mgrid[0:Ny - 1, 0:Nx]
    hy_e, wy_e = hy[jj.ravel()], dVx[ii.ravel()]

    bc = dev._contact_values([0.0, 0.5])
    phi_n = dev.psi - np.log(np.maximum(dev.n, 1e-300) / dev.nie_s)
    En_edge = -(phi_n[1:] - phi_n[:-1]) / dev.h
    Hn_edge = dev.Jn / dev.J0 * En_edge
    Qheat_1d = np.empty(Nx)
    Qheat_1d[0], Qheat_1d[-1] = Hn_edge[0], Hn_edge[-1]
    Qheat_1d[1:-1] = 0.5 * (Hn_edge[:-1] + Hn_edge[1:])
    Qheat_lag = np.tile(Qheat_1d, Ny)
    Jn_x = np.tile(dev.Jn / dev.J0, Ny)
    Jn_y = np.zeros(kSy.size)

    axes = [
        dict(kL=kLx, kR=kRx, h=hx_e, w=wx_e, Jn=Jn_x),
        dict(kL=kSy, kR=kNy, h=hy_e, w=wy_e, Jn=Jn_y),
    ]
    N = Nx * Ny
    dV = np.outer(dVy, dVx).ravel()
    dirichlet = np.concatenate([
        np.arange(0, N, Nx), np.arange(Nx - 1, N, Nx)])

    F, rows, cols, vals = grid_hydro(
        N, axes, dV, n_lag, theta, Qheat_lag, mu_n0, dev._KAPPA0,
        dev._ALPHA_RELAX, dirichlet)

    interior = np.setdiff1d(np.arange(N), dirichlet)
    assert np.abs(F[interior]).max() < 1e-8, (
        f"y-uniform 2D residual should vanish at Device1D's own "
        f"converged theta, got max |F|={np.abs(F[interior]).max():.3e}")


def test_g4_z_uniform_3d_reduction_to_device1d():
    """Same idea as G3, one axis further: a z-invariant 3D block, real
    (non-uniform, boundary-vs-interior) transverse dV in BOTH y and z."""
    dev = _diode1d_hydro_reference(N=31)
    Nx = dev.N
    Ny, Nz = 3, 2

    theta = np.tile(dev.Tn / dev.T, Ny * Nz)
    n_lag = np.tile(dev.n, Ny * Nz)
    mu_n0 = np.tile(dev.mu_n0, Ny * Nz)

    hx = dev.h
    hy = np.array([0.9, 1.1])
    hz = np.array([1.2])
    dVx, dVy, dVz = (control_volume_widths(hx), control_volume_widths(hy),
                     control_volume_widths(hz))
    kLx, kRx = _epx3(Nx, Ny, Nz)
    kSy, kNy = _epy3(Nx, Ny, Nz)
    kDz, kUz = _epz3(Nx, Ny, Nz)

    kk, jj, ii = np.mgrid[0:Nz, 0:Ny, 0:Nx - 1]
    hx_e, wx_e = hx[ii.ravel()], dVy[jj.ravel()] * dVz[kk.ravel()]
    kk, jj, ii = np.mgrid[0:Nz, 0:Ny - 1, 0:Nx]
    hy_e, wy_e = hy[jj.ravel()], dVx[ii.ravel()] * dVz[kk.ravel()]
    kk, jj, ii = np.mgrid[0:Nz - 1, 0:Ny, 0:Nx]
    hz_e, wz_e = hz[kk.ravel()], dVx[ii.ravel()] * dVy[jj.ravel()]

    phi_n = dev.psi - np.log(np.maximum(dev.n, 1e-300) / dev.nie_s)
    En_edge = -(phi_n[1:] - phi_n[:-1]) / dev.h
    Hn_edge = dev.Jn / dev.J0 * En_edge
    Qheat_1d = np.empty(Nx)
    Qheat_1d[0], Qheat_1d[-1] = Hn_edge[0], Hn_edge[-1]
    Qheat_1d[1:-1] = 0.5 * (Hn_edge[:-1] + Hn_edge[1:])
    Qheat_lag = np.tile(Qheat_1d, Ny * Nz)
    Jn_x = np.tile(dev.Jn / dev.J0, Ny * Nz)

    axes = [
        dict(kL=kLx, kR=kRx, h=hx_e, w=wx_e, Jn=Jn_x),
        dict(kL=kSy, kR=kNy, h=hy_e, w=wy_e, Jn=np.zeros(kSy.size)),
        dict(kL=kDz, kR=kUz, h=hz_e, w=wz_e, Jn=np.zeros(kDz.size)),
    ]
    N = Nx * Ny * Nz
    kk, jj, ii = np.mgrid[0:Nz, 0:Ny, 0:Nx]
    dV = (dVz[kk] * dVy[jj] * dVx[ii]).ravel()
    node = np.arange(N).reshape(Nz, Ny, Nx)
    dirichlet = np.concatenate([node[:, :, 0].ravel(), node[:, :, -1].ravel()])

    F, rows, cols, vals = grid_hydro(
        N, axes, dV, n_lag, theta, Qheat_lag, mu_n0, dev._KAPPA0,
        dev._ALPHA_RELAX, dirichlet)

    interior = np.setdiff1d(np.arange(N), dirichlet)
    assert np.abs(F[interior]).max() < 1e-8, (
        f"z-uniform 3D residual should vanish at Device1D's own "
        f"converged theta, got max |F|={np.abs(F[interior]).max():.3e}")
