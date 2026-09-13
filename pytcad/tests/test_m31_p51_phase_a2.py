"""M31 P5-1 Phase A-2 gates -- the `select_auto` cells Phase A never
measured.

Plan and every measured number:
`pytcad/M31-P5-1-SOLVER-SELECTION-PLAN.md`, "Phase A-2".

THE LOAD-BEARING GATE IN THIS FILE IS `test_a2_no_default_moved`.
Phase A-2 only ever ADDS measured cells to `linsolve._AUTO_EVIDENCE`,
which changes what `linsolve="auto"` resolves to and nothing else.
`NewtonOptions.linsolve` still defaults to `"direct"`, so no existing
caller's behaviour moves and no golden can shift. E-auto -- actually
changing that default -- is a separate proposal with its own sign-off
(plan section 4, Phase E), and this gate is what makes "Phase A-2 did
not quietly take E-auto" checkable rather than asserted.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad import linsolve
from pytcad.device import NewtonOptions


# Every (dim, unstructured, coupled) that has a real `select_auto`
# dispatch site in the tree, with the call site that reaches it.
# Derived by grepping select_auto, not from memory -- see the plan's
# Phase A-2 table.
DISPATCH_CELLS = {
    (1, False, True): "device.py Device1D.solve_bias",
    (2, False, True): "device2d.py Device2D.solve_bias",
    (3, False, False): "device3d.py Device3D.solve_equilibrium",
    (3, False, True): "device3d.py Device3D.solve_bias",
    (2, True, False): "unstructured_poisson.solve_poisson_equilibrium",
    (2, True, True): "unstructured_dd.solve_bias",
    (3, True, False): "unstructured_dd3d equilibrium sub-solve",
    (3, True, True): "unstructured_dd3d.solve_bias3d",
}


def test_a2_default_is_the_signed_off_e_auto():
    """Phase E-auto (default linsolve "direct" -> "auto") landed
    2026-09-13 with explicit user sign-off -- this test used to be
    named test_a2_no_default_moved and guarded against taking E-auto
    BY ACCIDENT before that sign-off existed; it now records that the
    sign-off happened, rather than that it never will."""
    opts = NewtonOptions()
    assert opts.linsolve == "auto"
    # The two Phase B fields must still reproduce the pre-P5-1
    # hardcoding exactly -- E-auto only touches `linsolve` itself.
    assert opts.block_size == 3
    assert opts.precond == "auto"


def test_a2_every_dispatch_site_has_an_opinion():
    """After Phase A-2 every cell a caller can actually REACH through
    `auto` is backed by a measurement -- the refusal path is no longer
    load-bearing for real code, only for hypothetical combinations."""
    missing = [cell for cell in DISPATCH_CELLS
               if cell not in linsolve._AUTO_EVIDENCE]
    assert not missing, (
        f"these reachable cells still have no measured entry: "
        f"{[(c, DISPATCH_CELLS[c]) for c in missing]}")


def test_a2_refusal_path_is_still_alive():
    """Gate D-3 must not have been defeated by filling the table in:
    a combination that does not exist in the tree still refuses."""
    method, reason = linsolve.select_auto(dim=1, unstructured=True,
                                          coupled=True, dof=10**6)
    assert method == "direct"
    assert "no Phase A measurement" in reason


@pytest.mark.parametrize("cell", sorted(linsolve._AUTO_EVIDENCE))
def test_a2_every_entry_names_its_evidence(cell):
    """Gate D-2: a reason always names a real benchmark case, never
    'trust me'."""
    entry = linsolve._AUTO_EVIDENCE[cell]
    reason = entry["reason"]
    assert reason and isinstance(reason, str)
    assert any(tag in reason for tag in
               ("B2", "B3", "B4", "B8", "B9", "S3D", "U2DP",
                "U3DP")), reason
    assert entry["method"] in linsolve._METHODS
    assert entry["min_dof"] >= 0


@pytest.mark.parametrize("cell", sorted(linsolve._AUTO_EVIDENCE))
def test_a2_below_the_measured_floor_refuses(cell):
    """No extrapolation below the smallest size actually measured."""
    dim, unstructured, coupled = cell
    entry = linsolve._AUTO_EVIDENCE[cell]
    if entry["min_dof"] == 0:
        pytest.skip("cell measured down to any size (direct wins there)")
    method, reason = linsolve.select_auto(
        dim, unstructured, coupled, dof=entry["min_dof"] - 1)
    assert method == "direct"
    assert "refusing to extrapolate" in reason
    at_floor, _ = linsolve.select_auto(
        dim, unstructured, coupled, dof=entry["min_dof"])
    assert at_floor == entry["method"]
