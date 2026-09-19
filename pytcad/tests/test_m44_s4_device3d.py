"""M44 Slice 4: coupled electron energy balance wired into Device3D.

Mirrors test_m44_s4_device2d.py -- same three-bug lesson applied from
the start here (DirichletBC/PinnedBC array shape, n_lag floor,
transverse control-volume weight), see M44-HYDRODYNAMIC-PLAN.md
Slice 4 for the full record. One NEW shape bug found here: `contact_k`
is reassigned from a list to a deduped ndarray earlier in
`_residual_jacobian`, so re-wrapping it in `np.concatenate` a second
time raised "zero-dimensional arrays cannot be concatenated" -- fixed
by reusing the already-deduped array directly.

Gates:
  G1  Models(energy_balance=False) bit-identical to the pre-M44 solver.
  G2  y/z-uniform reduction to Device1D's own Slice-1 result.
  G3  Physical sanity: Tn never drops below TL.
"""
import numpy as np

from pytcad.device3d import Device3D
from pytcad.mesh3d import Mesh3D
from pytcad.device import Device1D, Models, NewtonOptions


def _diode3d(Nx=21, Ny=3, Nz=3, L=1e-4, W=0.3e-4):
    x = np.linspace(0.0, L, Nx)
    y = np.linspace(0.0, W, Ny)
    z = np.linspace(0.0, W, Nz)
    mesh = Mesh3D(x, y, z)
    doping1d = np.where(x < 0.5 * L, 1e17, -1e17)
    doping3d = np.tile(doping1d, (Nz, Ny, 1))
    return mesh, doping3d, x, doping1d


def _make(mesh, doping3d, models, Nz, Ny, Nx):
    dev = Device3D(mesh, doping3d, models=models)
    for k in range(Nz):
        for j in range(Ny):
            dev.add_contact(f"L{k}_{j}", 0, j, k, V=0.0)
            dev.add_contact(f"R{k}_{j}", Nx - 1, j, k, V=0.0)
    return dev


def _voltages(Nz, Ny, V):
    volt = {}
    for k in range(Nz):
        for j in range(Ny):
            volt[f"L{k}_{j}"] = 0.0
            volt[f"R{k}_{j}"] = V
    return volt


def test_g1_off_path_bit_identical():
    mesh, doping3d, x, doping1d = _diode3d()
    Nz, Ny, Nx = doping3d.shape
    opts = NewtonOptions()

    dev_off = _make(mesh, doping3d, Models(energy_balance=False), Nz, Ny, Nx)
    dev_off.solve_equilibrium(opts)
    dev_off.solve_bias(_voltages(Nz, Ny, 0.5), opts)

    dev_base = _make(mesh, doping3d, Models(), Nz, Ny, Nx)
    dev_base.solve_equilibrium(opts)
    dev_base.solve_bias(_voltages(Nz, Ny, 0.5), opts)

    assert np.array_equal(dev_off.psi, dev_base.psi)
    assert np.array_equal(dev_off.n, dev_base.n)
    assert np.array_equal(dev_off.Jn_x, dev_base.Jn_x)


def test_g2_yz_uniform_reduction_to_device1d():
    mesh, doping3d, x, doping1d = _diode3d()
    Nz, Ny, Nx = doping3d.shape
    opts = NewtonOptions()

    dev1 = Device1D(x, doping1d, models=Models(energy_balance=True))
    dev1.solve_equilibrium(opts)
    dev1.solve_bias([0.0, 0.5], opts)
    assert dev1.last_converged

    dev3 = _make(mesh, doping3d, Models(energy_balance=True), Nz, Ny, Nx)
    dev3.solve_equilibrium(opts)
    dev3.solve_bias(_voltages(Nz, Ny, 0.5), opts)
    assert dev3.last_converged

    diff = np.abs(dev3.Tn - dev1.Tn[None, None, :]).max()
    assert diff < 1e-6, (
        f"y/z-uniform Device3D Tn should reproduce Device1D's own "
        f"Slice-1 result to round-off, got max diff {diff:.3e}")
    assert np.abs(dev3.Jn_y).max() < 1e-10
    assert np.abs(dev3.Jn_z).max() < 1e-10


def test_g3_no_negative_heating():
    mesh, doping3d, x, doping1d = _diode3d()
    Nz, Ny, Nx = doping3d.shape
    opts = NewtonOptions()
    dev = _make(mesh, doping3d, Models(energy_balance=True), Nz, Ny, Nx)
    dev.solve_equilibrium(opts)
    dev.solve_bias(_voltages(Nz, Ny, 0.5), opts)
    assert dev.last_converged
    assert dev.Tn.min() >= dev.T - 1e-6
    assert dev.Tn.max() > dev.T * 1.05
