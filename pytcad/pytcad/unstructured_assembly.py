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
import numpy as np


class DegenerateMeshError(ValueError):
    """A triangle mesh violates a structural invariant this module
    requires (degenerate triangle, non-manifold edge)."""


def _triangle_area2(pts):
    """Twice the signed area of the triangle with vertices pts[0:3, :2]."""
    return ((pts[1, 0] - pts[0, 0]) * (pts[2, 1] - pts[0, 1])
           - (pts[2, 0] - pts[0, 0]) * (pts[1, 1] - pts[0, 1]))


def _cot(p_apex, p_a, p_b):
    """cot of the angle at p_apex subtended by rays to p_a and p_b."""
    v1 = p_a - p_apex
    v2 = p_b - p_apex
    cross = v1[0] * v2[1] - v1[1] * v2[0]
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    return dot / cross


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
    nodes_xy = np.asarray(nodes, dtype=float)[:, :2]
    tri = np.asarray(triangles, dtype=int)
    N = nodes_xy.shape[0]
    node_areas = np.zeros(N, dtype=float)
    edge_owners = {}   # (min(i,j), max(i,j)) -> list of triangle indices

    for t_idx, (a, b, c) in enumerate(tri):
        pts = nodes_xy[[a, b, c]]
        area2 = _triangle_area2(pts)
        tri_area = 0.5 * abs(area2)
        if tri_area < min_area:
            raise DegenerateMeshError(
                f"triangle {t_idx} (nodes {a},{b},{c}) has area "
                f"{tri_area:.3e} < min_area={min_area:.1e} -- degenerate "
                "or duplicate/collinear vertices")

        for e in ((a, b), (b, c), (c, a)):
            key = (int(min(e)), int(max(e)))
            edge_owners.setdefault(key, []).append(t_idx)

        La2 = np.sum((pts[1] - pts[2]) ** 2)   # side opposite a (b-c)
        Lb2 = np.sum((pts[2] - pts[0]) ** 2)   # side opposite b (c-a)
        Lc2 = np.sum((pts[0] - pts[1]) ** 2)   # side opposite c (a-b)
        obtuse_a = La2 > Lb2 + Lc2
        obtuse_b = Lb2 > La2 + Lc2
        obtuse_c = Lc2 > La2 + Lb2

        if obtuse_a or obtuse_b or obtuse_c:
            # Mixed/barycentric split: the obtuse vertex's own Voronoi
            # region would extend outside the triangle, so it instead
            # takes half the triangle's area; the other two vertices
            # split the remainder evenly. Sums to tri_area exactly.
            if obtuse_a:
                node_areas[a] += 0.5 * tri_area
                node_areas[b] += 0.25 * tri_area
                node_areas[c] += 0.25 * tri_area
            elif obtuse_b:
                node_areas[b] += 0.5 * tri_area
                node_areas[a] += 0.25 * tri_area
                node_areas[c] += 0.25 * tri_area
            else:
                node_areas[c] += 0.5 * tri_area
                node_areas[a] += 0.25 * tri_area
                node_areas[b] += 0.25 * tri_area
        else:
            # Circumcentric Voronoi contribution (Meyer et al. eq. 7):
            # each edge (i, j) opposite vertex k contributes
            # cot(angle_k) * |x_i - x_j|^2 / 8 to BOTH i and j.
            cot_a = _cot(pts[0], pts[1], pts[2])
            cot_b = _cot(pts[1], pts[2], pts[0])
            cot_c = _cot(pts[2], pts[0], pts[1])
            term_ab = cot_c * Lc2 / 8.0   # edge a-b, opposite c
            term_bc = cot_a * La2 / 8.0   # edge b-c, opposite a
            term_ca = cot_b * Lb2 / 8.0   # edge c-a, opposite b
            node_areas[a] += term_ab + term_ca
            node_areas[b] += term_ab + term_bc
            node_areas[c] += term_bc + term_ca

    bad_edges = {k: v for k, v in edge_owners.items() if len(v) > 2}
    if bad_edges:
        k0, v0 = next(iter(bad_edges.items()))
        raise DegenerateMeshError(
            f"edge {k0} is shared by {len(v0)} triangles (expected 1 or "
            "2) -- the mesh is not a valid 2-manifold triangulation "
            "(likely disconnected/overlapping triangles)")

    edge_list = np.array(sorted(edge_owners.keys()), dtype=int)
    return edge_list, node_areas


def _edge_triangle_owners(triangles):
    """{(min(i,j), max(i,j)): [triangle indices touching this edge]}."""
    owners = {}
    for t_idx, (a, b, c) in enumerate(triangles):
        for e in ((a, b), (b, c), (c, a)):
            key = (int(min(e)), int(max(e)))
            owners.setdefault(key, []).append(t_idx)
    return owners


def triangle_circumcenter(pts):
    """Circumcenter of the triangle with vertices pts[0:3, :2]
    (standard closed-form determinant formula)."""
    (Ax, Ay), (Bx, By), (Cx, Cy) = pts[0], pts[1], pts[2]
    D = 2.0 * (Ax * (By - Cy) + Bx * (Cy - Ay) + Cx * (Ay - By))
    a2 = Ax * Ax + Ay * Ay
    b2 = Bx * Bx + By * By
    c2 = Cx * Cx + Cy * Cy
    Ux = (a2 * (By - Cy) + b2 * (Cy - Ay) + c2 * (Ay - By)) / D
    Uy = (a2 * (Cx - Bx) + b2 * (Ax - Cx) + c2 * (Bx - Ax)) / D
    return np.array([Ux, Uy])


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
    Not clipped or corrected here; a future session revisiting this
    should measure whether it actually degrades the physics gates
    before adding a correction.
    """
    nodes_xy = np.asarray(nodes, dtype=float)[:, :2]
    tri = np.asarray(triangles, dtype=int)
    owners = _edge_triangle_owners(tri)
    circumcenters = np.array([triangle_circumcenter(nodes_xy[t]) for t in tri])

    interior_edges, trans = [], []
    for i, j in map(tuple, np.asarray(edge_list, dtype=int).tolist()):
        owner_tris = owners[(i, j)]
        if len(owner_tris) != 2:
            continue   # boundary edge -- no interior flux term
        t1, t2 = owner_tris
        dual_len = np.linalg.norm(circumcenters[t1] - circumcenters[t2])
        primal_len = np.linalg.norm(nodes_xy[j] - nodes_xy[i])
        interior_edges.append((i, j))
        trans.append(dual_len / primal_len)
    return (np.array(interior_edges, dtype=int) if interior_edges
           else np.zeros((0, 2), dtype=int),
           np.array(trans, dtype=float))
