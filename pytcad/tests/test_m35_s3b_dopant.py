"""M35-S3b acceptance gates: dopant transport across the moving
oxidation boundary. See pytcad/M35-3D-PROCESS-PLAN.md section 4b.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from pytcad.levelset2d import LevelSet2D, project
from pytcad.oxidize_levelset import oxidize_levelset, oxidize_levelset_with_dopant

_UM_TO_CM = 1.0e-4
_CM_TO_UM = 1.0e4


def _flat_wafer(Nx=16, Ny=400, y_span_um=1.5, y_si_um=0.9):
    y0, y1 = 0.0, y_span_um * _UM_TO_CM
    x0, x1 = 0.0, 1.0 * _UM_TO_CM * Nx
    ls = LevelSet2D(x0=x0, x1=x1, Nx=Nx, y0=y0, y1=y1, Ny=Ny,
                     materials=("silicon", "sio2", "ambient"))
    y_si = y_si_um * _UM_TO_CM
    Y = ls.Y
    ls.phi["silicon"] = y_si - Y
    ls.phi["ambient"] = Y - y_si
    ls.phi["sio2"] = np.full((Ny, Nx), 10.0 * y_span_um * _UM_TO_CM)
    return project(ls)


def _gaussian_dopant(ls, y_si_um, peak=1e19, straggle_um=0.03):
    """A dose profile straddling the interface, peaked right at it."""
    y_um = ls.y * _CM_TO_UM
    profile_1d = peak * np.exp(-((y_um - y_si_um) ** 2) / (2 * straggle_um ** 2))
    return np.tile(profile_1d[:, None], (1, ls.Nx))


def _total_dose(Cdop, dy_cm):
    """Sum over the whole grid, areal-per-column style (dose per unit
    x times number of columns -- used only for BEFORE/AFTER ratio
    checks on the SAME grid, so absolute units don't matter)."""
    return np.sum(Cdop) * dy_cm


# ----------------------------------------------------------------------
#  dose conservation -- the load-bearing gate
# ----------------------------------------------------------------------
def test_dose_conserved_across_oxidation_step():
    ls = _flat_wafer()
    Cdop = _gaussian_dopant(ls, y_si_um=0.9)
    dose_before = _total_dose(Cdop, ls.dy)

    out, Cdop_after = oxidize_levelset_with_dopant(
        ls, Cdop, species_m=0.3, T_C=1000.0, t_hours=1.0, ambient="dry", steps=25)
    dose_after = _total_dose(Cdop_after, ls.dy)

    rel_err = abs(dose_after - dose_before) / dose_before
    print(f"S3b dose conservation: before={dose_before:.6e}, after={dose_after:.6e}, "
          f"rel_err={rel_err:.4e}")
    assert rel_err < 1e-9, "dose must be conserved to near machine precision (algebraic step)"


# ----------------------------------------------------------------------
#  split direction, m<1: dopant prefers oxide (boron-like)
# ----------------------------------------------------------------------
def test_low_m_enriches_oxide_relative_to_silicon():
    ls = _flat_wafer()
    Cdop = _gaussian_dopant(ls, y_si_um=0.9)

    out, Cdop_after = oxidize_levelset_with_dopant(
        ls, Cdop, species_m=0.2, T_C=1000.0, t_hours=1.0, ambient="dry", steps=25)

    idx_si = out.materials.index("silicon")
    idx_sio2 = out.materials.index("sio2")
    mat_idx = out.material_map()
    col = out.Nx // 2
    ox_cells = mat_idx[:, col] == idx_sio2
    si_cells = mat_idx[:, col] == idx_si
    assert np.any(ox_cells) and np.any(si_cells)
    C_ox_mean = Cdop_after[ox_cells, col].mean()
    C_si_at_surface = Cdop_after[si_cells, col][:5].mean()  # just below the new interface
    print(f"S3b m<1: C_ox_mean={C_ox_mean:.4e}, C_si_near_surface={C_si_at_surface:.4e}")
    assert C_ox_mean > C_si_at_surface, "m<1 should enrich the oxide side"


# ----------------------------------------------------------------------
#  split direction, m>1: dopant prefers silicon (P/As pile-up)
# ----------------------------------------------------------------------
def test_high_m_piles_up_dopant_in_silicon():
    ls = _flat_wafer()
    Cdop = _gaussian_dopant(ls, y_si_um=0.9)

    out, Cdop_after = oxidize_levelset_with_dopant(
        ls, Cdop, species_m=5.0, T_C=1000.0, t_hours=1.0, ambient="dry", steps=25)

    idx_si = out.materials.index("silicon")
    idx_sio2 = out.materials.index("sio2")
    mat_idx = out.material_map()
    col = out.Nx // 2
    ox_cells = mat_idx[:, col] == idx_sio2
    si_cells = mat_idx[:, col] == idx_si
    assert np.any(ox_cells) and np.any(si_cells)
    C_ox_mean = Cdop_after[ox_cells, col].mean()
    C_si_at_surface = Cdop_after[si_cells, col][:5].mean()
    print(f"S3b m>1: C_ox_mean={C_ox_mean:.4e}, C_si_near_surface={C_si_at_surface:.4e}")
    assert C_si_at_surface > C_ox_mean, "m>1 should pile dopant up in the silicon side"


# ----------------------------------------------------------------------
#  the oxide/silicon split ratio moves monotonically with m
# ----------------------------------------------------------------------
def test_split_ratio_is_monotonic_in_segregation_coefficient():
    """m=1 does NOT make the final oxide-mean equal the final
    silicon-near-surface mean -- each local conversion event splits
    evenly at m=1, but those events happen at DIFFERENT times against a
    non-uniform (Gaussian) initial profile, so their aggregate need not
    match. What m=1 actually guarantees is a position BETWEEN the low-m
    and high-m cases -- checked directly here instead of assuming the
    stronger (and wrong) equal-means claim."""
    def ratio(m):
        ls = _flat_wafer()
        Cdop = _gaussian_dopant(ls, y_si_um=0.9)
        out, Cdop_after = oxidize_levelset_with_dopant(
            ls, Cdop, species_m=m, T_C=1000.0, t_hours=1.0, ambient="dry", steps=25)
        idx_si = out.materials.index("silicon")
        idx_sio2 = out.materials.index("sio2")
        mat_idx = out.material_map()
        col = out.Nx // 2
        ox_cells = mat_idx[:, col] == idx_sio2
        si_cells = mat_idx[:, col] == idx_si
        C_ox_mean = Cdop_after[ox_cells, col].mean()
        C_si_at_surface = Cdop_after[si_cells, col][:5].mean()
        return C_ox_mean / C_si_at_surface

    r_low = ratio(0.2)
    r_mid = ratio(1.0)
    r_high = ratio(5.0)
    print(f"S3b oxide/silicon ratio: m=0.2 -> {r_low:.4f}, m=1.0 -> {r_mid:.4f}, "
          f"m=5.0 -> {r_high:.4f}")
    assert r_low > r_mid > r_high, "the oxide/silicon split ratio must decrease monotonically as m increases"


# ----------------------------------------------------------------------
#  geometry unaffected by dopant tracking
# ----------------------------------------------------------------------
def test_dopant_tracking_does_not_perturb_geometry():
    ls1 = _flat_wafer()
    ls2 = _flat_wafer()
    Cdop = _gaussian_dopant(ls2, y_si_um=0.9)

    out_plain = oxidize_levelset(ls1, T_C=1000.0, t_hours=1.0, ambient="dry", steps=25)
    out_with_dopant, _ = oxidize_levelset_with_dopant(
        ls2, Cdop, species_m=0.5, T_C=1000.0, t_hours=1.0, ambient="dry", steps=25)

    for name in ("silicon", "sio2", "ambient"):
        assert np.array_equal(out_plain.phi[name], out_with_dopant.phi[name]), (
            f"dopant tracking perturbed the {name!r} geometry"
        )
