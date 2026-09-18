"""M35-S5/S6 direct-meshing gap: tetrahedralize a 3D level set's ACTUAL
geometry directly (marching cubes + tetgen), not by extruding
process2d's 2D output the way gmsh_finfet3d.py does. See
pytcad/M35-3D-PROCESS-PLAN.md section 18.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.levelset3d import LevelSet3D, project3d, etch_isotropic3d, deposit_conformal3d
from pytcad.levelset3d_mesh import build_tet_mesh_from_levelset3d

pytest.importorskip("tetgen")
pytest.importorskip("skimage")


def _tet_volume_sum(nodes, tets):
    p = nodes[tets]
    v = np.einsum("ij,ij->i", p[:, 1] - p[:, 0], np.cross(p[:, 2] - p[:, 0], p[:, 3] - p[:, 0]))
    return np.sum(np.abs(v)) / 6.0


def _sphere_ls(Nx=40, Ny=40, Nz=40, r=0.25):
    ls = LevelSet3D(x0=0.0, x1=1.0, Nx=Nx, y0=0.0, y1=1.0, Ny=Ny,
                     z0=0.0, z1=1.0, Nz=Nz, materials=("silicon", "ambient"))
    D = np.sqrt((ls.X - 0.5) ** 2 + (ls.Y - 0.5) ** 2 + (ls.Z - 0.5) ** 2)
    ls.phi["silicon"] = D - r
    ls.phi["ambient"] = r - D
    return project3d(ls)


def test_tet_mesh_volume_matches_analytic_sphere():
    r = 0.25
    ls = _sphere_ls(r=r)
    m = build_tet_mesh_from_levelset3d(ls, solid_materials=["silicon"])
    vol = _tet_volume_sum(m.nodes, m.tets)
    expected = 4.0 / 3.0 * np.pi * r ** 3
    rel_err = abs(vol - expected) / expected
    print(f"S5e tet mesh volume: sim={vol:.6e}, analytic={expected:.6e}, rel_err={rel_err:.4e}")
    assert rel_err < 0.01
    assert set(m.volume_tags) == {"silicon"}
    # per-tet-centroid classification (see levelset3d_mesh.py's own
    # honesty clause) misclassifies a small VOLUME of thin boundary-
    # sliver tets whose centroid rounds to the "just outside" grid
    # point -- checked as a volume fraction (the physically meaningful
    # measure), not exact tet-count equality
    si_vol = _tet_volume_sum(m.nodes, m.tets[m.volume_tags["silicon"]])
    frac = si_vol / vol
    print(f"S5e sole-material classified volume fraction: {frac:.4f}")
    assert frac > 0.95, "with only one solid material, nearly all tet VOLUME should classify as it"


def test_tet_mesh_region_tags_split_correctly_two_materials():
    """A slab of silicon capped by a thinner sio2 layer, both meshed as
    one union solid -- region tags (by tet centroid) must split into
    roughly the right volume fraction for each material."""
    Nx, Ny, Nz = 30, 60, 30
    ls = LevelSet3D(x0=0.0, x1=1.0, Nx=Nx, y0=0.0, y1=1.0, Ny=Ny,
                     z0=0.0, z1=1.0, Nz=Nz, materials=("silicon", "sio2", "ambient"))
    y_si, y_ox_top = 0.6, 0.4   # sio2 from 0.4 to 0.6, silicon below 0.6, ambient above 0.4
    in_ox = (ls.Y >= y_ox_top) & (ls.Y < y_si)
    ls.phi["sio2"] = np.where(in_ox, -1.0, 1.0)
    ls.phi["silicon"] = np.where(ls.Y >= y_si, -1.0, 1.0)
    ls.phi["ambient"] = np.where(ls.Y < y_ox_top, -1.0, 1.0)
    ls = project3d(ls)

    m = build_tet_mesh_from_levelset3d(ls, solid_materials=["silicon", "sio2"])
    idx_si_tets = m.volume_tags["silicon"]
    idx_ox_tets = m.volume_tags["sio2"]
    assert len(idx_si_tets) + len(idx_ox_tets) == m.n_tets()

    vol_si = _tet_volume_sum(m.nodes, m.tets[idx_si_tets])
    vol_ox = _tet_volume_sum(m.nodes, m.tets[idx_ox_tets])
    expected_si = (1.0 - y_si) * 1.0 * 1.0   # depth (1-y_si) over full x,z
    expected_ox = (y_si - y_ox_top) * 1.0 * 1.0
    rel_err_si = abs(vol_si - expected_si) / expected_si
    rel_err_ox = abs(vol_ox - expected_ox) / expected_ox
    print(f"S5e region split: si vol={vol_si:.4f} (expected {expected_si:.4f}, err {rel_err_si:.3f}), "
          f"ox vol={vol_ox:.4f} (expected {expected_ox:.4f}, err {rel_err_ox:.3f})")
    # per-tet-centroid classification is a real, disclosed approximation
    # (see levelset3d_mesh.py's own honesty clause) -- tolerance is
    # consistent with roughly one grid cell of quantization, not tighter
    assert rel_err_si < 0.1
    assert rel_err_ox < 0.15


def test_contact_planes_tag_only_domain_boundary_faces():
    ls = _sphere_ls()
    # the sphere doesn't touch any domain boundary plane at all, so a
    # contact request on x=0 must come back EMPTY, not spuriously match
    # curved interior interface faces
    m = build_tet_mesh_from_levelset3d(ls, solid_materials=["silicon"],
                                        contact_planes={"x0_contact": ("x", 0.0)})
    assert m.face_tags["x0_contact"].shape[0] == 0


def test_contact_planes_tag_real_boundary_faces():
    """A flat wafer slab DOES touch the y1 domain boundary (its own
    deepest silicon extends to the bottom of the grid) -- that contact
    must be non-empty."""
    Nx, Ny, Nz = 20, 40, 20
    ls = LevelSet3D(x0=0.0, x1=1.0, Nx=Nx, y0=0.0, y1=1.0, Ny=Ny,
                     z0=0.0, z1=1.0, Nz=Nz, materials=("silicon", "ambient"))
    silicon_top = 0.4
    ls.phi["silicon"] = silicon_top - ls.Y
    ls.phi["ambient"] = ls.Y - silicon_top
    ls = project3d(ls)

    m = build_tet_mesh_from_levelset3d(ls, solid_materials=["silicon"],
                                        contact_planes={"bottom_contact": ("y", ls.y1)})
    assert m.face_tags["bottom_contact"].shape[0] > 0


@pytest.mark.slow
def test_direct_mesh_solver_handoff_converges():
    """The mesh from `build_tet_mesh_from_levelset3d` must be usable by
    the SAME solver-handoff functions `gmsh_finfet3d.py`'s own path
    uses -- a real Poisson equilibrium solve, not just geometry
    bookkeeping. Mirrors that module's own
    `test_finfet_mesh3d_from_process2d_equilibrium_solve_converges`
    gate, on a level-set-derived mesh instead of a process2d-extruded
    one."""
    import warnings
    from pytcad.unstructured_assembly3d import (
        build_unstructured_stencil3d, build_edge_flux_geometry3d,
    )
    from pytcad.unstructured_dd3d import solve_poisson_equilibrium3d
    from pytcad.materials import SILICON

    Nx, Ny, Nz = 24, 30, 16
    ls = LevelSet3D(x0=0.0, x1=2.0e-4, Nx=Nx, y0=0.0, y1=1.0e-4, Ny=Ny,
                     z0=0.0, z1=1.0e-4, Nz=Nz, materials=("silicon", "ambient"))
    silicon_top = 0.3e-4
    ls.phi["silicon"] = silicon_top - ls.Y
    ls.phi["ambient"] = ls.Y - silicon_top
    ls = project3d(ls)

    m = build_tet_mesh_from_levelset3d(
        ls, solid_materials=["silicon"],
        contact_planes={"left_contact": ("x", 0.0), "right_contact": ("x", ls.x1)})
    assert m.face_tags["left_contact"].shape[0] > 0
    assert m.face_tags["right_contact"].shape[0] > 0

    # a simple n-type doping so equilibrium is well-defined
    C_phys = np.full(m.n_nodes(), 1e17)
    edges, node_vols = build_unstructured_stencil3d(m.nodes, m.tets)
    edges, trans = build_edge_flux_geometry3d(m.nodes, m.tets, edges)
    contacts = {"left": m.face_tags["left_contact"], "right": m.face_tags["right_contact"]}

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        psi, scale = solve_poisson_equilibrium3d(
            m.nodes, m.tets, edges, node_vols, trans, C_phys, contacts, material=SILICON)
    assert np.all(np.isfinite(psi))
    print(f"S5e solver handoff: psi range [{psi.min():.4e}, {psi.max():.4e}], converged with no warnings")


def test_direct_mesh_follows_a_real_undercut_not_a_staircase():
    """The whole point of direct meshing: a REAL undercut profile
    (curved, from S1/S2's own advance_front) must show up as node
    positions that are NOT snapped to a small set of staircase-aligned
    x-values -- checked directly by counting distinct x-coordinates
    among boundary-surface nodes near the mask edge."""
    Nx, Ny, Nz = 80, 60, 8
    ls = LevelSet3D(x0=0.0, x1=1.0, Nx=Nx, y0=0.0, y1=0.5, Ny=Ny,
                     z0=0.0, z1=0.1, Nz=Nz, materials=("silicon", "resist", "ambient"))
    silicon_top = 0.2
    ls.phi["silicon"] = silicon_top - ls.Y
    ls.phi["ambient"] = ls.Y - silicon_top
    ls.phi["resist"] = np.full((Nx, Ny, Nz), 10.0)
    ls = project3d(ls)
    masked = deposit_conformal3d(ls, "resist", thickness_um=0.15, rate_um_s=1.0,
                                  windows=[(0.0, 0.5, 0.0, 0.1)])
    out = etch_isotropic3d(masked, "silicon", depth_um=0.08, rate_um_s=1.0)

    m = build_tet_mesh_from_levelset3d(out, solid_materials=["silicon"])
    # nodes near the mask edge (x in [0.35, 0.5]) at a depth inside the
    # undercut band -- a staircase extrusion would only ever place
    # surface vertices at the grid's own x-sample coordinates; a direct
    # marching-cubes+tetgen mesh interpolates the true zero-crossing
    near_edge = (m.nodes[:, 0] > 0.35) & (m.nodes[:, 0] < 0.5) & \
                (m.nodes[:, 1] > silicon_top) & (m.nodes[:, 1] < silicon_top + 0.08)
    xs = np.unique(np.round(m.nodes[near_edge, 0], 6))
    print(f"S5e undercut region: {xs.size} distinct x-coordinates among {np.count_nonzero(near_edge)} nodes")
    assert xs.size > 5, "a real curved undercut surface should show many distinct x-values, not a staircase snap"
