"""M3 acceptance tests, part 2: the observables/analysis layer
(ARCHITECTURE.md revised roadmap, milestone M3b).

Contract under test:
  - workbench.analysis.observables exposes backend-agnostic,
    array-based physics readouts. Math that already exists in
    gui/services/sweep_derived.py is DELEGATED to, not reimplemented --
    numerical parity with today's GUI readouts holds by construction and
    is pinned here by goldens.
  - band_diagram() reproduces Device1D.band_diagram() exactly on real
    solved data, but works from plain physical-unit arrays (what any
    backend's RunResult carries), not from solver internals.
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from workbench.analysis import observables as obs


# ----------------------------------------------------------------------
#  parity with today's GUI readouts (goldens)
# ----------------------------------------------------------------------
def _synthetic_sweep():
    """A clean MOS-like transfer curve: Ioff at Vg=0, subthreshold rise,
    above-threshold current."""
    v = np.linspace(0.0, 1.0, 11)
    i = 1e-12 + 1e-3 * np.maximum(0.0, v - 0.4) ** 2
    return v, i


def test_current_extremes_parity_with_service_layer():
    from gui.services import sweep_derived
    _, i = _synthetic_sweep()
    assert obs.current_extremes(i) == sweep_derived.current_extremes(i)


def test_on_off_ratio_parity_with_service_layer():
    from gui.services import sweep_derived
    _, i = _synthetic_sweep()
    assert obs.on_off_ratio(i) == sweep_derived.on_off_ratio(i)


def test_vth_parity_with_service_layer_in_both_sign_conventions():
    from gui.services import sweep_derived
    v, i = _synthetic_sweep()
    expected = sweep_derived.threshold_voltage_max_gm(v, i)
    assert obs.threshold_voltage_max_gm(v, i) == pytest.approx(expected)
    flipped = sweep_derived.threshold_voltage_max_gm(v, -i)
    assert obs.threshold_voltage_max_gm(v, -i) == pytest.approx(flipped)


# ----------------------------------------------------------------------
#  new observable: transconductance curve
# ----------------------------------------------------------------------
def test_gm_of_linear_ramp_is_constant_and_positive():
    v = np.linspace(0.0, 1.0, 101)
    i = 5e-3 * v                      # ideal ohmic channel
    gm = obs.gm_curve(v, i)
    assert gm.shape == v.shape
    assert np.allclose(gm, 5e-3, rtol=1e-9)


def test_gm_peaks_where_curvature_is_maximum():
    v = np.linspace(0.0, 1.0, 201)
    i = np.maximum(0.0, v - 0.4) ** 2     # turns on at 0.4
    gm = obs.gm_curve(v, i)
    assert v[np.argmax(gm)] == pytest.approx(1.0)   # parabola: gm grows


# ----------------------------------------------------------------------
#  band diagram from plain physical-unit arrays
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def solved_1d():
    x = np.linspace(0.0, 2e-4, 40)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    from pytcad.device import Device1D
    dev = Device1D(x, doping)
    dev.solve_equilibrium()
    return dev


def test_band_diagram_matches_core_exactly_on_real_solution(solved_1d):
    Ec_ref, Ev_ref, EFn_ref, EFp_ref = solved_1d.band_diagram()

    Ec, Ev, EFn, EFp = obs.band_diagram(
        psi_V=solved_1d.psi_V, n=solved_1d.n_cm3, p=solved_1d.p_cm3,
        material="SILICON", T=300.0)

    # the core returns eV relative to vacuum with its own sign convention;
    # psi_V IS the scaled psi * VT, so exact equality is required
    assert np.allclose(Ec, Ec_ref, atol=1e-12)
    assert np.allclose(Ev, Ev_ref, atol=1e-12)
    assert np.allclose(EFn, EFn_ref, atol=1e-12)
    assert np.allclose(EFp, EFp_ref, atol=1e-12)


def test_band_diagram_physics_sanity_on_real_solution(solved_1d):
    Ec, Ev, EFn, EFp = obs.band_diagram(
        psi_V=solved_1d.psi_V, n=solved_1d.n_cm3, p=solved_1d.p_cm3,
        material="SILICON", T=300.0)
    assert np.all(Ec > Ev)                       # gap never closes
    assert np.all(EFn - EFp > -1e-9)             # equilibrium split ~ 0
                                                 # (float noise allowed)
    assert abs(np.mean(EFn - EFp)) < 1e-6        # equilibrium: no QFL split


def test_band_diagram_unknown_material_rejected():
    with pytest.raises(KeyError, match="GaAs"):
        obs.band_diagram(psi_V=np.zeros(3), n=np.ones(3), p=np.ones(3),
                         material="GaAs", T=300.0)


# ----------------------------------------------------------------------
#  registry: what an educational surface would list
# ----------------------------------------------------------------------
def test_observable_registry_lists_names_and_callables():
    for name in obs.OBSERVABLES:
        assert callable(obs.OBSERVABLES[name]), name
    assert {"current_extremes", "on_off_ratio",
            "threshold_voltage_max_gm", "gm_curve", "band_diagram"} <= \
        set(obs.OBSERVABLES)
