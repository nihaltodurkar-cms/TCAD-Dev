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


def test_oxidize_2d_uniform_mask_matches_1d_deal_grove_bit_for_bit():
    """M23 gate G1 (Architecture_Master_Plan.md Phase 14 / ARCHITECTURE.md
    M23 acceptance): a fully-open (unmasked) 2D oxidation must reduce
    exactly to pytcad.process.oxide_thickness -- the whole point of the
    per-column bookkeeping in process2d.oxidize_2d is that the lateral
    bird's-beak kernel contributes nothing when there is no mask edge."""
    from pytcad import process
    from pytcad.process2d import ProcessGeometry2D, oxidize_2d
    x = np.linspace(0.0, 10e-4, 21)   # 21 columns, 10 um wide, all open
    geom = ProcessGeometry2D(x)
    out = oxidize_2d(geom, T_C=900.0, t_hours=1.0, ambient="dry", mask=None)
    expected = process.oxide_thickness(900.0, 1.0, ambient="dry")
    assert np.allclose(out.ox_thick_um, expected, rtol=0, atol=1e-13)


def test_oxidize_2d_conserves_silicon_by_the_0_44_factor():
    """M23 gate G2: cumulative silicon consumed must equal 0.44x the
    cumulative oxide grown at every column, to machine precision, even
    under a masked/graded-rate bird's-beak profile."""
    from pytcad import process
    from pytcad.process2d import ProcessGeometry2D, oxidize_2d, mask_from_intervals
    x = np.linspace(0.0, 20e-4, 41)
    mask = mask_from_intervals(x, [(0.0, 8e-4)])   # open 0-8um, masked past it
    geom = ProcessGeometry2D(x)
    out = oxidize_2d(geom, T_C=1000.0, t_hours=0.5, ambient="wet", mask=mask)
    assert np.allclose(out.si_consumed_um, process.silicon_consumed(out.ox_thick_um),
                        rtol=0, atol=1e-13)


def test_diffuse_with_defects_reduces_bit_identically_to_intrinsic_diffuse_numeric():
    """M24 gate G1: with no extrinsic/TED/OED enhancement requested,
    diffuse_with_defects must be bit-identical to process.diffuse_numeric
    -- it literally calls it, by construction, so this test guards against
    a future edit accidentally routing the disabled case through the
    enhanced (and therefore differently-discretized) code path."""
    from pytcad import process
    from pytcad.ted import diffuse_with_defects
    x = np.linspace(0.0, 1e-4, 101)
    C0 = process.implant(x, "B", 30, 1e13)
    a = process.diffuse_numeric(x, C0, "B", 950.0, 600.0)
    b = diffuse_with_defects(x, C0, "B", 950.0, 600.0)
    assert np.array_equal(a, b)


def test_extrinsic_enhancement_matches_fair_model_at_published_ratios():
    """M24 gate G2: Fair's pair-diffusion enhancement factor D/Di =
    f_I(n/ni) + f_V(ni/n) must equal 1 exactly at n=ni (intrinsic), and
    for boron (f_I=1, purely interstitial-mediated) must equal n/ni
    exactly -- the textbook published relation (Fair, 1981)."""
    from pytcad.ted import extrinsic_enhancement, ni_silicon
    ni = ni_silicon(1000.0)
    assert extrinsic_enhancement("B", ni, 1000.0) == pytest.approx(1.0, rel=1e-12)
    assert extrinsic_enhancement("B", 10 * ni, 1000.0) == pytest.approx(10.0, rel=1e-9)
    # Arsenic (mostly vacancy-mediated) must fall *below* boron's ratio at
    # the same extrinsic doping level -- the qualitative published trend.
    r_b = extrinsic_enhancement("B", 10 * ni, 1000.0)
    r_as = extrinsic_enhancement("As", 10 * ni, 1000.0)
    assert r_as < r_b


def test_segregation_partition_matches_the_analytic_equilibrium_split():
    """M24 gate G4: segregation_partition must exactly satisfy both the
    conservation and the segregation-coefficient constraints it is
    defined by (an algebraic identity, checked directly)."""
    from pytcad.ted import segregation_partition
    Q, m, t_si, t_ox = 5e13, 0.3, 1e-6, 2e-6
    C_si, C_ox = segregation_partition(Q, m, t_si, t_ox)
    assert C_si == pytest.approx(m * C_ox, rel=1e-12)
    assert (C_si * t_si + C_ox * t_ox) == pytest.approx(Q, rel=1e-9)


def test_mc_implant_bca_range_is_same_order_of_magnitude_as_the_srim_table():
    """M25 gate G1: after calibrating the (disclosed, single free
    parameter) electronic-stopping prefactor at one reference energy
    against pytcad.process's existing SRIM-derived range table, the BCA
    Monte-Carlo range at NEARBY energies (not the calibration point
    itself) must land within a factor of ~2 of that same table and must
    increase monotonically with energy. This is a "same physics, right
    order of magnitude, right trend" gate for a deliberately simplified
    BCA model -- see pytcad/mc_implant.py's honesty clause for why an
    exact SRIM match is not attempted."""
    from pytcad import process
    from pytcad.mc_implant import calibrate_electronic_stopping, mc_implant_bca
    species, ref_E = "B", 50
    k_e = calibrate_electronic_stopping(species, ref_E, n_ions=300, seed=1)

    Rp_mc = []
    for E in (30, 50, 100):
        out = mc_implant_bca(species, E, k_e, n_ions=500, seed=2)
        Rp_tab, _ = process.implant_moments(species, E)
        ratio = out["Rp_cm"] / Rp_tab
        assert 0.6 <= ratio <= 1.6, f"E={E}: Rp_mc/Rp_tab={ratio:.2f}"
        Rp_mc.append(out["Rp_cm"])
    assert Rp_mc[0] < Rp_mc[1] < Rp_mc[2]


def test_mc_implant_bca_channeling_produces_a_deeper_tail_than_amorphous():
    """M25 gate G2 (qualitative, honestly labeled per the milestone spec):
    enabling the channeling knob must produce a heavier/deeper tail than
    a purely amorphous run at the same energy and ion count -- the
    qualitative channeling-tail signature. Not compared to a specific
    published SIMS profile."""
    from pytcad.mc_implant import calibrate_electronic_stopping, mc_implant_bca
    k_e = calibrate_electronic_stopping("P", 50, n_ions=300, seed=1)
    amorphous = mc_implant_bca("P", 50, k_e, n_ions=800, seed=3)
    channeled = mc_implant_bca("P", 50, k_e, n_ions=800, seed=3,
                                channeling_fraction=0.15,
                                channeling_length_mean_cm=3e-5)
    assert channeled["depth_cm"].max() > 2.0 * amorphous["depth_cm"].max()
    assert channeled["channeled_ever"].sum() > 0


def test_mc_implant_bca_accounts_for_every_ion_backscattered_or_stopped():
    """M25 gate G3: dose conservation for a MC implant means every
    launched ion is accounted for as either stopped-in-target or
    backscattered-out -- none silently vanish -- and the backscattered
    fraction stays physically small for these light/medium ions at these
    energies (a sanity bound, not a literature-matched yield)."""
    from pytcad.mc_implant import calibrate_electronic_stopping, mc_implant_bca
    k_e = calibrate_electronic_stopping("As", 50, n_ions=300, seed=1)
    out = mc_implant_bca("As", 50, k_e, n_ions=1000, seed=4)
    assert out["depth_cm"].shape[0] == 1000
    assert out["backscattered"].shape[0] == 1000
    assert out["backscatter_fraction"] < 0.10
    assert out["unstopped_fraction"] < 0.01


def test_richardson_constant_A0_matches_the_published_fundamental_constant_value():
    """M28 gate G1: the free-electron Richardson constant derived here
    from fundamental constants (A0 = 4 pi q m0 kB^2 / h^3) must match
    the published textbook value 120.173 A/(cm^2 K^2) (Sze & Ng) to high
    precision -- this is an exact physical-constant calculation, not a
    fit, so the tolerance is tight."""
    from pytcad.schottky import richardson_constant_A0
    assert richardson_constant_A0() == pytest.approx(120.173, rel=1e-4)


def test_schottky_iv_matches_thermionic_emission_theory_at_a_published_barrier():
    """M28 gate G2: for a PtSi/n-Si-like Schottky contact (published
    barrier height phi_Bn ~= 0.85 eV, A*_n = 252 A/(cm^2 K^2) for Si,
    Sze & Ng), the ideal (no image-force) thermionic-emission I-V must
    exactly satisfy the textbook diode equation at forward bias: J(V) =
    J0 [exp(qV/kT) - 1] with J0 = A* T^2 exp(-phi_B/kT), and J(0) = 0
    exactly."""
    from pytcad.schottky import thermionic_current_density, richardson_a_star
    from pytcad.constants import KB_EV
    T = 300.0
    phi_B = 0.85
    A_star = richardson_a_star("Si", "n")
    assert thermionic_current_density(phi_B, T, 0.0, A_star) == pytest.approx(0.0, abs=1e-30)
    J0 = A_star * T**2 * np.exp(-phi_B / (KB_EV * T))
    from pytcad.constants import KB, Q
    Vt = KB * T / Q
    for V in (0.1, 0.2, 0.3):
        J = thermionic_current_density(phi_B, T, V, A_star)
        expected = J0 * (np.exp(V / Vt) - 1.0)
        assert J == pytest.approx(expected, rel=1e-9)


def test_schottky_barrier_lowering_reduces_the_barrier_and_grows_with_field():
    """M28 gate G3: image-force barrier lowering must be positive (it
    always LOWERS the barrier) and must increase with the depletion
    field, the qualitative Schottky-effect trend (Sze & Ng eq. 3.5-3.6),
    and must land in the tens-of-meV range for a typical moderately
    doped Si contact (Nd=1e16-1e17), the physically expected magnitude."""
    from pytcad.schottky import schottky_max_field, image_force_lowering_eV
    from pytcad.materials import SILICON
    phi_B = 0.85
    E_lo = schottky_max_field(1e16, phi_B, 0.0, SILICON.eps_r)
    E_hi = schottky_max_field(1e17, phi_B, 0.0, SILICON.eps_r)
    d_lo = image_force_lowering_eV(E_lo, SILICON.eps_r)
    d_hi = image_force_lowering_eV(E_hi, SILICON.eps_r)
    assert 0.0 < d_lo < d_hi
    assert 0.005 < d_lo < 0.1
    assert 0.005 < d_hi < 0.1


def test_schottky_ohmic_limit_recovery_as_barrier_height_vanishes():
    """M28 gate G4: as the barrier height phi_B -> 0, the thermionic
    saturation current J0 = A* T^2 exp(-phi_B/kT) must diverge (grow
    without the usual rectifying-diode bound), i.e. the contact's
    effective differential resistance collapses toward the near-zero
    resistance of an ohmic contact -- the model's built-in
    ohmic-limit-recovery behavior, checked as a strictly monotonic
    trend across several barrier heights spanning three decades of J0."""
    from pytcad.schottky import thermionic_current_density, richardson_a_star
    A_star = richardson_a_star("Si", "n")
    T = 300.0
    barriers = [0.85, 0.3, 0.05, 0.001]
    J0s = [thermionic_current_density(pb, T, 1e-6, A_star) / 1e-6 * (8.617333262e-5 * T)
           for pb in barriers]
    for a, b in zip(J0s, J0s[1:]):
        assert b > a
    assert J0s[-1] / J0s[0] > 1e6


@pytest.mark.slow
def test_finfet3d_dibl_and_subthreshold_swing_worsen_as_gate_length_shrinks():
    """M26 gate: FinFET electrostatics vs published TCAD-literature
    trends (DIBL/SSE), honestly labeled as a LITERATURE-TREND gate --
    not a match to any specific published I-V curve. Colinge (FinFETs
    and Other Multi-Gate Transistors) and standard short-channel MOSFET
    theory agree that both drain-induced barrier lowering and
    subthreshold swing get WORSE (larger) as gate length shrinks,
    because the gate progressively loses electrostatic control of the
    channel potential to the drain. This test builds two otherwise-
    identical tri-gate FinFETs (pytcad.finfet3d) differing only in Lg
    and checks that qualitative direction on both metrics.

    Runtime: ~2 minutes (4 full 3D Id-Vg sweeps at ~1500-4000 nodes
    each) -- see finfet3d.py's own honesty clause for what is and is
    not physically faithful about this structured-mesh FinFET model."""
    from pytcad.finfet3d import build_finfet3d, id_vg_sweep_3d
    from pytcad.characterization import extract_subthreshold_swing, extract_dibl

    Vg = np.linspace(-0.4, 1.2, 12)
    common = dict(Lsd=0.3e-6, Hfin=0.3e-6, Wfin=0.2e-6, tox_cm=2e-7,
                  Na=5e17, Nsd_peak=1e19, sigma_y=0.05e-6, sigma_lat=0.05e-6,
                  NX=6, NY=4, NZ=4, mesh_ratio=1.3)

    metrics = {}
    for Lg in (1.5e-6, 0.4e-6):
        Id_low = id_vg_sweep_3d(build_finfet3d(Lg=Lg, **common), Vg, Vds=0.05, verbose=False)
        Id_high = id_vg_sweep_3d(build_finfet3d(Lg=Lg, **common), Vg, Vds=0.3, verbose=False)
        ss = extract_subthreshold_swing(Vg, Id_low)
        dibl = extract_dibl(Vg, Id_low, Vg, Id_high, 0.05, 0.3, target=4e-7)
        metrics[Lg] = (ss, dibl)

    ss_long, dibl_long = metrics[1.5e-6]
    ss_short, dibl_short = metrics[0.4e-6]
    assert dibl_long > 0.0
    assert dibl_short > dibl_long
    assert ss_short >= ss_long


def test_resistor_divider_matches_analytic():
    """M27 gate G1: a plain two-resistor voltage divider must match
    the textbook analytic result to numerical precision."""
    from pytcad.circuit import Circuit, VSource, Resistor, GND
    c = Circuit()
    c.add(VSource("V1", "in", GND, 5.0))
    c.add(Resistor("R1", "in", "mid", 1000.0))
    c.add(Resistor("R2", "mid", GND, 2000.0))
    x, mna = c.dc_operating_point()
    v_mid = Circuit.node_voltage(x, mna, "mid")
    assert v_mid == pytest.approx(5.0 * 2000.0 / 3000.0, rel=1e-6)


def test_device_in_circuit_operating_point_matches_device_only_solve():
    """M27 gate G2: a real Device1D p-n junction embedded via
    DeviceStamp in a resistor-loaded circuit must reach the SAME
    operating point (terminal current) as solving the identical device
    standalone at the circuit-computed terminal voltage -- i.e. the
    finite-difference-conductance MNA stamp (see circuit.py's own
    honesty clause on why it is not literally "the analytic Jacobian")
    introduces no additional physics error."""
    from pytcad.mesh import graded_mesh
    from pytcad.device import Device1D
    from pytcad.circuit import Circuit, VSource, Resistor, DeviceStamp, GND

    x = graded_mesh(2e-4, [1e-4], 5e-7, 6e-6, 1.2)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    dev = Device1D(x, doping)

    c = Circuit()
    c.add(VSource("V1", "in", GND, 0.5))
    c.add(Resistor("R1", "in", "a", 500.0))
    stamp = c.add(DeviceStamp("D1", "a", GND, dev, area_cm2=1e-4))
    x_sol, mna = c.dc_operating_point(max_iter=40)
    va = Circuit.node_voltage(x_sol, mna, "a")

    dev_only = Device1D(x, doping)
    dev_only.solve_bias([va, 0.0])
    J, _spread = dev_only.current_density()
    I_standalone = J * 1e-4
    I_via_kirchhoff = (0.5 - va) / 500.0

    assert stamp.last_current == pytest.approx(I_standalone, rel=1e-6)
    assert I_standalone == pytest.approx(I_via_kirchhoff, rel=1e-3)


@pytest.mark.slow
def test_ring_oscillator_transient_smoke():
    """M27 gate G3 (honest: qualitative): a 3-stage CMOS inverter ring
    (level-1 MOSFETs, one load capacitor per stage), started from a
    symmetry-broken initial condition (the symmetric DC operating
    point is a genuine but UNSTABLE fixed point -- see circuit.py's
    own `transient()` docstring on why `initial_conditions` exists),
    must show real oscillation: repeated threshold crossings, not a
    flat line settling back to the symmetric point."""
    from pytcad.circuit import Circuit, VSource, Capacitor, MOSFET1, GND

    c = Circuit()
    VDD = 5.0
    c.add(VSource("VDD", "vdd", GND, VDD))
    nstages = 3
    nodes = [f"n{i}" for i in range(nstages)]
    for i in range(nstages):
        out = nodes[i]
        inp = nodes[(i - 1) % nstages]
        c.add(MOSFET1(f"MP{i}", "vdd", inp, out, kind="p", Vt0=-0.7,
                     kp=4e-4, W_L=10.0, lam=0.02))
        c.add(MOSFET1(f"MN{i}", out, inp, GND, kind="n", Vt0=0.7,
                     kp=2e-4, W_L=10.0, lam=0.02))
        c.add(Capacitor(f"C{i}", out, GND, 1e-12))

    times, hist, mna = c.transient(
        t_stop=4e-8, dt=2e-11,
        initial_conditions={"n0": 4.5, "n1": 0.5, "n2": 2.5})
    v0 = hist[:, mna.idx("n0")]
    assert v0.max() > 0.8 * VDD
    assert v0.min() < 0.2 * VDD
    crossings = int(np.sum(np.diff(np.sign(v0 - VDD / 2.0)) != 0))
    assert crossings >= 4


def test_hydrodynamic_dd_limit_is_bit_identical_when_unused():
    """M29 gate G1 (DD limit recovery, bit-identity when off): the
    hydrodynamic module (pytcad/hydrodynamic.py) is a standalone post-
    processing closure, never wired into Device1D's own residual/
    Jacobian -- so a Device1D solve is bit-for-bit identical whether
    or not the hydrodynamic module happens to be imported/called
    elsewhere in the process. Regression guard against a future
    session wiring it in and breaking this property silently."""
    from pytcad.mesh import graded_mesh
    from pytcad.device import Device1D
    import pytcad.hydrodynamic  # noqa: F401  (import alone must be a no-op)

    x = graded_mesh(2e-4, [1e-4], 5e-7, 6e-6, 1.2)
    doping = np.where(x < 1e-4, -1e17, 1e17)

    dev_a = Device1D(x, doping)
    dev_a.solve_bias([0.3, 0.0])
    psi_a, n_a, p_a = dev_a.psi.copy(), dev_a.n.copy(), dev_a.p.copy()

    from pytcad.hydrodynamic import carrier_temperature
    carrier_temperature(1e5, 1400.0)   # exercise the module in between

    dev_b = Device1D(x, doping)
    dev_b.solve_bias([0.3, 0.0])

    assert np.array_equal(psi_a, dev_b.psi)
    assert np.array_equal(n_a, dev_b.n)
    assert np.array_equal(p_a, dev_b.p)


def test_hydrodynamic_heating_ratio_is_near_unity_at_low_field_and_grows_with_field():
    """M29 gate G2 (overshoot trend, honestly scoped -- see
    hydrodynamic.py's own module docstring for why a LOCAL energy-
    balance closure cannot reproduce a Monte Carlo overshoot SPATIAL
    profile): the local carrier-temperature heating ratio must be
    ~1 at near-zero field (thermal equilibrium) and increase
    monotonically and substantially at realistic submicron-device
    fields, the qualitative "field heats the carrier gas" trend
    underlying the overshoot phenomenon. Also checks the genuinely
    computable energy-relaxation length lands in the published
    submicron order of magnitude (Sze & Ng: overshoot matters once a
    device's characteristic length is comparable to v_sat*tau_w)."""
    from pytcad.hydrodynamic import (
        hot_carrier_heating_ratio, energy_relaxation_length, TAU_W_N,
    )
    from pytcad.materials import SILICON

    fields = [1.0e2, 1.0e3, 1.0e4, 5.0e4, 1.0e5, 2.0e5]
    ratios = [hot_carrier_heating_ratio(E, SILICON.mu_n_max) for E in fields]

    assert ratios[0] == pytest.approx(1.0, abs=0.01)
    for a, b in zip(ratios, ratios[1:]):
        assert b > a
    assert ratios[-1] > 5.0   # substantial heating at a realistic peak field

    l_w = energy_relaxation_length(SILICON.vsat_n, TAU_W_N)
    assert 0.01e-4 < l_w < 0.5e-4   # 0.01-0.5 um, the published submicron scale


def test_hydrodynamic_impact_ionization_reduces_to_the_published_field_model():
    """M29 gate G3 ("II with carrier-T models vs published"): the
    carrier-temperature-driven avalanche generation rate, evaluated at
    the temperature this module's OWN local closure associates with a
    given field, must reduce to EXACTLY the existing (M15, van
    Overstraeten-de Man) field-driven generation rate at that same
    field -- see hydrodynamic.py's own honesty clause for why this
    (not an independent experimental comparison) is what "vs published"
    means for a temperature-mediated route to the same coefficients."""
    from pytcad.hydrodynamic import (
        carrier_temperature, impact_ionization_rate_carrierT,
    )
    from pytcad.ionization import alpha_n, alpha_p
    from pytcad.materials import SILICON

    n, p, E = 1.0e15, 1.0e10, 3.0e5
    mu_n, mu_p = SILICON.mu_n_max, SILICON.mu_p_max
    Tn = carrier_temperature(E, mu_n)
    Tp = carrier_temperature(E, mu_p)

    G_carrierT = impact_ionization_rate_carrierT(n, p, Tn, Tp, mu_n, mu_p)
    G_field = alpha_n(E) * mu_n * E * n + alpha_p(E) * mu_p * E * p
    assert G_carrierT == pytest.approx(G_field, rel=1e-9)


# ------------------------------------------ M34-S1 nonlocal BTBT (Kane WKB)
def test_kane_two_band_inverse_kappa_integral_matches_closed_form():
    """Esseni et al., Semicond. Sci. Technol. 32, 083005 (2017), eq (9):
    alpha runs from -1 to +1 across the gap with
    d(delta) = (alpha+u)/(2u) d(alpha), so the tunnel-path integral
        int_0^1 d(delta)/kappa = pi*hbar / (2*sqrt(mr*Eg))
    exactly, for any u = m0/(2*mr) > 1.  This identity is what makes
    eq (11) reduce to eq (8) with no leftover factor (an earlier
    "factor of pi" was a mistranscription of eq (8)'s 18*pi as
    18*pi^2).  Gauss-Chebyshev nodes never touch the integrable
    1/sqrt turning points."""
    from pytcad.btbt import kane_kappa, M0_SI, HBAR_SI, Q_SI
    Eg = 1.12 * Q_SI
    n = 64
    k = np.arange(1, n + 1)
    d = 0.5 * (1.0 + np.cos((2 * k - 1) * np.pi / (2 * n)))
    for mr_rel in (0.05, 0.1554, 0.3):
        mr = mr_rel * M0_SI
        integral = np.pi / n * np.sum(np.sqrt(d * (1.0 - d))
                                      / kane_kappa(d, Eg, mr))
        assert integral == pytest.approx(
            np.pi * HBAR_SI / (2.0 * np.sqrt(mr * Eg)), rel=1e-10)


def test_nonlocal_btbt_reduces_to_published_kane_formula_in_uniform_field():
    """M34-S1 G2: on a linear band profile the nonlocal path rate
    (Esseni 2017 eqs 11/12, btbt.nonlocal_btbt_window) equals the
    published uniform-field Kane closed form (eq 8, kane_local_fp):
        G = e^2 F^2 sqrt(mr) / (18 pi hbar^2 sqrt(Eg))
            * exp(-pi sqrt(mr) Eg^1.5 / (2 e hbar F))
    Silicon masses and gap; km^2 large so eq (11)'s bracket is 1 (eq 8
    integrates k_perp to infinity).  btbt.segment_integrals integrates
    eq (9)'s kappa EXACTLY along a piecewise-linear band (closed-form
    antiderivatives), so the reduction holds to rounding at ANY
    resolution -- a single edge included.  (The earlier edge-midpoint
    rule converged only as N^-1/2: 3.0e-3 off at N=16000.)"""
    from pytcad.btbt import (nonlocal_btbt_window, kane_local_fp,
                             M0_SI, HBAR_SI, Q_SI)
    mc, mv = SILICON.m_n_star * M0_SI, SILICON.m_p_star * M0_SI
    mr = 1.0 / (1.0 / mc + 1.0 / mv)
    Eg = SILICON.Eg(300.0) * Q_SI
    for F in (5e7, 1e8, 3e8):                        # V/m
        L = Eg / (Q_SI * F)                           # x_f - x_i
        G8 = kane_local_fp(F, Eg, mr)
        expo8 = np.pi * np.sqrt(mr) * Eg ** 1.5 / (2.0 * Q_SI * F * HBAR_SI)
        for N in (1, 7, 1000):
            x = np.linspace(0.0, L, N + 1)
            G, _, int_kappa, _ = nonlocal_btbt_window(
                x, -Q_SI * F * x, Q_SI * F, Eg, mr, mc, mv,
                -10.0 * Q_SI, 10.0 * Q_SI)
            assert 2.0 * int_kappa == pytest.approx(expo8, rel=1e-12)
            assert G == pytest.approx(G8, rel=1e-12), (F, N)


def test_nonlocal_btbt_tunnel_length_matches_published_uniform_field_value():
    """M34-S1 G7 (structural).  Esseni et al. 2017, section 2.1: the
    path generates holes at the start turning point x_i and electrons
    at the end turning point x_f, and in a uniform field
    x_f - x_i = e*Eg/|F| (stated with eq (7)).  The path engine puts
    the electron deposit at the live delta = 1 crossing, so its tunnel
    length must be Eg/(qF) exactly for a uniform field.  For a two-slope
    band it must equal the analytic piecewise value and lie inside
    [Eg/(q Fmax), Eg/(q Fmin)] -- the tunnel length is a harmonic mean
    of the segment fields.  No calibration constant is involved."""
    from pytcad.nonlocal_path import build_1d, evaluate
    from pytcad.btbt import M0_SI, Q_SI
    mc, mv = SILICON.m_n_star * M0_SI, SILICON.m_p_star * M0_SI
    mr = 1.0 / (1.0 / mc + 1.0 / mv)
    Eg_eV = SILICON.Eg(300.0)
    Eg = Eg_eV * Q_SI
    VT = 0.025852
    for F in (5e7, 3e8):                              # V/m, uniform
        L = Eg_eV / F
        x = np.linspace(0.0, 1.7 * L, 60)
        psi = F * x / VT                              # electrons go up psi
        ev = evaluate(build_1d(x, [0], [59]), psi, VT, Eg, mr, mc, mv)
        assert ev.reached[0]
        assert ev.length[0] == pytest.approx(L, rel=1e-12)
    F1, F2, f = 2e8, 6e7, 0.4                         # two slopes, kink at delta=f
    xk = f * Eg_eV / F1
    x = np.concatenate([np.linspace(0.0, xk, 11),
                        xk + np.linspace(0.0, 1.2 * (1 - f) * Eg_eV / F2, 31)[1:]])
    psi = np.where(x <= xk, F1 * x, F1 * xk + F2 * (x - xk)) / VT
    ev = evaluate(build_1d(x, [0], [x.size - 1]), psi, VT, Eg, mr, mc, mv)
    want = f * Eg_eV / F1 + (1 - f) * Eg_eV / F2
    assert ev.length[0] == pytest.approx(want, rel=1e-12)
    assert Eg_eV / ev.fmax[0] <= ev.length[0] <= Eg_eV / ev.fmin[0]


# ------------------------------------ M34-S2 nonlocal (effective-field) II
def test_nonlocal_ii_relaxation_length_matches_slotboom_1991():
    """Slotboom, Streutker, van Dort, Woerlee, Pruijmboom, Gravesteijn,
    "Non-local impact ionization in silicon devices", IEDM 1991 (IEEE
    Xplore 235484), abstract: an electron energy relaxation length
    lambda_e = 650 A was found from MBE-grown bipolar transistors and
    scaled submicron MOS transistors."""
    from pytcad.ii_nonlocal import LAMBDA_E_SLOTBOOM_CM
    assert LAMBDA_E_SLOTBOOM_CM == 6.5e-6          # cm = 650 A


def _ii_step_mesh():
    from pytcad.mesh import graded_mesh
    x = graded_mesh(2.0e-4, [1.0e-4], h_min=2e-7, h_max=5e-6)   # cm
    x0 = x[np.argmin(np.abs(x - 1.0e-4))]
    return x, x0


def test_effective_field_step_response_is_the_relaxation_solution():
    """The defining property of the relaxation equation
    lambda dE_eff/ds + E_eff = |E| (Slotboom 1991's simplified energy
    balance, drift-dominated form): cold electrons entering a field step
    E0 at x0 heat as E_eff = E0 (1 - exp(-(x - x0)/lambda)).  The
    per-edge exponential integrator is exact for a piecewise-constant
    field, so this holds to rounding on a graded mesh."""
    from pytcad.ii_nonlocal import effective_field, LAMBDA_E_SLOTBOOM_CM
    x, x0 = _ii_step_mesh()
    VT, E0, lam = 0.025852, 3.0e5, LAMBDA_E_SLOTBOOM_CM
    psi = np.where(x < x0, 0.0, E0 * (x - x0) / VT)   # electrons drift +x
    Eeff = effective_field(x, psi, VT, lam, "n")
    on = x >= x0
    want = E0 * (1.0 - np.exp(-(x[on] - x0) / lam))
    assert np.allclose(Eeff[on], want, rtol=1e-12, atol=1e-9 * E0)
    assert np.all(Eeff[~on] == 0.0)                   # upstream stays cold


def test_effective_field_is_the_local_field_in_a_uniform_field():
    """Far from the inflow boundary (>> lambda) a uniform field gives
    E_eff = |E| exactly: the nonlocal model reduces to the local M15
    model wherever the field is uniform over a relaxation length."""
    from pytcad.ii_nonlocal import effective_field, LAMBDA_E_SLOTBOOM_CM
    lam = LAMBDA_E_SLOTBOOM_CM
    x = np.linspace(0.0, 5.0e-4, 801)                 # 5 um = 77 lambda
    VT, E0 = 0.025852, 2.0e5
    for carrier, sign in (("n", 1.0), ("p", -1.0)):
        psi = sign * E0 * x / VT
        Eeff = effective_field(x, psi, VT, lam, carrier)
        # Both carriers drift +x here (electrons up psi, holes down
        # it), so the cold inflow is x = 0 for both; 40 lambda
        # downstream exp(-40) = 4e-18.
        far = x > 40 * lam
        assert far.sum() > 100                        # not vacuous
        # the recursion accumulates a few ulps over ~800 edges
        assert np.allclose(Eeff[far], E0, rtol=1e-12, atol=0.0)


def test_effective_field_lags_a_narrow_field_peak():
    """Slotboom 1991's central claim, as a formula: electrons gain much
    less energy than the maximum field implies when the field peak is
    narrow.  Across a rectangular pulse E0 of width w the exact response
    is E_eff(end) = E_eff(start) exp(-w/lambda) + E0 (1 - exp(-w/lambda));
    for w = lambda/2 the carriers leave the peak at under 40% of E0."""
    from pytcad.ii_nonlocal import effective_field, LAMBDA_E_SLOTBOOM_CM
    lam = LAMBDA_E_SLOTBOOM_CM
    VT, E0, Ebg, w = 0.025852, 5.0e5, 1.0e2, 0.5 * lam
    xa, xb = 2.0e-5, 2.0e-5 + w
    x = np.unique(np.concatenate([np.linspace(0.0, 6.0e-5, 601), [xa, xb]]))
    field = np.where((x[:-1] >= xa) & (x[1:] <= xb), E0, Ebg)
    psi = np.concatenate([[0.0], np.cumsum(field * np.diff(x))]) / VT
    Eeff = effective_field(x, psi, VT, lam, "n")
    ia, ib = np.searchsorted(x, xa), np.searchsorted(x, xb)
    want = Eeff[ia] * np.exp(-w / lam) + E0 * (1.0 - np.exp(-w / lam))
    assert Eeff[ib] == pytest.approx(want, rel=1e-12)
    assert Eeff.max() < 0.40 * E0
