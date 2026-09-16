"""M43 phase 2 acceptance gates -- steady-state 3D self-heating.

See M43-SELFHEATING-2D3D-PLAN.md for scope. pytcad/thermal3d.py is a
wholly separate module from device3d.py (never touched) -- the 3D
analogue of thermal2d.py, both now thin wrappers over
thermal_grid.py's dimension-generic core (mirrors ii_grid.py/
btbt_grid.py's "one kernel for Device2D and Device3D" pattern).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

from pytcad import Device2D, Device3D, Models
from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D
from pytcad.materials import SILICON
from pytcad.thermal import ThermalBC
from pytcad.thermal2d import solve_electrothermal_2d
from pytcad.thermal3d import (
    solve_lattice_temperature_3d, joule_heating_density_3d,
    solve_electrothermal_3d, _residual_jacobian_3d,
)

warnings.simplefilter("ignore")


def _junction_x(nx=17):
    x = np.linspace(0.0, 2.0e-4, nx)
    return x, np.where(x < 1.0e-4, -1e17, 1e17)


def _diode_2d(x, dop_1d, Wy=1e-4, Ny=5, T=300.0, **kw):
    y = np.linspace(0.0, Wy, Ny)
    mesh = Mesh2D(x, y)
    dop = np.tile(dop_1d, (Ny, 1))
    dev = Device2D(mesh, dop, T=T, models=Models(bgn=False, **kw))
    dev.add_contact("l", i=[0], j=list(range(Ny)), V=0.0)
    dev.add_contact("r", i=[mesh.Nx - 1], j=list(range(Ny)), V=0.0)
    return dev


def _diode_3d(x, dop_1d, Wy=1e-4, Wz=1e-4, Ny=4, Nz=4, T=300.0, **kw):
    """The SAME physical diode as _diode_2d, extruded z-uniformly."""
    y = np.linspace(0.0, Wy, Ny)
    z = np.linspace(0.0, Wz, Nz)
    mesh = Mesh3D(x=x, y=y, z=z)
    dop = np.broadcast_to(dop_1d, (Nz, Ny, x.size)).copy()
    dev = Device3D(mesh, dop, T=T, models=Models(bgn=False, **kw))
    kk, jj = np.meshgrid(range(Nz), range(Ny), indexing="ij")
    face = list(zip(jj.ravel(), kk.ravel()))
    dev.add_contact("l", i=[0] * len(face), j=[f[0] for f in face],
                     k=[f[1] for f in face], V=0.0)
    dev.add_contact("r", i=[mesh.Nx - 1] * len(face),
                     j=[f[0] for f in face], k=[f[1] for f in face], V=0.0)
    return dev


# ---------------------------------------------------------------- G-FD-3D
def test_g_fd_3d_jacobian_matches_numerical():
    """G-FD-3D: analytic vs central-FD Jacobian of the vectorized 3D
    residual (thermal_grid's generic core at D=3), mixed boundary kinds
    on all 3 axes including a corner shared by three different kinds."""
    rng = np.random.default_rng(1)
    Nx, Ny, Nz = 6, 4, 3
    x = np.linspace(0.0, 1e-3, Nx)
    y = np.linspace(0.0, 5e-4, Ny)
    z = np.linspace(0.0, 4e-4, Nz)
    T = 300.0 + 40.0 * rng.standard_normal((Nz, Ny, Nx))
    H = 1e3 * np.abs(rng.standard_normal((Nz, Ny, Nx)))
    bc_x_lo = ThermalBC.isothermal()
    bc_x_hi = ThermalBC.resistance(3.0)
    bc_y_lo = ThermalBC.resistance(2.0)
    bc_y_hi = ThermalBC.adiabatic()
    bc_z_lo = ThermalBC.resistance(1.5)
    bc_z_hi = ThermalBC.isothermal()

    F0, J0 = _residual_jacobian_3d(x, y, z, T, H, SILICON, 300.0,
                                    bc_x_lo, bc_x_hi, bc_y_lo, bc_y_hi,
                                    bc_z_lo, bc_z_hi)
    J0 = J0.toarray()

    h = 1e-4
    N = Nx * Ny * Nz
    Jfd = np.zeros_like(J0)
    Tflat = T.ravel()
    for k in range(N):
        Tp = Tflat.copy(); Tp[k] += h
        Tm = Tflat.copy(); Tm[k] -= h
        Fp, _ = _residual_jacobian_3d(x, y, z, Tp.reshape(Nz, Ny, Nx), H,
                                       SILICON, 300.0, bc_x_lo, bc_x_hi,
                                       bc_y_lo, bc_y_hi, bc_z_lo, bc_z_hi)
        Fm, _ = _residual_jacobian_3d(x, y, z, Tm.reshape(Nz, Ny, Nx), H,
                                       SILICON, 300.0, bc_x_lo, bc_x_hi,
                                       bc_y_lo, bc_y_hi, bc_z_lo, bc_z_hi)
        Jfd[:, k] = (Fp.ravel() - Fm.ravel()) / (2 * h)

    scale = np.maximum(np.abs(J0), 1.0)
    err = np.max(np.abs(J0 - Jfd) / scale)
    assert err < 2e-3, f"FD-Jacobian mismatch {err:.3e}"


# ---------------------------------------------------------------- G-BC-3D
def test_g_bc_3d_resistance_gives_higher_peak_than_isothermal():
    """G-BC-3D: same physical direction as the 1D/2D G-BC gates."""
    Nx, Ny, Nz = 15, 7, 6
    x = np.linspace(0.0, 1e-3, Nx)
    y = np.linspace(0.0, 5e-4, Ny)
    z = np.linspace(0.0, 4e-4, Nz)
    H = np.full((Nz, Ny, Nx), 5e5)

    iso = ThermalBC.isothermal()
    T_iso = solve_lattice_temperature_3d(x, y, z, H, SILICON, 300.0,
                                          iso, iso, iso, iso, iso, iso)
    res = ThermalBC.resistance(1.0)
    T_res = solve_lattice_temperature_3d(x, y, z, H, SILICON, 300.0,
                                          res, res, res, res, res, res)
    assert T_res.max() > T_iso.max(), (
        f"resistance-BC peak {T_res.max():.3f} K not above isothermal "
        f"peak {T_iso.max():.3f} K")


# ---------------------------------------------------------------- G-REDUCTION-3D
def test_g_reduction_z_uniform_3d_matches_2d_electrothermal():
    """ARCHITECTURE.md 4d.4: 'no dimensional lift lands without its
    reduction identity as a gate'. A z-UNIFORM 3D diode with ADIABATIC
    front/back must, by symmetry, carry zero z-direction heat flow
    anywhere -- so its electrothermal solve must reduce to
    thermal2d.py's own 2D solve_electrothermal_2d on the identical
    physical diode (which itself already reduces to 1D -- M43 phase
    1's own gate), both the temperature profile and the current
    roll-off ratio."""
    V, R_th, Wy, Ny = 0.55, 50.0, 1e-4, 4

    x, dop_1d = _junction_x()

    dev2d_iso = _diode_2d(x, dop_1d, Wy=Wy, Ny=Ny, T=300.0)
    dev2d_iso.solve_equilibrium()
    dev2d_iso.solve_bias({"l": V, "r": 0.0})
    I_iso_2d = dev2d_iso.terminal_current("l")

    dev_2d, T_2d, hist_2d = solve_electrothermal_2d(
        lambda T: _diode_2d(x, dop_1d, Wy=Wy, Ny=Ny, T=T),
        {"l": V, "r": 0.0}, 300.0,
        ThermalBC.resistance(R_th), ThermalBC.resistance(R_th),
        ThermalBC.adiabatic(), ThermalBC.adiabatic(), SILICON,
        max_outer=30)
    I_hot_2d = dev_2d.terminal_current("l")
    ratio_2d = I_hot_2d / I_iso_2d

    def build_3d(T):
        return _diode_3d(x, dop_1d, T=T)

    dev3d_iso = _diode_3d(x, dop_1d, T=300.0)
    dev3d_iso.solve_equilibrium()
    dev3d_iso.solve_bias({"l": V, "r": 0.0})
    I_iso_3d = dev3d_iso.terminal_current("l")

    dev_3d, T_3d, hist_3d = solve_electrothermal_3d(
        build_3d, {"l": V, "r": 0.0}, 300.0,
        ThermalBC.resistance(R_th), ThermalBC.resistance(R_th),
        ThermalBC.adiabatic(), ThermalBC.adiabatic(),
        ThermalBC.adiabatic(), ThermalBC.adiabatic(), SILICON,
        max_outer=30)
    I_hot_3d = dev_3d.terminal_current("l")
    ratio_3d = I_hot_3d / I_iso_3d

    # every (y,x) slab of the 3D result (for any z) must match the 2D
    # result (z-uniform problem, adiabatic z boundaries)
    slab_err = np.abs(T_3d - T_2d[None, :, :]).max()
    scale = T_2d.max() - 300.0
    assert slab_err < 1e-2 * scale, (
        f"3D slabs disagree with the 2D profile by {slab_err:.4f} K "
        f"(peak rise {scale:.4f} K)")

    assert abs(ratio_3d - ratio_2d) < 3e-2 * ratio_2d, (
        f"3D ratio {ratio_3d:.4f} vs 2D ratio {ratio_2d:.4f}")
    assert ratio_3d > 1.0, "expected the same positive-feedback direction as 1D/2D"


# ---------------------------------------------------------------- G-OFF-BIT-IDENTITY-3D
def test_g_off_bit_identity_3d_path_unaffected():
    """G-OFF-BIT-IDENTITY-3D: importing thermal3d must not change a
    single bit of an ordinary isothermal Device3D solve -- device3d.py
    is never touched by this module."""
    x, dop = _junction_x()
    dev_a = _diode_3d(x, dop, T=300.0)
    dev_a.solve_equilibrium()
    dev_a.solve_bias({"l": 0.3, "r": 0.0})

    import pytcad.thermal3d  # noqa: F401

    dev_b = _diode_3d(x, dop, T=300.0)
    dev_b.solve_equilibrium()
    dev_b.solve_bias({"l": 0.3, "r": 0.0})

    assert np.array_equal(dev_a.psi, dev_b.psi)
    assert np.array_equal(dev_a.n, dev_b.n)
    assert np.array_equal(dev_a.p, dev_b.p)
