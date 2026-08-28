"""Impact ionization -- the M8 first NEW physics model.

Van Overstraeten-de Man effective ionization coefficients for silicon
(piecewise exponential fits, the parameterization shipped by every major
TCAD tool), plus the avalanche breakdown condition for a one-sided
abrupt junction: the ionization integral

    I(W) = int_0^W  alpha_n(E(x)) exp( -int_0^x (alpha_n - alpha_p) dx' ) dx = 1

evaluated on the triangular field E(x) = q N (W - x) / eps of the
depletion region, with W(V) from the depletion approximation.

STATUS (honest): analysis-layer module only.  It is NOT yet coupled to
the drift-diffusion Newton solvers and is NOT registered as a selectable
ModelCatalog flag -- catalog registration happens together with solver
coupling, because every catalog key must be executable by the runner.
"""
import math

import numpy as np

# M15: the coefficient tables and alpha(E) live in the numerical CORE
# (pytcad/ionization.py -- single source of truth; this module re-
# exports them so existing callers/tests are untouched).  alpha_n/
# alpha_p are re-exported directly (not re-wrapped around the private
# _alpha helper) so this module can never drift out of sync with the
# core's per-carrier switch points again -- a local wrapper here
# calling the old single-switch _alpha(E, low, high) signature is
# exactly what broke silently when the core switched to per-carrier
# E_SWITCH_N/E_SWITCH_P (2026-08-28 bug fix, see pytcad/ionization.py).
from pytcad.ionization import (  # noqa: F401
    ALPHA_N_HIGH, ALPHA_N_LOW, ALPHA_P_HIGH, ALPHA_P_LOW,
    E_SWITCH, E_SWITCH_N, E_SWITCH_P,
    alpha_n, alpha_p,
)


def ionization_integral(V, N_doping, n_points=2000):
    """The avalanche criterion I(W(V)) for a one-sided abrupt junction
    doped N_doping [cm^-3] at bias V [V].  Returns I; breakdown is
    I >= 1."""
    EPS_SI = 11.7 * 8.854e-14        # F/cm
    Q = 1.602176634e-19              # C
    ni = 1.0e10                      # cm^-3, only shifts Vbi by ~mV here
    vbi = 0.02585 * math.log(N_doping * N_doping / (ni * ni))

    W = math.sqrt(2.0 * EPS_SI * max(vbi + V, 1e-9) / (Q * N_doping))
    x = np.linspace(0.0, W, n_points)
    E_field = Q * N_doping * (W - x) / EPS_SI          # triangular, max at x=0

    an = np.asarray(alpha_n(E_field), dtype=float)
    ap = np.asarray(alpha_p(E_field), dtype=float)
    # cumulative trapz of (alpha_n - alpha_p) from 0 to each x
    integrand = an - ap
    cum = np.concatenate(([0.0], np.cumsum(
        0.5 * (integrand[1:] + integrand[:-1]) * np.diff(x))))
    exp_term = np.exp(-cum)
    I = float(np.trapezoid(an * exp_term, x))
    return I


def breakdown_voltage_one_sided(N_doping):
    """Bias [V] at which the ionization integral reaches 1, by bisection.
    The criterion is monotone in V (wider, higher-field depletion), so
    bisection is exact within tolerance."""
    lo, hi = 0.05, 5000.0
    while ionization_integral(hi, N_doping) < 1.0:
        hi *= 2.0
        if hi > 1e6:
            raise ValueError("no breakdown found below 1e6 V")
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if ionization_integral(mid, N_doping) >= 1.0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
