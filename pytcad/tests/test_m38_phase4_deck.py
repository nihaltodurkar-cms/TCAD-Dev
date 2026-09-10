"""M38 Phase 4: the EXTRACT deck statement in workbench/workflow.py.

Plan: `M38-PHASE4-PLAN.md` section 2/3. PARSE-ONLY: `run_deck_full`
stores `{"model": ..., "scale": ...}` on `DeckRun.extract` and
validates the model name/scale, but nothing here drives batch/study
execution -- that is explicitly out of scope for this slice.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from workbench.workflow import run_deck_full

_BASE = """
go
template nmos
lsd_cm = 3e-5
lg_cm = 6e-5
bias source = 0.0
bias drain = 0.05
bias body = 0.0
{extra}
end
"""


def test_no_extract_line_leaves_extract_none():
    run = run_deck_full(_BASE.format(extra=""))
    assert run.extract is None


def test_extract_diode_parses():
    run = run_deck_full(_BASE.format(extra="extract model=diode scale=1e-4"))
    assert run.extract == {"model": "diode", "scale": 1e-4}


def test_extract_mosfet1_parses_case_insensitively():
    run = run_deck_full(_BASE.format(
        extra="EXTRACT model=MOSFET1 scale=2.5e-5"))
    assert run.extract == {"model": "mosfet1", "scale": 2.5e-5}


def test_extract_unknown_model_raises_with_line_number():
    with pytest.raises(ValueError, match=r"line 9.*EXTRACT model"):
        run_deck_full(_BASE.format(extra="extract model=bsim scale=1.0"))


def test_extract_non_positive_scale_raises():
    with pytest.raises(ValueError, match="positive"):
        run_deck_full(_BASE.format(extra="extract model=diode scale=-1.0"))


def test_extract_missing_argument_raises():
    with pytest.raises(ValueError, match="missing"):
        run_deck_full(_BASE.format(extra="extract model=diode"))


def test_duplicate_extract_statement_raises():
    with pytest.raises(ValueError, match="duplicate EXTRACT"):
        run_deck_full(_BASE.format(
            extra="extract model=diode scale=1e-4\n"
                  "extract model=mosfet1 scale=1e-4"))
