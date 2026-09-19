"""M44 Slice 4: coupled electron energy balance wired into Device2D.

Reuses `pytcad.hydro_grid.grid_hydro` (Slice 3, its own FD-Jacobian/
reduction gates already cover the kernel itself) -- these gates check
the INTEGRATION: DOF-append wiring, the per-iteration Wachutka Joule-
heating computation, and the Tn-consistent Canali mobility feedback,
end to end through a real Device2D.solve_bias() call.

See M44-HYDRODYNAMIC-PLAN.md Slice 4 for the three real bugs found
while gating this (a DirichletBC array-shape bug, an unfloored deep-
minority-density rank deficiency, and a missing transverse control-
volume weight on the flux-divergence term) and how each was diagnosed.

Gates:
  G1  Models(energy_balance=False) bit-identical to the pre-M44 solver.
  G2  y-uniform reduction to Device1D's own Slice-1 result -- THE
      critical gate: a y-invariant 2D diode must reproduce Device1D's
      converged Tn(x) to round-off, not just approximately.
  G3  Physical sanity: Tn never drops below TL (the Wachutka/M19-style
      negative-heating pathology Slice 1 already found once).
"""
import numpy as np

from pytcad.device2d import Device2D
from pytcad.mesh2d import Mesh2D
from pytcad.device import Device1D, Models, NewtonOptions


def _diode2d(Nx=41, Ny=3, L=1e-4, W=0.3e-4):
    x = np.linspace(0.0, L, Nx)
    y = np.linspace(0.0, W, Ny)
    mesh = Mesh2D(x, y)
    doping1d = np.where(x < 0.5 * L, 1e17, -1e17)
    doping2d = np.tile(doping1d, (Ny, 1))
    return mesh, doping2d, x, doping1d


def _make(mesh, doping2d, models, Ny, Nx):
    dev = Device2D(mesh, doping2d, models=models)
    for j in range(Ny):
        dev.add_contact(f"L{j}", 0, j, V=0.0)
        dev.add_contact(f"R{j}", Nx - 1, j, V=0.0)
    return dev


def test_g1_off_path_bit_identical():
    mesh, doping2d, x, doping1d = _diode2d()
    Ny, Nx = doping2d.shape
    opts = NewtonOptions()

    dev_off = _make(mesh, doping2d, Models(energy_balance=False), Ny, Nx)
    dev_off.solve_equilibrium(opts)
    dev_off.solve_bias({**{f"L{j}": 0.0 for j in range(Ny)},
                        **{f"R{j}": 0.5 for j in range(Ny)}}, opts)

    dev_base = _make(mesh, doping2d, Models(), Ny, Nx)
    dev_base.solve_equilibrium(opts)
    dev_base.solve_bias({**{f"L{j}": 0.0 for j in range(Ny)},
                         **{f"R{j}": 0.5 for j in range(Ny)}}, opts)

    assert np.array_equal(dev_off.psi, dev_base.psi)
    assert np.array_equal(dev_off.n, dev_base.n)
    assert np.array_equal(dev_off.Jn_x, dev_base.Jn_x)


def test_g2_y_uniform_reduction_to_device1d():
    mesh, doping2d, x, doping1d = _diode2d()
    Ny, Nx = doping2d.shape
    opts = NewtonOptions()

    dev1 = Device1D(x, doping1d, models=Models(energy_balance=True))
    dev1.solve_equilibrium(opts)
    dev1.solve_bias([0.0, 0.5], opts)
    assert dev1.last_converged

    dev2 = _make(mesh, doping2d, Models(energy_balance=True), Ny, Nx)
    dev2.solve_equilibrium(opts)
    dev2.solve_bias({**{f"L{j}": 0.0 for j in range(Ny)},
                     **{f"R{j}": 0.5 for j in range(Ny)}}, opts)
    assert dev2.last_converged

    for row in range(Ny):
        diff = np.abs(dev2.Tn[row] - dev1.Tn).max()
        assert diff < 1e-6, (
            f"row {row}: y-uniform Device2D Tn should reproduce "
            f"Device1D's own Slice-1 result to round-off, got "
            f"max diff {diff:.3e}")
    assert np.abs(dev2.Jn_y).max() < 1e-10


def test_g3_no_negative_heating():
    mesh, doping2d, x, doping1d = _diode2d()
    Ny, Nx = doping2d.shape
    opts = NewtonOptions()
    dev = _make(mesh, doping2d, Models(energy_balance=True), Ny, Nx)
    dev.solve_equilibrium(opts)
    dev.solve_bias({**{f"L{j}": 0.0 for j in range(Ny)},
                    **{f"R{j}": 0.5 for j in range(Ny)}}, opts)
    assert dev.last_converged
    assert dev.Tn.min() >= dev.T - 1e-6
    assert dev.Tn.max() > dev.T * 1.05
