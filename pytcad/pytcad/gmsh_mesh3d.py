"""3D sibling of gmsh_mesh.py: unstructured TETRAHEDRAL mesh geometry,
built the same "OCC solids, fragment()-ed so shared faces get shared
nodes, then extract Physical Groups" way build_diode_mesh does for 2D
triangles -- generalized one dimension further (3D box solids instead
of 2D rectangles, tetrahedra instead of triangles, boundary FACES
instead of boundary edges for contacts).

Scope: geometry only, the same phase the 2D gmsh_mesh.py module started
at. No flux/assembly here -- see unstructured_assembly3d.py.

The 2D path (gmsh_mesh.py) is UNTOUCHED by this module; this is a
sibling file, not an edit to it.
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
class GmshMesh3D:
    """nodes: (N, 3) float, x/y/z [cm].
    tets: (N_tet, 4) int, 0-based indices into `nodes`.
    volume_tags: {region name: (K,) int array of tet indices}.
    face_tags: {contact name: (K, 3) int array of boundary-triangle
    node-index triples}."""
    nodes: np.ndarray
    tets: np.ndarray
    volume_tags: dict = field(default_factory=dict)
    face_tags: dict = field(default_factory=dict)

    def n_nodes(self):
        return int(self.nodes.shape[0])

    def n_tets(self):
        return int(self.tets.shape[0])


def _extract_current_model3d():
    """3D analogue of gmsh_mesh._extract_current_model: Physical
    Groups on 3D volumes -> volume_tags (regions), Physical Groups on
    2D surfaces -> face_tags (contacts), tetrahedra (gmsh element type
    4) only -- any other element type present in a volume (e.g. a
    leftover pyramid at a hybrid-mesh transition) is dropped rather
    than silently miscounted, since nothing downstream reads tets in
    any layout but 4-node."""
    gmsh = _require_gmsh()

    node_tags, node_coords, _ = gmsh.model.mesh.getNodes()
    nodes = np.asarray(node_coords, dtype=float).reshape(-1, 3)
    tag_to_idx = {int(t): i for i, t in enumerate(node_tags)}

    volume_tags = {}
    all_tets = []
    for dim, pg in gmsh.model.getPhysicalGroups(3):
        name = gmsh.model.getPhysicalName(dim, pg)
        tet_indices = []
        for ent in gmsh.model.getEntitiesForPhysicalGroup(dim, pg):
            etypes, etags, enodes = gmsh.model.mesh.getElements(3, ent)
            for et, _tags, nds in zip(etypes, etags, enodes):
                if et != 4:   # 4 = 4-node tetrahedron
                    continue
                nds = np.asarray(nds, dtype=int).reshape(-1, 4)
                for row in nds:
                    tet_indices.append(len(all_tets))
                    all_tets.append([tag_to_idx[int(n)] for n in row])
        volume_tags[name] = np.asarray(tet_indices, dtype=int)
    tets = (np.asarray(all_tets, dtype=int) if all_tets
           else np.zeros((0, 4), dtype=int))

    face_tags = {}
    for dim, pg in gmsh.model.getPhysicalGroups(2):
        name = gmsh.model.getPhysicalName(dim, pg)
        faces = []
        for ent in gmsh.model.getEntitiesForPhysicalGroup(dim, pg):
            etypes, etags, enodes = gmsh.model.mesh.getElements(2, ent)
            for et, _tags, nds in zip(etypes, etags, enodes):
                if et != 2:   # 2 = 3-node triangle
                    continue
                nds = np.asarray(nds, dtype=int).reshape(-1, 3)
                for row in nds:
                    faces.append([tag_to_idx[int(n)] for n in row])
        face_tags[name] = (np.asarray(faces, dtype=int) if faces
                          else np.zeros((0, 3), dtype=int))

    return GmshMesh3D(nodes=nodes, tets=tets, volume_tags=volume_tags,
                      face_tags=face_tags)


def build_diode_mesh3d(Lx=2.0e-4, Ly=5.0e-5, Lz=3.0e-5, Xj=1.0e-4,
                       Nd_scale=1e17):
    """A z-invariant p-n slab, the exact geometry/doping-scale
    tests/test_validation_3d.py's own `test_bias_3d_reduces_to_2d`
    fixture uses for the STRUCTURED Mesh3D/Device3D path -- built here
    instead as two OCC box solids, fragment()-ed at x=Xj so they share
    a tetrahedron-mesh-conforming interface (the same "fragment for a
    shared node/face, not two coincident ones" convention
    gmsh_mesh.build_diode_mesh already established for 2D). Physical
    Groups: "p_region"/"n_region" (volumes), "left_contact"/
    "right_contact" (the x=0 and x=Lx faces).

    Mesh sized against `pytcad.mesh.debye_length(Nd_scale)`, GRADED
    toward the x=Xj junction plane with a gmsh Distance+Threshold field
    -- the same convention gmsh_mesh.build_diode_mesh already uses in
    2D (that module's own docstring: an ungrounded/uniform size field
    produced 10x more nodes than the physics needed, AND under-resolves
    the depletion region badly enough to distort the forward-bias
    diffusion current by orders of magnitude -- confirmed empirically
    while validating this module against test_unstructured_dd3d.py's
    structured Device3D cross-check).

    Returns a GmshMesh3D. Raises ImportError if gmsh is not installed.
    """
    gmsh = _require_gmsh()
    from .mesh import debye_length
    L_D = debye_length(Nd_scale)

    gmsh.initialize()
    try:
        gmsh.model.add("diode3d")
        occ = gmsh.model.occ
        p_box = occ.addBox(0.0, 0.0, 0.0, Xj, Ly, Lz)
        n_box = occ.addBox(Xj, 0.0, 0.0, Lx - Xj, Ly, Lz)
        occ.synchronize()

        occ.fragment([(3, p_box)], [(3, n_box)])
        occ.synchronize()

        vols = gmsh.model.getEntities(3)
        p_tag = n_tag = None
        for dim, tag in vols:
            com = occ.getCenterOfMass(dim, tag)
            if com[0] < Xj:
                p_tag = tag
            else:
                n_tag = tag
        if p_tag is None or n_tag is None:
            raise RuntimeError(
                "build_diode_mesh3d: could not identify both p/n "
                "volumes after fragment() -- geometry construction failed")
        gmsh.model.addPhysicalGroup(3, [p_tag], name="p_region")
        gmsh.model.addPhysicalGroup(3, [n_tag], name="n_region")

        faces = gmsh.model.getEntities(2)
        left_face = right_face = junction_face = None
        junction_faces = []
        for dim, tag in faces:
            com = occ.getCenterOfMass(dim, tag)
            if abs(com[0] - 0.0) < 1e-12:
                left_face = tag
            elif abs(com[0] - Lx) < 1e-12:
                right_face = tag
            if abs(com[0] - Xj) < 1e-9:
                junction_faces.append(tag)
        if left_face is None or right_face is None:
            raise RuntimeError(
                "build_diode_mesh3d: could not identify both contact faces")
        gmsh.model.addPhysicalGroup(2, [left_face], name="left_contact")
        gmsh.model.addPhysicalGroup(2, [right_face], name="right_contact")

        gmsh.model.mesh.field.add("Distance", 1)
        gmsh.model.mesh.field.setNumbers(1, "SurfacesList", junction_faces)
        gmsh.model.mesh.field.add("Threshold", 2)
        gmsh.model.mesh.field.setNumber(2, "InField", 1)
        gmsh.model.mesh.field.setNumber(2, "SizeMin", 1.5 * L_D)
        gmsh.model.mesh.field.setNumber(2, "SizeMax", 0.5 * min(Ly, Lz))
        gmsh.model.mesh.field.setNumber(2, "DistMin", 3.0 * L_D)
        gmsh.model.mesh.field.setNumber(2, "DistMax", 6.0 * L_D)
        gmsh.model.mesh.field.setAsBackgroundMesh(2)

        gmsh.model.mesh.generate(3)
        return _extract_current_model3d()
    finally:
        gmsh.finalize()


def load_gmsh_mesh3d(path):
    """Load an existing .msh file (Physical Groups on volumes/surfaces
    already tagged in the file). Raises ImportError if gmsh is not
    installed."""
    gmsh = _require_gmsh()
    gmsh.initialize()
    try:
        gmsh.open(path)
        return _extract_current_model3d()
    finally:
        gmsh.finalize()
