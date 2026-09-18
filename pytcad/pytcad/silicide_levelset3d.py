"""M35-S5 (full-scope pass): silicidation in 3D, a direct port of
`silicide_levelset.py`'s per-line linear-parabolic moving-boundary
solver to `levelset3d.LevelSet3D`. See that module's own docstring for
the full physics/honesty-clause writeup (no built-in named silicide --
same literature dead end, unchanged in 3D). The one generalization:
"per x-column, sum along y" becomes "per (x,z) line, sum along y"
(`product_mask.sum(axis=1)` instead of `.sum(axis=0)`), broadcasting
the resulting `(Nx,Nz)` rate field back over the y-axis.
"""
import numpy as np
from scipy.ndimage import distance_transform_edt

from .process2d import _UM_TO_CM, _CM_TO_UM
from .levelset3d import advect_upwind3d, cfl_dt3d, _project_from_owner3d


def silicide_levelset3d(ls, B_um2_hr, A_um, t_hours,
                         si_consumption_frac=0.5, metal_consumption_frac=0.5,
                         metal="metal", silicon="silicon", product="silicide",
                         steps=20):
    if abs((si_consumption_frac + metal_consumption_frac) - 1.0) > 1e-9:
        raise ValueError(
            f"si_consumption_frac + metal_consumption_frac must equal 1.0, "
            f"got {si_consumption_frac} + {metal_consumption_frac} = "
            f"{si_consumption_frac + metal_consumption_frac}"
        )
    for name in (metal, silicon, product):
        if name not in ls.materials:
            raise ValueError(f"silicide_levelset3d requires {name!r} in ls.materials")

    idx_si = ls.materials.index(silicon)
    idx_metal = ls.materials.index(metal)
    idx_product = ls.materials.index(product)
    static_names = [m for m in ls.materials if m not in (silicon, metal, product)]
    static_idx = [ls.materials.index(m) for m in static_names]
    static_phi = [ls.phi[m] for m in static_names]

    phi_si = ls.phi[silicon].copy()
    phi_metal = ls.phi[metal].copy()
    dx, dy, dz = ls.dx, ls.dy, ls.dz
    dy_um = dy * _CM_TO_UM

    def ownership():
        stack = np.stack([phi_si, phi_metal] + static_phi, axis=0)
        idxs = np.array([idx_si, idx_metal] + static_idx)
        winner = np.argmin(stack, axis=0)
        best = np.min(stack, axis=0)
        owner = idxs[winner]
        return np.where(best < 0, owner, idx_product)

    def reinit_single(phi):
        inside = phi < 0
        if not np.any(inside) or np.all(inside):
            return phi
        d_in = distance_transform_edt(inside, sampling=(dx, dy, dz))
        d_out = distance_transform_edt(~inside, sampling=(dx, dy, dz))
        return np.where(inside, -d_in, d_out)

    dt = t_hours / steps
    reinit_thresh = min(dx, dy, dz)
    accum_si = 0.0
    accum_metal = 0.0
    cfl = 0.4

    for _ in range(steps):
        mat_idx = ownership()
        product_mask = mat_idx == idx_product
        x_local_um = product_mask.sum(axis=1) * dy_um       # (Nx,Nz)
        dxdt_um_per_hr = B_um2_hr / (2.0 * x_local_um + A_um)   # (Nx,Nz)

        V_si_line = si_consumption_frac * dxdt_um_per_hr * _UM_TO_CM
        V_metal_line = metal_consumption_frac * dxdt_um_per_hr * _UM_TO_CM
        V_si = np.broadcast_to(V_si_line[:, None, :], phi_si.shape)
        V_metal = np.broadcast_to(V_metal_line[:, None, :], phi_metal.shape)

        t = 0.0
        while t < dt - 1e-15:
            dt_sub = cfl_dt3d(V_si, dx, dy, dz, cfl)
            dt_sub = min(dt_sub, dt - t)
            phi_si = advect_upwind3d(phi_si, -V_si, dx, dy, dz, dt_sub)
            t += dt_sub
        accum_si += dt * float(np.max(V_si))
        if accum_si >= reinit_thresh:
            phi_si = reinit_single(phi_si)
            accum_si = 0.0

        t = 0.0
        while t < dt - 1e-15:
            dt_sub = cfl_dt3d(V_metal, dx, dy, dz, cfl)
            dt_sub = min(dt_sub, dt - t)
            phi_metal = advect_upwind3d(phi_metal, -V_metal, dx, dy, dz, dt_sub)
            t += dt_sub
        accum_metal += dt * float(np.max(V_metal))
        if accum_metal >= reinit_thresh:
            phi_metal = reinit_single(phi_metal)
            accum_metal = 0.0

    final_owner = ownership()
    final = ls.copy()
    final.phi[silicon] = phi_si
    final.phi[metal] = phi_metal
    return _project_from_owner3d(final, final_owner)
