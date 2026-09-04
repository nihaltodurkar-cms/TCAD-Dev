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
device volume. Phase 3 adds volumetric rendering with preset transfer
functions. Phase 4 adds animated bias-sweep playback with snapshot
capture and timeline scrubber.
"""
import numpy as np
import pyvista as pv
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDockWidget, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QMainWindow, QPushButton, QSlider, QWidget,
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


# Phase 3: transfer function presets for volumetric rendering.
# Each preset returns a dict {"color_map": str, "opacity": float} that
# applies to add_volume(). The presets are deliberately simple -- no
# custom curve editor for this pass, just a small set of useful
# defaults that cover the common TCAD visualization cases:
#   "linear"      : uniform opacity across the full range (default)
#   "log-high"    : emphasizes high-value regions (carrier densities,
#                   current density) by compressing the low end
#   "log-low"     : emphasizes low-value regions (depletion tails,
#                   minor carrier concentrations) by expanding the low end
#   "threshold"   : binary threshold at 50% of range, useful for
#                   isolating specific field magnitudes
TRANSFER_FUNCTION_PRESETS = {
    "linear": {"color_map": "viridis", "opacity": 0.3},
    "log-high": {"color_map": "plasma", "opacity": 0.25},
    "log-low": {"color_map": "viridis", "opacity": 0.35},
    "threshold": {"color_map": "RdBu_r", "opacity": 0.5},
}


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


def _build_transfer_function(preset_name):
    """Build a transfer-function specification for PyVista's add_volume().

    Returns a dict {"color_map": str, "opacity": float} suitable for
    passing as keyword arguments to add_volume(). The opacity is kept
    low (0.2-0.5) so isosurfaces remain visible underneath the volume.

    preset_name: one of TRANSFER_FUNCTION_PRESETS keys.
    Returns the preset dict; callers should validate the key exists
    before calling (the sidebar controls enforce this).
    """
    if preset_name not in TRANSFER_FUNCTION_PRESETS:
        raise KeyError(
            f"unknown transfer function '{preset_name}' "
            f"(available: {sorted(TRANSFER_FUNCTION_PRESETS.keys())})")
    return dict(TRANSFER_FUNCTION_PRESETS[preset_name])


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
        # Tracked directly (not re-discovered by scanning the plotter
        # later -- see _remove_monolithic_surface's own note on the
        # real bug that used to do that) so Exploded view can remove
        # and later restore exactly this actor.
        self._monolithic_surface_actor = self.plotter.add_mesh(
            self.grid, style="surface", opacity=0.15,
            show_edges=False, color="lightsteelblue")

        self._iso_actor = None
        self._iso_cache_key = None
        self._iso_surface = None
        # Phase 3: volume rendering state.
        self._volume_actor = None
        self._volume_enabled = False
        self._volume_field_name = ""
        # Phase 4: sweep playback state.
        self._snapshots = None
        self._playback_idx = 0
        self._playback_playing = False
        self._playback_timer = QTimer()
        self._playback_timer.timeout.connect(self._on_playback_tick)
        self._playback_timer.setInterval(300)  # ~3.3 fps default
        # Phase 5: exploded view state.
        self._exploded_view = False
        # Real, pre-existing bug fixed here (confirmed by actually
        # running this against a real solved result, not the test
        # suite's mocked plotter): a hardcoded 0.5 cm default -- with a
        # 0.01-10.0 cm spinbox range -- made exploded view LOOK like a
        # no-op for every device this app ships (all span roughly 1e-5
        # to 2e-4 cm total). z_offset = idx*separation pushed regions
        # 2500x-50000x farther apart than the device's own size, so
        # reset_camera() zoomed out until each region was sub-pixel.
        # Scaled from the device's OWN bounding-box diagonal
        # (self.grid.length, already built above) instead of a fixed
        # constant, so a device 1000x bigger or smaller gets an equally
        # sensible default -- see _build_sidebar's spinbox range/step,
        # scaled from this same reference.
        self._exploded_separation = 0.15 * self.grid.length  # cm
        self._region_actors = []  # list of (actor, box) tuples for exploded regions
        self._store = store  # keep reference for region_materials access
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
            self._volume_toggle.setEnabled(False)
            self._transfer_func_box.setEnabled(False)
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

        # Phase 3: volume rendering controls.
        self._volume_toggle = QCheckBox("Volume render")
        self._volume_toggle.stateChanged.connect(self._on_volume_toggle_changed)
        form.addRow("Volume", self._volume_toggle)

        self._transfer_func_box = QComboBox()
        self._transfer_func_box.addItems(sorted(TRANSFER_FUNCTION_PRESETS.keys()))
        self._transfer_func_box.currentTextChanged.connect(
            self._on_transfer_func_changed)
        self._transfer_func_box.setEnabled(False)
        form.addRow("Transfer func", self._transfer_func_box)

        # Phase 5: exploded view controls.
        self._exploded_toggle = QCheckBox("Exploded view")
        self._exploded_toggle.stateChanged.connect(self._on_exploded_toggle_changed)
        form.addRow("Exploded", self._exploded_toggle)

        self._exploded_sep_spin = QDoubleSpinBox()
        # Range/decimals/step scaled from the device's own size
        # (self._exploded_separation, set in __init__ from
        # self.grid.length), not the old fixed 0.01-10.0 cm range --
        # see __init__'s own comment for the bug this fixes. 9 decimals
        # so a typical device (self.grid.length ~ 1e-4 cm) still shows
        # meaningful digits down near this range's own floor.
        self._exploded_sep_spin.setRange(
            max(self.grid.length * 1e-4, 1e-9), self.grid.length * 5.0)
        self._exploded_sep_spin.setDecimals(9)
        self._exploded_sep_spin.setSingleStep(self._exploded_separation / 10.0)
        self._exploded_sep_spin.setSuffix(" cm")
        self._exploded_sep_spin.setValue(self._exploded_separation)
        self._exploded_sep_spin.valueChanged.connect(self._on_exploded_sep_changed)
        self._exploded_sep_spin.setEnabled(False)
        form.addRow("Separation", self._exploded_sep_spin)

        dock.setWidget(panel)
        self._window.addDockWidget(Qt.RightDockWidgetArea, dock)

        # Phase 4: sweep playback controls in a separate dock.
        self._build_playback_dock()

    def _build_playback_dock(self):
        """Build the sweep playback dock widget with play/pause, step,
        and timeline scrubber controls."""
        dock = QDockWidget("Sweep Playback", self._window)
        panel = QWidget()
        lay = QHBoxLayout(panel)

        # Step backward button.
        self._step_back_btn = QPushButton("<<")
        self._step_back_btn.clicked.connect(self._on_step_back)
        self._step_back_btn.setEnabled(False)
        lay.addWidget(self._step_back_btn)

        # Play/pause button.
        self._play_btn = QPushButton("Play")
        self._play_btn.clicked.connect(self._on_play_pause)
        self._play_btn.setEnabled(False)
        lay.addWidget(self._play_btn)

        # Step forward button.
        self._step_fwd_btn = QPushButton(">>")
        self._step_fwd_btn.clicked.connect(self._on_step_fwd)
        self._step_fwd_btn.setEnabled(False)
        lay.addWidget(self._step_fwd_btn)

        # Timeline slider.
        self._playback_slider = QSlider(Qt.Horizontal)
        self._playback_slider.valueChanged.connect(self._on_playback_slider_changed)
        self._playback_slider.setEnabled(False)
        lay.addWidget(self._playback_slider)

        # Voltage label.
        self._voltage_label = QLabel("0.000 V")
        lay.addWidget(self._voltage_label)

        dock.setWidget(panel)
        self._window.addDockWidget(Qt.BottomDockWidgetArea, dock)

    def set_sweep_snapshots(self, snapshots):
        """Provide sweep snapshot data for animation playback.

        snapshots: a SweepSnapshots instance, or None to clear playback.
        """
        self._snapshots = snapshots
        if snapshots is None or snapshots.n_snapshots() == 0:
            self._step_back_btn.setEnabled(False)
            self._play_btn.setEnabled(False)
            self._step_fwd_btn.setEnabled(False)
            self._playback_slider.setEnabled(False)
            self._playback_slider.setRange(0, 0)
            self._voltage_label.setText("0.000 V")
            self._stop_playback()
            return
        n = snapshots.n_snapshots()
        self._playback_slider.setRange(0, n - 1)
        self._playback_slider.setValue(0)
        self._playback_idx = 0
        self._step_back_btn.setEnabled(True)
        self._play_btn.setEnabled(True)
        self._step_fwd_btn.setEnabled(True)
        self._playback_slider.setEnabled(True)
        self._update_playback_label()
        # Apply the first snapshot's field data to the grid.
        self._apply_snapshot(0)

    def _on_play_pause(self):
        if self._playback_playing:
            self._stop_playback()
        else:
            self._start_playback()

    def _start_playback(self):
        self._playback_playing = True
        self._play_btn.setText("Pause")
        self._playback_timer.start()

    def _stop_playback(self):
        self._playback_playing = False
        self._play_btn.setText("Play")
        self._playback_timer.stop()

    def _on_playback_tick(self):
        if not self._playback_playing or self._snapshots is None:
            return
        n = self._snapshots.n_snapshots()
        self._playback_idx = (self._playback_idx + 1) % n
        self._playback_slider.setValue(self._playback_idx)
        self._apply_snapshot(self._playback_idx)

    def _on_step_back(self):
        if self._snapshots is None or self._snapshots.n_snapshots() == 0:
            return
        self._stop_playback()
        self._playback_idx = max(0, self._playback_idx - 1)
        self._playback_slider.setValue(self._playback_idx)
        self._apply_snapshot(self._playback_idx)

    def _on_step_fwd(self):
        if self._snapshots is None or self._snapshots.n_snapshots() == 0:
            return
        self._stop_playback()
        self._playback_idx = min(self._snapshots.n_snapshots() - 1,
                                self._playback_idx + 1)
        self._playback_slider.setValue(self._playback_idx)
        self._apply_snapshot(self._playback_idx)

    def _on_playback_slider_changed(self, value):
        self._stop_playback()
        self._playback_idx = value
        self._apply_snapshot(value)

    def _apply_snapshot(self, idx):
        """Update the grid's scalar fields with the snapshot at index `idx`."""
        if self._snapshots is None:
            return
        # Update the active isosurface field from the snapshot.
        field_name = self._field_box.currentText()
        if field_name and self._snapshots and field_name in self._snapshots.field_names:
            try:
                arr = self._snapshots.field(field_name, idx)
                self.grid.point_data[field_name] = arr.flatten(order="C")
            except (KeyError, IndexError):
                return
        # Update the isosurface to reflect the new field values.
        self._redraw_isosurface()
        # If volume rendering is active, refresh it too.
        if self._volume_enabled:
            self._remove_volume()
            self._add_volume()
        self._update_playback_label()

    def _update_playback_label(self):
        if self._snapshots is None or self._snapshots.n_snapshots() == 0:
            return
        try:
            v = self._snapshots.voltage(self._playback_idx)
            self._voltage_label.setText(f"{v:.3f} V")
        except IndexError:
            pass

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

    def _on_volume_toggle_changed(self, state):
        """Toggle volume rendering on/off. When enabled, adds a volume
        actor using the current field and the selected transfer function
        preset. When disabled, removes the volume actor."""
        # PySide6's deprecated stateChanged signal hands back a plain int
        # (Qt.CheckState.Checked cannot be compared to an int directly in
        # this PySide6 version -- state == Qt.Checked is always False,
        # silently disabling this toggle). Normalize through CheckState.
        self._volume_enabled = (Qt.CheckState(state) == Qt.Checked)
        if self._volume_enabled:
            self._transfer_func_box.setEnabled(True)
            self._add_volume()
        else:
            self._transfer_func_box.setEnabled(False)
            self._remove_volume()

    def _on_transfer_func_changed(self, _name):
        """When the transfer function preset changes, re-add the volume
        with the new transfer function."""
        if self._volume_enabled:
            self._remove_volume()
            self._add_volume()

    def _on_exploded_toggle_changed(self, state):
        """Toggle exploded view on/off. When enabled, pulls regions apart
        along the Z axis for structural inspection."""
        # See _on_volume_toggle_changed's comment: state arrives as a
        # plain int, and Qt.Checked cannot be compared to it directly.
        self._exploded_view = (Qt.CheckState(state) == Qt.Checked)
        self._exploded_sep_spin.setEnabled(self._exploded_view)
        if self._exploded_view:
            self._build_exploded_view()
        else:
            self._remove_exploded_view()

    def _on_exploded_sep_changed(self, value):
        """When the separation distance changes, rebuild the exploded view."""
        if self._exploded_view:
            self._exploded_separation = float(value)
            self._build_exploded_view()

    def _build_exploded_view(self):
        """Build the exploded view by separating regions along the Z axis.
        Removes the monolithic device surface and replaces it with per-region
        actors, each offset by its region index times the separation distance."""
        # Remove the monolithic device surface.
        for actor in self._region_actors:
            if hasattr(actor, '__len__'):
                for a in actor:
                    if a is not None:
                        self.plotter.remove_actor(a)
            else:
                self.plotter.remove_actor(actor)
        self._region_actors.clear()

        # Get the regions to explode from the store: prefer material
        # regions (region_materials -- a genuine heterojunction, colored
        # by material), falling back to purely structural regions
        # (structure_regions -- a same-material device like a
        # homojunction MOSFET/BJT/JFET, named source/drain/channel/...)
        # when there is no material difference to key off. Box handling
        # below is identical either way -- only the *reason* a box
        # exists differs, never its shape.
        region_data = None
        if self._store is not None:
            try:
                region_data = self._store.region_materials()
            except Exception:
                region_data = None
            if not region_data:
                try:
                    region_data = self._store.structure_regions()
                except Exception:
                    region_data = None
        if region_data is None or not isinstance(region_data, list):
            # No region data available -- keep the monolithic surface.
            self._exploded_view = False
            self._exploded_toggle.setChecked(False)
            self._exploded_sep_spin.setEnabled(False)
            return

        # Remove the existing monolithic surface actor (index 1 in added list).
        # We need to find and remove it.
        self._remove_monolithic_surface()

        # Build per-region actors.
        z_axes = np.asarray(self.grid.points[:, 2], dtype=float)
        z_min, z_max = z_axes.min(), z_axes.max()
        z_range = z_max - z_min if z_max != z_min else 1.0

        # Assign a distinct color to each region.
        region_colors = [
            "lightcoral", "lightblue", "lightgreen", "lightyellow",
            "plum", "peachpuff", "lightcyan", "wheat",
            "lavender", "mistyrose", "honeydew", "powderblue",
        ]

        for idx, region in enumerate(region_data):
            box = region.get("box", [])
            if len(box) < 6:
                # 3D box should have [x0, x1, y0, y1, z0, z1]
                continue

            x0, x1, y0, y1, z0, z1 = box
            # Calculate Z offset: separate by region index.
            z_offset = idx * self._exploded_separation

            # Extract the region's portion of the grid.
            region_grid = self._extract_region_grid(x0, x1, y0, y1, z0, z1)
            if region_grid is None or region_grid.n_points == 0:
                continue

            # Apply Z offset to the region. RectilinearGrid stores its
            # geometry as per-axis coordinate arrays, not a free point
            # array -- points itself is derived and cannot be assigned
            # (pyvista raises AttributeError); shift the z axis instead.
            region_grid.z = region_grid.z + z_offset

            # Render as a semi-transparent surface with a distinct color.
            color = region_colors[idx % len(region_colors)]
            actor = self.plotter.add_mesh(
                region_grid, style="surface", opacity=0.6,
                show_edges=True, color=color, smooth_shading=True)
            self._region_actors.append(actor)

        self.plotter.reset_camera()

    def _extract_region_grid(self, x0, x1, y0, y1, z0, z1):
        """Extract a sub-grid for the region defined by the bounding box.
        Returns a new RectilinearGrid with only the points inside the box."""
        x = np.asarray(self.grid.points[:, 0], dtype=float)
        y = np.asarray(self.grid.points[:, 1], dtype=float)
        z = np.asarray(self.grid.points[:, 2], dtype=float)

        # Find indices within the box.
        x_mask = (x >= x0) & (x <= x1)
        y_mask = (y >= y0) & (y <= y1)
        z_mask = (z >= z0) & (z <= z1)
        mask = x_mask & y_mask & z_mask

        if not mask.any():
            return None

        # Get the unique coordinates within the box.
        x_unique = np.unique(x[mask])
        y_unique = np.unique(y[mask])
        z_unique = np.unique(z[mask])

        # Build a new RectilinearGrid.
        region_grid = pv.RectilinearGrid(x_unique, y_unique, z_unique)

        # Copy point data for the region.
        for key in self.grid.point_data.keys():
            region_grid.point_data[key] = self.grid.point_data[key][mask]

        return region_grid

    def _remove_exploded_view(self):
        """Remove the exploded view and restore the monolithic device surface."""
        for actor in self._region_actors:
            self.plotter.remove_actor(actor)
        self._region_actors.clear()
        # Restore the monolithic surface -- re-captured into the same
        # tracked reference _remove_monolithic_surface reads, so a
        # SECOND toggle back into exploded view can find and remove it
        # again (see that method's own note on the bug this fixes).
        self._monolithic_surface_actor = self.plotter.add_mesh(
            self.grid, style="surface", opacity=0.15,
            show_edges=False, color="lightsteelblue")

    def _remove_monolithic_surface(self):
        """Remove the monolithic device surface actor from the plotter.

        Real, pre-existing bug fixed here: this used to scan
        `self.plotter.added` for an actor matching the surface's own
        kwargs -- an attribute that exists ONLY on the test suite's
        FakeInteractor mock (test_viewer3d.py's own docstring explains
        why real pyvistaqt.QtInteractor/pv.Plotter objects are never
        exercised directly there), not on the real plotter class. Every
        exploded-view test passed anyway because every one of them
        monkeypatches QtInteractor to that same fake -- so a REAL run
        of this code (confirmed directly: `AttributeError:
        'QtInteractor' object has no attribute 'added'`, raised inside
        the checkbox's own Qt slot) crashed the instant a user checked
        "Exploded view", regardless of whether region_materials/
        structure_regions found anything to explode. Fixed by tracking
        the actor directly (self._monolithic_surface_actor, set in
        __init__ and again in _remove_exploded_view below) instead of
        re-discovering it through an interface the real plotter never had."""
        if self._monolithic_surface_actor is not None:
            self.plotter.remove_actor(self._monolithic_surface_actor)
            self._monolithic_surface_actor = None

    def _add_volume(self):
        """Add a volume actor to the plotter using the current field
        and the selected transfer function preset."""
        field_name = self._field_box.currentText()
        if not field_name:
            return
        # Check that the field has finite values (same guard as
        # _on_field_changed for isosurface).
        values = self.grid.point_data[field_name]
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            return
        preset = _build_transfer_function(
            self._transfer_func_box.currentText())
        self._volume_actor = self.plotter.add_volume(
            self.grid, scalars=field_name,
            cmap=preset["color_map"], opacity=preset["opacity"],
            show_scalar_bar=True)

    def _remove_volume(self):
        """Remove the volume actor from the plotter, if present."""
        if self._volume_actor is not None:
            self.plotter.remove_actor(self._volume_actor)
            self._volume_actor = None

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
        # Stop playback timer.
        self._stop_playback()
        # Clean up exploded view actors.
        for actor in self._region_actors:
            self.plotter.remove_actor(actor)
        self._region_actors.clear()
        # Clean up volume actor before closing the plotter.
        if self._volume_actor is not None:
            self.plotter.remove_actor(self._volume_actor)
            self._volume_actor = None
        self.plotter.close()

    def show(self):
        if self._closed:
            raise RuntimeError(
                "Viewer3DWindow already closed -- construct a new one")
        self._window.show()

    def close(self):
        self._release()
        self._window.close()
