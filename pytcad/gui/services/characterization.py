"""Characterization post-processing for the Virtual Probe Station GUI.

This module is intentionally solver-independent.  It consumes sweep arrays
and returns physically meaningful extracted quantities.  The GUI controller
uses these functions to populate the Virtual Probe Station panel.

All functions accept Python sequences or NumPy arrays and return NaN when an
extraction is not well-posed.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "engineering",
    "extract_vth_linear",
    "extract_vth_constant_current",
    "extract_subthreshold_swing",
    "extract_on_off_ratio",
    "extract_max_transconductance",
    "extract_output_conductance",
    "extract_breakdown_voltage",
    "extract_dibl",
    "estimate_ft",
    "build_extraction_report",
]


_PREFIXES = {
    -24: "y", -21: "z", -18: "a", -15: "f", -12: "p", -9: "n", -6: "u",
    -3: "m", 0: "", 3: "k", 6: "M", 9: "G", 12: "T", 15: "P", 18: "E",
    21: "Z", 24: "Y",
}


def engineering(value: Any, unit: str = "") -> str:
    """Format a scalar using engineering notation.

    Non-finite values are rendered as ``n/a`` so the GUI can safely display
    failed extractions without showing NaN or infinity.
    """
    try:
        value = float(value)
    except Exception:
        return "n/a"
    if not math.isfinite(value):
        return "n/a"
    if value == 0.0:
        return f"0 {unit}".strip()
    exp = int(math.floor(math.log10(abs(value)) / 3.0) * 3)
    exp = max(-24, min(24, exp))
    scaled = value / (10.0 ** exp)
    prefix = _PREFIXES.get(exp, f"e{exp}")
    return f"{scaled:.4g} {prefix}{unit}".strip()


def _prepare(x: Sequence[float], y: Sequence[float]) -> Tuple[np.ndarray, np.ndarray]:
    """Convert inputs to finite, sorted 1-D arrays."""
    xa = np.asarray(x, dtype=float)
    ya = np.asarray(y, dtype=float)
    if xa.ndim != 1 or ya.ndim != 1:
        raise ValueError("x and y must be 1-D arrays.")
    if xa.size != ya.size:
        raise ValueError("x and y must have equal length.")
    mask = np.isfinite(xa) & np.isfinite(ya)
    xa = xa[mask]
    ya = ya[mask]
    if xa.size == 0:
        return xa, ya
    order = np.argsort(xa)
    return xa[order], ya[order]


def extract_vth_linear(vg: Sequence[float], ids: Sequence[float]) -> float:
    """Threshold voltage by linear extrapolation in the strong-inversion region.

    Locates the maximum transconductance point, fits a local linear window
    around it, and returns the x-intercept of that fit as Vth.
    """
    try:
        v, i = _prepare(vg, ids)
    except Exception:
        return float("nan")
    if v.size < 6:
        return float("nan")
    pos = i > 0.0
    if np.count_nonzero(pos) < 6:
        return float("nan")
    v = v[pos]; i = i[pos]
    gm = np.gradient(i, v)
    if not np.any(np.isfinite(gm)):
        return float("nan")
    idx = int(np.nanargmax(gm))
    win = max(3, v.size // 8)
    lo = max(0, idx - win); hi = min(v.size - 1, idx + win)
    if hi - lo + 1 < 3:
        lo = max(0, idx - 2); hi = min(v.size - 1, idx + 2)
    if hi - lo + 1 < 3:
        return float("nan")
    try:
        m, b = np.polyfit(v[lo:hi + 1], i[lo:hi + 1], 1)
    except Exception:
        return float("nan")
    if not math.isfinite(m) or m <= 0.0:
        return float("nan")
    vt = -b / m
    return float(vt) if math.isfinite(vt) else float("nan")


def extract_vth_constant_current(vg: Sequence[float], ids: Sequence[float], target: float = 1.0e-7) -> float:
    """Threshold voltage at a fixed drain-current criterion."""
    try:
        v, i = _prepare(vg, ids)
    except Exception:
        return float("nan")
    if v.size < 2 or target <= 0.0:
        return float("nan")
    pos = i > 0.0
    if not np.any(pos):
        return float("nan")
    v = v[pos]; i = i[pos]
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


def extract_subthreshold_swing(vg: Sequence[float], ids: Sequence[float], current_floor: Optional[float] = None) -> float:
    """Subthreshold swing in mV/decade, using the lowest-current decade
    available in the sweep and a robust lower-percentile inverse slope."""
    try:
        v, i = _prepare(vg, ids)
    except Exception:
        return float("nan")
    if v.size < 6:
        return float("nan")
    pos = i > 0.0
    if current_floor is not None and current_floor > 0.0:
        pos &= i >= current_floor
    if np.count_nonzero(pos) < 6:
        return float("nan")
    v = v[pos]; i = i[pos]
    imax = float(np.max(i))
    if imax <= 0.0:
        return float("nan")
    low_mask = i <= imax * 1.0e-2
    if np.count_nonzero(low_mask) >= 6:
        v = v[low_mask]; i = i[low_mask]
    logi = np.log10(i)
    try:
        d = np.gradient(v, logi)
    except Exception:
        return float("nan")
    d = d[np.isfinite(d) & (d > 0.0)]
    if d.size == 0:
        return float("nan")
    return float(np.percentile(d, 25)) * 1000.0


def extract_on_off_ratio(vg: Sequence[float], ids: Sequence[float]) -> float:
    """On/off current ratio from the positive current range."""
    try:
        _, i = _prepare(vg, ids)
    except Exception:
        return float("nan")
    pos = i > 0.0
    if np.count_nonzero(pos) < 2:
        return float("nan")
    ipos = i[pos]
    imax, imin = float(np.max(ipos)), float(np.min(ipos))
    if imin <= 0.0:
        return float("nan")
    return imax / imin


def extract_max_transconductance(vg: Sequence[float], ids: Sequence[float]) -> float:
    """Maximum transconductance gm = dId/dVg."""
    try:
        v, i = _prepare(vg, ids)
    except Exception:
        return float("nan")
    if v.size < 3:
        return float("nan")
    gm = np.gradient(i, v)
    gm = gm[np.isfinite(gm)]
    return float(np.max(gm)) if gm.size else float("nan")


def extract_output_conductance(vd: Sequence[float], ids: Sequence[float], fit_fraction: float = 0.25) -> Tuple[float, float]:
    """Output conductance and resistance (gds, ro) fit over the last
    `fit_fraction` of the Vd range (the saturation-region tail)."""
    try:
        v, i = _prepare(vd, ids)
    except Exception:
        return float("nan"), float("nan")
    if v.size < 6:
        return float("nan"), float("nan")
    vmin, vmax = float(v[0]), float(v[-1])
    if vmax <= vmin:
        return float("nan"), float("nan")
    span = vmax - vmin
    cutoff = vmax - max(1.0e-12, abs(fit_fraction) * span)
    mask = v >= cutoff
    if np.count_nonzero(mask) < 3:
        mask = np.zeros(v.shape, dtype=bool)
        mask[-min(3, v.size):] = True
    try:
        m, _ = np.polyfit(v[mask], i[mask], 1)
    except Exception:
        return float("nan"), float("nan")
    if not math.isfinite(m):
        return float("nan"), float("nan")
    if m <= 0.0:
        return 0.0, float("inf")
    return float(m), float(1.0 / m)


def extract_breakdown_voltage(vd: Sequence[float], ids: Sequence[float], current_limit: Optional[float] = 1.0e-6) -> float:
    """Breakdown voltage as the first voltage crossing a current limit."""
    try:
        v, i = _prepare(vd, ids)
    except Exception:
        return float("nan")
    if v.size < 2:
        return float("nan")
    if current_limit is None or not math.isfinite(current_limit) or current_limit <= 0.0:
        current_limit = 1.0e-6
    pos = i >= current_limit
    if not np.any(pos):
        return float("nan")
    idx = int(np.argmax(pos))
    if idx == 0:
        return float(v[0])
    x0, x1, y0, y1 = v[idx - 1], v[idx], i[idx - 1], i[idx]
    if y1 == y0:
        return float(x1)
    return float(x0 + (current_limit - y0) * (x1 - x0) / (y1 - y0))


def extract_dibl(vg_low: Sequence[float], ids_low: Sequence[float], vg_high: Sequence[float], ids_high: Sequence[float],
                 vd_low: float, vd_high: float, target: float = 1.0e-7) -> float:
    """Drain-induced barrier lowering in V/V, via constant-current
    threshold extraction at low and high drain bias."""
    if vd_high == vd_low:
        return float("nan")
    vt_low = extract_vth_constant_current(vg_low, ids_low, target=target)
    vt_high = extract_vth_constant_current(vg_high, ids_high, target=target)
    if not math.isfinite(vt_low) or not math.isfinite(vt_high):
        return float("nan")
    return (vt_low - vt_high) / (vd_high - vd_low)


def estimate_ft(freq: Sequence[float], h21: Optional[Sequence[float]] = None,
                y21: Optional[Sequence[float]] = None, y11: Optional[Sequence[float]] = None) -> float:
    """Estimate unity-current-gain frequency fT from |H21| directly, or
    from |Y21|/|Y11| as an approximation when H21 isn't available."""
    try:
        f = np.asarray(freq, dtype=float)
    except Exception:
        return float("nan")
    if f.size == 0:
        return float("nan")
    if h21 is not None:
        try:
            mag = np.abs(np.asarray(h21, dtype=float))
        except Exception:
            return float("nan")
    elif y21 is not None:
        try:
            y21_arr = np.asarray(y21)
        except Exception:
            return float("nan")
        if y11 is None:
            mag = np.abs(y21_arr)
        else:
            try:
                y11_arr = np.asarray(y11)
            except Exception:
                return float("nan")
            denom = np.abs(y11_arr)
            denom = np.where(denom == 0.0, np.nan, denom)
            mag = np.abs(y21_arr) / denom
    else:
        return float("nan")
    mask = np.isfinite(f) & np.isfinite(mag) & (f > 0.0) & (mag > 0.0)
    f = f[mask]; mag = mag[mask]
    if f.size < 2:
        return float("nan")
    logf = np.log10(f); logm = np.log10(mag)
    for j in range(logm.size - 1):
        if logm[j] == 0.0:
            return float(f[j])
        if logm[j] * logm[j + 1] < 0.0:
            denom = logm[j + 1] - logm[j]
            if denom == 0.0:
                continue
            t = -logm[j] / denom
            return float(10.0 ** (logf[j] + t * (logf[j + 1] - logf[j])))
    slopes = np.diff(logm) / np.where(np.diff(logf) == 0.0, np.nan, np.diff(logf))
    finite = np.isfinite(slopes) & (slopes != 0.0)
    if not np.any(finite):
        return float("nan")
    j = int(np.where(finite)[0][-1])
    logft = logf[-1] + (0.0 - logm[-1]) / slopes[j]
    return float(10.0 ** logft) if math.isfinite(logft) else float("nan")


def build_extraction_report(sweep_type: str, x: Sequence[float], y: Sequence[float],
                            meta: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Build a row-oriented extraction report for the GUI."""
    meta = dict(meta or {})
    rows: List[Dict[str, Any]] = []
    try:
        xa, ya = _prepare(x, y)
    except Exception:
        return rows
    if xa.size == 0:
        return rows

    def add(name: str, value: float, unit: str = "", note: str = "") -> None:
        rows.append({
            "name": name,
            "value": float(value) if math.isfinite(float(value)) else float("nan"),
            "unit": unit,
            "display": engineering(value, unit),
            "note": note,
        })

    st = str(sweep_type).lower()
    if st == "transfer":
        target = float(meta.get("threshold_current", 1.0e-7))
        add("Vth (linear extrapolation)", extract_vth_linear(xa, ya), "V")
        add("Vth (constant current)", extract_vth_constant_current(xa, ya, target=target), "V",
            f"target={engineering(target, 'A')}")
        add("Subthreshold swing", extract_subthreshold_swing(xa, ya), "mV/dec")
        add("On/off ratio", extract_on_off_ratio(xa, ya), "")
        add("gm,max", extract_max_transconductance(xa, ya), "S")
    elif st == "output":
        gds, ro = extract_output_conductance(xa, ya)
        add("Output conductance", gds, "S")
        add("Output resistance", ro, "ohm")
        add("Id at max Vd", float(ya[-1]), "A")
    elif st == "breakdown":
        try:
            current_limit = float(meta.get("current_limit", 1.0e-6))
        except Exception:
            current_limit = 1.0e-6
        add("Breakdown voltage", extract_breakdown_voltage(xa, ya, current_limit=current_limit), "V",
            f"I_limit={engineering(current_limit, 'A')}")
        add("Max current", float(np.max(ya)), "A")
    else:
        add("Unsupported sweep type", float("nan"), "", st)
    return rows
