"""M35-S4 acceptance gates: CMP planarization. See
pytcad/M35-3D-PROCESS-PLAN.md section 5.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from pytcad.levelset2d import LevelSet2D, project, planarize

_UM_TO_CM = 1.0e-4


def _bumpy_wafer(Nx=20, Ny=200, y_span_um=2.0):
    """silicon fills a bumpy surface: y_surf(x) = 1.0 + 0.3*sin(2*pi*x/Nx)
    um, ambient above it. Bump peak ~0.7um, valley ~1.3um."""
    y0, y1 = 0.0, y_span_um * _UM_TO_CM
    x0, x1 = 0.0, 1.0 * _UM_TO_CM * Nx
    ls = LevelSet2D(x0=x0, x1=x1, Nx=Nx, y0=y0, y1=y1, Ny=Ny,
                     materials=("silicon", "ambient"))
    x_idx = np.arange(Nx)
    y_surf_um = 1.0 + 0.3 * np.sin(2 * np.pi * x_idx / Nx)
    y_surf = y_surf_um[None, :] * _UM_TO_CM
    ls.phi["silicon"] = y_surf - ls.Y
    ls.phi["ambient"] = ls.Y - y_surf
    return project(ls)


def test_planarize_clears_material_above_cut_line():
    ls = _bumpy_wafer()
    y_cmp_um = 0.9   # between peak (0.7) and valley (1.3)
    out = planarize(ls, y_cmp_um)

    idx_si = out.materials.index("silicon")
    idx_amb = out.materials.index("ambient")
    mat_idx = out.material_map()
    y_cmp = y_cmp_um * _UM_TO_CM

    above = ls.Y < y_cmp
    below = ~above
    assert np.all(mat_idx[above] == idx_amb), "everything above the cut line must be ambient"
    # below the cut line, ownership must match the ORIGINAL geometry
    orig_idx = ls.material_map()
    assert np.array_equal(mat_idx[below], orig_idx[below]), \
        "geometry below the cut line must be untouched"


def test_planarize_above_all_material_is_noop():
    ls = _bumpy_wafer()
    out = planarize(ls, y_cmp_um=0.01)   # shallower than the highest bump peak (0.7)
    orig_idx = ls.material_map()
    new_idx = out.material_map()
    assert np.array_equal(orig_idx, new_idx), "cut line above all material must be a no-op"


def test_planarize_below_all_material_clears_everything():
    ls = _bumpy_wafer(y_span_um=2.0)
    out = planarize(ls, y_cmp_um=2.5)   # deeper than the whole domain (y1=2.0)
    idx_amb = out.materials.index("ambient")
    mat_idx = out.material_map()
    assert np.all(mat_idx == idx_amb), "cut line below all material must clear everything to ambient"
