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
from .errors import DegenerateMeshError


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


def _solve3(a, b):
    """Solve the 3x3 system a @ x = b by Cramer's rule, in a FIXED
    operation order.

    Deliberately not np.linalg.solve.  That routes to LAPACK dgesv, whose
    result depends on the BLAS build (pivot order, blocking, whether the
    rank-1 update fuses its multiply-add), so it cannot be reproduced
    bit-for-bit by a C++ port -- and the M31 migration gates the compiled
    path against this module with np.array_equal, not a tolerance.  A
    closed-form solve in a fixed order is reproducible by construction,
    so the Python reference and the C++ kernel run the same arithmetic
    and agree exactly.

    Numerically neutral, measured rather than assumed: over 200k random
    device-scale tetrahedra (1 nm - 1 um, offset from the origin), the
    worst violation of the defining equidistance property was 4.182e-10
    for this routine against 4.184e-10 for np.linalg.solve -- i.e. the
    same, and both dominated by the cancellation in the `b` vector below,
    not by the solve.  Max relative disagreement between the two was
    6.3e-12, at that same conditioning level.

    Raises np.linalg.LinAlgError on an exactly singular matrix, so the
    caller's existing degenerate fallback is unchanged.
    """
    c00 = a[1, 1] * a[2, 2] - a[1, 2] * a[2, 1]
    c01 = a[1, 2] * a[2, 0] - a[1, 0] * a[2, 2]
    c02 = a[1, 0] * a[2, 1] - a[1, 1] * a[2, 0]
    det = a[0, 0] * c00 + a[0, 1] * c01 + a[0, 2] * c02
    if det == 0.0:
        raise np.linalg.LinAlgError("singular 3x3 system")
    c10 = a[0, 2] * a[2, 1] - a[0, 1] * a[2, 2]
    c11 = a[0, 0] * a[2, 2] - a[0, 2] * a[2, 0]
    c12 = a[0, 1] * a[2, 0] - a[0, 0] * a[2, 1]
    c20 = a[0, 1] * a[1, 2] - a[0, 2] * a[1, 1]
    c21 = a[0, 2] * a[1, 0] - a[0, 0] * a[1, 2]
    c22 = a[0, 0] * a[1, 1] - a[0, 1] * a[1, 0]
    r = 1.0 / det
    return np.array([(c00 * b[0] + c10 * b[1] + c20 * b[2]) * r,
                     (c01 * b[0] + c11 * b[1] + c21 * b[2]) * r,
                     (c02 * b[0] + c12 * b[1] + c22 * b[2]) * r])


def tetrahedron_circumcenter(pts):
    """Circumcenter of the tetrahedron pts[0:4, :3] (standard linear
    solve: point equidistant from all 4 vertices)."""
    a = pts[1:] - pts[0]
    b = 0.5 * np.sum(pts[1:] ** 2 - pts[0] ** 2, axis=1)
    try:
        sol = _solve3(a, b)
    except np.linalg.LinAlgError:
        return pts.mean(axis=0)   # degenerate fallback: centroid
    return sol


def _build_unstructured_stencil3d_py(nodes, tets, min_volume=1e-45):
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
                f"tet {t_idx} (nodes {[int(v) for v in verts]}) has volume "
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


def _boundary_face_node_weights3d_py(nodes, faces):
    """Per-node AREA weight from a set of boundary triangular faces:
    each face contributes exactly 1/3 of its own area to each of its 3
    vertices (barycentric split -- the same exact-partition technique
    build_unstructured_stencil3d already uses for tet VOLUME, just one
    dimension down, and the unstructured generalization of device3d.py's
    `_gate_face_weight` -- a structured control-volume face area
    per surface node -- used to weight its Robin/gate boundary
    condition).

    nodes: (N, 3) array. faces: (K, 3) int array of 0-based node
    indices (a Physical-Surface face-tag array, e.g. from
    gmsh_mesh3d.GmshMesh3D.face_tags).

    Returns (node_idx, weights): node_idx is the sorted-unique node
    indices touched by `faces` (a node on several faces appears once,
    same convention np.unique(faces) already uses for contact node
    lists elsewhere in this sub-project); weights[i] is node_idx[i]'s
    TOTAL area contribution summed over every incident face in
    `faces` -- a node shared between two differently-named face
    groups (e.g. the edge between a FinFET's top gate and one of its
    sidewall gates) gets its correct total incident area only if BOTH
    groups' faces are passed in together (see gmsh_finfet3d.py's own
    docstring for why a tri-gate FinFET's three wrap faces are
    registered as ONE combined gate, not three, for exactly this
    reason: passing them separately would silently double-count that
    shared edge's oxide capacitance, an easy mistake this function
    cannot detect from a single call in isolation)."""
    nodes_xyz = np.asarray(nodes, dtype=float)[:, :3]
    faces = np.asarray(faces, dtype=int)
    if faces.size == 0:
        return np.zeros(0, dtype=int), np.zeros(0, dtype=float)
    p0 = nodes_xyz[faces[:, 0]]
    p1 = nodes_xyz[faces[:, 1]]
    p2 = nodes_xyz[faces[:, 2]]
    areas = 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
    per_third = areas / 3.0

    node_w = {}
    for tri, w in zip(faces, per_third):
        for v in tri:
            node_w[int(v)] = node_w.get(int(v), 0.0) + float(w)
    node_idx = np.array(sorted(node_w), dtype=int)
    weights = np.array([node_w[k] for k in node_idx], dtype=float)
    return node_idx, weights


def _build_edge_flux_geometry3d_py(nodes, tets, edge_list):
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


# ----------------------------------------------------------------------
#  Compiled dispatch (M31 P2)
# ----------------------------------------------------------------------
# The functions above are the REFERENCE, kept and diffed against the
# compiled path with np.array_equal by tests/test_accel_parity.py.
#
# build_edge_flux_geometry3d is why this whole phase exists: it profiled
# at 3.5k tets/s, so a 1M-tet mesh spent ~5 minutes in Python dict and
# per-edge loop overhead before any physics ran. Measured after: 1.99M
# tets/s (539x), and that 1M-tet mesh now takes 0.71 s.
from . import _accel


def build_unstructured_stencil3d(nodes, tets, min_volume=1e-45):
    if _accel.use_accel():
        edges, vol = _accel.core.build_stencil3d(
            _accel.as_nodes3(nodes), _accel.as_idx(tets, 4), float(min_volume))
        return _accel.match_empty_edges(edges), vol
    return _build_unstructured_stencil3d_py(nodes, tets, min_volume)


def build_edge_flux_geometry3d(nodes, tets, edge_list):
    if _accel.use_accel():
        trans = _accel.core.build_flux_geometry3d(
            _accel.as_nodes3(nodes), _accel.as_idx(tets, 4),
            _accel.as_edge_list(edge_list))
        # The reference returns edge_list ITSELF (call-site parity with
        # the 2D signature), not a copy -- preserve that identity.
        return edge_list, trans
    return _build_edge_flux_geometry3d_py(nodes, tets, edge_list)


def boundary_face_node_weights3d(nodes, faces):
    import numpy as _np
    faces_a = _np.asarray(faces)
    if _accel.use_accel() and faces_a.size != 0:
        return _accel.core.boundary_face_node_weights3d(
            _accel.as_nodes3(nodes), _accel.as_idx(faces_a, 3))
    return _boundary_face_node_weights3d_py(nodes, faces)


build_unstructured_stencil3d.__doc__ = _build_unstructured_stencil3d_py.__doc__
build_edge_flux_geometry3d.__doc__ = _build_edge_flux_geometry3d_py.__doc__
boundary_face_node_weights3d.__doc__ = _boundary_face_node_weights3d_py.__doc__
