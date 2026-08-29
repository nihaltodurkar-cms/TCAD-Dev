"""Tunneling physics (M12-S1): analysis-layer diagnostics for gate
dielectric leakage.

Fowler-Nordheim (high-field, triangular barrier) and WKB direct
tunneling through a thin rectangular barrier.  Pure functions -- these
are DIAGNOSTICS computed at the solved oxide field, not self-consistent
boundary conditions (stated in TUNNELING-PLAN.md section 3).

All functions SI (E in V/m, lengths in m, J in A/m^2) unless suffixed.
"""
import math

# Universal Fowler-Nordheim constants (SI):
#   A_FN = q^3 / (16 pi^2 hbar phi)  -> prefactor 1.541e-6 A eV V^-2
#   B_FN = 4 sqrt(2 m_e) / (3 e hbar) -> 6.831e9 eV^-3/2 V m^-1
M_E = 9.1093837015e-31           # kg
HBAR = 1.054571817e-34           # J s
Q_E = 1.602176634e-19            # C

A_FN = 1.541e-6                  # A eV V^-2
B_FN = 6.831e9                   # eV^-3/2 V m^-1


def b_fn_constant():
    """B_FN recomputed from its physical definition
    B = 4 sqrt(2 m_e q) / (3 hbar).
    The 4/3 is the triangular-barrier WKB integral (int kappa dx =
    (2/3) kappa_max d); phi enters in eV hence the q under the root."""
    return 4.0 * math.sqrt(2.0 * M_E * Q_E) / (3.0 * HBAR)


def fowler_nordheim_current(E, phi):
    """FN current density [A/m^2] at field E [V/m] through a barrier of
    height phi [eV].  Valid in the FN regime E >~ 1 GV/m."""
    E = abs(float(E))
    if E <= 0.0 or phi <= 0.0:
        return 0.0
    return (A_FN * E * E / phi) * math.exp(-B_FN * phi ** 1.5 / E)


def fn_plot_slope(phi):
    """Slope of ln(J/E^2) vs (1/E): the defining FN signature,
    -B phi^{3/2}.  Returned so tests can recover it by regression."""
    return -B_FN * float(phi) ** 1.5


def wkb_kappa(phi_eV, m_star_rel=1.0, E_eV=0.0):
    """Inverse decay length [1/m]: kappa = sqrt(2 m* (phi-E)) / hbar."""
    dphi = max(phi_eV - E_eV, 0.0)
    return math.sqrt(2.0 * m_star_rel * M_E * Q_E * dphi) / HBAR


def wkb_direct_transmission(tox_m, phi_eV, m_star_rel=1.0, E_eV=0.0):
    """WKB transmission probability through a rectangular barrier of
    width tox_m and height phi_eV above the tunneling carrier energy."""
    kappa = wkb_kappa(phi_eV, m_star_rel, E_eV)
    return math.exp(-2.0 * kappa * float(tox_m))
