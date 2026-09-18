"""M35-S5 (full-scope pass): masks as first-class 3D objects via
deposit_conformal3d's `windows` param. See
pytcad/M35-3D-PROCESS-PLAN.md section 16/17.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from pytcad.levelset3d import LevelSet3D, project3d, deposit_conformal3d

_UM_TO_CM = 1.0e-4


def _flat_stack(Nx=30, Ny=100, Nz=20):
    ls = LevelSet3D(x0=0.0, x1=30.0 * _UM_TO_CM, Nx=Nx,
                     y0=0.0, y1=2.0 * _UM_TO_CM, Ny=Ny,
                     z0=0.0, z1=20.0 * _UM_TO_CM, Nz=Nz,
                     materials=("silicon", "resist", "ambient"))
    y_si = 1.0 * _UM_TO_CM
    ls.phi["silicon"] = y_si - ls.Y
    ls.phi["ambient"] = ls.Y - y_si
    ls.phi["resist"] = np.full((Nx, Ny, Nz), 10.0 * _UM_TO_CM * 30)
    return project3d(ls)


def test_patterned_deposit_stays_inside_3d_box():
    ls = _flat_stack()
    x_um = ls.x * 1.0e4
    z_um = ls.z * 1.0e4
    box = [(10.0 * _UM_TO_CM, 20.0 * _UM_TO_CM, 5.0 * _UM_TO_CM, 15.0 * _UM_TO_CM)]
    out = deposit_conformal3d(ls, "resist", thickness_um=0.3 * _UM_TO_CM,
                               rate_um_s=1.0 * _UM_TO_CM, windows=box)
    idx_resist = out.materials.index("resist")
    mat_idx = out.material_map()

    in_x = (x_um >= 10.0) & (x_um <= 20.0)
    in_z = (z_um >= 5.0) & (z_um <= 15.0)
    inside_box = in_x[:, None] & in_z[None, :]
    outside_box = ~inside_box

    any_resist_per_col = np.any(mat_idx == idx_resist, axis=1)   # (Nx,Nz)
    assert np.any(any_resist_per_col[inside_box]), "resist must be deposited inside the box"
    assert not np.any(any_resist_per_col[outside_box]), "resist must NOT appear outside the box"


def test_windows_none_matches_blanket_deposit3d():
    ls1 = _flat_stack()
    ls2 = _flat_stack()
    out_blanket = deposit_conformal3d(ls1, "resist", thickness_um=0.3 * _UM_TO_CM,
                                       rate_um_s=1.0 * _UM_TO_CM)
    out_default = deposit_conformal3d(ls2, "resist", thickness_um=0.3 * _UM_TO_CM,
                                       rate_um_s=1.0 * _UM_TO_CM, windows=None)
    for name in ("silicon", "resist", "ambient"):
        assert np.array_equal(out_blanket.phi[name], out_default.phi[name])
