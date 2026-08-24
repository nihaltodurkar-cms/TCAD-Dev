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


def _plausible_threshold(voltages, currents, vds=0.0):
    """threshold_voltage_max_gm(), tried against BOTH sign conventions of
    `currents` and accepted only when the result also falls near the
    actual swept range.

    Which sign is "conventional Id" (near zero off-state, rising with
    the sweep) depends on which physical terminal a channel is, and that
    is not derivable from a contact's name -- so both are tried here,
    never a hardcoded "source is negative"/"drain is positive" rule.
    Passing the mechanical gm > 0 check is not sufficient on its own: a
    channel whose OWN current is dominated by something other than the
    swept terminal (e.g. a large near-constant leakage-like baseline)
    can still have a locally positive gm and extrapolate to a tangent
    x-intercept far outside the sweep -- a number as fictional as a
    negative-gm result, just not caught by that guard.  Requiring the
    threshold to land within the swept span (plus one span's margin, to
    allow a threshold just outside a coarse ramp) rejects that case too.

    Returns (peak_gm, threshold_v) for the better-supported sign, or
    None if neither sign yields a plausible threshold.
    """
    V, I = _valid(voltages, currents)
    if V.size < 3 or V.max() == V.min():
        return None
    lo, hi = float(V.min()), float(V.max())
    margin = max(hi - lo, 1e-6)
    order = np.argsort(V)
    best = None
    for sign in (1.0, -1.0):
        vth = threshold_voltage_max_gm(voltages, sign * currents, vds=vds)
        if vth is None or not (lo - margin <= vth <= hi + margin):
            continue
        gm_peak = float(np.max(np.gradient(sign * I[order], V[order])))
        if best is None or gm_peak > best[0]:
            best = (gm_peak, vth)
    return best


def _select_primary_channel(sweep_result, vds=0.0):
    """Pick the channel most representative of the swept device's
    response, without assuming any particular contact name (a bundled
    example's structure may list "source" before "drain", or a caller
    may use non-standard contact names entirely).

    Among the channels that yield a plausible threshold (see
    _plausible_threshold), picks the one with the largest peak
    transconductance -- the terminal most strongly and cleanly
    modulated by the sweep.  Falls back to the first channel in file
    order when no channel yields a plausible threshold, so current
    extremes / Ion-Ioff keep being reported exactly as before this
    selection existed.
    """
    channels = sweep_result.channels
    if not channels:
        return None
    best_name, best_gm = None, -np.inf
    for name, currents in channels.items():
        result = _plausible_threshold(sweep_result.voltages, currents, vds=vds)
        if result is None:
            continue
        gm_peak, _ = result
        if gm_peak > best_gm:
            best_name, best_gm = name, gm_peak
    return best_name if best_name is not None else next(iter(channels))


def summarize(sweep_result, channel=None, vds=0.0):
    """Aggregate a SweepResult into plain-float derived values.

    Returns a dict whose keys EXIST only when meaningful (a missing key
    is the contract for 'not derivable', never None-valued noise):
      points_total, points_converged,
      current_min, current_max          -- signed extremes [unit]
      on_off_ratio                      -- dimensionless
      threshold_voltage_v               -- max-gm extrapolation estimate

    `channel` forces a specific channel when given and present; otherwise
    the channel is chosen by _select_primary_channel() -- see there for
    why this is not simply "the first channel" or a hardcoded name.
    current_min/current_max/on_off_ratio always use the channel's own
    reported sign (the actual physical terminal current); only the
    threshold extraction may internally try the opposite sign, since
    that is purely an artifact of the linear extrapolation method.
    """
    channels = sweep_result.channels
    name = channel if channel in channels else _select_primary_channel(sweep_result, vds=vds)
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
    result = _plausible_threshold(sweep_result.voltages, channels[name], vds=vds)
    if result is not None:
        out["threshold_voltage_v"] = result[1]
    return out
