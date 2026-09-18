"""M35-S5 (full-scope pass): silicidation in 3D, a direct port of
silicide_levelset.py's per-line linear-parabolic solver. See
M35-3D-PROCESS-PLAN.md section 16/17.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.levelset3d import LevelSet3D, project3d
from pytcad.silicide_levelset3d import silicide_levelset3d

_UM_TO_CM = 1.0e-4
_CM_TO_UM = 1.0e4


def _metal_on_silicon3d(Nx=6, Ny=400, Nz=6, y_span_um=1.5, y_metal_si_um=0.9):
    y0, y1 = 0.0, y_span_um * _UM_TO_CM
    x0, x1 = 0.0, 1.0 * _UM_TO_CM * Nx
    z0, z1 = 0.0, 1.0 * _UM_TO_CM * Nz
    ls = LevelSet3D(x0=x0, x1=x1, Nx=Nx, y0=y0, y1=y1, Ny=Ny, z0=z0, z1=z1, Nz=Nz,
                     materials=("silicon", "silicide", "metal"))
    y_int = y_metal_si_um * _UM_TO_CM
    Y = ls.Y
    ls.phi["silicon"] = y_int - Y
    ls.phi["metal"] = Y - y_int
    ls.phi["silicide"] = np.full((Nx, Ny, Nz), 10.0 * y_span_um * _UM_TO_CM)
    return project3d(ls)


def _silicide_thickness_um3d(ls, ix, iz):
    idx = ls.materials.index("silicide")
    mat_idx = ls.material_map()
    return np.count_nonzero(mat_idx[ix, :, iz] == idx) * ls.dy * _CM_TO_UM


def test_bad_consumption_split_rejected_3d():
    ls = _metal_on_silicon3d()
    with pytest.raises(ValueError):
        silicide_levelset3d(ls, B_um2_hr=0.02, A_um=0.05, t_hours=1.0,
                             si_consumption_frac=0.3, metal_consumption_frac=0.3)


def test_flat_stack_reduces_to_linear_parabolic_1d_3d():
    B, A = 0.02, 0.05
    t_hours = 2.0
    ls = _metal_on_silicon3d()
    out = silicide_levelset3d(ls, B_um2_hr=B, A_um=A, t_hours=t_hours,
                               si_consumption_frac=0.5, metal_consumption_frac=0.5,
                               steps=40)
    x_analytic = -A / 2.0 + np.sqrt((A / 2.0) ** 2 + B * t_hours)
    ix, iz = out.Nx // 2, out.Nz // 2
    x_sim = _silicide_thickness_um3d(out, ix, iz)
    rel_err = abs(x_sim - x_analytic) / x_analytic
    print(f"S5c silicide 3D reduction: analytic={x_analytic:.4e}, sim={x_sim:.4e}, rel_err={rel_err:.4e}")
    assert rel_err < 0.15


def test_mass_conservation_3d():
    B, A = 0.02, 0.05
    t_hours = 1.5
    si_frac, metal_frac = 0.6, 0.4
    ls = _metal_on_silicon3d()
    out = silicide_levelset3d(ls, B_um2_hr=B, A_um=A, t_hours=t_hours,
                               si_consumption_frac=si_frac, metal_consumption_frac=metal_frac,
                               steps=40)
    ix, iz = out.Nx // 2, out.Nz // 2
    idx_si = out.materials.index("silicon")
    idx_metal = out.materials.index("metal")
    mat_before = ls.material_map()
    mat_after = out.material_map()

    si_before = np.count_nonzero(mat_before[ix, :, iz] == idx_si) * ls.dy * _CM_TO_UM
    si_after = np.count_nonzero(mat_after[ix, :, iz] == idx_si) * ls.dy * _CM_TO_UM
    metal_before = np.count_nonzero(mat_before[ix, :, iz] == idx_metal) * ls.dy * _CM_TO_UM
    metal_after = np.count_nonzero(mat_after[ix, :, iz] == idx_metal) * ls.dy * _CM_TO_UM

    si_consumed = si_before - si_after
    metal_consumed = metal_before - metal_after
    silicide_grown = _silicide_thickness_um3d(out, ix, iz)

    rel_err = abs((si_consumed + metal_consumed) - silicide_grown) / silicide_grown
    print(f"S5c mass conservation 3D: si={si_consumed:.4e}, metal={metal_consumed:.4e}, "
          f"grown={silicide_grown:.4e}, rel_err={rel_err:.4e}")
    assert rel_err < 0.15
