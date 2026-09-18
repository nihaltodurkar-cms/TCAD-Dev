"""M42-S3 -- density-gradient quantum correction in Device3D equilibrium,
a direct lift of Device2D's S1/S2 coupled-Newton (psi, Lambda_n,
Lambda_p) solve one axis further (M42-DENSITY-GRADIENT-2D3D-PLAN.md
section 10.8). pytcad/dg_grid.py's Lambda-row kernel is now shared by
Device2D and Device3D (M42-S3's own extraction) and, same day on
request, compiled into pytcad._core (core/src/dg/grid.cpp) -- see
tests/test_m42_s3_accel_parity.py for that kernel's own gate.

Gates, mirroring S1's own section 5 table one dimension up:
  S3-G1  FD-Jacobian of the full 3N coupled (psi, Lambda_n, Lambda_p)
         system on a small Device3D mesh.
  S3-G2  dg=False bit-identity: unaffected by this change (the dg
         dispatch in solve_equilibrium is a new branch, not an edit to
         the existing classical path) -- checked directly here plus
         test_m13_goldens.py's resistor3d_eq.npz golden, run
         separately as part of the regression sweep, not duplicated.
  S3-G-REDUCTION a z-uniform 3D device (ohmic, then gated) reproduces
         Device2D's own DG equilibrium to floating-point noise, which
         itself already reduces to Device1D (S1-G3).
  S3-G5  dg+fd, dg+incomplete_ion, dg+band_offset="affinity",
         dg+SIC_4H all refuse, matching Device2D.
  S3-G6  gamma continuation converges without warning and is
         deterministic across repeat runs.
  extra  solve_bias refuses dg=True, matching Device1D/Device2D.
"""
import warnings

import numpy as np
import pytest

from pytcad import Device2D, Device3D, Models
from pytcad.materials import SIC_4H
from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D


def _tiny_3d_mesh():
    x = np.linspace(0.0, 2e-5, 5)
    y = np.linspace(0.0, 1e-5, 4)
    z = np.linspace(0.0, 1e-5, 4)
    return x, y, z


def _make_device_3d(dg_gamma=1.0, dg=True, extra_models=None):
    x, y, z = _tiny_3d_mesh()
    mesh = Mesh3D(x, y, z)
    dop1d = np.where(x < 1e-5, -1e17, 1e17)
    dop3d = np.tile(dop1d, (mesh.Nz, mesh.Ny, 1))
    kwargs = dict(bgn=False, dg=dg, dg_gamma=dg_gamma)
    if extra_models:
        kwargs.update(extra_models)
    dev = Device3D(mesh, dop3d, models=Models(**kwargs))
    jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev.add_contact("right", i=np.full_like(jj, mesh.Nx - 1), j=jj, k=kk, V=0.0)
    return dev


# ---------------------------------------------------------------- S3-G1
def test_g1_fd_jacobian_3d():
    dev = _make_device_3d()
    N = dev.N
    rng = np.random.default_rng(0)
    shp = (dev.Nz, dev.Ny, dev.Nx)
    psi0 = rng.uniform(-2, 2, shp)
    Lam_n0 = rng.uniform(-1e-3, 1e-3, shp)
    Lam_p0 = rng.uniform(-1e-3, 1e-3, shp)

    F0, J0 = dev._dg_residual_jacobian_eq(psi0, Lam_n0, Lam_p0, gamma=1.0)
    J0d = J0.toarray()

    x0 = np.empty(3 * N)
    x0[0::3] = psi0.ravel()
    x0[1::3] = Lam_n0.ravel()
    x0[2::3] = Lam_p0.ravel()

    def unpack(v):
        return (v[0::3].reshape(shp), v[1::3].reshape(shp), v[2::3].reshape(shp))

    eps = 1e-6
    rng2 = np.random.default_rng(1)
    cols = rng2.choice(3 * N, size=min(3 * N, 90), replace=False)
    worst = 0.0
    for c in cols:
        xp, xm = x0.copy(), x0.copy()
        xp[c] += eps
        xm[c] -= eps
        Fp, _ = dev._dg_residual_jacobian_eq(*unpack(xp), gamma=1.0)
        Fm, _ = dev._dg_residual_jacobian_eq(*unpack(xm), gamma=1.0)
        fd_col = (Fp - Fm) / (2 * eps)
        an_col = J0d[:, c]
        denom = max(np.abs(an_col).max(), 1e-12)
        worst = max(worst, np.abs(fd_col - an_col).max() / denom)
    assert worst < 5e-5, f"FD-Jacobian mismatch: {worst:.3e}"


# ---------------------------------------------------------------- S3-G2
def test_g2_off_bit_identity_3d():
    x, y, z = _tiny_3d_mesh()
    mesh = Mesh3D(x, y, z)
    dop1d = np.where(x < 1e-5, -1e17, 1e17)
    dop3d = np.tile(dop1d, (mesh.Nz, mesh.Ny, 1))
    jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
    jj, kk = jj.ravel(), kk.ravel()

    dev_a = Device3D(mesh, dop3d, models=Models(bgn=False, dg=False))
    dev_a.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev_a.add_contact("right", i=np.full_like(jj, mesh.Nx - 1), j=jj, k=kk, V=0.0)
    dev_a.solve_equilibrium()

    dev_b = Device3D(mesh, dop3d, models=Models(bgn=False))
    dev_b.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev_b.add_contact("right", i=np.full_like(jj, mesh.Nx - 1), j=jj, k=kk, V=0.0)
    dev_b.solve_equilibrium()

    assert np.array_equal(dev_a.psi, dev_b.psi)
    assert np.array_equal(dev_a.n, dev_b.n)
    assert np.array_equal(dev_a.p, dev_b.p)


# ------------------------------------------------------- S3-G-REDUCTION
def test_g_reduction_ohmic_to_device2d():
    """A z-uniform Device3D (no BC touching the z-boundary rows -- the
    natural missing-face Neumann condition, same reasoning as S1-G3's
    y-uniform 2D-to-1D reduction) reproduces Device2D's own DG
    equilibrium to floating-point noise."""
    x, y = np.linspace(0.0, 2e-5, 5), np.linspace(0.0, 1e-5, 4)
    dop1d = np.where(x < 1e-5, -1e17, 1e17)
    dop2d = np.tile(dop1d, (y.size, 1))
    mesh2 = Mesh2D(x, y)
    dev2 = Device2D(mesh2, dop2d, models=Models(bgn=False, dg=True))
    dev2.add_contact("left", i=[0], j=list(range(mesh2.Ny)), V=0.0)
    dev2.add_contact("right", i=[mesh2.Nx - 1], j=list(range(mesh2.Ny)), V=0.0)
    dev2.solve_equilibrium()

    z_uniform = np.linspace(0.0, 5e-6, 3)
    mesh3 = Mesh3D(x, y, z_uniform)
    dop3d = np.tile(dop2d, (mesh3.Nz, 1, 1))
    dev3 = Device3D(mesh3, dop3d, models=Models(bgn=False, dg=True))
    jj, kk = np.meshgrid(np.arange(mesh3.Ny), np.arange(mesh3.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev3.add_contact("left", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev3.add_contact("right", i=np.full_like(jj, mesh3.Nx - 1), j=jj, k=kk, V=0.0)
    dev3.solve_equilibrium()

    assert np.abs(dev3.psi - dev2.psi[None, :, :]).max() < 1e-10
    assert np.abs(dev3._dg_Lam_n - dev2._dg_Lam_n[None, :, :]).max() < 1e-10
    assert np.abs(dev3._dg_Lam_p - dev2._dg_Lam_p[None, :, :]).max() < 1e-10
    assert (np.abs(dev3.n - dev2.n[None, :, :]).max() / dev2.n.max()) < 1e-9
    assert (np.abs(dev3.p - dev2.p[None, :, :]).max() / dev2.p.max()) < 1e-9


def test_g_reduction_gated_to_device2d():
    """Same reduction, with a GateBC on the y=Ny-1 face (normal_axis='y')
    present in both -- Device3D's GateBC hard wall must reduce to
    Device2D's identically."""
    x, y = np.linspace(0.0, 2e-5, 6), np.linspace(0.0, 1e-5, 4)
    dop2d = np.full((y.size, x.size), -1e17)
    mesh2 = Mesh2D(x, y)
    dev2 = Device2D(mesh2, dop2d, models=Models(bgn=False, dg=True))
    dev2.add_contact("body", i=[0], j=list(range(mesh2.Ny)), V=0.0)
    dev2.add_gate("gate", i=list(range(mesh2.Nx)), j=[mesh2.Ny - 1],
                 tox_cm=2e-7, Vfb=-0.9, Vg=0.0)
    dev2.solve_equilibrium()

    z_uniform = np.linspace(0.0, 5e-6, 3)
    mesh3 = Mesh3D(x, y, z_uniform)
    dop3d = np.tile(dop2d, (mesh3.Nz, 1, 1))
    dev3 = Device3D(mesh3, dop3d, models=Models(bgn=False, dg=True))
    jj, kk = np.meshgrid(np.arange(mesh3.Ny), np.arange(mesh3.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev3.add_contact("body", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    ii, kk2 = np.meshgrid(np.arange(mesh3.Nx), np.arange(mesh3.Nz))
    ii, kk2 = ii.ravel(), kk2.ravel()
    dev3.add_gate("gate", i=ii, j=np.full_like(ii, mesh3.Ny - 1), k=kk2,
                 tox_cm=2e-7, Vfb=-0.9, Vg=0.0, normal_axis="y")
    dev3.solve_equilibrium()

    assert np.abs(dev3.psi - dev2.psi[None, :, :]).max() < 1e-9
    assert np.abs(dev3._dg_Lam_n - dev2._dg_Lam_n[None, :, :]).max() < 1e-9
    assert np.abs(dev3._dg_Lam_p - dev2._dg_Lam_p[None, :, :]).max() < 1e-9


# ---------------------------------------------------------------- S3-G5
@pytest.mark.parametrize("extra", [
    dict(fd=True),
    dict(incomplete_ion=True),
    dict(band_offset="affinity"),
])
def test_g5_refused_compositions_3d(extra):
    x, y, z = _tiny_3d_mesh()
    mesh = Mesh3D(x, y, z)
    dop1d = np.where(x < 1e-5, -1e17, 1e17)
    dop3d = np.tile(dop1d, (mesh.Nz, mesh.Ny, 1))
    kwargs = dict(bgn=False, dg=True)
    kwargs.update(extra)
    with pytest.raises(NotImplementedError):
        Device3D(mesh, dop3d, models=Models(**kwargs))


def test_g5_sic_4h_dg_refused_3d():
    x, y, z = _tiny_3d_mesh()
    mesh = Mesh3D(x, y, z)
    dop1d = np.where(x < 1e-5, -1e17, 1e17)
    dop3d = np.tile(dop1d, (mesh.Nz, mesh.Ny, 1))
    with pytest.raises(NotImplementedError):
        Device3D(mesh, dop3d, T=300.0, material=SIC_4H,
                 models=Models(bgn=False, dg=True))


# ---------------------------------------------------------------- S3-G6
def test_g6_converges_and_is_deterministic_3d():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        dev_a = _make_device_3d()
        dev_a.solve_equilibrium()
        dev_b = _make_device_3d()
        dev_b.solve_equilibrium()
    assert np.array_equal(dev_a.psi, dev_b.psi)
    assert np.array_equal(dev_a._dg_Lam_n, dev_b._dg_Lam_n)
    assert np.array_equal(dev_a._dg_Lam_p, dev_b._dg_Lam_p)


# --------------------------------------------------------- extra sanity
def test_dg_actually_moves_the_solution_3d():
    dev_classical = _make_device_3d(dg=False)
    dev_classical.solve_equilibrium()
    dev_dg = _make_device_3d(dg=True, dg_gamma=1.0)
    dev_dg.solve_equilibrium()
    rel = np.abs(dev_dg.n - dev_classical.n).max() / dev_classical.n.max()
    assert rel > 1e-6, "DG produced no measurable effect"


def test_solve_bias_refuses_dg_3d():
    dev = _make_device_3d()
    with pytest.raises(NotImplementedError):
        dev.solve_bias({"left": 0.0, "right": 0.1})
