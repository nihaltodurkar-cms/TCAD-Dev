"""3D (tetrahedral-mesh) sibling of unstructured_assembly.py: unique
edge list, per-node dual-cell VOLUME, and per-edge TPFA geometry factor
(dual facet AREA / primal edge length, generalizing 2D's dual facet
LENGTH / primal edge length).

Dual-cell volume: BARYCENTRIC only (each tet contributes exactly 1/4 of
its own volume to each of its 4 vertices) -- an HONEST SIMPLIFICATION
of the true mixed-Voronoi method unstructured_assembly.py implements in
2D. A proper 3D Voronoi dual (clipping against perpendicular-bisector
planes, handling obtuse/non-well-centered tets) is materially harder
than the 2D mixed-area formula and was judged out of scope for this
pass -- the barycentric split is still non-negative and exactly
partitions each tet's volume (so the G7-style "sums to total mesh
volume" property still holds by construction), it is just not the
Voronoi cell for a non-regular tet. State this, don't hide it.

Dual facet area per edge: for each tetrahedron containing an edge
(i, j), the two faces of that tet touching the edge each have a
(triangle) circumcenter; the tet itself has a (tetrahedron) circumcenter.
The planar quadrilateral [edge midpoint, face-circumcenter-1,
tet-circumcenter, face-circumcenter-2] is that tet's own contribution to
the dual facet separating i and j's dual cells (the natural 3D
generalization of the 2D module's "distance between the two owning
triangles' circumcenters" segment -- here a polygon stitched from one
quad per tet sharing the edge, since in 3D more than two tets can share
an interior edge). Summing every tet's quad area gives the edge's total
dual facet area.

HONEST LIMIT (generalizing the 2D module's own caveat): this
quadrilateral construction is exact for a well-centered (all
circumcenters inside their simplex) Delaunay tetrahedralization. A
poorly-shaped or non-Delaunay tet can put a face or tet circumcenter
outside the tet, which does not crash this code (the quad area formula
is well-defined regardless) but can make its contribution geometrically
inconsistent (even sign-flipped) with the ideal Voronoi dual -- not
detected or corrected here, exactly like the 2D module's own 1.39%-
obtuse-triangle disclosure. gmsh's default 3D (Delaunay) meshing keeps
this rare in practice; not proven bounded in general.
"""
import numpy as np

# One shared class, not a second same-named one: see pytcad/errors.py.
# Re-exported here so every existing `from .unstructured_assembly3d
# import DegenerateMeshError` keeps working.
from .errors import DegenerateMeshError  # noqa: F401 (re-exported)

# ----------------------------------------------------------------------
#  Compiled dispatch (M31 P2; pure-Python oracle REMOVED 2026-09-16,
#  M43 phase 4, at the user's explicit request -- these three now
#  require the compiled extension. core/src/mesh/stencil.cpp has the
#  bodies.)
# ----------------------------------------------------------------------
from . import _accel


def build_unstructured_stencil3d(nodes, tets, min_volume=1e-45):
    """Build the unique undirected edge list and per-node dual-cell
    (barycentric, see module docstring) VOLUME for a tetrahedral mesh.

    nodes: (N, 3) array. tets: (N_tet, 4) int array of 0-based indices.

    Returns (edge_list, node_volumes):
      edge_list     (N_edges, 2) int, i < j, one row per UNIQUE
                    undirected mesh edge.
      node_volumes  (N,) float, sums to the total mesh volume to
                    floating-point precision (barycentric split is
                    exact by construction).

    Raises DegenerateMeshError on a near-zero-volume tet, or a
    triangular face shared by more than 2 tets (non-manifold mesh).
    """
    _accel.require_accel()
    edges, vol = _accel.core.build_stencil3d(
        _accel.as_nodes3(nodes), _accel.as_idx(tets, 4), float(min_volume))
    return _accel.match_empty_edges(edges), vol


def build_edge_flux_geometry3d(nodes, tets, edge_list):
    """TPFA geometry factor per INTERIOR mesh edge: dual_facet_area /
    primal_edge_length (see module docstring for the quad-per-tet
    construction). Every edge in edge_list gets a factor here -- unlike
    the 2D module, a tet-mesh edge can be interior to the volume even
    when it also touches the boundary surface, so there is no 2D-style
    "exactly one owning triangle => boundary edge, no flux" rule.

    Returns (interior_edges, trans_factor): interior_edges is simply
    edge_list itself here (kept as a separate return for call-site
    parity with the 2D module's signature); trans_factor (N_edges,)
    float, the dimensionless (eps-free) geometry factor.
    """
    _accel.require_accel()
    trans = _accel.core.build_flux_geometry3d(
        _accel.as_nodes3(nodes), _accel.as_idx(tets, 4),
        _accel.as_edge_list(edge_list))
    return edge_list, trans


def boundary_face_node_weights3d(nodes, faces):
    """Per-node AREA weight from a set of boundary triangular faces:
    each face contributes exactly 1/3 of its own area to each of its 3
    vertices (barycentric split -- the same exact-partition technique
    build_unstructured_stencil3d uses for tet VOLUME, one dimension
    down; the unstructured generalization of device3d.py's
    `_gate_face_weight`, used to weight a Robin/gate boundary
    condition).

    nodes: (N, 3) array. faces: (K, 3) int array of 0-based node
    indices (a Physical-Surface face-tag array, e.g. from
    gmsh_mesh3d.GmshMesh3D.face_tags).

    Returns (node_idx, weights): node_idx is the sorted-unique node
    indices touched by `faces`; weights[i] is node_idx[i]'s TOTAL area
    contribution summed over every incident face in `faces` -- a node
    shared between two differently-named face groups gets its correct
    total incident area only if BOTH groups' faces are passed in
    together (see gmsh_finfet3d.py's docstring for why a tri-gate
    FinFET's three wrap faces are registered as ONE combined gate).
    """
    faces_a = np.asarray(faces)
    if faces_a.size == 0:
        return np.zeros(0, dtype=int), np.zeros(0, dtype=float)
    _accel.require_accel()
    return _accel.core.boundary_face_node_weights3d(
        _accel.as_nodes3(nodes), _accel.as_idx(faces_a, 3))
