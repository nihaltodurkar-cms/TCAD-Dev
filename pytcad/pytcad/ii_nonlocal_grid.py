"""M34-S6c: nonlocal (effective-field) impact ionization on structured
2D/3D grids -- the grid generalization of `ii_nonlocal.effective_field`
(M34-S6-PLAN.md section 2), feeding `ii_grid.grid_impact`'s `eff=`.

`lambda dE_eff/ds + E_eff = |E|` is solved along each carrier's flow on
the grid's edge graph, one axis at a time for direction assignment, then
combined into a single DAG for the relaxation itself:

  * per edge, the relaxation source is the field ALONG THAT EDGE;
  * direction per edge: strong edges (|E| >= E_STRONG_VCM) take it from
    the field sign (electrons toward higher psi, holes toward lower, the
    same convention as `ii_nonlocal`); weaker edges inherit the nearest
    strong edge's direction on the SAME grid line (fixed transverse
    indices, varying only along that edge's own axis) -- so a
    transversely uniform device reproduces `ii_nonlocal.effective_field`
    exactly, line by line;
  * a node with several inflowing edges (from one axis or several) takes
    their mean;
  * the per-edge relaxation is exact (piecewise-constant field), so the
    DAG is walked in topological (Kahn) order across ALL axes combined;
    a cycle -- impossible among strong edges alone, since psi rises
    along them, but not ruled out once weak edges inherit directions
    from different lines -- is broken by processing whatever nodes are
    left in potential order (ascending psi for electrons, descending for
    holes, matching each carrier's own downstream sense);
  * E_eff is linear in the edge field magnitudes for a fixed direction
    pattern (E_eff = W |E_edge|), so the Jacobian is exact; W is built
    and kept sparse, entries pruned below 1e-15 of their row's largest,
    which is what keeps the walk's per-node work bounded instead of
    accumulating a dense row over a long chain.
"""
from collections import deque

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import splu

from .ii_nonlocal import E_STRONG_VCM

__all__ = ["effective_field_grid", "E_STRONG_VCM"]


def _to_lines(flat, edge_shape, vary):
    """Reshape a flat (row-major) per-edge array into (n_lines, L), L the
    edge count along `vary` -- every line on a structured axis has the
    same length, so this is exact, not an approximation."""
    arr = np.moveaxis(flat.reshape(edge_shape), vary, -1)
    return arr.reshape(-1, edge_shape[vary])


def _from_lines(arr2d, edge_shape, vary):
    """Inverse of `_to_lines`."""
    L = edge_shape[vary]
    moved_shape = tuple(s for d, s in enumerate(edge_shape) if d != vary) + (L,)
    return np.moveaxis(arr2d.reshape(moved_shape), -1, vary).ravel()


def _propagate_signs_2d(s2, strong2, pos2):
    """Vectorized, ALL LINES OF ONE AXIS AT ONCE: weak edges inherit the
    nearest strong edge's sign, by physical distance along the line
    (`pos2`, a cumulative length so only differences matter); an all-weak
    line is entirely cold.  Tie (equidistant) goes to the earlier edge,
    matching `ii_nonlocal.effective_field`'s chain rule.  Equivalent to
    running that rule line by line -- verified in
    tests/test_m34_s6c_impact_nonlocal_grid.py -- but O(1) numpy calls
    instead of one Python-level loop iteration per line, which is what
    made the naive per-line version too slow to gate (measured: the
    S6a/S6b-equivalent suite finishes in ~70s; the per-line loop version
    of this function did not finish an equivalent S6c suite in 30
    minutes on a ~3000-node 3D device)."""
    n_lines, L = s2.shape
    idx = np.broadcast_to(np.arange(L), (n_lines, L))
    fwd_idx = np.maximum.accumulate(np.where(strong2, idx, -1), axis=-1)
    bwd_idx = np.minimum.accumulate(
        np.where(strong2, idx, L)[:, ::-1], axis=-1)[:, ::-1]
    has_fwd, has_bwd = fwd_idx >= 0, bwd_idx < L
    safe_fwd, safe_bwd = np.clip(fwd_idx, 0, L - 1), np.clip(bwd_idx, 0, L - 1)
    pos_fwd = np.take_along_axis(pos2, safe_fwd, axis=-1)
    pos_bwd = np.take_along_axis(pos2, safe_bwd, axis=-1)
    d_fwd = np.where(has_fwd, pos2 - pos_fwd, np.inf)
    d_bwd = np.where(has_bwd, pos_bwd - pos2, np.inf)
    near_idx = np.where(d_fwd <= d_bwd, safe_fwd, safe_bwd)
    s_near = np.take_along_axis(s2, near_idx, axis=-1)
    direction2 = np.where(strong2, s2, s_near)
    return np.where(strong2.any(axis=-1, keepdims=True), direction2, 0.0)


def _per_axis(shape, axes, psi, VT, LD, carrier):
    """One pass: for every axis, the edge field magnitude, its d/dpsi
    (dense over kL/kR, every edge), and the direction pattern (0 = cold)."""
    ndim = len(shape)
    out = []
    for ai, ax in enumerate(axes):
        kL, kR, h = ax["kL"], ax["kR"], ax["h"]
        vary = ndim - 1 - ai
        edge_shape = list(shape)
        edge_shape[vary] -= 1
        edge_shape = tuple(edge_shape)

        dpsi = psi[kR] - psi[kL]
        cE = VT / (LD * h)
        Emag = np.abs(dpsi) * cE
        s = np.sign(dpsi) if carrier == "n" else -np.sign(dpsi)
        strong = Emag >= E_STRONG_VCM

        s2 = _to_lines(s, edge_shape, vary)
        strong2 = _to_lines(strong, edge_shape, vary)
        pos2 = np.cumsum(_to_lines(h, edge_shape, vary), axis=-1)
        direction = _from_lines(
            _propagate_signs_2d(s2, strong2, pos2), edge_shape, vary)

        out.append(dict(kL=kL, kR=kR, Emag=Emag, direction=direction,
                         dEmag_dpsiR=np.sign(dpsi) * cE))
    return out


def effective_field_grid(shape, axes, psi, VT, LD, carrier, lam_cm):
    """Per-node effective field [V/cm] of `carrier` ('n' or 'p') on a
    structured grid, plus its (N, N) sparse d/dpsi.

    shape : full node grid shape, numpy order -- (Ny, Nx) or (Nz, Ny, Nx),
            matching how the device reshapes/ravels psi.
    axes  : the same per-axis dicts `ii_grid.grid_impact` takes (kL, kR,
            h), ordered x, y[, z] -- one entry per grid axis.

    Returns (E_eff (N,), D (scipy.sparse, N x N)).
    """
    shape = tuple(int(s) for s in shape)
    N = int(np.prod(shape))
    psi = np.asarray(psi, dtype=float).reshape(N)
    if carrier not in ("n", "p"):
        raise ValueError(f"carrier must be 'n' or 'p', got {carrier!r}")

    per = _per_axis(shape, axes, psi, VT, LD, carrier)

    # dEmag/dpsi over EVERY edge of every axis (cold edges included, they
    # still carry a well-defined field, they just propagate nothing) --
    # built once, columns indexed globally 0..n_edges_total-1.
    dEmag_rows, dEmag_cols, dEmag_vals = [], [], []
    all_up, all_down, all_a, all_Emag, act_cols = [], [], [], [], []
    col0 = 0
    for a in per:
        kL, kR, Emag = a["kL"], a["kR"], a["Emag"]
        direction = a["direction"]
        n_e = kL.size
        cols = np.arange(col0, col0 + n_e)
        dEmag_rows += [cols, cols]
        dEmag_cols += [kR, kL]
        dEmag_vals += [a["dEmag_dpsiR"], -a["dEmag_dpsiR"]]

        active = direction != 0.0
        if active.any():
            up = np.where(direction > 0, kL, kR)[active]
            down = np.where(direction > 0, kR, kL)[active]
            all_up.append(up)
            all_down.append(down)
            all_Emag.append(Emag[active])
            act_cols.append(cols[active])
        col0 += n_e
    n_edges_total = col0

    # re-derive h_cm per axis (kept alongside Emag/direction for clarity)
    all_a_list = []
    for ax, a in zip(axes, per):
        active = a["direction"] != 0.0
        if active.any():
            all_a_list.append(np.exp(-(LD * ax["h"][active]) / lam_cm))

    if all_up:
        all_up = np.concatenate(all_up)
        all_down = np.concatenate(all_down)
        all_a = np.concatenate(all_a_list)
        all_Emag = np.concatenate(all_Emag)
        act_cols = np.concatenate(act_cols)
    else:
        all_up = np.zeros(0, dtype=int)
        all_down = np.zeros(0, dtype=int)
        all_a = np.zeros(0)
        all_Emag = np.zeros(0)
        act_cols = np.zeros(0, dtype=int)
    n_act = all_up.size

    # Topological order across ALL axes' active edges combined (Kahn),
    # cycle leftovers (impossible among strong edges alone, but not ruled
    # out once weak edges inherit from different lines) broken by
    # potential order -- ascending psi for electrons, descending for
    # holes, each carrier's own downstream sense.
    def _groups(key, n):
        order = np.argsort(key, kind="stable")
        starts = np.searchsorted(key[order], np.arange(n + 1))
        return order, starts

    up_order, up_starts = _groups(all_up, N)

    def out_edges_of(v):
        return up_order[up_starts[v]:up_starts[v + 1]]

    indeg = np.bincount(all_down, minlength=N).copy()
    q = deque(int(v) for v in np.nonzero(indeg == 0)[0])
    processed = np.zeros(N, dtype=bool)
    order_list = []
    while q:
        v = q.popleft()
        if processed[v]:
            continue
        processed[v] = True
        order_list.append(v)
        for e in out_edges_of(v):
            d = int(all_down[e])
            indeg[d] -= 1
            if indeg[d] == 0:
                q.append(d)
    leftover = np.nonzero(~processed)[0]
    if leftover.size:
        key = psi if carrier == "n" else -psi
        leftover = leftover[np.argsort(key[leftover], kind="stable")]
        order_list.extend(int(v) for v in leftover)
    pos_in_order = np.empty(N, dtype=int)
    pos_in_order[np.array(order_list, dtype=int)] = np.arange(N)

    # E_eff solves (I - M) E = Source exactly, M/Source built from the
    # per-node mean of inflow edges (a node with several inflows takes
    # their mean).  M keeps only edges that run FORWARD in the
    # topological order -- a "back" edge (only possible among the
    # potential-order cycle leftovers) still contributes its own
    # (1 - a) * Emag source term (that edge's field is real), it just
    # cannot propagate an upstream E_eff that is not yet resolved,
    # exactly like walking the DAG node by node would leave it at 0
    # there.  (I - M) is unit-diagonal, row-sum-of-off-diagonal < 1 (each
    # a_e < 1), so it is diagonally dominant and its LU is stable; this
    # is one sparse factorization applied to the source vector AND, for
    # the Jacobian, to N right-hand sides at once -- exact and, unlike a
    # per-node Python DP over an exponentially-decaying chain (measured:
    # rows averaging ~400 entries on a fine mesh before the 1e-15 prune
    # bites), compiled.
    ins_count = np.bincount(all_down, minlength=N).astype(float)
    inv_ins = np.divide(1.0, ins_count, out=np.zeros(N), where=ins_count > 0)
    Source = np.bincount(all_down, weights=(1.0 - all_a) * all_Emag,
                          minlength=N) * inv_ins

    fwd = pos_in_order[all_up] < pos_in_order[all_down]
    M = sp.coo_matrix((all_a[fwd] * inv_ins[all_down[fwd]],
                       (all_down[fwd], all_up[fwd])), shape=(N, N)).tocsc()
    A = sp.identity(N, format="csc") - M

    dEmag_rows = np.concatenate(dEmag_rows)
    dEmag_cols = np.concatenate(dEmag_cols)
    dEmag_vals = np.concatenate(dEmag_vals)
    full = sp.coo_matrix((dEmag_vals, (dEmag_rows, dEmag_cols)),
                          shape=(n_edges_total, N)).tocsr()
    dEmag_active = full[act_cols, :]
    # C[v, e] = (1 - a_e)/ins_count[v] for every inflow edge e of v
    # (unconditionally -- the source term, not the propagated part)
    C = sp.coo_matrix(((1.0 - all_a) * inv_ins[all_down],
                       (all_down, np.arange(n_act))), shape=(N, n_act)).tocsr()

    lu = splu(A)
    E = lu.solve(Source)
    D = sp.csr_matrix(lu.solve((C @ dEmag_active).toarray()))
    return E, D
