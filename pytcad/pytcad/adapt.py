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

from .mesh import debye_length as _debye_length

__all__ = [
    "second_derivative", "indicator_debye", "indicator_curvature",
    "indicator_log_density", "indicator_rate", "combine", "mark_dorfler",
    "refine_1d", "default_indicator", "adapt_solve_1d",
    # phase 2 (2D/3D separable refinement)
    "reduce_x", "reduce_y", "reduce_z",
    "default_indicator_2d", "default_indicator_3d",
    "refine_2d", "refine_3d",
    "adapt_solve_2d", "adapt_solve_3d",
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
    LD = _debye_length(np.abs(np.asarray(doping, dtype=float)), eps_r, T)
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


# ----------------------------------------------------------------------
#  Phase 2: 2D/3D separable refinement on tensor-product meshes.
#
#  The same indicators are reduced onto each axis (x, y, [z]) by
#  integrating across the perpendicular dimensions, then each 1D node
#  set is refined independently.  The result is still a tensor-product
#  mesh consumed by Device2D / Device3D.
#
#  Honest limitation (must ship stated): refining one cell refines an
#  entire row/column (2D) or slice (3D), so a localised feature costs
#  O(N) nodes rather than O(1).  That waste is precisely the motivation
#  for phase 3 and must not be hidden.
# ----------------------------------------------------------------------

def reduce_x(eta, axis="x", weights=None):
    """Reduce a per-cell x-edge indicator array onto the x axis.

    2D: `eta` has shape (Ny, Nx-1) -- one row per y-cell.  Reduction is
    a weighted average across y, producing a 1D indicator of length
    Nx-1.

    3D: `eta` has shape (Nz, Ny, Nx-1).  Reduction averages across both
    z and y (no weights support in this case -- 3D callers use the
    default unweighted mean).  Same shape convention as
    default_indicator_3d's `eta_x` output.

    `axis` is ignored here (always x); kept for API symmetry with
    reduce_y / reduce_z.
    """
    eta = np.asarray(eta, dtype=float)
    if eta.ndim == 3:
        if weights is not None:
            raise ValueError("reduce_x does not support weights for 3-D input")
        if eta.shape[2] < 1:
            return np.array([], dtype=float)
        return eta.mean(axis=(0, 1))
    if eta.ndim != 2:
        raise ValueError("reduce_x needs a 2-D or 3-D indicator array")
    if eta.shape[1] < 1:
        return np.array([], dtype=float)
    if weights is None:
        return eta.mean(axis=0)
    w = np.asarray(weights, dtype=float)
    if w.shape[0] != eta.shape[0]:
        raise ValueError("weight length must match number of y cells")
    w = w / w.sum()
    return eta.T @ w


def reduce_y(eta, axis="y", weights=None):
    """Reduce a per-cell y-edge indicator array onto the y axis.

    2D: `eta` has shape (Ny-1, Nx) -- one column per x-cell.  Reduction
    is a weighted average across x, producing a 1D indicator of length
    Ny-1.

    3D: `eta` has shape (Nz, Ny-1, Nx).  Reduction averages across both
    z and x (no weights support in this case).  Same shape convention
    as default_indicator_3d's `eta_y` output.
    """
    eta = np.asarray(eta, dtype=float)
    if eta.ndim == 3:
        if weights is not None:
            raise ValueError("reduce_y does not support weights for 3-D input")
        if eta.shape[1] < 1:
            return np.array([], dtype=float)
        return eta.mean(axis=(0, 2))
    if eta.ndim != 2:
        raise ValueError("reduce_y needs a 2-D or 3-D indicator array")
    if eta.shape[0] < 1:
        return np.array([], dtype=float)
    if weights is None:
        return eta.mean(axis=1)
    w = np.asarray(weights, dtype=float)
    if w.shape[0] != eta.shape[1]:
        raise ValueError("weight length must match number of x cells")
    w = w / w.sum()
    return eta @ w


def reduce_z(eta_3d, axis="z", weights=None):
    """Reduce a 3D per-cell indicator array (Nz-1, Ny, Nx) onto the z axis.

    Reduction is a weighted average across y and x, producing a 1D
    indicator of length Nz-1.
    """
    eta_3d = np.asarray(eta_3d, dtype=float)
    if eta_3d.ndim != 3:
        raise ValueError("reduce_z needs a 3-D indicator array")
    nz = eta_3d.shape[0]
    if nz < 1:
        return np.array([], dtype=float)
    if weights is None:
        return eta_3d.mean(axis=(1, 2))
    w = np.asarray(weights, dtype=float)
    flat = eta_3d.reshape(nz, -1)
    if w.shape[0] != flat.shape[1]:
        raise ValueError("weight length must match y*x cell count")
    w = w / w.sum()
    return flat @ w


def default_indicator_2d(dev):
    """Per-cell 2D error indicator from a solved Device2D: potential
    curvature and carrier log-gradients.

    Returns (eta_x, eta_y) where:
      eta_x has shape (Ny, Nx-1) -- per-cell indicator for x-edges
      eta_y has shape (Ny-1, Nx) -- per-cell indicator for y-edges
    """
    psi = dev.psi
    n = dev.n
    p = dev.p

    # Per-cell second derivative along x (shape: Ny x (Nx-1))
    eta_psi_x = np.zeros((dev.Ny, dev.Nx - 1))
    for j in range(dev.Ny):
        eta_psi_x[j, :] = indicator_curvature(dev.mesh.x, psi[j, :])

    # Per-cell second derivative along y (shape: (Ny-1) x Nx)
    eta_psi_y = np.zeros((dev.Ny - 1, dev.Nx))
    for i in range(dev.Nx):
        eta_psi_y[:, i] = indicator_curvature(dev.mesh.y, psi[:, i])

    # Log-density gradients along x: one per (y-row, x-cell)
    eta_n_x = np.zeros((dev.Ny, dev.Nx - 1))
    eta_p_x = np.zeros((dev.Ny, dev.Nx - 1))
    for j in range(dev.Ny):
        eta_n_x[j, :] = indicator_log_density(dev.mesh.x, n[j, :], p[j, :])
        eta_p_x[j, :] = indicator_log_density(dev.mesh.x, p[j, :], n[j, :])

    # Log-density gradients along y: one per (x-col, y-cell)
    eta_n_y = np.zeros((dev.Ny - 1, dev.Nx))
    eta_p_y = np.zeros((dev.Ny - 1, dev.Nx))
    for i in range(dev.Nx):
        eta_n_y[:, i] = indicator_log_density(dev.mesh.y, n[:, i], p[:, i])
        eta_p_y[:, i] = indicator_log_density(dev.mesh.y, p[:, i], n[:, i])

    # Combine along each axis (normalise each indicator by its own peak)
    dens_x = np.maximum(eta_n_x, eta_p_x)
    eta_x = (eta_psi_x / max(float(np.max(np.abs(eta_psi_x))), _TINY)
             + dens_x / max(float(np.max(np.abs(dens_x))), _TINY))

    dens_y = np.maximum(eta_n_y, eta_p_y)
    eta_y = (eta_psi_y / max(float(np.max(np.abs(eta_psi_y))), _TINY)
             + dens_y / max(float(np.max(np.abs(dens_y))), _TINY))

    return eta_x, eta_y


def default_indicator_3d(dev):
    """Per-cell 3D error indicator from a solved Device3D: potential
    curvature and carrier log-gradients, reduced onto each axis.

    Returns (eta_x, eta_y, eta_z) each of shape (Nz, Ny, Nx-1),
    (Nz, Ny-1, Nx), (Nz-1, Ny, Nx) respectively.
    """
    psi = dev.psi
    n = dev.n
    p = dev.p

    # Curvature along x: (Nz, Ny, Nx-1)
    eta_psi_x = np.zeros((dev.Nz, dev.Ny, dev.Nx - 1))
    for kk in range(dev.Nz):
        for jj in range(dev.Ny):
            eta_psi_x[kk, jj, :] = indicator_curvature(dev.mesh.x, psi[kk, jj, :])

    # Curvature along y: (Nz, Ny-1, Nx)
    eta_psi_y = np.zeros((dev.Nz, dev.Ny - 1, dev.Nx))
    for kk in range(dev.Nz):
        for ii in range(dev.Nx):
            eta_psi_y[kk, :, ii] = indicator_curvature(dev.mesh.y, psi[kk, :, ii])

    # Curvature along z: (Nz-1, Ny, Nx)
    eta_psi_z = np.zeros((dev.Nz - 1, dev.Ny, dev.Nx))
    for jj in range(dev.Ny):
        for ii in range(dev.Nx):
            eta_psi_z[:, jj, ii] = indicator_curvature(dev.mesh.z, psi[:, jj, ii])

    # Log-density gradients along x: (Nz, Ny, Nx-1)
    eta_n_x = np.zeros((dev.Nz, dev.Ny, dev.Nx - 1))
    eta_p_x = np.zeros((dev.Nz, dev.Ny, dev.Nx - 1))
    for kk in range(dev.Nz):
        for jj in range(dev.Ny):
            eta_n_x[kk, jj, :] = indicator_log_density(
                dev.mesh.x, n[kk, jj, :], p[kk, jj, :])
            eta_p_x[kk, jj, :] = indicator_log_density(
                dev.mesh.x, p[kk, jj, :], n[kk, jj, :])

    # Log-density gradients along y: (Nz, Ny-1, Nx)
    eta_n_y = np.zeros((dev.Nz, dev.Ny - 1, dev.Nx))
    eta_p_y = np.zeros((dev.Nz, dev.Ny - 1, dev.Nx))
    for kk in range(dev.Nz):
        for ii in range(dev.Nx):
            eta_n_y[kk, :, ii] = indicator_log_density(
                dev.mesh.y, n[kk, :, ii], p[kk, :, ii])
            eta_p_y[kk, :, ii] = indicator_log_density(
                dev.mesh.y, p[kk, :, ii], n[kk, :, ii])

    # Log-density gradients along z: (Nz-1, Ny, Nx)
    eta_n_z = np.zeros((dev.Nz - 1, dev.Ny, dev.Nx))
    eta_p_z = np.zeros((dev.Nz - 1, dev.Ny, dev.Nx))
    for jj in range(dev.Ny):
        for ii in range(dev.Nx):
            eta_n_z[:, jj, ii] = indicator_log_density(
                dev.mesh.z, n[:, jj, ii], p[:, jj, ii])
            eta_p_z[:, jj, ii] = indicator_log_density(
                dev.mesh.z, p[:, jj, ii], n[:, jj, ii])

    # Combine along each axis (normalise each indicator by its own peak)
    dens_x = np.maximum(eta_n_x, eta_p_x)
    eta_x = (eta_psi_x / max(float(np.max(np.abs(eta_psi_x))), _TINY)
             + dens_x / max(float(np.max(np.abs(dens_x))), _TINY))

    dens_y = np.maximum(eta_n_y, eta_p_y)
    eta_y = (eta_psi_y / max(float(np.max(np.abs(eta_psi_y))), _TINY)
             + dens_y / max(float(np.max(np.abs(dens_y))), _TINY))

    dens_z = np.maximum(eta_n_z, eta_p_z)
    eta_z = (eta_psi_z / max(float(np.max(np.abs(eta_psi_z))), _TINY)
             + dens_z / max(float(np.max(np.abs(dens_z))), _TINY))

    return eta_x, eta_y, eta_z


def _reduce_all_2d(eta_x, eta_y):
    """Flatten 2D per-axis indicators to 1D per-cell arrays for
    Dorfler marking and combining."""
    return eta_x.ravel(), eta_y.ravel()


def refine_2d(mesh, marked_x, marked_y, ratio=2.0, max_nodes=None):
    """Refine a 2D tensor-product mesh by independently bisecting cells
    along the x and y axes.

    `marked_x` : indices along x to bisect (length Nx-1 cells -> indices
                 into range(Nx-1))
    `marked_y` : indices along y to bisect (length Ny-1 cells)

    Returns a new Mesh2D with refined x and/or y.

    The 2:1 balance condition applies independently to each axis.
    Refining one cell refines an entire row/column -- the structural
    limitation of separable refinement on tensor-product meshes.
    """
    x = np.asarray(mesh.x, dtype=float).copy()
    y = np.asarray(mesh.y, dtype=float).copy()

    marked_x = np.asarray(marked_x, dtype=int).ravel()
    marked_y = np.asarray(marked_y, dtype=int).ravel()

    cap = np.inf if max_nodes is None else int(max_nodes)

    # Refine x axis
    if marked_x.size > 0:
        x_new = refine_1d(x, marked_x, ratio=ratio, max_nodes=max_nodes)
        if x_new.size > x.size:
            x = x_new

    # Refine y axis
    if marked_y.size > 0:
        y_new = refine_1d(y, marked_y, ratio=ratio, max_nodes=max_nodes)
        if y_new.size > y.size:
            y = y_new

    # Check node budget
    if x.size * y.size > cap:
        # Return original if budget exceeded
        return type(mesh)(mesh.x.copy(), mesh.y.copy())

    return type(mesh)(x, y)


def refine_3d(mesh, marked_x, marked_y, marked_z, ratio=2.0, max_nodes=None):
    """Refine a 3D tensor-product mesh by independently bisecting cells
    along the x, y, and z axes.

    `marked_x` : indices along x to bisect (length Nx-1 cells)
    `marked_y` : indices along y to bisect (length Ny-1 cells)
    `marked_z` : indices along z to bisect (length Nz-1 cells)

    Returns a new Mesh3D with refined axes.
    """
    x = np.asarray(mesh.x, dtype=float).copy()
    y = np.asarray(mesh.y, dtype=float).copy()
    z = np.asarray(mesh.z, dtype=float).copy()

    marked_x = np.asarray(marked_x, dtype=int).ravel()
    marked_y = np.asarray(marked_y, dtype=int).ravel()
    marked_z = np.asarray(marked_z, dtype=int).ravel()

    cap = np.inf if max_nodes is None else int(max_nodes)

    # Refine x axis
    if marked_x.size > 0:
        x_new = refine_1d(x, marked_x, ratio=ratio, max_nodes=max_nodes)
        if x_new.size > x.size:
            x = x_new

    # Refine y axis
    if marked_y.size > 0:
        y_new = refine_1d(y, marked_y, ratio=ratio, max_nodes=max_nodes)
        if y_new.size > y.size:
            y = y_new

    # Refine z axis
    if marked_z.size > 0:
        z_new = refine_1d(z, marked_z, ratio=ratio, max_nodes=max_nodes)
        if z_new.size > z.size:
            z = z_new

    # Check node budget
    if x.size * y.size * z.size > cap:
        return type(mesh)(mesh.x.copy(), mesh.y.copy(), mesh.z.copy())

    return type(mesh)(x, y, z)


# ----------------------------------------------------------------------
#  Phase 2 drivers
# ----------------------------------------------------------------------

def _qoi_2d(dev):
    """Total |rho| dV for 2D devices."""
    rho = dev.n - dev.p - dev.C
    return float(np.sum(np.abs(rho).ravel() * dev.mesh.dV))


def _qoi_3d(dev):
    """Total |rho| dV for 3D devices."""
    rho = dev.n - dev.p - dev.C
    return float(np.sum(np.abs(rho).ravel() * dev.mesh.dV))


def adapt_solve_2d(build_device, mesh0, *, qoi=None, solve=None,
                   indicator=None, max_passes=6, tol=1e-3, theta=0.5,
                   max_nodes=200000, debye_target=1.0):
    """Adaptive h-refinement for 2D devices on tensor-product meshes.

    build_device(mesh) -> Device2D  caller owns doping, materials, Models
    solve(device)                  caller's solve sequence; defaults to
                                   solve_equilibrium()
    qoi(device) -> float           the scalar convergence is measured on
    indicator(device) -> (eta_x, eta_y)  per-cell 2D indicators (Ny, Nx-1)
                                         and ((Ny-1), Nx)

    Returns (device, mesh, history).  History records per pass: node
    count, QoI, delta, marked_x/marked_y fractions, and cause.

    The separable limitation is structural: refining one cell refines
    an entire row/column.  The driver does not hide this.
    """
    if solve is None:
        solve = lambda d: d.solve_equilibrium()
    if indicator is None:
        indicator = default_indicator_2d
    if qoi is None:
        qoi = _qoi_2d

    mesh = mesh0
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
                f"{mesh.N} nodes -- the solve did not produce a usable "
                f"state, and refining on it would compound nonsense")
        delta = (np.inf if prev_q is None
                 else abs(q - prev_q) / max(abs(q), _TINY))
        entry = {"pass": it, "nodes": int(mesh.N), "qoi": q,
                 "delta": delta, "marked_x": 0, "marked_y": 0,
                 "debye_violations_x": 0, "debye_violations_y": 0,
                 "cause": None}
        history.append(entry)

        # (1) mesh-quality constraint: h/L_D <= debye_target on each axis.
        # Compute per-node Debye lengths from doping, then per-cell ratios.
        dop = np.abs(dev.doping)
        LD = _debye_length(dop, T=dev.T)
        # Debye indicator along x: (Ny, Nx-1) cells
        debye_x = np.diff(mesh.x) / np.minimum(LD[:, :-1], LD[:, 1:])
        # Debye indicator along y: (Ny-1, Nx) cells
        debye_y = np.diff(mesh.y)[:, None] / np.minimum(LD[:-1, :], LD[1:, :])

        # Find max h/L_D per x-cell (averaged across y rows)
        viol_x = np.flatnonzero(debye_x.mean(axis=0) > debye_target)
        viol_y = np.flatnonzero(debye_y.mean(axis=1) > debye_target)
        entry["debye_violations_x"] = int(viol_x.size)
        entry["debye_violations_y"] = int(viol_y.size)

        # (1b) tol-based convergence, gated on debye adequacy -- mirrors
        # adapt_solve_1d's placement exactly (see its docstring, part 1):
        # `prev_q` is updated unconditionally every pass so `delta` is
        # meaningful even while cells keep getting marked for the error
        # indicator (the common case; Dorfler marking rarely returns an
        # empty set while theta < 1).
        if viol_x.size == 0 and viol_y.size == 0:
            if prev_q is None:
                cause = "already_adequate"
                break
            if delta <= tol:
                cause = "converged"
                break
        prev_q = q

        # (2) error indicator
        eta_x, eta_y = indicator(dev)

        if eta_x.size == 0 and eta_y.size == 0:
            marked_x, marked_y = viol_x, viol_y
        else:
            # Mark cells along each axis using Doerfler on the reduced
            # indicator, unioned with the Debye violations.
            marked_x = np.union1d(mark_dorfler(reduce_x(eta_x), theta), viol_x)
            marked_y = np.union1d(mark_dorfler(reduce_y(eta_y), theta), viol_y)

        entry["marked_x"] = int(marked_x.size)
        entry["marked_y"] = int(marked_y.size)

        if marked_x.size == 0 and marked_y.size == 0:
            cause = "converged"
            break

        new_mesh = refine_2d(mesh, marked_x, marked_y,
                             ratio=2.0, max_nodes=max_nodes)
        if new_mesh.N == mesh.N:
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


def adapt_solve_3d(build_device, mesh0, *, qoi=None, solve=None,
                   indicator=None, max_passes=6, tol=1e-3, theta=0.5,
                   max_nodes=200000, debye_target=1.0):
    """Adaptive h-refinement for 3D devices on tensor-product meshes.

    Same pattern as adapt_solve_2d but with three axes.
    """
    if solve is None:
        solve = lambda d: d.solve_equilibrium()
    if indicator is None:
        indicator = default_indicator_3d
    if qoi is None:
        qoi = _qoi_3d

    mesh = mesh0
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
                f"{mesh.N} nodes -- the solve did not produce a usable "
                f"state, and refining on it would compound nonsense")
        delta = (np.inf if prev_q is None
                 else abs(q - prev_q) / max(abs(q), _TINY))
        entry = {"pass": it, "nodes": int(mesh.N), "qoi": q,
                 "delta": delta, "marked_x": 0, "marked_y": 0,
                 "marked_z": 0, "debye_violations_x": 0,
                 "debye_violations_y": 0, "debye_violations_z": 0,
                 "cause": None}
        history.append(entry)

        # Debye constraint per axis: compute from doping array.
        dop = np.abs(dev.doping)
        LD = _debye_length(dop, T=dev.T)
        debye_x = np.diff(mesh.x) / np.minimum(LD[:, :, :-1], LD[:, :, 1:])
        debye_y = np.diff(mesh.y)[None, :, None] / np.minimum(
            LD[:, :-1, :], LD[:, 1:, :])
        debye_z = np.diff(mesh.z)[:, None, None] / np.minimum(
            LD[:-1, :, :], LD[1:, :, :])

        viol_x = np.flatnonzero(debye_x.mean(axis=(0, 1)) > debye_target)
        viol_y = np.flatnonzero(debye_y.mean(axis=(0, 2)) > debye_target)
        viol_z = np.flatnonzero(debye_z.mean(axis=(1, 2)) > debye_target)
        entry["debye_violations_x"] = int(viol_x.size)
        entry["debye_violations_y"] = int(viol_y.size)
        entry["debye_violations_z"] = int(viol_z.size)

        # (1b) tol-based convergence, gated on debye adequacy -- see the
        # matching comment in adapt_solve_2d for why `prev_q` is updated
        # unconditionally every pass here.
        if viol_x.size == 0 and viol_y.size == 0 and viol_z.size == 0:
            if prev_q is None:
                cause = "already_adequate"
                break
            if delta <= tol:
                cause = "converged"
                break
        prev_q = q

        eta_x, eta_y, eta_z = indicator(dev)

        if eta_x.size == 0 and eta_y.size == 0 and eta_z.size == 0:
            marked_x, marked_y, marked_z = viol_x, viol_y, viol_z
        else:
            marked_x = np.union1d(mark_dorfler(reduce_x(eta_x), theta), viol_x)
            marked_y = np.union1d(mark_dorfler(reduce_y(eta_y), theta), viol_y)
            marked_z = np.union1d(mark_dorfler(reduce_z(eta_z), theta), viol_z)

        entry["marked_x"] = int(marked_x.size)
        entry["marked_y"] = int(marked_y.size)
        entry["marked_z"] = int(marked_z.size)

        if marked_x.size == 0 and marked_y.size == 0 and marked_z.size == 0:
            cause = "converged"
            break

        new_mesh = refine_3d(mesh, marked_x, marked_y, marked_z,
                             ratio=2.0, max_nodes=max_nodes)
        if new_mesh.N == mesh.N:
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
