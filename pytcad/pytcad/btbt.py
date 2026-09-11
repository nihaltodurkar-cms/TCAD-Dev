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
# Wired into Device1D as Models(btbt_nonlocal=True); current state and
# open items are in M34-S1-PLAN.md section 9.
#
# Three real bugs were found and fixed while building the G2 self-
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
#  3. kane_local_fp()'s PREFACTOR was mistranscribed as
#     18*pi^2*hbar^2; the paper's eq (8) (page 5, re-read 2026-09-11)
#     has 18*pi*hbar^2, which is also what integrating eq (7) over
#     k_perp in eq (3) gives by hand.  This was the whole "factor of
#     pi" an earlier pass attributed to eq (10)'s small-k_perp
#     expansion -- in a uniform field that expansion is exact, and
#     int_0^1 d(delta)/kappa = pi*hbar/(2*sqrt(mr*Eg)) exactly for any
#     u = m0/(2 mr) > 1 (substitute alpha; gated in
#     tests/test_model_benchmarks.py), so eq (11) reduces to eq (8)
#     with ratio 1.  segment_integrals() integrates kappa exactly along a
#     piecewise-linear band, so the reduction holds to rounding.
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
    _alpha, c = _kane_alpha_c(delta, _kane_u(mr_kg))
    return np.sqrt(mr_kg * Eg_J) * c / hbar


def dkappa_ddelta(delta, Eg_J, mr_kg, hbar=HBAR_SI):
    """d(kappa)/d(delta), via alpha and sqrt(inner)=(alpha+u)/2 (eq 9's
    own definition, avoiding a second sqrt).  Singular exactly at the
    turning points (kappa -> 0); callers must exclude delta in {0, 1}
    from any live differentiation (M34-S1-PLAN.md section 4 -- this is
    a feature of the frozen-boundary/live-interior Jacobian split, not
    a bug to clip around)."""
    u = _kane_u(mr_kg)
    alpha, c = _kane_alpha_c(delta, u)
    S = 0.5 * (alpha + u)                        # sqrt(inner), eq (9)
    # d(kappa)/d(alpha) = -sqrt(mr Eg) alpha / (hbar c);
    # d(alpha)/d(delta) = u / S
    return -np.sqrt(mr_kg * Eg_J) * alpha * u / (
        hbar * np.maximum(c, 1e-300) * S)


def kane_local_fp(F_V_per_m, Eg_J, mr_kg, hbar=HBAR_SI, q=Q_SI):
    """eq (8): the FIRST-PRINCIPLES closed-form uniform-field limit of
    the nonlocal path integral (eqs 9-11) -- for the G2 self-
    consistency gate ONLY, see the module-level note above.  Returns
    G [m^-3 s^-1], SI throughout (distinct units/calibration from
    btbt_generation()'s cm^-3 s^-1 empirical fit)."""
    F = np.maximum(np.abs(np.asarray(F_V_per_m, dtype=float)), 1e-30)
    # 18*pi, not 18*pi^2 (eq (8) as printed; bug 3 in the module note).
    pref = (q * q * F * F * np.sqrt(mr_kg)) / \
        (18.0 * np.pi * hbar * hbar * np.sqrt(Eg_J))
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


def _kane_alpha_c(delta, u):
    """eq (9)'s alpha and cos(theta) = sqrt(1 - alpha^2), computed
    WITHOUT cancellation at the band edges.  The direct form
    alpha = -u + 2 S (S = sqrt(inner)) loses 1 + alpha to rounding once
    delta < ~1e-8 and returns kappa = 0 exactly below ~1e-16, which made
    1/kappa a divide-by-zero at a positive delta (a 0.25V ramp died on
    it).  With S0 = (u-1)/2 and S1 = (u+1)/2 (S at delta = 0 and 1):
        1 + alpha = 2u delta / (S + S0),   1 - alpha = 2u (1-delta)/(S1 + S)
    delta is clipped to [0, 1] (the gap)."""
    d = np.clip(np.asarray(delta, dtype=float), 0.0, 1.0)
    S = np.sqrt(u * (d - 0.5) + 0.25 * u * u + 0.25)
    one_p = 2.0 * u * d / (S + 0.5 * (u - 1.0))
    one_m = 2.0 * u * (1.0 - d) / (S + 0.5 * (u + 1.0))
    alpha = np.where(d < 0.5, one_p - 1.0, 1.0 - one_m)
    return alpha, np.sqrt(one_p * one_m)


def _kane_u(mr_kg):
    """u = m0/(2 mr) for eq (9).  The turning-point structure the whole
    path model rests on (alpha = -1 at delta = 0, +1 at delta = 1) needs
    u > 1, i.e. mr < m0/2; refuse loudly otherwise rather than integrate
    a kappa that does not vanish at the band edges."""
    u = M0_SI / (2.0 * mr_kg)
    if not u > 1.0:
        raise ValueError(
            "eq (9) needs u = m0/(2 mr) > 1 (mr < m0/2) for kappa to vanish "
            f"at both band edges; got mr = {mr_kg / M0_SI:.4g} m0")
    return u


def _kane_theta(delta, u):
    """theta = asin(alpha(delta)) (via atan2, accurate at the band
    edges), sin(theta) = alpha, cos(theta)."""
    alpha, c = _kane_alpha_c(delta, u)
    return np.arctan2(alpha, c), alpha, c


def kane_invkappa_antideriv(delta, Eg_J, mr_kg, hbar=HBAR_SI):
    """An antiderivative of 1/kappa in delta [m]: d/d(delta) of the result
    is eq (9)'s 1/kappa.  With theta = asin(alpha) and eq (9)'s own
    d(delta) = (alpha + u)/(2u) d(alpha):
        int d(delta)/kappa = hbar/(2u sqrt(mr Eg)) * (u*theta - cos(theta))
    Over the whole gap this is pi*hbar/(2 sqrt(mr Eg)) for any u > 1."""
    u = _kane_u(mr_kg)
    th, _a, c = _kane_theta(delta, u)
    return hbar / (2.0 * u * np.sqrt(mr_kg * Eg_J)) * (u * th - c)


def kane_kappa_antideriv(delta, Eg_J, mr_kg, hbar=HBAR_SI):
    """An antiderivative of kappa in delta [1/m] (eq 9):
        int kappa d(delta) = sqrt(mr Eg)/(2u hbar)
                             * (u*(theta + sin(theta)cos(theta))/2
                                - cos(theta)^3/3)
    Over the whole gap this is pi*sqrt(mr Eg)/(4 hbar): times 2*Eg/(qF)
    it is exactly eq (8)'s exponent."""
    u = _kane_u(mr_kg)
    th, a, c = _kane_theta(delta, u)
    return np.sqrt(mr_kg * Eg_J) / (2.0 * u * hbar) * (
        0.5 * u * (th + a * c) - c * c * c / 3.0)


FLAT_DDELTA = 1e-10     # below this |d delta| an edge is treated as flat


def segment_integrals(da, db, L, Eg_J, mr_kg, hbar=HBAR_SI):
    """EXACT WKB integrals over straight path segments along which delta
    runs linearly from `da` to `db` (psi is piecewise linear on the
    mesh), counting only the part inside the gap, 0 < delta < 1 --
    outside it the carrier sits in an allowed band (kappa = 0) and is
    not under the barrier.

    Replaces the edge-midpoint rule (M34-S1-PLAN.md section 9): that
    rule made int dx/kappa nearly discontinuous whenever a node crossed
    a turning point.  This form is continuous in (da, db), needs no
    kappa floor, and is exact for a uniform field at any resolution.
    Segments with |db - da| < FLAT_DDELTA use L*f(midpoint), which is
    the same limit without the cancellation of a tiny difference.

    Returns (Ik, Iik, dIk_dda, dIk_ddb, dIik_dda, dIik_ddb), arrays over
    segments: Ik = int kappa dx [-], Iik = int dx/kappa [m^2]; L in m.
    """
    da = np.asarray(da, dtype=float)
    db = np.asarray(db, dtype=float)
    L = np.asarray(L, dtype=float)
    D = np.abs(db - da)
    rising = db >= da
    vmin = np.where(rising, da, db)
    vmax = np.where(rising, db, da)
    lo = np.clip(vmin, 0.0, 1.0)
    hi = np.clip(vmax, 0.0, 1.0)
    in_lo = (vmin > 0.0) & (vmin < 1.0)
    in_hi = (vmax > 0.0) & (vmax < 1.0)
    flat = D < FLAT_DDELTA
    Ds = np.where(flat, 1.0, D)

    # Both differences are >= 0 analytically (kappa >= 0); clamp the
    # rounding sign error of a difference of two O(1) antiderivative
    # values when the in-gap range hi - lo is tiny.
    dK = np.maximum(kane_kappa_antideriv(hi, Eg_J, mr_kg, hbar)
                    - kane_kappa_antideriv(lo, Eg_J, mr_kg, hbar), 0.0)
    dG = np.maximum(kane_invkappa_antideriv(hi, Eg_J, mr_kg, hbar)
                    - kane_invkappa_antideriv(lo, Eg_J, mr_kg, hbar), 0.0)
    k_hi = kane_kappa(hi, Eg_J, mr_kg, hbar)
    k_lo = kane_kappa(lo, Eg_J, mr_kg, hbar)
    f_hi_k = np.where(in_hi, k_hi, 0.0)
    f_lo_k = np.where(in_lo, k_lo, 0.0)
    # 1/kappa only at an endpoint strictly inside the gap (kappa > 0).
    f_hi_i = np.where(in_hi, 1.0 / np.where(in_hi, k_hi, 1.0), 0.0)
    f_lo_i = np.where(in_lo, 1.0 / np.where(in_lo, k_lo, 1.0), 0.0)

    Ik = L * dK / Ds
    Iik = L * dG / Ds
    dIk_max = L * (f_hi_k - dK / Ds) / Ds
    dIk_min = L * (-f_lo_k + dK / Ds) / Ds
    dIik_max = L * (f_hi_i - dG / Ds) / Ds
    dIik_min = L * (-f_lo_i + dG / Ds) / Ds

    # flat branch: L * f(mid), derivative split equally between ends
    mid = 0.5 * (da + db)
    inm = (mid > 0.0) & (mid < 1.0)
    # A midpoint within 1e-30 of the start turning point would overflow
    # kappa'/kappa^2 (~ delta^-1.5); such a segment is flat AT the
    # turning point and suppresses its path to G ~ 0 either way.
    mids = np.where(inm, np.maximum(mid, 1e-30), 0.5)
    km = kane_kappa(mids, Eg_J, mr_kg, hbar)
    dkm = dkappa_ddelta(mids, Eg_J, mr_kg, hbar)
    fl_Ik = np.where(inm, L * km, 0.0)
    fl_Iik = np.where(inm, L / km, 0.0)
    fl_dIk = np.where(inm, 0.5 * L * dkm, 0.0)
    fl_dIik = np.where(inm, -0.5 * L * dkm / (km * km), 0.0)

    Ik = np.where(flat, fl_Ik, Ik)
    Iik = np.where(flat, fl_Iik, Iik)
    dIk_da = np.where(flat, fl_dIk, np.where(rising, dIk_min, dIk_max))
    dIk_db = np.where(flat, fl_dIk, np.where(rising, dIk_max, dIk_min))
    dIik_da = np.where(flat, fl_dIik, np.where(rising, dIik_min, dIik_max))
    dIik_db = np.where(flat, fl_dIik, np.where(rising, dIik_max, dIik_min))
    return Ik, Iik, dIk_da, dIk_db, dIik_da, dIik_db


def nonlocal_btbt_window(x_path, Ev_path, dEv_dxi, Eg_J, mr_kg, mc_kg,
                          mv_kg, Emin_J, Emax_J, hbar=HBAR_SI, q=Q_SI):
    """eq (11)/(12): nonlocal path BTBT generation rate for ONE tunneling
    path (dominant zero-transverse-momentum channel, E = Ev_path[0];
    (fc - fv) = 1 -- named S1 simplifications, M34-S1-PLAN.md sections
    1/4).  Ev is taken piecewise LINEAR between the given nodes and the
    WKB integrals are exact per segment (`segment_integrals`).

    x_path : node coordinates [m] along the path, >= 2 points.
    Ev_path: valence-band energy [J] at those nodes.
    dEv_dxi: |dEv/dx| at x_i [J/m] -- the eq (11) prefactor, already SI
             (eq 11's printed "|dEv/dx| e" is the eV/m convention; see
             the module note, bug 2).
    Emin_J/Emax_J: global band extrema [J] used by km^2 (eq 12).
    `q` is unused and kept for signature compatibility.

    Returns (G_T [m^-3 s^-1], kappa_path [1/m], int_kappa, int_invkappa).
    """
    x_path = np.asarray(x_path, dtype=float)
    Ev_path = np.asarray(Ev_path, dtype=float)
    E = Ev_path[0]
    delta = (E - Ev_path) / Eg_J
    Ik, Iik, *_ = segment_integrals(delta[:-1], delta[1:], np.diff(x_path),
                                    Eg_J, mr_kg, hbar)
    int_kappa = float(np.sum(Ik))
    int_invkappa = float(np.sum(Iik))
    kappa_path = kane_kappa(np.clip(delta, 0.0, 1.0), Eg_J, mr_kg, hbar)
    if int_invkappa <= 0.0:
        return 0.0, kappa_path, int_kappa, int_invkappa
    km2 = max(min(2.0 * mv_kg * (Emax_J - E),
                  2.0 * mc_kg * (E - Emin_J)) / (hbar * hbar), 0.0)
    bracket = 1.0 - np.exp(-km2 * int_invkappa)
    G_T = abs(dEv_dxi) / (36.0 * hbar) / int_invkappa * bracket \
        * np.exp(-2.0 * int_kappa)
    return G_T, kappa_path, int_kappa, int_invkappa
