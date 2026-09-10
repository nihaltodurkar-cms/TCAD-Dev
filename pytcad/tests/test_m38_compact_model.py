"""M38 gates -- TCAD-to-SPICE compact model extraction
(workbench/compact.py).

Plan and honest limits: pytcad/M38-COMPACT-MODEL-PLAN.md.

The three-layer unit boundary these gates guard (plan section 3.3):
Device1D.current_density is A/cm^2, Device2D.terminal_current is A/cm,
and pytcad/circuit.py's elements are in AMPERES.  Every extractor takes
its scaling factor as a REQUIRED argument; G1-SCALE is the gate that
that argument is actually load-bearing.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.device import Device1D, Models
from pytcad.mesh import graded_mesh

from pytcad.moscap import flatband_voltage, EPS_OX_R
from pytcad.constants import Q, EPS0
from pytcad.materials import SILICON

from workbench.compact import (
    DiodeParams, MOSFET1Params, IdVgCurve, IdVdCurve,
    extract_diode, extract_mosfet1, shockley_current, mosfet1_current,
    to_netlist, from_netlist, source_current,
    simulate_diode_iv, simulate_mosfet1_id,
    mna_resolvable, MNA_LEAKAGE_G,
)


VT_300K = 0.025852


def _tcad_diode(Na=1e17, Nd=1e17, L=2e-4, xj=1e-4):
    """Same fixture shape as tests/test_validation.py::_diode -- the
    device whose local ideality that file already gates to within 2% of
    1.0 for V > 0.3 V, which is what G1-TCAD's band is justified from."""
    x = graded_mesh(L, [xj], 1e-8, 1e-6, 1.12)
    dop = np.where(x < xj, -Na, Nd)
    return Device1D(x, dop, models=Models(bgn=False))


# ----------------------------------------------------------------------
# G1-SELF -- the fitter can recover parameters it did not choose
# ----------------------------------------------------------------------
def test_g1_self_recovers_known_diode_parameters():
    Is_true, N_true = 3.7e-13, 1.15
    V = np.linspace(0.20, 0.70, 26)
    I = shockley_current(V, Is_true, N_true, VT_300K)

    p = extract_diode(V, I, 1.0, VT=VT_300K)

    assert isinstance(p, DiodeParams)
    assert p.Is == pytest.approx(Is_true, rel=1e-2)
    assert p.N == pytest.approx(N_true, rel=1e-2)
    assert p.n_points == V.size
    assert p.rms_log_error < 1e-6


def test_g1_self_recovers_from_a_deliberately_wrong_seed():
    """Adversarial probe (plan section 6): a seed six orders of
    magnitude off in Is and 60% off in N must still land on the same
    answer, or report honest non-convergence -- never a silent bad fit."""
    Is_true, N_true = 1.0e-14, 1.0
    V = np.linspace(0.25, 0.65, 21)
    I = shockley_current(V, Is_true, N_true, VT_300K)

    p = extract_diode(V, I, 1.0, VT=VT_300K, seed=(1.0e-8, 1.6))

    assert p.converged
    assert p.Is == pytest.approx(Is_true, rel=1e-2)
    assert p.N == pytest.approx(N_true, rel=1e-2)


def test_g1_self_parameters_are_not_numerical_no_ops():
    """Adversarial probe (plan section 6): this project has twice
    shipped a parameter that was a numerical no-op.  Sweeping each one
    must MOVE the predicted curve."""
    V = np.linspace(0.3, 0.6, 7)
    base = shockley_current(V, 1e-13, 1.0, VT_300K)
    for Is in (1e-15, 1e-11):
        assert not np.allclose(shockley_current(V, Is, 1.0, VT_300K), base)
    for N in (0.8, 1.4):
        assert not np.allclose(shockley_current(V, 1e-13, N, VT_300K), base)


# ----------------------------------------------------------------------
# G1-SCALE -- the required unit-scaling argument is load-bearing
# ----------------------------------------------------------------------
def test_g1_scale_is_linear_in_is_and_leaves_ideality_alone():
    V = np.linspace(0.25, 0.65, 21)
    J = shockley_current(V, 2.0e-13, 1.05, VT_300K)   # "per cm^2"

    p1 = extract_diode(V, J, 1.0, VT=VT_300K)
    p2 = extract_diode(V, J, 1.0e-4, VT=VT_300K)      # area 1e-4 cm^2

    assert p2.Is == pytest.approx(p1.Is * 1.0e-4, rel=1e-6)
    assert p2.N == pytest.approx(p1.N, rel=1e-6)
    assert p2.scale == 1.0e-4


# ----------------------------------------------------------------------
# G1-REFUSE -- honest refusal, never a fabricated best fit
# ----------------------------------------------------------------------
@pytest.mark.parametrize("V,I,scale", [
    (np.array([-0.5, -1.0, -2.0]), np.array([-1e-13, -1.1e-13, -1.2e-13]), 1.0),
    (np.array([0.4]), np.array([1e-8]), 1.0),
    (np.array([0.3, 0.4, np.nan]), np.array([1e-9, 1e-8, 1e-7]), 1.0),
    (np.array([0.3, 0.4, 0.5]), np.array([1e-9, np.inf, 1e-7]), 1.0),
    (np.array([0.3, 0.4, 0.5]), np.array([1e-9, 1e-8, 1e-7]), 0.0),
    (np.array([0.3, 0.4, 0.5]), np.array([1e-9, 1e-8, 1e-7]), -1.0),
])
def test_g1_refuse_bad_input_raises(V, I, scale):
    with pytest.raises(ValueError):
        extract_diode(V, I, scale, VT=VT_300K)


def test_g1_refuse_reports_which_window_it_used():
    """A window argument that leaves too few points must refuse rather
    than quietly fitting whatever survived."""
    V = np.linspace(0.2, 0.7, 26)
    I = shockley_current(V, 1e-13, 1.0, VT_300K)
    with pytest.raises(ValueError):
        extract_diode(V, I, 1.0, VT=VT_300K, v_window=(0.69, 0.70))


# ----------------------------------------------------------------------
# G1-TCAD -- a real Device1D pn-diode
# ----------------------------------------------------------------------
def test_g1_tcad_pn_diode_ideality_is_near_unity():
    dev = _tcad_diode()
    V = np.arange(0.35, 0.601, 0.05)
    J = dev.iv_sweep(V, verbose=False)          # A/cm^2

    area_cm2 = 1.0e-4
    p = extract_diode(V, J, area_cm2, VT=dev.VT)

    assert p.converged
    # Band justified in plan section 4: test_validation.py already gates
    # this fixture's POINTWISE ideality to 2% of 1.0 for V > 0.3 V; a
    # single global fit over a window is a weaker statement, so 10%.
    assert 0.9 < p.N < 1.1, p.N
    assert p.Is > 0.0
    assert p.rms_log_error < 0.01, p.rms_log_error


# ======================================================================
# Phase 2 -- MOSFET level-1
# ======================================================================
def _tcad_mosfet():
    """A long-channel n-MOSFET the level-1 model can honestly describe.

    Lg = 1 um with sigma_lat = 0.05 um: the builder's DEFAULT lateral
    straggle is Lg/4, which at this gate length puts ~2e18 cm^-3 of
    n-type doping in the middle of the channel and shorts source to
    drain outright (measured while writing this gate -- the device
    showed 3% of gate control across 1 V).  Nsd_peak stays at 5e18 so
    the Boltzmann-degeneracy UserWarning does not fire; the suite
    invariant is zero warnings.
    """
    from pytcad.mosfet import build_mosfet
    return build_mosfet(Lg=1.0e-4, Lsd=0.5e-4, depth=1.0e-4, Na=5e16,
                        Nsd_peak=5e18, tox_cm=1.0e-6,
                        sigma_y=0.05e-4, sigma_lat=0.05e-4, nx=48, ny=28)


def _long_channel_vth(Na, tox_cm, VT, gate="n+poly"):
    """Textbook long-channel threshold: Vfb + 2*phi_f + Qdep/Cox.
    Independent of anything in workbench/compact.py -- that is the
    point, it is an external cross-check for G2-TCAD."""
    ni = SILICON.ni(300.0)
    phi_f = VT * np.log(Na / ni)
    Cox = EPS_OX_R * EPS0 / tox_cm
    Qdep = np.sqrt(2.0 * Q * SILICON.eps_r * EPS0 * Na * 2.0 * phi_f)
    return flatband_voltage(-Na, tox_cm, gate, 0.0, 300.0, SILICON) \
        + 2.0 * phi_f + Qdep / Cox


@pytest.mark.parametrize("kind,s", [("n", 1.0), ("p", -1.0)])
def test_g2_self_recovers_known_mosfet1_parameters(kind, s):
    """Both channel polarities.  Note MOSFET1's Vt0 lives in its own
    always-positive overdrive frame (`vov = sgn*(vg-vs) - Vt0`), so
    Vt0 = +0.7 describes a PMOS with a -0.7 V threshold."""
    Vt0, beta, lam = 0.7, 2.0e-3, 0.03
    vg = s * np.linspace(1.0, 3.0, 11)
    vds_lin = s * 0.1
    ig = mosfet1_current(vg, np.full_like(vg, vds_lin), Vt0, beta, lam, kind)
    vgs_sat = s * 3.0
    vd = s * np.linspace(2.6, 4.0, 8)
    idd = mosfet1_current(np.full_like(vd, vgs_sat), vd, Vt0, beta, lam, kind)

    p = extract_mosfet1(IdVgCurve(vg, ig, vds_lin),
                        IdVdCurve(vd, idd, vgs_sat), 1.0, kind=kind)

    assert isinstance(p, MOSFET1Params)
    assert p.converged
    assert p.Vt0 == pytest.approx(Vt0, rel=1e-2)
    assert p.kp_WL == pytest.approx(beta, rel=1e-2)
    assert p.lam == pytest.approx(lam, rel=1e-2)
    assert p.rel_rms_error < 1e-6
    assert p.n_points == vg.size + vd.size


def test_g2_self_recovers_with_refinement_disabled():
    """The closed-form ELR/saturation-slope seed must already be a real
    extraction, not merely a starting point the optimizer rescues."""
    Vt0, beta, lam = 0.55, 1.0e-3, 0.02
    vg = np.linspace(1.0, 3.0, 9)
    ig = mosfet1_current(vg, np.full_like(vg, 0.05), Vt0, beta, lam, "n")
    vd = np.linspace(2.6, 4.0, 8)
    idd = mosfet1_current(np.full_like(vd, 3.0), vd, Vt0, beta, lam, "n")

    p = extract_mosfet1(IdVgCurve(vg, ig, 0.05), IdVdCurve(vd, idd, 3.0),
                        1.0, refine=False)
    assert p.Vt0 == pytest.approx(Vt0, rel=5e-2)
    assert p.kp_WL == pytest.approx(beta, rel=5e-2)
    assert p.lam == pytest.approx(lam, rel=5e-2)


def test_g2_parameters_are_not_numerical_no_ops():
    """Adversarial probe: all three must move the curve."""
    vg = np.linspace(1.0, 3.0, 9)
    vds = np.full_like(vg, 0.1)
    base = mosfet1_current(vg, vds, 0.7, 2e-3, 0.03, "n")
    assert not np.allclose(mosfet1_current(vg, vds, 0.4, 2e-3, 0.03, "n"), base)
    assert not np.allclose(mosfet1_current(vg, vds, 0.7, 4e-3, 0.03, "n"), base)
    vd = np.linspace(2.6, 4.0, 8)
    vgs = np.full_like(vd, 3.0)
    base_d = mosfet1_current(vgs, vd, 0.7, 2e-3, 0.03, "n")
    assert not np.allclose(mosfet1_current(vgs, vd, 0.7, 2e-3, 0.09, "n"),
                           base_d)


# --- G2-REFUSE --------------------------------------------------------
def test_g2_refuse_subthreshold_window():
    """Plan section 3.1: MOSFET1 returns EXACTLY zero below threshold,
    so a window crossing threshold is ill-posed, not just inaccurate."""
    Vt0, beta, lam = 0.7, 2.0e-3, 0.03
    vg = np.linspace(0.72, 3.0, 13)      # reaches within 0.02 V of Vt0
    ig = mosfet1_current(vg, np.full_like(vg, 0.1), Vt0, beta, lam, "n")
    vd = np.linspace(2.6, 4.0, 8)
    idd = mosfet1_current(np.full_like(vd, 3.0), vd, Vt0, beta, lam, "n")
    with pytest.raises(ValueError, match="subthreshold"):
        extract_mosfet1(IdVgCurve(vg, ig, 0.1), IdVdCurve(vd, idd, 3.0), 1.0)


def test_g2_refuse_triode_points_in_the_lambda_window():
    Vt0, beta, lam = 0.7, 2.0e-3, 0.03
    vg = np.linspace(1.0, 3.0, 9)
    ig = mosfet1_current(vg, np.full_like(vg, 0.1), Vt0, beta, lam, "n")
    vd = np.linspace(1.0, 4.0, 10)       # 1.0 V is deep in triode at vov=2.3
    idd = mosfet1_current(np.full_like(vd, 3.0), vd, Vt0, beta, lam, "n")
    with pytest.raises(ValueError, match="saturation knee"):
        extract_mosfet1(IdVgCurve(vg, ig, 0.1), IdVdCurve(vd, idd, 3.0), 1.0)


def test_g2_refuse_zero_current_and_bad_scale():
    vg = np.linspace(1.0, 3.0, 9)
    ig = mosfet1_current(vg, np.full_like(vg, 0.1), 0.7, 2e-3, 0.03, "n")
    vd = np.linspace(2.6, 4.0, 8)
    idd = mosfet1_current(np.full_like(vd, 3.0), vd, 0.7, 2e-3, 0.03, "n")
    with pytest.raises(ValueError):
        extract_mosfet1(IdVgCurve(vg, ig * 0.0, 0.1),
                        IdVdCurve(vd, idd, 3.0), 1.0)
    with pytest.raises(ValueError):
        extract_mosfet1(IdVgCurve(vg, ig, 0.1), IdVdCurve(vd, idd, 3.0), 0.0)
    with pytest.raises(ValueError):
        extract_mosfet1(IdVgCurve(vg, ig, 0.1), IdVdCurve(vd, idd, 3.0), 1.0,
                        kind="q")


def test_g2_tcad_2d_mosfet_matches_long_channel_theory():
    """G2-TCAD: a real Device2D MOSFET, fitted, cross-checked against a
    formula that shares no code with the extractor."""
    from pytcad.device import NewtonOptions
    dev = _tcad_mosfet()
    opts = NewtonOptions()
    dev.solve_equilibrium(opts)

    VG = np.arange(0.5, 3.01, 0.25)
    IG = []
    for v in VG:
        dev.solve_bias({"drain": 0.1, "gate": float(v)}, opts)
        IG.append(dev.terminal_current("drain"))
    VD = np.arange(1.6, 3.01, 0.2)
    ID = []
    for v in VD:
        dev.solve_bias({"drain": float(v), "gate": 1.5}, opts)
        ID.append(dev.terminal_current("drain"))

    W_cm = 1.0e-4          # terminal_current is A/cm; pick a 1 um width
    p = extract_mosfet1(IdVgCurve(VG, np.array(IG), 0.1),
                        IdVdCurve(VD, np.array(ID), 1.5), W_cm)

    assert p.converged
    # Measured 2.90% when this gate was written (plan section 5); the
    # bound leaves margin without being vacuous.
    assert p.rel_rms_error < 0.06, p.rel_rms_error
    vth_theory = _long_channel_vth(5e16, 1.0e-6, dev.VT)
    assert p.Vt0 == pytest.approx(vth_theory, rel=0.15), (p.Vt0, vth_theory)
    assert p.kp_WL > 0.0 and 0.0 <= p.lam < 1.0


# ======================================================================
# Phase 3 -- netlist emission, read-back, and the closed loop
# ======================================================================
def _fitted_diode():
    """A 1 cm^2 synthetic diode.  The area is deliberately large: at
    1e-4 cm^2 the whole curve sits under circuit.Circuit's floating-node
    guard (see the closed-loop gate), which would leave nothing to
    compare in the guard-free regime."""
    V = np.linspace(0.25, 0.65, 21)
    I = shockley_current(V, 2.5e-14, 1.05, VT_300K)
    return extract_diode(V, I, 1.0, VT=VT_300K), V, I


def test_g3_emit_diode_card_is_syntactically_real():
    p, _, _ = _fitted_diode()
    text = to_netlist(p, name="DX")
    assert ".MODEL DX D (" in text
    assert "IS=" in text and "N=" in text
    assert text.strip().splitlines()[-1].startswith(".MODEL")


@pytest.mark.parametrize("kind,expected", [("n", "NMOS"), ("p", "PMOS")])
def test_g3_emit_mosfet_card_uses_spice_sign_convention(kind, expected):
    p = MOSFET1Params(Vt0=0.7, kp_WL=2e-3, lam=0.03, kind=kind, scale=1e-4,
                      rel_rms_error=0.01, n_points=19, vov_min=0.1,
                      converged=True)
    text = to_netlist(p)
    assert f" {expected} (" in text
    assert "LEVEL=1" in text
    sgn = 1.0 if kind == "n" else -1.0
    vto = float([t for t in text.split() if t.startswith("VTO=")][0][4:])
    assert vto == pytest.approx(sgn * 0.7)


def test_g3_round_trip_is_exact_for_both_models():
    """A real reader exists so this gate cannot pass vacuously."""
    p, _, _ = _fitted_diode()
    assert from_netlist(to_netlist(p)) == p

    m = MOSFET1Params(Vt0=0.61234567890123, kp_WL=2.71828e-3,
                      lam=0.031415926, kind="p", scale=1.5e-4,
                      rel_rms_error=0.0234, n_points=19, vov_min=0.1,
                      converged=True)
    assert from_netlist(to_netlist(m)) == m


def test_g3_from_netlist_refuses_a_deck_it_did_not_write():
    with pytest.raises(ValueError):
        from_netlist(".MODEL DX D (IS=1e-14 N=1.0)\n")
    with pytest.raises(ValueError):
        from_netlist("* PYTCAD_PROVENANCE model=bogus\n.MODEL X D (IS=1)\n")


def test_g3_from_netlist_refuses_a_multi_model_deck():
    p, _, _ = _fitted_diode()
    m = MOSFET1Params(Vt0=0.7, kp_WL=2e-3, lam=0.03, kind="n", scale=1.0,
                      rel_rms_error=0.01, n_points=19, vov_min=0.1,
                      converged=True)
    with pytest.raises(ValueError, match="multi-model"):
        from_netlist(to_netlist(p) + to_netlist(m))


def test_g3_from_netlist_refuses_a_malformed_card():
    with pytest.raises(ValueError, match="malformed"):
        from_netlist("* PYTCAD_PROVENANCE model=diode\n.MODEL DX D\n")


def test_g3_branch_current_sign_matches_a_known_resistor():
    """`source_current`'s single negation, checked against Ohm's law
    rather than read off the stamp."""
    from pytcad.circuit import Circuit, VSource, Resistor, GND
    c = Circuit()
    c.add(VSource("VS", "a", GND, 2.0))
    c.add(Resistor("R1", "a", GND, 1000.0))
    x, mna = c.dc_operating_point()
    assert source_current(x, mna, "VS") == pytest.approx(2.0e-3, rel=1e-6)


def test_g3_closed_loop_diode_reproduces_the_fitted_curve():
    """THE HEADLINE GATE (diode): parameters -> netlist text ->
    parameters -> a real circuit.Diode driven through circuit.py's own
    MNA solver -> back to the curve that was fitted."""
    p, V, I_ref = _fitted_diode()
    recovered = from_netlist(to_netlist(p))
    I_sim = simulate_diode_iv(recovered, V)
    assert np.all(np.isfinite(I_sim))
    I_amp = I_ref * p.scale
    rel = np.abs(I_sim - I_amp) / I_amp
    # Not a tolerance: a PREDICTION.  The only discrepancy the loop may
    # show is circuit.Circuit's own 1e-12 S floating-node guard, whose
    # contribution at each point is exactly MNA_LEAKAGE_G * V.  Asserting
    # against that (rather than a round number) means an error from any
    # OTHER cause fails this gate even where the guard is large.
    rel_guard = MNA_LEAKAGE_G * V / I_amp
    assert np.all(rel <= 1.1 * rel_guard + 1e-9), (rel, rel_guard)
    # ... and where the guard is negligible, the loop is exact.
    ok = mna_resolvable(V, I_amp, margin=1.0e5)
    assert np.count_nonzero(ok) >= 10, "resolvable window too small to gate"
    assert np.max(rel[ok]) < 1e-4, np.max(rel[ok])


def test_g3_closed_loop_tcad_diode_reproduces_the_tcad_curve():
    """The same loop, but starting from a REAL Device1D I-V."""
    dev = _tcad_diode()
    V = np.arange(0.35, 0.601, 0.05)
    J = dev.iv_sweep(V, verbose=False)
    area = 1.0e-4
    p = extract_diode(V, J, area, VT=dev.VT)
    recovered = from_netlist(to_netlist(p))
    I_sim = simulate_diode_iv(recovered, V)
    I_amp = J * area
    ok = mna_resolvable(V, I_amp)
    assert np.count_nonzero(ok) >= 4, "resolvable window too small to gate"
    I_sim, I_amp = I_sim[ok], I_amp[ok]
    rel = np.abs(I_sim - I_amp) / I_amp
    # The bound is the fit's own measured residual, not a wish: an
    # rms_log_error of e is a relative spread of about exp(e)-1.
    assert np.max(rel) < 5.0 * (np.expm1(p.rms_log_error)), (
        np.max(rel), p.rms_log_error)


def test_g3_closed_loop_mosfet_reproduces_the_fitted_curve():
    """THE HEADLINE GATE (MOSFET): the same round trip through a real
    circuit.MOSFET1."""
    Vt0, beta, lam = 0.7, 2.0e-3, 0.03
    vg = np.linspace(1.0, 3.0, 11)
    ig = mosfet1_current(vg, np.full_like(vg, 0.1), Vt0, beta, lam, "n")
    vd = np.linspace(2.6, 4.0, 8)
    idd = mosfet1_current(np.full_like(vd, 3.0), vd, Vt0, beta, lam, "n")
    p = extract_mosfet1(IdVgCurve(vg, ig, 0.1), IdVdCurve(vd, idd, 3.0), 1.0)

    recovered = from_netlist(to_netlist(p))
    sim = simulate_mosfet1_id(recovered, vg, np.full_like(vg, 0.1))
    assert np.max(np.abs(sim - ig) / ig) < 1e-4
    sim_d = simulate_mosfet1_id(recovered, np.full_like(vd, 3.0), vd)
    assert np.max(np.abs(sim_d - idd) / idd) < 1e-4


def test_g3_mna_guard_floor_is_real_and_detected():
    """The floor mna_resolvable() exists for, demonstrated rather than
    asserted: a diode small enough to sit under circuit.Circuit's
    floating-node guard is genuinely mis-simulated, and the mask says so."""
    tiny = DiodeParams(Is=2.5e-18, N=1.05, VT=VT_300K, scale=1.0,
                       rms_log_error=0.0, n_points=21, v_min=0.25,
                       v_max=0.25, converged=True)
    V = np.array([0.25])
    I_true = shockley_current(V, tiny.Is, tiny.N, tiny.VT)
    I_sim = simulate_diode_iv(tiny, V)
    assert not mna_resolvable(V, I_true)[0]
    assert I_sim[0] > 5.0 * I_true[0]          # dominated by the guard
    assert I_sim[0] == pytest.approx(I_true[0] + MNA_LEAKAGE_G * V[0],
                                     rel=1e-3)


def test_g3_simulate_diode_iv_step_clamp_is_reachable_and_documented():
    """The two circuit.py limits `simulate_diode_iv`'s docstring names,
    demonstrated live rather than asserted in prose."""
    p = DiodeParams(Is=1.0e-13, N=1.0, VT=VT_300K, scale=1.0,
                    rms_log_error=0.0, n_points=3, v_min=0.6, v_max=1.2,
                    converged=True)
    # 1.2 V draws ~1.4e7 A, far past the default 1 A/iteration clamp.
    with pytest.raises(RuntimeError):
        simulate_diode_iv(p, [1.2])
    assert simulate_diode_iv(p, [1.2], max_dv=1.0e9)[0] > 1.0e6
    # ... but above circuit.Diode's own 1.5 V linearization clip, no
    # max_dv helps.  That ceiling belongs to the element, not to us.
    with pytest.raises(RuntimeError):
        simulate_diode_iv(p, [2.0], max_dv=1.0e12)
