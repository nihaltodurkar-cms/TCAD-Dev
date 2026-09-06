"""M28 acceptance gates: Schottky / tunnel contacts + gate stacks.

See pytcad/schottky.py's module docstring for the honesty clause on
what is simplified (published A* used directly rather than derived
from conductivity mass; image-force lowering via the depletion-
approximation E_max; field-emission LIMIT formula only, no TFE
integral; no live Jacobian coupling into Device1D/Device2D).

Core thermionic-emission / Richardson-constant / image-force / ohmic-
limit gates live in test_model_benchmarks.py per house rule. This file
covers the remaining structural/consistency checks.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.schottky import (
    richardson_constant_A0, richardson_a_star, RICHARDSON_A_STAR_TABLE,
    schottky_barrier_height_n, schottky_barrier_height_p,
    schottky_max_field, image_force_lowering_eV,
    thermionic_current_density, schottky_iv,
    characteristic_tunneling_energy_E00_eV, contact_regime,
    field_emission_current_density,
)
from pytcad.materials import SILICON


def test_barrier_height_n_and_p_sum_to_the_bandgap_on_the_same_junction():
    phi_m = 4.9  # eV, generic mid-gap-ish metal
    Bn = schottky_barrier_height_n(phi_m, SILICON.chi)
    Bp = schottky_barrier_height_p(phi_m, SILICON.chi, SILICON.Eg(300.0))
    assert Bn + Bp == pytest.approx(SILICON.Eg(300.0), rel=1e-12)


def test_unknown_material_carrier_pair_raises():
    with pytest.raises(KeyError):
        richardson_a_star("Unobtainium", "n")


def test_richardson_a_star_table_has_both_carriers_for_silicon():
    assert ("Si", "n") in RICHARDSON_A_STAR_TABLE
    assert ("Si", "p") in RICHARDSON_A_STAR_TABLE
    assert RICHARDSON_A_STAR_TABLE[("Si", "n")] != RICHARDSON_A_STAR_TABLE[("Si", "p")]


def test_max_field_increases_with_doping_and_decreases_with_forward_bias():
    phi_B = 0.85
    E_1e16 = schottky_max_field(1e16, phi_B, 0.0, SILICON.eps_r)
    E_1e17 = schottky_max_field(1e17, phi_B, 0.0, SILICON.eps_r)
    assert E_1e17 > E_1e16
    E_fwd = schottky_max_field(1e16, phi_B, 0.3, SILICON.eps_r)
    assert E_fwd < E_1e16


def test_schottky_iv_with_image_force_gives_higher_current_than_without():
    """Image-force lowering reduces the effective barrier, so the
    image-force-corrected I-V must sit at or above the fixed-barrier
    curve at the same forward bias."""
    phi_B = 0.85
    A_star = richardson_a_star("Si", "n")
    T = 300.0
    V = 0.3
    J_plain = thermionic_current_density(phi_B, T, V, A_star)
    J_img = schottky_iv(phi_B, T, V, A_star, Nd_cm3=1e16, eps_r=SILICON.eps_r)
    assert J_img >= J_plain


def test_schottky_iv_falls_back_to_plain_thermionic_without_doping_info():
    phi_B = 0.85
    A_star = richardson_a_star("Si", "n")
    T = 300.0
    V = np.array([0.1, 0.2, 0.3])
    J_fallback = schottky_iv(phi_B, T, V, A_star)
    J_direct = thermionic_current_density(phi_B, T, V, A_star)
    np.testing.assert_allclose(J_fallback, J_direct)


def test_E00_increases_with_doping_and_decreases_with_effective_mass():
    E_lo = characteristic_tunneling_energy_E00_eV(1e17, SILICON.m_n_star, SILICON.eps_r)
    E_hi = characteristic_tunneling_energy_E00_eV(1e19, SILICON.m_n_star, SILICON.eps_r)
    assert E_hi > E_lo
    E_heavier_mass = characteristic_tunneling_energy_E00_eV(1e19, 2.0 * SILICON.m_n_star, SILICON.eps_r)
    assert E_heavier_mass < E_hi


def test_contact_regime_classifies_light_and_heavy_doping_correctly():
    E00_light = characteristic_tunneling_energy_E00_eV(1e15, SILICON.m_n_star, SILICON.eps_r)
    E00_heavy = characteristic_tunneling_energy_E00_eV(1e20, SILICON.m_n_star, SILICON.eps_r)
    assert contact_regime(E00_light, 300.0) == "TE"
    assert contact_regime(E00_heavy, 300.0) == "FE"


def test_field_emission_current_grows_with_doping_deep_in_the_fe_regime():
    """Deeper into the FE regime (higher doping -> larger E00), the
    tunnel-contact current for a fixed barrier must increase -- this is
    the qualitative basis for degenerate contacts behaving 'ohmic'."""
    A_star = richardson_a_star("Si", "n")
    phi_B = 0.85
    E00_a = characteristic_tunneling_energy_E00_eV(5e19, SILICON.m_n_star, SILICON.eps_r)
    E00_b = characteristic_tunneling_energy_E00_eV(2e20, SILICON.m_n_star, SILICON.eps_r)
    J_a = field_emission_current_density(phi_B, 300.0, E00_a, A_star)
    J_b = field_emission_current_density(phi_B, 300.0, E00_b, A_star)
    assert J_b > J_a
