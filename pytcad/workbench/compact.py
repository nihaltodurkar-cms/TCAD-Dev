"""M38 -- TCAD-to-SPICE compact model extraction.

The INVERSE of M27.  `pytcad/circuit.py` embeds a real `Device1D` in an
MNA circuit (the forward direction); this module fits an ANALYTIC
compact model to a simulated I-V, emits a SPICE `.MODEL` card, and can
read it back -- so a TCAD result reaches a circuit design flow.

Nothing here reimplements physics.  The models fitted are exactly the
ones `pytcad/circuit.py` already implements and
`tests/test_m27_circuit.py` already gates against their published laws
(Shockley; Shichman-Hodges level-1), the optimizer is the same
`scipy.optimize.minimize(method="Nelder-Mead")` call shape
`workbench/calibration.py` uses, and the round-trip closes through
`circuit.Circuit`'s own solver -- no external SPICE, no network.

Plan, gates and full honest limits: `pytcad/M38-COMPACT-MODEL-PLAN.md`.

HONEST LIMITS (properties of the TARGET MODELS, not of the fitter --
see plan section 3; written here so a caller meets them at the API):

  * UNITS DO NOT MATCH ACROSS THE THREE LAYERS, and that is
    load-bearing.  `Device1D.current_density` returns A/cm^2,
    `Device2D.terminal_current` returns A/cm (per cm of width), and
    `circuit.py`'s elements are in AMPERES.  Every extractor therefore
    takes its scaling factor as a REQUIRED positional argument -- no
    default -- and records it on the result, mirroring
    `circuit.DeviceStamp`'s explicit `area_cm2`.  For a 1D device pass
    the area in cm^2; for a 2D device pass the width in cm.
  * `circuit.Circuit` ADDS A 1e-12 S SHUNT TO GROUND ON EVERY NODE
    (its floating-node guard, `G += np.eye(size) * 1.0e-12`).  A
    terminal current below roughly `MNA_LEAKAGE_G * V` amperes is
    therefore DOMINATED by that guard, not by the element being
    simulated -- measured directly while writing gate G3-CLOSED, where
    a 1e-4 cm^2 diode at 0.25 V passes 2.5e-14 A against a 2.5e-13 A
    guard leakage, a 10x error.  This is a property of the MNA solver,
    not of the fit; `mna_resolvable()` below is how a caller checks it
    instead of discovering it as a mysterious low-bias discrepancy.
  * A FIT REPORTS ITS OWN RESIDUAL AND NEVER HIDES IT.  Following
    `calibration.py`'s G-NOCONVERGE precedent, an extraction that
    cannot converge says so on the result rather than returning a
    fabricated "best fit", and malformed input RAISES rather than
    being silently dropped.
"""
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

# Room-temperature thermal voltage, matching `circuit.Diode`'s own
# default exactly so a parameter set extracted here and stamped there
# describes the same curve.
VT_DEFAULT = 0.025852

# Finite (not inf) penalty for a trial the model cannot evaluate, so
# scipy's simplex geometry stays well-defined -- same reasoning as
# `calibration.UNREACHABLE_PENALTY`.
UNREACHABLE_PENALTY = 1.0e6

# A two-parameter fit needs more than two points to say anything; below
# this the fit is under-determined and is refused rather than reported.
MIN_FIT_POINTS = 3


def shockley_current(V, Is, N, VT=VT_DEFAULT):
    """I = Is*(exp(V/(N*VT)) - 1), the law `circuit.Diode` stamps."""
    V = np.asarray(V, dtype=float)
    return Is * (np.expm1(V / (N * VT)))


@dataclass
class DiodeParams:
    """Extracted SPICE diode parameters, in AMPERES (i.e. already
    through `scale`), plus the provenance a reader needs to judge them."""
    Is: float
    N: float
    VT: float
    scale: float
    rms_log_error: float
    n_points: int
    v_min: float
    v_max: float
    converged: bool


def _clean_iv(V, I, scale):
    """Validate and scale a raw (V, I) pair.  Raises on anything the
    caller cannot have meant; returns arrays in volts and AMPERES."""
    V = np.asarray(V, dtype=float).ravel()
    I = np.asarray(I, dtype=float).ravel()
    if V.shape != I.shape:
        raise ValueError(f"V and I must have the same shape, got "
                         f"{V.shape} and {I.shape}")
    if V.size == 0:
        raise ValueError("empty I-V data")
    # NaN fails every comparison, so a bound check alone would let it
    # through silently -- check finiteness explicitly (house gotcha).
    if not np.all(np.isfinite(V)) or not np.all(np.isfinite(I)):
        raise ValueError("I-V data contains non-finite values")
    scale = float(scale)
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError(f"scale must be a positive finite number "
                         f"(cm^2 for a 1D device, cm for a 2D device), "
                         f"got {scale!r}")
    return V, I * scale, scale


def _seed_diode(V, I, VT):
    """Closed-form two-point estimate from the endpoints of the fit
    window: the exponential's slope gives N, then one point gives Is."""
    v1, v2 = float(V[0]), float(V[-1])
    i1, i2 = float(I[0]), float(I[-1])
    dlog = np.log(i2) - np.log(i1)
    if dlog <= 0.0 or v2 <= v1:
        return 1.0e-14, 1.0
    N = (v2 - v1) / (VT * dlog)
    N = float(np.clip(N, 0.2, 5.0))
    Is = i1 / np.expm1(v1 / (N * VT))
    if not np.isfinite(Is) or Is <= 0.0:
        Is = 1.0e-14
    return float(Is), N


def extract_diode(V, I, scale, VT=VT_DEFAULT, v_window=None, seed=None,
                  max_iter=2000, tol=1.0e-12):
    """Fit `circuit.Diode`'s (Is, N) to a forward I-V curve.

    V       [V] terminal voltages.
    I       raw currents as the solver reported them (A/cm^2 for
            `Device1D.current_density`, A/cm for
            `Device2D.terminal_current`).
    scale   REQUIRED multiplier taking `I` to amperes -- area in cm^2
            for a 1D device, width in cm for a 2D device.  See the
            module docstring; there is deliberately no default.
    v_window optional (vmin, vmax) restricting the fit; forward points
            only are used in any case.

    The fit is done on log(I), because the quantity being matched spans
    orders of magnitude and an absolute-error fit would see only the
    largest currents (the same reasoning as M13's log-space Fermi
    integral table).
    """
    V, I, scale = _clean_iv(V, I, scale)

    mask = (V > 0.0) & (I > 0.0)
    if v_window is not None:
        vmin, vmax = float(v_window[0]), float(v_window[1])
        if not (np.isfinite(vmin) and np.isfinite(vmax)) or vmax <= vmin:
            raise ValueError(f"v_window must be an increasing finite "
                             f"(vmin, vmax), got {v_window!r}")
        mask &= (V >= vmin) & (V <= vmax)
    if int(np.count_nonzero(mask)) < MIN_FIT_POINTS:
        raise ValueError(
            f"need at least {MIN_FIT_POINTS} forward-bias points with "
            f"positive current to fit a 2-parameter diode; got "
            f"{int(np.count_nonzero(mask))}"
            + ("" if v_window is None else f" inside v_window={v_window}"))

    order = np.argsort(V[mask])
    Vf = V[mask][order]
    If = I[mask][order]
    log_ref = np.log(If)

    Is0, N0 = _seed_diode(Vf, If, VT) if seed is None else (
        float(seed[0]), float(seed[1]))
    if not (np.isfinite(Is0) and Is0 > 0.0 and np.isfinite(N0) and N0 > 0.0):
        raise ValueError(f"seed must be a positive (Is, N), got {seed!r}")

    def rms_log(Is, N):
        if not (np.isfinite(Is) and Is > 0.0 and np.isfinite(N) and N > 0.0):
            return UNREACHABLE_PENALTY
        model = shockley_current(Vf, Is, N, VT)
        if not np.all(np.isfinite(model)) or np.any(model <= 0.0):
            return UNREACHABLE_PENALTY
        return float(np.sqrt(np.mean((np.log(model) - log_ref) ** 2)))

    def objective(x):
        return rms_log(10.0 ** x[0], x[1])

    res = minimize(objective, np.array([np.log10(Is0), N0]),
                   method="Nelder-Mead",
                   options={"maxiter": max_iter, "xatol": tol, "fatol": tol})

    Is_fit, N_fit = 10.0 ** float(res.x[0]), float(res.x[1])
    err = float(res.fun)
    return DiodeParams(
        Is=Is_fit, N=N_fit, VT=float(VT), scale=scale,
        rms_log_error=err, n_points=int(Vf.size),
        v_min=float(Vf[0]), v_max=float(Vf[-1]),
        converged=bool(res.success) and err < UNREACHABLE_PENALTY)


# ======================================================================
# MOSFET level-1 (Shichman-Hodges) -- see plan sections 3.1/3.2 for the
# two honest limits that shape this entire extraction: the model has NO
# subthreshold conduction (Id is EXACTLY 0 below threshold) and NO body
# effect.  The fit is therefore defined on strong inversion only, the
# error is reported in LINEAR relative terms, and a window containing
# sub-threshold points is REFUSED rather than quietly fitted.
# ======================================================================

# Minimum overdrive (Vgs - Vt0) every supplied Id-Vg point must clear
# before the fit is considered well-posed.  Not a tuning knob: it is
# the boundary of the region where `MOSFET1` has any physics at all.
VOV_MIN_DEFAULT = 0.1

# Fraction of peak transconductance defining the "near-peak gm plateau"
# the ELR tangent is least-squares fitted over.  See the comment at its
# use site for the adversarial measurement that motivated a windowed fit
# rather than a pointwise derivative.
ELR_PLATEAU_FRAC = 0.8


def mosfet1_current(vgs, vds, Vt0, beta, lam, kind="n"):
    """Drain current of `circuit.MOSFET1`, in amperes.

    Mirrors `MOSFET1.stamp`'s three branches exactly -- cutoff (exactly
    zero), triode, saturation, each with the same first-order
    channel-length-modulation factor -- so a parameter set fitted here
    reproduces what that element will actually stamp.
    """
    if kind not in ("n", "p"):
        raise ValueError(f"kind must be 'n' or 'p', got {kind!r}")
    sgn = 1.0 if kind == "n" else -1.0
    vgs_f = sgn * np.asarray(vgs, dtype=float)
    vds_f = sgn * np.asarray(vds, dtype=float)
    vov = vgs_f - Vt0
    onepl = 1.0 + lam * vds_f
    triode = beta * (vov * vds_f - 0.5 * vds_f ** 2) * onepl
    sat = 0.5 * beta * vov ** 2 * onepl
    Id = np.where(vov <= 0.0, 0.0, np.where(vds_f < vov, triode, sat))
    return sgn * Id


@dataclass
class IdVgCurve:
    """Transfer characteristic at ONE fixed drain bias (and, since
    `MOSFET1` has no body effect, one fixed Vbs = 0)."""
    vg: np.ndarray
    id: np.ndarray
    vds: float


@dataclass
class IdVdCurve:
    """Output characteristic at ONE fixed gate bias."""
    vd: np.ndarray
    id: np.ndarray
    vgs: float


@dataclass
class MOSFET1Params:
    """Extracted level-1 parameters, in AMPERES/volts (already through
    `scale`).

    `kp_WL` is the PRODUCT kp*W_L, which is the only combination the
    model depends on (`MOSFET1.__init__` immediately forms
    `beta = kp*W_L`); the two factors are degenerate against an I-V
    curve and are NOT separately extractable.  Emitting it means
    `KP=kp_WL` with W/L = 1.
    """
    Vt0: float
    kp_WL: float
    lam: float
    kind: str
    scale: float
    rel_rms_error: float
    n_points: int
    vov_min: float
    converged: bool


def _clean_curve(v, i, scale, what):
    v = np.asarray(v, dtype=float).ravel()
    i = np.asarray(i, dtype=float).ravel()
    if v.shape != i.shape:
        raise ValueError(f"{what}: v and id must have the same shape, "
                         f"got {v.shape} and {i.shape}")
    if not np.all(np.isfinite(v)) or not np.all(np.isfinite(i)):
        raise ValueError(f"{what}: data contains non-finite values")
    if v.size < MIN_FIT_POINTS:
        raise ValueError(f"{what}: need at least {MIN_FIT_POINTS} points, "
                         f"got {v.size}")
    return v, i * scale


def extract_mosfet1(idvg, idvd, scale, kind="n",
                    vov_min=VOV_MIN_DEFAULT, refine=True,
                    max_iter=4000, tol=1.0e-12):
    """Fit `circuit.MOSFET1`'s (Vt0, kp*W_L, lambda) to a TCAD
    transfer curve plus one output curve.

    scale   REQUIRED multiplier taking the supplied currents to
            amperes -- width in cm for a `Device2D.terminal_current`
            result (A/cm), area in cm^2 for a 1D one.  See the module
            docstring; there is deliberately no default.

    Vt0 and beta come from the textbook linear-extrapolation (ELR)
    construction -- the tangent to Id(Vgs) at PEAK transconductance,
    extrapolated to Id = 0, minus Vds/2 -- taken at the low Vds of
    `idvg`.  lambda then comes from the saturation-region slope of
    `idvd`.  `refine=True` polishes all three together against both
    curves at once (Nelder-Mead, the same call shape
    `workbench/calibration.py` uses).
    """
    if kind not in ("n", "p"):
        raise ValueError(f"kind must be 'n' or 'p', got {kind!r}")
    scale = float(scale)
    if not np.isfinite(scale) or scale <= 0.0:
        raise ValueError(f"scale must be a positive finite number, "
                         f"got {scale!r}")
    sgn = 1.0 if kind == "n" else -1.0

    vg, ig = _clean_curve(idvg.vg, idvg.id, scale, "idvg")
    vd, idd = _clean_curve(idvd.vd, idvd.id, scale, "idvd")
    vds_lin = sgn * float(idvg.vds)
    vgs_sat = sgn * float(idvd.vgs)
    # Sort in the NMOS-equivalent frame, not in raw node voltages: for a
    # PMOS the two orders are reversed, and np.gradient/np.polyfit below
    # both read their abscissa as increasing.
    og, od = np.argsort(sgn * vg), np.argsort(sgn * vd)
    vg, ig, vd, idd = vg[og], ig[og], vd[od], idd[od]
    vg_f, ig_f = sgn * vg, sgn * ig
    vd_f, id_f = sgn * vd, sgn * idd
    if vds_lin <= 0.0:
        raise ValueError("idvg.vds must be a nonzero drain bias of the "
                         "same polarity as `kind`")
    if np.any(ig_f <= 0.0) or np.any(id_f <= 0.0):
        raise ValueError(
            "every fitted point must carry a nonzero drain current of the "
            "expected polarity; `MOSFET1` returns EXACTLY zero below "
            "threshold, so a zero/reversed point cannot be fitted "
            "(plan section 3.1)")

    # --- ELR seed: tangent at peak gm, extrapolated to Id = 0 ---------
    # The tangent is a LEAST-SQUARES line over the whole near-peak-gm
    # plateau, not the derivative at the single argmax point.  Measured
    # while probing adversarially: a pointwise np.gradient argmax on a
    # curve with 5% noise picked the wrong point and moved the extracted
    # threshold by 0.6 V, enough to trip the strong-inversion refusal on
    # data the windowed fit handles.  On a noiseless level-1 triode
    # curve gm is exactly constant, so every point is in the plateau and
    # this reduces to the exact answer.
    gm = np.gradient(ig_f, vg_f)
    if float(np.max(gm)) <= 0.0:
        raise ValueError("idvg is not monotonically increasing in "
                         "overdrive; cannot extract a threshold from it")
    plateau = gm >= ELR_PLATEAU_FRAC * float(np.max(gm))
    if int(np.count_nonzero(plateau)) < MIN_FIT_POINTS:
        # Too peaked to have a plateau: fall back to the MIN_FIT_POINTS
        # points nearest the peak.
        k = int(np.argmax(gm))
        lo = int(np.clip(k - MIN_FIT_POINTS // 2, 0,
                         max(0, vg_f.size - MIN_FIT_POINTS)))
        plateau = np.zeros_like(gm, dtype=bool)
        plateau[lo:lo + MIN_FIT_POINTS] = True
    slope_g, inter_g = np.polyfit(vg_f[plateau], ig_f[plateau], 1)
    if slope_g <= 0.0:
        raise ValueError("idvg's transconductance is not positive over "
                         "the fitted window; cannot extract a threshold")
    Vt0 = float(-inter_g / slope_g - 0.5 * vds_lin)
    beta = float(slope_g / vds_lin)

    # --- refusals that make the honest limits enforceable ------------
    vov_min = float(vov_min)
    if np.any(vg_f < Vt0 + vov_min):
        raise ValueError(
            f"idvg window reaches Vgs = {float(vg_f.min()):.4g} V, below "
            f"the strong-inversion floor Vt0 + vov_min = "
            f"{Vt0 + vov_min:.4g} V (extracted Vt0 = {Vt0:.4g} V). "
            f"`MOSFET1` has no subthreshold conduction at all, so a "
            f"window that crosses threshold is ill-posed, not merely "
            f"inaccurate -- supply strong-inversion points only "
            f"(plan section 3.1, gate G2-REFUSE).")
    vov_sat = vgs_sat - Vt0
    if np.any(vd_f <= vov_sat):
        raise ValueError(
            f"idvd window reaches Vds = {float(vd_f.min()):.4g} V, at or "
            f"below the saturation knee Vgs - Vt0 = {vov_sat:.4g} V. "
            f"lambda is the saturation-region slope; triode points "
            f"cannot constrain it (gate G2-REFUSE).")

    # --- lambda from the saturation slope ----------------------------
    slope, intercept = np.polyfit(vd_f, id_f, 1)
    lam = float(slope / intercept) if intercept > 0.0 else 0.0
    lam = float(np.clip(lam, 0.0, 10.0))

    def rel_rms(Vt0_, beta_, lam_):
        if not (np.isfinite(Vt0_) and np.isfinite(beta_)
                and np.isfinite(lam_)) or beta_ <= 0.0 or lam_ < 0.0:
            return UNREACHABLE_PENALTY
        m1 = mosfet1_current(vg, np.full_like(vg, idvg.vds),
                             Vt0_, beta_, lam_, kind) * sgn
        m2 = mosfet1_current(np.full_like(vd, idvd.vgs), vd,
                             Vt0_, beta_, lam_, kind) * sgn
        if np.any(m1 <= 0.0) or np.any(m2 <= 0.0):
            return UNREACHABLE_PENALTY
        r = np.concatenate([(m1 - ig_f) / ig_f, (m2 - id_f) / id_f])
        return float(np.sqrt(np.mean(r ** 2)))

    converged = True
    if refine:
        res = minimize(lambda x: rel_rms(x[0], x[1], x[2]),
                       np.array([Vt0, beta, lam]), method="Nelder-Mead",
                       options={"maxiter": max_iter, "xatol": tol,
                                "fatol": tol})
        if res.fun < rel_rms(Vt0, beta, lam):
            Vt0, beta, lam = (float(res.x[0]), float(res.x[1]),
                              float(res.x[2]))
        converged = bool(res.success)

    err = rel_rms(Vt0, beta, lam)
    return MOSFET1Params(
        Vt0=Vt0, kp_WL=beta, lam=lam, kind=kind, scale=scale,
        rel_rms_error=err, n_points=int(vg.size + vd.size),
        vov_min=vov_min,
        converged=converged and err < UNREACHABLE_PENALTY)


# ======================================================================
# Netlist emission / read-back, and the closed loop back through
# `pytcad/circuit.py`'s own MNA solver.
#
# Provenance (fit residual, point count, the unit `scale`) travels in
# a comment line, not in the `.MODEL` card: a real SPICE ignores it,
# and a reader that needs to judge the fit still gets it.  `from_netlist`
# exists so the round-trip is GENUINE rather than asserted -- a test
# that only checks emitted text against a hand-written string is
# structurally incapable of catching a reader/writer disagreement.
# ======================================================================

_PROV = "* PYTCAD_PROVENANCE"
_HEADER = ("* PyTCAD M38 extracted compact model -- provenance in the "
           "PYTCAD_PROVENANCE line below.\n"
           "* Plan, gates and honest limits: "
           "pytcad/M38-COMPACT-MODEL-PLAN.md\n")


def _g(x):
    """Full-precision float text, so read-back is exact."""
    return "%.17g" % float(x)


def to_netlist(params, name=None):
    """Emit a SPICE `.MODEL` card (plus a provenance comment) for an
    extracted parameter set."""
    if isinstance(params, DiodeParams):
        name = name or "DMOD"
        prov = (f"{_PROV} model=diode VT={_g(params.VT)} "
                f"scale={_g(params.scale)} "
                f"rms_log_error={_g(params.rms_log_error)} "
                f"n_points={params.n_points} v_min={_g(params.v_min)} "
                f"v_max={_g(params.v_max)} "
                f"converged={int(params.converged)}")
        card = (f".MODEL {name} D (IS={_g(params.Is)} N={_g(params.N)})")
        return _HEADER + prov + "\n" + card + "\n"
    if isinstance(params, MOSFET1Params):
        name = name or ("NMOD" if params.kind == "n" else "PMOD")
        sgn = 1.0 if params.kind == "n" else -1.0
        prov = (f"{_PROV} model=mosfet1 channel={params.kind} "
                f"scale={_g(params.scale)} "
                f"rel_rms_error={_g(params.rel_rms_error)} "
                f"n_points={params.n_points} "
                f"vov_min={_g(params.vov_min)} "
                f"converged={int(params.converged)}")
        # VTO follows the SPICE sign convention (negative for a PMOS),
        # NOT `MOSFET1`'s internal always-positive overdrive frame; the
        # reader flips it back.  W/L is 1 because kp and W_L are
        # degenerate against an I-V curve (see MOSFET1Params).
        card = (f".MODEL {name} {'NMOS' if params.kind == 'n' else 'PMOS'} "
                f"(LEVEL=1 VTO={_g(sgn * params.Vt0)} "
                f"KP={_g(params.kp_WL)} LAMBDA={_g(params.lam)})")
        return _HEADER + prov + "\n" + card + "\n"
    raise TypeError(f"cannot emit a netlist for {type(params).__name__}")


def _kv(text):
    out = {}
    for tok in text.replace(",", " ").split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k.upper()] = v
    return out


def from_netlist(text):
    """Read back what `to_netlist` wrote.  Raises on a deck this module
    did not write (no provenance line) or an unknown model kind."""
    prov_lines = []
    card_lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(_PROV):
            prov_lines.append(line[len(_PROV):])
        elif line.upper().startswith(".MODEL"):
            card_lines.append(line)
    if len(prov_lines) != 1 or len(card_lines) != 1:
        raise ValueError(
            f"expected exactly one PYTCAD_PROVENANCE comment and one "
            f".MODEL card, got {len(prov_lines)} and {len(card_lines)}; "
            f"this reader deliberately refuses a multi-model deck rather "
            f"than silently picking one")
    prov_line, card_line = prov_lines[0], card_lines[0]
    if "(" not in card_line or ")" not in card_line:
        raise ValueError(f"malformed .MODEL card (no parameter list): "
                         f"{card_line!r}")
    prov = _kv(prov_line)
    body = card_line[card_line.index("(") + 1:card_line.rindex(")")]
    card = _kv(body)
    model = prov.get("MODEL", "").lower()

    if model == "diode":
        return DiodeParams(
            Is=float(card["IS"]), N=float(card["N"]),
            VT=float(prov["VT"]), scale=float(prov["SCALE"]),
            rms_log_error=float(prov["RMS_LOG_ERROR"]),
            n_points=int(prov["N_POINTS"]), v_min=float(prov["V_MIN"]),
            v_max=float(prov["V_MAX"]),
            converged=bool(int(prov["CONVERGED"])))
    if model == "mosfet1":
        kind = prov["CHANNEL"].lower()
        sgn = 1.0 if kind == "n" else -1.0
        return MOSFET1Params(
            Vt0=sgn * float(card["VTO"]), kp_WL=float(card["KP"]),
            lam=float(card["LAMBDA"]), kind=kind,
            scale=float(prov["SCALE"]),
            rel_rms_error=float(prov["REL_RMS_ERROR"]),
            n_points=int(prov["N_POINTS"]),
            vov_min=float(prov["VOV_MIN"]),
            converged=bool(int(prov["CONVERGED"])))
    raise ValueError(f"unknown compact model kind {model!r}")


# `circuit.Circuit._newton`'s floating-node guard conductance [S].
# Pinned here so a caller can reason about the resolution floor it
# implies; see the module docstring.
MNA_LEAKAGE_G = 1.0e-12


def mna_resolvable(V, I_amp, margin=100.0):
    """Mask of points whose current clears `circuit.Circuit`'s
    floating-node guard leakage (|V| * MNA_LEAKAGE_G) by `margin`.

    Below that, a closed-loop comparison measures the guard, not the
    compact model.  Returning a MASK rather than silently dropping the
    points keeps the caller responsible for saying so.
    """
    V = np.abs(np.asarray(V, dtype=float))
    I_amp = np.abs(np.asarray(I_amp, dtype=float))
    return I_amp > margin * MNA_LEAKAGE_G * V


def source_current(x, mna, name):
    """Current flowing OUT of a `VSource`'s + terminal into the rest of
    the circuit, from an MNA solution.

    `circuit.VSource` stamps its branch unknown with the opposite sign,
    so this one negation is the whole conversion -- verified directly
    against a resistor whose current is known analytically (gate
    G3-BRANCH), not read off the stamp by inspection.
    """
    return -float(x[mna.vsrc_index[name]])


def simulate_diode_iv(params, V, name="D1", max_dv=1.0):
    """Drive the extracted diode through `circuit.Circuit`'s own MNA
    solver at each V and return the terminal current [A].

    An IDEAL voltage source sits directly across the diode, so the
    diode voltage is exactly the swept V -- which is what a closed-loop
    comparison against an I-V curve wants, and which also inherits two
    limits of `circuit.py` worth knowing before they look like bugs
    (both measured directly, not read off the source):

      * `Circuit._newton` clamps every Newton step to `max_dv`, and the
        source's BRANCH CURRENT is one of the clamped unknowns.  A bias
        drawing far more than `max_dv` amperes therefore cannot be
        reached in the default 100 iterations; raise `max_dv` for it.
      * `circuit.Diode.stamp` clips the voltage it LINEARIZES at to
        1.5 V.  Above that the linearization no longer tracks the true
        operating point and the solve does not converge at ANY
        `max_dv`.  That is a hard ceiling of the element, not of this
        wrapper.
    """
    from pytcad.circuit import Circuit, VSource, Diode, GND
    V = np.asarray(V, dtype=float).ravel()
    out = np.empty_like(V)
    for k, v in enumerate(V):
        c = Circuit()
        c.add(VSource("VS", "a", GND, float(v)))
        c.add(Diode(name, "a", GND, Is=params.Is, N=params.N, VT=params.VT))
        x, mna = c.dc_operating_point(max_dv=max_dv)
        out[k] = source_current(x, mna, "VS")
    return out


def simulate_mosfet1_id(params, vgs, vds, name="M1", max_dv=1.0):
    """Drive the extracted MOSFET through `circuit.Circuit` at each
    (vgs, vds) pair and return the drain current [A]."""
    from pytcad.circuit import Circuit, VSource, MOSFET1, GND
    vgs = np.asarray(vgs, dtype=float).ravel()
    vds = np.asarray(vds, dtype=float).ravel()
    if vgs.shape != vds.shape:
        raise ValueError(f"vgs and vds must have the same shape, got "
                         f"{vgs.shape} and {vds.shape}")
    out = np.empty_like(vgs)
    for k in range(vgs.size):
        c = Circuit()
        c.add(VSource("VG", "g", GND, float(vgs[k])))
        c.add(VSource("VD", "d", GND, float(vds[k])))
        c.add(MOSFET1(name, "d", "g", GND, kind=params.kind,
                      Vt0=params.Vt0, kp=params.kp_WL, W_L=1.0,
                      lam=params.lam))
        x, mna = c.dc_operating_point(max_dv=max_dv)
        out[k] = source_current(x, mna, "VD")
    return out
