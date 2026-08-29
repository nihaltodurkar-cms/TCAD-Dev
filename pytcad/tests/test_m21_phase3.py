"""M21 Phase 3: General unstructured 2D + Delaunay FV assembly tests.

These tests exercise the new unstructured mesh path in Device2D, which
accepts gmsh-generated triangular meshes and assembles the box-
integration finite-volume residual/Jacobian on the unstructured mesh.

Gates G1-G8 from M21-PHASE3-MESHING-PLAN.md.
"""
import os
import sys
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import numpy as np
import pytest

# Skip all tests if gmsh is not installed
gmsh = pytest.importorskip("gmsh", reason="gmsh not installed")

from pytcad.mesh import debye_length
from pytcad.device2d import Device2D, DirichletBC, GateBC, Models
from pytcad.mesh2d import Mesh2D


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _build_gmsh_diode(Xj=3.0e-4, Lx=6.0e-4, Ly=2.0e-4):
    """Build a gmsh p-n diode mesh matching the Device2D golden fixture.

    Returns (nodes, triangles, surface_tags, curve_tags) where:
      - nodes: (N, 2) array of (x, y) coordinates in cm
      - triangles: (N_tri, 3) array of node indices
      - surface_tags: dict mapping surface tag -> physical group name
      - curve_tags: dict mapping curve tag -> physical group name
    """
    gmsh.initialize()
    gmsh.model.add("diode2d")
    occ = gmsh.model.occ

    # Build two rectangles (p region: [0, Xj], n region: [Xj, Lx])
    p_rect = occ.addRectangle(0.0, 0.0, 0, Xj, Ly)
    n_rect = occ.addRectangle(Xj, 0.0, 0, Lx - Xj, Ly)
    occ.synchronize()

    # Fragment for conformal mesh across the junction
    out, out_map = occ.fragment([(2, p_rect)], [(2, n_rect)])
    occ.synchronize()

    # Identify surfaces by centroid
    surfaces = gmsh.model.getEntities(2)
    p_tag = n_tag = None
    for dim, tag in surfaces:
        com = gmsh.model.occ.getCenterOfMass(dim, tag)
        if com[0] < Xj:
            p_tag = tag
        else:
            n_tag = tag

    # Physical Groups for regions
    gmsh.model.addPhysicalGroup(2, [p_tag], name="p_region")
    gmsh.model.addPhysicalGroup(2, [n_tag], name="n_region")

    # Contacts: left edge of p, right edge of n
    curves = gmsh.model.getEntities(1)
    left_curve = right_curve = None
    for dim, tag in curves:
        com = gmsh.model.occ.getCenterOfMass(dim, tag)
        if abs(com[0] - 0.0) < 1e-12:
            left_curve = tag
        elif abs(com[0] - Lx) < 1e-12:
            right_curve = tag

    gmsh.model.addPhysicalGroup(1, [left_curve], name="left_contact")
    gmsh.model.addPhysicalGroup(1, [right_curve], name="right_contact")

    # Mesh size: Debye-grounded
    L_D = debye_length(1e16)
    gmsh.model.mesh.field.add("Distance", 1)
    # Junction curve
    junction_curves = [c for d, c in curves
                       if abs(gmsh.model.occ.getCenterOfMass(d, c)[0] - Xj) < 1e-12]
    gmsh.model.mesh.field.setNumbers(1, "CurvesList", junction_curves)
    gmsh.model.mesh.field.add("Threshold", 2)
    gmsh.model.mesh.field.setNumber(2, "InField", 1)
    gmsh.model.mesh.field.setNumber(2, "SizeMin", 0.5 * L_D)
    gmsh.model.mesh.field.setNumber(2, "SizeMax", 2e-5)
    gmsh.model.mesh.field.setNumber(2, "DistMin", 2.0 * L_D)
    gmsh.model.mesh.field.setNumber(2, "DistMax", 15.0 * L_D)
    gmsh.model.mesh.field.setAsBackgroundMesh(2)

    gmsh.model.mesh.generate(2)
    gmsh.model.mesh.setOrder(1)

    # Extract mesh data
    nodes_tags, nodes_coord, _ = gmsh.model.mesh.getNodes()
    nx = len(nodes_tags)
    nodes = np.zeros((nx, 2))
    for i in range(nx):
        nodes[i, 0] = nodes_coord[3*i]
        nodes[i, 1] = nodes_coord[3*i+1]

    # Extract triangles (get all 2D elements)
    etypes, etags, enodes = gmsh.model.mesh.getElements(2)
    tri_conn = []
    for et, tags_, nds in zip(etypes, etags, enodes):
        if et == 2:  # 3-node triangle
            nds = np.asarray(nds).reshape(-1, 3)
            tri_conn.append(nds)
    triangles = np.concatenate(tri_conn, axis=0) if tri_conn else np.zeros((0, 3), dtype=int)

    # Extract Physical Group mappings
    surface_tags = {}
    curve_tags = {}
    for pdim, ptag in gmsh.model.getPhysicalGroups():
        name = gmsh.model.getPhysicalName(pdim, ptag)
        if pdim == 2:
            surface_tags[ptag] = name
        else:
            curve_tags[ptag] = name

    gmsh.finalize()
    return nodes, triangles, surface_tags, curve_tags


def _build_gmsh_diode_mesh_file(Xj=3.0e-4, Lx=6.0e-4, Ly=2.0e-4):
    """Build a gmsh p-n diode and write it to a .msh file.

    Returns the path to the temporary .msh file.
    """
    gmsh.initialize()
    gmsh.model.add("diode2d")
    occ = gmsh.model.occ

    p_rect = occ.addRectangle(0.0, 0.0, 0, Xj, Ly)
    n_rect = occ.addRectangle(Xj, 0.0, 0, Lx - Xj, Ly)
    occ.synchronize()

    out, out_map = occ.fragment([(2, p_rect)], [(2, n_rect)])
    occ.synchronize()

    surfaces = gmsh.model.getEntities(2)
    p_tag = n_tag = None
    for dim, tag in surfaces:
        com = gmsh.model.occ.getCenterOfMass(dim, tag)
        if com[0] < Xj:
            p_tag = tag
        else:
            n_tag = tag

    gmsh.model.addPhysicalGroup(2, [p_tag], name="p_region")
    gmsh.model.addPhysicalGroup(2, [n_tag], name="n_region")

    curves = gmsh.model.getEntities(1)
    left_curve = right_curve = None
    for dim, tag in curves:
        com = gmsh.model.occ.getCenterOfMass(dim, tag)
        if abs(com[0] - 0.0) < 1e-12:
            left_curve = tag
        elif abs(com[0] - Lx) < 1e-12:
            right_curve = tag

    gmsh.model.addPhysicalGroup(1, [left_curve], name="left_contact")
    gmsh.model.addPhysicalGroup(1, [right_curve], name="right_contact")

    L_D = debye_length(1e16)
    gmsh.model.mesh.field.add("Distance", 1)
    junction_curves = [c for d, c in curves
                       if abs(gmsh.model.occ.getCenterOfMass(d, c)[0] - Xj) < 1e-12]
    gmsh.model.mesh.field.setNumbers(1, "CurvesList", junction_curves)
    gmsh.model.mesh.field.add("Threshold", 2)
    gmsh.model.mesh.field.setNumber(2, "InField", 1)
    gmsh.model.mesh.field.setNumber(2, "SizeMin", 0.5 * L_D)
    gmsh.model.mesh.field.setNumber(2, "SizeMax", 2e-5)
    gmsh.model.mesh.field.setNumber(2, "DistMin", 2.0 * L_D)
    gmsh.model.mesh.field.setNumber(2, "DistMax", 15.0 * L_D)
    gmsh.model.mesh.field.setAsBackgroundMesh(2)

    gmsh.model.mesh.generate(2)
    gmsh.model.mesh.setOrder(1)

    tmp = tempfile.NamedTemporaryFile(suffix=".msh", delete=False, prefix="gmsh_test_")
    tmp.close()
    gmsh.write(tmp.name)
    gmsh.finalize()
    return tmp.name


def _build_structured_diode(Nx=60, Ny=20):
    """Build a structured mesh p-n diode matching the gmsh geometry."""
    Lx, Ly, Xj = 6.0e-4, 2.0e-4, 3.0e-4
    x = np.linspace(0, Lx, Nx)
    y = np.linspace(0, Ly, Ny)
    mesh = Mesh2D(x, y)
    doping = np.where(mesh.x < Xj, 1e16, -1e17)  # p on left, n on right
    doping = np.tile(doping[:, np.newaxis], (1, Ny))
    return mesh, doping


# ----------------------------------------------------------------------
# G1: FD-Jacobian on unstructured mesh <= 1e-5
# ----------------------------------------------------------------------
class TestG1FDJacobian:
    def test_unstructured_fd_jacobian_matches_analytic(self):
        """G1: FD-Jacobian on unstructured mesh <= 1e-5 relative error."""
        nodes, triangles, surface_tags, curve_tags = _build_gmsh_diode()

        # Build structured reference for comparison
        struct_mesh, doping = _build_structured_diode()

        # TODO: Create unstructured device and check FD-Jacobian
        pytest.skip("Implementation not yet complete")


# ----------------------------------------------------------------------
# G2: Homojunction equilibrium convergence (tolerance-based, not bit-identity)
# ----------------------------------------------------------------------
class TestG2Homojunction:
    def test_homojunction_equilibrium_converges(self):
        """G2: Homojunction converges at equilibrium; built-in potential
        differs from structured path by < 1e-3 relative error."""
        pytest.skip("Implementation not yet complete")


# ----------------------------------------------------------------------
# G3: Global charge conservation at equilibrium
# ----------------------------------------------------------------------
class TestG3ChargeConservation:
    def test_charge_conservation_at_equilibrium(self):
        """G3: Integrated Poisson residual over all nodes < 1e-10 at
        equilibrium. Verifies edge flux cancellation on shared edges."""
        pytest.skip("Implementation not yet complete")


# ----------------------------------------------------------------------
# G4: Golden parity (structured vs unstructured)
# ----------------------------------------------------------------------
class TestG4GoldenParity:
    def test_golden_parity_diode_0_5V(self):
        """G4: Same diode on unstructured mesh matches structured to
        < 1e-4 relative error on J at 0.5 V."""
        pytest.skip("Implementation not yet complete")


# ----------------------------------------------------------------------
# G5: Physics flags (SRH + Boltzmann)
# ----------------------------------------------------------------------
class TestG5PhysicsFlags:
    def test_physics_flags_srh_boltzmann(self):
        """G5: Unstructured path respects SRH recombination and
        Boltzmann carrier statistics (fd=False) at equilibrium."""
        pytest.skip("Implementation not yet complete")


# ----------------------------------------------------------------------
# G6: Optional dependency
# ----------------------------------------------------------------------
class TestG6OptionalDependency:
    def test_optional_dependency_gmsh_absent(self):
        """G6: When gmsh is not installed, all existing paths work."""
        # This test runs even when gmsh IS installed, to verify the
        # soft-import path. We skip it when gmsh is available because
        # we can't easily uninstall it mid-test.
        pytest.skip("Run separately without gmsh installed")


# ----------------------------------------------------------------------
# G7: Edge orientation consistency
# ----------------------------------------------------------------------
class TestG7EdgeOrientation:
    def test_edge_list_unique_directed_edges(self):
        """G7: Edge list has correct number of unique directed edges."""
        pytest.skip("Implementation not yet complete")

    def test_dual_cell_areas_sum_to_mesh_area(self):
        """G7: Sum of all dual-cell edge areas equals total mesh area."""
        pytest.skip("Implementation not yet complete")


# ----------------------------------------------------------------------
# G8: Mesh quality validation
# ----------------------------------------------------------------------
class TestG8MeshQuality:
    def test_mesh_quality_rejects_bad_mesh(self):
        """G8: load_gmsh_mesh rejects meshes with degenerate triangles."""
        pytest.skip("Implementation not yet complete")


# ----------------------------------------------------------------------
# Additional tests for gmsh_mesh.py components
# ----------------------------------------------------------------------
class TestGmshMeshLoader:
    def test_gmsh_mesh_loads_valid_file(self):
        """Verify gmsh mesh loader can parse a valid .msh file."""
        msh_path = _build_gmsh_diode_mesh_file()
        try:
            # TODO: load_gmsh_mesh(msh_path)
            pytest.skip("load_gmsh_mesh not yet implemented")
        finally:
            os.unlink(msh_path)

    def test_gmsh_mesh_rejects_degenerate_triangles(self):
        """Verify gmsh mesh loader rejects meshes with degenerate triangles."""
        pytest.skip("Implementation not yet complete")


class TestRegionResolver:
    def test_region_resolver_maps_single_surface(self):
        """Verify single-surface region resolution with doping evaluation."""
        pytest.skip("Implementation not yet complete")

    def test_region_resolver_rejects_untagged_surface(self):
        """Verify untagged surfaces are rejected."""
        pytest.skip("Implementation not yet complete")


class TestContactResolver:
    def test_contact_resolver_maps_all_curves(self):
        """Verify all contact curves are resolved."""
        pytest.skip("Implementation not yet complete")


class TestUnstructuredAssembly:
    def test_edge_list_correct(self):
        """Verify edge list construction."""
        pytest.skip("Implementation not yet complete")

    def test_dual_cell_areas_positive(self):
        """Verify dual-cell areas are positive."""
        pytest.skip("Implementation not yet complete")

    def test_poisson_residual_structure(self):
        """Verify Poisson residual has correct structure."""
        pytest.skip("Implementation not yet complete")

    def test_edge_flux_sg_consistency(self):
        """Verify Scharfetter-Gummel flux direction consistency."""
        pytest.skip("Implementation not yet complete")


class TestDopingEvaluation:
    def test_doping_evaluation_at_arbitrary_positions(self):
        """Verify doping can be evaluated at arbitrary (x, y) positions."""
        pytest.skip("Implementation not yet complete")
