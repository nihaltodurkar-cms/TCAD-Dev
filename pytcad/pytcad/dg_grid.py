"""M42-S3: dimension-generic (2D or 3D) Lambda_n/Lambda_p flux-divergence
kernel for the density-gradient (Ancona-Stafford) equilibrium solve,
shared by device2d.py and device3d.py -- mirrors ii_grid.py/btbt_grid.py's
"one kernel for Device2D and Device3D" pattern (M34-S6) rather than
hand-duplicating the box-integration/harmonic-mean/gate-ghosting Lambda
stencil a third time.

Scope note: this factors ONLY the Lambda_n/Lambda_p rows -- the newest
and most error-prone part of M42-S1/S2's own assembly (device2d.py's
_dg_residual_jacobian_eq docstring). The classical Poisson row
(dielectric et_x/et_y/et_z arrays, the GateBC Robin weight, the
LD-scaled mesh) stays written per-device, exactly as
_residual_jacobian_poisson already is in both device2d.py and
device3d.py without ever being merged into a shared module either --
this is the SAME precedent this repo already uses, not a scope cut
invented for this port.

Reduces EXACTLY to Device1D's own non-uniform three-point second
derivative when called with a single axis over a 1-row line of nodes
(Device2D's own S1-G3 gate, re-verified bit-identical after this
extraction -- not re-derived).

Compiled path (added same day, on request): `_dg_lambda_rows_py` below
is now the pure-Python ORACLE, kept for the accel-parity gate
(tests/test_m42_s3_density_gradient_3d.py); `dg_lambda_rows`, the
public entry point every device calls, dispatches to
`_accel.core.dg_grid_lambda_rows` (core/src/dg/grid.cpp) when `_core`
is importable and falls back to the oracle otherwise -- this kernel is
OPTIONAL, unlike the P2/P4/M34-S4/M43 kernels CLAUDE.md's "C++ engine"
section says are now required; nothing about M42 has been declared
required, so the M31-era graceful-fallback default still applies here.
The one transcendental (sqrt(n)/sqrt(p), i.e. `gn`/`gp`) is computed
ONCE in Python either way and crosses as plain data -- the compiled
kernel is pure arithmetic, matching every other accelerated kernel's
own rule.
"""
import numpy as np

from . import _accel
from .dg import _dg_prefactor


def _hmean(lo, hi):
    # gamma=0 (the first continuation stage) makes pref exactly zero
    # everywhere; guard the 0/0 a plain harmonic mean would hit there --
    # no coupling at zero prefactor is the physically correct limit, not
    # an indeterminate form. Same guard as device2d.py's own hmean2d.
    s = lo + hi
    return np.where(s > 0.0, 2.0 * lo * hi / np.where(s > 0.0, s, 1.0), 0.0)


def dg_lambda_rows(N, axes, n, p, Lam_n, Lam_p, m_n, m_p, gamma, gate_mask,
                    ip, iln, ilp, VT):
    """Public entry point: dispatches to the compiled kernel when
    available, the pure-Python oracle (_dg_lambda_rows_py) otherwise.
    See this module's own docstring; parameters match
    _dg_lambda_rows_py exactly."""
    if _accel.HAVE_ACCEL:
        return _dg_lambda_rows_accel(N, axes, n, p, Lam_n, Lam_p, m_n, m_p,
                                     gamma, gate_mask, ip, iln, ilp, VT)
    return _dg_lambda_rows_py(N, axes, n, p, Lam_n, Lam_p, m_n, m_p, gamma,
                              gate_mask, ip, iln, ilp, VT)


def _dg_lambda_rows_accel(N, axes, n, p, Lam_n, Lam_p, m_n, m_p, gamma,
                          gate_mask, ip, iln, ilp, VT):
    """`_accel.core.dg_grid_lambda_rows` wrapper. `ip`/`iln`/`ilp` are
    not passed through -- the compiled kernel hardcodes the SAME fixed
    interleave convention (3k, 3k+1, 3k+2) every caller's own
    ip()/iln()/ilp() already implements; unused here beyond that
    implicit contract (asserted nowhere -- both devices define them
    identically and this is a private module, not a public API a third
    caller could violate)."""
    pref_n = (_dg_prefactor(m_n, gamma) * 1e4).reshape(-1)
    pref_p = (_dg_prefactor(m_p, gamma) * 1e4).reshape(-1)
    gn = np.sqrt(np.maximum(n.reshape(-1), 1e-300))
    gp = np.sqrt(np.maximum(p.reshape(-1), 1e-300))
    n_edges = np.array([ax["kL"].shape[0] for ax in axes], dtype=np.int64)
    kL_concat = np.concatenate([ax["kL"] for ax in axes]).astype(np.int64)
    kR_concat = np.concatenate([ax["kR"] for ax in axes]).astype(np.int64)
    h_concat = np.concatenate([ax["h_phys"] for ax in axes]).astype(np.float64)
    dV_concat = np.concatenate([ax["dV_phys"] for ax in axes]).astype(np.float64)
    gate_mask_u8 = np.ascontiguousarray(gate_mask, dtype=np.uint8)

    Fn, Fp, rows, cols, vals = _accel.core.dg_grid_lambda_rows(
        int(N), n_edges, kL_concat, kR_concat, h_concat, dV_concat,
        np.ascontiguousarray(gn), np.ascontiguousarray(gp),
        np.ascontiguousarray(Lam_n.reshape(-1)),
        np.ascontiguousarray(Lam_p.reshape(-1)),
        np.ascontiguousarray(pref_n), np.ascontiguousarray(pref_p),
        gate_mask_u8, float(VT))
    return (np.asarray(Fn), np.asarray(Fp),
            [np.asarray(rows)], [np.asarray(cols)], [np.asarray(vals)])


def _dg_lambda_rows_py(N, axes, n, p, Lam_n, Lam_p, m_n, m_p, gamma, gate_mask,
                       ip, iln, ilp, VT):
    """Pure-Python oracle. Lambda_n/Lambda_p box-integration
    flux-divergence rows and their Jacobian, generic over an arbitrary
    list of grid axes (one entry for Device2D's x/y, three for
    Device3D's x/y/z).

    Parameters
    ----------
    N        : total node count.
    axes     : list of dicts, one per mesh axis, each with:
                 kL, kR   -- flat node-index pairs for this axis's edges
                             (same convention as each device's own
                             _edge_pairs_x/_y/_z helpers)
                 h_phys   -- PHYSICAL (unscaled) edge length, one value
                             per edge, matching this axis's kL/kR order
                 dV_phys  -- PHYSICAL control-volume width along THIS
                             axis, one value per NODE (flat, length N)
                             -- e.g. Device2D's dVx_phys broadcast to
                             (Ny, Nx) then raveled for the x axis.
    n, p     : flat (N,) slaved densities (scaled units, as computed by
               the caller's own Poisson-row assembly).
    Lam_n, Lam_p : flat (N,) current Lambda iterates [V].
    m_n, m_p : flat (N,) per-node effective masses (materials.py's
               m_n_star/m_p_star, already gathered by the caller).
    gamma    : continuation strength (0..dg_gamma target).
    gate_mask: bool (N,), True at any GateBC node on ANY axis -- the
               infinite-barrier ghosting applies to the whole node, not
               one face, matching device2d.py's own M42-S2 convention.
    ip, iln, ilp : index functions into the interleaved 3N unknown
               vector (psi_k, Lambda_n_k, Lambda_p_k per node k),
               exactly as each device's own _dg_residual_jacobian_eq
               already defines them.

    Returns
    -------
    F_lam_n, F_lam_p : flat (N,) residuals (Lam*g + laplacian(g) term).
    rows, cols, vals : COO Jacobian triples into the 3N system (NOT yet
               concatenated with the caller's own Poisson-row triples).
    """
    pref_n = (_dg_prefactor(m_n, gamma) * 1e4).reshape(-1)
    pref_p = (_dg_prefactor(m_p, gamma) * 1e4).reshape(-1)
    Lam_n = Lam_n.reshape(-1)
    Lam_p = Lam_p.reshape(-1)
    n = n.reshape(-1)
    p = p.reshape(-1)
    gn = np.sqrt(np.maximum(n, 1e-300))
    gp = np.sqrt(np.maximum(p, 1e-300))
    kdiag = np.arange(N)

    F_lam = {"n": np.zeros(N), "p": np.zeros(N)}
    rows, cols, vals = [], [], []

    for tag, g, Lam, pref, sign, idx in (
        ("n", gn, Lam_n, pref_n, +1.0, iln),
        ("p", gp, Lam_p, pref_p, -1.0, ilp),
    ):
        # M42-S2's ghosting: a gate node's g is forced to 0 in the
        # curvature stencil (both the flux F and its Jacobian) -- the
        # infinite-barrier limit matching this repo's own
        # Schrodinger-Poisson reference solver's hard_wall_left=True
        # convention. The node's OWN Lambda row is pinned by the
        # caller regardless of what this computes for it, so ghosting
        # is applied unconditionally (harmless: that row is discarded).
        g_eff = np.where(gate_mask, 0.0, g)

        def dg_dpsi(gv, sign=sign): return sign * gv / 2.0
        def dg_dlam(gv): return -gv / (2.0 * VT)

        lap = np.zeros(N)
        for ax in axes:
            kL, kR = ax["kL"], ax["kR"]
            pref_e = _hmean(pref[kL], pref[kR])
            G = pref_e * (g_eff[kR] - g_eff[kL]) / ax["h_phys"]
            np.add.at(lap, kL, G / ax["dV_phys"][kL])
            np.add.at(lap, kR, -G / ax["dV_phys"][kR])

            wx_recv_L = pref_e / (ax["h_phys"] * ax["dV_phys"][kL])
            wx_recv_R = pref_e / (ax["h_phys"] * ax["dV_phys"][kR])
            rows.append(idx(kL)); cols.append(ip(kR)); vals.append(wx_recv_L * dg_dpsi(g_eff[kR]))
            rows.append(idx(kL)); cols.append(idx(kR)); vals.append(wx_recv_L * dg_dlam(g_eff[kR]))
            rows.append(idx(kL)); cols.append(ip(kL)); vals.append(-wx_recv_L * dg_dpsi(g_eff[kL]))
            rows.append(idx(kL)); cols.append(idx(kL)); vals.append(-wx_recv_L * dg_dlam(g_eff[kL]))
            rows.append(idx(kR)); cols.append(ip(kL)); vals.append(wx_recv_R * dg_dpsi(g_eff[kL]))
            rows.append(idx(kR)); cols.append(idx(kL)); vals.append(wx_recv_R * dg_dlam(g_eff[kL]))
            rows.append(idx(kR)); cols.append(ip(kR)); vals.append(-wx_recv_R * dg_dpsi(g_eff[kR]))
            rows.append(idx(kR)); cols.append(idx(kR)); vals.append(-wx_recv_R * dg_dlam(g_eff[kR]))

        F_lam[tag] = Lam * g + lap

        # diagonal "Lam*g" Jacobian term: uses the GHOSTED g_eff, not
        # the real g the residual above used -- a direct port of
        # device2d.py's own documented asymmetry (its docstring: "The
        # diagonal 'Lam*g' Jacobian entries ... pick up the ghosted
        # value at a gate node's OWN row, but that row is entirely
        # overwritten by the Lambda pin ..., so it is discarded, not
        # wrong"). Kept exactly, for bit-identity with the pre-
        # extraction code, not re-derived.
        rows.append(idx(kdiag)); cols.append(ip(kdiag)); vals.append(Lam * dg_dpsi(g_eff))
        rows.append(idx(kdiag)); cols.append(idx(kdiag)); vals.append(g_eff + Lam * dg_dlam(g_eff))

    return F_lam["n"], F_lam["p"], rows, cols, vals
