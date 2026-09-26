"""Qt-free PyVista grid builders for solved 3D results (NATIVE-DESKTOP-PLAN.md
section 15.6 / S4a): moved here verbatim from viewer3d.py, so they
build grids without importing PySide6 or pyvistaqt. viewer3d.py
re-imports every name below, so existing callers and tests are
unchanged. Needs only numpy and pyvista.
"""
import numpy as np
import pyvista as pv


def attach_scalar_field(grid, mesh_axes, field):
    """Attach one scalar field to an existing grid as point data,
    in place. Shared by build_rectilinear_grid() (Phase 1, one field at
    construction) and Viewer3DWindow (Phase 2, every available field
    attached up front so switching the active field needs no rebuild).

    Raises ValueError if the field's shape doesn't match the mesh axes
    -- the same guard build_rectilinear_grid() has always had, now
    shared rather than duplicated.
    """
    z = np.asarray(mesh_axes.axes["z"], dtype=float)
    y = np.asarray(mesh_axes.axes["y"], dtype=float)
    x = np.asarray(mesh_axes.axes["x"], dtype=float)
    expected_shape = (z.size, y.size, x.size)
    values = np.asarray(field.values, dtype=float)
    if values.shape != expected_shape:
        raise ValueError(
            f"field '{field.name}' has shape {values.shape}, "
            f"expected {expected_shape} to match the mesh axes")
    grid.point_data[field.name] = values.flatten(order="C")


def attach_vector_field(grid, mesh_axes, vector_field):
    """Attach one vector field to an existing grid as point data, in
    place -- the vector analogue of attach_scalar_field above, shared
    by Viewer3DWindow's vector sidebar (glyphs/streamlines both need a
    real (n_points, 3) vector array set as active on the grid, which is
    what VTK's own glyph()/streamlines() filters key off).

    vector_field: a result_store.VectorField whose `.components` dict
    carries per-axis arrays, each shaped like this device's node grid
    (Nz, Ny, Nx) -- same node ordering as attach_scalar_field. A
    missing axis (e.g. a 2D result's current_density, which has no
    "z" component) is treated as all-zero, so a genuinely 2D vector
    quantity still glyphs/streamlines sensibly in a thin 3D grid.

    Raises ValueError if a present component's shape doesn't match the
    mesh axes -- the same guard attach_scalar_field has always had.
    """
    z = np.asarray(mesh_axes.axes["z"], dtype=float)
    y = np.asarray(mesh_axes.axes["y"], dtype=float)
    x = np.asarray(mesh_axes.axes["x"], dtype=float)
    expected_shape = (z.size, y.size, x.size)
    n_points = z.size * y.size * x.size
    cols = []
    for axis in ("x", "y", "z"):
        if axis not in vector_field.components:
            cols.append(np.zeros(n_points, dtype=float))
            continue
        values = np.asarray(vector_field.components[axis], dtype=float)
        if values.shape != expected_shape:
            raise ValueError(
                f"vector field '{vector_field.name}' component '{axis}' has "
                f"shape {values.shape}, expected {expected_shape} to match "
                "the mesh axes")
        cols.append(values.flatten(order="C"))
    grid.point_data[vector_field.name] = np.column_stack(cols)


def build_rectilinear_grid(mesh_axes, field=None):
    """A pyvista.RectilinearGrid for a 3D device's mesh, optionally
    carrying one scalar field as point data.

    mesh_axes: a result_store.MeshAxes with dimensionality == 3.
    field: an optional result_store.ScalarField whose `.values` array
    has this device's node shape (Nz, Ny, Nx) -- pytcad's own node
    ordering (x fastest, z slowest; see mesh3d.py's module docstring).
    A plain `.flatten()` (C order) of that array lines up exactly with
    VTK's own point order for a RectilinearGrid built from (x, y, z)
    axes in that same order -- verified directly, not assumed; see
    3D-VISUALIZATION-PLAN.md Phase 1's test for the check.

    Raises ValueError for anything other than a 3D mesh -- this
    function has no 1D/2D behavior to silently fall back to.
    """
    if mesh_axes.dimensionality != 3:
        raise ValueError(
            "build_rectilinear_grid requires a 3D mesh, got "
            f"dimensionality={mesh_axes.dimensionality}")
    x = np.asarray(mesh_axes.axes["x"], dtype=float)
    y = np.asarray(mesh_axes.axes["y"], dtype=float)
    z = np.asarray(mesh_axes.axes["z"], dtype=float)
    grid = pv.RectilinearGrid(x, y, z)
    if field is not None:
        attach_scalar_field(grid, mesh_axes, field)
    return grid


def extract_isosurface(grid, field_name, level):
    """The real isosurface (a pv.PolyData) where `field_name` on `grid`
    crosses `level`, via VTK's own contour filter -- no approximation
    or custom marching-cubes code here.

    A level outside the field's actual [min, max] range yields an
    EMPTY surface (n_points == 0), verified directly (not assumed) to
    be VTK's actual behavior -- never a crash or an exception, which
    matters because a user is free to type any number into the level
    control.

    Raises KeyError if `field_name` isn't a scalar field on this grid
    -- a real caller mistake, not a scenario to silently paper over.
    """
    if field_name not in grid.point_data:
        raise KeyError(
            f"no scalar field '{field_name}' on this grid (available: "
            f"{sorted(grid.point_data.keys())})")
    return grid.contour(isosurfaces=[float(level)], scalars=field_name)
