"""M35-S5 acceptance gates: the level-set CORE (representation,
advection, deposit/etch topology) lifted to 3D. See
pytcad/M35-3D-PROCESS-PLAN.md section 6. Scope note: this pass ports
S1+S2 only (oxidation/silicidation/epitaxy/CMP-in-3D are deferred, a
cost-driven cut recorded in the plan doc, not an oversight).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from pytcad.levelset2d import LevelSet2D, project, advance_front, advance_material
from pytcad.levelset3d import (
    LevelSet3D, project3d, advance_front3d, advance_material3d,
    deposit_conformal3d, etch_isotropic3d, etch_directional3d,
    deposit_epitaxial3d, planarize3d,
)


def _grid2d(Nx=60, Ny=60):
    ls = LevelSet2D(x0=0.0, x1=1.0, Nx=Nx, y0=0.0, y1=1.0, Ny=Ny,
                     materials=("silicon", "sio2", "ambient"))
    silicon_top = 0.4
    ls.phi["silicon"] = silicon_top - ls.Y
    ls.phi["ambient"] = ls.Y - silicon_top
    ls.phi["sio2"] = np.full((Ny, Nx), 10.0)
    return project(ls)


def _grid3d_z_invariant(Nx=60, Ny=60, Nz=3):
    ls3 = LevelSet3D(x0=0.0, x1=1.0, Nx=Nx, y0=0.0, y1=1.0, Ny=Ny,
                      z0=0.0, z1=0.3, Nz=Nz,
                      materials=("silicon", "sio2", "ambient"))
    silicon_top = 0.4
    ls3.phi["silicon"] = silicon_top - ls3.Y
    ls3.phi["ambient"] = ls3.Y - silicon_top
    ls3.phi["sio2"] = np.full((Nx, Ny, Nz), 10.0)
    return project3d(ls3)


# ----------------------------------------------------------------------
#  G1 (load-bearing, 4d.4): z-invariant 3D reproduces 2D to fp noise
# ----------------------------------------------------------------------
def test_advance_front3d_zinvariant_reduces_to_2d():
    ls2 = _grid2d()
    ls3 = _grid3d_z_invariant()

    out2 = advance_front(ls2, receding="ambient", growing="sio2", V=1.0, t_total=0.05)
    out3 = advance_front3d(ls3, receding="ambient", growing="sio2", V=1.0, t_total=0.05)

    for name in ("silicon", "sio2", "ambient"):
        for k in range(out3.Nz):
            slice_k = out3.phi[name][:, :, k].T   # (Nx,Ny) -> (Ny,Nx)
            diff = np.max(np.abs(slice_k - out2.phi[name]))
            assert diff < 1e-10, f"{name!r} z-slice {k} diverges from 2D by {diff:.3e}"


def test_advance_material3d_zinvariant_reduces_to_2d():
    # "sio2" is a degenerate placeholder here (owns nothing in either
    # grid) -- its "far" constant depends on the FULL bounding box
    # diagonal (levelset2d._far_value / levelset3d._far_value3d), which
    # differs between a 2D and a 3D domain even when z is uninvolved, so
    # comparing a material that owns nothing is not a meaningful
    # reduction check. "silicon" already owns real territory with a
    # genuine signed-distance gradient, so growing IT is the real test.
    ls2 = _grid2d()
    ls3 = _grid3d_z_invariant()
    out2 = advance_material(ls2, "silicon", V=1.0, t_total=0.03)
    out3 = advance_material3d(ls3, "silicon", V=1.0, t_total=0.03)
    for name in ("silicon", "ambient"):
        for k in range(out3.Nz):
            diff = np.max(np.abs(out3.phi[name][:, :, k].T - out2.phi[name]))
            assert diff < 1e-10, f"{name!r} z-slice {k} diverges from 2D by {diff:.3e}"
    idx_sio2_2 = out2.materials.index("sio2")
    idx_sio2_3 = out3.materials.index("sio2")
    assert not np.any(out2.material_map() == idx_sio2_2)
    assert not np.any(out3.material_map() == idx_sio2_3)


def test_etch_isotropic3d_zinvariant_reduces_to_2d():
    # see test_advance_material3d's comment: "sio2" owns nothing in
    # either grid, so its placeholder phi (domain-diagonal-dependent) is
    # excluded from the strict comparison -- only ownership emptiness is
    # checked for it.
    from pytcad.levelset2d import etch_isotropic
    ls2 = _grid2d()
    ls3 = _grid3d_z_invariant()
    out2 = etch_isotropic(ls2, "silicon", depth_um=0.05, rate_um_s=1.0)
    out3 = etch_isotropic3d(ls3, "silicon", depth_um=0.05, rate_um_s=1.0)
    for name in ("silicon", "ambient"):
        for k in range(out3.Nz):
            diff = np.max(np.abs(out3.phi[name][:, :, k].T - out2.phi[name]))
            assert diff < 1e-10, f"{name!r} z-slice {k} diverges from 2D by {diff:.3e}"
    idx_sio2_2 = out2.materials.index("sio2")
    idx_sio2_3 = out3.materials.index("sio2")
    assert not np.any(out2.material_map() == idx_sio2_2)
    assert not np.any(out3.material_map() == idx_sio2_3)


def test_deposit_conformal3d_zinvariant_reduces_to_2d():
    from pytcad.levelset2d import deposit_conformal
    ls2 = _grid2d()
    ls3 = _grid3d_z_invariant()
    out2 = deposit_conformal(ls2, "sio2", thickness_um=0.05, rate_um_s=1.0)
    out3 = deposit_conformal3d(ls3, "sio2", thickness_um=0.05, rate_um_s=1.0)
    for name in ("silicon", "sio2", "ambient"):
        for k in range(out3.Nz):
            diff = np.max(np.abs(out3.phi[name][:, :, k].T - out2.phi[name]))
            assert diff < 1e-10, f"{name!r} z-slice {k} diverges from 2D by {diff:.3e}"


# ----------------------------------------------------------------------
#  G3: z is a real, load-bearing axis (a finite z-strip mask changes
#  the result inside vs. outside the strip)
# ----------------------------------------------------------------------
def test_z_localized_mask_produces_z_dependent_undercut():
    """Depth note: `advance_front3d`'s masked-erosion exposure test
    inherits the SAME latent numerical limitation already disclosed for
    `advance_front` (2D, S2/S4 landing notes): lateral exposure can
    propagate up to one grid cell per CFL substep regardless of that
    substep's actual physical dt, so a deep enough etch (more substeps)
    over-propagates protection loss even to points that should be
    physically out of reach. Confirmed directly at this grid: depth=0.02
    stays within the safe regime (protection holds at a probe 0.4 units
    from the nearest x-edge and 0.2 units from the nearest z-edge of the
    mask strip); depth=0.04+ does not. This is a pre-existing property
    inherited from the already-known 2D limitation, not new to 3D --
    the test uses a depth known to be safe, the same way S4's own
    patterned-mask undercut gate reuses S2's known-good grid scale."""
    Nx, Ny, Nz = 100, 60, 40
    ls = LevelSet3D(x0=0.0, x1=1.0, Nx=Nx, y0=0.0, y1=0.5, Ny=Ny,
                     z0=0.0, z1=1.0, Nz=Nz,
                     materials=("silicon", "resist", "ambient"))
    X, Y, Z = ls.X, ls.Y, ls.Z
    silicon_top = 0.2
    # a resist cap only for x<0.5 AND 0.3<=z<=0.7 (a finite strip along z)
    is_cap = (X < 0.5) & (Y < silicon_top) & (Z >= 0.3) & (Z <= 0.7)
    is_silicon = (Y >= silicon_top)
    ls.phi["resist"] = np.where(is_cap, -1.0, 1.0)
    ls.phi["silicon"] = np.where(is_silicon, -1.0, 1.0)
    ls.phi["ambient"] = np.where(is_cap | is_silicon, 1.0, -1.0)
    ls = project3d(ls)

    depth = 0.02
    out = etch_isotropic3d(ls, "silicon", depth_um=depth, rate_um_s=1.0)
    mat_idx = out.material_map()
    idx_si = out.materials.index("silicon")

    # probe deep under the mask (far from BOTH the x-edge at 0.5 and the
    # z-edges at 0.3/0.7), just below the original surface
    ix = np.argmin(np.abs(out.x - 0.1))
    iy = np.argmin(np.abs(out.y - (silicon_top + 0.005)))
    iz_in_strip = np.argmin(np.abs(out.z - 0.5))
    iz_out_strip = np.argmin(np.abs(out.z - 0.9))

    protected = mat_idx[ix, iy, iz_in_strip] == idx_si
    exposed = mat_idx[ix, iy, iz_out_strip] == idx_si
    print(f"S5 z-dependence: protected(in-strip)={protected}, still-silicon(out-of-strip)={exposed}")
    assert protected, "silicon under the mask, at a z INSIDE the masked strip, should remain"
    assert not exposed, "silicon at the same (x,y) but z OUTSIDE the masked strip should be etched"


# ----------------------------------------------------------------------
#  G4: multi-material ownership sanity in 3D
# ----------------------------------------------------------------------
def test_material_map3d_partitions_completely():
    ls = _grid3d_z_invariant()
    mat_idx = ls.material_map()
    assert mat_idx.shape == (ls.Nx, ls.Ny, ls.Nz)
    assert np.all((mat_idx >= 0) & (mat_idx < len(ls.materials)))


# ----------------------------------------------------------------------
#  Part A additions: etch_directional3d, deposit_epitaxial3d, planarize3d
# ----------------------------------------------------------------------
def test_etch_directional3d_zinvariant_reduces_to_2d():
    from pytcad.levelset2d import etch_directional
    ls2 = _grid2d()
    ls3 = _grid3d_z_invariant()
    out2 = etch_directional(ls2, "silicon", depth_um=0.05, direction=(0.0, -1.0), rate_um_s=1.0)
    out3 = etch_directional3d(ls3, "silicon", depth_um=0.05, direction=(0.0, -1.0, 0.0), rate_um_s=1.0)
    for name in ("silicon", "ambient"):
        for k in range(out3.Nz):
            diff = np.max(np.abs(out3.phi[name][:, :, k].T - out2.phi[name]))
            assert diff < 1e-10, f"{name!r} z-slice {k} diverges from 2D by {diff:.3e}"


def test_etch_directional3d_removes_nothing_on_a_vertical_wall():
    Nx, Ny, Nz = 60, 60, 4
    ls = LevelSet3D(x0=0.0, x1=1.0, Nx=Nx, y0=0.0, y1=1.0, Ny=Ny,
                     z0=0.0, z1=0.3, Nz=Nz, materials=("silicon", "ambient"))
    ls.phi["silicon"] = ls.X - 0.5
    ls.phi["ambient"] = 0.5 - ls.X
    ls = project3d(ls)
    out = etch_directional3d(ls, "silicon", depth_um=0.1, direction=(0.0, -1.0, 0.0), rate_um_s=1.0)
    diff = np.max(np.abs(out.phi["silicon"] - ls.phi["silicon"]))
    assert diff < 1e-9


def test_deposit_epitaxial3d_none_reduces_exactly_to_conformal():
    ls3a = _grid3d_z_invariant()
    ls3b = _grid3d_z_invariant()
    out_a = deposit_conformal3d(ls3a, "sio2", thickness_um=0.05, rate_um_s=1.0)
    out_b = deposit_epitaxial3d(ls3b, "sio2", thickness_um=0.05, rate_um_s=1.0)
    for name in ("silicon", "sio2", "ambient"):
        assert np.array_equal(out_a.phi[name], out_b.phi[name])


def test_planarize3d_clears_material_above_cut_line():
    _UM_TO_CM = 1.0e-4
    Nx, Ny, Nz = 40, 80, 4
    ls = LevelSet3D(x0=0.0, x1=40.0 * _UM_TO_CM, Nx=Nx,
                     y0=0.0, y1=2.0 * _UM_TO_CM, Ny=Ny,
                     z0=0.0, z1=10.0 * _UM_TO_CM, Nz=Nz,
                     materials=("silicon", "ambient"))
    silicon_top_um = 0.8
    silicon_top = silicon_top_um * _UM_TO_CM
    ls.phi["silicon"] = silicon_top - ls.Y
    ls.phi["ambient"] = ls.Y - silicon_top
    ls = project3d(ls)

    y_cmp_um = 0.4   # shallower than silicon_top_um=0.8
    out = planarize3d(ls, y_cmp_um=y_cmp_um)
    idx_amb = out.materials.index("ambient")
    mat_idx = out.material_map()
    above = ls.Y < y_cmp_um * _UM_TO_CM
    assert np.all(mat_idx[above] == idx_amb)
    below = ~above
    assert np.array_equal(mat_idx[below], ls.material_map()[below])
