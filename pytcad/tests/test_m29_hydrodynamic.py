"""M29 structural/consistency gates: the local carrier-temperature
energy-balance closure (pytcad/hydrodynamic.py).

The three headline acceptance gates (DD-limit bit-identity, overshoot/
heating trend, carrier-temperature impact ionization vs published)
live in test_model_benchmarks.py per house rule. This file covers
cheaper structural/unit checks on the closure's own math.

See hydrodynamic.py's own module docstring for the honesty clause on
what is simplified: a LOCAL (no spatial energy-flux) closure, published
order-of-magnitude energy relaxation times (not doping/field-dependent
fits), and carrier-temperature-driven impact ionization reached by
mapping back to an effective field and reusing the existing M15
field-driven coefficients rather than an independently fitted law.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.hydrodynamic import (
    carrier_temperature, effective_field_from_temperature, thermal_velocity,
    energy_relaxation_length, hot_carrier_heating_ratio,
    impact_ionization_rate_carrierT, TAU_W_N, TAU_W_P,
)
from pytcad.materials import SILICON


def test_carrier_temperature_equals_lattice_temperature_at_zero_field():
    assert carrier_temperature(0.0, SILICON.mu_n_max) == pytest.approx(300.0)


def test_carrier_temperature_increases_monotonically_with_field():
    fields = [0.0, 1e3, 1e4, 1e5, 3e5]
    temps = [carrier_temperature(E, SILICON.mu_n_max) for E in fields]
    for a, b in zip(temps, temps[1:]):
        assert b > a


def test_carrier_temperature_scales_with_mobility():
    """Higher mobility -> more power delivered per carrier at the same
    field (v_d = mu*E is larger) -> higher carrier temperature."""
    Tn_lo = carrier_temperature(1e4, 200.0)
    Tn_hi = carrier_temperature(1e4, 1400.0)
    assert Tn_hi > Tn_lo


@pytest.mark.parametrize("E", [1e2, 1e3, 1e4, 1e5, 3e5])
def test_effective_field_round_trips_carrier_temperature(E):
    """The whole point of `effective_field_from_temperature` is being
    the exact algebraic inverse of `carrier_temperature` -- verified
    directly across several decades of field, not just one value."""
    Tn = carrier_temperature(E, SILICON.mu_n_max)
    E_back = effective_field_from_temperature(Tn, SILICON.mu_n_max)
    assert E_back == pytest.approx(E, rel=1e-9)


def test_thermal_velocity_matches_hand_computed_rms_speed():
    from pytcad.constants import KB, M0
    Tn = 500.0
    m_star = 0.26
    v_hand = np.sqrt(3.0 * KB * Tn / (m_star * M0)) * 1.0e2   # m/s -> cm/s
    assert thermal_velocity(Tn, m_star) == pytest.approx(v_hand, rel=1e-9)


def test_thermal_velocity_increases_with_temperature():
    assert thermal_velocity(600.0, SILICON.m_n_star) > \
        thermal_velocity(300.0, SILICON.m_n_star)


def test_energy_relaxation_length_scales_linearly_with_tau_w():
    l1 = energy_relaxation_length(SILICON.vsat_n, TAU_W_N)
    l2 = energy_relaxation_length(SILICON.vsat_n, 2.0 * TAU_W_N)
    assert l2 == pytest.approx(2.0 * l1, rel=1e-9)


def test_hot_carrier_heating_ratio_is_exactly_one_at_zero_field():
    assert hot_carrier_heating_ratio(0.0, SILICON.mu_n_max) == pytest.approx(1.0)


def test_hot_carrier_heating_ratio_equals_sqrt_temperature_ratio():
    E = 5e4
    Tn = carrier_temperature(E, SILICON.mu_n_max)
    expected = np.sqrt(Tn / 300.0)
    assert hot_carrier_heating_ratio(E, SILICON.mu_n_max) == pytest.approx(expected)


def test_impact_ionization_carrierT_matches_the_field_model_for_holes_too():
    n, p, E = 1e14, 1e14, 4.5e5
    Tn = carrier_temperature(E, SILICON.mu_n_max)
    Tp = carrier_temperature(E, SILICON.mu_p_max, tau_w=TAU_W_P)
    from pytcad.ionization import alpha_n, alpha_p
    G = impact_ionization_rate_carrierT(
        n, p, Tn, Tp, SILICON.mu_n_max, SILICON.mu_p_max, tau_w_p=TAU_W_P)
    expected = (alpha_n(E) * SILICON.mu_n_max * E * n
               + alpha_p(E) * SILICON.mu_p_max * E * p)
    assert G == pytest.approx(expected, rel=1e-9)


def test_impact_ionization_carrierT_is_zero_at_zero_carrier_density():
    Tn = carrier_temperature(3e5, SILICON.mu_n_max)
    Tp = carrier_temperature(3e5, SILICON.mu_p_max)
    G = impact_ionization_rate_carrierT(
        0.0, 0.0, Tn, Tp, SILICON.mu_n_max, SILICON.mu_p_max)
    assert G == pytest.approx(0.0, abs=1e-30)


def test_carrier_temperature_and_effective_field_are_array_vectorized():
    E = np.array([1e3, 1e4, 1e5])
    Tn = carrier_temperature(E, SILICON.mu_n_max)
    assert Tn.shape == E.shape
    E_back = effective_field_from_temperature(Tn, SILICON.mu_n_max)
    np.testing.assert_allclose(E_back, E, rtol=1e-9)
