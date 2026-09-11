"""M34: nonlocal band-to-band tunneling PATH ENGINE, shared by Device1D,
Device2D and Device3D (M34-PLAN.md sections 2 and 4).

A tunnel path is frozen GEOMETRY: a polyline of sample points, each
carrying an interpolation stencil onto mesh nodes, located once per
solve_bias call and refreshed after convergence (see the devices).
Everything that depends on the potential is LIVE and differentiated
analytically:
  * psi at each sample (stencil-weighted nodal psi), hence the band
    profile delta(s) = (E - Ev(s))/Eg along the path, with the tunnel
    energy E = Ev at the start node;
  * the WKB integrals int kappa ds and int ds/kappa, exact per segment
    (btbt.segment_integrals -- delta is linear along a segment);
  * eq (11)'s prefactor |dEv/dx| at the start (a gradient stencil);
  * eq (12)'s band extrema Emin/Emax (global psi extrema);
  * the electron deposit point, the live delta = 1 crossing, split
    linearly between the two samples of the crossing segment -- which
    conserves the pair count exactly and moves continuously with psi.

Physics: Esseni et al., Semicond. Sci. Technol. 32, 083005 (2017),
section 2.1, eqs (9), (11), (12); see btbt.py.  Single dominant
zero-transverse-momentum channel E = Ev(x_i), (fc - fv) = 1.  A path
that never reaches delta = 1 inside its frozen span is TRUNCATED: its
electrons go to the last sample and `reached` is False for it (the
devices re-locate paths until none is truncated).

Units: psi in units of VT (the devices' scaled potential), lengths in
m, energies in J, rates in m^-3 s^-1.
"""
import bisect
import math
from dataclasses import dataclass

import numpy as np
from scipy.sparse import coo_matrix, csr_matrix

from .btbt import HBAR_SI, Q_SI, segment_integrals
from . import _accel


@dataclass
class TunnelPaths:
    """Frozen geometry of P tunnel paths (flat storage).

    start   (P,)    start node of each path (holes deposited there; its
                    psi fixes the tunnel energy)
    offset  (P+1,)  samples of path p are offset[p] .. offset[p+1]-1
    sidx    (S, K)  stencil node indices of each sample
    swts    (S, K)  stencil weights (rows sum to 1; unused slots weight 0)
    seg_len (S,)    length [m] of the segment from sample s to s+1
                    (0 for the last sample of a path)
    gidx    (P, Kg) start-gradient stencil: dpsi/ds at the start [1/m]
    gwts    (P, Kg) is sum(gwts * psi[gidx])
    """
    start: np.ndarray
    offset: np.ndarray
    sidx: np.ndarray
    swts: np.ndarray
    seg_len: np.ndarray
    gidx: np.ndarray
    gwts: np.ndarray

    @property
    def n_paths(self):
        return int(self.start.size)

    def path_of_sample(self):
        return np.repeat(np.arange(self.n_paths), np.diff(self.offset))

    def nodes_of_path(self, p):
        """Every node path p can read or deposit into."""
        a, b = self.offset[p], self.offset[p + 1]
        idx = self.sidx[a:b][self.swts[a:b] != 0.0]
        return np.unique(np.concatenate([idx, [self.start[p]],
                                         self.gidx[p]]))


def empty_paths(K=1, Kg=2):
    return TunnelPaths(np.zeros(0, int), np.zeros(1, int),
                       np.zeros((0, K), int), np.zeros((0, K)),
                       np.zeros(0), np.zeros((0, Kg), int),
                       np.zeros((0, Kg)))


def build_1d(x_m, starts, ends):
    """Paths along a 1D mesh: path p runs over nodes starts[p]..ends[p]
    (samples ARE nodes, unit stencils); the start gradient is the start
    edge's difference quotient."""
    x_m = np.asarray(x_m, dtype=float)
    starts = np.asarray(starts, dtype=int)
    ends = np.asarray(ends, dtype=int)
    if starts.size == 0:
        return empty_paths()
    if np.any(ends <= starts):
        raise ValueError("every 1D path needs at least one edge")
    counts = ends - starts + 1
    offset = np.concatenate([[0], np.cumsum(counts)])
    sidx = np.concatenate([np.arange(a, b + 1)
                           for a, b in zip(starts, ends)])[:, None]
    swts = np.ones_like(sidx, dtype=float)
    seg_len = np.zeros(sidx.shape[0])
    seg = np.ones(sidx.shape[0], bool)
    seg[offset[1:] - 1] = False
    s = np.nonzero(seg)[0]
    seg_len[s] = x_m[sidx[s + 1, 0]] - x_m[sidx[s, 0]]
    h0 = x_m[starts + 1] - x_m[starts]
    gidx = np.stack([starts, starts + 1], axis=1)
    gwts = np.stack([-1.0 / h0, 1.0 / h0], axis=1)
    return TunnelPaths(starts, offset, sidx, swts, seg_len, gidx, gwts)


@dataclass
class PathEval:
    """Live evaluation of a TunnelPaths at one psi.

    G      (P,)   generation rate of each path [m^-3 s^-1] (eq 11)
    dG     csr (P, N)  dG/dpsi_node
    dep    csr (P, N)  electron deposit weights (each row sums to 1)
    ddep_p, ddep_node, ddep_col, ddep_val:  d dep[p, node] / d psi[col]
    Ik, Iik (P,)  int kappa ds [-], int ds/kappa [m^2]
    reached (P,)  the delta = 1 crossing lies inside the frozen span
    length  (P,)  arc length start -> crossing [m] (x_f - x_i)
    fmin, fmax (P,) min/max field [V/m] over the segments under the
                  barrier (0 < delta < 1 on some part of the segment)
    """
    G: np.ndarray
    dG: csr_matrix
    dep: csr_matrix
    ddep_p: np.ndarray
    ddep_node: np.ndarray
    ddep_col: np.ndarray
    ddep_val: np.ndarray
    Ik: np.ndarray
    Iik: np.ndarray
    reached: np.ndarray
    length: np.ndarray
    fmin: np.ndarray
    fmax: np.ndarray


def evaluate(paths, psi, VT, Eg_J, mr_kg, mc_kg, mv_kg,
             hbar=HBAR_SI, q=Q_SI):
    """Evaluate every path at the live `psi` (see the module docstring)."""
    psi = np.asarray(psi, dtype=float)
    N = psi.size
    P = paths.n_paths
    if P == 0:
        z = np.zeros(0)
        zi = np.zeros(0, int)
        return PathEval(z, csr_matrix((0, N)), csr_matrix((0, N)),
                        zi, zi, zi, z, z, z, np.zeros(0, bool), z, z, z)

    ps = paths.path_of_sample()
    S = ps.size
    K = paths.sidx.shape[1]
    st = paths.start
    sc = VT * q / Eg_J                        # d(delta)/d(psi)
    psi_s = np.sum(paths.swts * psi[paths.sidx], axis=1)
    raw = sc * (psi_s - psi[st][ps])          # unclipped delta per sample

    last = paths.offset[1:] - 1
    is_seg = np.ones(S, bool)
    is_seg[last] = False
    seg = np.nonzero(is_seg)[0]
    segp = ps[seg]
    da, db, L = raw[seg], raw[seg + 1], paths.seg_len[seg]
    Ik_s, Iik_s, dIk_a, dIk_b, dIik_a, dIik_b = segment_integrals(
        da, db, L, Eg_J, mr_kg, hbar)
    Ik = np.bincount(segp, Ik_s, minlength=P)
    Iik = np.bincount(segp, Iik_s, minlength=P)

    # fields over the barrier segments (diagnostic, gates G3/G7)
    D = np.abs(db - da)
    lo = np.clip(np.minimum(da, db), 0.0, 1.0)
    hi = np.clip(np.maximum(da, db), 0.0, 1.0)
    barrier = hi > lo
    F_seg = np.where(L > 0.0, D * Eg_J / (q * np.where(L > 0.0, L, 1.0)), 0.0)
    fmin = np.full(P, np.inf)
    fmax = np.full(P, -np.inf)
    np.minimum.at(fmin, segp[barrier], F_seg[barrier])
    np.maximum.at(fmax, segp[barrier], F_seg[barrier])

    # the delta = 1 crossing: first segment with da < 1 <= db
    cand = (da < 1.0) & (db >= 1.0)
    big = S + 1
    cross = np.full(P, big)
    np.minimum.at(cross, segp[cand], seg[cand])
    reached = cross < big
    cseg = np.where(reached, cross, last - 1)
    ca, cb = raw[cseg], raw[cseg + 1]
    Dc = np.where(reached, cb - ca, 1.0)
    t = np.where(reached, (1.0 - ca) / Dc, 1.0)
    dt_da = np.where(reached, (1.0 - cb) / (Dc * Dc), 0.0)
    dt_db = np.where(reached, -(1.0 - ca) / (Dc * Dc), 0.0)
    cs = np.concatenate([[0.0], np.cumsum(paths.seg_len)])
    length = cs[cseg] - cs[paths.offset[:-1]] + t * paths.seg_len[cseg]

    # eq (11) prefactor and eq (12) km^2, both live
    gval = np.sum(paths.gwts * psi[paths.gidx], axis=1)
    gabs = np.abs(gval)
    Pf = q * VT * gabs / (36.0 * hbar)
    imin = int(np.argmin(psi))
    imax = int(np.argmax(psi))
    E = -q * VT * psi[st]
    Emax = -q * VT * psi[imin]
    Emin = -q * VT * psi[imax] + Eg_J
    a_km = 2.0 * mv_kg * (Emax - E)
    b_km = 2.0 * mc_kg * (E - Emin)
    m_km = np.minimum(a_km, b_km)
    km2 = np.maximum(m_km, 0.0) / (hbar * hbar)

    ok = Iik > 0.0
    A = np.where(ok, 1.0 / np.where(ok, Iik, 1.0), 0.0)
    e1 = np.exp(-km2 * Iik)
    B = 1.0 - e1
    C = np.exp(-2.0 * Ik)
    G = np.where(ok, Pf * A * B * C, 0.0)

    dG_dIk = -2.0 * G
    dG_dIik = np.where(ok, Pf * (-A * A * B * C + A * km2 * e1 * C), 0.0)
    dG_dkm2 = np.where(ok, Pf * C * e1, 0.0)
    dG_dg = np.where(ok & (gabs > 0.0),
                     G / np.where(gabs > 0.0, gabs, 1.0), 0.0) * np.sign(gval)

    g_raw = np.zeros(S)
    np.add.at(g_raw, seg, dG_dIk[segp] * dIk_a + dG_dIik[segp] * dIik_a)
    np.add.at(g_raw, seg + 1, dG_dIk[segp] * dIk_b + dG_dIik[segp] * dIik_b)

    Kg = paths.gidx.shape[1]
    hb2 = hbar * hbar
    qv = q * VT
    use_a = (m_km > 0.0) & (a_km < b_km)
    use_b = (m_km > 0.0) & ~(a_km < b_km)
    rows = [np.repeat(ps, K), ps, np.repeat(np.arange(P), Kg),
            np.arange(P), np.arange(P), np.arange(P), np.arange(P)]
    cols = [paths.sidx.ravel(), st[ps], paths.gidx.ravel(),
            np.full(P, imin), st, st, np.full(P, imax)]
    vals = [(sc * paths.swts * g_raw[:, None]).ravel(), -sc * g_raw,
            (dG_dg[:, None] * paths.gwts).ravel(),
            np.where(use_a, dG_dkm2 * (-2.0 * mv_kg * qv) / hb2, 0.0),
            np.where(use_a, dG_dkm2 * (2.0 * mv_kg * qv) / hb2, 0.0),
            np.where(use_b, dG_dkm2 * (-2.0 * mc_kg * qv) / hb2, 0.0),
            np.where(use_b, dG_dkm2 * (2.0 * mc_kg * qv) / hb2, 0.0)]
    dG = coo_matrix((np.concatenate(vals),
                     (np.concatenate(rows), np.concatenate(cols))),
                    shape=(P, N)).tocsr()

    # electron deposit: (1 - t) on the crossing segment's first sample,
    # t on its second, each spread over that sample's stencil
    sa, sb = cseg, cseg + 1
    pr = np.arange(P)
    dep = coo_matrix((np.concatenate([((1.0 - t)[:, None] * paths.swts[sa]).ravel(),
                                      (t[:, None] * paths.swts[sb]).ravel()]),
                      (np.concatenate([np.repeat(pr, K), np.repeat(pr, K)]),
                       np.concatenate([paths.sidx[sa].ravel(),
                                       paths.sidx[sb].ravel()]))),
                     shape=(P, N)).tocsr()
    # d dep / d psi = (d weight / d t) * (d t / d psi)
    n_nodes = np.concatenate([paths.sidx[sa], paths.sidx[sb]], axis=1)
    n_coef = np.concatenate([-paths.swts[sa], paths.swts[sb]], axis=1)
    c_cols = np.concatenate([paths.sidx[sa], paths.sidx[sb], st[:, None]],
                            axis=1)
    c_vals = np.concatenate([dt_da[:, None] * sc * paths.swts[sa],
                             dt_db[:, None] * sc * paths.swts[sb],
                             (-sc * (dt_da + dt_db))[:, None]], axis=1)
    nn, nc = n_nodes.shape[1], c_cols.shape[1]
    ddep_p = np.repeat(pr, nn * nc)
    ddep_node = np.repeat(n_nodes, nc, axis=1).ravel()
    ddep_col = np.tile(c_cols, (1, nn)).ravel()
    ddep_val = (n_coef[:, :, None] * c_vals[:, None, :]).ravel()
    keep = ddep_val != 0.0
    return PathEval(G, dG, dep, ddep_p[keep], ddep_node[keep],
                    ddep_col[keep], ddep_val[keep], Ik, Iik, reached,
                    length, fmin, fmax)


# ---------------------------------------------------------------------
# M34-S3: field-line path tracing on structured 2D/3D tensor grids
# ---------------------------------------------------------------------
def build_structured(coords_cm, psi, VT, Eg_eV, contact_mask,
                     screen_Vcm=1.0e3, margin=1.5, max_steps=100000):
    """Trace nonlocal-BTBT tunnel paths on a structured 2D or 3D grid.

    Esseni et al. 2017 section 2.4: commercial TCAD's "dynamic path"
    takes the tunneling direction at each point from the gradient of the
    valence-band energy, i.e. the path follows a field line.  Electrons
    tunnel toward higher psi, so a path runs along +grad(psi) from its
    start node until the band has risen by margin*Eg (delta = 1.5), the
    domain boundary, or a contact.

    coords_cm    : one 1D coordinate array [cm] per ARRAY axis of `psi`
                   (C order: 2D (y, x), 3D (z, y, x)).
    psi          : potential grid in units of VT.
    contact_mask : bool grid, True at Dirichlet contact nodes.

    Construction, chosen so a device uniform across the transverse axes
    reduces EXACTLY to Device1D's paths:
      * the direction at a point is the multilinear interpolation of the
        nodal gradient (numpy.gradient, second-order central);
      * at an insulating (Neumann) boundary the outward component of the
        direction is dropped -- the continuum field has no normal
        component there, and round-off otherwise pushed boundary-row
        paths out of the domain;
      * each step runs straight to the next cell face or half the
        smallest cell width, whichever is nearer, and lands EXACTLY on
        any face it reaches, so within a step the multilinear psi is
        sampled on one cell only;
      * psi at a sample is the multilinear stencil of its cell -- linear
        in nodal psi, as the path engine requires;
      * the start gradient (eq 11's |dEv/dx|) is the difference quotient
        along the first segment, 1D's convention;
      * a path also stops after NO_PROGRESS_STEPS consecutive steps
        without a new maximum of psi along it (along a true field line
        psi rises monotonically; a plateau, a local maximum or a noise-
        flipped direction otherwise let a path wander to max_steps --
        measured: 100000 steps on a noisy field), or beyond a length of
        margin*Eg/(q*screen_Vcm), where the transmission is negligible;
      * a start is a non-contact node from which psi rises by Eg/VT
        somewhere in the domain and whose field ALONG THE PATH'S FIRST
        SEGMENT clears `screen_Vcm` -- in a transverse-uniform device
        that is exactly Device1D's forward-edge test; a path is cut
        before any sample that puts weight on a contact node, and kept
        only if its delta = 1 crossing lies inside.

    The array work (gradient, edge-field pre-screen, candidate list) is
    numpy; the per-path stepping runs either as `_trace_paths_py`, the
    reference, or as the compiled `pytcad._core.trace_paths`, which
    mirrors it operation for operation (M31 P4 convention; parity is
    gated with np.array_equal in tests/test_m34_s4_trace_parity.py).
    """
    psi = np.asarray(psi, dtype=float)
    d = psi.ndim
    if d not in (2, 3):
        raise ValueError(f"build_structured needs a 2D or 3D grid, got {d}D")
    coords = [np.ascontiguousarray(c, dtype=float) for c in coords_cm]
    shape = psi.shape
    if len(coords) != d or any(c.size != s for c, s in zip(coords, shape)):
        raise ValueError("coords_cm must match psi's shape axis by axis")
    contact_mask = np.asarray(contact_mask, dtype=bool)
    thr = Eg_eV / VT
    grads = np.gradient(psi, *coords)                  # 1/cm per axis
    # pre-screen on the largest one-sided edge field of each node (a
    # superset of the decisive first-segment test)
    emax_V = np.zeros(shape)
    for a in range(d):
        e = np.abs(np.diff(psi, axis=a)) * VT / np.expand_dims(
            np.diff(coords[a]), tuple(b for b in range(d) if b != a))
        lo = [slice(None)] * d
        hi = [slice(None)] * d
        lo[a] = slice(0, -1)
        hi[a] = slice(1, None)
        emax_V[tuple(lo)] = np.maximum(emax_V[tuple(lo)], e)
        emax_V[tuple(hi)] = np.maximum(emax_V[tuple(hi)], e)
    psi_max = float(psi.max())
    cand = np.nonzero(((emax_V >= screen_Vcm) & (psi_max - psi >= thr)
                       & ~contact_mask).ravel())[0].astype(np.int64)
    gflat = np.ascontiguousarray(np.stack([g.ravel() for g in grads]))
    hmin_all = min(float(np.diff(c).min()) for c in coords)
    args = (coords, np.ascontiguousarray(psi.ravel()), gflat, cand,
            np.ascontiguousarray(contact_mask.ravel()), shape, float(VT),
            float(Eg_eV), float(screen_Vcm), float(margin), int(max_steps),
            hmin_all)
    core = _accel.core if _accel.use_accel() else None
    if core is not None and hasattr(core, "trace_paths"):
        out = core.trace_paths(np.ascontiguousarray(np.concatenate(coords)),
                               np.asarray(shape, dtype=np.int64), *args[1:5],
                               *args[6:])
    else:
        out = _trace_paths_py(*args)
    starts, offset, sidx, swts, seg_len, gidx, gwts = out
    K = 2 ** d
    if len(starts) == 0:
        return empty_paths(K=K, Kg=K + 1)
    return TunnelPaths(np.asarray(starts, dtype=int),
                       np.asarray(offset, dtype=int),
                       np.asarray(sidx, dtype=int).reshape(-1, K),
                       np.asarray(swts, dtype=float).reshape(-1, K),
                       np.asarray(seg_len, dtype=float),
                       np.asarray(gidx, dtype=int).reshape(-1, K + 1),
                       np.asarray(gwts, dtype=float).reshape(-1, K + 1))


NO_PROGRESS_STEPS = 64


def _trace_paths_py(coords, psi_flat, gflat, cand, contact_flat, shape, VT,
                    Eg_eV, screen_Vcm, margin, max_steps, hmin_all):
    """Reference per-path stepping loop of build_structured.

    Pure-Python scalar arithmetic in a FIXED operation order -- sequential
    sums rather than np.dot (whose BLAS summation order is not
    guaranteed), bisect for searchsorted, explicit products for the
    multilinear weights -- so the compiled trace_paths can reproduce it
    bit for bit.  Returns flat lists: starts, offset, sidx, swts,
    seg_len, gidx, gwts.
    """
    d = len(shape)
    K = 2 ** d
    cl = [list(map(float, c)) for c in coords]
    n_ax = [len(c) for c in cl]
    strides = [1] * d
    for a in range(d - 2, -1, -1):
        strides[a] = strides[a + 1] * shape[a + 1]
    corners = [[(c >> (d - 1 - a)) & 1 for a in range(d)] for c in range(K)]
    psi_l = psi_flat.tolist()
    g_l = [row.tolist() for row in gflat]
    contact = contact_flat.tolist()

    def cell(P, dirv):
        idx = [0] * d
        t = [0.0] * d
        for a in range(d):
            c = cl[a]
            k = bisect.bisect_right(c, P[a]) - 1
            if dirv is not None and k > 0 and P[a] == c[k] and dirv[a] < 0.0:
                k -= 1
            k = min(max(k, 0), n_ax[a] - 2)
            idx[a] = k
            v = (P[a] - c[k]) / (c[k + 1] - c[k])
            t[a] = min(max(v, 0.0), 1.0)
        return idx, t

    def stencil(idx, t):
        nodes = [0] * K
        w = [0.0] * K
        for ci in range(K):
            bits = corners[ci]
            flat = 0
            wi = 1.0
            for a in range(d):
                flat += (idx[a] + bits[a]) * strides[a]
                wi *= t[a] if bits[a] else 1.0 - t[a]
            nodes[ci] = flat
            w[ci] = wi
        return nodes, w

    def interp(nodes, w, vals):
        acc = 0.0
        for ci in range(K):
            acc += w[ci] * vals[nodes[ci]]
        return acc

    starts, offset, sidx, swts, seg_len, gidx, gwts = [], [0], [], [], [], [], []
    for s in cand.tolist():
        m = []
        rem = s
        for a in range(d):
            m.append(rem // strides[a])
            rem -= m[a] * strides[a]
        P = [cl[a][m[a]] for a in range(d)]
        psi_s = psi_l[s]
        pn = [[s] * K]
        pw = [[1.0] + [0.0] * (K - 1)]
        pl = []
        reached = False
        best = psi_s
        stall = 0
        length = 0.0
        len_cap = margin * Eg_eV / screen_Vcm          # cm
        for _step in range(max_steps):
            idx, t = cell(P, None)
            nodes, w = stencil(idx, t)
            g = [interp(nodes, w, g_l[a]) for a in range(d)]
            acc = 0.0
            for a in range(d):
                acc += g[a] * g[a]
            gn = math.sqrt(acc)
            if gn == 0.0:
                break
            dirv = [g[a] / gn for a in range(d)]
            for a in range(d):
                if ((P[a] <= cl[a][0] and dirv[a] < 0.0)
                        or (P[a] >= cl[a][-1] and dirv[a] > 0.0)):
                    dirv[a] = 0.0
            acc = 0.0
            for a in range(d):
                acc += dirv[a] * dirv[a]
            nrm = math.sqrt(acc)
            if nrm == 0.0:
                break
            dirv = [dirv[a] / nrm for a in range(d)]
            idx, t = cell(P, dirv)
            ds = cl[0][idx[0] + 1] - cl[0][idx[0]]
            for a in range(1, d):
                ds = min(ds, cl[a][idx[a] + 1] - cl[a][idx[a]])
            ds = 0.5 * ds
            lim_axis, lim_face = -1, 0.0
            for a in range(d):
                if dirv[a] > 0.0:
                    face = cl[a][idx[a] + 1]
                elif dirv[a] < 0.0:
                    face = cl[a][idx[a]]
                else:
                    continue
                da = (face - P[a]) / dirv[a]
                if da < ds:
                    ds, lim_axis, lim_face = da, a, face
            if not ds > 1e-12 * hmin_all:
                break
            Pn = [P[a] + ds * dirv[a] for a in range(d)]
            if lim_axis >= 0:
                Pn[lim_axis] = lim_face
            for a in range(d):
                if dirv[a] > 0.0:
                    face = cl[a][idx[a] + 1]
                elif dirv[a] < 0.0:
                    face = cl[a][idx[a]]
                else:
                    continue
                w_cell = cl[a][idx[a] + 1] - cl[a][idx[a]]
                if abs(Pn[a] - face) <= 1e-9 * w_cell:
                    Pn[a] = face
            if any(Pn[a] < cl[a][0] or Pn[a] > cl[a][-1] for a in range(d)):
                break
            idx_n, t_n = cell(Pn, dirv)
            nodes, w = stencil(idx_n, t_n)
            if any(w[ci] > 0.0 and contact[nodes[ci]] for ci in range(K)):
                break
            pn.append(nodes)
            pw.append(w)
            pl.append(ds * 1e-2)                      # cm -> m
            length += ds
            psi_here = interp(nodes, w, psi_l)
            if len(pn) == 2 and VT * (psi_here - psi_s) / ds < screen_Vcm:
                break                                 # first-segment screen
            raw = VT * (psi_here - psi_s) / Eg_eV
            if raw >= 1.0:
                reached = True
            if raw >= margin:
                break
            if psi_here > best:
                best = psi_here
                stall = 0
            else:
                stall += 1
                if stall >= NO_PROGRESS_STEPS:
                    break
            if length > len_cap:
                break
            P = Pn
        if not reached or len(pn) < 2:
            continue
        L0 = pl[0]
        starts.append(s)
        for nodes, w in zip(pn, pw):
            sidx.extend(nodes)
            swts.extend(w)
        seg_len.extend(pl)
        seg_len.append(0.0)
        offset.append(offset[-1] + len(pn))
        gidx.append(s)
        gidx.extend(pn[1])
        gwts.append(-1.0 / L0)
        gwts.extend(wi / L0 for wi in pw[1])
    return starts, offset, sidx, swts, seg_len, gidx, gwts
