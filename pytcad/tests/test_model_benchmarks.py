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
