"""M44 Slice 3: dimension-generic (2D or 3D) structured-grid electron
energy-balance assembly, for the eventual Device2D/Device3D dimensional
lift (Slice 4).

ARCHITECTURE NOTE (revised from the Slice 3 plan text before writing
this file): the plan originally said "mirrors thermal_grid.py exactly"
-- that turned out to be the wrong sibling to copy. thermal_grid.py
solves lattice temperature via a SEPARATE, NESTED Newton solve inside
an outer Gummel loop (thermal.py's own docstring: "isothermal DD +
outer thermal loop"), which is what made it hot enough to justify
compiling. M44 Slice 1's own architecture is different: Tn is an
APPENDED DOF inside the SAME single Newton iterate as psi/n/p (no
nested solve, no outer loop) -- exactly the cost profile of
`ii_grid.py`/`btbt_grid.py` (M34-S6), which stay pure Python and are
NOT compiled. So this module follows THEIR calling convention (a flat
`axes` list of per-axis edge arrays with `kL`/`kR` node indices,
returning (F, rows, cols, vals) COO triples the caller stamps into its
own residual -- see `ii_grid.grid_impact`'s own docstring for the
precedent), not thermal_grid.py's raw-coordinate/ND-array one. Whether
this ends up needing a C++ compile at all is a Slice-3 MEASUREMENT
question (same discipline as Slice 2), not assumed from the sibling
that turned out not to match.

Physics: identical to Device1D's own Slice 1 equation (steady-state
three-moment energy-transport model, Grasser/Tang/Kosina/Selberherr
2003 Eqs. 58-59 with d/dt dropped), box-integrated over a structured
D-axis grid, summing the flux divergence over every axis:

    F_T[node] = sum_axis (flux divergence along that axis)
                - dV[node] * Q_src[node]
    Q_src     = Qheat_lag - ALPHA * n_lag * (theta - 1)
    flux[edge]= -(5/2)*theta_edge*Jn_lag[edge]
                - kappa_edge(theta) * (theta[kR]-theta[kL])/h[edge]
    kappa_s[node] = KAPPA0 * mu_n0[node] * n_lag[node] * theta[node]

`n_lag`, `Jn_lag` (per axis), `Qheat_lag` are LAGGED (frozen, one outer
Newton iterate old) exactly as in Device1D's own `_residual_jacobian`
-- so this block's Jacobian is, by construction, a pure function of
`theta` alone (zero cross-coupling into psi/n/p), same design
invariant Slice 1's own FD-Jacobian gate checks.

A boundary/contact node with theta pinned to 1.0 (Tn=TL) is given
directly as `dirichlet_nodes` (flat node indices) -- an ordinary
insulating mesh boundary needs no special handling: a node with fewer
incident edges gets an implicit zero-flux Neumann condition "for free"
from the box-integration sum, the same way Poisson's own equation
already gets it in device2d.py/device3d.py.
"""
import numpy as np


def grid_hydro(N, axes, dV, n_lag, theta, Qheat_lag, mu_n0, KAPPA0, ALPHA,
               dirichlet_nodes):
    """Structured D-axis (D=2 or 3) electron energy-balance residual +
    Jacobian, appended-DOF convention (see module docstring).

    N            : node count (flat, row-major -- the device's own
                   convention).
    axes         : one dict per grid axis, each with flat edge arrays
                   kL, kR (node indices, kL along the "lower" side),
                   h (scaled edge length), Jn (LAGGED scaled electron
                   edge current along this axis, oriented kL->kR), and
                   w (the TRANSVERSE control-volume width at that
                   edge -- e.g. in 2D, dVy[row] for an x-axis edge,
                   dVx[col] for a y-axis edge; in 3D, the PRODUCT of
                   the other two axes' local widths. Mandatory, not
                   optional: an x-face's flux has a "depth" in y (and
                   z), exactly like device2d.py's own Poisson residual
                   weights its two divergence terms by dVy[:,None] and
                   dVx[None,:] respectively. Omitting this was a real
                   bug found while gating Slice 4 -- see
                   M44-HYDRODYNAMIC-PLAN.md Slice 4 note 3: without it,
                   the flux-divergence term and the dV-weighted source
                   term use INCONSISTENT relative weightings between a
                   boundary row (half-width dVy) and an interior row
                   (full-width dVy), breaking exact y/z-uniformity).
    dV           : (N,) scaled control-volume width (already computed
                   by the device -- box-integration convention).
    n_lag        : (N,) LAGGED scaled electron density.
    theta        : (N,) CURRENT Tn/T iterate (the unknown).
    Qheat_lag    : (N,) LAGGED Joule-heating source (E_n.Jn, already
                   box-averaged to nodes exactly as Device1D's own
                   Wachutka-term computation does -- see
                   M44-HYDRODYNAMIC-PLAN.md Slice 1 note 2).
    mu_n0        : (N,) physical low-field electron mobility.
    KAPPA0, ALPHA: device-level scaling constants (Device1D's own
                   `_KAPPA0`/`_ALPHA_RELAX` formulas, unchanged).
    dirichlet_nodes : flat node indices pinned to theta=1 (contacts).

    Returns (F, rows, cols, vals) -- F is (N,), rows/cols/vals are COO
    triples for an (N, N) Jacobian block (the caller offsets them by
    its own `3*N` base before stamping, same as Device1D's own `base`
    offset in `_residual_jacobian`).
    """
    # M44 Slice 4 finding: kappa_s (and the relaxation term) are
    # multiplicative in n_lag, which underflows to ~1e-14 or below in a
    # device's deep-minority-carrier regions (same regime the existing
    # `_STIFF_DENSITY_FLOOR` -- device.py's own n/p convergence-metric
    # floor -- already exists for). Left unfloored, kappa_s vanishes
    # there, decoupling those nodes from their neighbors in EVERY
    # direction at once and making the assembled Jacobian measurably
    # rank-deficient (confirmed directly: rank 72/123 on a real device
    # state before this fix, condition number ~3e14) -- theta at those
    # nodes becomes numerically arbitrary, not physically meaningless
    # (a node with essentially zero carriers has no meaningful electron
    # temperature anyway, so flooring is the correct physical choice,
    # not just a numerical patch).
    n_floor = np.maximum(n_lag, 1e-8)
    kappa_s = KAPPA0 * mu_n0 * n_floor * theta
    Q_src = Qheat_lag - ALPHA * n_floor * (theta - 1.0)
    dQ_dtheta = -ALPHA * n_floor

    F = -dV * Q_src
    diag = -dV * dQ_dtheta
    rows, cols, vals = [], [], []

    for ax in axes:
        kL, kR = ax["kL"], ax["kR"]
        h, Jn, w = ax["h"], ax["Jn"], ax["w"]
        theta_edge = 0.5 * (theta[kL] + theta[kR])
        kappa_edge = 0.5 * (kappa_s[kL] + kappa_s[kR])
        grad_theta = (theta[kR] - theta[kL]) / h
        # w (the TRANSVERSE control-volume width) multiplies the WHOLE
        # face flux, same as device2d.py's own dVy[:,None]*div_x --
        # this is what makes a boundary row (half-width transverse CV)
        # and an interior row (full-width) weigh their OWN flux
        # against their OWN dV-scaled source term consistently. See
        # this module's own axes docstring / M44-HYDRODYNAMIC-PLAN.md
        # Slice 4 note 3 for the bug this fixes.
        flux = w * (-2.5 * theta_edge * Jn - kappa_edge * grad_theta)

        dkappa_L = 0.5 * KAPPA0 * mu_n0[kL] * n_floor[kL]
        dkappa_R = 0.5 * KAPPA0 * mu_n0[kR] * n_floor[kR]
        dflux_dthetaL = w * (-2.5 * 0.5 * Jn
                             - dkappa_L * grad_theta - kappa_edge * (-1.0 / h))
        dflux_dthetaR = w * (-2.5 * 0.5 * Jn
                             - dkappa_R * grad_theta - kappa_edge * (1.0 / h))

        # divergence: +flux through the kL->kR (this edge's) face for
        # the kL node, -flux for the kR node -- same convention as
        # Device1D's own F_T[i] = w_edge[Rt] - w_edge[L].
        F += np.bincount(kL, flux, N) - np.bincount(kR, flux, N)
        diag += (np.bincount(kL, dflux_dthetaL, N)
                - np.bincount(kR, dflux_dthetaR, N))

        rows.append(kL); cols.append(kR); vals.append(dflux_dthetaR)
        rows.append(kR); cols.append(kL); vals.append(-dflux_dthetaL)

    rows.append(np.arange(N)); cols.append(np.arange(N)); vals.append(diag)

    if len(dirichlet_nodes):
        dn = np.asarray(dirichlet_nodes, dtype=int)
        F[dn] = theta[dn] - 1.0
        keep = ~np.isin(np.concatenate(rows), dn)
        rows = [np.concatenate(rows)[keep]]
        cols = [np.concatenate(cols)[keep]]
        vals = [np.concatenate(vals)[keep]]
        rows.append(dn); cols.append(dn); vals.append(np.ones(dn.size))

    return F, np.concatenate(rows), np.concatenate(cols), np.concatenate(vals)
