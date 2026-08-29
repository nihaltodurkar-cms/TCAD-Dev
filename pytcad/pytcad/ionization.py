"""Impact-ionization coefficients -- van Overstraeten-de Man (M15).

Single source of truth for the silicon alpha(E)=A exp(-B/E) piecewise
parameterization, values as tabulated in the Sentaurus/Taurus device
manuals and cross-checked directly against van Overstraeten & de Man,
Solid-State Electron. 13, 583 (1970).  This lives in the numerical CORE
so the Device1D Newton assembly can couple it without violating
layering; the M8 analysis module (workbench/physics/impact_ionization.py)
imports these symbols instead of carrying its own copy.

Pure functions, vectorized, no cross-module dependencies.

BUG FIXED 2026-08-28 (M15 G-C investigation): the low/high-field switch
point is NOT the same for both carriers in the original paper.
Electrons use a SINGLE fit (A, B identical either side) valid over
[1.75e5, 6.0e5] V/cm, so where exactly a switch is applied never
mattered for them.  Holes have a GENUINE two-branch fit with the switch
at 4.0e5 V/cm (low: [1.75e5, 4.0e5], high: [4.0e5, 6.0e5]).  This
module previously used one shared E_SWITCH = 5e5 V/cm for both carriers
-- borrowed from Sentaurus/Taurus documentation conventions without
re-deriving it from the paper -- which silently misclassified holes in
the [4e5, 5e5) V/cm window into the LOW-field branch when the measured
data calls for HIGH.  Both the core solver (alpha_p, dalpha_dE) and the
M8 analysis layer (ionization_integral, breakdown_voltage_one_sided)
import from here, so both were affected identically -- see
M15-IONIZATION-PLAN.md for the measured before/after impact on the
G-C/G-D gates.
"""
import numpy as np

E_SWITCH_N = 5e5                    # V/cm -- electrons: no real split (A, B
                                     # identical either side), kept as the
                                     # historical constant name below.
E_SWITCH_P = 4.0e5                  # V/cm -- holes: the ACTUAL published
                                     # switch point (van Overstraeten & de
                                     # Man 1970, Table); previously wrongly
                                     # shared the electron value of 5e5.
E_SWITCH = E_SWITCH_N                # kept for backward compatibility with
                                     # callers that only ever probed the
                                     # electron kink; new code should use
                                     # E_SWITCH_N / E_SWITCH_P explicitly.
# Published coefficient tables [A in cm^-1, B in V/cm].
# van Overstraeten & de Man, Solid-State Electron. 13, 583 (1970).
ALPHA_N_LOW = {"A": 7.03e5, "B": 1.231e6}
ALPHA_N_HIGH = {"A": 7.03e5, "B": 1.231e6}
ALPHA_P_LOW = {"A": 1.582e6, "B": 2.036e6}
ALPHA_P_HIGH = {"A": 6.71e5, "B": 1.693e6}

Q_E = 1.602176634e-19               # C


def _alpha(E, low, high, switch):
    """Piecewise alpha(E) = A exp(-B/E); vectorized, E in V/cm."""
    E = np.asarray(E, dtype=float)
    out = np.where(E < switch,
                   low["A"] * np.exp(-low["B"] / np.maximum(E, 1e-9)),
                   high["A"] * np.exp(-high["B"] / np.maximum(E, 1e-9)))
    return float(out) if out.ndim == 0 else out


def alpha_n(E):
    """Electron ionization coefficient [cm^-1]."""
    return _alpha(E, ALPHA_N_LOW, ALPHA_N_HIGH, E_SWITCH_N)


def alpha_p(E):
    """Hole ionization coefficient [cm^-1]."""
    return _alpha(E, ALPHA_P_LOW, ALPHA_P_HIGH, E_SWITCH_P)


def dalpha_dE(E, carrier):
    """d(alpha)/dE [cm^-2]: alpha * B / E^2 on the active branch.

    The piecewise switch (E_SWITCH_N for electrons, E_SWITCH_P for
    holes) is a kink; callers probing the Jacobian numerically must
    stay away from +-2% of the RELEVANT carrier's switch point (the
    M15 G-B gate enforces this on its probe states)."""
    E = np.asarray(E, dtype=float)
    if carrier == "n":
        tbl_l, tbl_h, switch = ALPHA_N_LOW, ALPHA_N_HIGH, E_SWITCH_N
    else:
        tbl_l, tbl_h, switch = ALPHA_P_LOW, ALPHA_P_HIGH, E_SWITCH_P
    a = _alpha(E, tbl_l, tbl_h, switch)
    B = np.where(E < switch, tbl_l["B"], tbl_h["B"])
    out = a * B / np.maximum(E, 1e-9) ** 2
    return float(out) if out.ndim == 0 else out
