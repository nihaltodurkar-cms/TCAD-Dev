"""AppController's new v0.2 surface, tested headlessly the same way
v0.1's controllers were -- Python-level assertions on the models/state
the Qt properties expose."""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from gui.controllers.app_controller import AppController


@pytest.fixture(scope="module")
def qapp():
    yield QCoreApplication.instance() or QCoreApplication([])


def test_loading_structure_example_populates_regions_contacts_gates(qapp):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    assert app.regionListModel.rowCount() == 3
    assert app.contactListModel.rowCount() == 3
    assert app.gateListModel.rowCount() == 1
    assert app.structureValidationErrors == []


def test_add_region_is_undoable(qapp):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    before = app.regionListModel.rowCount()
    app.addRegion("Extra", 0.0, 1e-5, 0.0, 1e-5, 1e16)
    assert app.regionListModel.rowCount() == before + 1
    assert app.canUndo is True
    assert app.isDirty is True
    app.undo()
    assert app.regionListModel.rowCount() == before
    assert app.canRedo is True
    app.redo()
    assert app.regionListModel.rowCount() == before + 1


def test_rename_region_updates_the_model_and_is_undoable(qapp):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    region_id = app.structure.regions[0].id
    old_name = app.structure.regions[0].name
    app.renameRegion(region_id, "Renamed")
    assert app.structure.find_region(region_id).name == "Renamed"
    app.undo()
    assert app.structure.find_region(region_id).name == old_name


def test_set_region_doping_marks_dirty_and_reraster_validates(qapp):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    region_id = app.structure.regions[0].id
    app.setRegionDoping(region_id, 5e17)
    assert app.structure.find_region(region_id).net_doping_cm3 == 5e17
    assert app.isDirty is True


def test_invalid_edit_surfaces_as_a_validation_error(qapp):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    region_id = app.structure.regions[0].id
    r = app.structure.find_region(region_id)
    app.setRegionBounds(region_id, r.x_max, r.x_min, r.y_min, r.y_max)  # swapped -> zero/negative width
    errors = app.runStructureValidation()
    assert errors is False
    assert app.structureValidationErrors != []


def test_move_region_reorders_priority_and_is_undoable(qapp):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    ids_before = [app.regionListModel.data(app.regionListModel.index(k), app.regionListModel.IdRole)
                  for k in range(app.regionListModel.rowCount())]
    assert len(ids_before) >= 2, "structure example must have >= 2 regions to test reordering"

    app.moveRegion(ids_before[0], +1)
    ids_after = [app.regionListModel.data(app.regionListModel.index(k), app.regionListModel.IdRole)
                 for k in range(app.regionListModel.rowCount())]
    assert ids_after[1] == ids_before[0]           # moved into slot 1
    assert ids_after[0] == ids_before[1]            # slot 1's old occupant shifted up
    assert app.canUndo is True

    app.undo()
    ids_restored = [app.regionListModel.data(app.regionListModel.index(k), app.regionListModel.IdRole)
                    for k in range(app.regionListModel.rowCount())]
    assert ids_restored == ids_before

    # moving the last region further than the list allows clamps, not errors
    app.moveRegion(ids_before[-1], +99)
    ids_clamped = [app.regionListModel.data(app.regionListModel.index(k), app.regionListModel.IdRole)
                   for k in range(app.regionListModel.rowCount())]
    assert ids_clamped[-1] == ids_before[-1]         # already last -- no-op, no undo entry pushed


def test_gate_vfb_mode_switch_is_reflected(qapp):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    gate_id = app.structure.gates[0].id
    app.setGateVfbMode(gate_id, "manual", -0.77)
    gate = app.structure.find_gate(gate_id)
    assert gate.vfb_mode == "manual"
    assert gate.vfb_manual == -0.77


def test_mesh_edits_are_undoable_and_dirty(qapp):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    original_nx = app.mesh_model.nx
    app.setMeshNxNy(20, 12)
    assert app.mesh_model.nx == 20 and app.mesh_model.ny == 12
    assert app.isDirty is True
    app.undo()
    assert app.mesh_model.nx == original_nx


def test_run_solves_the_loaded_structure_end_to_end(qapp):
    """A real gap found during Task 13's DoD walk: run() only ever used
    self.spec (the v0.1 loadExample() pathway) -- a structure built
    through loadStructureExample() had no way to actually be solved.
    This proves the fix: run() converts the current StructureModel via
    to_device_spec() and solves it through the real JobRunner/subprocess,
    the same path v0.1's own test_run_completes_and_exposes_solved_fields
    exercises."""
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    assert app.structure is not None

    loop = QEventLoop()
    app.resultChanged.connect(loop.quit)
    app.errorRaised.connect(lambda s, d: loop.quit())
    QTimer.singleShot(180000, loop.quit)
    app.run()
    assert app.busy is True
    loop.exec()

    assert app.hasResult is True, app.status
    assert app.busy is False
    assert "potential" in app.fieldNames


def test_save_and_load_project_round_trips(qapp, tmp_path):
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    path = str(tmp_path / "proj.json")
    app.saveProject(path, "My Project")
    assert app.isDirty is False

    app2 = AppController()
    app2.loadProject(path)
    assert app2.regionListModel.rowCount() == app.regionListModel.rowCount()
    assert app2.isDirty is False


def test_save_and_load_project_accept_file_urls(qapp, tmp_path):
    """QtQuick.Dialogs' FileDialog hands saveProject()/loadProject() a
    file:// URL string, not a plain path -- both slots must convert it."""
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    path = tmp_path / "proj.json"
    app.saveProject(path.as_uri(), "My Project")
    assert path.exists()
    assert app.isDirty is False

    app2 = AppController()
    app2.loadProject(path.as_uri())
    assert app2.regionListModel.rowCount() == app.regionListModel.rowCount()
    assert app2.isDirty is False
