"""M21 phase 3a -- unstructured 2D mesh geometry foundation.

gmsh is an OPTIONAL dependency (same "soft import, friendly error at
call time" pattern workbench/solvers/devsim_backend.py already uses for
devsim): nothing in this module is imported at pytcad's top level, and
importing THIS module never fails just because gmsh is absent -- only
actually calling one of its functions does, with an actionable message.

This turns the validated ad-hoc script
examples/debug_geometry_gmsh_conformality.py into a real, reusable
module: `build_diode_mesh` reproduces that script's exact geometry
(two OCC rectangles, `fragment()`-ed so they share nodes exactly at the
material interface, sized against `pytcad.mesh.debye_length` rather
than an arbitrary distance field), and `_extract_current_model` is the
shared extraction logic both `build_diode_mesh` and `load_gmsh_mesh`
use to turn whatever is currently loaded in the gmsh model into a
`GmshMesh`.

Scope (M21-PHASE3-MESHING-PLAN.md section 1): geometry only. No
Scharfetter-Gummel flux, no Poisson/continuity assembly, no Device2D
integration -- see unstructured_assembly.py for the (also geometry-
only, this phase) dual-cell area construction that consumes a
GmshMesh's `nodes`/`triangles`.
"""
from dataclasses import dataclass, field

import numpy as np


def _require_gmsh():
    try:
        import gmsh  # noqa: F401
        return gmsh
    except ImportError as exc:
        raise ImportError(
            "this feature requires the optional 'gmsh' package "
            f"(pip install gmsh): {exc}") from exc


@dataclass
class GmshMesh:
    """nodes: (N, 3) float, x/y/z [cm] (z=0 for a 2D mesh).
    triangles: (N_tri, 3) int, 0-based indices into `nodes`.
    surface_tags: {region name: (K,) int array of triangle indices}.
    curve_tags: {contact name: (K, 2) int array of boundary-edge node
    index pairs}."""
    nodes: np.ndarray
    triangles: np.ndarray
    surface_tags: dict = field(default_factory=dict)
    curve_tags: dict = field(default_factory=dict)

    def n_nodes(self):
        return int(self.nodes.shape[0])

    def n_triangles(self):
        return int(self.triangles.shape[0])


def _extract_current_model():
    """Read whatever geometry/mesh is CURRENTLY active in the gmsh
    model (after gmsh.model.mesh.generate(2)) into a GmshMesh, keyed by
    the Physical Group names already defined for surfaces (regions)
    and curves (contacts). Node tags from gmsh are neither 0-based nor
    necessarily contiguous -- remapped here to plain 0-based indices
    into the returned `nodes` array, the only indexing convention
    anything downstream of this module needs to know about."""
    gmsh = _require_gmsh()

    node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
    nodes = np.asarray(node_coords, dtype=float).reshape(-1, 3)
    tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}

    surface_tags = {}
    all_tris = []
    for dim, pg in gmsh.model.getPhysicalGroups(2):
        name = gmsh.model.getPhysicalName(dim, pg)
        tri_indices = []
        for ent in gmsh.model.getEntitiesForPhysicalGroup(dim, pg):
            etypes, etags, enodes = gmsh.model.mesh.getElements(2, ent)
            for et, _tags, nds in zip(etypes, etags, enodes):
                if et != 2:   # 2 = 3-node triangle
                    continue
                nds = np.asarray(nds, dtype=int).reshape(-1, 3)
                for row in nds:
                    tri_indices.append(len(all_tris))
                    all_tris.append([tag_to_idx[int(n)] for n in row])
        surface_tags[name] = np.asarray(tri_indices, dtype=int)
    triangles = (np.asarray(all_tris, dtype=int) if all_tris
                else np.zeros((0, 3), dtype=int))

    curve_tags = {}
    for dim, pg in gmsh.model.getPhysicalGroups(1):
        name = gmsh.model.getPhysicalName(dim, pg)
        edges = []
        for ent in gmsh.model.getEntitiesForPhysicalGroup(dim, pg):
            etypes, etags, enodes = gmsh.model.mesh.getElements(1, ent)
            for et, _tags, nds in zip(etypes, etags, enodes):
                if et != 1:   # 1 = 2-node line
                    continue
                nds = np.asarray(nds, dtype=int).reshape(-1, 2)
                for row in nds:
                    edges.append([tag_to_idx[int(n)] for n in row])
        curve_tags[name] = (np.asarray(edges, dtype=int) if edges
                           else np.zeros((0, 2), dtype=int))

    return GmshMesh(nodes=nodes, triangles=triangles,
                    surface_tags=surface_tags, curve_tags=curve_tags)


def build_diode_mesh(Lx=6.0e-4, Ly=2.0e-4, Xj=3.0e-4, Nd_scale=1e16):
    """The same p-n diode geometry examples/debug_geometry_gmsh_
    conformality.py already validated: two OCC rectangles (p_region:
    [0,Xj]x[0,Ly], n_region: [Xj,Lx]x[0,Ly]) fragmented so they SHARE
    nodes exactly at x=Xj -- required for any SG-flux scheme that
    assumes a shared node at every interior interface, not two
    coincident-but-distinct boundary nodes. Physical Groups:
    "p_region"/"n_region" (surfaces), "left_contact"/"right_contact"
    (the x=0 and x=Lx edges). Mesh sized against
    `pytcad.mesh.debye_length(Nd_scale)`, not an arbitrary distance
    field -- the debug script's own hard-debug finding was that an
    ungrounded size field produced 10x more nodes than the physics
    needed.

    Returns a GmshMesh. Raises ImportError if gmsh is not installed.
    """
    gmsh = _require_gmsh()
    from .mesh import debye_length
    L_D = debye_length(Nd_scale)

    gmsh.initialize()
    try:
        gmsh.model.add("diode2d")
        occ = gmsh.model.occ
        p_rect = occ.addRectangle(0.0, 0.0, 0, Xj, Ly)
        n_rect = occ.addRectangle(Xj, 0.0, 0, Lx - Xj, Ly)
        occ.synchronize()

        occ.fragment([(2, p_rect)], [(2, n_rect)])
        occ.synchronize()

        surfaces = gmsh.model.getEntities(2)
        p_tag = n_tag = None
        for dim, tag in surfaces:
            com = occ.getCenterOfMass(dim, tag)
            if com[0] < Xj:
                p_tag = tag
            else:
                n_tag = tag
        if p_tag is None or n_tag is None:
            raise RuntimeError(
                "build_diode_mesh: could not identify both p/n surfaces "
                "after fragment() -- geometry construction failed")
        gmsh.model.addPhysicalGroup(2, [p_tag], name="p_region")
        gmsh.model.addPhysicalGroup(2, [n_tag], name="n_region")

        curves = gmsh.model.getEntities(1)
        left_curve = right_curve = None
        for dim, tag in curves:
            com = occ.getCenterOfMass(dim, tag)
            if abs(com[0] - 0.0) < 1e-12:
                left_curve = tag
            elif abs(com[0] - Lx) < 1e-12:
                right_curve = tag
        if left_curve is None or right_curve is None:
            raise RuntimeError(
                "build_diode_mesh: could not identify both contact edges")
        gmsh.model.addPhysicalGroup(1, [left_curve], name="left_contact")
        gmsh.model.addPhysicalGroup(1, [right_curve], name="right_contact")

        gmsh.model.mesh.field.add("Distance", 1)
        junction_curves = [c for d, c in curves
                          if abs(occ.getCenterOfMass(d, c)[0] - Xj) < 1e-12]
        gmsh.model.mesh.field.setNumbers(1, "CurvesList", junction_curves)
        gmsh.model.mesh.field.add("Threshold", 2)
        gmsh.model.mesh.field.setNumber(2, "InField", 1)
        gmsh.model.mesh.field.setNumber(2, "SizeMin", 0.5 * L_D)
        gmsh.model.mesh.field.setNumber(2, "SizeMax", 2e-5)
        gmsh.model.mesh.field.setNumber(2, "DistMin", 2.0 * L_D)
        gmsh.model.mesh.field.setNumber(2, "DistMax", 15.0 * L_D)
        gmsh.model.mesh.field.setAsBackgroundMesh(2)

        gmsh.model.mesh.generate(2)
        return _extract_current_model()
    finally:
        gmsh.finalize()


def load_gmsh_mesh(path):
    """Load an existing .msh file (Physical Groups already tagged in
    the file) and extract it the same way build_diode_mesh does. Raises
    ImportError if gmsh is not installed, FileNotFoundError-compatible
    errors from gmsh itself for a bad path."""
    gmsh = _require_gmsh()
    gmsh.initialize()
    try:
        gmsh.open(path)
        return _extract_current_model()
    finally:
        gmsh.finalize()
