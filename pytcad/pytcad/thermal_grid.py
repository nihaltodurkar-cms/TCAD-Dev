"""M43 phase 2: dimension-generic (2D or 3D) structured-grid core for
steady-state lattice self-heating, shared by thermal2d.py and
thermal3d.py -- mirrors ii_grid.py/btbt_grid.py's "one kernel for
Device2D and Device3D" pattern (M34-S6) rather than hand-duplicating
the same per-axis FV stencil a third time. thermal2d.py's original
_residual_jacobian_2d (gated by tests/test_m43_thermal2d.py before this
refactor) is now a thin wrapper around _residual_jacobian_grid below;
re-running its exact same gates after the refactor is this module's own
correctness check (see M43-SELFHEATING-2D3D-PLAN.md).

M43 phase 3: `_residual_jacobian_grid_py` below (renamed from the
former `_residual_jacobian_grid`) is now the ORACLE for an optional
compiled kernel, `_core.thermal_grid_residual_jacobian`
(core/src/thermal/grid.cpp) -- same M31 P4 discipline as
process.diffuse_numeric: the Python body never moves, `_accel.use_accel()`
decides which path runs, and `tests/test_m43_thermal_grid_accel_parity.py`
diffs the two with `np.array_equal`. The kernel is pure arithmetic (no
transcendentals): material.kappa_th(Tavg)'s power law is evaluated ONCE
in `_residual_jacobian_grid_accel` below (the only place either path
calls it), same as `np.log(n)` staying in Python for the P4 indicator
kernels -- see core/include/tcad/thermal/kernels.hpp's own docstring.
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

from . import _accel
from .mesh2d import control_volume_widths
from .thermal import ThermalOptions  # noqa: F401 (re-exported)

_BC_KIND = {"isothermal": 0, "resistance": 1, "adiabatic": 2}


def _residual_jacobian_grid(coords, T, H, material, T_ambient, bcs):
    """Dispatcher: the compiled kernel when available and enabled,
    else the pure-Python oracle below. Same arguments either way."""
    if _accel.use_accel():
        return _residual_jacobian_grid_accel(coords, T, H, material, T_ambient, bcs)
    return _residual_jacobian_grid_py(coords, T, H, material, T_ambient, bcs)


def _residual_jacobian_grid_accel(coords, T, H, material, T_ambient, bcs):
    """`_core.thermal_grid_residual_jacobian` wrapper. Computes the one
    transcendental (kappa_th's power law) here, in Python, then hands
    the per-axis edge kappa/derivative arrays down as plain data --
    the kernel itself is pure arithmetic. Per-axis arrays are
    concatenated (not a Python list of ndarrays -- nanobind has no
    direct binding for that; mirrors nonlocal_bindings.cpp's
    trace_paths, the existing D=2-or-3-generic precedent)."""
    D = T.ndim
    shape = T.shape
    hs = [np.diff(c) for c in coords]
    dVs = [control_volume_widths(h) for h in hs]

    ke_parts, dke_parts = [], []
    for axis in range(D):
        lo = [slice(None)] * D; hi = [slice(None)] * D
        lo[axis] = slice(0, -1); hi[axis] = slice(1, None)
        Tavg = 0.5 * (T[tuple(lo)] + T[tuple(hi)])
        ke = material.kappa_th(Tavg)
        dke = 0.5 * ke * (-1.33 / Tavg)
        ke_parts.append(np.ascontiguousarray(ke, dtype=np.float64).ravel())
        dke_parts.append(np.ascontiguousarray(dke, dtype=np.float64).ravel())

    bc_kind = np.array([_BC_KIND[b.kind] for axis in bcs for b in axis], dtype=np.int64)
    bc_rth = np.array(
        [(b.R_th_area if b.kind == "resistance" else 0.0) for axis in bcs for b in axis],
        dtype=np.float64)

    F_flat, rows, cols, vals = _accel.core.thermal_grid_residual_jacobian(
        np.asarray(shape, dtype=np.int64),
        _accel.as_field(np.ascontiguousarray(T, dtype=np.float64).ravel()),
        _accel.as_field(np.ascontiguousarray(H, dtype=np.float64).ravel()),
        float(T_ambient),
        _accel.as_field(np.concatenate(dVs)),
        _accel.as_field(np.concatenate(hs)),
        _accel.as_field(np.concatenate(ke_parts)),
        _accel.as_field(np.concatenate(dke_parts)),
        bc_kind, bc_rth)

    F = np.asarray(F_flat).reshape(shape)
    J = sp.csr_matrix((vals, (rows, cols)), shape=(T.size, T.size))
    return F, J


def _residual_jacobian_grid_py(coords, T, H, material, T_ambient, bcs):
    """Residual/Jacobian of the steady ND (D=2 or 3) heat equation
    -div(kappa_th(T) grad T) = H on a tensor-product mesh. Fully
    vectorized -- no per-node Python loop (thermal.py's own 1D
    assembly has the one scalar loop ARCHITECTURE.md flags as pairing
    with M31 P4; this generalization does not repeat it in any
    dimension).

    coords : list of D physical 1D axis arrays [cm], ordered to match
             T's own axes (T.shape[a] == len(coords[a])).
    T, H   : ND arrays, shape matching coords' lengths.
    bcs    : list of D (bc_lo, bc_hi) ThermalBC pairs, same axis order.

    Box-integration convention: the flux through axis `a`'s edges is
    weighted by the CROSS-SECTION -- the product of every OTHER axis's
    control-volume width -- exactly the dVy-for-x-flux/dVx-for-y-flux
    (2D) or dVy*dVz-for-x-flux/etc (3D) convention device2d.py's own
    Poisson/continuity residual and device3d.py's own F_n assembly
    already use (device2d.py:970-983, device3d.py:993-998) -- a dual of
    an already-gated operation in both dimensionalities, not a fresh
    derivation.
    """
    D = T.ndim
    shape = T.shape
    hs = [np.diff(c) for c in coords]
    dVs = [control_volume_widths(h) for h in hs]

    def axis_weight(axis, include_axis):
        """Product of dV along every axis except `axis` (if
        include_axis is False) or every axis (if True), each
        reshaped to broadcast against a full/edge ND array."""
        w = np.array(1.0)
        for a in range(D):
            if a == axis and not include_axis:
                continue
            bshape = [1] * D
            bshape[a] = shape[a]
            w = w * dVs[a].reshape(bshape)
        return w

    dV = axis_weight(None, include_axis=True)
    F = H * dV
    idx = np.arange(T.size).reshape(shape)
    rows, cols, vals = [], [], []

    def add(r, c, v):
        r = np.broadcast_to(r, v.shape).ravel()
        c = np.broadcast_to(c, v.shape).ravel()
        v = v.ravel()
        m = v != 0.0
        rows.extend(r[m]); cols.extend(c[m]); vals.extend(v[m])

    def _clear_row(row_ids):
        row_set = set(row_ids.tolist())
        keep = [i for i, r in enumerate(rows) if r not in row_set]
        rows[:] = [rows[i] for i in keep]
        cols[:] = [cols[i] for i in keep]
        vals[:] = [vals[i] for i in keep]

    # ---- interior flux contributions, one axis at a time ----
    for axis in range(D):
        lo = [slice(None)] * D; hi = [slice(None)] * D
        lo[axis] = slice(0, -1); hi[axis] = slice(1, None)
        lo, hi = tuple(lo), tuple(hi)
        h_shape = [1] * D; h_shape[axis] = shape[axis] - 1
        h_a = hs[axis].reshape(h_shape)

        Tavg = 0.5 * (T[lo] + T[hi])
        ke = material.kappa_th(Tavg)
        dke = 0.5 * ke * (-1.33 / Tavg)          # d(kappa)/dT, per endpoint

        w = axis_weight(axis, include_axis=False)  # size 1 along `axis`
        dT = T[hi] - T[lo]
        Fedge = w * ke * dT / h_a
        div = np.zeros(shape)
        div[lo] += Fedge
        div[hi] -= Fedge
        F = F + div

        # F[kL] += w*Fedge, F[kR] -= w*Fedge  =>
        # dF[kL]/dT[kL] = +w*dFedge/dT_lo, dF[kR]/dT[kR] = -w*dFedge/dT_hi
        # (matches device2d.py's own scatter() sign convention for the
        # identical construction -- M43's original 2D FD-Jacobian gate
        # caught this exact sign backwards on the first attempt).
        dF_lo = np.broadcast_to(w * (dke * dT / h_a - ke / h_a), T[lo].shape)
        dF_hi = np.broadcast_to(w * (dke * dT / h_a + ke / h_a), T[lo].shape)
        kL, kR = idx[lo], idx[hi]
        add(kL, kL, dF_lo); add(kL, kR, dF_hi)
        add(kR, kL, -dF_lo); add(kR, kR, -dF_hi)

    # ---- boundaries: resistance is ADDITIVE (the interior formula
    # above already gives the correct one-sided residual at every
    # boundary/corner node -- "adiabatic" needs no code at all, exactly
    # as in the 2D case); isothermal is a full OVERRIDE, applied last
    # so it always wins at a corner/edge shared with a Robin boundary.
    boundaries = []
    for axis in range(D):
        for side, i in (("lo", 0), ("hi", shape[axis] - 1)):
            bslice = [slice(None)] * D
            bslice[axis] = i
            bc = bcs[axis][0] if side == "lo" else bcs[axis][1]
            cross = np.squeeze(axis_weight(axis, include_axis=False), axis=axis)
            boundaries.append((bc, tuple(bslice), cross))

    for bc, bslice, cross in boundaries:
        if bc.kind != "resistance":
            continue
        bnode = idx[bslice]
        Tb = T[bslice]
        inv_Rth = 1.0 / bc.R_th_area
        cross_b = np.broadcast_to(cross, Tb.shape)
        F[bslice] = F[bslice] - (Tb - T_ambient) * inv_Rth * cross_b
        add(bnode, bnode, -inv_Rth * cross_b)

    for bc, bslice, _ in boundaries:
        if bc.kind != "isothermal":
            continue
        bnode = idx[bslice]
        Tb = T[bslice]
        F[bslice] = Tb - T_ambient
        _clear_row(bnode.ravel())
        add(bnode, bnode, np.ones_like(Tb))

    J = sp.csr_matrix((vals, (rows, cols)), shape=(T.size, T.size))
    return F, J


def solve_lattice_temperature_grid(coords, H, material, T_ambient, bcs,
                                    opts=None):
    """Steady-state ND (D=2 or 3) lattice temperature [K] on a
    tensor-product mesh under heat-source density H [W/cm^3] (shape
    matching coords' lengths). One ThermalBC pair per axis in `bcs`.
    Vectorized Newton solve, kappa_th(T) nonlinear as in the 1D/2D
    modules."""
    opts = opts or ThermalOptions()
    H = np.asarray(H, dtype=float)
    shape = H.shape
    T = np.full(shape, float(T_ambient))

    for _ in range(opts.max_iter):
        F, J = _residual_jacobian_grid(coords, T, H, material, T_ambient, bcs)
        d = spsolve(J.tocsc(), -F.ravel()).reshape(shape)
        d = np.clip(d, -opts.max_dT, opts.max_dT)
        T = T + d
        if np.abs(d).max() < opts.tol:
            break
    else:
        raise RuntimeError(
            "solve_lattice_temperature_grid did not converge "
            f"(|dT| still {np.abs(d).max():.3e} K at the iteration cap)")
    return T
