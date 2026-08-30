"""M21 phase 3a -- map a GmshMesh's Physical Groups to device regions
and contacts, validating full mesh coverage.

Geometry-only, like gmsh_mesh.py and unstructured_assembly.py's stencil
builder: this never touches Device2D or any residual/Jacobian.
"""
import numpy as np


def resolve_regions(mesh):
    """Every triangle must belong to EXACTLY one region (surface
    Physical Group) -- never zero (an untagged hole in the geometry)
    and never more than one (overlapping regions, which would make the
    material/doping at that triangle ambiguous). Returns
    {region_name: (K,) int array of triangle indices} (a copy of
    mesh.surface_tags, returned only after the coverage check passes).

    Raises ValueError with an actionable message on any violation.
    """
    n_tri = mesh.n_triangles()
    owner = np.full(n_tri, -1, dtype=int)
    for name, tri_idx in mesh.surface_tags.items():
        for i in np.asarray(tri_idx, dtype=int):
            if owner[i] != -1:
                raise ValueError(
                    f"triangle {i} is claimed by both region "
                    f"'{owner_name(mesh, owner[i])}' and '{name}' -- "
                    "overlapping regions make the material ambiguous")
            owner[i] = _region_index(mesh, name)
    unassigned = np.where(owner == -1)[0]
    if unassigned.size:
        raise ValueError(
            f"{unassigned.size} triangle(s) belong to no region "
            f"(e.g. triangle {int(unassigned[0])}) -- every element of "
            "the mesh must be tagged with a region Physical Group")
    return {name: np.asarray(tri_idx, dtype=int)
           for name, tri_idx in mesh.surface_tags.items()}


def _region_index(mesh, name):
    return list(mesh.surface_tags).index(name)


def owner_name(mesh, idx):
    return list(mesh.surface_tags)[idx]


def resolve_contacts(mesh):
    """Every named contact (curve Physical Group) must resolve to at
    least one real boundary edge, and every one of its edges' nodes
    must actually appear in the triangle connectivity (a contact tag on
    a curve with no adjacent meshed surface would silently produce a
    contact nobody can ever apply a bias to). Returns a copy of
    mesh.curve_tags after validation.

    Raises ValueError with an actionable message on any violation.
    """
    tri_nodes = set(mesh.triangles.ravel().tolist())
    contacts = {}
    for name, edges in mesh.curve_tags.items():
        edges = np.asarray(edges, dtype=int)
        if edges.shape[0] == 0:
            raise ValueError(
                f"contact '{name}' resolves to zero boundary edges -- "
                "the curve Physical Group exists but the mesh has no "
                "line elements on it")
        stray = [int(n) for n in np.unique(edges) if n not in tri_nodes]
        if stray:
            raise ValueError(
                f"contact '{name}' references node(s) {stray[:5]} that "
                "are not part of any meshed triangle -- the contact "
                "curve is not adjacent to a meshed surface")
        contacts[name] = edges
    return contacts
