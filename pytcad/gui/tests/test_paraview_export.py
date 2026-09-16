"""PARAVIEW-EXPORT-PLAN.md: paraview_export.py's export_vtu/
export_pvd_series (pure, headlessly testable) and Viewer3DWindow's
"Open in ParaView" launch handler.

Same FakeInteractor pattern as test_viewer3d.py: a real QMainWindow/
QDockWidget/QPushButton tree, a fake VTK render surface -- see that
file's own module docstring for why a real pyvistaqt.QtInteractor isn't
exercised under QT_QPA_PLATFORM=offscreen.
"""
import os
import sys
import json
import xml.etree.ElementTree as ET

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pyvista as pv
import pytest
from PySide6.QtWidgets import QApplication, QWidget

from gui.services import examples, paraview_export, viewer3d
from gui.services.result_store import NpzResultStore, SweepSnapshots
from gui.services.solver_runner import run_job


@pytest.fixture(scope="module")
def gapp():
    yield QApplication.instance() or QApplication([])


class FakeInteractor:
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


def test_export_vtu_round_trips_every_scalar_field(resistor_3d_store, tmp_path):
    out_path = tmp_path / "result.vtu"
    returned = paraview_export.export_vtu(resistor_3d_store, out_path)
    assert returned == out_path
    assert out_path.exists()

    reread = pv.read(str(out_path))
    axes = resistor_3d_store.mesh_axes()
    for name in resistor_3d_store.available_scalars():
        field = resistor_3d_store.scalar_field(name)
        assert name in reread.point_data
        assert np.array_equal(
            np.asarray(reread.point_data[name], dtype=float),
            np.asarray(field.values, dtype=float).flatten(order="C"))
    n = axes.axes["x"].size * axes.axes["y"].size * axes.axes["z"].size
    assert reread.n_points == n


def test_export_vtu_round_trips_vector_fields_when_present(resistor_3d_store, tmp_path):
    vector_names = resistor_3d_store.available_vectors()
    out_path = tmp_path / "result.vtu"
    paraview_export.export_vtu(resistor_3d_store, out_path)
    reread = pv.read(str(out_path))
    for name in vector_names:
        vf = resistor_3d_store.vector_field(name)
        assert name in reread.point_data
        # Re-derive the expected (n_points, 3) array the same way
        # attach_vector_field itself does, rather than re-implementing
        # the axis-stacking convention a second time in the test.
        axes = resistor_3d_store.mesh_axes()
        grid = viewer3d.build_rectilinear_grid(axes)
        viewer3d.attach_vector_field(grid, axes, vf)
        assert np.array_equal(
            np.asarray(reread.point_data[name], dtype=float),
            np.asarray(grid.point_data[name], dtype=float))


def _synthetic_snapshots(resistor_3d_store, n=3):
    """A synthetic multi-step SweepSnapshots built directly (no actual
    multi-point sweep solve) -- keeps this test fast and targeted at
    export_pvd_series's own logic, not the solver."""
    axes = resistor_3d_store.mesh_axes()
    nx, ny, nz = axes.axes["x"].size, axes.axes["y"].size, axes.axes["z"].size
    shape = (nz, ny, nx)
    doping = resistor_3d_store.scalar_field("doping").values
    voltages = np.linspace(0.0, 1.0, n)
    data = {}
    for i in range(n):
        # A distinct, checkable value per snapshot: doping scaled by
        # (i + 1), so a round-trip check can tell snapshots apart.
        data[("doping", i)] = (doping * (i + 1)).flatten(order="C")
    return SweepSnapshots(voltages=voltages, field_names=["doping"],
                          shape=shape, _data=data)


def test_export_pvd_series_writes_one_vtu_per_snapshot_and_a_valid_pvd(
        resistor_3d_store, tmp_path):
    snapshots = _synthetic_snapshots(resistor_3d_store, n=3)
    out_dir = tmp_path / "sweep_export"
    pvd_path = paraview_export.export_pvd_series(
        resistor_3d_store, snapshots, out_dir, "sweep")
    assert os.path.exists(pvd_path)

    tree = ET.parse(pvd_path)
    datasets = tree.getroot().find("Collection").findall("DataSet")
    assert len(datasets) == 3
    for i, ds in enumerate(datasets):
        assert float(ds.get("timestep")) == pytest.approx(snapshots.voltage(i))
        vtu_path = out_dir / ds.get("file")
        assert vtu_path.exists()
        reread = pv.read(str(vtu_path))
        expected = snapshots.field("doping", i).flatten(order="C")
        assert np.array_equal(
            np.asarray(reread.point_data["doping"], dtype=float), expected)


def test_export_pvd_series_refuses_empty_snapshots(resistor_3d_store, tmp_path):
    axes = resistor_3d_store.mesh_axes()
    nx, ny, nz = axes.axes["x"].size, axes.axes["y"].size, axes.axes["z"].size
    empty = SweepSnapshots(voltages=np.array([]), field_names=["doping"],
                           shape=(nz, ny, nx), _data={})
    with pytest.raises(ValueError, match="no sweep snapshots"):
        paraview_export.export_pvd_series(
            resistor_3d_store, empty, tmp_path / "out", "sweep")


def _fake_viewer3d_window(store, monkeypatch):
    monkeypatch.setattr(viewer3d, "QtInteractor", FakeInteractor)
    return viewer3d.Viewer3DWindow(store)


def test_open_in_paraview_launches_with_configured_path_and_last_export(
        gapp, resistor_3d_store, monkeypatch, tmp_path):
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    out_path = str(tmp_path / "result.vtu")
    win._last_export_path = out_path
    win._paraview_path_edit.setText("C:/fake/paraview.exe")

    calls = []
    monkeypatch.setattr(
        viewer3d.QProcess, "startDetached",
        staticmethod(lambda path, args: calls.append((path, args)) or True))

    win._on_open_in_paraview_clicked()
    assert calls == [("C:/fake/paraview.exe", [out_path])]


def test_open_in_paraview_reports_a_real_error_when_launch_fails(
        gapp, resistor_3d_store, monkeypatch, tmp_path):
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    win._last_export_path = str(tmp_path / "result.vtu")
    win._paraview_path_edit.setText("definitely-not-on-path")

    monkeypatch.setattr(
        viewer3d.QProcess, "startDetached",
        staticmethod(lambda path, args: False))

    warnings = []
    monkeypatch.setattr(
        viewer3d.QMessageBox, "warning",
        staticmethod(lambda *a, **k: warnings.append(a) or None))

    win._on_open_in_paraview_clicked()
    assert len(warnings) == 1
    assert "Could not launch ParaView" in warnings[0][1]


def test_open_in_paraview_does_nothing_without_a_prior_export(
        gapp, resistor_3d_store, monkeypatch):
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    assert win._last_export_path is None

    calls = []
    monkeypatch.setattr(
        viewer3d.QProcess, "startDetached",
        staticmethod(lambda path, args: calls.append((path, args)) or True))

    win._on_open_in_paraview_clicked()
    assert calls == []


def test_export_vtu_button_handler_writes_a_real_file(
        gapp, resistor_3d_store, monkeypatch, tmp_path):
    """Exercises the actual '_on_export_vtu_clicked' button handler, not
    just paraview_export.export_vtu directly underneath it -- this is
    the exact gap that let a real bug (the handler referenced
    'paraview_export' with no import in scope, a NameError caught only
    by clicking the button in the real running app, see
    PARAVIEW-EXPORT-PLAN.md) ship past every earlier test in this file."""
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    out_path = str(tmp_path / "result.vtu")
    monkeypatch.setattr(
        viewer3d.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (out_path, "")))

    win._on_export_vtu_clicked()

    assert os.path.exists(out_path)
    assert win._last_export_path == out_path
    assert win._open_in_paraview_btn.isEnabled() is True
    reread = pv.read(out_path)
    for name in resistor_3d_store.available_scalars():
        assert name in reread.point_data


def test_export_pvd_button_handler_writes_a_real_pvd(
        gapp, resistor_3d_store, monkeypatch, tmp_path):
    """Same real-handler check as above, for the animation export path."""
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    win.set_sweep_snapshots(_synthetic_snapshots(resistor_3d_store, n=2))
    out_dir = str(tmp_path / "sweep_export")
    monkeypatch.setattr(
        viewer3d.QFileDialog, "getExistingDirectory",
        staticmethod(lambda *a, **k: out_dir))

    win._on_export_pvd_clicked()

    assert win._last_export_path is not None
    assert os.path.exists(win._last_export_path)
    assert win._open_in_paraview_btn.isEnabled() is True


def test_export_pvd_button_only_enabled_once_snapshots_are_set(
        gapp, resistor_3d_store, monkeypatch):
    win = _fake_viewer3d_window(resistor_3d_store, monkeypatch)
    assert win._export_pvd_btn.isEnabled() is False

    snapshots = _synthetic_snapshots(resistor_3d_store, n=2)
    win.set_sweep_snapshots(snapshots)
    assert win._export_pvd_btn.isEnabled() is True

    win.set_sweep_snapshots(None)
    assert win._export_pvd_btn.isEnabled() is False
