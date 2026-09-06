"""M30 Phase 2 acceptance tests: calibration / optimization loop.

Contract under test (workbench/calibration.py):
  - `GoalFunction` wraps a reference array (any fixed-length numeric
    field, e.g. an equilibrium potential profile) and an RMS error
    against a trial's array of the same field.
  - `calibrate(template_id, base_values, free_params, goal, ...)` drives
    scipy's Nelder-Mead simplex over `free_params`, each trial building
    a device through the SAME template path Phase 1's splits use and
    solving it through the EXISTING solver pipeline
    (gui.services.solver_runner.run_job) -- no reimplemented physics,
    no faked results.
  - A trial the template/solver rejects is penalized, not raised --
    the optimizer must survive an unreachable region of parameter
    space instead of crashing.
  - When NO trial across the whole search ever solves successfully
    (a goal that is unreachable for reasons the free parameters can't
    fix), the result is honestly reported as not converged.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from workbench.calibration import (
    GoalFunction, UNREACHABLE_PENALTY, calibrate, solve_field,
)


# ----------------------------------------------------------------------
#  GoalFunction: unit-tested standalone against hand-computed values
# ----------------------------------------------------------------------
def test_goal_function_rms_error_hand_computed():
    goal = GoalFunction(reference=np.array([1.0, 2.0, 3.0]))
    # trial - reference = [1, 1, 1] -> RMS = 1.0
    assert goal.error(np.array([2.0, 3.0, 4.0])) == pytest.approx(1.0)
    # exact match -> zero error
    assert goal.error(np.array([1.0, 2.0, 3.0])) == pytest.approx(0.0)


def test_goal_function_rejects_shape_mismatch():
    goal = GoalFunction(reference=np.array([1.0, 2.0, 3.0]))
    with pytest.raises(ValueError, match="shape mismatch"):
        goal.error(np.array([1.0, 2.0]))


# ----------------------------------------------------------------------
#  G-RECOVER: the load-bearing gate -- optimizer recovers a planted
#  parameter (ARCHITECTURE.md's own M30 acceptance language), using the
#  equilibrium potential profile of a pn_diode as the reference "curve"
#  (equilibrium-only per Phase 2's scope: no bias sweep needed).
# ----------------------------------------------------------------------
_BASE = {"length_cm": 1e-4, "height_cm": 2e-5, "nx": 20, "ny": 6,
         "v_p": 0.0, "v_n": 0.0}
_PLANTED_NA = -3e18


@pytest.fixture(scope="module")
def planted_reference(tmp_path_factory):
    work_dir = str(tmp_path_factory.mktemp("m30-calib-ref"))
    values = dict(_BASE, na_cm3=_PLANTED_NA, nd_cm3=1e18)
    return solve_field("pn_diode", values, "field__potential", work_dir)


def test_calibrate_recovers_planted_na_cm3(planted_reference, tmp_path):
    goal = GoalFunction(reference=planted_reference, field="field__potential")
    base_values = dict(_BASE, nd_cm3=1e18)   # na_cm3 deliberately omitted
    result = calibrate(
        "pn_diode", base_values, ["na_cm3"], goal,
        x0={"na_cm3": -1e18},                # perturbed initial guess
        work_dir=str(tmp_path))

    assert result.converged
    recovered = result.best_params["na_cm3"]
    assert recovered == pytest.approx(_PLANTED_NA, rel=0.03)
    assert result.error < 1e-3
    assert result.n_iterations > 0
    assert len(result.trace) > 0


# ----------------------------------------------------------------------
#  G-NOCONVERGE: an unreachable goal (wrong-shaped reference no value
#  of the free parameter can ever produce, since mesh size is fixed and
#  not a free parameter) reports honest non-convergence, never a
#  fabricated "best fit."
# ----------------------------------------------------------------------
def test_calibrate_reports_honest_nonconvergence_for_unreachable_goal(tmp_path):
    unreachable = GoalFunction(reference=np.zeros(999), field="field__potential")
    base_values = dict(_BASE, nd_cm3=1e18)
    result = calibrate(
        "pn_diode", base_values, ["na_cm3"], unreachable,
        x0={"na_cm3": -1e18}, max_iter=20, work_dir=str(tmp_path))

    assert not result.converged
    assert result.error >= UNREACHABLE_PENALTY
    assert all(t["failed"] for t in result.trace)


def test_calibrate_penalizes_but_does_not_crash_on_out_of_range_trial(tmp_path):
    """An out-of-range trial (template.build() rejects it) must be
    penalized like any other unreachable point, not propagate an
    exception out of the optimizer."""
    goal = GoalFunction(reference=np.ones(4), field="field__potential")
    base_values = dict(_BASE, nd_cm3=1e18)
    # na_cm3's template bound is [-1e21, 1e21]; force an immediate,
    # deliberately out-of-bounds x0 to exercise the guard on the very
    # first evaluation.
    result = calibrate(
        "pn_diode", base_values, ["na_cm3"], goal,
        x0={"na_cm3": -5e21}, max_iter=5, work_dir=str(tmp_path))
    assert result.trace[0]["failed"] is True
    assert result.trace[0]["error"] == UNREACHABLE_PENALTY
