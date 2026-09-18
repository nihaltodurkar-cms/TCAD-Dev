"""M35-S5/S6 smooth-geometry gap: a genuinely continuous/smooth 3D
surface extracted from the level set (marching cubes), as opposed to
the piecewise-constant staircase `gmsh_finfet3d.py` builds from
process2d's 2D string-model output. See
pytcad/M35-3D-PROCESS-PLAN.md section 18.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.levelset3d import LevelSet3D, project3d, marching_cubes_surface, etch_isotropic3d, deposit_conformal3d


def _mesh_volume(verts, faces):
    """Signed volume of a closed triangle mesh via the divergence
    theorem -- used only as an independent geometric check here, not
    reused by the tet-meshing module (which gets its own volume
    straight from the generated tets)."""
    v0 = verts[faces[:, 0]]
    v1 = verts[faces[:, 1]]
    v2 = verts[faces[:, 2]]
    return np.sum(np.einsum("ij,ij->i", v0, np.cross(v1, v2))) / 6.0


def test_marching_cubes_reproduces_analytic_sphere_volume():
    Nx, Ny, Nz = 40, 40, 40
    ls = LevelSet3D(x0=0.0, x1=1.0, Nx=Nx, y0=0.0, y1=1.0, Ny=Ny,
                     z0=0.0, z1=1.0, Nz=Nz, materials=("silicon", "ambient"))
    cx, cy, cz, r = 0.5, 0.5, 0.5, 0.25
    D = np.sqrt((ls.X - cx) ** 2 + (ls.Y - cy) ** 2 + (ls.Z - cz) ** 2)
    ls.phi["silicon"] = D - r
    ls.phi["ambient"] = r - D
    ls = project3d(ls)

    verts, faces = marching_cubes_surface(ls, "silicon")
    vol = abs(_mesh_volume(verts, faces))
    expected = 4.0 / 3.0 * np.pi * r ** 3
    rel_err = abs(vol - expected) / expected
    print(f"S5d marching-cubes sphere volume: sim={vol:.6e}, analytic={expected:.6e}, rel_err={rel_err:.4e}")
    assert rel_err < 0.01


def test_marching_cubes_surface_is_genuinely_smooth_not_staircase():
    """The surface normal direction should vary CONTINUOUSLY around a
    curved (isotropically-undercut) feature -- a staircase/voxel-aligned
    surface would instead show normals clustered at only the 3
    coordinate-axis directions (+/-x, +/-y, +/-z). This is the actual
    claim the smooth-geometry gap is about, checked directly rather
    than assumed from the sphere-volume gate alone.

    A flat, unmasked isotropic etch stays perfectly planar (no
    curvature at all -- confirmed directly, an earlier version of this
    test used exactly that and got frac_off_axis=0.0), so a real mask
    edge is used here specifically to produce a rounded, genuinely
    curved undercut corner."""
    Nx, Ny, Nz = 80, 60, 10
    ls = LevelSet3D(x0=0.0, x1=1.0, Nx=Nx, y0=0.0, y1=0.5, Ny=Ny,
                     z0=0.0, z1=0.15, Nz=Nz, materials=("silicon", "resist", "ambient"))
    silicon_top = 0.2
    ls.phi["silicon"] = silicon_top - ls.Y
    ls.phi["ambient"] = ls.Y - silicon_top
    ls.phi["resist"] = np.full((Nx, Ny, Nz), 10.0)
    ls = project3d(ls)
    masked = deposit_conformal3d(ls, "resist", thickness_um=0.15, rate_um_s=1.0,
                                  windows=[(0.0, 0.5, 0.0, 0.15)])
    # isotropic etch of the OPEN half (x>0.5) undercuts under the mask
    # edge at x=0.5, rounding that corner
    out = etch_isotropic3d(masked, "silicon", depth_um=0.08, rate_um_s=1.0)

    verts, faces = marching_cubes_surface(out, "silicon")
    v0 = verts[faces[:, 0]]; v1 = verts[faces[:, 1]]; v2 = verts[faces[:, 2]]
    n = np.cross(v1 - v0, v2 - v0)
    nmag = np.linalg.norm(n, axis=1, keepdims=True)
    n = n / np.where(nmag > 1e-15, nmag, 1.0)

    # a purely axis-aligned (staircase) surface would have every face
    # normal within numerical noise of exactly one of the 6 axis
    # directions; a genuinely curved surface has a wide SPREAD of
    # normal directions in between
    axis_dirs = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]], dtype=float)
    best_axis_alignment = np.max(n @ axis_dirs.T, axis=1)   # cos(angle) to nearest axis, per face
    frac_off_axis = np.mean(best_axis_alignment < 0.99)
    print(f"S5d smoothness: fraction of faces with normal >8 deg off any coordinate axis = {frac_off_axis:.3f}")
    # a flat, unmasked etch (no undercut at all) measures EXACTLY 0.0 here
    # (confirmed directly) -- any clearly-nonzero fraction demonstrates
    # real curvature the staircase path cannot represent; most of this
    # geometry's surface is still flat planes away from the one rounded
    # mask-edge corner, so the bar is "clearly present", not "dominant"
    assert frac_off_axis > 0.1, "surface should have a genuine spread of normal directions, not be voxel-staircase-aligned"


def test_marching_cubes_requires_a_real_crossing():
    ls = LevelSet3D(x0=0.0, x1=1.0, Nx=10, y0=0.0, y1=1.0, Ny=10,
                     z0=0.0, z1=1.0, Nz=10, materials=("silicon", "ambient"))
    # silicon phi never crosses zero -- entirely "far" positive
    with pytest.raises(ValueError):
        marching_cubes_surface(ls, "silicon")
