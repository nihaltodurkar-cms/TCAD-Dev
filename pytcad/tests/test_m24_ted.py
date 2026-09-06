"""M24 acceptance gates: pair-diffusion enhancement (extrinsic/TED/OED),
segregation, and clustering (see pytcad/ted.py module docstring for the
honesty clause on what is NOT modeled -- this is a lumped engineering
model, not a coupled point-defect PDE).

Gates, per ARCHITECTURE.md's M24 spec:
  G1 (exact)       -- intrinsic limit reduces to the current constant-D
                       model, bit-identically. Covered in
                       test_model_benchmarks.py (house rule: new-model
                       gates land there first).
  G2 (published)   -- extrinsic enhancement vs Fair's published D(n/Ni)
                       relation. Core algebraic check in
                       test_model_benchmarks.py; broader curve-shape
                       checks here.
  G3 (qualitative) -- TED junction-depth plateau: a decaying
                       supersaturation must give diffusion enhancement
                       that saturates over time rather than growing
                       Fickian-forever, honestly labeled qualitative (no
                       digitized literature curve is bundled).
  G4 (exact)       -- segregation dose split matches the analytic
                       equilibrium partition. Core identity in
                       test_model_benchmarks.py; a physical-limit sanity
                       check here.
  Clustering       -- solubility clipping conserves total dose exactly
                       and only activates once concentration exceeds
                       solubility.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from pytcad import process
from pytcad.ted import (
    ni_silicon, extrinsic_enhancement, ted_plus_one_S0, ted_supersaturation,
    oed_enhancement, diffuse_with_defects, solid_solubility, apply_clustering,
    segregation_partition,
)


# ----------------------------------------------------------------------
#  ni(T)
# ----------------------------------------------------------------------
def test_ni_silicon_room_temperature_matches_the_textbook_value():
    ni_300 = ni_silicon(26.85)   # 300.0 K
    assert 8e9 <= ni_300 <= 1.2e10   # ~9.65e9 cm^-3, Sze & Ng


def test_ni_silicon_increases_monotonically_with_temperature():
    T = np.array([300.0, 500.0, 800.0, 1000.0])
    ni = ni_silicon(T)
    assert np.all(np.diff(ni) > 0)


# ----------------------------------------------------------------------
#  Extrinsic enhancement curve shape
# ----------------------------------------------------------------------
def test_extrinsic_enhancement_is_monotonic_above_intrinsic_for_boron():
    ni = ni_silicon(1000.0)
    ratios = np.array([1.0, 2.0, 5.0, 10.0, 50.0])
    D = np.array([extrinsic_enhancement("B", r * ni, 1000.0) for r in ratios])
    assert np.all(np.diff(D) > 0)
    assert D[0] == pytest_approx(1.0)


def pytest_approx(v, rel=1e-9):
    import pytest
    return pytest.approx(v, rel=rel)


def test_extrinsic_enhancement_rejects_unknown_species():
    import pytest
    with pytest.raises(KeyError):
        extrinsic_enhancement("Xx", 1e18, 1000.0)


# ----------------------------------------------------------------------
#  TED
# ----------------------------------------------------------------------
def test_ted_plus_one_S0_scales_with_dose_and_inversely_with_depth():
    C_I_eq = 1e15
    S_shallow = ted_plus_one_S0(1e14, 1e-6, C_I_eq)
    S_deep = ted_plus_one_S0(1e14, 1e-5, C_I_eq)
    S_more_dose = ted_plus_one_S0(1e15, 1e-6, C_I_eq)
    assert S_shallow > S_deep
    assert S_more_dose > S_shallow


def test_ted_supersaturation_decays_to_zero():
    S0, tau = 5.0, 10.0
    assert ted_supersaturation(0.0, S0, tau) == pytest_approx(S0)
    assert ted_supersaturation(10 * tau, S0, tau) < 1e-3 * S0


def test_ted_junction_depth_plateaus_instead_of_growing_forever():
    """G3 (qualitative): a TED-boosted anneal should show most of its
    *extra* diffusion (relative to the no-TED case) happen early, with
    the marginal extra spread per unit time falling off once the
    supersaturation has decayed -- i.e. a plateau, not continued
    Fickian-rate growth of the TED-induced extra spread."""
    x = np.linspace(0.0, 3e-4, 301)
    C0 = process.implant(x, "B", 30, 5e13)
    T_C = 950.0
    tau = 20.0   # s, short so the anneal windows below straddle several tau

    def spread(t_s, ted_S0):
        C = diffuse_with_defects(x, C0, "B", T_C, t_s, ted_S0=ted_S0, ted_tau_s=tau)
        # second moment as a width proxy
        return float(np.sqrt(np.trapezoid(C * x**2, x) / np.trapezoid(C, x)))

    baseline = [spread(t, 0.0) for t in (60.0, 600.0)]
    boosted = [spread(t, 20.0) for t in (60.0, 600.0)]
    extra_early = boosted[0] - baseline[0]     # extra spread by t=60s (>>tau already)
    extra_late = boosted[1] - baseline[1]      # extra spread by t=600s

    assert extra_early > 0.0    # TED did enhance diffusion
    # The *extra* TED spread should not keep growing much once t >> tau --
    # it should be within a modest factor of the early value, not scale
    # up the way ordinary sqrt(Dt) growth would over a 10x longer anneal.
    assert extra_late < 3.0 * extra_early


def test_diffuse_with_defects_ted_boost_increases_diffusion_relative_to_bare():
    x = np.linspace(0.0, 2e-4, 201)
    C0 = process.implant(x, "P", 50, 1e14)
    bare = process.diffuse_numeric(x, C0, "P", 1000.0, 120.0)
    boosted = diffuse_with_defects(x, C0, "P", 1000.0, 120.0,
                                    ted_S0=10.0, ted_tau_s=30.0)
    # boosted profile should have spread further (lower peak, since dose
    # is conserved by the same conservative discretization).
    assert boosted.max() < bare.max()
    assert np.trapezoid(boosted, x) == pytest_approx(np.trapezoid(bare, x), rel=1e-2)


# ----------------------------------------------------------------------
#  OED
# ----------------------------------------------------------------------
def test_oed_enhancement_is_zero_with_no_growth_and_positive_with_growth():
    assert oed_enhancement(0.0) == 0.0
    assert oed_enhancement(0.5) > 0.0


def test_oed_enhancement_increases_with_growth_rate():
    assert oed_enhancement(0.1) < oed_enhancement(1.0)


# ----------------------------------------------------------------------
#  Segregation
# ----------------------------------------------------------------------
def test_segregation_partition_boron_like_m_below_one_depletes_silicon():
    """Boron-like segregation (m < 1, dopant prefers the oxide) should
    leave less dopant in silicon than an m=1 (no preference) split of the
    same total dose."""
    Q, t_si, t_ox = 1e13, 1e-6, 1e-6
    C_si_boron, _ = segregation_partition(Q, m=0.3, thickness_si_cm=t_si,
                                           thickness_ox_cm=t_ox)
    C_si_neutral, _ = segregation_partition(Q, m=1.0, thickness_si_cm=t_si,
                                             thickness_ox_cm=t_ox)
    assert C_si_boron < C_si_neutral


def test_segregation_partition_phosphorus_like_m_above_one_piles_up_in_silicon():
    Q, t_si, t_ox = 1e13, 1e-6, 1e-6
    C_si_p, _ = segregation_partition(Q, m=10.0, thickness_si_cm=t_si,
                                       thickness_ox_cm=t_ox)
    C_si_neutral, _ = segregation_partition(Q, m=1.0, thickness_si_cm=t_si,
                                             thickness_ox_cm=t_ox)
    assert C_si_p > C_si_neutral


# ----------------------------------------------------------------------
#  Clustering
# ----------------------------------------------------------------------
def test_clustering_conserves_total_dose_exactly():
    C = np.array([1e18, 1e20, 1e21, 5e21])
    active, clustered = apply_clustering(C, "B", 1000.0)
    assert np.allclose(active + clustered, C, rtol=0, atol=1e-6)


def test_clustering_is_inactive_below_solubility():
    Cs = solid_solubility("B", 1000.0)
    C = np.array([0.1 * Cs, 0.5 * Cs])
    active, clustered = apply_clustering(C, "B", 1000.0)
    assert np.allclose(active, C)
    assert np.all(clustered == 0.0)


def test_clustering_clips_at_solubility_when_exceeded():
    Cs = solid_solubility("As", 1000.0)
    C = np.array([5.0 * Cs])
    active, clustered = apply_clustering(C, "As", 1000.0)
    assert active[0] == pytest_approx(Cs)
    assert clustered[0] == pytest_approx(4.0 * Cs, rel=1e-6)


def test_solid_solubility_rolls_off_with_temperature_change():
    Cs_1000 = solid_solubility("P", 1000.0)
    Cs_800 = solid_solubility("P", 800.0)
    assert Cs_1000 != Cs_800
