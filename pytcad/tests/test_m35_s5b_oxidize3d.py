"""M35-S5 (full-scope pass): oxidation + dopant transport in 3D, a
direct port of oxidize_levelset.py's already-debugged architecture to
LevelSet3D. See M35-3D-PROCESS-PLAN.md section 16/17.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from pytcad.levelset3d import LevelSet3D, project3d
from pytcad.oxidize_levelset3d import oxidize_levelset3d, oxidize_levelset3d_with_dopant
from pytcad import process

_UM_TO_CM = 1.0e-4
_CM_TO_UM = 1.0e4


def _flat_wafer3d(Nx=10, Ny=400, Nz=6, y_span_um=1.5, y_si_um=0.9, x_span_um=1.0, z_span_um=1.0):
    y0, y1 = 0.0, y_span_um * _UM_TO_CM
    x0, x1 = 0.0, x_span_um * _UM_TO_CM * Nx
    z0, z1 = 0.0, z_span_um * _UM_TO_CM * Nz
    ls = LevelSet3D(x0=x0, x1=x1, Nx=Nx, y0=y0, y1=y1, Ny=Ny, z0=z0, z1=z1, Nz=Nz,
                     materials=("silicon", "sio2", "ambient"))
    y_si = y_si_um * _UM_TO_CM
    Y = ls.Y
    ls.phi["silicon"] = y_si - Y
    ls.phi["ambient"] = Y - y_si
    ls.phi["sio2"] = np.full((Nx, Ny, Nz), 10.0 * y_span_um * _UM_TO_CM)
    return project3d(ls)


def _oxide_thickness_um3d(ls, ix, iz):
    idx = ls.materials.index("sio2")
    mat_idx = ls.material_map()
    return np.count_nonzero(mat_idx[ix, :, iz] == idx) * ls.dy * _CM_TO_UM


def test_dry_oxidation_reduces_to_deal_grove_1d_3d():
    T_C, t_hours = 1000.0, 1.0
    ls = _flat_wafer3d()
    out = oxidize_levelset3d(ls, T_C=T_C, t_hours=t_hours, ambient="dry", steps=20)
    x_analytic = process.oxide_thickness(T_C, t_hours, "dry")
    ix, iz = out.Nx // 2, out.Nz // 2
    x_sim = _oxide_thickness_um3d(out, ix, iz)
    rel_err = abs(x_sim - x_analytic) / x_analytic
    print(f"S5b dry 3D reduction: analytic={x_analytic:.4e}, sim={x_sim:.4e}, rel_err={rel_err:.4e}")
    assert rel_err < 0.15


def test_oxidation_mass_conservation_3d():
    T_C, t_hours = 1000.0, 0.5
    ls = _flat_wafer3d()
    out = oxidize_levelset3d(ls, T_C=T_C, t_hours=t_hours, ambient="dry", steps=20)
    ix, iz = out.Nx // 2, out.Nz // 2
    idx_si = out.materials.index("silicon")
    si_before = np.count_nonzero(ls.material_map()[ix, :, iz] == idx_si) * ls.dy * _CM_TO_UM
    si_after = np.count_nonzero(out.material_map()[ix, :, iz] == idx_si) * ls.dy * _CM_TO_UM
    si_consumed = si_before - si_after
    x_ox = _oxide_thickness_um3d(out, ix, iz)
    si_consumed_expected = process.silicon_consumed(x_ox)
    rel_err = abs(si_consumed - si_consumed_expected) / si_consumed_expected
    print(f"S5b mass conservation 3D: si_consumed={si_consumed:.4e}, "
          f"expected={si_consumed_expected:.4e}, rel_err={rel_err:.4e}")
    assert rel_err < 0.15


def test_dopant_dose_conserved_across_oxidation_step_3d():
    ls = _flat_wafer3d()
    y_um = ls.y * _CM_TO_UM
    profile_1d = 1e19 * np.exp(-((y_um - 0.9) ** 2) / (2 * 0.03 ** 2))
    Cdop = np.tile(profile_1d[None, :, None], (ls.Nx, 1, ls.Nz))

    dose_before = np.sum(Cdop) * ls.dy
    out, Cdop_after = oxidize_levelset3d_with_dopant(
        ls, Cdop, species_m=0.3, T_C=1000.0, t_hours=1.0, ambient="dry", steps=20)
    dose_after = np.sum(Cdop_after) * ls.dy
    rel_err = abs(dose_after - dose_before) / dose_before
    print(f"S5b dose conservation 3D: before={dose_before:.6e}, after={dose_after:.6e}, "
          f"rel_err={rel_err:.4e}")
    assert rel_err < 1e-9
