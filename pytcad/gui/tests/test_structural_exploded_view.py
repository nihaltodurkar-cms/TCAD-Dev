"""v0.6 Phase 2f: the "structural" (region-based, not material-based)
half of exploded view, following up on
test_exploded_view_region_materials_bug.py's region_materials fix.

That fix only helps a genuine HETEROJUNCTION device (a region_materials
entry needs a non-silicon material) -- every 3D device this GUI ships
in the File menu (mosfet_3d, finfet_3d, bjt_3d, jfet_3d, pn_junction_3d)
is a plain-silicon HOMOjunction, so region_materials is always empty for
them and exploded view would still show nothing. DeviceSpec.
structure_regions (name + box, independent of material) closes that
gap: it carries a device's logical/geometric parts (source/drain/
channel, emitter/base/collector, ...) even when there is no material
difference, and viewer3d.py's _build_exploded_view falls back to it
whenever region_materials is empty.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from gui.services import examples
from gui.services.device_spec import DeviceSpec
from gui.services.result_store import NpzResultStore, SpecResultStore
from gui.services.solver_runner import run_job
from gui.services.structure_model import (
    BoundarySpec, ContactModel, MeshModel, RegionSpec, StructureModel,
)
from gui.services import viewer3d


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


# ---------------------------------------------------------------- wire format
def test_device_spec_round_trips_structure_regions(tmp_path):
    spec = examples.mosfet_3d_example_spec()
    assert spec.structure_regions == [
        {"name": "source", "box": [0.0, 3e-5, 0.0, 2e-5, 0.0, 1e-4]},
        {"name": "channel", "box": [3e-5, 9e-5, 0.0, 2e-5, 0.0, 1e-4]},
        {"name": "drain", "box": [9e-5, 1.2e-4, 0.0, 2e-5, 0.0, 1e-4]},
    ]
    path = str(tmp_path / "job.json")
    spec.to_json(path)
    back = DeviceSpec.from_json(path)
    assert back.structure_regions == spec.structure_regions


def test_old_job_file_without_structure_regions_key_still_loads(tmp_path):
    d = examples.mosfet_3d_example_spec().to_dict()
    assert "structure_regions" in d
    del d["structure_regions"]
    path = str(tmp_path / "old.json")
    json.dump(d, open(path, "w"))
    assert DeviceSpec.from_json(path).structure_regions is None


def test_malformed_structure_regions_entry_is_rejected():
    d = examples.mosfet_3d_example_spec().to_dict()
    d["structure_regions"] = [{"box": [0, 1, 0, 1, 0, 1]}]   # missing "name"
    with pytest.raises(ValueError, match="structure_regions"):
        DeviceSpec.from_dict(d)


# ---------------------------------------------------------------- shipped examples
@pytest.mark.parametrize("fn_name,expected_names", [
    ("mosfet_3d_example_spec", {"source", "channel", "drain"}),
    ("finfet_3d_example_spec", {"source", "channel", "drain"}),
    ("pn_junction_3d_example_spec", {"p_side", "n_side"}),
    ("bjt_3d_example_spec", {"emitter", "base", "collector"}),
    ("jfet_3d_example_spec", {"channel", "gate"}),
])
def test_shipped_3d_example_has_the_expected_named_regions(fn_name, expected_names):
    spec = getattr(examples, fn_name)()
    assert {r["name"] for r in spec.structure_regions} == expected_names
    x0, x1 = spec.mesh.axes["x"][0], spec.mesh.axes["x"][-1]
    y0, y1 = spec.mesh.axes["y"][0], spec.mesh.axes["y"][-1]
    z0, z1 = spec.mesh.axes["z"][0], spec.mesh.axes["z"][-1]
    for r in spec.structure_regions:
        bx0, bx1, by0, by1, bz0, bz1 = r["box"]
        assert x0 - 1e-12 <= bx0 <= bx1 <= x1 + 1e-12
        assert y0 - 1e-12 <= by0 <= by1 <= y1 + 1e-12
        assert z0 - 1e-12 <= bz0 <= bz1 <= z1 + 1e-12


def test_single_material_uniform_examples_have_no_structure_regions():
    """moscap_3d/resistor_3d genuinely have only ONE region each (a
    uniform bulk) -- structure_regions must stay None/absent, not a
    fabricated single-entry list."""
    assert examples.moscap_3d_example_spec().structure_regions is None
    assert examples.resistor_3d_example_spec().structure_regions is None


# ---------------------------------------------------------------- structure workbench
def _small_3d_two_region_structure():
    width_cm, height_cm, depth_cm = 4e-5, 1e-5, 1e-5
    structure = StructureModel(
        width_cm=width_cm, height_cm=height_cm, depth_cm=depth_cm,
        regions=[
            RegionSpec("left", "Left half", 0.0, 2e-5, 0.0, height_cm,
                      1e17, z_min=0.0, z_max=depth_cm),
            RegionSpec("right", "Right half", 2e-5, width_cm, 0.0, height_cm,
                      1e17, z_min=0.0, z_max=depth_cm),
        ],
        contacts=[
            ContactModel("left_c", "left", BoundarySpec("left"), V=0.0),
            ContactModel("right_c", "right", BoundarySpec("right"), V=0.1),
        ])
    mesh = MeshModel(nx=8, ny=6, nz=6, grading="uniform")
    return structure, mesh


def test_structure_model_emits_structure_regions_for_a_3d_structure():
    """Both regions here are plain SILICON (RegionSpec.material
    defaults to it) -- region_materials must stay empty, but
    structure_regions must carry BOTH named regions regardless."""
    structure, mesh = _small_3d_two_region_structure()
    spec = structure.to_device_spec(mesh)
    assert spec.mesh.dimensionality == 3
    assert spec.region_materials is None
    assert {r["name"] for r in spec.structure_regions} == {"Left half", "Right half"}


def test_structure_model_emits_no_structure_regions_for_a_2d_structure():
    """2D has no 3D viewer at all -- structure_regions must stay None,
    same additive/absent-means-N/A contract as region_materials."""
    from gui.tests.test_structure_to_device_spec import _small_mosfet_like_structure
    structure, mesh = _small_mosfet_like_structure()
    spec = structure.to_device_spec(mesh)
    assert spec.mesh.dimensionality == 2
    assert spec.structure_regions is None


# ---------------------------------------------------------------- result store
def test_spec_result_store_answers_structure_regions_honestly():
    spec = examples.mosfet_3d_example_spec()
    assert SpecResultStore(spec).structure_regions() is None


def test_npz_result_store_round_trips_structure_regions(tmp_path):
    spec = examples.mosfet_3d_example_spec()
    job = str(tmp_path / "job.json")
    out = str(tmp_path / "out.npz")
    spec.to_json(job)
    run_job(job, out)
    store = NpzResultStore(out)
    assert store.structure_regions() == spec.structure_regions
    assert store.region_materials() is None    # homojunction: no material key


# ---------------------------------------------------------------- viewer3d integration
def test_exploded_view_falls_back_to_structure_regions_on_a_homojunction_device(
        gapp, tmp_path, monkeypatch):
    """The end-to-end regression guard for this feature: a real solved
    mosfet_3d result (no region_materials at all) still gets real,
    named per-region actors through the REAL Viewer3DWindow."""
    spec = examples.mosfet_3d_example_spec()
    job = str(tmp_path / "job.json")
    out = str(tmp_path / "out.npz")
    spec.to_json(job)
    run_job(job, out)
    store = NpzResultStore(out)
    assert store.region_materials() is None

    monkeypatch.setattr(viewer3d, "QtInteractor", FakeInteractor)
    win = viewer3d.Viewer3DWindow(store)
    win._exploded_toggle.setCheckState(Qt.Checked)

    assert win._exploded_view is True
    assert len(win._region_actors) == 3   # source, channel, drain


def test_exploded_view_prefers_region_materials_over_structure_regions(
        gapp, monkeypatch):
    """When a store carries BOTH (a heterojunction device authored with
    named regions too), the material-colored region_materials list
    wins -- structure_regions is a fallback, not a second, competing
    source of truth."""
    from gui.services.result_store import MeshAxes, ScalarField

    class _BothStore:
        def mesh_axes(self):
            return MeshAxes(axes={"x": [0.0, 1.0], "y": [0.0, 1.0],
                                  "z": [0.0, 1.0]}, dimensionality=3)
        def available_scalars(self):
            return ["doping"]
        def scalar_field(self, name):
            return ScalarField(name="doping", values=np.ones((2, 2, 2)),
                               unit="cm^-3")
        def region_materials(self):
            return [{"material": "GaAs", "box": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]}]
        def structure_regions(self):
            return [{"name": "should_not_be_used",
                    "box": [0.0, 0.5, 0.0, 1.0, 0.0, 1.0]},
                   {"name": "also_not_used",
                    "box": [0.5, 1.0, 0.0, 1.0, 0.0, 1.0]}]

    monkeypatch.setattr(viewer3d, "QtInteractor", FakeInteractor)
    win = viewer3d.Viewer3DWindow(_BothStore())
    win._exploded_toggle.setCheckState(Qt.Checked)

    assert win._exploded_view is True
    # one region (region_materials), not two (structure_regions)
    assert len(win._region_actors) == 1
