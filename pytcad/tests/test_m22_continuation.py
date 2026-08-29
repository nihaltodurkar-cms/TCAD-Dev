"""M22 phase 2 gates: continuation drivers (M22-LINSOLVE-PLAN.md section 1).

pytcad/continuation.py is a PURE ADDITION -- it drives Device1D through
solve_bias/_residual_jacobian/_contact_values, the same public/internal
surface iv_sweep already uses, and touches no residual, no Jacobian and
no committed golden.

Two drivers are gated:
  adaptive_bias_sweep -- step backoff/retry on Newton failure.
  arc_length_sweep    -- pseudo-arclength continuation.

Both are gated against the SAME reference: a plain fixed-step iv_sweep
on an ordinary (unfolded) reverse-biased diode, where the true answer is
already trusted (M13/M15 goldens exercise this same solve path).

arc_length_sweep's `strength_stages` parameter (M15 R1b attempt 3,
2026-08-28) is gated separately below: it ramps a generation-strength
attribute on the device through the corrector, mirroring Device1D.
solve_bias's own ladder, because the corrector calls
device._residual_jacobian directly and so never goes through
solve_bias's ladder at all.  Without it, a stiff coupled term (M15's
avalanche generation) runs at full strength from the corrector's very
first iterate at every arc-length step -- see M15-IONIZATION-PLAN.md's
"R1b ATTEMPT 2" for the resulting stall this was built to fix, and
"R1b ATTEMPT 3" for what it does and does not close.
"""
import os
import sys
import warnings

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pytcad import Device1D, Models, NewtonOptions
from pytcad.mesh import graded_mesh
from pytcad.continuation import (
    adaptive_bias_sweep, arc_length_sweep,
    _bordered_corrector_staged, _pack,
)
from pytcad.device import _II_STAGES


def _one_sided(nd_low=1e16, nd_high=1e19):
    x = graded_mesh(6.0e-4, [3.0e-4], h_min=1e-8, h_max=1e-6)
    dop = np.where(x < 3.0e-4, -nd_low, nd_high)
    return x, dop


def _reference_current(v_target):
    """Trusted answer: plain fixed-step iv_sweep, II off."""
    x, dop = _one_sided()
    dev = Device1D(x, dop, T=300.0, models=Models(bgn=False, srh=True))
    dev.solve_equilibrium()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        J = dev.iv_sweep(np.arange(-2.0, v_target - 0.01, -2.0),
                          verbose=False)
    return float(J[-1])


# ---------------------------------------------------------- adaptive
def test_adaptive_matches_fixed_step_reference():
    """G1: adaptive_bias_sweep on an ordinary reverse ramp lands within
    5% of a plain fixed-step iv_sweep at the same target bias."""
    v_target = -20.0
    j_ref = _reference_current(v_target)

    x, dop = _one_sided()
    dev = Device1D(x, dop, T=300.0, models=Models(bgn=False, srh=True))
    dev.solve_equilibrium()
    recs = adaptive_bias_sweep(dev, v_target, -2.0)

    assert recs, "adaptive_bias_sweep produced no accepted steps"
    assert abs(recs[-1]["V"] - v_target) < 1e-9
    rel = abs(recs[-1]["J"] - j_ref) / abs(j_ref)
    assert rel < 0.05, f"adaptive J={recs[-1]['J']:.4e} vs ref={j_ref:.4e}"


def test_adaptive_grows_step_when_easy():
    """G2: on an easy (unfolded) ramp the step should grow past step0,
    not stay pinned at the initial size -- otherwise it is just a
    slower fixed-step sweep wearing an adaptive label."""
    x, dop = _one_sided()
    dev = Device1D(x, dop, T=300.0, models=Models(bgn=False, srh=True))
    dev.solve_equilibrium()
    recs = adaptive_bias_sweep(dev, -20.0, -1.0, max_step=-8.0)
    steps = np.diff([0.0] + [r["V"] for r in recs])
    assert np.abs(steps).max() > 1.0, \
        "adaptive step never grew past its initial size on an easy ramp"


def test_adaptive_retries_from_last_converged_state_not_a_failed_one():
    """G3: a failed attempt must not corrupt the state used for the
    next (smaller) retry.  Forcing an artificially tiny max_dpsi makes
    the very first full-size step fail; the driver must back off and
    still reach the target, warm-started from the ORIGINAL equilibrium
    state, not from whatever the failed Newton iterate left behind."""
    x, dop = _one_sided()
    dev = Device1D(x, dop, T=300.0, models=Models(bgn=False, srh=True))
    dev.solve_equilibrium()
    opts = NewtonOptions(max_dpsi=0.05)  # deliberately tiny -> first try fails
    recs = adaptive_bias_sweep(dev, -6.0, -6.0, opts, min_step=-1e-4)
    assert recs[-1]["V"] == pytest.approx(-6.0, abs=1e-9)
    assert np.isfinite(recs[-1]["J"])


def test_adaptive_raises_rather_than_silently_stalling():
    """G4: an unreachable target (min_step too coarse to ever back off
    enough) must raise, never silently stop and call it done."""
    x, dop = _one_sided()
    dev = Device1D(x, dop, T=300.0, models=Models(bgn=False, srh=True))
    dev.solve_equilibrium()
    opts = NewtonOptions(max_dpsi=1e-6)  # everything fails at this size
    with pytest.raises(RuntimeError):
        adaptive_bias_sweep(dev, -6.0, -6.0, opts, min_step=-3.0)


# ---------------------------------------------------------- arc-length
def test_arc_length_matches_fixed_step_reference():
    """G5: arc_length_sweep on the SAME ordinary (unfolded) ramp lands
    within 10% of the fixed-step reference -- looser than adaptive's
    5% because arc-length overshoots its target slightly by
    construction (it stops at the first accepted step that reaches or
    passes v_end, not exactly on it)."""
    v_target = -20.0
    j_ref = _reference_current(v_target)

    x, dop = _one_sided()
    dev = Device1D(x, dop, T=300.0, models=Models(bgn=False, srh=True))
    dev.solve_equilibrium()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        recs = arc_length_sweep(dev, 0.0, v_target, ds0=10.0, ds_max=200.0,
                                 max_steps=300)

    assert abs(recs[-1]["V"] - v_target) < 2.0, \
        f"arc-length overshot the target by more than 2V: {recs[-1]['V']}"
    rel = abs(recs[-1]["J"] - j_ref) / abs(j_ref)
    assert rel < 0.10, f"arclen J={recs[-1]['J']:.4e} vs ref={j_ref:.4e}"


def test_arc_length_v_progresses_monotonically_off_a_fold():
    """G6: away from any fold, V should still progress monotonically
    toward the target (arc-length CAN retrace past a fold -- see the
    module docstring -- but has no reason to here)."""
    x, dop = _one_sided()
    dev = Device1D(x, dop, T=300.0, models=Models(bgn=False, srh=True))
    dev.solve_equilibrium()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        recs = arc_length_sweep(dev, 0.0, -15.0, ds0=10.0, ds_max=200.0,
                                 max_steps=300)
    Vs = np.array([r["V"] for r in recs])
    assert np.all(np.diff(Vs) <= 1e-9), \
        "V regressed at some point during an unfolded ramp"


def test_arc_length_raises_rather_than_silently_stalling():
    """G7: same honesty requirement as adaptive_bias_sweep's -- a
    corrector that cannot converge even at ds_min must raise."""
    x, dop = _one_sided()
    dev = Device1D(x, dop, T=300.0, models=Models(bgn=False, srh=True))
    dev.solve_equilibrium()
    opts = NewtonOptions(max_dpsi=1e-6)
    with pytest.raises(RuntimeError):
        arc_length_sweep(dev, 0.0, -6.0, ds0=5.0, opts=opts, ds_min=1.0,
                          corrector_max_iter=3)


# ---------------------------------------------- strength_stages (M15 R1b)
def _avalanche_device():
    """One-sided junction with impact ionization on -- the stiff coupled
    term strength_stages exists to navigate (same device family as
    tests/test_m15_ionization.py)."""
    x, dop = _one_sided(1e16, 1e19)
    return Device1D(x, dop, T=300.0,
                     models=Models(bgn=False, srh=True, impact=True))


def test_strength_stages_accepted_state_is_a_full_strength_solution():
    """G8: staging must never accept an under-converged, partially-
    ramped intermediate state as if it were the true full-strength
    answer.  Each RECORDED point must be a genuine solution of the
    device at strength=1.0: re-evaluating device._residual_jacobian at
    that exact (psi, n, p, V) with strength forced to 1.0 must give a
    residual as small as an ordinary full-strength solve would.

    (Note: this codebase's backtracking damping, added to the
    corrector alongside staging, independently fixed R1b attempt 2's
    original stall on its own -- measured, an UNSTAGED damped corrector
    reaches V=-55 on this device without failing.  strength_stages is
    integrated and gated here for correctness and because it is the
    piece the milestone asked for, not because it is the only fix.)
    """
    dev = _avalanche_device()
    dev.solve_equilibrium()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        recs = arc_length_sweep(dev, 0.0, -5.0, ds0=10.0, ds_max=100.0,
                                 max_steps=40, strength_stages=_II_STAGES)
    assert recs[-1]["V"] <= -5.0 + 1e-6

    dev._ii_strength = 1.0
    bc = dev._contact_values([recs[-1]["V"], 0.0])
    F, *_ = dev._residual_jacobian(recs[-1]["psi"], recs[-1]["n"],
                                    recs[-1]["p"], bc)
    assert np.abs(F).max() < 1e-6, (
        f"staged result at V={recs[-1]['V']:.3f} is not a converged "
        f"full-strength solution: max|F|={np.abs(F).max():.3e}")


def test_strength_stages_restores_full_strength_after_a_failed_stage():
    """G9: if a LATER stage in the ladder fails to converge, the whole
    staged attempt must report failure (never accept a partially-ramped
    intermediate state as if it were the true, full-strength solution),
    AND the device's strength attribute must be restored to the
    ladder's last (full-strength) value regardless -- a failed attempt
    must never leave a stale partial-strength value for whatever runs
    next (the caller's retry at a smaller ds, or unrelated code)."""
    dev = _avalanche_device()
    dev.solve_equilibrium()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dev.solve_bias([-2.0, 0.0], NewtonOptions())
    assert dev.last_converged

    u_prev = _pack(dev.psi, dev.n, dev.p)
    V_prev = -2.0
    t_u = np.zeros_like(u_prev)
    t_u[0::3] = 1.0
    t_norm = np.linalg.norm(np.concatenate([t_u, [1.0]]))
    t_u, t_V = t_u / t_norm, 1.0 / t_norm
    c_vec = np.zeros_like(u_prev)
    c_vec[0] = -1.0 / dev.VT

    def bc_at(v):
        return dev._contact_values([v, 0.0])

    opts = NewtonOptions()
    # corrector_max_iter=0 guarantees every stage's Newton loop exits
    # having done zero iterations, i.e. never converges -- a controlled
    # way to force a mid-ladder failure without depending on physics.
    u, V, ok, n_iter, jn_jp = _bordered_corrector_staged(
        dev, u_prev, V_prev, u_prev, V_prev, t_u, t_V, ds=1.0,
        c_vec=c_vec, bc_at=bc_at, opts=opts, tol=1e-8, max_iter=0,
        strength_stages=_II_STAGES, strength_attr="_ii_strength")

    assert not ok, "corrector_max_iter=0 must never report convergence"
    assert jn_jp is None
    assert dev._ii_strength == _II_STAGES[-1], (
        f"a failed staged attempt left device._ii_strength="
        f"{dev._ii_strength}, expected it restored to the ladder's "
        f"full-strength value {_II_STAGES[-1]}")


def test_arc_length_staged_raises_rather_than_silently_stalling():
    """G10: the staged corrector path must honor the same honesty
    contract as the unstaged one (G7) -- a ladder that can never
    converge (here: zero corrector iterations allowed) must raise,
    never silently stop and report success."""
    dev = _avalanche_device()
    dev.solve_equilibrium()
    with pytest.raises(RuntimeError):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            arc_length_sweep(dev, 0.0, -20.0, ds0=5.0, ds_min=1.0,
                              max_steps=10, corrector_max_iter=0,
                              strength_stages=_II_STAGES)
