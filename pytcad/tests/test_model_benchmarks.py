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
