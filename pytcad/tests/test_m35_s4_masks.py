"""M35-S4 acceptance gates: masks as first-class 2D objects (patterned
deposition via deposit_conformal's new x_windows param). See
pytcad/M35-3D-PROCESS-PLAN.md section 5.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from pytcad.levelset2d import LevelSet2D, project, deposit_conformal, etch_isotropic

_UM_TO_CM = 1.0e-4


def _flat_stack(Nx=40, Ny=200, y_span_um=2.0, y_si_um=1.0):
    y0, y1 = 0.0, y_span_um * _UM_TO_CM
    x0, x1 = 0.0, 1.0 * _UM_TO_CM * Nx
    ls = LevelSet2D(x0=x0, x1=x1, Nx=Nx, y0=y0, y1=y1, Ny=Ny,
                     materials=("silicon", "resist", "ambient"))
    y_si = y_si_um * _UM_TO_CM
    ls.phi["silicon"] = y_si - ls.Y
    ls.phi["ambient"] = ls.Y - y_si
    ls.phi["resist"] = np.full((Ny, Nx), 10.0 * y_span_um * _UM_TO_CM)
    return project(ls)


def test_patterned_deposit_stays_inside_window():
    ls = _flat_stack()
    x_um = ls.x * 1.0e4
    lo_um, hi_um = 15.0, 25.0
    out = deposit_conformal(ls, "resist", thickness_um=0.3 * _UM_TO_CM,
                             rate_um_s=1.0 * _UM_TO_CM,
                             x_windows=[(lo_um * _UM_TO_CM, hi_um * _UM_TO_CM)])

    idx_resist = out.materials.index("resist")
    mat_idx = out.material_map()
    inside_cols = (x_um >= lo_um) & (x_um <= hi_um)
    outside_cols = ~inside_cols

    assert np.any(mat_idx[:, inside_cols] == idx_resist), "resist must be deposited inside the window"
    assert not np.any(mat_idx[:, outside_cols] == idx_resist), "resist must NOT appear outside the window"


def test_x_windows_none_matches_blanket_deposit():
    ls1 = _flat_stack()
    ls2 = _flat_stack()
    out_blanket = deposit_conformal(ls1, "resist", thickness_um=0.3 * _UM_TO_CM,
                                     rate_um_s=1.0 * _UM_TO_CM)
    out_default = deposit_conformal(ls2, "resist", thickness_um=0.3 * _UM_TO_CM,
                                     rate_um_s=1.0 * _UM_TO_CM, x_windows=None)
    for name in ("silicon", "resist", "ambient"):
        assert np.array_equal(out_blanket.phi[name], out_default.phi[name]), (
            f"x_windows=None must be bit-identical to the default (no window arg) for {name!r}"
        )


def test_patterned_mask_produces_real_undercut_on_subsequent_etch():
    """The patterned resist is REAL geometry, so an isotropic etch of
    silicon underneath its edge should undercut, exactly like S2's own
    manually-built-cap undercut gate (test_m35_s2_topology.py's
    per-column retreat-depth measure, reused here, at the SAME grid
    scale that gate uses -- see below for why the scale matters).

    Grid scale note: `advance_front`'s masked-erosion exposure test
    recomputes lateral grid-adjacency via `binary_dilation` once per
    CFL substep -- correct for S2's own gate (few tens of substeps at
    that grid's dx), but the number of substeps needed for a given
    physical depth grows as the grid is refined (finer dy/dx -> smaller
    CFL dt -> more substeps for the same t_total), and each substep can
    extend lateral "exposure" adjacency by up to one grid cell
    REGARDLESS of how small that substep's actual physical dt was. At
    a much finer grid than S2's own gate uses, this was confirmed
    directly to over-propagate undercut across the ENTIRE mask width
    (a 20-unit-wide mask fully undercut by a 0.6-unit-deep etch, which
    is not physically possible for an isotropic front of that speed).
    This is a pre-existing property of the already-landed, already-gated
    `advance_front` (S2 scope), not something introduced here -- S2's
    own gate happens not to exercise it because its grid/depth ratio
    keeps the substep count low. Fixing the underlying rate limiter is
    out of S4's scope (masks/silicidation/epitaxy/CMP, not a rework of
    S2's core erosion loop); this test instead uses THE SAME grid scale
    as S2's own accepted gate (`test_m35_s2_topology.py`'s
    `test_isotropic_etch_undercut_matches_depth_to_grid_resolution`),
    where that gate is already known to pass, and its purpose here is
    narrower: confirm a PATTERNED mask (built via `x_windows`) produces
    the same real, physical undercut behavior as a hand-built cap, not
    to re-litigate S2's own numerics."""
    Nx, Ny = 200, 100
    ls = LevelSet2D(x0=0.0, x1=1.0, Nx=Nx, y0=0.0, y1=0.5, Ny=Ny,
                     materials=("silicon", "resist", "ambient"))
    silicon_top = 0.2
    ls.phi["silicon"] = silicon_top - ls.Y
    ls.phi["ambient"] = ls.Y - silicon_top
    ls.phi["resist"] = np.full((Ny, Nx), 10.0)
    ls = project(ls)

    cap_thickness = 0.2   # matches S2's own cap_bottom=0.2 exactly
    masked = deposit_conformal(ls, "resist", thickness_um=cap_thickness,
                                rate_um_s=1.0, x_windows=[(0.0, 0.5)])

    depth = 0.06
    etched = etch_isotropic(masked, "silicon", depth_um=depth, rate_um_s=1.0)

    x, y = etched.x, etched.y
    phi = etched.phi["silicon"]
    col_depth = np.full(x.shape, np.nan)
    for i in range(x.size):
        col = phi[:, i]
        idxs = np.where(np.diff(np.sign(col)) != 0)[0]
        if idxs.size:
            k = idxs[0]
            y_c = y[k] - col[k] * (y[k + 1] - y[k]) / (col[k + 1] - col[k])
            col_depth[i] = y_c - silicon_top

    achieved_depth = np.nanmax(col_depth)
    half = 0.5 * achieved_depth
    under_cap = (x < 0.5) & ~np.isnan(col_depth) & (col_depth >= half)
    assert np.any(under_cap), "no undercut penetration detected under the patterned mask"
    x_edge = x[under_cap].min()
    undercut = 0.5 - x_edge
    err = abs(undercut - achieved_depth)
    print(f"S4 patterned-mask undercut: {undercut:.4e}, achieved depth: {achieved_depth:.4e}, err: {err:.4e}")
    assert err < 5 * etched.dx
    # deep interior of the mask (far from the edge) must stay essentially
    # unetched -- physically, undercut of ~achieved_depth cannot reach
    # a point ~0.5 units from the exposed edge
    interior_col = np.argmin(np.abs(x - 0.1))
    assert np.isnan(col_depth[interior_col]) or col_depth[interior_col] < 0.5 * depth, \
        "silicon deep under the mask interior should stay essentially unetched"
