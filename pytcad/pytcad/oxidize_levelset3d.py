"""M35-S5 (full-scope pass): oxidation as a real moving-boundary
problem in 3D, a direct port of `oxidize_levelset.py`'s already-
debugged architecture to `levelset3d.LevelSet3D`. See that module's
own docstring for the full physics/numerics reasoning (parameter
degeneracy resolution, growth-rate 0.44/0.56 split, and -- most
importantly -- WHY this tracks persistent `phi_silicon`/`phi_ambient`
arrays across the whole call instead of chaining `advance_front3d`);
none of that reasoning changes in 3D, so it is not repeated here.

The one real generalization: `_solve_oxidant_diffusion3d`'s finite-
volume flux balance uses a 6-neighbor stencil (+/-x, +/-y, +/-z)
instead of 2D's 4-neighbor one, with each face's area being the
product of the two spacings perpendicular to that face (2D's "face
length" times the extra axis's own spacing) -- otherwise the exact
same Robin (ambient)/reactive (silicon)/Neumann (any other material)
face rules.

HONEST LIMITS: identical to `oxidize_levelset.py`'s own list, in 3D.
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve
from scipy.ndimage import distance_transform_edt, binary_dilation

from . import process
from .ted import segregation_partition
from .process2d import _UM_TO_CM, _CM_TO_UM
from .levelset3d import advect_upwind3d, cfl_dt3d, deposit_conformal3d, _project_from_owner3d


def _effective_params(T_C, ambient):
    BA, B = process.deal_grove_coefficients(T_C, ambient)
    A = B / BA
    D = 1.0
    ks = h = 4.0 / A
    Cgas = B / 2.0
    return D, ks, h, Cgas


def _xi_um(ambient):
    return process._DEAL_GROVE[ambient]["xi"]


def _seed_thin_oxide3d(ls, ambient, rate_um_hr=1.0):
    xi = _xi_um(ambient)
    if xi <= 0:
        return ls
    idx_si = ls.materials.index("silicon")
    idx_amb = ls.materials.index("ambient")
    mat_idx = ls.material_map()
    si_mask = mat_idx == idx_si
    amb_mask = mat_idx == idx_amb
    bare = si_mask & binary_dilation(amb_mask)
    if not np.any(bare):
        return ls
    thickness_cm = xi * _UM_TO_CM
    return deposit_conformal3d(ls, "sio2", thickness_um=thickness_cm,
                                rate_um_s=rate_um_hr * _UM_TO_CM)


def _solve_oxidant_diffusion3d(oxide, mat_idx, idx_sio2, idx_si, idx_amb,
                                dx_um, dy_um, dz_um, T_C, ambient):
    D, ks, h, Cgas = _effective_params(T_C, ambient)
    Nx, Ny, Nz = oxide.shape
    C = np.zeros((Nx, Ny, Nz))
    flux_si = np.zeros((Nx, Ny, Nz))
    flux_gas = np.zeros((Nx, Ny, Nz))

    if not np.any(oxide):
        return C, flux_si, flux_gas

    lin_idx = -np.ones((Nx, Ny, Nz), dtype=np.int64)
    ox, oy, oz = np.where(oxide)
    n = ox.size
    lin_idx[ox, oy, oz] = np.arange(n)

    rows, cols, vals = [], [], []
    rhs = np.zeros(n)
    # (di,dj,dk, spacing along the move axis, face AREA perpendicular to it)
    directions = [
        (-1, 0, 0, dx_um, dy_um * dz_um), (1, 0, 0, dx_um, dy_um * dz_um),
        (0, -1, 0, dy_um, dx_um * dz_um), (0, 1, 0, dy_um, dx_um * dz_um),
        (0, 0, -1, dz_um, dx_um * dy_um), (0, 0, 1, dz_um, dx_um * dy_um),
    ]

    for m in range(n):
        i, j, k = ox[m], oy[m], oz[m]
        diag = 0.0
        for di, dj, dk, spacing, face_area in directions:
            ii, jj, kk = i + di, j + dj, k + dk
            if ii < 0 or ii >= Nx or jj < 0 or jj >= Ny or kk < 0 or kk >= Nz:
                continue
            nbr_mat = mat_idx[ii, jj, kk]
            if nbr_mat == idx_sio2:
                w = D / spacing * face_area
                diag += w
                rows.append(m); cols.append(lin_idx[ii, jj, kk]); vals.append(-w)
            elif nbr_mat == idx_amb:
                w = h * face_area
                diag += w
                rhs[m] += w * Cgas
            elif nbr_mat == idx_si:
                w = ks * face_area
                diag += w
        rows.append(m); cols.append(m); vals.append(diag if diag > 0 else 1.0)
        if diag <= 0:
            rhs[m] = 0.0

    M = sp.csr_matrix((vals, (rows, cols)), shape=(n, n))
    C_flat = spsolve(M, rhs)
    C[ox, oy, oz] = C_flat

    for di, dj, dk, spacing, face_area in directions:
        si_ = ox + di; sj_ = oy + dj; sk_ = oz + dk
        valid = (si_ >= 0) & (si_ < Nx) & (sj_ >= 0) & (sj_ < Ny) & (sk_ >= 0) & (sk_ < Nz)
        nbr_mat = np.full(ox.shape, -1)
        nbr_mat[valid] = mat_idx[si_[valid], sj_[valid], sk_[valid]]
        at_si = nbr_mat == idx_si
        at_amb = nbr_mat == idx_amb
        flux_si[si_[at_si], sj_[at_si], sk_[at_si]] += ks * C_flat[at_si]
        flux_gas[si_[at_amb], sj_[at_amb], sk_[at_amb]] += h * (Cgas - C_flat[at_amb])

    return C, flux_si, flux_gas


def _reinit_single3d(phi, ls):
    inside = phi < 0
    if not np.any(inside) or np.all(inside):
        return phi
    d_in = distance_transform_edt(inside, sampling=(ls.dx, ls.dy, ls.dz))
    d_out = distance_transform_edt(~inside, sampling=(ls.dx, ls.dy, ls.dz))
    return np.where(inside, -d_in, d_out)


def oxidize_levelset3d(ls, T_C, t_hours, ambient="dry", steps=20):
    """3D port of `oxidize_levelset.oxidize_levelset` -- identical
    architecture (see that module's docstring), one more axis."""
    for name in ("silicon", "sio2", "ambient"):
        if name not in ls.materials:
            raise ValueError(f"oxidize_levelset3d requires {name!r} in ls.materials")

    seeded = _seed_thin_oxide3d(ls, ambient)
    idx_si = seeded.materials.index("silicon")
    idx_amb = seeded.materials.index("ambient")
    idx_sio2 = seeded.materials.index("sio2")
    static_names = [m for m in seeded.materials if m not in ("silicon", "sio2", "ambient")]
    static_idx = [seeded.materials.index(m) for m in static_names]
    static_phi = [seeded.phi[m] for m in static_names]

    phi_si = seeded.phi["silicon"].copy()
    phi_amb = seeded.phi["ambient"].copy()
    dx, dy, dz = seeded.dx, seeded.dy, seeded.dz
    dx_um, dy_um, dz_um = dx * _CM_TO_UM, dy * _CM_TO_UM, dz * _CM_TO_UM

    def ownership():
        stack = np.stack([phi_si, phi_amb] + static_phi, axis=0)
        idxs = np.array([idx_si, idx_amb] + static_idx)
        winner = np.argmin(stack, axis=0)
        best = np.min(stack, axis=0)
        owner = idxs[winner]
        return np.where(best < 0, owner, idx_sio2)

    dt = t_hours / steps
    reinit_thresh = min(dx, dy, dz)
    accum_si = 0.0
    accum_amb = 0.0
    cfl = 0.4
    D, ks, h, Cgas = _effective_params(T_C, ambient)

    for _ in range(steps):
        mat_idx = ownership()
        oxide = mat_idx == idx_sio2
        if np.any(oxide):
            _, flux_si_um, flux_gas_um = _solve_oxidant_diffusion3d(
                oxide, mat_idx, idx_sio2, idx_si, idx_amb, dx_um, dy_um, dz_um, T_C, ambient)
        else:
            bare_flux_um = Cgas / (1.0 / h + 1.0 / ks)
            bare = (mat_idx == idx_si) & binary_dilation(mat_idx == idx_amb)
            flux_si_um = np.where(bare, bare_flux_um, 0.0)
            flux_gas_um = np.where(binary_dilation(mat_idx == idx_si) & (mat_idx == idx_amb),
                                    bare_flux_um, 0.0)
        V_si = 0.44 * flux_si_um * _UM_TO_CM
        V_gas = 0.56 * flux_gas_um * _UM_TO_CM

        t = 0.0
        while t < dt - 1e-15:
            dt_sub = cfl_dt3d(V_si, dx, dy, dz, cfl)
            dt_sub = min(dt_sub, dt - t)
            phi_si = advect_upwind3d(phi_si, -V_si, dx, dy, dz, dt_sub)
            t += dt_sub
        accum_si += dt * float(np.max(V_si)) if np.any(V_si) else 0.0
        if accum_si >= reinit_thresh:
            phi_si = _reinit_single3d(phi_si, seeded)
            accum_si = 0.0

        t = 0.0
        while t < dt - 1e-15:
            dt_sub = cfl_dt3d(V_gas, dx, dy, dz, cfl)
            dt_sub = min(dt_sub, dt - t)
            phi_amb = advect_upwind3d(phi_amb, -V_gas, dx, dy, dz, dt_sub)
            t += dt_sub
        accum_amb += dt * float(np.max(V_gas)) if np.any(V_gas) else 0.0
        if accum_amb >= reinit_thresh:
            phi_amb = _reinit_single3d(phi_amb, seeded)
            accum_amb = 0.0

    final_owner = ownership()
    final = seeded.copy()
    final.phi["silicon"] = phi_si
    final.phi["ambient"] = phi_amb
    return _project_from_owner3d(final, final_owner)


def oxidize_levelset3d_with_dopant(ls, Cdop, species_m, T_C, t_hours, ambient="dry", steps=20):
    """3D port of `oxidize_levelset.oxidize_levelset_with_dopant` --
    identical algorithm (see that function's docstring), generalized
    from "per column" to "per (x,z) line" for the dose-redistribution
    bookkeeping."""
    for name in ("silicon", "sio2", "ambient"):
        if name not in ls.materials:
            raise ValueError(f"oxidize_levelset3d_with_dopant requires {name!r} in ls.materials")

    seeded = _seed_thin_oxide3d(ls, ambient)
    Cdop = np.asarray(Cdop, dtype=float).copy()
    idx_si = seeded.materials.index("silicon")
    idx_amb = seeded.materials.index("ambient")
    idx_sio2 = seeded.materials.index("sio2")
    static_names = [m for m in seeded.materials if m not in ("silicon", "sio2", "ambient")]
    static_idx = [seeded.materials.index(m) for m in static_names]
    static_phi = [seeded.phi[m] for m in static_names]

    phi_si = seeded.phi["silicon"].copy()
    phi_amb = seeded.phi["ambient"].copy()
    dx, dy, dz = seeded.dx, seeded.dy, seeded.dz
    dx_um, dy_um, dz_um = dx * _CM_TO_UM, dy * _CM_TO_UM, dz * _CM_TO_UM
    Nx, Ny, Nz = phi_si.shape

    def ownership(phi_si_, phi_amb_):
        stack = np.stack([phi_si_, phi_amb_] + static_phi, axis=0)
        idxs = np.array([idx_si, idx_amb] + static_idx)
        winner = np.argmin(stack, axis=0)
        best = np.min(stack, axis=0)
        owner = idxs[winner]
        return np.where(best < 0, owner, idx_sio2)

    dt = t_hours / steps
    reinit_thresh = min(dx, dy, dz)
    accum_si = 0.0
    accum_amb = 0.0
    cfl = 0.4
    D, ks, h, Cgas = _effective_params(T_C, ambient)

    for _ in range(steps):
        owner_before = ownership(phi_si, phi_amb)
        oxide = owner_before == idx_sio2
        if np.any(oxide):
            _, flux_si_um, flux_gas_um = _solve_oxidant_diffusion3d(
                oxide, owner_before, idx_sio2, idx_si, idx_amb, dx_um, dy_um, dz_um, T_C, ambient)
        else:
            bare_flux_um = Cgas / (1.0 / h + 1.0 / ks)
            bare = (owner_before == idx_si) & binary_dilation(owner_before == idx_amb)
            flux_si_um = np.where(bare, bare_flux_um, 0.0)
            flux_gas_um = np.where(
                binary_dilation(owner_before == idx_si) & (owner_before == idx_amb),
                bare_flux_um, 0.0)
        V_si = 0.44 * flux_si_um * _UM_TO_CM
        V_gas = 0.56 * flux_gas_um * _UM_TO_CM

        t = 0.0
        while t < dt - 1e-15:
            dt_sub = cfl_dt3d(V_si, dx, dy, dz, cfl)
            dt_sub = min(dt_sub, dt - t)
            phi_si = advect_upwind3d(phi_si, -V_si, dx, dy, dz, dt_sub)
            t += dt_sub
        accum_si += dt * float(np.max(V_si)) if np.any(V_si) else 0.0
        if accum_si >= reinit_thresh:
            phi_si = _reinit_single3d(phi_si, seeded)
            accum_si = 0.0

        owner_after_si = ownership(phi_si, phi_amb)
        transitioned = (owner_before == idx_si) & (owner_after_si == idx_sio2)
        if np.any(transitioned):
            xs, zs = np.where(np.any(transitioned, axis=1))
            for ix, iz in zip(xs, zs):
                col = transitioned[ix, :, iz]
                rows = np.sort(np.where(col)[0])
                nxt = rows[-1] + 1
                if nxt >= Ny:
                    continue
                Q = (Cdop[ix, rows, iz].sum() + Cdop[ix, nxt, iz]) * dy
                C_si_new, C_ox_new = segregation_partition(
                    Q, species_m, thickness_si_cm=dy, thickness_ox_cm=dy * rows.size)
                Cdop[ix, rows, iz] = C_ox_new
                Cdop[ix, nxt, iz] = C_si_new

        t = 0.0
        while t < dt - 1e-15:
            dt_sub = cfl_dt3d(V_gas, dx, dy, dz, cfl)
            dt_sub = min(dt_sub, dt - t)
            phi_amb = advect_upwind3d(phi_amb, -V_gas, dx, dy, dz, dt_sub)
            t += dt_sub
        accum_amb += dt * float(np.max(V_gas)) if np.any(V_gas) else 0.0
        if accum_amb >= reinit_thresh:
            phi_amb = _reinit_single3d(phi_amb, seeded)
            accum_amb = 0.0

    final_owner = ownership(phi_si, phi_amb)
    final = seeded.copy()
    final.phi["silicon"] = phi_si
    final.phi["ambient"] = phi_amb
    final_ls = _project_from_owner3d(final, final_owner)
    return final_ls, Cdop
