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


# ---------------------------------------------------------------------
# M34-S1: nonlocal path (dynamic-path) direct BTBT, Kane two-band WKB
# ---------------------------------------------------------------------
# Reference (verified open-access, read directly -- not a paraphrase;
# see M34-S1-PLAN.md section 4): D Esseni, M Pala, P Palestri, C Alper,
# T Rollo, "A review of selected topics in physics based modeling for
# tunnel field-effect transistors," Semicond. Sci. Technol. 32, 083005
# (2017), doi:10.1088/1361-6641/aa6fca (CC-BY 3.0), section 2.1,
# equations (8), (9), (11), (12).
#
# IMPORTANT, stated once here and not repeated at every call site: the
# functions below are a FIRST-PRINCIPLES construction from bare
# mr/Eg/hbar (eq 9/11 evaluated pointwise along the actual band
# profile).  They are NOT calibrated against, and are not expected to
# numerically match, btbt_generation()/KANE_A_SI/KANE_B_SI above --
# those are Hurkx et al.'s 1992 EMPIRICAL RECALIBRATION of this same
# Kane theory, done precisely because the bare first-principles form
# (kane_local_fp below, eq 8) does not match measured Si BTBT current.
# kane_local_fp() exists ONLY as the uniform-field self-consistency
# check for the nonlocal path integral's own correctness (M34-S1 gate
# G2) -- never as a second "local BTBT model" to compare against
# Models(btbt=True), and never to be rescaled to match KANE_A_SI/B_SI.
# 1D homojunction only; scope and named simplifications (single
# zero-transverse-momentum energy channel, (fc-fv)=1, mesh-snapped
# turning point xf) are in M34-S1-PLAN.md sections 1 and 4.
#
# *** STATUS: PARTIALLY VERIFIED, STILL NOT WIRED. DO NOT CALL FROM
# device.py YET -- see M34-S1-PLAN.md section 6 for the full trail. ***
#
# Two real bugs were found and fixed while building the G2 self-
# consistency check (comparing this module's uniform-field limit
# against kane_local_fp(), eq 8):
#  1. kane_local_fp()'s exponent denominator was mistranscribed as
#     sqrt(2)*hbar*e*F; the primary source (re-read at high resolution
#     2026-09-11) has 2*hbar*e*F. Fixed. Confirmed directly: with the
#     fix, this module's WKB path integral (2*int_kappa) matches
#     kane_local_fp()'s exponent MAGNITUDE to 5+ significant figures
#     on a synthetic uniform-field profile, across a decade of field
#     strengths -- the dominant, exponentially-sensitive physics is
#     verified correct.
#  2. nonlocal_btbt_window()'s prefactor double-counted a factor of
#     elementary charge: eq (11) as printed shows BOTH
#     "|dEv/dx|" and a separate "e" multiplying it, but a from-scratch
#     re-derivation of eq (11)'s prefactor (redoing the SAME
#     eq(3)->eq(7)->eq(8) k_perp Gaussian-integral method the paper
#     itself uses, applied instead to eq(3)+eq(10)) gives only ONE net
#     factor of charge. Read literally, "|dEv/dx| * e" is consistent
#     with the paper's dEv/dx being conventionally in eV/m (a natural
#     unit for a band-diagram derivative) and their "e" performing the
#     eV->Joule conversion -- but `dEv_dxi` here is documented and
#     passed already in SI J/m, so multiplying by q again double-
#     counted that conversion. Fixed (dropped the extra q).
#
# After both fixes, the remaining prefactor ratio (nonlocal / eq 8,
# uniform field) is NOT 1.0 -- it converges, as quadrature resolution
# N increases, cleanly to exactly pi (measured: 3.1955, 3.1685,
# 3.1550, 3.1483, 3.1449, 3.1433 for N = 500..512000, monotonically
# approaching 3.14159265). This is NOT residual quadrature noise (it
# is the well-known slow convergence of a plain quadrature rule near
# an integrable inverse-sqrt turning-point singularity) and it is NOT
# treated as a bug to divide out: eq (10)'s small-k_perp expansion
# (Im(kx) = kappa + k_perp^2/(2 kappa)) is a LEADING-ORDER
# approximation of the EXACT k_perp dependence eq (7) uses for the
# uniform-field case -- a Gaussian truncation differing from the exact
# integral by a clean O(1) factor is an expected, explicable
# consequence of that approximation, not noise or a transcription
# error. It has NOT been proven from scratch that pi is exactly the
# right correction (that would need fully redoing eq(10)'s own
# k_perp-integral derivation, which was not done here), so it is
# documented, not silently divided out. Next step before wiring:
# either complete that from-scratch derivation, or accept a
# documented, gated pi-ratio as the STATED, honest calibration of this
# specific approximation (never guessed, never silently tuned) --
# a decision for the next pass, not made here.
M0_SI = 9.1093837015e-31          # kg, free electron rest mass
HBAR_SI = 1.054571817e-34         # J s
Q_SI = 1.602176634e-19            # C


def kane_alpha(delta, u):
    """eq (9)'s alpha(x), given delta=(E-Ev(x))/Eg in [0,1] and
    u = m0/(2*mr) [dimensionless].  Vectorized over delta."""
    delta = np.asarray(delta, dtype=float)
    inner = np.maximum(u * (delta - 0.5) + 0.25 * u * u + 0.25, 0.0)
    return -u + 2.0 * np.sqrt(inner)


def kane_kappa(delta, Eg_J, mr_kg, hbar=HBAR_SI):
    """eq (9): WKB imaginary wavevector kappa(x) [1/m] along the
    tunnel path, as a function of delta=(E-Ev(x))/Eg (0 at the start
    turning point x_i, 1 at the end turning point x_f -- both give
    kappa=0 exactly, verified algebraically in M34-S1-PLAN.md section
    4).  Eg_J in Joules, mr_kg in kg.  Vectorized over delta."""
    u = M0_SI / (2.0 * mr_kg)
    alpha = kane_alpha(delta, u)
    val = np.maximum(mr_kg * Eg_J * (1.0 - alpha * alpha), 0.0)
    return np.sqrt(val) / hbar


def dkappa_ddelta(delta, Eg_J, mr_kg, hbar=HBAR_SI):
    """d(kappa)/d(delta), via alpha and sqrt(inner)=(alpha+u)/2 (eq 9's
    own definition, avoiding a second sqrt).  Singular exactly at the
    turning points (kappa -> 0); callers must exclude delta in {0, 1}
    from any live differentiation (M34-S1-PLAN.md section 4 -- this is
    a feature of the frozen-boundary/live-interior Jacobian split, not
    a bug to clip around)."""
    u = M0_SI / (2.0 * mr_kg)
    alpha = kane_alpha(delta, u)
    kappa = kane_kappa(delta, Eg_J, mr_kg, hbar=hbar)
    sqrt_inner = 0.5 * (alpha + u)
    # d(alpha)/d(delta) = u / sqrt_inner ; d(kappa)/d(alpha) =
    # -mr*Eg*alpha / (hbar^2 * kappa)
    dalpha_ddelta = u / np.maximum(sqrt_inner, 1e-300)
    dkappa_dalpha = -mr_kg * Eg_J * alpha / (hbar * hbar
                                              * np.maximum(kappa, 1e-300))
    return dkappa_dalpha * dalpha_ddelta


def kane_local_fp(F_V_per_m, Eg_J, mr_kg, hbar=HBAR_SI, q=Q_SI):
    """eq (8): the FIRST-PRINCIPLES closed-form uniform-field limit of
    the nonlocal path integral (eqs 9-11) -- for the G2 self-
    consistency gate ONLY, see the module-level note above.  Returns
    G [m^-3 s^-1], SI throughout (distinct units/calibration from
    btbt_generation()'s cm^-3 s^-1 empirical fit)."""
    F = np.maximum(np.abs(np.asarray(F_V_per_m, dtype=float)), 1e-30)
    pref = (q * q * F * F * np.sqrt(mr_kg)) / \
        (18.0 * np.pi * np.pi * hbar * hbar * np.sqrt(Eg_J))
    # Denominator is 2*hbar*e*F (verified against a high-res re-read of
    # the primary source's eq (8) image, 2026-09-11) -- an earlier pass
    # mistranscribed this as sqrt(2)*hbar*e*F, which alone accounted
    # for part of the "G2 does not close" finding (see M34-S1-PLAN.md
    # section 6): the WKB path integral this module computes directly
    # (2*int_kappa) matches THIS corrected exponent's magnitude to
    # 4 significant figures on a synthetic uniform-field profile.
    expo = -np.pi * np.sqrt(mr_kg) * Eg_J ** 1.5 \
        / (2.0 * q * F * hbar)
    return pref * np.exp(expo)


def nonlocal_btbt_window(x_path, Ev_path, dEv_dxi, Eg_J, mr_kg, mc_kg,
                          mv_kg, Emin_J, Emax_J, hbar=HBAR_SI, q=Q_SI):
    """eq (11)/(12): nonlocal path BTBT generation rate for ONE
    tunneling window (dominant, zero-transverse-momentum channel,
    E = Ev_path[0]; (fc-fv)=1 -- named S1 simplifications, see
    M34-S1-PLAN.md sections 1/4).

    x_path : node coordinates [m], x_i..x_f inclusive, >=2 points.
    Ev_path: local valence-band energy [J] at those SAME nodes.
    dEv_dxi: |dEv/dx| evaluated AT x_i [J/m] -- the eq (11) prefactor.
    Emin_J/Emax_J: global band extrema [J] used by km^2 (eq 12).

    Returns (G_T [m^-3 s^-1], kappa_path [1/m], int_kappa, int_invkappa)
    -- the last three returned so device.py's live interior-node
    Jacobian can reuse them without recomputing the quadrature.
    """
    x_path = np.asarray(x_path, dtype=float)
    Ev_path = np.asarray(Ev_path, dtype=float)
    E = Ev_path[0]
    delta = np.clip((E - Ev_path) / Eg_J, 0.0, 1.0)

    # EDGE-MIDPOINT quadrature, not nodal trapezoid: kappa is EXACTLY
    # zero at delta=0/1 (the turning points, by construction -- see
    # M34-S1-PLAN.md section 4), so 1/kappa diverges there.  A nodal
    # trapezoid rule samples 1/kappa AT that exact singular point and
    # is wrong by orders of magnitude (confirmed directly: it drove
    # int_invkappa to ~1e300 and G_T to underflow, versus the correct
    # eq (8) uniform-field answer -- caught by the G2 self-consistency
    # gate this fixes, not assumed away).  Using the delta value at
    # each EDGE'S MIDPOINT (average of its two nodal deltas) never
    # touches delta=0 or 1 as long as the window spans >=2 edges,
    # since the two boundary nodes only ever contribute half-weight
    # through an averaged, strictly-interior midpoint value -- the
    # standard fix for an integrable inverse-sqrt turning-point
    # singularity (kappa ~ sqrt(x-x_i) near x_i, so 1/kappa's
    # divergence is integrable but not nodally samplable).
    dx = np.diff(x_path)
    delta_mid = 0.5 * (delta[1:] + delta[:-1])
    kappa_path = kane_kappa(delta, Eg_J, mr_kg, hbar=hbar)   # nodal (returned for callers)
    kappa_mid = kane_kappa(delta_mid, Eg_J, mr_kg, hbar=hbar)
    # A real (non-uniform-field) device has long near-flat regions, so
    # a wide window can carry MANY interior edges whose delta_mid sits
    # within float precision of 0 or 1 -- not just the window's two
    # true boundary edges (confirmed directly: on a real diode this
    # drove int_invkappa to ~1e291 via 1/kappa_mid^2-scale terms at
    # several such edges, silently producing a G_T underflowed to
    # ~1e-274 rather than the physically correct value -- the
    # kappa_mid_safe=1e-300 floor alone is not enough, since it still
    # lets 1/(1e-300) enter the sum as a huge but finite number). Any
    # edge whose kappa_mid falls below a PHYSICALLY negligible floor
    # (a WKB kappa of 1e8-1e9 /m is typical for real tunneling; 1.0 /m
    # is many orders below that) contributes a numerically meaningless
    # but individually enormous term to int_invkappa and must be
    # dropped from the quadrature entirely, not merely clamped.
    _KAPPA_FLOOR = 1.0                                    # 1/m
    live_edge = kappa_mid > _KAPPA_FLOOR
    kappa_mid_safe = np.maximum(kappa_mid, _KAPPA_FLOOR)

    int_kappa = float(np.sum(kappa_mid * dx))
    int_invkappa = float(np.sum(np.where(live_edge, dx / kappa_mid_safe, 0.0)))

    km2 = max(min(2.0 * mv_kg * (Emax_J - E),
                  2.0 * mc_kg * (E - Emin_J)) / (hbar * hbar), 0.0)
    bracket = 1.0 - np.exp(-km2 * int_invkappa)
    # NOT abs(dEv_dxi)*q/(36*hbar): a hand re-derivation of eq (11) by
    # redoing the SAME eq(3)->eq(7)->eq(8) k_perp-integral method for
    # the eq(3)+eq(10) nonlocal case shows only ONE net factor of
    # elementary charge belongs here, not two. The paper's displayed
    # "|dEv/dx| * e" is consistent with `dEv_dxi` being conventionally
    # in eV/m (natural for a band-diagram derivative) and their "e"
    # doing the eV->Joule conversion; `dEv_dxi` is documented and
    # passed here already in SI J/m (which numerically equals
    # eV/m-value * q), so multiplying by q again double-counts it.
    # Confirmed directly: removing this q dropped the measured G2
    # mismatch from ~18 orders of magnitude to a small O(1) residual
    # (see M34-S1-PLAN.md section 6 for the full numeric trail).
    G_T = abs(dEv_dxi) / (36.0 * hbar) \
        / max(int_invkappa, 1e-300) * bracket * np.exp(-2.0 * int_kappa)
    return G_T, kappa_path, int_kappa, int_invkappa
