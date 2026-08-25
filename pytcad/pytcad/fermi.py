"""Complete Fermi-Dirac integral F_{1/2} and friends (M13).

    F_{1/2}(eta) = (1/Gamma(3/2)) * Integral_0..inf
                   t^(1/2) / (1 + exp(t - eta)) dt

normalized so the nondegenerate limit is exactly exp(eta).  The
degenerate limit is the Sommerfeld expansion
(4/(3 sqrt(pi))) eta^(3/2) [1 + pi^2/(8 eta^2) + ...].

Production evaluation (f_half) is a fixed-node Gauss-Legendre
quadrature of the smooth transformed integrand t = s^2:

    F_{1/2}(eta) = (4/sqrt(pi)) Integral_0..smax
                   s^2 / (1 + exp(s^2 - eta)) ds

-- deterministic, C-infinity smooth in eta, vectorized, overflow-safe
through the split evaluation of 1/(1+e^x).  smax = sqrt(max(eta,0)+50)
keeps the truncation below double-precision noise for eta in [-40,40].

The independent reference (f_half_ref) is scipy adaptive quadrature on
the same transform -- a different discretization entirely, so the G1
gate compares two independent schemes, and the tests additionally
audit both against 30-digit mpmath values.

dF_{1/2}/d eta = F_{-1/2} (standard identity, verified numerically in
the tests); f_mhalf evaluates F_{-1/2} on the same GL nodes (the
t = s^2 transform removes its integrable t^(-1/2) endpoint
singularity).

No pytcad imports: this module is pure and independently testable.
"""
import numpy as np

__all__ = ["f_half", "f_half_ref", "f_mhalf", "df_half",
           "f_half_inv", "ni_fd", "FERMI_ETA_MIN", "FERMI_ETA_MAX"]

# eta domain of the implementation; outside it we refuse loudly
# (G7 applicability limit -- no silent extrapolation).
FERMI_ETA_MIN = -40.0
FERMI_ETA_MAX = +40.0

_GL_ORDER = 48
_gn, _gw = np.polynomial.legendre.leggauss(_GL_ORDER)
# Hybrid evaluation: [0, 1] in s (t = s^2 transform, kills the t^(-1/2)
# endpoint singularity of F_{-1/2}), then [1, t_max] directly in t with
# width-2 panels.  In t the 1/(1+e^(t-eta)) transition has O(1) width
# for EVERY eta -- unlike in s, where it narrows as 1/(2 sqrt(eta)) and
# defeated uniform panels at eta = 40 (measured 1.2e-7).
_PANEL_WIDTH_T = 2.0
_T_SWITCH = 1.0


def _inv_softplus(x):
    """1/(1+exp(x)) without overflow anywhere in x."""
    out = np.empty_like(x)
    pos = x > 0
    xp = x[pos]
    out[pos] = np.exp(-xp) / (1.0 + np.exp(-xp))
    xm = x[~pos]
    out[~pos] = 1.0 / (1.0 + np.exp(xm))
    return out


def _check_eta(eta):
    if np.any(eta < FERMI_ETA_MIN) or np.any(eta > FERMI_ETA_MAX):
        raise ValueError(
            f"Fermi integral argument eta outside the validated range "
            f"[{FERMI_ETA_MIN}, {FERMI_ETA_MAX}]: got {eta!r}.  The "
            f"quadrature is only gated on this interval; refusing to "
            f"extrapolate (M13 G7 applicability limit).")


def _gl_eval(eta, fn_s, fn_t):
    """Hybrid fixed-node GL evaluation, vectorized over eta.

    Region A: s in [0, 1]  (t = s^2), one GL panel.
    Region B: t in [1, t_max], width-2 panels, t_max = max(eta, 0)+60
    (truncation below double-precision noise).
    fn_s(s, eta) / fn_t(t, eta) return the integrand; broadcasting
    over the padded panel grid keeps this one vectorized call.
    """
    eta = np.asarray(eta, dtype=float)
    scalar = (eta.ndim == 0)
    eta1 = np.atleast_1d(eta)
    _check_eta(eta1)
    n = eta1.size

    # region A: single panel s in [0, 1]
    sA = 0.5 * (_gn + 1.0)
    wA = 0.5 * _gw
    totA = (fn_s(sA[None, :], eta1[:, None]) * wA[None, :]).sum(axis=1)

    # region B: width-2 panels on [1, t_max]
    tmax = np.maximum(eta1, 0.0) + 60.0
    n_pan = np.ceil((tmax - _T_SWITCH) / _PANEL_WIDTH_T).astype(int)
    np_max = int(n_pan.max())
    k_lo = np.minimum(np.arange(np_max)[None, :], n_pan[:, None])
    k_hi = np.minimum(np.arange(1, np_max + 1)[None, :], n_pan[:, None])
    a = _T_SWITCH + (tmax[:, None] - _T_SWITCH) * k_lo / n_pan[:, None]
    b = _T_SWITCH + (tmax[:, None] - _T_SWITCH) * k_hi / n_pan[:, None]
    half = 0.5 * (b - a)
    mid = 0.5 * (a + b)
    t = mid[:, :, None] + half[:, :, None] * _gn[None, None, :]
    w = half[:, :, None] * _gw[None, None, :]
    vals = fn_t(t.reshape(n, -1),
                np.repeat(eta1[:, None], np_max * _GL_ORDER, axis=1))
    totB = (vals * w.reshape(n, -1)).sum(axis=1)

    total = totA + totB
    return total[0] if scalar else total


def f_half(eta):
    """Complete Fermi integral F_{1/2}(eta), normalized to exp(eta)."""
    return _gl_eval(
        eta,
        lambda s, e: (4.0 / np.sqrt(np.pi)) * s * s
        * _inv_softplus(s * s - e),
        lambda t, e: (2.0 / np.sqrt(np.pi)) * np.sqrt(t)
        * _inv_softplus(t - e))


def f_mhalf(eta):
    """F_{-1/2}(eta) = d F_{1/2} / d eta (same normalization family)."""
    return _gl_eval(
        eta,
        lambda s, e: (2.0 / np.sqrt(np.pi)) * _inv_softplus(s * s - e),
        lambda t, e: (1.0 / np.sqrt(np.pi)) * t ** -0.5
        * _inv_softplus(t - e))


def df_half(eta):
    """Analytic derivative d F_{1/2}/d eta (= F_{-1/2})."""
    return f_mhalf(eta)


def f_half_ref(eta):
    """Independent reference: scipy adaptive quadrature (hybrid split,
    per point) -- a different discretization from f_half entirely.

    The IntegrationWarning is suppressed deliberately: at 1e-14
    tolerances scipy warns about its own roundoff floor on the
    deep-Boltzmann tail; that floor (~1e-21 absolute here) is far
    below every gate this reference feeds."""
    import warnings
    from scipy.integrate import quad
    from scipy.integrate import IntegrationWarning
    eta = np.asarray(eta, dtype=float)
    scalar = (eta.ndim == 0)
    out = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", IntegrationWarning)
        for e in np.atleast_1d(eta):
            _check_eta(np.asarray([e]))
            isp = lambda x: 1.0 / (1.0 + np.exp(x)) if x < 0 else \
                np.exp(-x) / (1.0 + np.exp(-x))
            va, _ = quad(lambda s: (4.0 / np.sqrt(np.pi)) * s * s
                         * isp(s * s - e), 0.0, 1.0,
                         limit=200, epsabs=1e-15, epsrel=1e-13)
            tmax = max(e, 0.0) + 60.0
            vb, _ = quad(lambda t: (2.0 / np.sqrt(np.pi)) * np.sqrt(t)
                         * isp(t - e), 1.0, tmax,
                         limit=500, epsabs=1e-15, epsrel=1e-13)
            out.append(va + vb)
    res = np.array(out)
    return res[0] if scalar else res


def f_half_inv(nu):
    """Inverse of F_{1/2}: given nu = F_{1/2}(eta), return eta.

    Bracketed bisection (F is strictly increasing, F(eta) < exp(eta)
    gives the lower bracket, the Sommerfeld leading term gives the
    upper) with a Newton polish; machine-precision by construction.
    """
    nu = np.asarray(nu, dtype=float)
    scalar = (nu.ndim == 0)
    nu1 = np.atleast_1d(nu)
    if np.any(nu1 <= 0) or not np.all(np.isfinite(nu1)):
        raise ValueError(f"f_half_inv needs nu > 0 finite, got {nu!r}")
    nu_max = f_half(FERMI_ETA_MAX)
    if np.any(nu1 > nu_max):
        raise ValueError(
            f"f_half_inv: nu={nu1.max():.6g} exceeds "
            f"F_1/2({FERMI_ETA_MAX})={nu_max:.6g} -- the inverse is "
            f"only validated on the eta range [-40, 40] (M13 G7).")
    lo = np.maximum(np.log(nu1) - 1.0, FERMI_ETA_MIN)
    hi = np.minimum((0.75 * np.sqrt(np.pi) * nu1) ** (2.0 / 3.0) + 1.0,
                    FERMI_ETA_MAX)
    # F(hi) > (4/(3 sqrt(pi))) hi^1.5 >= nu by construction (all
    # Sommerfeld terms positive for eta > 0; for nu <= F(1) the +1
    # covers the bracket).
    for _ in range(200):
        mid = np.clip(0.5 * (lo + hi), FERMI_ETA_MIN, FERMI_ETA_MAX)
        fm = f_half(mid)
        left = fm > nu1
        hi = np.where(left, mid, hi)
        lo = np.where(left, lo, mid)
        if np.all(hi - lo < 1e-14 * (1.0 + np.abs(lo))):
            break
    res = 0.5 * (lo + hi)
    # Newton polish (derivative = F_{-1/2} > 0, monotone -> safe)
    for _ in range(3):
        f = f_half(res)
        d = f_mhalf(res)
        step = (f - nu1) / np.maximum(d, 1e-300)
        res = np.clip(res - np.clip(step, -0.5, 0.5),
                      FERMI_ETA_MIN, FERMI_ETA_MAX)
    return res[0] if scalar else res


def ni_fd(Nc, Nv, Eg_eV, T):
    """FD intrinsic carrier density from charge neutrality n = p.

    Solves Nc F_{1/2}(eta_i) = Nv F_{1/2}(-eta_i - Eg/kT) for the
    reduced Fermi level eta_i (bisection; the LHS-RHS difference is
    strictly increasing).  Returns (ni, eta_i).
    """
    kT = 8.617333262e-5 * T
    Nc = float(Nc)
    Nv = float(Nv)
    EgkT = Eg_eV / kT

    def imbalance(eta):
        return Nc * f_half(eta) - Nv * f_half(-eta - EgkT)

    lo, hi = -EgkT - 10.0, 10.0     # imbalance(lo) < 0 < imbalance(hi)
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if imbalance(mid) < 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-14 * (1.0 + abs(lo)):
            break
    eta_i = 0.5 * (lo + hi)
    return Nc * f_half(eta_i), eta_i
