"""M23 acceptance gates: 2D process geometry engine (structured-mesh,
string-model slice -- see pytcad/process2d.py module docstring for the
honesty clause on what is NOT modeled).

Gates, per ARCHITECTURE.md's M23 spec and Architecture_Master_Plan.md
Phase 14:
  G1 (exact)       -- uniform oxidation recovers 1D Deal-Grove bit-for-bit.
                       Covered in test_model_benchmarks.py (kept there per
                       house rule: new model gates land in the benchmark
                       file first).
  G2 (exact)       -- mass conservation of moved material to machine
                       precision. Oxidation case in test_model_benchmarks.py;
                       deposit/etch round-trip case here.
  G3 (qualitative) -- bird's-beak geometry: monotonic taper from open-rate
                       to masked-rate oxide thickness across a mask edge,
                       honestly labeled qualitative (no published
                       cross-section comparison is attempted).
  G4 (qualitative) -- mask-driven 2D implant: dose is (numerically)
                       conserved and lateral spread grows monotonically
                       with the lateral-straggle knob, i.e. the mask-edge
                       encroachment behaves as SUPREM-style 2D moments
                       would predict qualitatively.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from pytcad.process2d import (
    ProcessGeometry2D, deposit, etch, oxidize_2d, implant_2d,
    mask_from_intervals, total_dose_2d,
)


# ----------------------------------------------------------------------
#  G2 -- deposit/etch round trip
# ----------------------------------------------------------------------
def test_deposit_then_etch_round_trip_conserves_thickness_exactly():
    x = np.linspace(0.0, 5e-4, 11)
    geom = ProcessGeometry2D(x)
    g1 = deposit(geom, thickness_um=0.5)
    g2 = etch(g1, depth_um=0.5)
    assert np.allclose(g2.surface_um, geom.surface_um, rtol=0, atol=1e-13)


def test_deposit_etch_respect_the_open_mask():
    x = np.linspace(0.0, 10e-4, 21)
    mask = mask_from_intervals(x, [(0.0, 4e-4)])
    geom = ProcessGeometry2D(x)
    g = deposit(geom, thickness_um=1.0, mask=mask)
    assert np.all(g.surface_um[mask] == 1.0)
    assert np.all(g.surface_um[~mask] == 0.0)


# ----------------------------------------------------------------------
#  G3 -- bird's beak taper
# ----------------------------------------------------------------------
def test_birds_beak_tapers_monotonically_from_open_to_masked():
    """Across a single mask edge, oxide thickness should fall
    monotonically from the full open-field value to the suppressed
    masked value -- the qualitative signature of bird's-beak encroachment.
    Not compared to a published cross-section (see honesty clause)."""
    x = np.linspace(0.0, 20e-4, 201)
    mask = mask_from_intervals(x, [(0.0, 10e-4)])   # open on the left half
    geom = ProcessGeometry2D(x)
    out = oxidize_2d(geom, T_C=1000.0, t_hours=1.0, ambient="dry", mask=mask)

    # Look at a window straddling the edge at x = 10e-4.
    edge = 10e-4
    window = (x > edge - 3e-4) & (x < edge + 3e-4)
    xw, tw = x[window], out.ox_thick_um[window]
    order = np.argsort(xw)
    tw_sorted = tw[order]
    diffs = np.diff(tw_sorted)
    # Allow flat spots (rounding) but no *increase* moving from open into
    # the masked side.
    assert np.all(diffs <= 1e-12), "oxide thickness must not increase across the taper"

    open_thick = out.ox_thick_um[mask].max()
    deep_masked_thick = out.ox_thick_um[~mask][-1]   # far from the edge
    assert deep_masked_thick < open_thick
    assert deep_masked_thick > 0.0   # field growth under nitride is small, not zero


def test_masked_rate_fraction_controls_field_oxide_thickness():
    x = np.linspace(0.0, 30e-4, 61)
    mask = mask_from_intervals(x, [(0.0, 5e-4)])
    geom = ProcessGeometry2D(x)
    low = oxidize_2d(geom, 1000.0, 1.0, "dry", mask=mask, masked_rate_fraction=0.01)
    high = oxidize_2d(geom, 1000.0, 1.0, "dry", mask=mask, masked_rate_fraction=0.10)
    # far-field (away from any edge) masked thickness should scale with
    # the requested masked_rate_fraction.
    assert high.ox_thick_um[~mask][-1] > low.ox_thick_um[~mask][-1]


# ----------------------------------------------------------------------
#  G4 -- mask-driven 2D implant
# ----------------------------------------------------------------------
def test_implant_2d_dose_is_conserved_under_open_mask():
    x = np.linspace(-10e-4, 10e-4, 101)
    y = np.linspace(0.0, 2e-4, 401)
    geom = ProcessGeometry2D(x)
    dose = 1e14
    C = implant_2d(x, y, geom, "P", 50, dose, mask=None, lateral_straggle_ratio=0.0)
    # No lateral spreading: every column should integrate (over depth) to
    # very nearly the nominal dose.
    per_col = np.trapezoid(C, y, axis=0)
    assert np.allclose(per_col, dose, rtol=2e-2)


def test_implant_2d_lateral_spread_grows_with_the_straggle_ratio():
    x = np.linspace(-10e-4, 10e-4, 201)
    y = np.linspace(0.0, 2e-4, 201)
    mask = mask_from_intervals(x, [(-10e-4, 0.0)])   # open on the left only
    geom = ProcessGeometry2D(x)

    def lateral_extent(ratio):
        C = implant_2d(x, y, geom, "As", 30, 1e13, mask=mask,
                        lateral_straggle_ratio=ratio)
        # dose profile just past the mask edge (x>0, nominally zero
        # without lateral spread)
        per_col = np.trapezoid(C, y, axis=0)
        past_edge = per_col[x > 0]
        return float(past_edge.max())

    assert lateral_extent(0.0) < lateral_extent(0.5) < lateral_extent(1.2)


def test_implant_2d_is_blocked_outside_the_open_mask_with_no_spreading():
    x = np.linspace(-5e-4, 5e-4, 51)
    y = np.linspace(0.0, 1e-4, 51)
    mask = mask_from_intervals(x, [(-5e-4, 0.0)])
    geom = ProcessGeometry2D(x)
    C = implant_2d(x, y, geom, "B", 20, 1e13, mask=mask, lateral_straggle_ratio=0.0)
    assert np.all(C[:, x > 0] == 0.0)


def test_total_dose_2d_is_finite_and_positive():
    x = np.linspace(-5e-4, 5e-4, 51)
    y = np.linspace(0.0, 1e-4, 51)
    geom = ProcessGeometry2D(x)
    C = implant_2d(x, y, geom, "B", 20, 1e13)
    d = total_dose_2d(x, y, C)
    assert np.isfinite(d) and d > 0.0
