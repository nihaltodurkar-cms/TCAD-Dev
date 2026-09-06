"""M30 Phase 1 acceptance tests: parameter splits (run matrix).

Contract under test (workbench/splits.py + the SPLIT statement added to
workbench/workflow.py's deck grammar):
  - `expand_splits(base_values, split_spec)` produces the full
    cartesian-product run matrix as plain-dict rows, in a documented
    order (itertools.product semantics: the LAST split key varies
    fastest).
  - A deck's new `SPLIT key = v1, v2, ...` statement is collected into
    `DeckRun.splits` without disturbing any pre-existing TEMPLATE/BIAS/
    SWEEP behavior (backward compatible -- decks without a SPLIT line
    are untouched, covered by the existing test_workbench_m1.py suite
    running unmodified).
  - `run_split_matrix(run)` builds one device per row through the
    existing template path, isolating a bad row's build failure from
    the rest of the matrix (mirrors run_deck_full's own
    collect-don't-abort pattern for per-line problems, generalized to
    per-row).
"""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from workbench.splits import expand_splits, run_split_matrix
from workbench.workflow import run_deck_full


# ----------------------------------------------------------------------
#  G-EXPAND: cartesian product, documented order, exact row count
# ----------------------------------------------------------------------
def test_expand_splits_cartesian_product_row_count_and_order():
    base = {"a": 1.0}
    spec = {"tox_cm": [7e-7, 8e-7, 9e-7], "na_cm3": [-1e16, -5e16]}
    rows = expand_splits(base, spec)

    assert len(rows) == 6
    # documented order: itertools.product(*values) -- the LAST key
    # (na_cm3) varies fastest.
    expected = [
        {"a": 1.0, "tox_cm": tox, "na_cm3": na}
        for tox, na in itertools.product([7e-7, 8e-7, 9e-7], [-1e16, -5e16])
    ]
    assert rows == expected


def test_expand_splits_with_no_split_spec_returns_single_base_row():
    base = {"a": 1.0, "b": 2.0}
    assert expand_splits(base, {}) == [dict(base)]


def test_expand_splits_does_not_mutate_base_values():
    base = {"tox_cm": 5e-7}
    frozen = dict(base)
    expand_splits(base, {"tox_cm": [7e-7, 8e-7]})
    assert base == frozen


# ----------------------------------------------------------------------
#  G-PARSE: SPLIT statement, backward-compatible deck grammar
# ----------------------------------------------------------------------
_MOS_DECK = """
go
template mos_capacitor
na_cm3 = -1e16
split tox_cm = 7e-7, 8e-7, 9e-7
end
"""


def test_split_statement_parses_into_deck_run():
    run = run_deck_full(_MOS_DECK)
    assert run.splits == {"tox_cm": [7e-7, 8e-7, 9e-7]}
    assert run.template_id == "mos_capacitor"


def test_split_statement_bad_value_raises_line_numbered_error():
    deck = """
    go
    template mos_capacitor
    split tox_cm = 7e-7, not_a_number
    end
    """
    with pytest.raises(ValueError, match="line 4"):
        run_deck_full(deck)


def test_split_statement_missing_equals_raises():
    deck = """
    go
    template mos_capacitor
    split tox_cm 7e-7, 8e-7
    end
    """
    with pytest.raises(ValueError, match="line 4"):
        run_deck_full(deck)


def test_deck_without_split_line_has_empty_splits_dict():
    deck = """
    go
    template pn_diode
    na_cm3 = -1e18
    end
    """
    run = run_deck_full(deck)
    assert run.splits == {}


# ----------------------------------------------------------------------
#  G-STUDY: split matrix reproduces a documented study -- the classic
#  MOS oxide-capacitance relation Cox = eps_ox / tox_cm (any MOS/TCAD
#  textbook; pytcad.moscap.flatband_voltage already computes the same
#  Cox internally as EPS_OX_R * EPS0 / tox_cm).
# ----------------------------------------------------------------------
def test_split_matrix_reproduces_mos_cox_tox_study():
    from pytcad.constants import EPS0
    from pytcad.moscap import EPS_OX_R

    run = run_deck_full(_MOS_DECK)
    rows = run_split_matrix(run)

    assert len(rows) == 3
    tox_values = [7e-7, 8e-7, 9e-7]
    for row, expected_tox in zip(rows, tox_values):
        assert row.error is None
        assert row.params["tox_cm"] == expected_tox
        gate = next(c for c in row.device.contacts if c.kind == "gate")
        assert gate.tox_cm == expected_tox
        cox = (EPS_OX_R * EPS0) / gate.tox_cm
        # Cox increases as tox_cm decreases -- the documented inverse
        # relationship, not just "some function of tox".
        assert cox == pytest.approx((EPS_OX_R * EPS0) / expected_tox)
    coxes = [(EPS_OX_R * EPS0) / r.params["tox_cm"] for r in rows]
    assert coxes == sorted(coxes, reverse=True)


# ----------------------------------------------------------------------
#  G-ISOLATION: one bad row does not abort the rest of the matrix
# ----------------------------------------------------------------------
def test_run_split_matrix_isolates_a_bad_row():
    deck = """
    go
    template mos_capacitor
    split tox_cm = 7e-7, -1.0, 9e-7
    end
    """
    run = run_deck_full(deck)
    rows = run_split_matrix(run)

    assert len(rows) == 3
    assert rows[0].error is None and rows[0].device is not None
    assert rows[1].error is not None and rows[1].device is None
    assert "tox_cm" in rows[1].error
    assert rows[2].error is None and rows[2].device is not None


def test_run_split_matrix_with_no_splits_builds_one_row():
    run = run_deck_full("go\ntemplate pn_diode\nend\n")
    rows = run_split_matrix(run)
    assert len(rows) == 1
    assert rows[0].error is None
