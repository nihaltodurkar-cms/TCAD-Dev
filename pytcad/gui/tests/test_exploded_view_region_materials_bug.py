"""Regression test for a real, pre-existing bug found while investigating
a user report that the 3D viewer's "Exploded view" toggle silently did
nothing: it ALWAYS did nothing, for every device (heterojunction
included), because the data path was never wired end to end.

Root cause, confirmed by direct reproduction (build a real heterojunction
Device3D spec, run it through the real solver, load the real result):

  1. Viewer3DWindow._build_exploded_view() (gui/services/viewer3d.py)
     calls self._store.region_materials().
  2. No ResultStore implementation defined that method at all -- not the
     ABC, not NpzResultStore, not SpecResultStore. Every real store threw
     AttributeError, silently swallowed by _build_exploded_view's own
     `except Exception: region_data = None`, so the checkbox just
     unchecked itself with zero visible feedback.
  3. Even with the method present, there was nothing to read:
     solver_runner.run_job() rasterizes spec.region_materials into the
     solve's per-node material grid (build_material_grid) but never
     stamped the ORIGINAL region_materials list back into the output
     .npz -- the data was discarded after the solve.

Same class of bug test_solver_engine_label_bug.py already documents for
has_record()/run_record(): a capability added to one call site without
becoming a protocol member (ResultStore ABC) with an honest default, so
every OTHER store silently misbehaved instead of answering honestly.

Fix: solver_runner.run_job() now stamps spec.region_materials into the
result (only when non-empty) as region_materials__meta; ResultStore
gained a region_materials() protocol member defaulting to None;
NpzResultStore overrides it to read the stamped data back.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gui.services.device_spec import (
    ContactSpec, DeviceSpec, DopingSpec, MeshSpec,
)
from gui.services.result_store import NpzResultStore, SpecResultStore
from gui.services.solver_runner import run_job
from gui.services import viewer3d


@pytest.fixture(scope="module")
def gapp():
    yield QApplication.instance() or QApplication([])


def _hetero_resistor_3d_spec():
    """The same resistor_3d_example_spec() geometry (see
    gui/services/examples.py), with the x >= 2e-4 half of the bar
    reassigned to GaAs -- a genuine two-material 3D device, which no
    shipped example builds (confirmed while investigating this bug)."""
    nx, ny, nz = 12, 8, 8
    x = np.linspace(0.0, 4e-4, nx)
    y = np.linspace(0.0, 1e-4, ny)
    z = np.linspace(0.0, 1e-4, nz)
    doping = np.full((nz, ny, nx), 1e17)
    jj, kk = np.meshgrid(np.arange(ny), np.arange(nz))
    jj, kk = jj.ravel().tolist(), kk.ravel().tolist()
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=3,
                      axes={"x": x.tolist(), "y": y.tolist(), "z": z.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[
            ContactSpec(name="left", kind="ohmic",
                        nodes={"i": [0] * len(jj), "j": jj, "k": kk}, V=0.0),
            ContactSpec(name="right", kind="ohmic",
                        nodes={"i": [nx - 1] * len(jj), "j": jj, "k": kk}, V=0.1),
        ],
        bias={"left": 0.0, "right": 0.1},
        region_materials=[
            {"material": "GaAs", "box": [2e-4, 4e-4, 0.0, 1e-4, 0.0, 1e-4]},
        ],
    )


def test_spec_result_store_answers_region_materials_honestly():
    """A pre-solve preview store legitimately carries no region data --
    same "most stores legitimately carry neither" ABC-default contract
    has_record()/run_record() already follow."""
    spec = _hetero_resistor_3d_spec()
    assert SpecResultStore(spec).region_materials() is None


def test_single_material_device_stamps_no_region_key(tmp_path):
    """The overwhelmingly common case (no region_materials at all) must
    stay a true no-op: no new key in the .npz, region_materials() ->
    None -- exercises the exact path every existing example takes."""
    from gui.services import examples
    spec = examples.resistor_3d_example_spec()
    assert not spec.region_materials
    job = str(tmp_path / "job.json")
    out = str(tmp_path / "out.npz")
    spec.to_json(job)
    run_job(job, out)
    d = np.load(out)
    assert "region_materials__meta" not in d.files
    assert NpzResultStore(out).region_materials() is None


def test_heterojunction_device_round_trips_region_materials(tmp_path):
    spec = _hetero_resistor_3d_spec()
    job = str(tmp_path / "job.json")
    out = str(tmp_path / "out.npz")
    spec.to_json(job)
    run_job(job, out)

    store = NpzResultStore(out)
    regions = store.region_materials()
    assert regions == spec.region_materials
    assert regions[0]["material"] == "GaAs"
    assert regions[0]["box"] == [2e-4, 4e-4, 0.0, 1e-4, 0.0, 1e-4]


class FakeInteractor:
    """Same fake pyvistaqt.QtInteractor test_viewer3d.py's own module
    docstring explains the need for -- records add_mesh/remove_actor
    instead of touching a real GL context."""

    def __init__(self, parent=None):
        from PySide6.QtWidgets import QWidget
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


def test_exploded_view_builds_real_region_actors_from_a_real_solved_result(
        gapp, tmp_path, monkeypatch):
    """The end-to-end regression guard: unlike every pre-existing
    exploded-view test (which hand-rolls a fake store defining
    region_materials() itself, so they never touched the real gap), this
    drives a REAL NpzResultStore from a REAL heterojunction solve through
    the REAL Viewer3DWindow -- the exact path that silently did nothing
    before this fix."""
    spec = _hetero_resistor_3d_spec()
    job = str(tmp_path / "job.json")
    out = str(tmp_path / "out.npz")
    spec.to_json(job)
    run_job(job, out)
    store = NpzResultStore(out)

    monkeypatch.setattr(viewer3d, "QtInteractor", FakeInteractor)
    win = viewer3d.Viewer3DWindow(store)
    win._exploded_toggle.setCheckState(Qt.Checked)

    assert win._exploded_view is True, (
        "exploded view reverted itself -- region_materials() still "
        "unreachable from a real solved result")
    assert win._exploded_sep_spin.isEnabled() is True
    assert len(win._region_actors) > 0, "no per-region actors were built"
