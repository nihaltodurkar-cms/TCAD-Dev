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

# Published coefficient tables [A in cm^-1, B in V/cm].
# van Overstraeten & de Man, Solid-State Electron. 13, 583 (1970),
# low-field / high-field split at E0 = 5e5 V/cm, values as tabulated in
# the Sentaurus/Taurus device manuals.
E_SWITCH = 5e5                      # V/cm
ALPHA_N_LOW = {"A": 7.03e5, "B": 1.231e6}
ALPHA_N_HIGH = {"A": 7.03e5, "B": 1.231e6}
ALPHA_P_LOW = {"A": 1.582e6, "B": 2.036e6}
ALPHA_P_HIGH = {"A": 6.71e5, "B": 1.693e6}


def _alpha(E, low, high):
    """Piecewise alpha(E) = A exp(-B/E); vectorized, E in V/cm."""
    E = np.asarray(E, dtype=float)
    out = np.where(E < E_SWITCH,
                   low["A"] * np.exp(-low["B"] / np.maximum(E, 1e-9)),
                   high["A"] * np.exp(-high["B"] / np.maximum(E, 1e-9)))
    return float(out) if out.ndim == 0 else out


def alpha_n(E):
    """Electron ionization coefficient [cm^-1]."""
    return _alpha(E, ALPHA_N_LOW, ALPHA_N_HIGH)


def alpha_p(E):
    """Hole ionization coefficient [cm^-1]."""
    return _alpha(E, ALPHA_P_LOW, ALPHA_P_HIGH)


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
