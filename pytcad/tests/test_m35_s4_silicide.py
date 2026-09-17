"""M35-S4 acceptance gates: silicidation as a moving-boundary problem,
structurally mirroring M35-S3's oxidation solver. See
pytcad/M35-3D-PROCESS-PLAN.md section 5.

No built-in named silicide (NiSi/CoSi2/TiSi2): a web-search literature
pass for a verifiable numeric (B, A) rate-constant table came back with
only contradictory secondary-source activation-energy snippets and no
verified open-access prefactor -- the same class of blocker as M14's
G-A. (B, A) and the consumption split are REQUIRED caller arguments
here; this is a real, honestly-limited linear-parabolic moving-boundary
solver, not calibrated to any specific real silicide.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.levelset2d import LevelSet2D, project
from pytcad.silicide_levelset import silicide_levelset

_UM_TO_CM = 1.0e-4
_CM_TO_UM = 1.0e4


def _metal_on_silicon(Nx=16, Ny=400, y_span_um=1.5, y_metal_si_um=0.9):
    """A flat stack: silicon below y_metal_si_um, metal above it, no
    silicide yet."""
    y0, y1 = 0.0, y_span_um * _UM_TO_CM
    x0, x1 = 0.0, 1.0 * _UM_TO_CM * Nx
    ls = LevelSet2D(x0=x0, x1=x1, Nx=Nx, y0=y0, y1=y1, Ny=Ny,
                     materials=("silicon", "silicide", "metal"))
    y_int = y_metal_si_um * _UM_TO_CM
    Y = ls.Y
    ls.phi["silicon"] = y_int - Y
    ls.phi["metal"] = Y - y_int
    ls.phi["silicide"] = np.full((Ny, Nx), 10.0 * y_span_um * _UM_TO_CM)
    return project(ls)


def _silicide_thickness_um(ls, col):
    idx = ls.materials.index("silicide")
    mat_idx = ls.material_map()
    return np.count_nonzero(mat_idx[:, col] == idx) * ls.dy * _CM_TO_UM


def test_bad_consumption_split_rejected():
    ls = _metal_on_silicon()
    with pytest.raises(ValueError):
        silicide_levelset(ls, B_um2_hr=0.02, A_um=0.05, t_hours=1.0,
                           si_consumption_frac=0.3, metal_consumption_frac=0.3)


def test_flat_stack_reduces_to_linear_parabolic_1d():
    """No lateral variation -> every column must independently satisfy
    the SAME dx/dt=B/(2x+A) integrated thickness (analytic, closed
    form: x(t) = -A/2 + sqrt((A/2)^2 + B*t)) to a stated numerical
    tolerance -- the direct silicidation analog of S3's own dry/wet
    Deal-Grove reduction gates."""
    B, A = 0.02, 0.05   # um^2/hr, um -- arbitrary, self-consistent constants
    t_hours = 2.0
    ls = _metal_on_silicon()
    out = silicide_levelset(ls, B_um2_hr=B, A_um=A, t_hours=t_hours,
                             si_consumption_frac=0.5, metal_consumption_frac=0.5,
                             steps=40)

    x_analytic = -A / 2.0 + np.sqrt((A / 2.0) ** 2 + B * t_hours)
    col = out.Nx // 2
    x_sim = _silicide_thickness_um(out, col)
    rel_err = abs(x_sim - x_analytic) / x_analytic
    print(f"S4 silicide 1D reduction: analytic={x_analytic:.4e} um, sim={x_sim:.4e} um, "
          f"rel_err={rel_err:.4e}")
    assert rel_err < 0.15


def test_mass_conservation():
    """silicon consumed (as thickness) + metal consumed (as thickness)
    must equal the total silicide thickness grown, to a stated
    tolerance -- exactly S3's own mass-conservation gate pattern,
    adapted to two consuming reactants instead of one."""
    B, A = 0.02, 0.05
    t_hours = 1.5
    si_frac, metal_frac = 0.6, 0.4
    ls = _metal_on_silicon()
    out = silicide_levelset(ls, B_um2_hr=B, A_um=A, t_hours=t_hours,
                             si_consumption_frac=si_frac, metal_consumption_frac=metal_frac,
                             steps=40)

    col = out.Nx // 2
    idx_si = out.materials.index("silicon")
    idx_metal = out.materials.index("metal")
    mat_idx_before = ls.material_map()
    mat_idx_after = out.material_map()

    si_before = np.count_nonzero(mat_idx_before[:, col] == idx_si) * ls.dy * _CM_TO_UM
    si_after = np.count_nonzero(mat_idx_after[:, col] == idx_si) * ls.dy * _CM_TO_UM
    metal_before = np.count_nonzero(mat_idx_before[:, col] == idx_metal) * ls.dy * _CM_TO_UM
    metal_after = np.count_nonzero(mat_idx_after[:, col] == idx_metal) * ls.dy * _CM_TO_UM

    si_consumed = si_before - si_after
    metal_consumed = metal_before - metal_after
    silicide_grown = _silicide_thickness_um(out, col)

    rel_err = abs((si_consumed + metal_consumed) - silicide_grown) / silicide_grown
    print(f"S4 silicide mass conservation: si_consumed={si_consumed:.4e}, "
          f"metal_consumed={metal_consumed:.4e}, silicide_grown={silicide_grown:.4e}, "
          f"rel_err={rel_err:.4e}")
    assert rel_err < 0.15


def test_requires_declared_materials():
    ls = LevelSet2D(x0=0.0, x1=1.0e-3, Nx=8, y0=0.0, y1=1.0e-4, Ny=20,
                     materials=("silicon", "ambient"))
    with pytest.raises(ValueError):
        silicide_levelset(ls, B_um2_hr=0.02, A_um=0.05, t_hours=1.0)
