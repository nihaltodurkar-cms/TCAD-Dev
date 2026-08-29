"""Schema v5: Physics Lab model config in project files.

v5 adds one further optional key -- "models" (the ModelCatalog config
dict, or null). v2/v3/v4 files simply lack the key, which loads as
model_config=None -- the caller's contract for None is "leave whatever
Physics Lab config is already in effect untouched", i.e. byte-identical
to pre-v5 behavior for old files.

This is the persistence-layer counterpart to
gui/tests/test_smoke_e2e.py::test_1d_project_save_reload_persists_physics_lab_config,
which drives the same round trip through the real QML GUI and controllers.
"""
import json
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QGuiApplication

from gui.services.structure_model import (
    BoundarySpec, ContactModel, GateModel, MeshModel, RegionSpec, StructureModel)
from gui.services.process_model import ProcessFlow
from gui.services.project_store import SCHEMA_VERSION, load_project, save_project
from workbench.core.catalog import ModelCatalog


def _sample():
    structure = StructureModel(width_cm=4e-5, height_cm=2e-5, regions=[
        RegionSpec("ch", "Channel", 0.0, 4e-5, 0.0, 2e-5, -1e17)],
        contacts=[ContactModel("c1", "left", BoundarySpec("left"), 0.0)],
        gates=[GateModel("g1", "gate", BoundarySpec("top"), tox_cm=5e-7,
                         vfb_mode="manual", vfb_manual=-0.8)])
    mesh = MeshModel(nx=10, ny=6)
    return structure, mesh


# ----------------------------------------------------------------------
#  version bump and file shape
# ----------------------------------------------------------------------
def test_schema_version_is_5():
    assert SCHEMA_VERSION == 5


def test_v5_file_contains_models_key(tmp_path):
    structure, mesh = _sample()
    config = ModelCatalog.default_config()
    config["auger"] = False
    path = str(tmp_path / "p.json")
    save_project(path, "P", structure, mesh, ProcessFlow(), None, config)
    data = json.load(open(path))
    assert data["schema_version"] == 5
    assert data["models"] == config


def test_v5_file_without_model_config_writes_null(tmp_path):
    """save_project's new parameter is optional -- a caller that never
    passes model_config still writes a valid v5 file."""
    structure, mesh = _sample()
    path = str(tmp_path / "p.json")
    save_project(path, "P", structure, mesh)
    assert json.load(open(path))["models"] is None


# ----------------------------------------------------------------------
#  round-trip: create -> save -> load -> compare, at the module level
# ----------------------------------------------------------------------
def test_v5_model_config_round_trips_exactly(tmp_path):
    structure, mesh = _sample()
    config = ModelCatalog.default_config()
    config["auger"] = False
    config["impact"] = True
    path = str(tmp_path / "p.json")
    save_project(path, "P", structure, mesh, ProcessFlow(), None, config)

    name, s, m, f, sweep, model_config = load_project(path)
    assert model_config == config


def test_v5_file_with_null_models_loads_none(tmp_path):
    structure, mesh = _sample()
    path = str(tmp_path / "p.json")
    save_project(path, "P", structure, mesh, ProcessFlow(), None, None)
    _, _, _, _, _, model_config = load_project(path)
    assert model_config is None


# ----------------------------------------------------------------------
#  backward compatibility: v2/v3/v4 files have no "models" key at all
# ----------------------------------------------------------------------
def test_v4_file_loads_with_model_config_none(tmp_path):
    structure, mesh = _sample()
    path = str(tmp_path / "p.json")
    save_project(path, "P", structure, mesh)          # writes SCHEMA_VERSION (5)
    data = json.load(open(path))
    del data["models"]                                # simulate a real v4 file
    data["schema_version"] = 4
    with open(path, "w") as fh:
        json.dump(data, fh)
    _, _, _, _, _, model_config = load_project(path)
    assert model_config is None


def test_v3_file_loads_with_model_config_none(tmp_path):
    structure, mesh = _sample()
    data = {
        "schema_version": 3,
        "name": "legacy",
        "structure": structure.to_dict(),
        "mesh": mesh.to_dict(),
        "process": {"steps": []},
    }
    path = str(tmp_path / "v3.json")
    with open(path, "w") as fh:
        json.dump(data, fh)
    _, _, _, _, _, model_config = load_project(path)
    assert model_config is None


# ----------------------------------------------------------------------
#  controller integration -- real save/load through AppController
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    yield QCoreApplication.instance() or QGuiApplication([])


def test_controller_round_trips_a_toggled_model(qapp, tmp_path):
    from gui.controllers.app_controller import AppController
    ctl = AppController()
    ctl.addProcessStep(
        "substrate", "Substrate",
        {"length_cm": 1e-4, "background_doping_cm3": -1e15,
         "mesh": {"h_min_cm": 1e-7, "h_max_cm": 1e-5, "ratio": 1.2}})
    ctl.lab.setModelEnabled("auger", False)
    ctl.lab.setModelEnabled("impact", True)

    path = str(tmp_path / "p.json")
    ctl.saveProject(path, "P")

    ctl2 = AppController()
    ctl2.loadProject(path)
    assert ctl2.lab.model_config["auger"] is False
    assert ctl2.lab.model_config["impact"] is True
    # untouched models must still read their documented defaults
    assert ctl2.lab.model_config["srh"] is True


def test_controller_loading_a_pre_v5_project_leaves_lab_config_untouched(qapp, tmp_path):
    """A project saved before v5 (or one this build wrote with no model
    config) must not silently reset a session's in-progress Physics Lab
    toggles back to catalog defaults on load."""
    from gui.controllers.app_controller import AppController
    structure, mesh = _sample()
    path = str(tmp_path / "legacy.json")
    save_project(path, "legacy", structure, mesh)      # models=None
    data = json.load(open(path))
    del data["models"]
    data["schema_version"] = 4
    with open(path, "w") as fh:
        json.dump(data, fh)

    ctl = AppController()
    ctl.lab.setModelEnabled("auger", False)
    ctl.loadProject(path)
    assert ctl.lab.model_config["auger"] is False, (
        "loading a pre-v5 project silently reset the Physics Lab config")


def test_setmodelconfig_rejects_malformed_input_without_raising():
    from gui.controllers.lab_controller import PhysicsLabController
    from gui.controllers.app_controller import AppController
    ctl = AppController()
    errs = []
    ctl.lab.labError.connect(errs.append)
    ctl.lab.setModelConfig("not a dict")
    assert errs and "dict" in errs[0]
    assert ctl.lab.model_config == ModelCatalog.default_config()


def test_setmodelconfig_merges_partial_config_onto_defaults():
    """A config missing keys (an old save from a build with fewer models,
    or hand-edited JSON) must fill the gaps from the documented defaults
    rather than raising or leaving those models unset."""
    from gui.controllers.app_controller import AppController
    ctl = AppController()
    ctl.lab.setModelConfig({"auger": False})
    assert ctl.lab.model_config["auger"] is False
    assert ctl.lab.model_config["srh"] == ModelCatalog.default_config()["srh"]
    assert set(ctl.lab.model_config) == set(ModelCatalog.default_config())
