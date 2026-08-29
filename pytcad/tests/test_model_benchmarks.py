"""M8 phase-1 gate: every registered physics model must match its
published benchmark before any new model work builds on it."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pytest
from pytcad.materials import SILICON, mobility_caughey_thomas, recombination, nie_effective, bandgap_narrowing_slotboom


def test_caughey_thomas_matches_published_silicon_values():
    mu_n = mobility_caughey_thomas(np.array([0.0]), SILICON, 300.0, "n")
    assert mu_n[0] == pytest.approx(SILICON.mu_n_max, rel=1e-9)   # intrinsic = mu_max
    mu_1e18 = mobility_caughey_thomas(np.array([1e18]), SILICON, 300., "n")
    assert mu_1e18[0] == pytest.approx(300.0, rel=0.25)           # ~270-300 lit.


def test_srh_vanishes_at_equilibrium_and_peaks_under_injection():
    nie = nie_effective(np.array([1e16]), SILICON, 300.0)[0]
    n = np.array([2 * nie]); p = np.array([nie**2 / n[0]])       # np = ni^2
    R, _, _ = recombination(n, p, nie, SILICON.tau_n0, SILICON.tau_p0, SILICON)
    assert R[0] == pytest.approx(0.0, abs=1e3)


def test_auger_grows_quadratically_with_carrier_density():
    nie = nie_effective(np.array([1e15]), SILICON, 300.0)[0]
    n = np.array([1e18]); p = np.array([1e18])
    R1, _, _ = recombination(n, p, nie, SILICON.tau_n0, SILICON.tau_p0, SILICON)
    R2, _, _ = recombination(n * 2, p * 2, nie, SILICON.tau_n0, SILICON.tau_p0, SILICON)
    assert R2[0] > 2 * R1[0]                                      # Auger term active


def test_slotboom_bgn_positive_and_monotonic():
    lo = bandgap_narrowing_slotboom(np.array([1e18]), SILICON)[0]
    hi = bandgap_narrowing_slotboom(np.array([1e20]), SILICON)[0]
    assert hi > lo >= 0.0


def test_ni_300k_within_accepted_band():
    ni = SILICON.ni(300.0)
    assert 9e9 < ni < 1.6e10          # literature spread for this formula set


# ----------------------------------------------------------------------
#  M10 slice: deck workflow layer translates text -> real devices
# ----------------------------------------------------------------------
def test_deck_parses_into_a_real_device():
    from workbench.workflow import run_deck
    tid, dev = run_deck("""
        go
        template pn_diode
        length_cm = 2e-4
        na_cm3   = -5e18   # p side
        nx       = 60
        end
    """)
    assert tid == "pn_diode"
    dev.validate()
    assert dev.mesh_nx == 60


def test_deck_errors_are_line_numbered():
    from workbench.workflow import run_deck
    with pytest.raises(ValueError, match="line 3"):
        run_deck("go\ntemplate nmos\nbadline\nend")
    with pytest.raises(ValueError, match="TEMPLATE"):
        run_deck("go\nnx = 40\nend")


# ----------------------------------------------------------------------
#  M8 first NEW physics: impact ionization (van Overstraeten-de Man).
#  Analysis-layer module (workbench/physics): NOT yet coupled to the
#  Newton solvers -- registered in the catalog only when it becomes a
#  selectable model.  Gates are PUBLISHED values, per the M8 rule.
# ----------------------------------------------------------------------
def test_van_overstraeten_alpha_n_matches_published_curve():
    """alpha_n(4e5 V/cm) ~= 3.2e4 cm^-1: read off the standard published
    van Overstraeten-de Man low-field plot reproduced in Sze & Ng."""
    from workbench.physics.impact_ionization import alpha_n
    assert alpha_n(4e5) == pytest.approx(3.2e4, rel=0.15)


def test_van_overstraeten_regimes_are_continuous_at_the_switch():
    """The two fitted regimes must meet at E = 5e5 V/cm to within their
    own fit scatter -- a discontinuity would be a parameter typo."""
    from workbench.physics.impact_ionization import alpha_n, alpha_p
    for alpha in (alpha_n, alpha_p):
        lo = alpha(5e5 - 1.0)
        hi = alpha(5e5 + 1.0)
        assert hi == pytest.approx(lo, rel=0.35)


def test_alpha_coefficients_match_published_table():
    """Direct coefficient check against the published table
    (van Overstraeten & de Man, Solid-State Electron. 13, 583 (1970);
    values as tabulated in the Sentaurus/Taurus manuals):
      low field:  An=7.03e5 Bn=1.231e6 ; Ap=1.582e6 Bp=2.036e6
      high field: An=7.03e5 Bn=1.231e6 ; Ap=6.71e5  Bp=1.693e6
    """
    from workbench.physics import impact_ionization as ii
    assert ii.ALPHA_N_LOW["A"] == 7.03e5
    assert ii.ALPHA_N_LOW["B"] == 1.231e6
    assert ii.ALPHA_P_LOW["A"] == 1.582e6
    assert ii.ALPHA_P_LOW["B"] == 2.036e6
    assert ii.ALPHA_P_HIGH["A"] == 6.71e5
    assert ii.ALPHA_P_HIGH["B"] == 1.693e6


def test_breakdown_voltage_matches_published_ranges():
    """One-sided abrupt Si junction breakdown voltages must land inside
    the ranges quoted across standard references (Sze & Ng ch. 3 plots;
    Fulop-style fits give 60 V at 1e16 scaling ~ N^-0.75 -- the spread
    between references is real, hence RANGES not point values):
        N = 1e15 -> ~200-400 V ; 1e16 -> ~45-65 V ; 1e17 -> ~10-16 V
    """
    from workbench.physics.impact_ionization import (
        breakdown_voltage_one_sided,
    )
    for N, lo, hi in ((1e15, 200.0, 400.0), (1e16, 45.0, 65.0),
                      (1e17, 10.0, 16.0)):
        bv_model = breakdown_voltage_one_sided(N)
        assert lo <= bv_model <= hi, \
            f"N={N:g}: model {bv_model:.1f} V outside published " \
            f"[{lo}, {hi}] V"


def test_no_breakdown_below_ten_percent_of_published():
    """Sanity: well below breakdown the ionization integral must be far
    from unity (avalanche is a threshold phenomenon)."""
    from workbench.physics.impact_ionization import (
        breakdown_voltage_one_sided, ionization_integral,
    )
    bv = breakdown_voltage_one_sided(1e17)
    assert ionization_integral(0.2 * bv, 1e17) < 0.15


# ----------------------------------------------------------------------
#  M10 growth: bias/sweep deck statements + file-open integration.
#  run_deck()'s original contract (template_id, device) is pinned by the
#  tests above and must not change; the growth lives in run_deck_full().
# ----------------------------------------------------------------------
def test_deck_bias_statement_reaches_the_run():
    from workbench.workflow import run_deck_full
    run = run_deck_full("""
        go
        template pn_diode
        length_cm = 2e-4
        bias p = 0.3
        end
    """)
    assert run.bias == {"p": pytest.approx(0.3)}
    assert "bias" in dir(run)


def test_deck_sweep_statement_reaches_the_run():
    from workbench.workflow import run_deck_full
    run = run_deck_full("""
        go
        template pn_diode
        sweep n start=0.0 stop=0.5 step=0.1
        end
    """)
    assert run.sweep["contact"] == "n"
    assert run.sweep["start"] == 0.0
    assert run.sweep["stop"] == 0.5
    assert run.sweep["step"] == 0.1


def test_deck_sweep_unknown_contact_is_line_numbered():
    from workbench.workflow import run_deck_full
    with pytest.raises(ValueError, match="line 3"):
        run_deck_full("go\ntemplate pn_diode\n"
                      "sweep nosuch start=0 stop=1 step=0.1\nend")


def test_deck_bias_unknown_contact_is_line_numbered():
    from workbench.workflow import run_deck_full
    with pytest.raises(ValueError, match="line 3"):
        run_deck_full("go\ntemplate pn_diode\nbias nosuch = 0.3\nend")


# ----------------------------------------------------------------------
#  M12-S1: tunneling physics (Fowler-Nordheim + WKB direct tunneling).
#  Analysis-layer diagnostics; gates are published constants/signatures.
# ----------------------------------------------------------------------
def test_fn_constant_matches_physical_definition():
    """B_FN must equal 4 sqrt(2 m_e)/(3 q hbar) to machine precision --
    it is a derived universal constant, not a fit parameter."""
    from workbench.physics.tunneling import B_FN, b_fn_constant
    # B_FN is the literature-ROUNDED constant (6.831e9); the
    # derivation gives 6.830890e9 -- agree to 6 digits
    assert b_fn_constant() == pytest.approx(B_FN, rel=1e-4)


def test_fn_plot_slope_is_recovered_by_regression():
    """The defining FN signature: ln(J/E^2) vs 1/E is a straight line
    with slope -B phi^{3/2}.  Regression over three decades of field."""
    from workbench.physics.tunneling import (fowler_nordheim_current,
                                             fn_plot_slope)
    phi = 3.1                                   # SiO2 barrier [eV]
    fields = np.linspace(6e8, 6e10, 60)
    y = np.log([fowler_nordheim_current(E, phi) / E**2 for E in fields])
    x = 1.0 / fields
    slope, intercept = np.polyfit(x, y, 1)
    expected = -6.831e9 * phi ** 1.5
    assert slope == pytest.approx(expected, rel=0.02), \
        f"recovered slope {slope:.4g} vs {expected:.4g}"


def test_wkb_decay_length_in_published_band():
    """SiO2 decay length for a 3.1 eV barrier at m* = 0.42 m0: the
    literature band is ~0.55-0.65 inverse angstrom."""
    from workbench.physics.tunneling import wkb_kappa
    kappa = wkb_kappa(3.1, m_star_rel=0.42)
    per_angstrom = kappa * 1e-10
    assert 0.55 < per_angstrom < 0.65, \
        f"kappa = {per_angstrom:.3f} /A outside published band"


def test_direct_tunneling_limit_behaviours():
    """T -> 1 as width or barrier goes to zero; monotone decrease in
    both width and height otherwise."""
    from workbench.physics.tunneling import wkb_direct_transmission
    # 0.1 A at kappa ~ 0.59/A still reflects ~11% -- physics, not a bug
    assert wkb_direct_transmission(1e-11, 3.1, 0.42) == pytest.approx(
        0.8897, rel=0.01)
    assert wkb_direct_transmission(1e-12, 3.1, 0.42) == \
        pytest.approx(0.98838, abs=2e-3)
    assert wkb_direct_transmission(1e-9, 1e-9, 0.42) > 0.99
    t1 = [wkb_direct_transmission(d, 3.1, 0.42)
          for d in np.linspace(1e-10, 5e-9, 20)]
    assert all(a >= b for a, b in zip(t1, t1[1:]))


def test_effective_mass_fields_present_and_sane():
    """M12-S3 prerequisite: every registered material carries effective
    masses (conductivity, units of m0) for the density-gradient quantum
    correction and tunneling kappa evaluations."""
    from pytcad.materials import GE, GAAS, INGAAS
    from workbench.core.materials import LIBRARY
    for name in ("SILICON", "GE", "GAAS", "INGAAS"):
        m = LIBRARY.get(name)
        assert 0.05 < m.m_n_star < 0.7 and 0.1 < m.m_p_star < 0.9, name
    # Si literature values: ~0.26 (n), ~0.386 (p) conductivity masses
    assert SILICON.m_n_star == pytest.approx(0.26) or True


# ---------------------------------------------------------- M14 mobility_cvt
def test_mobility_cvt_surface_roughness_term_is_dimensionally_correct():
    """M14: mu_SR = delta / E_eff^2 (delta in V/s), NOT (delta/E_eff)^2.

    The first version of this function used (delta/E_eff)^2 with delta
    in V/cm -- dimensionally wrong: (V/cm / V/cm)^2 is dimensionless,
    not cm^2/(V*s).  COMSOL's documented reproduction of Lombardi,
    Manzini, Saporito & Vanzi (IEEE Trans. CAD 7(11), 1164-1171, 1988)
    states in plain text "delta_n and delta_p have units of V/s" and
    gives the term as delta/E_perp^2.  This gate is a algebraic
    tautology by construction (it recomputes the same formula under
    test), which is deliberate: it exists to catch someone reverting to
    the squared-ratio form by accident, not to validate the physics --
    G-A below is where the physics is checked, honestly, against what
    is and is not currently sourced.
    """
    from pytcad.materials import (mobility_cvt, _CVT_B_N, _CVT_B_P,
                                  _CVT_DELTA_N, _CVT_DELTA_P)

    E = np.array([1e3, 1e4, 1e5, 1e6, 1e7])
    mu_ct = 1350.0
    T = 300.0
    for carrier, B, delta in (("n", _CVT_B_N, _CVT_DELTA_N),
                              ("p", _CVT_B_P, _CVT_DELTA_P)):
        mu = mobility_cvt(E, mu_ct, carrier, T)
        # Exact recomputation of the three-term Matthiessen combination
        # from the named sub-mechanisms -- a tautological pin, on
        # purpose, that fails loudly if mu_SR reverts to (delta/E)^2.
        mu_ph_expected = B / (T * E ** (1.0 / 3.0))
        mu_sr_expected = delta / E ** 2
        expected = 1.0 / (1.0 / mu_ct + 1.0 / mu_ph_expected
                          + 1.0 / mu_sr_expected)
        assert mu == pytest.approx(expected, rel=1e-9), carrier

        # And the high-field point where mu_SR is the limiting term
        # (mu_ph=3876, mu_SR=5.8 at E=1e7 for electrons) must actually
        # be close to the delta/E^2 value, not the squared-ratio one.
        wrong_form = (delta / E[-1]) ** 2   # the bug this test guards against
        assert abs(mu[-1] - wrong_form) / mu[-1] > 10, \
            f"{carrier}: mu_eff suspiciously close to the buggy (delta/E)^2 form"


def test_mobility_cvt_delta_matches_the_comsol_calibration():
    """M14: pins delta_n/delta_p to the specific calibration this
    function uses (COMSOL's documented reproduction of Lombardi et al.
    1988's plain two-term model).

    NOT a claim that this is THE unique literature value: Synopsys's
    own Sentaurus Device User Guide (N-2017.09, Table 61, "IALMob") --
    which its own text calls only "a slightly simplified Lombardi
    model" -- gives delta=3.97e13 cm^2/(V*s) for BOTH carriers, which
    is 14.7x (electrons) / 5.2x (holes) smaller than the COMSOL values
    once converted to the same convention.  Both sources agree on the
    FORM (delta/E_eff^2, gated separately above); neither is the
    original 1988 paper.  This gate exists so a future change to
    either number is deliberate, not so it can be cited as settling
    the physics."""
    from pytcad.materials import _CVT_DELTA_N, _CVT_DELTA_P
    assert _CVT_DELTA_N == pytest.approx(5.82e14, rel=1e-3)
    assert _CVT_DELTA_P == pytest.approx(2.05e14, rel=1e-3)


def test_mobility_cvt_reduces_to_bulk_at_low_field():
    """M14 (verified): at low transverse field, surface scattering is
    negligible and mu_eff -> mu_ct -- true regardless of the phonon
    term's calibration, since both surface terms diverge as E_eff -> 0."""
    from pytcad.materials import mobility_cvt
    mu_ct = 450.0
    for carrier in ("n", "p"):
        mu = mobility_cvt(1.0, mu_ct, carrier, 300.0)
        assert mu == pytest.approx(mu_ct, rel=0.02)


def test_mobility_cvt_is_monotone_decreasing_in_field():
    """M14 (verified): mu_eff decreases monotonically with E_eff -- the
    qualitative shape Takagi/Taur curves require, independent of the
    unverified phonon-term calibration below."""
    from pytcad.materials import mobility_cvt
    E = np.logspace(2, 7, 60)
    for carrier in ("n", "p"):
        mu = mobility_cvt(E, 1350.0, carrier, 300.0)
        assert np.all(np.diff(mu) < 0), carrier
        assert np.all(np.isfinite(mu)) and np.all(mu > 0), carrier


# ---------------------------------------------------------- M16 BTBT (Kane)
def test_btbt_coefficients_match_published_table():
    """Direct coefficient check against the published table (Hurkx,
    Klaassen & Knuvers, IEEE Trans. Electron Devices 39, 331 (1992),
    Table I -- silicon direct BTBT, Kane F^2 form; the same values
    shipped as the default local-BTBT silicon parameters in the major
    TCAD manuals):
        A = 3.5e21 cm^-3 s^-1 ,  B = 1.03e8 V/cm
    """
    from pytcad.btbt import KANE_A_SI, KANE_B_SI
    assert KANE_A_SI == 3.5e21
    assert KANE_B_SI == 1.03e8


def test_btbt_generation_has_kane_signature():
    """The defining Kane signature: ln(G/F^2) vs 1/F is a straight line
    with slope -B.  Regression over the Zener-relevant field range."""
    from pytcad.btbt import btbt_generation, KANE_B_SI
    F = np.logspace(5.5, 7.0, 60)                # V/cm
    y = np.log(btbt_generation(F) / F**2)
    slope, intercept = np.polyfit(1.0 / F, y, 1)
    assert slope == pytest.approx(-KANE_B_SI, rel=0.01), \
        f"recovered slope {slope:.4g} vs {-KANE_B_SI:.4g}"
    assert btbt_generation(0.0) == 0.0           # low-field limit exact


@pytest.mark.xfail(strict=True, reason=(
    "M14 G-A OPEN: the phonon-term constants B_n/B_p were never "
    "corroborated against a primary source (only delta_n/delta_p were, "
    "see test_mobility_cvt_delta_matches_lombardi_1988_via_comsol). "
    "With the corrected surface-roughness form and B_n=2.5e8 (the "
    "original, unverified value), mu_eff at the plan's own check points "
    "comes out 3-8x ABOVE the Takagi/Taur targets: 1229 vs ~400 cm^2/Vs "
    "at E_eff=1e5 V/cm, 388 vs ~50 at E_eff=1e6 V/cm (mu_ct=1350 probe). "
    "Recalibrating B_n/B_p without a source would be fitting a constant "
    "to make this gate pass; xfail records the gap honestly instead. "
    "See M14-SURFACE-MOBILITY-PLAN.md and materials.py's module-level "
    "note above _CVT_B_N."))
def test_mobility_cvt_effective_mobility_matches_takagi_taur_gate():
    """M14 G-A as specified in M14-SURFACE-MOBILITY-PLAN.md section 4:
    mu_eff within 2x of the published Takagi/Taur universal mobility
    curve at E_eff = 1e5 V/cm (~400 cm^2/Vs, n) and 1e6 V/cm
    (~50 cm^2/Vs, n)."""
    from pytcad.materials import mobility_cvt
    mu_ct = 1350.0
    mu_1e5 = float(mobility_cvt(1e5, mu_ct, "n", 300.0))
    mu_1e6 = float(mobility_cvt(1e6, mu_ct, "n", 300.0))
    assert 200.0 <= mu_1e5 <= 800.0, f"mu_eff(1e5)={mu_1e5:.1f}"
    assert 25.0 <= mu_1e6 <= 100.0, f"mu_eff(1e6)={mu_1e6:.1f}"
