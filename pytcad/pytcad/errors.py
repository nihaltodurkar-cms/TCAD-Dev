"""Shared exception types for the numerical core.

Historically `DegenerateMeshError` was declared TWICE -- once in
`unstructured_assembly.py` (triangles) and once in
`unstructured_assembly3d.py` (tets) -- as two unrelated classes that
merely shared a name.  That meant

    from .unstructured_assembly import DegenerateMeshError
    ...
    except DegenerateMeshError:      # did NOT catch the 3D one

silently failed to catch the 3D module's error, and vice versa.  Both
modules now import the single class defined here, so the name means one
thing everywhere.  Both still re-export it, so every existing import
site (`tests/test_m21_phase3.py`, `tests/test_unstructured_dd3d.py`,
`adapt_unstructured*.py`, `device2d.py`) keeps working unchanged.

This module must stay import-cheap and dependency-free: it is imported
by the assembly modules, which `pytcad/__init__.py` reaches eagerly,
and (per M31 phase 2) the C++ extension's exception translator resolves
these classes lazily by name -- the PYTHON class is the authority, so a
C++ kernel raises the same type an existing `pytest.raises` already
catches.
"""

__all__ = ["DegenerateMeshError"]


class DegenerateMeshError(ValueError):
    """A mesh violates a structural invariant the assembly requires.

    Raised for a degenerate (zero/near-zero measure) element -- a
    collinear triangle or a flat tetrahedron -- or for a non-manifold
    entity: an edge shared by more than 2 triangles, or a face shared
    by more than 2 tets.  A `ValueError` because it always means the
    caller handed in a malformed mesh, never that the solver failed.
    """
