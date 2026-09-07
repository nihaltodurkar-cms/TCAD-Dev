"""M30 Phase 10 acceptance tests: parameter constraints.

Contract under test (workbench/constraints.py + the optional
`constraints` argument on workbench.splits.run_split_matrix and
workbench.calibration.calibrate):
  - Constraint parses a bounded 'PARAM OP PARAM' / 'PARAM OP NUMBER'
    vocabulary; an unparseable expression raises ValueError naming it.
  - run_split_matrix(run, constraints=...) drops exactly the rows that
    violate a constraint, marking them distinctly
    (SplitRow.constraint_violation) from a template build error
    (SplitRow.error) -- and constraints=None (the default) leaves
    Phase 1's own behavior untouched.
  - calibrate(..., constraints=...) never calls template.build()/the
    solver for an out-of-constraint trial point -- it is penalized
    immediately.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from workbench.calibration import UNREACHABLE_PENALTY, GoalFunction, calibrate
from workbench.constraints import Constraint, first_violation, parse_constraints
from workbench.splits import run_split_matrix
from workbench.workflow import run_deck_full


# ----------------------------------------------------------------------
#  Constraint parsing / evaluation
# ----------------------------------------------------------------------
def test_constraint_param_vs_param():
    c = Constraint("lg_cm < width_cm")
    assert c.check({"lg_cm": 1.0, "width_cm": 2.0}) is True
    assert c.check({"lg_cm": 3.0, "width_cm": 2.0}) is False


def test_constraint_param_vs_numeric_literal():
    c = Constraint("tox_cm >= 1e-7")
    assert c.check({"tox_cm": 2e-7}) is True
    assert c.check({"tox_cm": 5e-8}) is False


@pytest.mark.parametrize("op,a,b,expected", [
    ("==", 2.0, 2.0, True), ("==", 2.0, 3.0, False),
    ("!=", 2.0, 3.0, True), ("!=", 2.0, 2.0, False),
    ("<=", 2.0, 2.0, True), (">=", 2.0, 2.0, True),
])
def test_all_comparison_operators(op, a, b, expected):
    c = Constraint(f"a {op} b")
    assert c.check({"a": a, "b": b}) is expected


def test_constraint_rejects_unparseable_expression():
    with pytest.raises(ValueError, match="unsupported constraint"):
        Constraint("lg_cm between width_cm and 2")


def test_constraint_check_raises_on_unknown_parameter():
    c = Constraint("lg_cm < width_cm")
    with pytest.raises(KeyError, match="width_cm"):
        c.check({"lg_cm": 1.0})


def test_first_violation_returns_expr_of_first_failing_constraint():
    constraints = ["a < b", "a > 0"]
    assert first_violation({"a": -1.0, "b": 2.0}, constraints) == "a > 0"
    assert first_violation({"a": 1.0, "b": 2.0}, constraints) is None


# ----------------------------------------------------------------------
#  G-FILTER: constraints drop exactly the violating rows; constraints=
#  None leaves Phase 1's own behavior unchanged
# ----------------------------------------------------------------------
_HEMT_DECK = """
go
template hemt
split lg_cm = 1e-5, 3e-5, 6e-5
end
"""


def test_run_split_matrix_filters_rows_violating_a_constraint():
    run = run_deck_full(_HEMT_DECK)
    # width_cm default is 5e-5 -- lg_cm=6e-5 violates "lg_cm < width_cm"
    rows = run_split_matrix(run, constraints=["lg_cm < width_cm"])
    assert len(rows) == 3
    assert rows[0].constraint_violation is None and rows[0].device is not None
    assert rows[1].constraint_violation is None and rows[1].device is not None
    assert rows[2].constraint_violation == "lg_cm < width_cm"
    assert rows[2].device is None and rows[2].error is None


def test_run_split_matrix_constraints_default_is_backward_compatible():
    run = run_deck_full(_HEMT_DECK)
    with_none = run_split_matrix(run, constraints=None)
    without_arg = run_split_matrix(run)
    assert len(with_none) == len(without_arg) == 3
    for a, b in zip(with_none, without_arg):
        assert a.params == b.params and a.error == b.error
        assert a.constraint_violation is None and b.constraint_violation is None


# ----------------------------------------------------------------------
#  G-DISTINCT-STATUS: constraint exclusion is a DIFFERENT signal from a
#  template build error
# ----------------------------------------------------------------------
def test_constraint_violation_is_distinct_from_build_error():
    deck = """
    go
    template mos_capacitor
    split tox_cm = 8e-7, -1.0
    end
    """
    run = run_deck_full(deck)
    # tox_cm >= 0 excludes the (already build-invalid) -1.0 row via a
    # constraint too, to prove the two failure kinds don't collapse
    # into the same field on the SAME row.
    rows = run_split_matrix(run, constraints=["tox_cm >= 0"])
    assert rows[0].constraint_violation is None and rows[0].error is None
    assert rows[1].constraint_violation == "tox_cm >= 0"
    assert rows[1].error is None          # never reached template.build()

    # without the constraint, that same bad row surfaces as a build
    # error instead -- proving the two statuses are genuinely different
    # code paths, not just different labels on one path.
    rows_unconstrained = run_split_matrix(run)
    assert rows_unconstrained[1].constraint_violation is None
    assert rows_unconstrained[1].error is not None


# ----------------------------------------------------------------------
#  G-CALIBRATION-PENALTY: an out-of-constraint trial never reaches the
#  solver
# ----------------------------------------------------------------------
_BASE = {"length_cm": 1e-4, "height_cm": 2e-5, "nx": 16, "ny": 6,
         "nd_cm3": 1e18}


def test_calibrate_never_solves_an_out_of_constraint_trial(tmp_path, monkeypatch):
    import workbench.calibration as calib_module

    calls = []
    real_solve_field = calib_module.solve_field

    def _spy(*args, **kwargs):
        calls.append(args)
        return real_solve_field(*args, **kwargs)
    monkeypatch.setattr(calib_module, "solve_field", _spy)

    goal = GoalFunction(reference=__import__("numpy").ones(4))
    # na_cm3 forced to a value the constraint always rejects, at x0
    # itself, so a single objective() call already proves the guard.
    result = calibrate(
        "pn_diode", _BASE, ["na_cm3"], goal,
        x0={"na_cm3": -5e18}, max_iter=3, work_dir=str(tmp_path),
        constraints=["na_cm3 >= 0"])   # na_cm3 is always negative here

    assert not calls, "solve_field was called for an out-of-constraint trial"
    assert result.trace[0]["failed"] is True
    assert result.trace[0]["error"] == UNREACHABLE_PENALTY
    assert result.trace[0]["constraint_violation"] == "na_cm3 >= 0"
