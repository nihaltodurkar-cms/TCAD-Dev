"""Derived readouts computed from sweep CURVE DATA ONLY.

v0.4 scope guard: nothing in this module models semiconductor physics --
every function is a geometric statistic over an already-computed sweep
(SweepResult from the result-store layer).  The Vth extraction is the
same max-transconductance tangent method validated against the MOSCapacitor
analytic landmark in pytcad/tests/test_validation_2d.py
(_extract_vth_max_gm, 0.1 V tolerance), promoted here so the GUI reports
it; it is NOT a new model.

Non-converged points arrive NaN'd by SweepResult and are excluded from
every statistic before anything is reported -- an invalid point can never
become part of a derived number.

Qt-free, like every service module.
"""
import numpy as np


def _valid(voltages, currents):
    """Finite (i.e. converged) points as parallel arrays."""
    V = np.asarray(voltages, dtype=float)
    I = np.asarray(currents, dtype=float)
    mask = np.isfinite(V) & np.isfinite(I)
    return V[mask], I[mask]


def current_extremes(currents):
    """Signed (min, max) over finite points; (nan, nan) if none."""
    I = np.asarray(currents, dtype=float)
    I = I[np.isfinite(I)]
    if not I.size:
        return float("nan"), float("nan")
    return float(I.min()), float(I.max())


def on_off_ratio(currents):
    """max|I| / min nonzero |I| over valid points -- the ratio between
    the largest and smallest distinct positive magnitudes.  None unless
    at least two meaningfully different magnitudes exist: a ratio like
    1.0 (flat curve) or one built on a single valid point would be
    numerically defined but physically meaningless.  Note this is only a
    real "on/off" figure for transistor-like transfer curves; callers
    should not present it for output-characteristic sweeps."""
    I = np.asarray(currents, dtype=float)
    I = I[np.isfinite(I)]
    mags = np.abs(I[I != 0.0])
    if mags.size < 2:
        return None
    lo, hi = mags.min(), mags.max()
    if hi <= 0.0 or hi == lo:
        return None
    return float(hi / lo)


def threshold_voltage_max_gm(voltages, currents, vds=0.0):
    """Max-transconductance linear-extrapolation threshold estimate:
    tangent to Id-Vg at peak gm, crossed at Id=0, with the textbook
    linear-region correction -Vds/2.  Identical method (and sign
    conventions) to pytcad/tests/test_validation_2d._extract_vth_max_gm;
    pass the actual Vds when the swept gate's opposing terminal sits at a
    known nonzero bias, else leave vds=0.0 and read the result as carrying
    a +Vds/2 offset.

    Returns None when there are fewer than 3 valid points, no voltage
    variation, or nowhere-positive transconductance -- conditions under
    which any reported number would be fiction.
    """
    V, I = _valid(voltages, currents)
    if V.size < 3 or V.max() == V.min():
        return None
    order = np.argsort(V)
    V, I = V[order], I[order]
    gm = np.gradient(I, V)
    i = int(np.argmax(gm))
    if not np.isfinite(gm[i]) or gm[i] <= 0.0:
        return None
    return float(V[i] - I[i] / gm[i] - vds / 2.0)


def summarize(sweep_result, channel=None, vds=0.0):
    """Aggregate a SweepResult into plain-float derived values.

    Returns a dict whose keys EXIST only when meaningful (a missing key
    is the contract for 'not derivable', never None-valued noise):
      points_total, points_converged,
      current_min, current_max          -- signed extremes [unit]
      on_off_ratio                      -- dimensionless
      threshold_voltage_v               -- max-gm extrapolation estimate
    """
    channels = sweep_result.channels
    name = channel if channel in channels else next(iter(channels), None)
    out = {
        "points_total": sweep_result.n_points(),
        "points_converged": sweep_result.n_valid(),
    }
    if name is None:
        return out
    V, I = _valid(sweep_result.voltages, channels[name])
    if I.size:
        out["current_min"], out["current_max"] = current_extremes(channels[name])
    ratio = on_off_ratio(channels[name])
    if ratio is not None:
        out["on_off_ratio"] = ratio
    vth = threshold_voltage_max_gm(sweep_result.voltages, channels[name], vds=vds)
    if vth is not None:
        out["threshold_voltage_v"] = vth
    return out
