"""M21 phase 1: solution-driven adaptive h-refinement for 1D devices.

Spec: M21-MESHING-PLAN.md.

LAYERING.  This module is a DRIVER that sits ABOVE the device cores: it
may import mesh.py and numpy, and it consumes Device1D through its
public interface only.  It touches no residual, no Jacobian and no
committed golden, which is why phase 1 is a pure addition and needs no
core amendment (plan section 6).  The core must never import it.

HONESTY.  The indicators here are HEURISTIC.  They are gated for
self-consistency against closed forms (G1) and for the convergence they
produce (G4, G5), NOT for a proven effectivity bound.  They are not
error estimators and this module does not call them that.
"""
import warnings

import numpy as np

from .mesh import debye_length

__all__ = [
    "second_derivative", "indicator_debye", "indicator_curvature",
    "indicator_log_density", "indicator_rate", "combine", "mark_dorfler",
    "refine_1d", "default_indicator", "adapt_solve_1d",
]

_TINY = 1e-300


# ----------------------------------------------------------------------
#  Pure indicator functions.  Array in, array out; no solver state.
#  Every one returns a PER-CELL array of length len(x) - 1.
# ----------------------------------------------------------------------
def second_derivative(x, u):
    """Nodal second derivative of `u` on a (possibly non-uniform) mesh.

    Three-point divided difference:

        u''_i ~ 2 [ (u_{i+1}-u_i)/h_i - (u_i-u_{i-1})/h_{i-1} ]
                / (h_{i-1} + h_i)

    Exact for quadratics on ANY mesh, and exact for cubics on a uniform
    mesh (the leading error term carries h_i - h_{i-1}).  Endpoints copy
    their neighbour -- a one-sided estimate there would be a different
    approximation order and would silently bias the boundary cells.
    """
    x = np.asarray(x, dtype=float)
    u = np.asarray(u, dtype=float)
    if x.ndim != 1 or x.shape != u.shape:
        raise ValueError("x and u must be 1-D arrays of the same shape")
    if x.size < 3:
        return np.zeros_like(u)
    h = np.diff(x)
    fwd = (u[2:] - u[1:-1]) / h[1:]
    bwd = (u[1:-1] - u[:-2]) / h[:-1]
    out = np.empty_like(u)
    out[1:-1] = 2.0 * (fwd - bwd) / (h[:-1] + h[1:])
    out[0], out[-1] = out[1], out[-2]
    return out


def indicator_debye(x, doping, eps_r=11.7, T=300.0):
    """Per-cell spacing-to-Debye-length ratio h / L_D.

    Reproduces mesh.check_mesh's ratio EXACTLY (gated by array_equal in
    G1) so the two can never drift apart.
    """
    x = np.asarray(x, dtype=float)
    LD = debye_length(np.abs(np.asarray(doping, dtype=float)), eps_r, T)
    return np.diff(x) / np.minimum(LD[:-1], LD[1:])


def indicator_curvature(x, u, scale=None):
    """Per-cell h^2 |u''|, the classic smoothness indicator.

    `scale` normalises the result; it defaults to the peak magnitude of
    `u`, making the indicator dimensionless and comparable across
    fields with different units.
    """
    x = np.asarray(x, dtype=float)
    u2 = second_derivative(x, u)
    h = np.diff(x)
    cell_u2 = 0.5 * (np.abs(u2[:-1]) + np.abs(u2[1:]))
    if scale is None:
        scale = float(np.max(np.abs(u)))
    scale = max(float(scale), _TINY)
    return h * h * cell_u2 / scale


def indicator_log_density(x, n, p):
    """Per-cell max(|d ln n|, |d ln p|) across the cell.

    Carrier densities span ~20 decades, so a linear gradient indicator
    is dominated by the majority region and blind to the depletion edge
    that actually needs resolving.  The log difference is the physically
    meaningful one, and for n ~ exp(k x) it returns exactly k*h (G1).
    """
    n = np.maximum(np.asarray(n, dtype=float), _TINY)
    p = np.maximum(np.asarray(p, dtype=float), _TINY)
    dln_n = np.abs(np.diff(np.log(n)))
    dln_p = np.abs(np.diff(np.log(p)))
    return np.maximum(dln_n, dln_p)


def indicator_rate(x, rate, dV):
    """Per-cell share of a volumetric rate (SRH recombination, or the
    M15 impact-generation source).  Sums to 1 unless the rate is
    identically zero, in which case it is all zeros.
    """
    rate = np.abs(np.asarray(rate, dtype=float))
    dV = np.asarray(dV, dtype=float)
    w = rate * dV
    cell = 0.5 * (w[:-1] + w[1:])
    total = float(cell.sum())
    if total <= _TINY:
        return np.zeros_like(cell)
    return cell / total


def combine(indicators, weights=None):
    """Normalise each indicator by its own peak, then take a weighted
    sum and renormalise to a peak of 1.

    Per-indicator normalisation is what makes quantities with wildly
    different natural scales (h/L_D ~ 1, |d ln n| ~ 30) comparable.  An
    all-zero input returns all zeros rather than dividing by zero.
    """
    mats = [np.asarray(a, dtype=float) for a in indicators]
    if not mats:
        raise ValueError("combine() needs at least one indicator")
    ncell = mats[0].size
    if any(m.size != ncell for m in mats):
        raise ValueError("indicators must all have the same length")
    if weights is None:
        weights = np.ones(len(mats))
    weights = np.asarray(weights, dtype=float)
    if weights.size != len(mats):
        raise ValueError("weights must match the number of indicators")

    acc = np.zeros(ncell)
    for w, m in zip(weights, mats):
        peak = float(np.max(np.abs(m)))
        if peak > _TINY:
            acc += w * np.abs(m) / peak
    peak = float(np.max(acc))
    return acc / peak if peak > _TINY else acc


def mark_dorfler(eta, theta=0.5):
    """Doerfler marking: the smallest set of cells carrying at least
    `theta` of the total indicator mass.  Returns ascending indices.

    A zero indicator marks nothing -- there is no error to chase, and
    marking "the largest cell anyway" would refine forever.
    """
    eta = np.abs(np.asarray(eta, dtype=float))
    total = float(eta.sum())
    if total <= _TINY or eta.size == 0:
        return np.array([], dtype=int)
    theta = float(np.clip(theta, 0.0, 1.0))
    if theta <= 0.0:
        return np.array([], dtype=int)
    if not np.all(np.isfinite(eta)):
        raise ValueError(
            "indicator contains non-finite values; marking would sort "
            "NaNs into arbitrary positions and refine on nonsense")
    order = np.argsort(eta)[::-1]
    csum = np.cumsum(eta[order])
    k = int(np.searchsorted(csum, theta * total, side="left")) + 1
    return np.sort(order[:min(k, eta.size)])


# ----------------------------------------------------------------------
#  Refinement
# ----------------------------------------------------------------------
def _enforce_grading(x, ratio):
    """Bisect cells until no two neighbours differ by more than `ratio`.

    NOTE ON THE ACHIEVABLE RATIO.  Refinement here is BISECTION, so a
    refined cell sits next to an unrefined one at a size jump of exactly
    2.  No bisection-only scheme can therefore guarantee a ratio below
    2, and asking for one loops until the sweep cap and returns a mesh
    that quietly fails the request.  `ratio = 2` is the standard "2:1
    balance" condition of adaptive mesh refinement and is the tightest
    honest default; values < 2 are rejected by refine_1d rather than
    silently approximated.

    Terminates: every sweep strictly halves at least one offending cell,
    and sizes are bounded below by the smallest cell present.
    """
    x = np.asarray(x, dtype=float)
    for _ in range(200):
        h = np.diff(x)
        if h.size < 2:
            return x
        left, right = h[:-1], h[1:]
        bad_r = right > ratio * left            # right neighbour too big
        bad_l = left > ratio * right            # left neighbour too big
        idx = np.r_[np.flatnonzero(bad_r) + 1, np.flatnonzero(bad_l)]
        if idx.size == 0:
            return x
        idx = np.unique(idx)
        mids = 0.5 * (x[idx] + x[idx + 1])
        x = np.union1d(x, mids)
    return x


def refine_1d(x, marked, ratio=2.0, max_nodes=None):
    """Bisect the `marked` cells of mesh `x`, then restore the grading
    invariant.  Refines only: every input node survives (phase 1 does
    not coarsen -- plan 10.2).

    `ratio` is the 2:1-balance bound (see _enforce_grading); values
    below 2 are refused rather than silently approximated.

    `max_nodes` is a HARD cap.  Grading is an invariant and is never
    traded away for it, so when the smoothed result would exceed the cap
    the marked set is reduced until it fits.  If even zero refinement
    does not fit -- which means the INPUT already violated grading -- the
    input is returned unchanged rather than silently breaking either
    promise.
    """
    if ratio < 2.0:
        raise ValueError(
            f"ratio={ratio} is unachievable by bisection refinement: a "
            f"bisected cell adjacent to an unbisected one differs by "
            f"exactly 2.  Use ratio >= 2 (the standard 2:1 balance "
            f"condition); build a smoothly graded mesh with "
            f"mesh.graded_mesh if a gentler grading is required.")
    x = np.asarray(x, dtype=float)
    marked = np.asarray(marked, dtype=int).ravel()
    if x.size < 2:
        return x
    ncell = x.size - 1
    if marked.size and (marked.min() < 0 or marked.max() >= ncell):
        raise IndexError(f"marked cell out of range for {ncell} cells")

    cap = np.inf if max_nodes is None else int(max_nodes)
    if x.size >= cap:
        return x

    # Priority order is the caller's order; ties break toward the front.
    ordered = marked.copy()
    keep = ordered.size
    while True:
        sel = np.unique(ordered[:keep]) if keep else np.array([], dtype=int)
        y = x if sel.size == 0 else np.union1d(
            x, 0.5 * (x[sel] + x[sel + 1]))
        y = _enforce_grading(y, ratio)
        if y.size <= cap:
            return y
        if keep == 0:
            # Cap cannot be met even with no refinement: the input mesh
            # already violates grading.  Return it untouched -- refusing
            # to pretend we satisfied a constraint we cannot.
            return x
        keep //= 2


# ----------------------------------------------------------------------
#  Driver
# ----------------------------------------------------------------------
def default_indicator(dev):
    """Per-cell ERROR indicator from a solved Device1D: potential
    curvature and carrier log-gradients, equally weighted.

    Deliberately EXCLUDES h/L_D.  The Debye ratio is a mesh-quality
    CONSTRAINT, not an error indicator: on a uniform mesh it is very
    nearly constant, so folding it into a Doerfler mass criterion adds a
    flat floor that dominates the selection and turns refinement into
    near-uniform bisection (measured: h spanning only 2x end to end, and
    an adaptive mesh LOSING to a uniform one at equal node count).  The
    driver enforces it separately, as a constraint (see `debye_target`).

    Reads only public solution state, so it works for any Models
    combination the caller built.
    """
    return combine(
        (indicator_curvature(dev.x, dev.psi),
         indicator_log_density(dev.x, dev.n, dev.p)))


def adapt_solve_1d(build_device, x0, *, qoi, solve=None, indicator=None,
                   max_passes=6, tol=1e-3, theta=0.5, max_nodes=20000,
                   debye_target=1.0):
    """Refine until `qoi` stops moving, then return the converged device.

    build_device(x) -> Device1D   caller owns doping, materials, Models,
                                  so the driver cannot drop a flag (G7)
    solve(device)                 caller's solve sequence; defaults to
                                  solve_equilibrium()
    qoi(device) -> float          the scalar convergence is measured on
    indicator(device) -> per-cell array; defaults to default_indicator

    Returns (device, mesh, history).  `history` is part of the contract,
    not debug output: one entry per pass with nodes, qoi, delta, marked
    and the termination `cause`.

    Stopping has TWO parts, and both must hold:
      1. mesh quality, absolute: max h / L_D <= `debye_target`.  This is
         the standard TCAD criterion (mesh.check_mesh: "Aim for < ~1")
         and it is enforced as a CONSTRAINT -- every violating cell is
         marked unconditionally, regardless of its error indicator.
      2. quantity of interest, relative: |dqoi| / |qoi| <= `tol`.

    A mesh that already satisfies (1) on the first pass is left exactly
    as it was found and reported with cause "already_adequate" -- the
    caller asked for Debye resolution and already has it.  That exit is
    named distinctly rather than folded into "converged" because no QoI
    difference was ever measured on it, and the history should say so.

    Termination is always recorded, and any exit that is NOT convergence
    also WARNS.  A budget-limited or pass-limited result must never be
    mistaken for a converged one -- that failure mode is exactly what
    the M15 outer loop had to have retrofitted.
    """
    if solve is None:
        solve = lambda d: d.solve_equilibrium()
    if indicator is None:
        indicator = default_indicator

    mesh = np.asarray(x0, dtype=float).copy()
    history = []
    dev = None
    prev_q = None
    cause = "max_passes"

    for it in range(max_passes):
        dev = build_device(mesh)
        solve(dev)
        q = float(qoi(dev))
        if not np.isfinite(q):
            raise ValueError(
                f"quantity of interest is {q} after pass {it} on "
                f"{mesh.size} nodes -- the solve did not produce a usable "
                f"state, and refining on it would compound nonsense")
        delta = (np.inf if prev_q is None
                 else abs(q - prev_q) / max(abs(q), _TINY))
        entry = {"pass": it, "nodes": int(mesh.size), "qoi": q,
                 "delta": delta, "marked": 0, "debye_violations": 0,
                 "cause": None}
        history.append(entry)

        # (1) mesh-quality constraint, absolute.
        viol = np.flatnonzero(
            indicator_debye(mesh, dev.doping) > debye_target)
        entry["debye_violations"] = int(viol.size)

        if viol.size == 0:
            if prev_q is None:
                # Adequate as handed to us: touch nothing.
                cause = "already_adequate"
                break
            if delta <= tol:
                cause = "converged"
                break
        prev_q = q

        # (2) error indicator, relative -- Doerfler on the peaked part.
        eta = np.asarray(indicator(dev), dtype=float)
        if eta.size != mesh.size - 1:
            raise ValueError(
                f"indicator returned {eta.size} values for "
                f"{mesh.size - 1} cells")
        if not np.all(np.isfinite(eta)):
            raise ValueError(
                f"indicator returned non-finite values after pass {it}; "
                f"refusing to refine on them")
        marked = np.union1d(mark_dorfler(eta, theta), viol)
        entry["marked"] = int(marked.size)
        if marked.size == 0:
            cause = "converged"
            break

        new_mesh = refine_1d(mesh, marked, max_nodes=max_nodes)
        if new_mesh.size == mesh.size:
            # Refinement made no progress: the node budget is spent.
            cause = "max_nodes"
            break
        mesh = new_mesh
    else:
        cause = "max_passes"

    for entry in history:
        entry["cause"] = cause

    if cause == "max_nodes":
        warnings.warn(
            f"adaptive refinement stopped on the node budget "
            f"({max_nodes} nodes); the quantity of interest had not "
            f"converged to tol={tol:g} (last change "
            f"{history[-1]['delta']:.3e}) -- this result is "
            f"budget-limited, not converged")
    elif cause == "max_passes":
        warnings.warn(
            f"adaptive refinement stopped on the pass limit "
            f"({max_passes} passes); the quantity of interest had not "
            f"converged to tol={tol:g} (last change "
            f"{history[-1]['delta']:.3e}) -- this result is "
            f"iteration-limited, not converged")

    return dev, mesh, history
