"""3D-VISUALIZATION-PLAN.md Phase 1/2: build_rectilinear_grid()/
extract_isosurface() (pure, headlessly testable) and
AppController.openViewer3d()'s dimensionality gate.

Viewer3DWindow's WIDGET CONSTRUCTION AND SIGNAL WIRING (the field/level/
colormap sidebar) ARE exercised here, for real, with a real QMainWindow/
QComboBox/QDoubleSpinBox -- this needs a real QApplication (not just
QGuiApplication), which is why gui/app.py's bootstrap and this suite's
session-scoped Qt fixture (gui/tests/conftest.py's `_qt_application`)
both construct QApplication now: QWidget construction hard-aborts the
whole process without one ("QWidget: Cannot create a QWidget without
QApplication", confirmed directly -- this was a real bug in the
original Phase 1 landing, since gui/app.py used to construct a bare
QGuiApplication, which would have crashed the entire app the first time
a real user clicked "View in 3D").

What's still NOT exercised: the actual `pyvistaqt.QtInteractor` (VTK's
live render window) -- it does its own windowing-system calls
independent of Qt's platform plugin, and building one under
QT_QPA_PLATFORM=offscreen raises an X11 BadWindow error rather than a
clean no-op (confirmed directly). Every test that constructs a real
Viewer3DWindow monkeypatches `viewer3d.QtInteractor` to a lightweight
fake that records add_mesh/remove_actor calls -- real widget tree, real
signal wiring, fake GL surface.
"""
import os, sys, json, tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QWidget

from gui import app as gui_app
from gui.services import examples
from gui.services.result_store import MeshAxes, NpzResultStore, ScalarField
from gui.services.solver_runner import run_job
from gui.services import viewer3d
from gui.services.viewer3d import build_rectilinear_grid


@pytest.fixture(scope="module")
def gapp():
    yield QApplication.instance() or QApplication([])


class FakeInteractor:
    """Stands in for pyvistaqt.QtInteractor: records every add_mesh/
    remove_actor call instead of touching a real GL context, so
    Viewer3DWindow's sidebar wiring can be tested with a real widget
    tree around it."""

    def __init__(self, parent=None):
        self.interactor = QWidget(parent)
        self.added = []
        self.removed = []

    def add_mesh(self, mesh, **kwargs):
        actor = object()
        self.added.append((mesh, kwargs, actor))
        return actor

    def remove_actor(self, actor):
        self.removed.append(actor)

    def reset_camera(self):
        pass

    def close(self):
        pass


@pytest.fixture()
def resistor_3d_store(tmp_path):
    spec = examples.resistor_3d_example_spec()
    job_path = str(tmp_path / "job.json")
    out_path = str(tmp_path / "out.npz")
    with open(job_path, "w") as fh:
        json.dump(spec.to_dict(), fh)
    run_job(job_path, out_path)
    return NpzResultStore(out_path)


def test_build_rectilinear_grid_matches_mesh_axes(resistor_3d_store):
    axes = resistor_3d_store.mesh_axes()
    grid = build_rectilinear_grid(axes)
    nx = len(axes.axes["x"])
    ny = len(axes.axes["y"])
    nz = len(axes.axes["z"])
    assert grid.n_points == nx * ny * nz
    assert np.isclose(grid.bounds[0], min(axes.axes["x"]))
    assert np.isclose(grid.bounds[1], max(axes.axes["x"]))
    assert np.isclose(grid.bounds[4], min(axes.axes["z"]))
    assert np.isclose(grid.bounds[5], max(axes.axes["z"]))


def test_build_rectilinear_grid_field_ordering_matches_pytcad_node_order(resistor_3d_store):
    """The doping field carried as point_data must line up with the mesh
    node it actually belongs to, not merely have the right count --
    check the actual value at a known corner node against the array
    pytcad itself wrote."""
    axes = resistor_3d_store.mesh_axes()
    field = resistor_3d_store.scalar_field("doping")
    grid = build_rectilinear_grid(axes, field)

    # The i=0,j=0,k=0 corner: node index 0 in both pytcad's C-order
    # array and VTK's point order (per build_rectilinear_grid's own
    # docstring claim, verified here rather than trusted).
    expected = field.values[0, 0, 0]
    assert grid.point_data["doping"][0] == pytest.approx(expected)
    x0 = min(axes.axes["x"])
    y0 = min(axes.axes["y"])
    z0 = min(axes.axes["z"])
    corner_point = grid.points[0]
    assert np.allclose(corner_point, [x0, y0, z0])


def test_build_rectilinear_grid_rejects_non_3d_mesh():
    axes = MeshAxes(axes={"x": [0.0, 1.0], "y": [0.0, 1.0]}, dimensionality=2)
    with pytest.raises(ValueError, match="requires a 3D mesh"):
        build_rectilinear_grid(axes)


def test_build_rectilinear_grid_rejects_a_field_with_the_wrong_shape():
    axes = MeshAxes(axes={"x": [0.0, 1.0], "y": [0.0, 1.0], "z": [0.0, 1.0]},
                    dimensionality=3)
    bad_field = ScalarField(name="doping", values=np.zeros((3, 3, 3)), unit="cm^-3")
    with pytest.raises(ValueError, match="expected"):
        build_rectilinear_grid(axes, bad_field)


def test_open_viewer3d_refuses_without_a_result(gapp):
    from gui.controllers.app_controller import AppController
    ctl = AppController()
    ctl._store = None
    errors = []
    ctl.errorRaised.connect(lambda summary, details: errors.append(summary))
    ctl.openViewer3d()
    assert errors == ["Nothing to view in 3D"]
    assert ctl._viewer3d_window is None


def test_open_viewer3d_refuses_without_a_solved_result_even_if_dimensionality_would_pass(gapp):
    """An unsolved preview store (loadExample() before any Run) must
    refuse with "Nothing to view in 3D", not fall through to the
    dimensionality check -- even when its dimensionality happens to be
    3 (mesh_axes() works on a SpecResultStore before any solve)."""
    from gui.controllers.app_controller import AppController
    from gui.services.result_store import SpecResultStore
    ctl = AppController()
    ctl.loadExample("resistor_3d")
    ctl._store = SpecResultStore(ctl.spec)
    errors = []
    ctl.errorRaised.connect(lambda summary, details: errors.append(summary))
    ctl.openViewer3d()
    assert errors == ["Nothing to view in 3D"]
    assert ctl._viewer3d_window is None


def test_open_viewer3d_refuses_for_a_solved_2d_result(gapp, tmp_path):
    from gui.controllers.app_controller import AppController
    from gui.services.result_store import NpzResultStore
    from gui.services.solver_runner import run_job
    import json

    spec = examples.mosfet_example_spec()
    job_path = str(tmp_path / "job2d.json")
    out_path = str(tmp_path / "out2d.npz")
    with open(job_path, "w") as fh:
        json.dump(spec.to_dict(), fh)
    run_job(job_path, out_path)

    ctl = AppController()
    ctl._store = NpzResultStore(out_path)
    errors = []
    ctl.errorRaised.connect(lambda summary, details: errors.append(summary))
    ctl.openViewer3d()
    assert errors == ["Not a 3D result"]
    assert ctl._viewer3d_window is None


def test_open_viewer3d_accepts_a_real_3d_result(gapp, resistor_3d_store, monkeypatch):
    """Without actually opening a live VTK window (see module docstring),
    confirm openViewer3d() gets past the dimensionality gate and hands
    Viewer3DWindow the real store -- patch Viewer3DWindow itself out so
    the test never touches VTK's windowing calls."""
    from gui.controllers.app_controller import AppController
    from gui.services import viewer3d

    built = {}

    class FakeWindow:
        def __init__(self, store, title="PyTCAD 3D Viewer"):
            built["store"] = store
        def show(self):
            built["shown"] = True
        def close(self):
            pass

    monkeypatch.setattr(viewer3d, "Viewer3DWindow", FakeWindow)
    ctl = AppController()
    ctl._store = resistor_3d_store
    ctl.openViewer3d()
    assert built.get("shown") is True
    assert built["store"] is resistor_3d_store
    assert isinstance(ctl._viewer3d_window, FakeWindow)


def test_view_in_3d_button_disabled_without_a_3d_result(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    controller.loadExample("mosfet_2d")
    button = root.findChild(object, "viewIn3dButton")
    assert button is not None
    assert button.property("enabled") is False


def test_view_in_3d_button_enabled_for_a_3d_result(gapp, resistor_3d_store):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    controller._store = resistor_3d_store
    controller.resultChanged.emit()
    button = root.findChild(object, "viewIn3dButton")
    assert button is not None
    assert button.property("enabled") is True


# ----------------------------------------------------------------------
# Phase 2: isosurfaces
# ----------------------------------------------------------------------
def test_extract_isosurface_at_a_real_level_is_nonempty(resistor_3d_store):
    from gui.services.viewer3d import extract_isosurface
    axes = resistor_3d_store.mesh_axes()
    field = resistor_3d_store.scalar_field("potential")
    grid = build_rectilinear_grid(axes, field)
    vmin, vmax = float(field.values.min()), float(field.values.max())
    surface = extract_isosurface(grid, "potential", (vmin + vmax) / 2.0)
    assert surface.n_points > 0


def test_extract_isosurface_outside_the_field_range_is_empty_not_a_crash(resistor_3d_store):
    from gui.services.viewer3d import extract_isosurface
    axes = resistor_3d_store.mesh_axes()
    field = resistor_3d_store.scalar_field("potential")
    grid = build_rectilinear_grid(axes, field)
    vmax = float(field.values.max())
    surface = extract_isosurface(grid, "potential", vmax + 1000.0)
    assert surface.n_points == 0


def test_extract_isosurface_rejects_an_unknown_field(resistor_3d_store):
    from gui.services.viewer3d import extract_isosurface
    axes = resistor_3d_store.mesh_axes()
    grid = build_rectilinear_grid(axes)
    with pytest.raises(KeyError, match="no scalar field"):
        extract_isosurface(grid, "not_a_real_field", 0.0)


def test_attach_scalar_field_puts_every_available_field_on_one_grid(resistor_3d_store):
    from gui.services.viewer3d import attach_scalar_field
    axes = resistor_3d_store.mesh_axes()
    grid = build_rectilinear_grid(axes)
    for name in resistor_3d_store.available_scalars():
        attach_scalar_field(grid, axes, resistor_3d_store.scalar_field(name))
    assert set(grid.point_data.keys()) == set(resistor_3d_store.available_scalars())


def _fake_viewer3d_window(store, monkeypatch):
    from gui.services import viewer3d
    monkeypatch.setattr(viewer3d, "QtInteractor", FakeInteractor)
    return viewer3d.Viewer3DWindow(store)


def test_viewer3d_window_defaults_to_doping_and_shows_base_mesh(gapp, resistor_3d_store, monkeypatch):
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    assert win._field_box.currentText() == "doping"
    field_names = {win._field_box.itemText(i) for i in range(win._field_box.count())}
    assert field_names == set(resistor_3d_store.available_scalars())
    # outline + translucent surface, always present regardless of field
    assert len(win.plotter.added) >= 2


def test_viewer3d_window_degenerate_field_adds_no_isosurface_actor(gapp, resistor_3d_store, monkeypatch):
    """The example device is uniformly doped (a resistor bar, by
    design) -- doping's min == max, so the isosurface level range
    collapses to a single point and VTK's contour filter correctly
    produces an empty surface. Confirms the "no crash" contract holds
    for the one field this very demo device actually exercises it on,
    not just a synthetic test case."""
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    assert win._level_box.minimum() == win._level_box.maximum()
    assert win._iso_actor is None


def test_viewer3d_window_switching_field_updates_level_range_and_isosurface(gapp, resistor_3d_store, monkeypatch):
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    base_actor_count = len(win.plotter.added)

    win._field_box.setCurrentText("potential")

    field = resistor_3d_store.scalar_field("potential")
    assert win._level_box.minimum() == pytest.approx(float(field.values.min()))
    assert win._level_box.maximum() == pytest.approx(float(field.values.max()))
    # potential genuinely varies across the biased bar -> a real
    # isosurface actor gets added (unlike the degenerate doping case).
    assert len(win.plotter.added) == base_actor_count + 1
    assert win._iso_actor is not None
    _, kwargs, _ = win.plotter.added[-1]
    assert kwargs["scalars"] == "potential"


def test_viewer3d_window_colormap_change_redraws_the_isosurface(gapp, resistor_3d_store, monkeypatch):
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    win._field_box.setCurrentText("potential")
    actor_count = len(win.plotter.added)
    removed_count = len(win.plotter.removed)

    win._colormap_box.setCurrentText("plasma")

    assert len(win.plotter.removed) == removed_count + 1
    assert len(win.plotter.added) == actor_count + 1
    _, kwargs, _ = win.plotter.added[-1]
    assert kwargs["cmap"] == "plasma"


def test_viewer3d_window_colormap_change_does_not_recompute_the_surface(gapp, resistor_3d_store, monkeypatch):
    """A colormap-only change must reuse the cached isosurface geometry
    (same PolyData object) rather than re-running grid.contour()."""
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    win._field_box.setCurrentText("potential")
    surface_before = win._iso_surface

    win._colormap_box.setCurrentText("plasma")

    assert win._iso_surface is surface_before


def test_viewer3d_window_close_is_idempotent_and_native_close_releases_plotter(gapp, resistor_3d_store, monkeypatch):
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)

    # The native window-manager close path (_Viewer3DMainWindow.closeEvent)
    # must release the plotter too, not just Qt's explicit close().
    win._window.close()
    assert win._closed is True

    # Calling close() again (e.g. AppController closing an already-closed
    # window) must not raise or double-release.
    win.close()


def test_viewer3d_window_show_after_close_refuses(gapp, resistor_3d_store, monkeypatch):
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    win.close()
    with pytest.raises(RuntimeError, match="already closed"):
        win.show()


def test_viewer3d_window_all_nan_field_disables_level_without_crashing(gapp, monkeypatch):
    from gui.services import viewer3d

    class _AllNanStore:
        def mesh_axes(self):
            return MeshAxes(axes={"x": [0.0, 1.0], "y": [0.0, 1.0],
                                  "z": [0.0, 1.0]}, dimensionality=3)
        def available_scalars(self):
            return ["broken"]
        def scalar_field(self, name):
            return ScalarField(name="broken",
                               values=np.full((2, 2, 2), np.nan), unit="V")

    monkeypatch.setattr(viewer3d, "QtInteractor", FakeInteractor)
    win = viewer3d.Viewer3DWindow(_AllNanStore())
    assert win._level_box.isEnabled() is False
    assert win._iso_actor is None


def test_open_viewer3d_reports_an_error_instead_of_crashing_on_construction_failure(gapp, resistor_3d_store, monkeypatch):
    from gui.controllers.app_controller import AppController
    from gui.services import viewer3d

    class ExplodingWindow:
        def __init__(self, store, title="PyTCAD 3D Viewer"):
            raise RuntimeError("boom")

    monkeypatch.setattr(viewer3d, "Viewer3DWindow", ExplodingWindow)
    ctl = AppController()
    ctl._store = resistor_3d_store
    errors = []
    ctl.errorRaised.connect(lambda summary, details: errors.append(summary))

    ctl.openViewer3d()  # must not raise

    assert errors == ["Could not open the 3D viewer"]
    assert ctl._viewer3d_window is None


# ----------------------------------------------------------------------
# Phase 4: sweep playback controls
# ----------------------------------------------------------------------
def test_viewer3d_window_playback_dock_exists(gapp, resistor_3d_store, monkeypatch):
    """The sweep playback dock should be created even when no snapshots
    are provided (it just stays disabled)."""
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    # The playback dock should exist and be visible.
    docks = [w for w in win._window.findChildren(QDockWidget)
             if w.windowTitle() == "Sweep Playback"]
    assert len(docks) == 1


def test_viewer3d_window_playback_controls_disabled_without_snapshots(gapp,
                                                                      resistor_3d_store,
                                                                      monkeypatch):
    """Without sweep snapshots, all playback controls should be disabled."""
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    assert win._step_back_btn.isEnabled() is False
    assert win._play_btn.isEnabled() is False
    assert win._step_fwd_btn.isEnabled() is False
    assert win._playback_slider.isEnabled() is False


def test_viewer3d_window_set_sweep_snapshots_enables_controls(gapp,
                                                              resistor_3d_store,
                                                              monkeypatch):
    """Setting sweep snapshots should enable all playback controls."""
    from gui.services.result_store import SweepSnapshots
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    snapshots = SweepSnapshots(
        voltages=np.array([0.0, 0.5, 1.0]),
        field_names=["potential"],
        shape=(2, 2, 2),
        _data={("potential", 0): np.zeros((2, 2, 2)),
               ("potential", 1): np.ones((2, 2, 2)),
               ("potential", 2): np.full((2, 2, 2), 2.0)},
    )
    win.set_sweep_snapshots(snapshots)
    assert win._step_back_btn.isEnabled() is True
    assert win._play_btn.isEnabled() is True
    assert win._step_fwd_btn.isEnabled() is True
    assert win._playback_slider.isEnabled() is True
    assert win._playback_slider.value() == 0


def test_viewer3d_window_step_forward_advances_index(gapp, resistor_3d_store,
                                                     monkeypatch):
    from gui.services.result_store import SweepSnapshots
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    snapshots = SweepSnapshots(
        voltages=np.array([0.0, 0.5, 1.0]),
        field_names=["potential"],
        shape=(2, 2, 2),
        _data={("potential", 0): np.zeros((2, 2, 2)),
               ("potential", 1): np.ones((2, 2, 2)),
               ("potential", 2): np.full((2, 2, 2), 2.0)},
    )
    win.set_sweep_snapshots(snapshots)
    assert win._playback_idx == 0
    win._on_step_fwd()
    assert win._playback_idx == 1
    assert win._playback_slider.value() == 1


def test_viewer3d_window_step_backward_advances_index(gapp, resistor_3d_store,
                                                       monkeypatch):
    from gui.services.result_store import SweepSnapshots
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    snapshots = SweepSnapshots(
        voltages=np.array([0.0, 0.5, 1.0]),
        field_names=["potential"],
        shape=(2, 2, 2),
        _data={("potential", 0): np.zeros((2, 2, 2)),
               ("potential", 1): np.ones((2, 2, 2)),
               ("potential", 2): np.full((2, 2, 2), 2.0)},
    )
    win.set_sweep_snapshots(snapshots)
    win._playback_idx = 2
    win._on_step_back()
    assert win._playback_idx == 1
    win._on_step_back()
    assert win._playback_idx == 0
    # Stepping back at index 0 should stay at 0.
    win._on_step_back()
    assert win._playback_idx == 0


def test_viewer3d_window_step_forward_at_end_stays_at_end(gapp,
                                                           resistor_3d_store,
                                                           monkeypatch):
    from gui.services.result_store import SweepSnapshots
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    snapshots = SweepSnapshots(
        voltages=np.array([0.0, 0.5, 1.0]),
        field_names=["potential"],
        shape=(2, 2, 2),
        _data={("potential", 0): np.zeros((2, 2, 2)),
               ("potential", 1): np.ones((2, 2, 2)),
               ("potential", 2): np.full((2, 2, 2), 2.0)},
    )
    win.set_sweep_snapshots(snapshots)
    win._playback_idx = 2
    win._on_step_fwd()
    # Should stay at the last index, not wrap.
    assert win._playback_idx == 2


def test_viewer3d_window_slider_change_updates_index(gapp, resistor_3d_store,
                                                      monkeypatch):
    from gui.services.result_store import SweepSnapshots
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    snapshots = SweepSnapshots(
        voltages=np.array([0.0, 0.5, 1.0]),
        field_names=["potential"],
        shape=(2, 2, 2),
        _data={("potential", 0): np.zeros((2, 2, 2)),
               ("potential", 1): np.ones((2, 2, 2)),
               ("potential", 2): np.full((2, 2, 2), 2.0)},
    )
    win.set_sweep_snapshots(snapshots)
    win._playback_slider.setValue(2)
    assert win._playback_idx == 2


def test_viewer3d_window_playback_timer_starts_and_stops(gapp,
                                                          resistor_3d_store,
                                                          monkeypatch):
    from gui.services.result_store import SweepSnapshots
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    snapshots = SweepSnapshots(
        voltages=np.array([0.0, 0.5, 1.0]),
        field_names=["potential"],
        shape=(2, 2, 2),
        _data={("potential", 0): np.zeros((2, 2, 2)),
               ("potential", 1): np.ones((2, 2, 2)),
               ("potential", 2): np.full((2, 2, 2), 2.0)},
    )
    win.set_sweep_snapshots(snapshots)
    assert win._playback_idx == 0
    # Manually trigger the timer callback to simulate playback.
    win._on_play_pause()
    assert win._playback_playing is True
    assert win._play_btn.text() == "Pause"
    win._on_play_pause()
    assert win._playback_playing is False
    assert win._play_btn.text() == "Play"


def test_viewer3d_window_clear_snapshots_disables_controls(gapp,
                                                            resistor_3d_store,
                                                            monkeypatch):
    from gui.services.result_store import SweepSnapshots
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    snapshots = SweepSnapshots(
        voltages=np.array([0.0, 0.5, 1.0]),
        field_names=["potential"],
        shape=(2, 2, 2),
        _data={("potential", 0): np.zeros((2, 2, 2)),
               ("potential", 1): np.ones((2, 2, 2)),
               ("potential", 2): np.full((2, 2, 2), 2.0)},
    )
    win.set_sweep_snapshots(snapshots)
    assert win._step_back_btn.isEnabled() is True
    # Clear snapshots.
    win.set_sweep_snapshots(None)
    assert win._step_back_btn.isEnabled() is False
    assert win._play_btn.isEnabled() is False
    assert win._playback_slider.isEnabled() is False


def test_viewer3d_window_release_stops_playback_timer(gapp,
                                                       resistor_3d_store,
                                                       monkeypatch):
    """Releasing the viewer (via close) should stop any running playback
    timer, preventing callbacks from firing after the window is closed."""
    from gui.services.result_store import SweepSnapshots
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    snapshots = SweepSnapshots(
        voltages=np.array([0.0, 0.5, 1.0]),
        field_names=["potential"],
        shape=(2, 2, 2),
        _data={("potential", 0): np.zeros((2, 2, 2)),
               ("potential", 1): np.ones((2, 2, 2)),
               ("potential", 2): np.full((2, 2, 2), 2.0)},
    )
    win.set_sweep_snapshots(snapshots)
    win._on_play_pause()
    assert win._playback_playing is True
    # Release the viewer.
    win._release()
    assert win._closed is True
    assert win._playback_playing is False


# ----------------------------------------------------------------------
# Phase 5: exploded view
# ----------------------------------------------------------------------
def test_viewer3d_window_exploded_toggle_exists(gapp, resistor_3d_store, monkeypatch):
    """The exploded view checkbox and separation spinbox should be
    present in the sidebar."""
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    assert hasattr(win, '_exploded_toggle')
    assert hasattr(win, '_exploded_sep_spin')
    assert win._exploded_toggle.text() == "Exploded view"
    assert win._exploded_sep_spin.value() == 0.5


def test_viewer3d_window_exploded_disabled_without_region_data(gapp,
                                                                resistor_3d_store,
                                                                monkeypatch):
    """Without region materials, enabling exploded view should disable
    itself and show a message."""
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    # The resistor_3d example has no region_materials, so enabling
    # exploded view should revert to off.
    win._exploded_toggle.setCheckState(Qt.Checked)
    assert win._exploded_view is False
    assert win._exploded_toggle.isChecked() is False
    assert win._exploded_sep_spin.isEnabled() is False


def test_viewer3d_window_exploded_with_region_data(gapp, monkeypatch):
    """With region materials, enabling exploded view should build per-region
    actors."""
    from gui.services.result_store import MeshAxes, ScalarField

    class _RegionStore:
        def mesh_axes(self):
            return MeshAxes(axes={"x": [0.0, 1.0], "y": [0.0, 1.0],
                                  "z": [0.0, 1.0]}, dimensionality=3)
        def available_scalars(self):
            return ["doping"]
        def scalar_field(self, name):
            return ScalarField(name="doping", values=np.ones((2, 2, 2)),
                               unit="cm^-3")
        def region_materials(self):
            return [
                {"material": "SILICON", "box": [0.0, 0.5, 0.0, 1.0, 0.0, 1.0]},
                {"material": "GaAs", "box": [0.5, 1.0, 0.0, 1.0, 0.0, 1.0]},
            ]

    monkeypatch.setattr(viewer3d, "QtInteractor", FakeInteractor)
    win = viewer3d.Viewer3DWindow(_RegionStore())
    # Enable exploded view.
    win._exploded_toggle.setCheckState(Qt.Checked)
    assert win._exploded_view is True
    assert win._exploded_sep_spin.isEnabled() is True
    # Should have built region actors.
    assert len(win._region_actors) > 0


def test_viewer3d_window_exploded_cleanup_on_release(gapp, monkeypatch):
    """Releasing the viewer should clean up exploded view actors."""
    from gui.services.result_store import MeshAxes, ScalarField

    class _RegionStore:
        def mesh_axes(self):
            return MeshAxes(axes={"x": [0.0, 1.0], "y": [0.0, 1.0],
                                  "z": [0.0, 1.0]}, dimensionality=3)
        def available_scalars(self):
            return ["doping"]
        def scalar_field(self, name):
            return ScalarField(name="doping", values=np.ones((2, 2, 2)),
                               unit="cm^-3")
        def region_materials(self):
            return [
                {"material": "SILICON", "box": [0.0, 0.5, 0.0, 1.0, 0.0, 1.0]},
            ]

    monkeypatch.setattr(viewer3d, "QtInteractor", FakeInteractor)
    win = viewer3d.Viewer3DWindow(_RegionStore())
    win._exploded_toggle.setCheckState(Qt.Checked)
    assert len(win._region_actors) > 0
    # Release the viewer.
    win._release()
    assert win._closed is True
    assert len(win._region_actors) == 0
