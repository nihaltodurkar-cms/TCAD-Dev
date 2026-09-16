"""M21 phase 3a -- unstructured-mesh geometry: unique edge list and
dual-cell (Voronoi) node areas, from a triangle mesh.

GEOMETRY ONLY this phase (M21-PHASE3-MESHING-PLAN.md section 1): no
Scharfetter-Gummel flux, no Poisson/continuity residual or Jacobian, no
Device2D integration. Those are explicitly deferred to a follow-up
session (the plan's own risk assessment flags them HIGH RISK, touching
Device2D's frozen core) -- this module only builds the box-integration
GEOMETRY (edges + per-node cell areas) a future physics assembly would
consume, using the same box-integration philosophy device2d.py already
uses on structured meshes (see its module docstring), generalized to
triangles.

Dual-cell area method: the standard "mixed Voronoi/barycentric" area
(Meyer, Desbrun, Schroder & Barr, "Discrete Differential-Geometry
Operators for Triangulated 2-Manifolds", 2003, section 3.3) rather than
literal circumcenter computation + polygon clipping against the
opposite edge's perpendicular bisector -- the two are the STANDARD
equivalent for this purpose (both are exact for non-obtuse triangles;
both partition an obtuse triangle so no vertex is assigned a negative
or over-large area). The mixed method was chosen here because it is
simple index arithmetic with no clipping-polygon edge cases to get
wrong, and it satisfies the property this module's own G7 gate checks
BY CONSTRUCTION: each triangle's three per-vertex contributions sum to
EXACTLY that triangle's own area (1/2+1/4+1/4 in the obtuse case; the
six cotangent-weighted terms in the non-obtuse case are the same
identity the circumcenter construction relies on), so the total over
all triangles equals the total mesh area to floating-point precision,
not by tuning a tolerance.
"""
# One shared class, not a second same-named one: see pytcad/errors.py for
# why (an `except` on the 2D name used not to catch the 3D module's).
# Re-exported here so every existing `from .unstructured_assembly import
# DegenerateMeshError` keeps working.
from .errors import DegenerateMeshError  # noqa: F401 (re-exported)


# ----------------------------------------------------------------------
#  Compiled dispatch (M31 P2; pure-Python oracle REMOVED 2026-09-16,
#  M43 phase 4, at the user's explicit request -- these two now require
#  the compiled extension. core/src/mesh/stencil.cpp has the bodies.)
# ----------------------------------------------------------------------
from . import _accel


def build_unstructured_stencil(nodes, triangles, min_area=1e-30):
    """Build the unique undirected edge list and per-node dual-cell
    (Voronoi/mixed) areas for a triangle mesh.

    nodes: (N, >=2) array, only the first two (x, y) columns are used.
    triangles: (N_tri, 3) int array of 0-based node indices.

    Returns (edge_list, node_areas):
      edge_list  (N_edges, 2) int, each row (i, j) with i < j, one entry
                 per UNIQUE undirected mesh edge (an interior edge
                 shared by two triangles appears once, not twice).
      node_areas (N,) float, sums to the total mesh area to floating-
                 point precision (this module's own G7 gate).

    Raises DegenerateMeshError on a zero/near-zero-area triangle, or on
    a non-manifold edge (shared by more than 2 triangles -- a malformed
    or self-overlapping mesh, not a legal 2-manifold triangulation).
    """
    _accel.require_accel()
    edges, areas = _accel.core.build_stencil2d(
        _accel.as_nodes3(nodes), _accel.as_idx(triangles, 3), float(min_area))
    return _accel.match_empty_edges(edges), areas


def build_edge_flux_geometry(nodes, triangles, edge_list):
    """Two-Point Flux Approximation (TPFA) geometry factor per INTERIOR
    mesh edge: dual_facet_length / primal_edge_length, where
    dual_facet_length is the distance between the two owning triangles'
    circumcenters -- the Voronoi facet separating their dual cells.
    Boundary edges (one owning triangle) carry no such term at all
    (the implicit zero-flux Neumann convention every structured solver
    in this codebase already uses wherever an edge is simply absent).

    Returns (interior_edges, trans_factor): interior_edges (M, 2) int,
    a SUBSET of edge_list; trans_factor (M,) float, the dimensionless
    geometry factor (scale-invariant: a ratio of two lengths, so it is
    identical whether `nodes` is in physical or LD-scaled units --
    callers never need to rescale it).

    HONEST LIMIT: TPFA is exact for a strictly Delaunay mesh. Measured
    directly on this module's own diode fixture (gmsh's frontal-
    Delaunay algorithm): 1.39% of triangles are obtuse, meaning a
    small number of edges get a geometrically inconsistent (but still
    well-defined, non-crashing) factor -- not silently assumed away.
    """
    _accel.require_accel()
    return _accel.core.build_flux_geometry2d(
        _accel.as_nodes3(nodes), _accel.as_idx(triangles, 3),
        _accel.as_edge_list(edge_list))
