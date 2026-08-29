"""3D visualization (3D-VISUALIZATION-PLAN.md): PyVista/VTK, opened as
a separate top-level QWidget window rather than embedded in the QML
scene graph -- confirmed with the user, see that plan's "Architecture
decision" section for why (VTK's Qt integration is a QWidget, not a
QML item; bridging it into the QML scene graph needs a heavy custom FBO
pipeline that buys nothing for a first version).

This module is split into a pure, headlessly-testable half (build the
PyVista mesh object and extract isosurfaces from real ResultStore data
-- no Qt, no window) and a Qt half (Viewer3DWindow). Phase 1 shipped a
mesh bounding-box wireframe plus a solid device surface, proving the
whole pipeline (real 3D solve -> real result store -> real PyVista mesh
-> a window on screen). Phase 2 adds a real isosurface mode: pick a
field and a level, see the actual shell that field crosses through the
device volume -- still no volumetric rendering or animation, later
phases.
"""
import numpy as np
import pyvista as pv
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDockWidget, QDoubleSpinBox, QFormLayout, QMainWindow,
    QWidget,
)
from pyvistaqt import QtInteractor

# A small curated set, not every matplotlib colormap -- perceptually
# uniform sequential (viridis/plasma) plus one diverging colormap for
# fields that cross zero (net doping), matching the same "small honest
# set over a fake feature-complete list" choice this plan already makes
# for Phase 3's transfer-function presets. "RdBu_r", not "coolwarm":
# mpl_canvas_item.py's _draw_doping_preview already established RdBu_r
# as this project's diverging colormap for the identical zero-crossing
# net-doping case -- reusing it instead of picking a second one keeps
# the doping color convention consistent between the 2D and 3D viewers.
COLORMAPS = ["viridis", "plasma", "RdBu_r"]


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


class _Viewer3DMainWindow(QMainWindow):
    """A QMainWindow whose only job beyond the default is routing the
    native window-manager close button (the ordinary way a user closes
    a window) through the same release callback as an explicit
    Viewer3DWindow.close() -- otherwise the OS close button only hides
    the widget and never releases the VTK render context underneath
    it."""

    def __init__(self, on_close):
        super().__init__()
        self._on_close = on_close

    def closeEvent(self, event):
        self._on_close()
        super().closeEvent(event)


class Viewer3DWindow:
    """Owns one PyVista/VTK window. The mesh/isosurface LOGIC lives in
    the module-level functions above, exercised directly by headless
    tests; this class's own Qt wiring is not, since VTK's own render
    window does its own windowing-system calls independent of Qt's
    platform plugin and is not meaningfully testable under
    QT_QPA_PLATFORM=offscreen (confirmed: attempting to build a live
    QtInteractor there raises an X11 BadWindow error, not a clean
    no-op). `QtInteractor` is imported at module level specifically so
    a test CAN monkeypatch `viewer3d.QtInteractor` to a fake and still
    exercise this class's widget-construction/signal-wiring code
    without touching a real GL context -- see test_viewer3d.py.

    store: a ResultStore (mesh_axes()/available_scalars()/
    scalar_field(name)) for a solved 3D result. Every available scalar
    field is attached to ONE grid up front, so switching the active
    field in the sidebar recomputes only the isosurface, never rebuilds
    the mesh.
    """

    def __init__(self, store, title="PyTCAD 3D Viewer"):
        axes = store.mesh_axes()
        self.grid = build_rectilinear_grid(axes)
        # The canonical field list, not grid.point_data.keys() -- that's
        # a VTK mapping whose iteration order happens to match this
        # today but isn't a guaranteed contract, unlike this accessor.
        field_names = store.available_scalars()
        for name in field_names:
            attach_scalar_field(self.grid, axes, store.scalar_field(name))

        self._closed = False
        self._window = _Viewer3DMainWindow(self._release)
        self._window.setWindowTitle(title)
        self._window.resize(1100, 700)
        self.plotter = QtInteractor(self._window)
        self._window.setCentralWidget(self.plotter.interactor)

        # Phase 1: mesh outline + a solid, flat-colored surface of the
        # device volume -- permanent spatial context underneath
        # whichever isosurface is selected.
        self.plotter.add_mesh(self.grid.outline(), color="white")
        self.plotter.add_mesh(self.grid, style="surface", opacity=0.15,
                              show_edges=False, color="lightsteelblue")

        self._iso_actor = None
        self._iso_cache_key = None
        self._iso_surface = None
        self._build_sidebar(field_names)
        if field_names:
            # "doping" first if present (the example every Phase-1/2
            # device actually has), else whatever sorted-first field
            # exists -- never silently pick nothing when data exists.
            default = "doping" if "doping" in field_names else sorted(field_names)[0]
            # Blocked so setCurrentText() never double-fires
            # _on_field_changed via currentTextChanged when `default`
            # differs from the combo's own auto-selected first item --
            # the explicit call below is the single source of truth.
            self._field_box.blockSignals(True)
            self._field_box.setCurrentText(default)
            self._field_box.blockSignals(False)
            self._on_field_changed(default)
        else:
            # No scalar field exists on this result at all -- disable
            # the sidebar rather than leave it showing a default range
            # with no field selected and no indication anything is wrong.
            self._field_box.setEnabled(False)
            self._level_box.setEnabled(False)
            self._colormap_box.setEnabled(False)
        self.plotter.reset_camera()

    def _build_sidebar(self, field_names):
        dock = QDockWidget("Isosurface", self._window)
        panel = QWidget()
        form = QFormLayout(panel)

        self._field_box = QComboBox()
        self._field_box.addItems(sorted(field_names))
        self._field_box.currentTextChanged.connect(self._on_field_changed)
        form.addRow("Field", self._field_box)

        self._level_box = QDoubleSpinBox()
        self._level_box.setDecimals(6)
        self._level_box.valueChanged.connect(self._on_level_changed)
        form.addRow("Level", self._level_box)

        self._colormap_box = QComboBox()
        self._colormap_box.addItems(COLORMAPS)
        self._colormap_box.currentTextChanged.connect(self._on_colormap_changed)
        form.addRow("Colormap", self._colormap_box)

        dock.setWidget(panel)
        self._window.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _on_field_changed(self, field_name):
        if not field_name:
            return
        values = self.grid.point_data[field_name]
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            # Every value is NaN/Inf (e.g. a non-converged solve) --
            # refuse rather than hand QDoubleSpinBox a NaN range/value,
            # which Qt accepts silently instead of raising.
            self._level_box.setEnabled(False)
            if self._iso_actor is not None:
                self.plotter.remove_actor(self._iso_actor)
                self._iso_actor = None
            return
        self._level_box.setEnabled(True)
        vmin, vmax = float(finite.min()), float(finite.max())
        self._level_box.blockSignals(True)
        self._level_box.setRange(vmin, vmax)
        self._level_box.setValue((vmin + vmax) / 2.0)
        self._level_box.blockSignals(False)
        self._redraw_isosurface()

    def _on_level_changed(self, _value):
        self._redraw_isosurface()

    def _on_colormap_changed(self, _name):
        self._redraw_isosurface()

    def _redraw_isosurface(self):
        field_name = self._field_box.currentText()
        if not field_name:
            return
        level = self._level_box.value()
        cache_key = (field_name, level)
        # A colormap-only change leaves field/level unchanged -- reuse
        # the already-extracted surface instead of paying VTK's contour
        # cost again for identical geometry.
        if cache_key == self._iso_cache_key and self._iso_surface is not None:
            surface = self._iso_surface
        else:
            surface = extract_isosurface(self.grid, field_name, level)
            self._iso_cache_key = cache_key
            self._iso_surface = surface
        if self._iso_actor is not None:
            self.plotter.remove_actor(self._iso_actor)
            self._iso_actor = None
        if surface.n_points == 0:
            return
        self._iso_actor = self.plotter.add_mesh(
            surface, scalars=field_name, cmap=self._colormap_box.currentText(),
            show_scalar_bar=True)

    def _release(self):
        """Release the VTK render context exactly once, however the
        window gets closed -- the native OS close button (via
        _Viewer3DMainWindow.closeEvent) or an explicit close() call
        both route through here."""
        if self._closed:
            return
        self._closed = True
        self.plotter.close()

    def show(self):
        if self._closed:
            raise RuntimeError(
                "Viewer3DWindow already closed -- construct a new one")
        self._window.show()

    def close(self):
        self._release()
        self._window.close()
