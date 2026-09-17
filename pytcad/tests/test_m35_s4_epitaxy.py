"""M35-S4 acceptance gates: epitaxy as facet-dependent deposition. See
pytcad/M35-3D-PROCESS-PLAN.md section 5.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from pytcad.levelset2d import LevelSet2D, project, deposit_conformal, deposit_epitaxial


def _flat_grid(Nx=80, Ny=80, x1=1.0, y1=1.0):
    ls = LevelSet2D(x0=0.0, x1=x1, Nx=Nx, y0=0.0, y1=y1, Ny=Ny,
                     materials=("silicon", "poly", "ambient"))
    silicon_top = 0.5
    ls.phi["silicon"] = silicon_top - ls.Y
    ls.phi["ambient"] = ls.Y - silicon_top
    ls.phi["poly"] = np.full((Ny, Nx), 10.0)
    return project(ls)


def _trench_grid(Nx=120, Ny=120, x1=1.0, y1=1.0):
    """A trench: silicon everywhere below y=0.6, EXCEPT a rectangular
    notch cut out for 0.4<=x<=0.6, 0.2<=y<=0.6 (an open trench with
    vertical sidewalls and a flat bottom at y=0.6, flat top at y=0.2
    elsewhere)."""
    ls = LevelSet2D(x0=0.0, x1=x1, Nx=Nx, y0=0.0, y1=y1, Ny=Ny,
                     materials=("silicon", "poly", "ambient"))
    X, Y = ls.X, ls.Y
    in_trench = (X >= 0.4) & (X <= 0.6) & (Y >= 0.2) & (Y <= 0.6)
    is_silicon = (Y >= 0.6) | ((Y >= 0.2) & ~in_trench)
    ls.phi["silicon"] = np.where(is_silicon, -1.0, 1.0)
    ls.phi["ambient"] = np.where(is_silicon, 1.0, -1.0)
    ls.phi["poly"] = np.full((Ny, Nx), 10.0)
    return project(ls)


def test_isotropic_rate_fn_reduces_exactly_to_deposit_conformal():
    ls1 = _flat_grid()
    ls2 = _flat_grid()
    out_conformal = deposit_conformal(ls1, "poly", thickness_um=0.1, rate_um_s=1.0)
    out_epi_none = deposit_epitaxial(ls2, "poly", thickness_um=0.1, rate_um_s=1.0)
    for name in ("silicon", "poly", "ambient"):
        assert np.array_equal(out_conformal.phi[name], out_epi_none.phi[name]), (
            f"rate_fn=None must reduce EXACTLY (same code path) to deposit_conformal for {name!r}"
        )


def test_uniform_rate_fn_matches_conformal_deposit():
    """A constant rate_fn (returns 1.0 everywhere) is the isotropic case
    -- physically identical to deposit_conformal, though it goes through
    the facet-normal code path rather than the same function call, so
    check physical equivalence (thickness), not bit-identity."""
    ls1 = _flat_grid()
    ls2 = _flat_grid()
    out_conformal = deposit_conformal(ls1, "poly", thickness_um=0.1, rate_um_s=1.0)
    out_epi = deposit_epitaxial(ls2, "poly", thickness_um=0.1, rate_um_s=1.0,
                                 rate_fn=lambda nx, ny: np.ones_like(nx))
    idx_poly = out_conformal.materials.index("poly")
    thickness_conformal = np.count_nonzero(out_conformal.material_map() == idx_poly)
    thickness_epi = np.count_nonzero(out_epi.material_map() == idx_poly)
    rel_err = abs(thickness_epi - thickness_conformal) / thickness_conformal
    print(f"S4 epitaxy uniform rate_fn vs conformal: {thickness_conformal} vs {thickness_epi} cells, "
          f"rel_err={rel_err:.4e}")
    assert rel_err < 0.05


def test_anisotropic_rate_fn_grows_faster_on_a_chosen_facet():
    """rate_fn favoring the (0,-1) normal (straight up, ny<0 in this
    module's convention since y increases downward and 'up' is toward
    smaller y) should grow MUCH thicker on the flat top of the trench
    grid than on its vertical sidewalls, where the local normal is
    horizontal (favored direction's dot product ~0)."""
    ls = _trench_grid()

    def rate_fn(nx, ny):
        # favor the upward-facing normal (ny < 0, i.e. pointing to
        # smaller y): speed ~1 on a flat top, ~0 on a vertical sidewall
        return np.maximum(-ny, 0.0)

    out = deposit_epitaxial(ls, "poly", thickness_um=0.05, rate_um_s=1.0, rate_fn=rate_fn)
    idx_poly = out.materials.index("poly")
    mat_idx = out.material_map()

    x, y = out.x, out.y
    flat_top_col = np.argmin(np.abs(x - 0.1))     # far from the trench, flat top
    sidewall_col = np.argmin(np.abs(x - 0.4))     # right at the trench's vertical wall
    # exclude the trench's top/bottom corners (mixed-normal cells) --
    # probe only the middle of the sidewall, where the local normal is
    # purely horizontal
    mid_wall_rows = (y >= 0.3) & (y <= 0.5)

    flat_top_poly = np.count_nonzero(mat_idx[:, flat_top_col] == idx_poly)
    sidewall_poly = np.count_nonzero(mat_idx[mid_wall_rows, sidewall_col] == idx_poly)
    print(f"S4 anisotropic epitaxy: flat_top_poly_cells={flat_top_poly}, mid_sidewall_poly_cells={sidewall_poly}")
    assert flat_top_poly >= 3, "flat top should grow a measurable amount under the favored facet"
    assert sidewall_poly == 0, (
        "the vertical sidewall's local normal is horizontal (perpendicular to the "
        "favored direction), so the disfavored-facet rate should be exactly zero there"
    )
