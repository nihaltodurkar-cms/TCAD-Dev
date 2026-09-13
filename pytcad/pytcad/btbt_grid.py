"""M16-S2: local Kane BTBT (pytcad/btbt.py) on a structured 2D/3D grid.

Mirrors `ii_grid.py`'s shape and contract so Device2D/Device3D can call
one kernel for either generation model.  Per node i, over every grid
axis a:

    E_a,i = mean over the node's incident a-edges of |E_e|
    F_i   = sqrt( sum_a E_a,i^2 )
    G_i   = A * F_i^2 * exp(-B / F_i)          [cm^-3 s^-1]  (btbt.py)

This is the same per-axis edge average `ii_grid.grid_impact` computes
(the `inv = 1/count` weighting), combined by Euclidean norm rather than
projected onto a current direction -- BTBT is driven by field
magnitude, not by transport along anything, so there is no current
direction here and no eps-smoothing.

Two reductions are EXACT (not just round-off-close), because unlike
`ii_grid.py` there is no eps-smoothed |J| anywhere in this model:

1. one axis: F = E_x = the mean of the node's incident x-edge
   magnitudes, bit-for-bit device.py's `_ii_compute_E_from_state`.
2. transverse-uniform: psi_R = psi_L exactly on every transverse edge,
   so the transverse E_a is exactly 0 and F = E_x.

See M16-S2-PLAN.md sections 1-2 for the derivation.
"""
import numpy as np

from .btbt import btbt_generation, dbtbt_dF
from .ii_grid import _ratio


def grid_btbt(N, axes, psi, VT, LD, R0):
    """Local Kane BTBT generation on a structured grid.

    N    : node count; node indices are the devices' flat (row-major) ones.
    axes : one dict per grid axis, each array flat over that axis's edges:
           kL, kR   end nodes (lower / upper index along the axis)
           h        scaled edge length (x/LD units)
           (the `Jn`/`Jp`/current-derivative entries `ii_grid` also
           carries are ignored here -- BTBT depends on psi only.)
    psi  : flat potential (units of VT).

    Returns (G, rows, cols, vals, F_node): G (N,) generation scaled by
    1/R0 (physical cm^-3 s^-1 / R0, matching ii_grid's scaled G); the
    Jacobian dG_i/dpsi_j as COO triples (cols are 3*node, psi component
    only); and F_node [V/cm], the field G was evaluated at.
    """
    per = []
    for ax in axes:
        kL, kR = ax["kL"], ax["kR"]
        cnt = (np.bincount(kL, minlength=N)
               + np.bincount(kR, minlength=N)).astype(float)
        inv = _ratio(np.ones(N), cnt)
        dpsi = psi[kR] - psi[kL]
        cE = VT / (LD * ax["h"])                      # V/cm per unit psi
        Ee = np.abs(dpsi) * cE
        Ea = (np.bincount(kL, Ee, N) + np.bincount(kR, Ee, N)) * inv
        per.append(dict(ax=ax, inv=inv, Ea=Ea, cEs=np.sign(dpsi) * cE))

    F_node = np.sqrt(sum(a["Ea"] * a["Ea"] for a in per))
    G_phys = btbt_generation(F_node)
    dG_dF = dbtbt_dF(F_node)
    G = G_phys / R0

    rows, cols, vals = [], [], []
    for a in per:
        ax, inv = a["ax"], a["inv"]
        ratio = _ratio(a["Ea"], F_node)          # dF/dE_a
        g = dG_dF * ratio / R0                   # dG_i/dE_a,i
        kL, kR = ax["kL"], ax["kR"]
        for i in (kL, kR):                       # the edge enters both ends
            c = g[i] * inv[i] * a["cEs"]
            rows.append(i); cols.append(3 * kL); vals.append(-c)
            rows.append(i); cols.append(3 * kR); vals.append(c)

    return (G, np.concatenate(rows), np.concatenate(cols),
            np.concatenate(vals), F_node)
