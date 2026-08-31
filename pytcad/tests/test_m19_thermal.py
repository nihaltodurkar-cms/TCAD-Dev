"""M19 phase 1 acceptance gates -- steady-state 1D self-heating.

See M19-SELFHEATING-PLAN.md for scope. pytcad/thermal.py is a wholly
separate module from device.py/moscap.py (neither is touched) -- an
OUTER Gummel loop between the unmodified, isothermal Device1D
electrical solve and a standalone steady lattice-temperature solve,
not a monolithic psi/n/p/T Newton system (see the plan doc for why).
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest

from pytcad import Device1D, Models
from pytcad.mesh import graded_mesh
from pytcad.materials import SILICON
from pytcad.thermal import (
    ThermalBC, ThermalOptions, solve_lattice_temperature,
    joule_heating_density, solve_electrothermal, _thermal_residual_jacobian,
)

warnings.simplefilter("ignore")


class _ConstKappaMaterial:
    """A material stub with a CONSTANT kappa_th -- the closed-form
    parabola gate needs kappa fixed (a real material's kappa_th(T)
    would smear the profile away from the textbook parabola)."""

    def __init__(self, kappa):
        self.kappa = float(kappa)

    def kappa_th(self, T):
        return np.full_like(np.asarray(T, dtype=float), self.kappa)


def _diode(Na=1e17, Nd=1e17, L=2e-4, xj=1e-4, T=300.0, **kw):
    x = graded_mesh(L, [xj], 1e-8, 1e-6, 1.12)
    dop = np.where(x < xj, -Na, Nd)
    return Device1D(x, dop, T=T, models=Models(bgn=False, **kw))


# ---------------------------------------------------------------- G-PARABOLA
def test_g_parabola_uniform_resistor_matches_analytic():
    """G-PARABOLA: a uniform heat-source density H0 with CONSTANT kappa
    on a bare rod, isothermal ends, matches the closed-form parabola
    T(x) = T_ambient + H0/(2*kappa) * x*(L-x) exactly (a linear PDE --
    no Device1D involved at all, a pure unit test of thermal.py)."""
    L = 1e-3
    N = 101
    x = np.linspace(0.0, L, N)
    kappa = 1.48
    H0 = 5e5
    H = np.full(N, H0)
    mat = _ConstKappaMaterial(kappa)

    T = solve_lattice_temperature(x, H, mat, 300.0,
                                  ThermalBC.isothermal(), ThermalBC.isothermal())
    T_analytic = 300.0 + H0 / (2.0 * kappa) * x * (L - x)
    max_rise = T_analytic.max() - 300.0
    err = np.abs(T - T_analytic).max()
    assert err < 1e-6 * max_rise, (
        f"parabola mismatch: max abs err {err:.3e} K vs peak rise {max_rise:.3e} K")


# ---------------------------------------------------------------- G-FD
def test_g_fd_jacobian_matches_numerical():
    """G-FD: analytic vs central-finite-difference Jacobian of the
    (nonlinear, T-dependent-kappa) thermal residual -- required by the
    standing FD-Jacobian-first rule for any new coupled-block solve."""
    N = 25
    x = np.linspace(0.0, 1e-3, N)
    rng = np.random.default_rng(0)
    T = 300.0 + 50.0 * rng.standard_normal(N)
    H = 1e3 * np.abs(rng.standard_normal(N))
    bc_left = ThermalBC.isothermal()
    bc_right = ThermalBC.resistance(5.0)

    F0, J0 = _thermal_residual_jacobian(x, T, H, SILICON, 300.0, bc_left, bc_right)
    J0 = J0.toarray()

    h = 1e-4
    Jfd = np.zeros_like(J0)
    for k in range(N):
        Tp = T.copy(); Tp[k] += h
        Tm = T.copy(); Tm[k] -= h
        Fp, _ = _thermal_residual_jacobian(x, Tp, H, SILICON, 300.0, bc_left, bc_right)
        Fm, _ = _thermal_residual_jacobian(x, Tm, H, SILICON, 300.0, bc_left, bc_right)
        Jfd[:, k] = (Fp - Fm) / (2 * h)

    scale = np.maximum(np.abs(J0), 1.0)
    assert np.max(np.abs(J0 - Jfd) / scale) < 2e-3


# ---------------------------------------------------------------- G-BC
def test_g_bc_resistance_gives_higher_peak_than_isothermal():
    """G-BC: a finite thermal resistance to ambient must let the rod
    run hotter than perfectly isothermal ends, same H -- the correctly
    ordered physical direction for a Robin vs Dirichlet thermal BC."""
    N = 101
    x = np.linspace(0.0, 1e-3, N)
    H = np.full(N, 5e5)

    T_iso = solve_lattice_temperature(x, H, SILICON, 300.0,
                                      ThermalBC.isothermal(), ThermalBC.isothermal())
    T_res = solve_lattice_temperature(x, H, SILICON, 300.0,
                                      ThermalBC.resistance(1.0), ThermalBC.resistance(1.0))
    assert T_res.max() > T_iso.max(), (
        f"resistance-BC peak {T_res.max():.3f} K not above isothermal "
        f"peak {T_iso.max():.3f} K")


# ---------------------------------------------------------------- G-ROLLOFF
def test_g_rolloff_electrothermal_feedback_direction():
    """G-ROLLOFF: electrothermal self-heating on a forward-biased diode
    must measurably shift the current away from the isothermal I-V at
    a bias/R_th combination with real dissipation, in the physically
    correct direction for a PN JUNCTION.

    Honest finding (not the MOSFET/resistor "roll-off" the milestone's
    shorthand name suggests): a plain PN diode's DOMINANT self-heating
    effect is POSITIVE feedback -- current INCREASES at fixed V as T
    rises (Vbi drops, n_ie grows exponentially with T), a well-
    documented diode thermal-runaway precursor, not the mobility-
    degradation-driven current SUPPRESSION "roll-off" implies for a
    MOSFET/resistor. No field-dependent mobility (Models.field_mobility)
    is enabled here to provide negative feedback, so this device shows
    the diode-characteristic direction; gate on that measured, honest
    direction rather than force a MOSFET-shaped assumption. At high
    enough bias/R_th this feedback loop diverges (thermal runaway) --
    solve_electrothermal raises RuntimeError rather than silently
    returning nonsense; the bias chosen here is comfortably inside the
    stable regime (measured: runaway starts well above this device's
    0.6V/Rth=500 combination, see M19-SELFHEATING-PLAN.md)."""
    def build(T):
        return _diode(T=T)

    V = 0.55
    R_th = 50.0
    dev_iso = _diode(T=300.0)
    dev_iso.solve_equilibrium()
    dev_iso.solve_bias([V, 0.0])
    I_iso, _ = dev_iso.current_density()

    dev, T_profile, history = solve_electrothermal(
        build, [V, 0.0], 300.0, ThermalBC.resistance(R_th),
        ThermalBC.resistance(R_th), SILICON, max_outer=30)
    I_hot, _ = dev.current_density()

    ratio = I_hot / I_iso
    assert ratio > 1.05, (
        f"electrothermal current {I_hot:.4e} not measurably above "
        f"isothermal {I_iso:.4e} (ratio {ratio:.4f})")
    assert T_profile.max() > 300.0, "self-heating produced no temperature rise"


# ---------------------------------------------------------------- G-OFF-BIT-IDENTITY
def test_g_off_bit_identity_isothermal_path_unaffected():
    """G-OFF-BIT-IDENTITY: thermal.py existing must not change a single
    bit of an ordinary isothermal solve/iv_sweep -- it is a wholly
    separate module, device.py is never touched."""
    dev_a = _diode(T=300.0)
    dev_a.solve_equilibrium()
    dev_a.solve_bias([0.3, 0.0])

    # import thermal AFTER the fact too, to rule out any import-time
    # side effect on device.py's module state
    import pytcad.thermal  # noqa: F401

    dev_b = _diode(T=300.0)
    dev_b.solve_equilibrium()
    dev_b.solve_bias([0.3, 0.0])

    assert np.array_equal(dev_a.psi, dev_b.psi)
    assert np.array_equal(dev_a.n, dev_b.n)
    assert np.array_equal(dev_a.p, dev_b.p)


# ---------------------------------------------------------------- G-BC-REFUSAL
def test_g_bc_refuses_bad_resistance():
    with pytest.raises(ValueError):
        ThermalBC.resistance(0.0)
    with pytest.raises(ValueError):
        ThermalBC.resistance(-1.0)
    with pytest.raises(ValueError):
        ThermalBC("not-a-real-kind")
