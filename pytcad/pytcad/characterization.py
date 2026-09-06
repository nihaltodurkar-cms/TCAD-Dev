"""Solver-independent Id-Vg sweep post-processing: Vth, subthreshold
swing, DIBL.

These are pure array-in/array-out functions with no pytcad-core
dependency of their own (only numpy) -- used by finfet3d.py's M26
acceptance gate. gui/services/characterization.py implements the same
extraction algorithms for the GUI's Virtual Probe Station panel;
deliberately duplicated (rather than imported) here because pytcad
core must not depend on gui (see tests/test_m21_phase2.py's own
dependency-direction check) and gui already cannot be imported from
here. Keep both in sync if the extraction algorithm changes.
"""

import math

import numpy as np

__all__ = [
    "extract_vth_constant_current",
    "extract_subthreshold_swing",
    "extract_dibl",
]


def _prepare(x, y):
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    mask = np.isfinite(xa) & np.isfinite(ya)
    xa, ya = xa[mask], ya[mask]
    order = np.argsort(xa)
    return xa[order], ya[order]


def extract_vth_constant_current(vg, ids, target=1.0e-7):
    """Threshold voltage at a fixed drain-current criterion (linear
    interpolation between the bracketing sweep points)."""
    v, i = _prepare(vg, ids)
    if v.size < 2 or target <= 0.0:
        return float("nan")
    pos = i > 0.0
    if not np.any(pos):
        return float("nan")
    v, i = v[pos], i[pos]
    if float(np.max(i)) < target:
        return float("nan")
    idx = int(np.argmax(i >= target))
    if idx == 0:
        return float(v[0])
    if i[idx] == target:
        return float(v[idx])
    x0, x1, y0, y1 = v[idx - 1], v[idx], i[idx - 1], i[idx]
    if y1 == y0:
        return float(x1)
    return float(x0 + (target - y0) * (x1 - x0) / (y1 - y0))


def extract_subthreshold_swing(vg, ids, current_floor=None):
    """Subthreshold swing in mV/decade, using the bottom current decade
    of the sweep and a robust (25th-percentile) inverse log-slope."""
    v, i = _prepare(vg, ids)
    if v.size < 6:
        return float("nan")
    pos = i > 0.0
    if current_floor is not None and current_floor > 0.0:
        pos &= i >= current_floor
    if np.count_nonzero(pos) < 6:
        return float("nan")
    v, i = v[pos], i[pos]
    imax = float(np.max(i))
    if imax <= 0.0:
        return float("nan")
    low_mask = i <= imax * 1.0e-2
    if np.count_nonzero(low_mask) >= 6:
        v, i = v[low_mask], i[low_mask]
    logi = np.log10(i)
    d = np.gradient(v, logi)
    d = d[np.isfinite(d) & (d > 0.0)]
    if d.size == 0:
        return float("nan")
    return float(np.percentile(d, 25)) * 1000.0


def extract_dibl(vg_low, ids_low, vg_high, ids_high, vd_low, vd_high, target=1.0e-7):
    """Drain-induced barrier lowering in V/V: the drop in constant-
    current threshold voltage between a low and a high drain bias,
    normalised by the drain-bias difference."""
    if vd_high == vd_low:
        return float("nan")
    vt_low = extract_vth_constant_current(vg_low, ids_low, target=target)
    vt_high = extract_vth_constant_current(vg_high, ids_high, target=target)
    if not math.isfinite(vt_low) or not math.isfinite(vt_high):
        return float("nan")
    return (vt_low - vt_high) / (vd_high - vd_low)
