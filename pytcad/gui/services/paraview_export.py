"""PARAVIEW-EXPORT-PLAN.md: write genuine ParaView-native files (.vtu /
.pvd) from a solved 3D ResultStore, so a user can hand a result to their
own ParaView install for filters/animation/screenshots that the in-app
PyVista viewer (viewer3d.py) doesn't cover.

Deliberately reuses viewer3d.py's own pure grid-building functions
(build_rectilinear_grid/attach_scalar_field/attach_vector_field) instead
of re-deriving the RectilinearGrid-from-MeshAxes logic a second time --
both modules live under gui/services, which is already a hard PySide6
dependency (see CLAUDE.md), so importing viewer3d here carries no cost
examples/08_3d_umos_amr.py doesn't have (that script avoids viewer3d.py
only because IT must stay pytcad-core-only, importable with no GUI
present at all).

Pure functions, no Qt: take a ResultStore + plain paths, return a path.
Headlessly testable exactly like viewer3d.py's own module-level
functions -- no QApplication/offscreen platform needed.
"""
import os
import xml.etree.ElementTree as ET

from .viewer3d import (
    attach_scalar_field, attach_vector_field, build_rectilinear_grid,
)


def export_vtu(store, out_path):
    """Write the current state of `store` (every available scalar and
    vector field, all attached to one grid) as a single ParaView-native
    .vtu file.

    store: a ResultStore for a solved 3D result (mesh_axes().dimensionality
    == 3 -- build_rectilinear_grid enforces this and raises ValueError
    otherwise, same guard the in-app viewer already relies on).

    Mirrors examples/08_3d_umos_amr.py's own _export_vtu (RectilinearGrid
    -> cast_to_unstructured_grid() -> .save()), the one place in this repo
    that already solved "make VTK write a file ParaView reads natively" --
    but as reusable service code operating on the GUI's ResultStore
    abstraction, not a raw Device3D.

    Returns out_path.
    """
    axes = store.mesh_axes()
    grid = build_rectilinear_grid(axes)
    for name in store.available_scalars():
        attach_scalar_field(grid, axes, store.scalar_field(name))
    try:
        vector_names = store.available_vectors()
    except AttributeError:
        vector_names = []
    for name in vector_names:
        attach_vector_field(grid, axes, store.vector_field(name))
    ugrid = grid.cast_to_unstructured_grid()
    ugrid.save(str(out_path))
    return out_path


def export_pvd_series(store, snapshots, out_dir, base_name):
    """Write one .vtu per sweep snapshot plus a .pvd collection file
    tying them together as a ParaView time series, keyed by each step's
    REAL bias voltage (not a meaningless frame index) -- the concrete gap
    versus examples/08's bare `{base_name}_pass{cycle}.vtu` sequence,
    which has no .pvd at all and so never gives ParaView a genuine
    "Play" timeline.

    store: the ResultStore the snapshots were captured from (used only
    for mesh_axes() -- the snapshot field VALUES come from `snapshots`
    itself, not store.scalar_field(), exactly like
    Viewer3DWindow._apply_snapshot's own pattern).
    snapshots: a result_store.SweepSnapshots (store.sweep_snapshots()).
    out_dir: directory to write into (created if missing).
    base_name: filename stem; files land as "{base_name}_{i}.vtu" and
    "{base_name}.pvd".

    Raises ValueError if snapshots carries zero snapshots -- a .pvd with
    no <DataSet> entries is not a meaningful ParaView time series to
    write silently.

    Returns the .pvd path.
    """
    n = snapshots.n_snapshots()
    if n == 0:
        raise ValueError("no sweep snapshots to export")
    os.makedirs(str(out_dir), exist_ok=True)
    axes = store.mesh_axes()
    template_grid = build_rectilinear_grid(axes)

    entries = []
    for idx in range(n):
        grid = template_grid.copy()
        for field_name in snapshots.field_names:
            grid.point_data[field_name] = (
                snapshots.field(field_name, idx).flatten(order="C"))
        fname = f"{base_name}_{idx}.vtu"
        ugrid = grid.cast_to_unstructured_grid()
        ugrid.save(str(os.path.join(str(out_dir), fname)))
        entries.append((snapshots.voltage(idx), fname))

    root = ET.Element("VTKFile", type="Collection", version="0.1")
    collection = ET.SubElement(root, "Collection")
    for voltage, fname in entries:
        ET.SubElement(collection, "DataSet", timestep=str(voltage),
                      part="0", file=fname)
    pvd_path = os.path.join(str(out_dir), f"{base_name}.pvd")
    ET.ElementTree(root).write(pvd_path, xml_declaration=True,
                               encoding="UTF-8")
    return pvd_path
