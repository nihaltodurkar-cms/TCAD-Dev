"""M11-S4: 2D heterojunction box-integration gates.

Port of the M11-S3 1D heterojunction physics (HETEROSTRUCTURE-PLAN.md
sections 3/7) to Device2D's box integration:

  - per-node material lists (Semiconductor sequences),
  - position-dependent permittivity entering Poisson in FLUX FORM with
    harmonic-mean edge eps, normalized by the FIRST node's eps so a
    uniform device reduces ALGEBRAICALLY to the legacy assembly
    (bit-identity is structural, not empirical),
  - Anderson band offsets through CARRIER-SPECIFIC ln(nie) SG edge
    deltas (electron +dln(nie), hole -dln(nie) -- the M11 lesson:
    a shared delta passes a Jacobian check but breaks hole detailed
    balance),
  - per-material mobility/lifetime/recombination parameter sets.

Gates (M11-S3 precedent):
  a) homojunction regression: material=[SILICON]*N is bit-identical
     (np.array_equal) to the single-object constructor,
  b) FD-Jacobian across a Si/GaAs interface <= 5e-5 (house gate),
  c) equilibrium detailed balance: zero current for BOTH carriers
     across the interface,
  d) dimensional reduction: an x-only heterostructure solved in 2D
     reproduces the validated 1D Device1D heterojunction solution.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from pytcad import Device1D, Device2D, Device3D, Models, NewtonOptions
from pytcad.materials import GAAS, SILICON
from pytcad.mesh2d import Mesh2D


def _hetero_mesh(nx=25, ny=9):
    xg = np.linspace(0.0, 1.0e-4, nx)
    yg = np.linspace(0.0, 0.4e-4, ny)
    return Mesh2D(xg, yg), xg, yg


def _split_materials(mesh, x_split, left=SILICON, right=GAAS):
    # Device2D flattens row-major (j*Nx+i): rows of the same x-pattern
    return [left if x < x_split else right
            for _ in range(mesh.Ny) for x in mesh.x]


def _diode2d(material, models=None, nx=25, ny=9, na=1e17, nd=1e17):
    mesh, xg, yg = _hetero_mesh(nx, ny)
    dop = np.tile(np.where(xg < 0.5e-4, -na, nd), (yg.size, 1))
    dev = Device2D(mesh, dop, T=300.0, material=material,
                   models=models or Models(bgn=False, srh=True))
    dev.add_contact("l", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev.add_contact("r", i=[mesh.Nx - 1], j=list(range(mesh.Ny)),
                    V=0.0)
    return dev


# ------------------------------------------------------------------ (a)
def test_homojunction_bit_identical():
    """Gate (a): constructing with a per-node list of ONE material must
    produce results bit-identical (array_equal) to the legacy single-
    Semiconductor constructor -- the reduction is algebraic."""
    kw = dict(models=Models(bgn=True, srh=True))
    legacy = _diode2d(SILICON, **kw)
    listed = _diode2d([SILICON] * 25 * 9, **kw)
    legacy.solve_equilibrium()
    listed.solve_equilibrium()
    for attr in ("psi", "n", "p"):
        assert np.array_equal(getattr(legacy, attr),
                              getattr(listed, attr)), \
            f"homojunction {attr} not bit-identical"
    legacy.solve_bias({"l": 0.4}, NewtonOptions())
    listed.solve_bias({"l": 0.4}, NewtonOptions())
    for attr in ("psi", "n", "p", "Jn_x", "Jp_x"):
        assert np.array_equal(getattr(legacy, attr),
                              getattr(listed, attr)), \
            f"homojunction bias {attr} not bit-identical"


# ------------------------------------------------------------------ (b)
def test_fd_jacobian_si_gaas_interface_2d():
    """Gate (b): analytic Jacobian vs central finite differences across
    an abrupt Si/GaAs interface (house per-column normalization)."""
    mats = _split_materials(_hetero_mesh()[0], 0.5e-4)
    dev = _diode2d(mats)
    dev.solve_equilibrium()
    rng = np.random.default_rng(3)
    psi = dev.psi + 0.02 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1.0 + 0.01 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1.0 + 0.01 * rng.standard_normal(dev.p.shape))
    voltages = {"l": 0.3, "r": 0.0}
    F0, J, *_ = dev._residual_jacobian(psi, n, p, voltages)
    J = J.tocsc()
    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()
    worst = 0.0
    for c in rng.choice(u.size, size=80, replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        u1 = u.copy(); u1[c] -= step
        shp = dev.psi.shape
        Fp_, *_ = dev._residual_jacobian(u2[0::3].reshape(shp),
                                         u2[1::3].reshape(shp),
                                         u2[2::3].reshape(shp), voltages)
        Fm_, *_ = dev._residual_jacobian(u1[0::3].reshape(shp),
                                         u1[1::3].reshape(shp),
                                         u1[2::3].reshape(shp), voltages)
        fd_col = (Fp_.ravel() - Fm_.ravel()) / (2.0 * step)
        an_col = np.asarray(J[:, c].todense()).ravel()
        col_scale = np.abs(an_col).max() + 1e-30
        worst = max(worst,
                    float(np.abs(fd_col - an_col).max() / col_scale))
    assert worst <= 5e-5, \
        f"S4 GATE FAIL: FD-Jacobian rel err {worst:.3e} > 5e-5"


# ------------------------------------------------------------------ (c)
def test_zero_equilibrium_current_across_interface():
    """Gate (c): BOTH carriers carry identically zero current across the
    Si/GaAs interface at equilibrium (the shared-delta bug catcher)."""
    mats = _split_materials(_hetero_mesh()[0], 0.5e-4)
    dev = _diode2d(mats)
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=300))
    _, _, Jn_x, Jn_y, Jp_x, Jp_y, _, _ = dev._residual_jacobian(
        dev.psi, dev.n, dev.p, {})
    scale = float(np.abs(dev.n).max() + dev.p.max())
    an_scale = max(float(np.abs(dev.dn_edge_x / dev.hx[None, :]).max()),
                   float(np.abs(dev.dn_edge_y / dev.hy[:, None]).max()))
    limit = 1e-10 * an_scale * scale
    for name, arr in (("Jn_x", Jn_x), ("Jn_y", Jn_y),
                      ("Jp_x", Jp_x), ("Jp_y", Jp_y)):
        assert np.abs(arr).max() <= limit, \
            f"{name} at equilibrium: {np.abs(arr).max():.3e} > {limit:.1e}"


# ------------------------------------------------------------------ (d)
def test_reduces_to_1d_heterojunction():
    """Gate (d): an x-only heterostructure (materials/doping uniform in
    y) solved with Device2D reproduces the VALIDATED 1D Device1D
    heterojunction solution (same x-mesh, mid-row comparison)."""
    xg = np.linspace(0.0, 1.0e-4, 31)
    yg = np.linspace(0.0, 0.4e-4, 7)
    mesh = Mesh2D(xg, yg)
    dop1d = np.where(xg < 0.5e-4, -1e17, 1e17)
    dop2d = np.tile(dop1d, (yg.size, 1))
    mats1d = [SILICON if x < 0.5e-4 else GAAS for x in xg]

    dev1 = Device1D(xg, dop1d, T=300.0, material=mats1d,
                    models=Models(bgn=False, srh=True))
    dev1.solve_equilibrium()

    mats2d = [mats1d[i] for _ in range(yg.size) for i in range(xg.size)]
    dev2 = Device2D(mesh, dop2d, T=300.0, material=mats2d,
                    models=Models(bgn=False, srh=True))
    dev2.add_contact("l", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev2.add_contact("r", i=[mesh.Nx - 1], j=list(range(mesh.Ny)),
                     V=0.0)
    dev2.solve_equilibrium(NewtonOptions(tol_update=1e-12,
                                         max_iter=300))
    jmid = yg.size // 2
    dpsi = np.abs(dev2.psi[jmid, :] * dev2.VT
                  - dev1.psi * dev1.VT)
    dn = np.abs(dev2.n_cm3[jmid, :] - dev1.n_cm3) / dev1.n_cm3
    dp = np.abs(dev2.p_cm3[jmid, :] - dev1.p_cm3) / dev1.p_cm3
    assert dpsi.max() <= 1e-9, \
        f"reduction FAIL: |dpsi| {dpsi.max():.3e} V"
    assert max(dn.max(), dp.max()) <= 1e-8, \
        f"reduction FAIL: densities {max(dn.max(), dp.max()):.3e}"
    # Anderson step present: band offset shows in psi across interface
    assert abs(dev2.psi[0, 12] - dev2.psi[0, 13]) > 0.05, \
        "no visible Anderson band step at the Si/GaAs interface"


# --------------------------------------------------- fd + hetero compose
def test_fd_composes_with_heterojunction_2d():
    """fd statistics and the heterojunction deltas compose additively;
    the combined Jacobian passes the house gate."""
    mats = _split_materials(_hetero_mesh(nx=19, ny=7)[0], 0.5e-4)
    mesh, xg, yg = _hetero_mesh(nx=19, ny=7)
    dop = np.tile(np.where(xg < 0.5e-4, -1e18, 1e18), (yg.size, 1))
    dev = Device2D(mesh, dop, T=300.0, material=mats,
                   models=Models(bgn=False, srh=True, fd=True))
    dev.add_contact("l", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev.add_contact("r", i=[mesh.Nx - 1], j=list(range(mesh.Ny)),
                    V=0.0)
    dev.solve_equilibrium()
    rng = np.random.default_rng(5)
    psi = dev.psi + 0.02 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1.0 + 0.01 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1.0 + 0.01 * rng.standard_normal(dev.p.shape))
    voltages = {"l": 0.2, "r": 0.0}
    F0, J, *_ = dev._residual_jacobian(psi, n, p, voltages)
    J = J.tocsc()
    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()
    worst = 0.0
    for c in rng.choice(u.size, size=60, replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        u1 = u.copy(); u1[c] -= step
        shp = dev.psi.shape
        Fp_, *_ = dev._residual_jacobian(u2[0::3].reshape(shp),
                                         u2[1::3].reshape(shp),
                                         u2[2::3].reshape(shp), voltages)
        Fm_, *_ = dev._residual_jacobian(u1[0::3].reshape(shp),
                                         u1[1::3].reshape(shp),
                                         u1[2::3].reshape(shp), voltages)
        fd_col = (Fp_.ravel() - Fm_.ravel()) / (2.0 * step)
        an_col = np.asarray(J[:, c].todense()).ravel()
        col_scale = np.abs(an_col).max() + 1e-30
        worst = max(worst,
                    float(np.abs(fd_col - an_col).max() / col_scale))
    assert worst <= 5e-5, f"fd+hetero Jacobian {worst:.3e} > 5e-5"


# ================================================================ Device3D
# The same per-node material machinery on the 3D box integration
# (completes the M11-S4 core coverage across all three dimensions).

def _step3d(na=1e17, nd=1e17, nx=13, ny=5, nz=4):
    from pytcad.mesh3d import Mesh3D
    xg = np.linspace(0.0, 0.8e-4, nx)
    yg = np.linspace(0.0, 0.3e-4, ny)
    zg = np.linspace(0.0, 0.3e-4, nz)
    mesh = Mesh3D(xg, yg, zg)
    dop = np.full((mesh.Nz, mesh.Ny, mesh.Nx), na)
    dop[:, :, nx // 2:] = nd
    mats = [SILICON if x < 0.4e-4 else GAAS
            for _ in range(mesh.Nz) for _ in range(mesh.Ny)
            for x in xg]
    dev = Device3D(mesh, dop, T=300.0, material=mats,
                   models=Models(bgn=False, srh=True))
    jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev.add_contact("l", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    dev.add_contact("r", i=np.full_like(jj, mesh.Nx - 1), j=jj, k=kk,
                    V=0.0)
    return dev


def test_port3d_homojunction_bit_identical():
    """3D: [SILICON]*N construction is bit-identical to the single-
    object constructor (algebraic reduction, as in 2D)."""
    from pytcad.mesh3d import Mesh3D
    xg = np.linspace(0.0, 0.8e-4, 9)
    yg = np.linspace(0.0, 0.3e-4, 5)
    zg = np.linspace(0.0, 0.3e-4, 4)
    mesh = Mesh3D(xg, yg, zg)
    dop = np.tile(np.where(xg < 0.4e-4, -1e17, 1e17),
                  (mesh.Nz, mesh.Ny, 1))
    a = Device3D(mesh, dop, models=Models(bgn=False, srh=True))
    b = Device3D(mesh, dop,
                 material=[SILICON] * mesh.N,
                 models=Models(bgn=False, srh=True))
    jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    for d in (a, b):
        d.add_contact("l", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
        d.add_contact("r", i=np.full_like(jj, mesh.Nx - 1), j=jj,
                      k=kk, V=0.0)
        d.solve_equilibrium()
        d.solve_bias({"r": 0.35})
    assert np.array_equal(a.psi, b.psi)
    assert np.array_equal(a.Jn_x, b.Jn_x)


def test_port3d_zero_equilibrium_current_interface():
    """3D: zero equilibrium current for BOTH carriers across the
    Si/GaAs interface."""
    dev = _step3d()
    dev.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=300))
    scale = float(np.abs(dev.n).max() + dev.p.max())
    an_scale = max(float(np.abs(dev.dn_edge_x / dev.hx[None, None, :]).max()),
                   float(np.abs(dev.dn_edge_y / dev.hy[None, :, None]).max()),
                   float(np.abs(dev.dn_edge_z / dev.hz[:, None, None]).max()))
    limit = 1e-10 * an_scale * scale
    _, _, Jnx, Jny, Jnz, Jpx, Jpy, Jpz, _, _ = dev._residual_jacobian(
        dev.psi, dev.n, dev.p, {})
    for name, arr in (("Jnx", Jnx), ("Jny", Jny), ("Jnz", Jnz),
                      ("Jpx", Jpx), ("Jpy", Jpy), ("Jpz", Jpz)):
        assert np.abs(arr).max() <= limit, \
            f"3D {name}: {np.abs(arr).max():.3e} > {limit:.1e}"


def test_port3d_jacobian_across_interface():
    """3D house FD-Jacobian gate across the Si/GaAs interface."""
    dev = _step3d()
    dev.solve_equilibrium()
    rng = np.random.default_rng(13)
    psi = dev.psi + 0.02 * rng.standard_normal(dev.psi.shape)
    n = dev.n * (1.0 + 0.01 * rng.standard_normal(dev.n.shape))
    p = dev.p * (1.0 + 0.01 * rng.standard_normal(dev.p.shape))
    voltages = {"l": 0.25, "r": 0.0}
    F0, J, *_ = dev._residual_jacobian(psi, n, p, voltages)
    J = J.tocsc()
    u = np.stack([psi.ravel(), n.ravel(), p.ravel()], axis=1).ravel()
    worst = 0.0
    for c in rng.choice(u.size, size=60, replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        u1 = u.copy(); u1[c] -= step
        shp = dev.psi.shape
        Fp_, *_ = dev._residual_jacobian(u2[0::3].reshape(shp),
                                         u2[1::3].reshape(shp),
                                         u2[2::3].reshape(shp), voltages)
        Fm_, *_ = dev._residual_jacobian(u1[0::3].reshape(shp),
                                         u1[1::3].reshape(shp),
                                         u1[2::3].reshape(shp), voltages)
        fd_col = (Fp_.ravel() - Fm_.ravel()) / (2.0 * step)
        an_col = np.asarray(J[:, c].todense()).ravel()
        col_scale = np.abs(an_col).max() + 1e-30
        worst = max(worst,
                    float(np.abs(fd_col - an_col).max() / col_scale))
    assert worst <= 5e-5, f"3D hetero Jacobian {worst:.3e} > 5e-5"


def test_port3d_reduces_to_2d_heterojunction():
    """z-invariant 3D heterostructure reproduces the (now validated)
    2D heterojunction solution -- the dimensional-reduction pattern."""
    from pytcad.mesh3d import Mesh3D
    xg = np.linspace(0.0, 0.8e-4, 15)
    yg = np.linspace(0.0, 0.3e-4, 7)
    zg = np.linspace(0.0, 0.24e-4, 4)
    dop1 = np.where(xg < 0.4e-4, -1e17, 1e17)
    mats_2d = [SILICON if x < 0.4e-4 else GAAS
               for _ in range(yg.size) for x in xg]
    m2 = Mesh2D(xg, yg)
    d2 = Device2D(m2, np.tile(dop1, (yg.size, 1)), material=mats_2d,
                  models=Models(bgn=False, srh=True))
    d2.add_contact("l", i=[0], j=list(range(m2.Ny)), V=0.0)
    d2.add_contact("r", i=[m2.Nx - 1], j=list(range(m2.Ny)), V=0.0)
    d2.solve_equilibrium()

    mesh = Mesh3D(xg, yg, zg)
    dop3 = np.tile(dop1, (zg.size, yg.size, 1))
    mats_3d = [SILICON if x < 0.4e-4 else GAAS
               for _ in range(zg.size) for _ in range(yg.size)
               for x in xg]
    d3 = Device3D(mesh, dop3, material=mats_3d,
                  models=Models(bgn=False, srh=True))
    jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    d3.add_contact("l", i=np.zeros_like(jj), j=jj, k=kk, V=0.0)
    d3.add_contact("r", i=np.full_like(jj, mesh.Nx - 1), j=jj, k=kk,
                   V=0.0)
    d3.solve_equilibrium(NewtonOptions(tol_update=1e-12, max_iter=300))
    dpsi = np.abs(d3.psi[1, :, :] * d3.VT - d2.psi * d2.VT)
    assert dpsi.max() <= 1e-9, f"3D->2D reduction FAIL: {dpsi.max():.2e}"
