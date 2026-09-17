"""M35-S2 acceptance gates: deposit/etch as real topology on the S1
level set. See pytcad/M35-3D-PROCESS-PLAN.md section 3.

All functions here are ADDITIONS to levelset2d.py; process2d.py and
levelset2d.py's S1 functions (advance_material, project, advect_upwind)
are untouched -- verified by test_regression_s1_still_passes below and
by re-running test_m23_process2d.py / test_m35_s1_levelset.py directly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from scipy.ndimage import label

from pytcad.levelset2d import (
    LevelSet2D, project, advance_front, deposit_conformal,
    etch_isotropic, etch_directional,
)


def _grid(x0=0.0, x1=1.0, Nx=100, y0=0.0, y1=1.0, Ny=100, materials=("silicon", "ambient")):
    return LevelSet2D(x0=x0, x1=x1, Nx=Nx, y0=y0, y1=y1, Ny=Ny, materials=materials)


# ----------------------------------------------------------------------
#  trench pinch-off
# ----------------------------------------------------------------------
def test_conformal_deposit_pinches_off_a_void_in_a_narrow_trench():
    """A keyhole/flask profile: a narrow neck near the opening (closes
    under `thickness`) above a much wider bulb (does not close) --
    isolates whether pinch-off traps a void from whether the whole
    cavity is simply small enough to fill completely (a uniformly
    narrow trench closes end to end, leaving no void at all, which is
    correct physics for that shape, not a pinch-off failure)."""
    Nx, Ny = 200, 200
    L = 1.0
    ls = LevelSet2D(x0=0.0, x1=L, Nx=Nx, y0=0.0, y1=L, Ny=Ny,
                     materials=("silicon", "sio2", "ambient"))
    X, Y = ls.X, ls.Y
    neck_lo, neck_hi = 0.46, 0.54          # 0.08-wide neck near the opening
    neck_bottom = 0.15
    bulb_lo, bulb_hi = 0.3, 0.7            # 0.4-wide bulb below the neck
    bulb_bottom = 0.3
    in_neck = (X > neck_lo) & (X < neck_hi) & (Y < neck_bottom)
    in_bulb = (X > bulb_lo) & (X < bulb_hi) & (Y >= neck_bottom) & (Y < bulb_bottom)
    in_trench = in_neck | in_bulb
    ls.phi["silicon"] = np.where(in_trench, 1.0, -1.0)
    ls.phi["ambient"] = np.where(in_trench, -1.0, 1.0)
    ls.phi["sio2"] = np.full((Ny, Nx), 5.0)
    ls = project(ls)

    thickness = 0.07   # > half the 0.08 neck (closes it); << half the 0.4 bulb
    out = deposit_conformal(ls, "sio2", thickness_um=thickness, rate_um_s=1.0)

    ambient_mask = out.phi["ambient"] < 0
    labeled, n = label(ambient_mask)
    # the pinched void is a component NOT connected to the open-domain
    # ambient above the trench (y < a bit above trench_top at the gap
    # center is now covered; ambient above the wafer entirely is a
    # separate, much larger component touching the domain top edge).
    top_row_labels = set(labeled[0, :]) - {0}
    void_labels = [l for l in range(1, n + 1) if l not in top_row_labels]
    assert void_labels, "expected an enclosed ambient void, found none"
    void_area = sum(np.sum(labeled == l) for l in void_labels) * out.dx * out.dy
    assert void_area > 0.0
    print(f"S2 pinch-off void area: {void_area:.4e}")


# ----------------------------------------------------------------------
#  isotropic undercut -- a real SiO2 hard-mask cap (actual geometry, not
#  a special-cased mask argument -- see etch_isotropic's own docstring
#  for why a raw column-position mask does NOT produce real undercut).
# ----------------------------------------------------------------------
def test_isotropic_etch_undercut_matches_depth_to_grid_resolution():
    Nx, Ny = 200, 100
    ls = LevelSet2D(x0=0.0, x1=1.0, Nx=Nx, y0=0.0, y1=0.5, Ny=Ny,
                     materials=("silicon", "sio2", "ambient"))
    X, Y = ls.X, ls.Y
    # silicon fills y>=0.2 everywhere (the bulk wafer); an SiO2 cap sits
    # directly on top of silicon for x<0.5 between y=0 (the wafer
    # surface plane) and y=0.2; for x>=0.5 that same slab is just open
    # ambient (no cap), exposing silicon's true top at y=0.2 directly.
    cap_bottom = 0.2
    silicon_top = 0.2
    is_cap = (X < 0.5) & (Y < cap_bottom)
    is_silicon = (Y >= silicon_top)
    ls.phi["sio2"] = np.where(is_cap, -1.0, 1.0)
    ls.phi["silicon"] = np.where(is_silicon, -1.0, 1.0)
    ls.phi["ambient"] = np.where(is_cap | is_silicon, 1.0, -1.0)
    ls = project(ls)

    depth = 0.06
    out = etch_isotropic(ls, "silicon", depth_um=depth, rate_um_s=1.0)

    # Per-column retreat depth Y_c(x) - silicon_top (0 where untouched,
    # up to the full achieved open-area depth where fully exposed).
    # Probing a single FIXED row is degenerate here: at the maximum
    # achieved depth, every column's own crossing is AT OR SHALLOWER
    # than that row, so the whole row reads "silicon" trivially except
    # exactly at the open interface -- not a meaningful undercut probe.
    x, y = out.x, out.y
    phi = out.phi["silicon"]
    col_depth = np.full(x.shape, np.nan)
    for i in range(x.size):
        col = phi[:, i]
        idxs = np.where(np.diff(np.sign(col)) != 0)[0]
        if idxs.size:
            k = idxs[0]
            y_c = y[k] - col[k] * (y[k + 1] - y[k]) / (col[k + 1] - col[k])
            col_depth[i] = y_c - silicon_top

    achieved_depth = np.nanmax(col_depth)
    # undercut length: how far under the cap (x<0.5) the retreat depth
    # is still at least half the fully-open depth -- the standard
    # "50% point" measure of a lateral etch-undercut transition.
    half = 0.5 * achieved_depth
    under_cap = (x < 0.5) & ~np.isnan(col_depth) & (col_depth >= half)
    assert np.any(under_cap), "no undercut penetration detected at all"
    x_edge = x[under_cap].min()
    undercut = 0.5 - x_edge
    err = abs(undercut - achieved_depth)
    print(f"S2 undercut: {undercut:.4e}, achieved depth: {achieved_depth:.4e}, err: {err:.4e}")
    assert err < 5 * out.dx


# ----------------------------------------------------------------------
#  directional etch removes nothing on a vertical wall
# ----------------------------------------------------------------------
def test_directional_etch_removes_nothing_on_a_vertical_wall():
    Nx, Ny = 80, 80
    ls = _grid(Nx=Nx, Ny=Ny)
    X, Y = ls.X, ls.Y
    ls.phi["silicon"] = X - 0.5   # silicon for x<0.5: a purely VERTICAL wall
    ls.phi["ambient"] = 0.5 - X
    ls = project(ls)

    out = etch_directional(ls, "silicon", depth_um=0.1, direction=(0.0, -1.0), rate_um_s=1.0)
    diff = np.max(np.abs(out.phi["silicon"] - ls.phi["silicon"]))
    print(f"S2 directional-etch vertical-wall max|dphi|: {diff:.4e}")
    assert diff < 1e-9


# ----------------------------------------------------------------------
#  a re-entrant profile is lossy for a height-field view
# ----------------------------------------------------------------------
def test_conformal_deposit_into_trench_is_lossy_for_a_height_view():
    Nx, Ny = 160, 160
    L = 1.0
    ls = LevelSet2D(x0=0.0, x1=L, Nx=Nx, y0=0.0, y1=L, Ny=Ny,
                     materials=("silicon", "sio2", "ambient"))
    X, Y = ls.X, ls.Y
    gap_lo, gap_hi = 0.4, 0.6
    trench_top = 0.3
    in_trench = (X > gap_lo) & (X < gap_hi) & (Y < trench_top)
    ls.phi["silicon"] = np.where(in_trench, 1.0, -1.0)
    ls.phi["ambient"] = np.where(in_trench, -1.0, 1.0)
    ls.phi["sio2"] = np.full((Ny, Nx), 5.0)
    ls = project(ls)

    out = deposit_conformal(ls, "sio2", thickness_um=0.03, rate_um_s=1.0)

    col = np.argmin(np.abs(out.x - 0.5))   # center of the trench
    owners = []
    prev = None
    mat_idx = out.material_map()
    for row in range(Ny):
        m = out.materials[mat_idx[row, col]]
        if m != prev:
            owners.append(m)
            prev = m
    print(f"S2 trench column material sequence (top->bottom): {owners}")
    # a single scalar surface height per column can encode exactly ONE
    # transition; a genuinely re-entrant profile shows more than one
    # material transition down this column (sio2 coats the sidewall
    # near the top of the trench, ambient still open below it).
    assert len(owners) > 2, (
        f"expected >2 material segments down the trench column "
        f"(height-field-incompatible), got {owners}"
    )


# ----------------------------------------------------------------------
#  advance_front cannot overflow into a third material's territory:
#  erosion is bounded by the receding material's own real extent, so a
#  thin pocket saturates (fully consumed) instead of overrunning
#  whatever lies beyond it.
# ----------------------------------------------------------------------
def test_advance_front_saturates_instead_of_overrunning_a_third_material():
    Nx, Ny = 60, 60
    ls = LevelSet2D(x0=0.0, x1=1.0, Nx=Nx, y0=0.0, y1=1.0, Ny=Ny,
                     materials=("silicon", "sio2", "ambient"))
    X, Y = ls.X, ls.Y
    # three horizontal bands: silicon (bottom), ambient (middle, thin),
    # sio2 (top). A grossly oversized V "eroding" the thin ambient band
    # to grow silicon must consume ambient entirely and STOP there --
    # it must never touch sio2's territory, no matter how large V is.
    ls.phi["silicon"] = Y - 0.3
    ls.phi["ambient"] = np.maximum(0.3 - Y, Y - 0.35)
    ls.phi["sio2"] = 0.35 - Y
    ls = project(ls)
    sio2_before = ls.phi["sio2"].copy()
    sio2_owned_before = ls.material_map() == ls.materials.index("sio2")

    out = advance_front(ls, receding="ambient", growing="silicon", V=1.0,
                         t_total=1.0, cfl=0.4)

    mat_idx = out.material_map()
    sio2_owned_after = mat_idx == out.materials.index("sio2")
    ambient_owned_after = mat_idx == out.materials.index("ambient")
    assert not np.any(ambient_owned_after), "ambient should be fully consumed"
    assert np.array_equal(sio2_owned_before, sio2_owned_after), (
        "sio2's territory must be untouched regardless of V's size"
    )


# ----------------------------------------------------------------------
#  regression: S1 is untouched
# ----------------------------------------------------------------------
def test_regression_s1_still_passes():
    import subprocess
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for f in ("test_m23_process2d.py", "test_m35_s1_levelset.py"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", os.path.join("tests", f), "-q"],
            cwd=repo_root, capture_output=True, text=True, timeout=180,
        )
        assert result.returncode == 0, f"{f} failed:\n{result.stdout}\n{result.stderr}"
