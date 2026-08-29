"""Grading guarantee of mesh.graded_mesh.

graded_mesh's docstring promises that adjacent cells never differ by
more than `ratio`.  It did not hold: the old forward walk clamped each
step onto the next focus point and onto L, and every clamp left a stub
cell.  Measured before the fix: up to 11.06x against a stated 1.15, with
the worst jump of the whole mesh landing on the ohmic contact cell --
where the docstring's own warning about degraded second-order accuracy
bites hardest.

These gates pin the promise so it cannot silently rot again.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pytcad.mesh import graded_mesh


def _worst_grading(x):
    h = np.diff(x)
    if h.size < 2:
        return 1.0
    return float(np.maximum(h[1:] / h[:-1], h[:-1] / h[1:]).max())


def test_graded_mesh_honours_its_ratio_under_fuzz():
    """Over randomised geometries, the realised grading never exceeds
    the requested ratio."""
    rng = np.random.default_rng(7)
    worst = 0.0
    for trial in range(400):
        L = 10.0 ** rng.uniform(-5, -2)
        ratio = float(rng.uniform(1.05, 1.6))
        h_min = L * 10 ** rng.uniform(-4, -2)
        h_max = min(L, h_min * 10 ** rng.uniform(0.3, 3))
        focus = [float(rng.uniform(0, L))]
        if rng.random() < 0.3:
            focus.append(float(rng.uniform(0, L)))

        x = graded_mesh(L, focus, h_min, h_max, ratio)

        assert x[0] == 0.0, f"trial {trial}: left endpoint moved"
        assert abs(x[-1] - L) <= 1e-18 * max(L, 1.0), \
            f"trial {trial}: right endpoint {x[-1]!r} != {L!r}"
        assert np.all(np.diff(x) > 0), f"trial {trial}: not increasing"
        g = _worst_grading(x)
        assert g <= ratio * (1.0 + 1e-9), \
            f"trial {trial}: grading {g:.6f} exceeds requested {ratio:.6f}"
        worst = max(worst, g / ratio)
    assert worst <= 1.0 + 1e-9


def test_no_stub_cell_at_the_contacts_or_the_focus():
    """The regression that motivated the fix: the FINAL cell (the ohmic
    contact cell) and the cells straddling a focus point must not be
    stubs."""
    for L, xf, h_min, h_max, ratio in (
            (2.0e-4, 1.0e-4, 1.0e-8, 1.0e-6, 1.12),
            (6.0e-4, 3.0e-4, 1.0e-7, 1.0e-5, 1.15),
            (2.0e-4, 1.0e-4, 1.0e-8, 5.0e-7, 1.15)):
        x = graded_mesh(L, [xf], h_min, h_max, ratio)
        h = np.diff(x)
        assert h[-1] >= h[-2] / ratio - 1e-30, \
            f"stub contact cell: h[-1]={h[-1]:.3e} vs h[-2]={h[-2]:.3e}"
        assert h[0] >= h[1] / ratio - 1e-30, "stub cell at x=0"
        assert _worst_grading(x) <= ratio * (1.0 + 1e-9)


def test_endpoints_and_monotonicity_for_degenerate_inputs():
    """Focus on a boundary, focus outside the domain, h_max below h_min."""
    for focus in (0.0, 1.0e-4, -5.0, 1.0):
        x = graded_mesh(1.0e-4, [focus], 1e-7, 1e-6, 1.2)
        assert x[0] == 0.0 and abs(x[-1] - 1.0e-4) <= 1e-18
        assert np.all(np.diff(x) > 0)
    x = graded_mesh(1.0e-4, [5e-5], 1e-6, 1e-9, 1.2)   # h_max < h_min
    assert np.all(np.diff(x) > 0) and x[0] == 0.0
