"""M25 acceptance gates: Monte-Carlo (BCA) implantation.

See pytcad/mc_implant.py's module docstring for the honesty clause on
what physics is simplified/approximated (screened-Rutherford + calibrated
LSS electronic stopping, not the literal SRIM magic-formula potential;
channeling is a disclosed phenomenological knob, not a lattice
simulation).

Core moment-matching and channeling-tail gates live in
test_model_benchmarks.py per house rule (new-model gates land there
first). This file covers the remaining structural/consistency checks.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.mc_implant import (
    mc_implant_bca, calibrate_electronic_stopping, zbl_screening_length_cm,
    SI_ATOMIC_DENSITY_CM3,
)


def test_si_atomic_density_matches_the_well_known_5e22_figure():
    assert 4.5e22 < SI_ATOMIC_DENSITY_CM3 < 5.5e22


def test_zbl_screening_length_decreases_with_heavier_ion():
    a_b = zbl_screening_length_cm(5)     # boron
    a_as = zbl_screening_length_cm(33)   # arsenic
    assert 0 < a_as < a_b   # heavier ion -> more nuclear charge -> tighter screening


def test_unknown_species_raises():
    with pytest.raises(KeyError):
        mc_implant_bca("Xx", 50, k_e=1e5, n_ions=10)


def test_higher_energy_gives_deeper_mean_range_at_fixed_k_e():
    k_e = calibrate_electronic_stopping("B", 50, n_ions=300, seed=1)
    low = mc_implant_bca("B", 20, k_e, n_ions=400, seed=5)
    high = mc_implant_bca("B", 100, k_e, n_ions=400, seed=5)
    assert low["Rp_cm"] < high["Rp_cm"]


def test_tilt_reduces_the_projected_range_along_the_original_axis():
    """A tilted implant should show a shorter projected depth (measured
    along the original surface-normal axis) than a normal-incidence
    implant of the same species/energy -- geometric foreshortening, an
    exact-in-direction-cosine effect independent of the stopping-model
    calibration details."""
    k_e = calibrate_electronic_stopping("P", 50, n_ions=300, seed=1)
    normal = mc_implant_bca("P", 50, k_e, n_ions=600, seed=6, tilt_deg=0.0)
    tilted = mc_implant_bca("P", 50, k_e, n_ions=600, seed=6, tilt_deg=45.0)
    assert tilted["Rp_cm"] < normal["Rp_cm"]


def test_dose_bookkeeping_partitions_every_ion_into_stopped_or_backscattered():
    k_e = calibrate_electronic_stopping("B", 30, n_ions=300, seed=1)
    out = mc_implant_bca("B", 30, k_e, n_ions=500, seed=7)
    n_stopped = int((~out["backscattered"]).sum())
    n_back = int(out["backscattered"].sum())
    assert n_stopped + n_back == 500


def test_calibration_is_reproducible_given_a_fixed_seed():
    k_e_a = calibrate_electronic_stopping("As", 50, n_ions=200, seed=42)
    k_e_b = calibrate_electronic_stopping("As", 50, n_ions=200, seed=42)
    assert k_e_a == k_e_b


def test_calibration_at_the_reference_energy_recovers_the_target_within_tolerance():
    """Sanity check on calibrate_electronic_stopping itself: re-running
    the calibrated k_e at its own reference energy should reproduce the
    target Rp reasonably closely (it's an iterative correction, not an
    exact solve, so allow some Monte-Carlo/statistical slack)."""
    from pytcad import process
    species, ref_E = "P", 70
    Rp_tab, _ = process.implant_moments(species, ref_E)
    k_e = calibrate_electronic_stopping(species, ref_E, n_ions=500, seed=9, n_refine=2)
    out = mc_implant_bca(species, ref_E, k_e, n_ions=800, seed=10)
    assert out["Rp_cm"] == pytest.approx(Rp_tab, rel=0.2)
