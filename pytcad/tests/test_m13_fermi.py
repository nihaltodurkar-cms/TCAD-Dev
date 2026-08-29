"""M13 G1-G3 gates: Fermi integral evaluation, limits, inverse.

Gate reference: M13-FERMI-DIRAC-PLAN.md section 4.  These tests need
ONLY pytcad.fermi (pure addition -- no core dependency, no amendment
required).  G4-G8 (solver-level gates) live in their own files and
block M15+ together with these.

Published audit strategy, stated honestly:
  - the exact analytic anchor F_{1/2}(0) = (1 - 2^(-1/2)) zeta(3/2)
    is hardcoded to 16 digits (Blakemore, Semiconductor Statistics);
  - 30-digit mpmath quadrature values are generated IN-TEST (mpmath
    is an independent implementation: different transform, different
    arithmetic) and serve as the published-precision audit;
  - scipy adaptive quadrature (f_half_ref) is the CI working
    reference, a third discretization.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from pytcad.fermi import (f_half, f_half_ref, f_mhalf, df_half,
                          f_half_inv, ni_fd)

ZETA_32 = 2.6123753486854883          # zeta(3/2), published
F_HALF_0_EXACT = (1.0 - 2.0 ** -0.5) * ZETA_32


# ---------------------------------------------------------------- G1
def test_fermi_half_vs_quadrature():
    """G1: f_half vs the independent adaptive-quadrature reference.

    Gate: max relative error <= 1e-9 over eta in [-40, 40], grid
    dense near 0 where the solver lives.  Below F ~ 1e-11 (eta <~-25,
    densities ~1e8 cm^-3 -- far below device relevance) the metric
    switches to |fast-ref|/1e-11: two double-precision quadratures
    cannot agree RELATIVELY on values at 1e-14 (measured disagreement
    there is ~2e-21 ABSOLUTE -- roundoff of the summation itself)."""
    eta = np.unique(np.concatenate([
        np.linspace(-40, 40, 801),
        np.linspace(-2, 6, 3201),
    ]))
    fast = f_half(eta)
    ref = f_half_ref(eta)
    rel = np.abs(fast - ref) / np.maximum(ref, 1e-11)
    worst = float(rel.max())
    assert worst <= 1e-9, f"G1 FAIL: max metric err {worst:.3e} > 1e-9"


def test_fermi_half_smoothness():
    """G1: C1-smoothness guard (Newton and the Jacobian need it)."""
    eta = np.linspace(-40, 40, 80001)
    lf = np.log(f_half(eta))
    d2 = np.abs(np.diff(lf, 2))
    assert d2.max() <= 1e-6, f"G1 FAIL: roughness {d2.max():.3e}"


def test_fermi_half_published_spot_values():
    """G1 audit: exact analytic anchor + 30-digit mpmath values.

    The mpmath quadrature MUST subdivide at the knee (t ~ eta):
    mp.quad on [0, inf) under-resolves the plateau-to-decay transition
    there and was measured 5e-5 off at eta=40 -- against BOTH scipy
    and the published Sommerfeld series, which agree with f_half to
    ~1e-9.  (Audit-the-audit: this is why G1 uses three schemes.)"""
    # exact anchor (published identity, hardcoded digits)
    assert f_half(0.0) == pytest.approx(F_HALF_0_EXACT, rel=1e-13)
    # independent 30-digit mpmath quadrature, generated in-test
    mpmath = pytest.importorskip("mpmath")
    mp = mpmath.mp
    mp.dps = 30

    def F(eta):
        knee = max(eta, 0.0)
        lo = (2 / mp.sqrt(mp.pi)) * mp.quad(
            lambda s: (2 * s) * (mp.sqrt(s * s))
            / (1 + mp.e ** (s * s - eta)), [0, 1])
        hi = (2 / mp.sqrt(mp.pi)) * mp.quad(
            lambda t: mp.sqrt(t) / (1 + mp.e ** (t - eta)),
            [1, knee + 20, mp.inf])
        return lo + hi

    # third opinion at high eta: Sommerfeld series, THREE published
    # terms (1 + pi^2/(8 eta^2) + 7 pi^4/(640 eta^4)); the residual is
    # then dominated by the c3/eta^6 term, so the deviation decays as
    # eta^-6 -- factor ~64 per eta doubling, which the rate gate below
    # asserts (normalization errors break both gates at once).
    def sommerfeld(eta):
        eta = mp.mpf(eta)
        c = [mp.mpf(1), mp.pi ** 2 / 8, 7 * mp.pi ** 4 / 640]
        core = 4 / (3 * mp.sqrt(mp.pi)) * eta ** (mp.mpf(3) / 2)
        return core * sum(c[k] / eta ** (2 * k) for k in range(3))

    for eta in (-20.0, -10.0, -5.0, -2.0, -1.0, 0.0, 1.0, 2.0, 5.0,
                10.0, 20.0, 40.0):
        ref = float(mp.nstr(F(eta), 25))
        rel = abs(f_half(eta) - ref) / ref
        assert rel <= 1e-11, \
            f"G1 FAIL at eta={eta}: rel {rel:.3e} vs mpmath 30-digit"
    # Sommerfeld cross-check of the audit itself at the two highest
    # points (guards against a repeat of the knee under-resolution)
    d20 = abs(mp.mpf(float(f_half(20.0))) - sommerfeld(20.0)) \
        / sommerfeld(20.0)
    d40 = abs(mp.mpf(float(f_half(40.0))) - sommerfeld(40.0)) \
        / sommerfeld(40.0)
    assert d40 <= 1e-8, f"G1 FAIL: f_half vs Sommerfeld at 40: {mp.nstr(d40)}"
    rate = float(d20 / d40)
    assert 32.0 <= rate <= 128.0, \
        f"G1 FAIL: Sommerfeld residual rate {rate:.1f} not ~eta^-6 (64x)"


def test_fermi_mhalf_is_derivative():
    """d F_{1/2}/d eta = F_{-1/2} (identity the Jacobian relies on)."""
    eta = np.array([-20.0, -5.0, 0.0, 2.0, 10.0, 30.0])
    h = 1e-6
    fd = (f_half(eta + h) - f_half(eta - h)) / (2 * h)
    rel = np.abs(fd - f_mhalf(eta)) / fd
    assert rel.max() <= 1e-8, f"derivative identity broken: {rel}"
    assert np.allclose(df_half(eta), f_mhalf(eta))


# ---------------------------------------------------------------- G2
def test_fermi_half_boltzmann_limit():
    """G2: nondegenerate limit vs exp(eta).

    Gate numbers are the EXACT Taylor-series deviation of the complete
    Fermi integral, rel = e^eta / 2^(3/2) + O(e^(3 eta)) (published
    series, Blakemore App.): the spec's original (eta=-20, 1e-12) and
    (-15, 1e-9) were mathematically unattainable -- true deviations
    7.3e-10 and 1.1e-7 -- and were corrected to the exact-series
    values (spec-fix, not tolerance-weakening; documented in
    M13-FERMI-DIRAC-PLAN.md)."""
    gates = ((-30.0, 1e-12), (-20.0, 1e-9), (-15.0, 1e-6))
    for eta, tol in gates:
        true_dev = np.exp(eta) / 2.0 ** 1.5     # exact leading deviation
        rel = abs(f_half(eta) - np.exp(eta)) / np.exp(eta)
        assert rel <= max(tol, 2.0 * true_dev) and rel <= tol * 100, \
            f"G2 FAIL at eta={eta}: rel {rel:.3e}"
        assert rel <= tol, \
            f"G2 FAIL at eta={eta}: rel {rel:.3e} > {tol:.0e}"


def test_fd_on_boltzmann_regime_equivalence():
    """G2 (function level): at nondegenerate eta the FD density tracks
    exp(eta) with the exact series deviation e^eta/2^(3/2) -- the
    gates below are that deviation at each eta (solver-level I-V
    equivalence is a separate gate once the core lands)."""
    for eta, tol in ((-10.0, 1e-4), (-15.0, 1e-6), (-20.0, 1e-9)):
        rel = abs(f_half(eta) - np.exp(eta)) / np.exp(eta)
        assert rel <= tol, f"G2 FAIL at eta={eta}: {rel:.3e} > {tol:.0e}"


# ---------------------------------------------------------------- G3
def test_fermi_half_sommerfeld_asymptotics():
    """G3: degenerate limit -- Sommerfeld expansion with the
    published coefficients.  TWO terms are used deliberately: with 2
    terms the residual is dominated by the known 7 pi^4/(640 eta^4)
    term, so the deviation decays as eta^-4 and the RATE check
    (factor 16 per doubling) is meaningful; with 4 terms the residual
    decays eta^-8 (rate ~256, outside the naive band -- first run
    measured 78)."""
    def sommerfeld2(eta):
        core = (4.0 / (3.0 * np.sqrt(np.pi))) * eta ** 1.5
        return core * (1.0 + np.pi ** 2 / (8.0 * eta ** 2))

    dev20 = abs(f_half(20.0) - sommerfeld2(20.0)) / f_half(20.0)
    dev40 = abs(f_half(40.0) - sommerfeld2(40.0)) / f_half(40.0)
    # leading omitted term: (7 pi^4/640)/eta^4
    assert dev40 <= 1.2 * (7.0 * np.pi ** 4 / 640.0) / 40.0 ** 4, \
        f"G3 FAIL: Sommerfeld dev at 40 = {dev40:.3e}"
    rate = dev20 / dev40
    assert 8.0 <= rate <= 32.0, \
        f"G3 FAIL: deviation ratio {rate:.2f} not ~eta^-4 (16x)"


def test_fermi_inverse_roundtrip():
    """G3/G5 support: f_half_inv inverts to machine precision."""
    eta = np.array([-30.0, -10.0, -1.0, 0.0, 0.5, 2.0, 5.0, 20.0])
    back = f_half_inv(f_half(eta))
    err = np.abs(back - eta)
    assert err.max() <= 1e-10 * (1 + np.abs(eta)).max(), \
        f"inverse roundtrip err {err.max():.3e}"
    # bracket sanity at extreme nu
    assert abs(f_half_inv(f_half(40.0)) - 40.0) <= 1e-9


def test_fd_degenerate_neutrality_root():
    """G3 (physical): ni_fd solves its own neutrality identity to
    machine precision, and 300 K Si lands near the Boltzmann ni with
    the expected small FD shift."""
    from pytcad.materials import SILICON
    T = 300.0
    Nc, Nv = SILICON.Nc(T), SILICON.Nv(T)
    Eg = SILICON.Eg(T)
    ni, eta_i = ni_fd(Nc, Nv, Eg, T)
    # neutrality identity at the returned eta (machine precision)
    lhs = Nc * f_half(eta_i)
    rhs = Nv * f_half(-eta_i - Eg / (8.617333262e-5 * T))
    assert abs(lhs - rhs) / (0.5 * (lhs + rhs)) <= 1e-12, \
        "G3 FAIL: ni_fd neutrality identity violated"
    # FD ni is within a few percent of Boltzmann ni at 300 K (weakly
    # degenerate intrinsic Si), and ni^2 consistency: the product
    # Nc Nv exp(-Eg/kT) is the Boltzmann limit of (ni_fd)^2 only up
    # to the FD correction -- gate the DIRECTION and magnitude.
    ni_boltz = np.sqrt(Nc * Nv) * np.exp(-Eg / (2 * 8.617333262e-5 * T))
    ratio = ni / ni_boltz
    assert 0.95 < ratio < 1.05, \
        f"G3 FAIL: ni_fd/ni_boltzmann = {ratio:.4f} out of range"


def test_fermi_eta_range_refusal():
    """G7 applicability limit: outside [-40, 40] the module refuses
    loudly instead of extrapolating."""
    with pytest.raises(ValueError):
        f_half(41.0)
    with pytest.raises(ValueError):
        f_half(np.array([0.0, -41.0]))
    with pytest.raises(ValueError):
        f_half_inv(np.array([np.nan]))
    with pytest.raises(ValueError):
        f_half_inv(np.array([0.0]))


# ----------------------------------------------- M13 tabulated fast path
def test_tabulated_fast_path_matches_the_quadrature():
    """The interpolated f_half/f_mhalf must agree with the QUADRATURE
    they are built from, across the whole validated eta range.

    This is the gate that licenses the fast path: it is the only thing
    standing between a 1260x speedup and silently wrong carrier
    statistics.  The bound is 1e-11 -- two orders tighter than the 1e-9
    G1 gate, and the measured error is ~1e-13.
    """
    from pytcad import fermi as F

    rng = np.random.default_rng(20260827)
    eta = np.sort(np.r_[
        rng.uniform(F.FERMI_ETA_MIN, F.FERMI_ETA_MAX, 3000),
        np.linspace(F.FERMI_ETA_MIN, F.FERMI_ETA_MAX, 1001),
        # table endpoints and the series/quadrature seam
        F._SERIES_ETA, F._SERIES_ETA + 1e-12, F.FERMI_ETA_MAX,
        F.FERMI_ETA_MIN])

    fast_h, exact_h = F.f_half(eta), F.f_half_exact(eta)
    fast_m, exact_m = F.f_mhalf(eta), F.f_mhalf_exact(eta)

    rel_h = np.abs(fast_h / exact_h - 1.0).max()
    rel_m = np.abs(fast_m / exact_m - 1.0).max()
    assert rel_h <= 1e-11, f"f_half fast path off by {rel_h:.3e}"
    assert rel_m <= 1e-11, f"f_mhalf fast path off by {rel_m:.3e}"

    # Positivity and monotonicity survive interpolation: a table that
    # dipped negative would poison every density it feeds.
    assert np.all(fast_h > 0.0) and np.all(fast_m > 0.0)
    dense = np.linspace(F.FERMI_ETA_MIN, F.FERMI_ETA_MAX, 20001)
    assert np.all(np.diff(F.f_half(dense)) > 0.0), \
        "f_half must stay strictly increasing through the fast path"


def test_fast_path_preserves_scalar_and_shape_semantics():
    """Interpolation must not change the calling contract."""
    from pytcad import fermi as F

    assert np.ndim(F.f_half(0.0)) == 0 and np.ndim(F.f_mhalf(0.0)) == 0
    assert np.isscalar(float(F.f_half(1.5)))
    for shape in ((5,), (3, 4), (2, 3, 2)):
        eta = np.full(shape, -2.0)
        assert F.f_half(eta).shape == shape
        assert F.f_mhalf(eta).shape == shape
    # out-of-range still refuses loudly, table or no table
    with pytest.raises(ValueError, match="outside the validated range"):
        F.f_half(F.FERMI_ETA_MAX + 1e-6)
    with pytest.raises(ValueError, match="outside the validated range"):
        F.f_mhalf(F.FERMI_ETA_MIN - 1e-6)


def test_exact_only_env_switch_bypasses_the_table(monkeypatch):
    """PYTCAD_FERMI_EXACT=1 must give the quadrature verbatim, so a
    suspicious result can always be re-checked without the table."""
    import importlib
    from pytcad import fermi as F
    monkeypatch.setenv("PYTCAD_FERMI_EXACT", "1")
    F2 = importlib.reload(F)
    try:
        eta = np.linspace(-8.0, 30.0, 41)
        assert np.array_equal(F2.f_half(eta), F2.f_half_exact(eta))
        assert np.array_equal(F2.f_mhalf(eta), F2.f_mhalf_exact(eta))
    finally:
        monkeypatch.delenv("PYTCAD_FERMI_EXACT", raising=False)
        importlib.reload(F)


def test_non_finite_eta_is_refused_not_silently_propagated():
    """NaN fails every comparison, so the range check used to pass it
    through: f_half returned NaN silently, and the tabulated path also
    warned from an undefined NaN->int cast while indexing the table
    (breaking the suite's zero-warning invariant).  Both must raise.
    """
    from pytcad import fermi as F
    for bad in (np.nan, np.inf, -np.inf):
        with pytest.raises(ValueError):
            F.f_half(np.array([0.0, bad]))
        with pytest.raises(ValueError):
            F.f_mhalf(np.array([0.0, bad]))
        with pytest.raises(ValueError):
            F.f_half_exact(np.array([0.0, bad]))
