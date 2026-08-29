"""Validation suite.

Every test here compares PyTCAD against something independent: an analytic
limit, a textbook formula, or a finite-difference check.  A numerical device
simulator that has not been validated against the cases where the answer is
known is not a tool, it is a random number generator with units.

    python -m pytest tests/ -q      (or just: python tests/test_validation.py)
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np

from pytcad import (Device1D, Models, NewtonOptions, MOSCapacitor, SILICON,
                    bernoulli, dbernoulli, process)
from pytcad.mesh import graded_mesh
from pytcad.materials import mobility_caughey_thomas
from pytcad.constants import Q

warnings.simplefilter("ignore")


def _diode(Na=1e17, Nd=1e17, L=2e-4, xj=1e-4, **kw):
    x = graded_mesh(L, [xj], 1e-8, 1e-6, 1.12)
    dop = np.where(x < xj, -Na, Nd)
    return Device1D(x, dop, models=Models(bgn=False, **kw))


# ----------------------------------------------------------------------
def test_bernoulli():
    """B(x) identity: exp(x) B(x) = B(-x), and B(0) = 1."""
    x = np.array([-50, -1, -1e-6, 0.0, 1e-6, 1.0, 50.0])
    assert abs(bernoulli(0.0) - 1.0) < 1e-14
    xs = np.array([-5.0, -0.3, 0.3, 5.0])
    assert np.allclose(np.exp(xs) * bernoulli(xs), bernoulli(-xs), rtol=1e-12)
    # derivative against central differences
    xs = np.array([-8.0, -1.0, -1e-3, 1e-3, 1.0, 8.0])
    h = 1e-6
    fd = (bernoulli(xs + h) - bernoulli(xs - h)) / (2 * h)
    assert np.allclose(dbernoulli(xs), fd, rtol=1e-5, atol=1e-9)


def test_jacobian_matches_finite_differences():
    """The analytic Newton Jacobian must match a numerical one."""
    dev = _diode()
    dev.solve_equilibrium()
    bc = dev._contact_values([0.3, 0.0])
    rng = np.random.default_rng(0)
    psi = dev.psi + 0.02 * rng.standard_normal(dev.N)
    n = dev.n * (1 + 0.01 * rng.standard_normal(dev.N))
    p = dev.p * (1 + 0.01 * rng.standard_normal(dev.N))
    F, J, _, _ = dev._residual_jacobian(psi, n, p, bc)
    Jd = J.toarray()
    u = np.stack([psi, n, p], axis=1).ravel()
    worst = 0.0
    for c in rng.choice(3 * dev.N, 25, replace=False):
        step = 1e-7 * max(abs(u[c]), 1.0)
        u2 = u.copy(); u2[c] += step
        F2, _, _, _ = dev._residual_jacobian(u2[0::3], u2[1::3], u2[2::3], bc)
        an = Jd[:, c]
        worst = max(worst, np.abs((F2 - F) / step - an).max()
                    / (np.abs(an).max() + 1e-30))
    assert worst < 1e-4, f"Jacobian error {worst:.2e}"


def test_built_in_potential():
    """V_bi = V_T ln(N_A N_D / n_i^2) for an abrupt junction."""
    dev = _diode()
    dev.solve_equilibrium()
    Vbi = (dev.psi[-1] - dev.psi[0]) * dev.VT
    Vbi_ana = dev.VT * np.log(1e17 * 1e17 / dev.ni**2)
    assert abs(Vbi - Vbi_ana) < 2e-3, (Vbi, Vbi_ana)


def test_bulk_charge_neutrality():
    """Deep in the neutral bulk, n - p - N must vanish."""
    dev = _diode()
    dev.solve_equilibrium()
    rho = dev.n_cm3 - dev.p_cm3 - dev.doping
    far = (dev.x < 0.3e-4) | (dev.x > 1.7e-4)
    assert np.abs(rho[far]).max() / 1e17 < 1e-6


def test_current_continuity():
    """Jn + Jp must be constant along a 1D device in steady state."""
    dev = _diode()
    dev.solve_equilibrium()
    dev.solve_bias([0.6, 0.0])
    J, spread = dev.current_density()
    assert spread < 1e-6, spread


def test_ideal_diode_law():
    """Short-base saturation current and ideality factor."""
    dev = _diode()
    V = np.arange(0.0, 0.61, 0.05)
    J = dev.iv_sweep(V, verbose=False)

    Vbi = dev.VT * np.log(1e34 / dev.ni**2)
    W = np.sqrt(2 * dev.eps * Vbi / Q * (1 / 1e17 + 1 / 1e17))
    Wp = Wn = 1e-4 - W / 2
    Dn = mobility_caughey_thomas(1e17, SILICON, 300.0, "n") * dev.VT
    Dp = mobility_caughey_thomas(1e17, SILICON, 300.0, "p") * dev.VT
    J0 = Q * dev.ni**2 * (Dp / (Wn * 1e17) + Dn / (Wp * 1e17))

    k = np.argmin(np.abs(V - 0.5))
    ratio = J[k] / (J0 * np.exp(V[k] / dev.VT))
    assert 0.85 < ratio < 1.15, f"J/J_ideal = {ratio:.3f}"

    # Restrict to V > 0.3 V: below that, depletion-region SRH recombination
    # (the n = 2 component) still contributes and the ideality is not 1.
    k0 = np.argmin(np.abs(V - 0.3))
    ideality = np.diff(V[k0:]) / (dev.VT * np.diff(np.log(J[k0:])))
    assert np.all(np.abs(ideality - 1.0) < 0.02), ideality


def test_reverse_saturation():
    """Reverse leakage is generation-limited: sub-linear in V, never ohmic.

    It does NOT go flat.  The depletion-region generation current grows
    because the width over which BOTH carriers fall below n_i (and hence
    R -> -n_i/(tau_n+tau_p)) widens with bias.  A 16x voltage increase
    should raise the current by well under 16x but by more than sqrt(16).
    """
    dev = _diode()
    V = np.array([-0.5, -2.0, -8.0])
    J = dev.iv_sweep(V, verbose=False)
    assert np.all(J < 0)
    exponent = np.polyfit(np.log(0.83 - V), np.log(-J), 1)[0]
    assert 0.5 < exponent < 1.5, exponent


def test_mesh_independence():
    """Halving the cell size must not move the current by more than a few %."""
    Jc = _diode().iv_sweep([0.5], verbose=False)[0]
    x = graded_mesh(2e-4, [1e-4], 5e-9, 5e-7, 1.10)
    dop = np.where(x < 1e-4, -1e17, 1e17)
    Jf = Device1D(x, dop, models=Models(bgn=False)).iv_sweep(
        [0.5], verbose=False)[0]
    assert abs(Jf - Jc) / Jf < 0.03, (Jc, Jf)


def test_moscap_limits():
    """C_max -> C_ox; C_min close to the depletion-approximation value."""
    mos = MOSCapacitor(-1e17, 5e-7, gate="n+poly")
    lm = mos.analytic_landmarks()
    Vg = np.linspace(-2.5, 2.5, 251)
    _, _, C = mos.cv_sweep(Vg)
    assert C.max() / lm["C_ox"] > 0.93
    assert 0.8 < C.min() / lm["C_min"] < 1.35
    # C_min occurs near threshold
    assert abs(Vg[np.argmin(C)] - lm["V_th"]) < 0.30


def test_moscap_flatband_shift():
    """Positive fixed oxide charge shifts the C-V curve negative by Qf/Cox."""
    m0 = MOSCapacitor(-1e17, 5e-7, gate="n+poly", Qf=0.0)
    m1 = MOSCapacitor(-1e17, 5e-7, gate="n+poly", Qf=1e12)
    shift = m1.Vfb - m0.Vfb
    assert abs(shift + Q * 1e12 / m0.Cox) < 1e-9


def test_diffusion_against_analytic():
    """Numerical diffusion of a narrow Gaussian -> analytic drive-in."""
    x = np.linspace(0, 4e-4, 4001)
    T, t = 1000.0, 3600.0
    D = process.diffusivity("B", T)
    s0 = 1e-6                      # initial width, cm
    dose = 1e14
    C0 = dose / (np.sqrt(np.pi) * s0) * np.exp(-(x / s0) ** 2) * 2
    C = process.diffuse_numeric(x, C0, "B", T, t, reflecting=True)
    s = np.sqrt(s0**2 + 4 * D * t)
    ana = 2 * dose / (np.sqrt(np.pi) * s) * np.exp(-(x / s) ** 2)
    m = ana > ana.max() * 1e-3
    assert np.abs(C[m] / ana[m] - 1).max() < 0.05


def test_diffusion_conserves_dose():
    x = np.linspace(0, 3e-4, 3001)
    C0 = process.implant(x, "P", 50, 1e14)
    C1 = process.diffuse_numeric(x, C0, "P", 1000.0, 1800.0)
    assert abs(np.trapezoid(C1, x) / np.trapezoid(C0, x) - 1) < 1e-3


def test_deal_grove_regimes():
    """Thin oxides grow linearly in time, thick oxides as sqrt(t)."""
    t_thin = np.array([0.02, 0.04])
    x_thin = process.oxide_thickness(900.0, t_thin, "wet")
    assert abs(x_thin[1] / x_thin[0] - 2.0) < 0.25       # linear regime
    t_thick = np.array([4.0, 16.0])
    x_thick = process.oxide_thickness(1100.0, t_thick, "wet")
    assert abs(x_thick[1] / x_thick[0] - 2.0) < 0.20     # parabolic regime


def test_implant_dose_conservation():
    x = np.linspace(0, 5e-4, 5001)
    C = process.implant(x, "As", 100, 5e14)
    # The Gaussian is truncated at the surface, so a small fraction of the
    # dose (~erfc(Rp/dRp/sqrt2)/2) falls outside the wafer; a real implanter
    # deposits it near x = 0 instead.
    assert abs(np.trapezoid(C, x) / 5e14 - 1) < 2e-3


def test_temperature_scaling_of_leakage():
    """Reverse leakage must rise steeply with temperature (~ n_i^2 or n_i)."""
    J = []
    for T in (300.0, 350.0):
        x = graded_mesh(2e-4, [1e-4], 1e-8, 1e-6, 1.12)
        dop = np.where(x < 1e-4, -1e17, 1e17)
        d = Device1D(x, dop, T=T, models=Models(bgn=False))
        J.append(abs(d.iv_sweep([-1.0], verbose=False)[0]))
    assert J[1] / J[0] > 10.0, J


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fails = 0
    for f in fns:
        try:
            f()
            print(f"  PASS  {f.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  FAIL  {f.__name__}: {e}")
    print(f"\n{len(fns)-fails}/{len(fns)} passed")
    sys.exit(1 if fails else 0)
