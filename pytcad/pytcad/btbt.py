"""Band-to-band tunneling coefficients -- local Kane/Hurkx model (M16).

Single source of truth for the silicon local-field BTBT generation rate

    G(F) = A * F^2 * exp(-B / F)            [cm^-3 s^-1]

with F = |E| the local electric field [V/cm].  This is the "Kane form"
as used by Hurkx et al. (IEEE Trans. Electron Devices 39, 331 (1992),
Table I, silicon direct BTBT) and reproduced as the default local BTBT
parameterization in commercial TCAD manuals (Sentaurus "BBT.DIRECT"
F^2-form silicon defaults; Silvaco's equivalent).

Constants provenance (M16, 2026-08-29): A and B are the published
silicon values from Hurkx et al. 1992 as tabulated in the TCAD
manuals.  The house rule is that published constants are never guessed:
the exact pin lives in tests/test_model_benchmarks.py
(test_btbt_coefficients_match_published_table) and in
tests/test_m16_btbt.py (test_g_d_coefficients_match_analysis_layer),
so any change to either number is a deliberate, gated act.

Known model limitation (ARCHITECTURE.md M16 LITERATURE NOTE): plain
local Kane/Hurkx UNDERESTIMATES leakage at large reverse bias relative
to nonlocal (line-integral) BTBT, because it assumes a single local
field stands in for the whole tunneling path.  The local model here is
gated on its known failure mode: the M16 high-bias gate asserts the
GIDL/Zener current does NOT plateau (keeps growing steeply) as reverse
bias increases, rather than only matching at onset.  The nonlocal
variant is deferred to Tier 3.

Pure functions, vectorized, no cross-module dependencies -- mirrors
pytcad/ionization.py (the M15 module this follows).
"""
import numpy as np

# Published silicon coefficient table [A in cm^-3 s^-1, B in V/cm].
# Hurkx, Klaassen & Knuvers, IEEE Trans. Electron Devices 39, 331
# (1992), Table I (silicon, direct BTBT, Kane F^2 form).
KANE_A_SI = 3.5e21                    # cm^-3 s^-1
KANE_B_SI = 1.03e8                    # V/cm


def btbt_generation(F, A=KANE_A_SI, B=KANE_B_SI):
    """Kane-form local BTBT generation rate G(F) [cm^-3 s^-1].

    G = A * F^2 * exp(-B/F), F in V/cm.  Vectorized; F is clamped away
    from zero so the low-field limit is exactly 0 (exp(-inf) -> 0)
    rather than a divide-by-zero.
    """
    F = np.asarray(F, dtype=float)
    Fsafe = np.maximum(F, 1e-30)
    out = A * Fsafe * Fsafe * np.exp(-B / Fsafe)
    out = np.where(F > 0.0, out, 0.0)
    return float(out) if out.ndim == 0 else out


def dbtbt_dF(F, A=KANE_A_SI, B=KANE_B_SI):
    """d(G)/dF [cm^-3 s^-1 per V/cm]: G * (2/F + B/F^2).

    G(F) is smooth (C-infinity) for F > 0 -- unlike ionization's
    piecewise alpha(E) there is no branch switch, so an FD-Jacobian
    probe has no kink windows to avoid.  Only F -> 0 is singular, where
    both G and dG/dF vanish (exponentially); F is clamped the same way
    btbt_generation clamps it.
    """
    F = np.asarray(F, dtype=float)
    Fsafe = np.maximum(F, 1e-30)
    G = A * Fsafe * Fsafe * np.exp(-B / Fsafe)
    out = np.where(F > 0.0, G * (2.0 / Fsafe + B / (Fsafe * Fsafe)), 0.0)
    return float(out) if out.ndim == 0 else out
