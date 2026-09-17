"""M42-S1 -- density-gradient quantum correction in Device2D equilibrium
(originally: ohmic contacts only, GateBC refused -- see M42-DENSITY-
GRADIENT-2D3D-PLAN.md section 0.2). M42-S2 (2026-09-17) landed the
GateBC Lambda boundary condition (test_m42_s2_gate_bc.py); S1-G4 below
is REWRITTEN accordingly (S2 intentionally removes the refusal it used
to check -- same M34-S6/M41-precedent rewrite section 9's own record
already used once for test_m20_dg.py::test_ge_device2d_...).

Gates, mirroring the plan's own section 5 table:
  S1-G1  FD-Jacobian of the full 3N coupled (psi, Lambda_n, Lambda_p)
         system, written first.
  S1-G2  dg=False bit-identity: np.array_equal on psi/n/p vs. the plain
         Poisson-only equilibrium path, plus the six m13 golden md5s
         (checked separately by test_m13_goldens.py, unaffected by this
         change -- see the module docstring history there).
  S1-G3  reduction identity: a transversely-uniform 2D device with two
         ohmic contacts reproduces Device1D's own DG equilibrium
         (psi, n, p, Lambda_n, Lambda_p) to floating-point noise.
  S1-G4  (M42-S2 rewrite) a device with a GateBC now SOLVES (S2 landed
         the Lambda boundary condition) rather than refusing -- see
         test_m42_s2_gate_bc.py for the full S2 gate suite.
  S1-G5  dg+fd, dg+incomplete_ion, dg+band_offset="affinity" all refuse.
  S1-G6  gamma continuation converges without warning, and the result is
         deterministic across repeat runs.
"""
import warnings

import numpy as np
import pytest

from pytcad import Device1D, Device2D, Models
from pytcad.mesh2d import Mesh2D
from pytcad.mesh import graded_mesh


def _pn_junction_mesh():
    x = graded_mesh(2e-5, [1e-5], h_min=1e-8, h_max=1e-6)
    y = graded_mesh(1e-5, [0.5e-5], h_min=1e-8, h_max=1e-6)
    return x, y


def _make_device(dg_gamma=1.0, dg=True, extra_models=None):
    x, y = _pn_junction_mesh()
    mesh = Mesh2D(x, y)
    dop = np.tile(np.where(x < 1e-5, -1e17, 1e17), (y.size, 1))
    kwargs = dict(bgn=False, dg=dg, dg_gamma=dg_gamma)
    if extra_models:
        kwargs.update(extra_models)
    dev = Device2D(mesh, dop, models=Models(**kwargs))
    dev.add_contact("left", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev.add_contact("right", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    return dev


# ---------------------------------------------------------------- S1-G1
def test_g1_fd_jacobian():
    dev = _make_device()
    N = dev.N
    rng = np.random.default_rng(0)
    psi0 = rng.uniform(-2, 2, (dev.Ny, dev.Nx))
    Lam_n0 = rng.uniform(-1e-3, 1e-3, (dev.Ny, dev.Nx))
    Lam_p0 = rng.uniform(-1e-3, 1e-3, (dev.Ny, dev.Nx))

    F0, J0 = dev._dg_residual_jacobian_eq(psi0, Lam_n0, Lam_p0, gamma=1.0)
    J0d = J0.toarray()

    x0 = np.empty(3 * N)
    x0[0::3] = psi0.ravel()
    x0[1::3] = Lam_n0.ravel()
    x0[2::3] = Lam_p0.ravel()

    def unpack(v):
        return (v[0::3].reshape(dev.Ny, dev.Nx),
                v[1::3].reshape(dev.Ny, dev.Nx),
                v[2::3].reshape(dev.Ny, dev.Nx))

    eps = 1e-6
    cols = rng.choice(3 * N, size=min(3 * N, 90), replace=False)
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


# ---------------------------------------------------------------- S1-G2
def test_g2_off_bit_identity():
    x, y = _pn_junction_mesh()
    mesh = Mesh2D(x, y)
    dop = np.tile(np.where(x < 1e-5, -1e17, 1e17), (y.size, 1))

    dev_a = Device2D(mesh, dop, models=Models(bgn=False, dg=False))
    dev_a.add_contact("left", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev_a.add_contact("right", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    dev_a.solve_equilibrium()

    dev_b = Device2D(mesh, dop, models=Models(bgn=False))
    dev_b.add_contact("left", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev_b.add_contact("right", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    dev_b.solve_equilibrium()

    assert np.array_equal(dev_a.psi, dev_b.psi)
    assert np.array_equal(dev_a.n, dev_b.n)
    assert np.array_equal(dev_a.p, dev_b.p)


# ---------------------------------------------------------------- S1-G3
def test_g3_reduction_to_device1d():
    x, y = _pn_junction_mesh()
    dop1d = np.where(x < 1e-5, -1e17, 1e17)
    dev1 = Device1D(x, dop1d, T=300.0, models=Models(bgn=False, dg=True))
    dev1.solve_equilibrium()

    # transversely uniform: no BC on the y-boundary rows at all, so they
    # get the natural (missing-face) Neumann condition, same as the
    # x-boundary rows in 1D.
    y_uniform = np.linspace(0.0, 5e-6, 4)
    mesh = Mesh2D(x, y_uniform)
    dop2d = np.tile(dop1d, (y_uniform.size, 1))
    dev2 = Device2D(mesh, dop2d, models=Models(bgn=False, dg=True))
    dev2.add_contact("left", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev2.add_contact("right", i=[mesh.Nx - 1], j=list(range(mesh.Ny)), V=0.0)
    dev2.solve_equilibrium()

    assert np.abs(dev2.psi - dev1.psi[None, :]).max() < 1e-10
    assert np.abs(dev2._dg_Lam_n - dev1._dg_Lam_n[None, :]).max() < 1e-10
    assert np.abs(dev2._dg_Lam_p - dev1._dg_Lam_p[None, :]).max() < 1e-10
    assert (np.abs(dev2.n - dev1.n[None, :]).max()
            / dev1.n.max()) < 1e-9
    assert (np.abs(dev2.p - dev1.p[None, :]).max()
            / dev1.p.max()) < 1e-9


# ---------------------------------------------------------------- S1-G4
def test_g4_gatebc_now_solves_s2_landed():
    """M42-S2 (2026-09-17) landed the GateBC Lambda boundary condition --
    a device with a GateBC now solves rather than refusing. See
    test_m42_s2_gate_bc.py for the gates that actually validate the
    physics of this boundary condition (S2-G-CONF/-SP/-MESH etc.)."""
    x, y = _pn_junction_mesh()
    mesh = Mesh2D(x, y)
    dop = np.tile(np.where(x < 1e-5, -1e17, 1e17), (y.size, 1))
    dev = Device2D(mesh, dop, models=Models(bgn=False, dg=True))
    dev.add_contact("left", i=[0], j=list(range(mesh.Ny)), V=0.0)
    dev.add_gate("g", i=[mesh.Nx // 2], j=[0], tox_cm=5e-7, Vfb=0.0)
    dev.solve_equilibrium()
    assert np.all(np.isfinite(dev.psi))
    assert np.all(np.isfinite(dev._dg_Lam_n))
    assert np.all(np.isfinite(dev._dg_Lam_p))


# ---------------------------------------------------------------- S1-G5
@pytest.mark.parametrize("extra", [
    dict(fd=True),
    dict(incomplete_ion=True),
    dict(band_offset="affinity"),
])
def test_g5_refused_compositions(extra):
    x, y = _pn_junction_mesh()
    mesh = Mesh2D(x, y)
    dop = np.tile(np.where(x < 1e-5, -1e17, 1e17), (y.size, 1))
    kwargs = dict(bgn=False, dg=True)
    kwargs.update(extra)
    with pytest.raises(NotImplementedError):
        Device2D(mesh, dop, models=Models(**kwargs))


# ---------------------------------------------------------------- S1-G6
def test_g6_converges_and_is_deterministic():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        dev_a = _make_device()
        dev_a.solve_equilibrium()
        dev_b = _make_device()
        dev_b.solve_equilibrium()
    assert np.array_equal(dev_a.psi, dev_b.psi)
    assert np.array_equal(dev_a._dg_Lam_n, dev_b._dg_Lam_n)
    assert np.array_equal(dev_a._dg_Lam_p, dev_b._dg_Lam_p)


# --------------------------------------------------------- extra sanity
def test_dg_actually_moves_the_solution():
    dev_classical = _make_device(dg=False)
    dev_classical.solve_equilibrium()
    dev_dg = _make_device(dg=True, dg_gamma=1.0)
    dev_dg.solve_equilibrium()
    rel = np.abs(dev_dg.n - dev_classical.n).max() / dev_classical.n.max()
    assert rel > 1e-6, "DG produced no measurable effect"

    dev_dg2 = _make_device(dg=True, dg_gamma=2.0)
    dev_dg2.solve_equilibrium()
    assert np.abs(dev_dg2._dg_Lam_n).max() > np.abs(dev_dg._dg_Lam_n).max(), \
        "DG effect should grow with gamma"


def test_solve_bias_refuses_dg():
    dev = _make_device()
    with pytest.raises(NotImplementedError):
        dev.solve_bias({"left": 0.0, "right": 0.1})
