"""3D device authoring, GUI wiring phase: setDomainDepth/setRegionZBounds
expose the domain model's existing z-extent support (StructureModel.
depth_cm, RegionSpec.z_min/z_max, MeshModel.nz -- already proven to
build a real 3D DeviceSpec bit-identical to resistor_3d_example_spec(),
see tests/test_workbench_m1.py) through AppController, headlessly the
same way test_structure_controller.py tests the 2D surface."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import pytest
from PySide6.QtCore import QCoreApplication

from gui.controllers.app_controller import AppController


@pytest.fixture(scope="module")
def qapp():
    yield QCoreApplication.instance() or QCoreApplication([])


def test_domain_starts_2d(qapp):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    assert app.is3D is False
    assert app.domainDepthCm == 0.0
    assert app.meshNz == 0


def test_set_domain_depth_makes_the_structure_3d_and_is_undoable(qapp):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    app.setDomainDepth(2e-4, 5)
    assert app.is3D is True
    assert app.domainDepthCm == 2e-4
    assert app.meshNz == 5
    assert app.structure.depth_cm == 2e-4
    assert app.mesh_model.nz == 5
    app.undo()
    assert app.is3D is False
    assert app.structure.depth_cm is None
    assert app.mesh_model.nz is None
    app.redo()
    assert app.is3D is True


def test_set_domain_depth_zero_clears_back_to_2d(qapp):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    app.setDomainDepth(2e-4, 5)
    app.setDomainDepth(0.0, 0)
    assert app.is3D is False
    assert app.structure.depth_cm is None
    assert app.mesh_model.nz is None


def test_set_domain_depth_rejects_invalid_nz(qapp):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    errors = []
    app.errorRaised.connect(lambda title, msg: errors.append((title, msg)))
    app.setDomainDepth(2e-4, 1)
    assert errors, "expected errorRaised for nz < 2"
    assert app.is3D is False


def test_set_region_z_bounds_is_undoable(qapp):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    app.setDomainDepth(2e-4, 5)
    region_id = app.structure.regions[0].id
    app.setRegionZBounds(region_id, 0.0, 1e-4)
    region = app.structure.find_region(region_id)
    assert (region.z_min, region.z_max) == (0.0, 1e-4)
    app.undo()
    region = app.structure.find_region(region_id)
    assert region.z_min is None and region.z_max is None


def test_region_list_model_exposes_z_bounds(qapp):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    app.setDomainDepth(2e-4, 5)
    region_id = app.structure.regions[0].id
    app.setRegionZBounds(region_id, 0.0, 1e-4)
    model = app.regionListModel
    row = next(i for i in range(model.rowCount())
               if model.data(model.index(i, 0), model.IdRole) == region_id)
    z = model.data(model.index(row, 0), model.BoundsZRole)
    assert z == [0.0, 1e-4]


def test_fully_specified_3d_structure_builds_a_real_device_spec(qapp):
    """The end-to-end click-path: set domain depth, set every region's
    z-bounds, and to_device_spec() (already exercised by
    test_workbench_m1.py's 3D-authoring tests) must build without
    raising -- this is the "Build 3D device" path, now reachable
    entirely through AppController Slots rather than hand-built Python.

    3D device authoring phase 1 is ohmic-contacts-only (no gates) and
    has no range restriction on a 3D contact face (StructureModel's own
    documented phase-1 limits), so this uses a plain two-terminal
    resistor-like structure rather than the mosfet template (whose
    source/drain contacts are range-restricted and whose gate has no
    3D Vfb resolution)."""
    from gui.services.structure_model import (
        StructureModel, RegionSpec, ContactModel, BoundarySpec, MeshModel)
    app = AppController()
    structure = StructureModel(width_cm=1e-4, height_cm=1e-4, regions=[
        RegionSpec("body", "Body", 0.0, 1e-4, 0.0, 1e-4, 1e17),
    ], contacts=[
        ContactModel("left_c", "left", BoundarySpec("left"), V=0.0),
        ContactModel("right_c", "right", BoundarySpec("right"), V=0.1),
    ])
    mesh = MeshModel(nx=10, ny=10)
    app.adoptStructure(structure, mesh, "3D test fixture")
    app.setDomainDepth(2e-4, 4)
    for region in list(app.structure.regions):
        app.setRegionZBounds(region.id, 0.0, 2e-4)
    assert app.structureValidationErrors == []
    spec = app.structure.to_device_spec(app.mesh_model)
    assert spec.mesh.dimensionality == 3
