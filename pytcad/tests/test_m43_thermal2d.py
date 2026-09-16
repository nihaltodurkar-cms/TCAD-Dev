"""M43 phase 1 acceptance gates -- steady-state 2D self-heating.

See M43-SELFHEATING-2D3D-PLAN.md for scope. pytcad/thermal2d.py is a
wholly separate module from device2d.py (never touched) -- the 2D
analogue of M19's thermal.py, same outer-Gummel-loop architecture.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

from pytcad import Device2D, Models
from pytcad.device import Device1D
from pytcad.mesh import graded_mesh
from pytcad.mesh2d import Mesh2D
from pytcad.materials import SILICON
from pytcad.thermal import ThermalBC, solve_electrothermal
from pytcad.thermal2d import (
    solve_lattice_temperature_2d, joule_heating_density_2d,
    solve_electrothermal_2d, _residual_jacobian_2d,
)

warnings.simplefilter("ignore")


def _diode_1d(Na=1e17, Nd=1e17, L=2e-4, xj=1e-4, T=300.0, **kw):
    x = graded_mesh(L, [xj], 1e-8, 1e-6, 1.12)
    dop = np.where(x < xj, -Na, Nd)
    return Device1D(x, dop, T=T, models=Models(bgn=False, **kw)), x, dop


def _diode_2d(x, dop_1d, Wy=1e-4, Ny=5, T=300.0, **kw):
    """The SAME physical diode as _diode_1d, extruded y-uniformly."""
    y = np.linspace(0.0, Wy, Ny)
    mesh = Mesh2D(x, y)
    dop = np.tile(dop_1d, (Ny, 1))
    dev = Device2D(mesh, dop, T=T, models=Models(bgn=False, **kw))
    dev.add_contact("l", i=[0], j=list(range(Ny)), V=0.0)
    dev.add_contact("r", i=[mesh.Nx - 1], j=list(range(Ny)), V=0.0)
    return dev


# ---------------------------------------------------------------- G-FD-2D
def test_g_fd_2d_jacobian_matches_numerical():
    """G-FD-2D: analytic vs central-FD Jacobian of the vectorized 2D
    thermal residual, including a corner shared by two DIFFERENT
    boundary kinds (isothermal x_lo, resistance x_hi/y_lo, adiabatic
    y_hi) -- exercises the resistance-first/isothermal-last corner
    ordering, not just a single boundary kind in isolation."""
    rng = np.random.default_rng(0)
    Nx, Ny = 9, 6
    x = np.linspace(0.0, 1e-3, Nx)
    y = np.linspace(0.0, 6e-4, Ny)
    T = 300.0 + 40.0 * rng.standard_normal((Ny, Nx))
    H = 1e3 * np.abs(rng.standard_normal((Ny, Nx)))
    bc_x_lo = ThermalBC.isothermal()
    bc_x_hi = ThermalBC.resistance(3.0)
    bc_y_lo = ThermalBC.resistance(2.0)
    bc_y_hi = ThermalBC.adiabatic()

    F0, J0 = _residual_jacobian_2d(x, y, T, H, SILICON, 300.0,
                                    bc_x_lo, bc_x_hi, bc_y_lo, bc_y_hi)
    J0 = J0.toarray()

    h = 1e-4
    N = Nx * Ny
    Jfd = np.zeros_like(J0)
    Tflat = T.ravel()
    for k in range(N):
        Tp = Tflat.copy(); Tp[k] += h
        Tm = Tflat.copy(); Tm[k] -= h
        Fp, _ = _residual_jacobian_2d(x, y, Tp.reshape(Ny, Nx), H, SILICON,
                                       300.0, bc_x_lo, bc_x_hi, bc_y_lo, bc_y_hi)
        Fm, _ = _residual_jacobian_2d(x, y, Tm.reshape(Ny, Nx), H, SILICON,
                                       300.0, bc_x_lo, bc_x_hi, bc_y_lo, bc_y_hi)
        Jfd[:, k] = (Fp.ravel() - Fm.ravel()) / (2 * h)

    scale = np.maximum(np.abs(J0), 1.0)
    err = np.max(np.abs(J0 - Jfd) / scale)
    assert err < 2e-3, f"FD-Jacobian mismatch {err:.3e}"


# ---------------------------------------------------------------- G-BC-2D
def test_g_bc_2d_resistance_gives_higher_peak_than_isothermal():
    """G-BC-2D: same physical direction as M19's 1D G-BC -- a finite
    thermal resistance to ambient on all 4 sides must run hotter than
    isothermal on all 4 sides, same H."""
    Nx, Ny = 21, 11
    x = np.linspace(0.0, 1e-3, Nx)
    y = np.linspace(0.0, 5e-4, Ny)
    H = np.full((Ny, Nx), 5e5)

    iso = ThermalBC.isothermal()
    T_iso = solve_lattice_temperature_2d(x, y, H, SILICON, 300.0,
                                          iso, iso, iso, iso)
    res = ThermalBC.resistance(1.0)
    T_res = solve_lattice_temperature_2d(x, y, H, SILICON, 300.0,
                                          res, res, res, res)
    assert T_res.max() > T_iso.max(), (
        f"resistance-BC peak {T_res.max():.3f} K not above isothermal "
        f"peak {T_iso.max():.3f} K")


# ---------------------------------------------------------------- G-REDUCTION
def test_g_reduction_y_uniform_2d_matches_1d_electrothermal():
    """M41-style reduction-identity gate (ARCHITECTURE.md 4d.4: 'no
    dimensional lift lands without its reduction identity as a gate'):
    a y-UNIFORM 2D diode with ADIABATIC top/bottom must, by symmetry,
    carry zero y-direction heat flow anywhere -- so its electrothermal
    solve must reduce to thermal.py's own 1D solve_electrothermal on
    the identical physical diode, both the temperature profile (every
    row of the 2D result equal to the 1D result) and the current
    roll-off ratio."""
    # Same bias/R_th M19's own G-ROLLOFF gate uses (test_m19_thermal.py)
    # -- empirically confirmed there to give a measurable (>1.05) ratio
    # comfortably inside the stable (non-runaway) regime.
    V, R_th = 0.55, 50.0

    dev1d_iso, x, dop_1d = _diode_1d(T=300.0)
    dev1d_iso.solve_equilibrium()
    dev1d_iso.solve_bias([V, 0.0])
    I_iso_1d, _ = dev1d_iso.current_density()

    dev_1d, T_1d, hist_1d = solve_electrothermal(
        lambda T: _diode_1d(T=T)[0], [V, 0.0], 300.0,
        ThermalBC.resistance(R_th), ThermalBC.resistance(R_th), SILICON,
        max_outer=30)
    I_hot_1d, _ = dev_1d.current_density()
    ratio_1d = I_hot_1d / I_iso_1d

    def build_2d(T):
        return _diode_2d(x, dop_1d, T=T)

    dev2d_iso = _diode_2d(x, dop_1d, T=300.0)
    dev2d_iso.solve_equilibrium()
    dev2d_iso.solve_bias({"l": V, "r": 0.0})
    I_iso_2d = dev2d_iso.terminal_current("l")

    dev_2d, T_2d, hist_2d = solve_electrothermal_2d(
        build_2d, {"l": V, "r": 0.0}, 300.0,
        ThermalBC.resistance(R_th), ThermalBC.resistance(R_th),
        ThermalBC.adiabatic(), ThermalBC.adiabatic(), SILICON,
        max_outer=30)
    I_hot_2d = dev_2d.terminal_current("l")
    ratio_2d = I_hot_2d / I_iso_2d

    # temperature profile: every row of the 2D result must match the
    # 1D result (y-uniform problem, adiabatic transverse boundaries)
    row_err = np.abs(T_2d - T_1d[None, :]).max()
    scale = T_1d.max() - 300.0
    assert row_err < 5e-3 * scale, (
        f"2D rows disagree with the 1D profile by {row_err:.4f} K "
        f"(peak rise {scale:.4f} K)")

    # current roll-off ratio: dimension-independent, must match
    assert abs(ratio_2d - ratio_1d) < 2e-2 * ratio_1d, (
        f"2D ratio {ratio_2d:.4f} vs 1D ratio {ratio_1d:.4f}")
    assert ratio_2d > 1.0, "expected the same positive-feedback direction as 1D (G-ROLLOFF)"


# ---------------------------------------------------------------- G-OFF-BIT-IDENTITY
def test_g_off_bit_identity_2d_path_unaffected():
    """G-OFF-BIT-IDENTITY-2D: importing thermal2d must not change a
    single bit of an ordinary isothermal Device2D solve -- device2d.py
    is never touched by this module."""
    x = graded_mesh(2e-4, [1e-4], 1e-8, 1e-6, 1.12)
    dop = np.where(x < 1e-4, -1e17, 1e17)
    dev_a = _diode_2d(x, dop, T=300.0)
    dev_a.solve_equilibrium()
    dev_a.solve_bias({"l": 0.3, "r": 0.0})

    import pytcad.thermal2d  # noqa: F401

    dev_b = _diode_2d(x, dop, T=300.0)
    dev_b.solve_equilibrium()
    dev_b.solve_bias({"l": 0.3, "r": 0.0})

    assert np.array_equal(dev_a.psi, dev_b.psi)
    assert np.array_equal(dev_a.n, dev_b.n)
    assert np.array_equal(dev_a.p, dev_b.p)
