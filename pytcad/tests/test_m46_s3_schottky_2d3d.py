"""M46-S3 -- Schottky contacts lifted to Device2D and Device3D.

Device2D gets FULL parity with Device1D: a SchottkyBC subclassing
DirichletBC (so every existing `isinstance(bc, DirichletBC)` site
already treats it correctly with zero changes), both S1's Dirichlet
approximation (A_star=None) and S2's Robin thermionic-flux BC
(A_star given) -- the Robin mode reuses Device2D's OWN pre-existing
M14 G-C S_n/S_p machinery, generalized from a single global velocity
to a per-node one (majority carrier only; refused combined with a
nonzero global S_n/S_p).

Device3D gets ONLY S1 (the Dirichlet approximation): Device3D's own
constructor already refuses Models.S_n/S_p outright (no Robin-BC
machinery to reuse at all), so SchottkyBC(A_star=...) is refused there
by add_schottky_contact -- a real, disclosed scope limit, not an
oversight.

A hard-debug finding during this slice: the first draft of Device2D's
per-node Robin/Dirichlet row splitting dropped the +1/+2 column-index
offsets when building `strip_rows_list` (rows meant for the n/p
continuity equations were marked as if they were the psi row instead).
Caught immediately by G1's FD-Jacobian gate (worst error 1.0, i.e.
completely wrong, not a rounding issue) before any physics gate was
trusted -- fixed by restoring the offsets; the same gate then passed
at 1.7e-9. Recorded here as evidence the gate did its job, not
scrubbed from the record.

Gates:
  G1  FD-Jacobian, Device2D Robin mode (S2 lift).
  G2  FD-Jacobian, Device3D Dirichlet mode (S1 lift).
  G3  Device2D: A_star=None reproduces the Dirichlet approximation;
      equilibrium matches the Robin mode exactly (Jn=0 invariant).
  G4  Device2D and Device3D: a transversely-uniform 2D/3D Schottky
      device reduces to Device1D's own SchottkyContact result at
      equilibrium, to floating-point noise -- the load-bearing
      dimensional-lift gate (4d.4's rule).
  G5  Device2D rectifies under bias (forward >> reverse current),
      both Dirichlet and Robin modes.
  G6  Device3D solves cleanly under bias and rectifies (Dirichlet
      mode only).
  G7  Device2D: S_n/S_p combined with a Robin-mode SchottkyBC is
      refused. Device3D: SchottkyBC(A_star=...) is refused outright.
"""
import warnings

import numpy as np
import pytest

from pytcad.device import Device1D, Models, NewtonOptions, SchottkyContact
from pytcad.device2d import Device2D
from pytcad.device3d import Device3D
from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D
from pytcad.mesh import graded_mesh
from pytcad.schottky import richardson_a_star

_A_STAR_N = richardson_a_star("Si", "n")


def _mesh_2d(fine=False):
    x = (graded_mesh(2e-4, [0.0], h_min=2e-6, h_max=1e-5) if fine
        else graded_mesh(2e-4, [0.0], 1e-6, 4e-6))
    y = np.linspace(0.0, 1e-5, 3 if fine else 4)
    return x, y


def _device_2d(A_star=None, fine=False):
    x, y = _mesh_2d(fine)
    mesh = Mesh2D(x, y)
    dop = np.full((mesh.Ny, mesh.Nx), 1e16)
    dev = Device2D(mesh, dop, models=Models(bgn=False))
    dev.add_schottky_contact("left", i=[0] * mesh.Ny, j=list(range(mesh.Ny)),
                             phi_metal_eV=4.8, A_star=A_star)
    dev.add_contact("right", i=[mesh.Nx - 1] * mesh.Ny, j=list(range(mesh.Ny)), V=0.0)
    return dev


def _device_3d(A_star=None, fine=False):
    x, y = _mesh_2d(fine)
    z = np.linspace(0.0, 1e-5, 3)
    mesh = Mesh3D(x, y, z)
    dop = np.full((mesh.Nz, mesh.Ny, mesh.Nx), 1e16)
    jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev = Device3D(mesh, dop, models=Models(bgn=False))
    dev.add_schottky_contact("left", i=np.zeros_like(jj), j=jj, k=kk,
                             phi_metal_eV=4.8, A_star=A_star)
    dev.add_contact("right", i=np.full_like(jj, mesh.Nx - 1), j=jj, k=kk, V=0.0)
    return dev


# ---------------------------------------------------------------- G1
def test_g1_fd_jacobian_device2d_robin():
    dev = _device_2d(A_star=_A_STAR_N, fine=True)
    dev.solve_equilibrium()
    N = dev.N
    shp = (dev.Ny, dev.Nx)
    rng = np.random.default_rng(2)
    psi0 = dev.psi + rng.uniform(-0.2, 0.2, shp)
    n0_ = dev.n * (1.0 + rng.uniform(-0.05, 0.05, shp))
    p0_ = dev.p * (1.0 + rng.uniform(-0.05, 0.05, shp))
    voltages = {"left": 0.1, "right": 0.0}
    F0, J, *_ = dev._residual_jacobian(psi0, n0_, p0_, voltages)
    u0 = np.stack([psi0, n0_, p0_], axis=2).ravel()

    def unpack(u):
        a = u.reshape(*shp, 3)
        return a[:, :, 0], a[:, :, 1], a[:, :, 2]

    eps = 1e-6
    cols = rng.choice(3 * N, size=60, replace=False)
    worst = 0.0
    for c in cols:
        up, um = u0.copy(), u0.copy()
        up[c] += eps; um[c] -= eps
        Fp, *_ = dev._residual_jacobian(*unpack(up), voltages)
        Fm, *_ = dev._residual_jacobian(*unpack(um), voltages)
        fd = (Fp - Fm) / (2 * eps)
        an = np.asarray(J[:, c].todense()).ravel()
        worst = max(worst, np.abs(fd - an).max() / max(np.abs(an).max(), 1e-12))
    assert worst < 5e-5, f"Device2D Robin FD-Jacobian mismatch: {worst:.3e}"


# ---------------------------------------------------------------- G2
def test_g2_fd_jacobian_device3d_dirichlet():
    dev = _device_3d(A_star=None, fine=True)
    dev.solve_equilibrium()
    N = dev.N
    shp = (dev.Nz, dev.Ny, dev.Nx)
    rng = np.random.default_rng(4)
    psi0 = dev.psi + rng.uniform(-0.2, 0.2, shp)
    n0_ = dev.n * (1.0 + rng.uniform(-0.05, 0.05, shp))
    p0_ = dev.p * (1.0 + rng.uniform(-0.05, 0.05, shp))
    voltages = {"left": 0.1, "right": 0.0}
    F0, J, *_ = dev._residual_jacobian(psi0, n0_, p0_, voltages)
    u0 = np.stack([psi0, n0_, p0_], axis=3).ravel()

    def unpack(u):
        a = u.reshape(*shp, 3)
        return a[..., 0], a[..., 1], a[..., 2]

    eps = 1e-6
    cols = rng.choice(3 * N, size=60, replace=False)
    worst = 0.0
    for c in cols:
        up, um = u0.copy(), u0.copy()
        up[c] += eps; um[c] -= eps
        Fp, *_ = dev._residual_jacobian(*unpack(up), voltages)
        Fm, *_ = dev._residual_jacobian(*unpack(um), voltages)
        fd = (Fp - Fm) / (2 * eps)
        an = np.asarray(J[:, c].todense()).ravel()
        worst = max(worst, np.abs(fd - an).max() / max(np.abs(an).max(), 1e-12))
    assert worst < 5e-5, f"Device3D Dirichlet FD-Jacobian mismatch: {worst:.3e}"


# ---------------------------------------------------------------- G3
def test_g3_device2d_equilibrium_robin_matches_dirichlet():
    d_dirichlet = _device_2d(A_star=None)
    d_robin = _device_2d(A_star=_A_STAR_N)
    d_dirichlet.solve_equilibrium()
    d_robin.solve_equilibrium()
    assert np.array_equal(d_dirichlet.psi, d_robin.psi)
    assert np.array_equal(d_dirichlet.n, d_robin.n)


# ---------------------------------------------------------------- G4
def test_g4_device2d_reduces_to_device1d():
    x, y = _mesh_2d()
    dop1d = np.full_like(x, 1e16)
    dev1 = Device1D(x, dop1d, models=Models(bgn=False),
                    schottky_left=SchottkyContact(phi_metal_eV=4.8))
    dev1.solve_equilibrium()

    dev2 = _device_2d(A_star=None)
    dev2.solve_equilibrium()

    assert np.abs(dev2.psi - dev1.psi[None, :]).max() < 1e-10
    assert (np.abs(dev2.n - dev1.n[None, :]).max() / dev1.n.max()) < 1e-9


def test_g4_device3d_reduces_to_device2d():
    d2 = _device_2d(A_star=None)
    d2.solve_equilibrium()
    d3 = _device_3d(A_star=None)
    d3.solve_equilibrium()
    assert np.abs(d3.psi - d2.psi[None, :, :]).max() < 1e-10
    assert (np.abs(d3.n - d2.n[None, :, :]).max() / d2.n.max()) < 1e-9


# ---------------------------------------------------------------- G5
@pytest.mark.parametrize("A_star", [None, _A_STAR_N])
def test_g5_device2d_rectifies(A_star):
    d_fwd = _device_2d(A_star=A_star)
    d_fwd.solve_equilibrium()
    d_fwd.solve_bias({"left": 0.3})
    I_fwd = d_fwd.terminal_current("left")

    d_rev = _device_2d(A_star=A_star)
    d_rev.solve_equilibrium()
    d_rev.solve_bias({"left": -0.3})
    I_rev = d_rev.terminal_current("left")

    assert abs(I_fwd) > 1e3 * abs(I_rev), (
        f"A_star={A_star}: insufficient rectification I_fwd={I_fwd:.3e} "
        f"I_rev={I_rev:.3e}")


# ---------------------------------------------------------------- G6
def test_g6_device3d_solves_and_rectifies():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        d_fwd = _device_3d(A_star=None)
        d_fwd.solve_equilibrium()
        d_fwd.solve_bias({"left": 0.3})
        I_fwd = d_fwd.terminal_current("left")

        d_rev = _device_3d(A_star=None)
        d_rev.solve_equilibrium()
        d_rev.solve_bias({"left": -0.3})
        I_rev = d_rev.terminal_current("left")
    assert abs(I_fwd) > 1e3 * abs(I_rev)


# ---------------------------------------------------------------- G7
def test_g7_device2d_s_n_combined_with_robin_refused():
    x, y = _mesh_2d()
    mesh = Mesh2D(x, y)
    dop = np.full((mesh.Ny, mesh.Nx), 1e16)
    dev = Device2D(mesh, dop, models=Models(bgn=False, S_n=1e4))
    dev.add_schottky_contact("left", i=[0] * mesh.Ny, j=list(range(mesh.Ny)),
                             phi_metal_eV=4.8, A_star=_A_STAR_N)
    dev.add_contact("right", i=[mesh.Nx - 1] * mesh.Ny, j=list(range(mesh.Ny)), V=0.0)
    dev.solve_equilibrium()
    with pytest.raises(NotImplementedError):
        dev.solve_bias({"left": 0.1})


def test_g7_device3d_robin_mode_refused():
    x, y = _mesh_2d()
    z = np.linspace(0.0, 1e-5, 3)
    mesh = Mesh3D(x, y, z)
    jj, kk = np.meshgrid(np.arange(mesh.Ny), np.arange(mesh.Nz))
    jj, kk = jj.ravel(), kk.ravel()
    dev = Device3D(mesh, np.full((mesh.Nz, mesh.Ny, mesh.Nx), 1e16),
                   models=Models(bgn=False))
    with pytest.raises(NotImplementedError):
        dev.add_schottky_contact("left", i=np.zeros_like(jj), j=jj, k=kk,
                                 phi_metal_eV=4.8, A_star=_A_STAR_N)
