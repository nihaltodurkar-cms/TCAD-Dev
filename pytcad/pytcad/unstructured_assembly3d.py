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


class DegenerateMeshError(ValueError):
    """A tet mesh violates a structural invariant this module requires
    (near-zero-volume tet, or a boundary/interior face shared by more
    than 2 tets -- not a valid manifold tetrahedralization)."""


def _tet_volume(pts):
    """Signed volume of the tetrahedron with vertices pts[0:4, :3]."""
    return np.dot(pts[1] - pts[0],
                 np.cross(pts[2] - pts[0], pts[3] - pts[0])) / 6.0


def triangle_circumcenter3d(pts):
    """Circumcenter of the triangle pts[0:3, :3] (barycentric-coordinate
    formula, valid off the xy-plane unlike unstructured_assembly.py's
    2D determinant form)."""
    a, b, c = pts[0], pts[1], pts[2]
    ac = c - a
    ab = b - a
    abXac = np.cross(ab, ac)
    denom = 2.0 * np.dot(abXac, abXac)
    if abs(denom) < 1e-300:
        return (a + b + c) / 3.0   # degenerate fallback: centroid
    to_c = (np.dot(np.cross(abXac, ab), np.dot(ac, ac))
           + np.dot(np.cross(ac, abXac), np.dot(ab, ab))) / denom
    return a + to_c


def tetrahedron_circumcenter(pts):
    """Circumcenter of the tetrahedron pts[0:4, :3] (standard linear
    solve: point equidistant from all 4 vertices)."""
    a = pts[1:] - pts[0]
    b = 0.5 * np.sum(pts[1:] ** 2 - pts[0] ** 2, axis=1)
    try:
        sol = np.linalg.solve(a, b)
    except np.linalg.LinAlgError:
        return pts.mean(axis=0)   # degenerate fallback: centroid
    return sol


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
    nodes_xyz = np.asarray(nodes, dtype=float)[:, :3]
    tet = np.asarray(tets, dtype=int)
    N = nodes_xyz.shape[0]
    node_vol = np.zeros(N, dtype=float)
    edge_owners = {}   # (i,j) i<j -> [tet indices]
    face_owners = {}   # (a,b,c) sorted -> [tet indices]

    FACES = ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))
    EDGES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))

    for t_idx, verts in enumerate(tet):
        pts = nodes_xyz[verts]
        vol = abs(_tet_volume(pts))
        if vol < min_volume:
            raise DegenerateMeshError(
                f"tet {t_idx} (nodes {list(verts)}) has volume "
                f"{vol:.3e} < min_volume={min_volume:.1e} -- degenerate "
                "or duplicate/coplanar vertices")
        node_vol[verts] += vol / 4.0

        for e in EDGES:
            key = (int(min(verts[e[0]], verts[e[1]])),
                  int(max(verts[e[0]], verts[e[1]])))
            edge_owners.setdefault(key, []).append(t_idx)
        for f in FACES:
            key = tuple(sorted(int(verts[k]) for k in f))
            face_owners.setdefault(key, []).append(t_idx)

    bad_faces = {k: v for k, v in face_owners.items() if len(v) > 2}
    if bad_faces:
        k0, v0 = next(iter(bad_faces.items()))
        raise DegenerateMeshError(
            f"face {k0} is shared by {len(v0)} tets (expected 1 or 2) "
            "-- the mesh is not a valid manifold tetrahedralization")

    edge_list = np.array(sorted(edge_owners.keys()), dtype=int)
    return edge_list, node_vol


def build_edge_flux_geometry3d(nodes, tets, edge_list):
    """TPFA geometry factor per INTERIOR mesh edge: dual_facet_area /
    primal_edge_length (see module docstring for the quad-per-tet
    construction). Boundary edges (touched by only one owning tet's
    worth of the standard box-integration sense -- see below) are
    still assigned a factor here as long as at least one tet contains
    them, UNLIKE the 2D module: in a tet mesh, an "interior" edge (not
    on the outer boundary surface) is shared by potentially many tets,
    and an edge ON the boundary surface can still be shared by 2+
    interior tets and carry a legitimate interior flux -- there is no
    2D-style "exactly one owning triangle => boundary edge, no flux"
    rule in 3D, since edges (unlike triangle EDGES in 2D, which border
    exactly the mesh boundary when owned by 1 triangle) are 1D features
    that boundary tets still enclose. Every edge in edge_list therefore
    gets a factor here; a genuinely isolated/degenerate edge (0 owning
    tets, which cannot occur if the edge came from edge_list itself)
    would raise ZeroDivisionError-adjacent nan and is not expected.

    Returns (interior_edges, trans_factor): interior_edges is simply
    edge_list itself here (kept as a separate return for call-site
    parity with the 2D module's signature); trans_factor (N_edges,)
    float, the dimensionless (eps-free) geometry factor.
    """
    nodes_xyz = np.asarray(nodes, dtype=float)[:, :3]
    tet = np.asarray(tets, dtype=int)
    N_tet = tet.shape[0]

    tet_cc = np.array([tetrahedron_circumcenter(nodes_xyz[t]) for t in tet])
    FACES = ((0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3))
    face_cc = {}   # (t_idx, local_face) -> circumcenter, memoized per tet

    def face_circumcenter(t_idx, local_face):
        key = (t_idx, local_face)
        if key not in face_cc:
            verts = tet[t_idx][list(local_face)]
            face_cc[key] = triangle_circumcenter3d(nodes_xyz[verts])
        return face_cc[key]

    EDGES = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
    edge_owners = {}
    for t_idx, verts in enumerate(tet):
        for e in EDGES:
            key = (int(min(verts[e[0]], verts[e[1]])),
                  int(max(verts[e[0]], verts[e[1]])))
            edge_owners.setdefault(key, []).append(t_idx)

    trans = np.zeros(edge_list.shape[0], dtype=float)
    for row, (i, j) in enumerate(map(tuple, np.asarray(edge_list, dtype=int).tolist())):
        mid = 0.5 * (nodes_xyz[i] + nodes_xyz[j])
        primal_len = np.linalg.norm(nodes_xyz[j] - nodes_xyz[i])
        area = 0.0
        for t_idx in edge_owners.get((i, j), []):
            verts = tet[t_idx]
            local_i = int(np.where(verts == i)[0][0])
            local_j = int(np.where(verts == j)[0][0])
            # the two faces of this tet containing both i and j
            local_faces = [f for f in FACES if local_i in f and local_j in f]
            fc1 = face_circumcenter(t_idx, local_faces[0])
            fc2 = face_circumcenter(t_idx, local_faces[1])
            tc = tet_cc[t_idx]
            # quad [mid, fc1, tc, fc2] area via two triangles
            a1 = 0.5 * np.linalg.norm(np.cross(fc1 - mid, tc - mid))
            a2 = 0.5 * np.linalg.norm(np.cross(tc - mid, fc2 - mid))
            area += a1 + a2
        trans[row] = area / primal_len if primal_len > 0 else 0.0
    return edge_list, trans
