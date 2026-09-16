"""M43 phase 2: dimension-generic (2D or 3D) structured-grid core for
steady-state lattice self-heating, shared by thermal2d.py and
thermal3d.py -- mirrors ii_grid.py/btbt_grid.py's "one kernel for
Device2D and Device3D" pattern (M34-S6) rather than hand-duplicating
the same per-axis FV stencil a third time. thermal2d.py's original
_residual_jacobian_2d (gated by tests/test_m43_thermal2d.py before this
refactor) is now a thin wrapper around _residual_jacobian_grid below;
re-running its exact same gates after the refactor is this module's own
correctness check (see M43-SELFHEATING-2D3D-PLAN.md).

M43 phase 4 (2026-09-16): the pure-Python oracle
(`_residual_jacobian_grid_py`) was REMOVED at the user's explicit
request -- this module now requires the compiled kernel,
`_core.thermal_grid_residual_jacobian` (core/src/thermal/grid.cpp).
`_accel.require_accel()` raises with build instructions if `_core`
isn't importable. See CLAUDE.md's "What is compiled so far" section
for why the pure-Python fallback existed at all and what changed.
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

from . import _accel
from .mesh2d import control_volume_widths
from .thermal import ThermalOptions  # noqa: F401 (re-exported)

_BC_KIND = {"isothermal": 0, "resistance": 1, "adiabatic": 2}


def _residual_jacobian_grid(coords, T, H, material, T_ambient, bcs):
    """`_core.thermal_grid_residual_jacobian` wrapper. Computes the one
    transcendental (kappa_th's power law) here, in Python, then hands
    the per-axis edge kappa/derivative arrays down as plain data --
    the kernel itself is pure arithmetic. Per-axis arrays are
    concatenated (not a Python list of ndarrays -- nanobind has no
    direct binding for that; mirrors nonlocal_bindings.cpp's
    trace_paths, the existing D=2-or-3-generic precedent)."""
    _accel.require_accel()
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
