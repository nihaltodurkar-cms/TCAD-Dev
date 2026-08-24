"""Schema v4: sweep configuration in project files.

v4 adds one optional key -- "sweep" (a plain dict or null).  v2/v3 files
load unchanged and yield sweep=None; missing/null sweep is a safe
default; a structurally invalid sweep fails AT LOAD with a clear error
(contact-name validity can only be checked at Run time against the real
spec, which run() already does).  Loading a project must also never let
results from a previous session masquerade as this project's results.

The round-trip contract: create -> save -> load -> compare, exactly,
for process-only / structure-only / combined projects alike.
"""
import json
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication

from gui.services.structure_model import (
    BoundarySpec, ContactModel, GateModel, MeshModel, RegionSpec, StructureModel)
from gui.services.process_model import ProcessFlow, ProcessStep
from gui.services.device_spec import SweepSpec
from gui.services.project_store import (
    SCHEMA_VERSION, UnsupportedProjectVersionError, load_project, save_project)


def _sample():
    structure = StructureModel(width_cm=4e-5, height_cm=2e-5, regions=[
        RegionSpec("ch", "Channel", 0.0, 4e-5, 0.0, 2e-5, -1e17)],
        contacts=[ContactModel("c1", "left", BoundarySpec("left"), 0.0)],
        gates=[GateModel("g1", "gate", BoundarySpec("top"), tox_cm=5e-7,
                         vfb_mode="manual", vfb_manual=-0.8)])
    mesh = MeshModel(nx=10, ny=6)
    return structure, mesh


SWEEP = SweepSpec(contact="drain", start=0.0, stop=0.8, step=0.1)


# ----------------------------------------------------------------------
#  version bump and file shape
# ----------------------------------------------------------------------
def test_schema_version_is_4():
    assert SCHEMA_VERSION == 4


def test_v4_file_contains_sweep_key(tmp_path):
    structure, mesh = _sample()
    path = str(tmp_path / "p.json")
    save_project(path, "P", structure, mesh, ProcessFlow(), SWEEP)
    data = json.load(open(path))
    assert data["schema_version"] == 4
    assert data["sweep"] == {"contact": "drain", "start": 0.0,
                             "stop": 0.8, "step": 0.1}


def test_v4_file_without_sweep_writes_null(tmp_path):
    """save_project's new parameter is optional; a caller that does not
    know about sweeps still writes a valid v4 file."""
    structure, mesh = _sample()
    path = str(tmp_path / "p.json")
    save_project(path, "P", structure, mesh)
    assert json.load(open(path))["sweep"] is None


# ----------------------------------------------------------------------
#  round-trip: create -> save -> load -> compare
# ----------------------------------------------------------------------
def test_v4_sweep_round_trips_exactly(tmp_path):
    structure, mesh = _sample()
    path = str(tmp_path / "p.json")
    save_project(path, "P", structure, mesh, ProcessFlow(), SWEEP)

    name, s, m, f, sweep = load_project(path)
    assert sweep == SWEEP
    assert sweep.contact == "drain"
    assert (sweep.start, sweep.stop, sweep.step) == (0.0, 0.8, 0.1)


def test_round_trip_still_covers_structure_mesh_process(tmp_path):
    flow = ProcessFlow(steps=[ProcessStep(
        id="st1", name="Substrate", operation="substrate",
        parameters={"length_cm": 1e-3, "background_doping_cm3": -1e16})])
    structure, mesh = _sample()
    path = str(tmp_path / "p.json")
    save_project(path, "P", structure, mesh, flow, SWEEP)
    name, s, m, f, sweep = load_project(path)
    assert s.to_dict() == structure.to_dict()
    assert m.to_dict() == mesh.to_dict()
    assert [step.id for step in f.steps] == ["st1"]
    assert sweep == SWEEP


def test_process_only_project_with_sweep_round_trips(tmp_path):
    flow = ProcessFlow(steps=[ProcessStep(
        id="st1", name="Substrate", operation="substrate",
        parameters={"length_cm": 1e-3, "background_doping_cm3": -1e16})])
    path = str(tmp_path / "p.json")
    save_project(path, "ProcOnly", None, None, flow, SWEEP)
    name, s, m, f, sweep = load_project(path)
    assert s is None and m is None
    assert len(f.steps) == 1
    assert sweep == SWEEP


def test_structure_only_project_with_sweep_round_trips(tmp_path):
    structure, mesh = _sample()
    path = str(tmp_path / "p.json")
    save_project(path, "StructOnly", structure, mesh, ProcessFlow(), SWEEP)
    name, s, m, f, sweep = load_project(path)
    assert s.to_dict() == structure.to_dict()
    assert f.steps == []
    assert sweep == SWEEP


# ----------------------------------------------------------------------
#  migration from older schemas
# ----------------------------------------------------------------------
def _write_v3(tmp_path, name="legacy"):
    structure, mesh = _sample()
    data = {
        "schema_version": 3,
        "name": name,
        "structure": structure.to_dict(),
        "mesh": mesh.to_dict(),
        "process": {"steps": []},
    }
    path = str(tmp_path / "v3.json")
    with open(path, "w") as fh:
        json.dump(data, fh)
    return path


def test_v3_project_loads_with_sweep_none(tmp_path):
    path = _write_v3(tmp_path)
    name, s, m, f, sweep = load_project(path)
    assert name == "legacy"
    assert s is not None and m is not None
    assert sweep is None, "v3 files have no sweep; default must be safe None"


def test_v2_project_still_loads_with_sweep_none(tmp_path):
    structure, mesh = _sample()
    data = {
        "schema_version": 2,
        "name": "old",
        "structure": structure.to_dict(),
        "mesh": mesh.to_dict(),
    }
    path = str(tmp_path / "v2.json")
    with open(path, "w") as fh:
        json.dump(data, fh)
    name, s, m, f, sweep = load_project(path)
    assert s is not None
    assert f.steps == []
    assert sweep is None


def test_v4_file_with_missing_sweep_key_defaults_to_none(tmp_path):
    structure, mesh = _sample()
    path = str(tmp_path / "p.json")
    save_project(path, "P", structure, mesh)
    data = json.load(open(path))
    del data["sweep"]                      # simulate a writer that omitted it
    with open(path, "w") as fh:
        json.dump(data, fh)
    _, _, _, _, sweep = load_project(path)
    assert sweep is None


def test_v4_file_with_null_sweep_loads_none(tmp_path):
    structure, mesh = _sample()
    path = str(tmp_path / "p.json")
    save_project(path, "P", structure, mesh, ProcessFlow(), None)
    _, _, _, _, sweep = load_project(path)
    assert sweep is None


# ----------------------------------------------------------------------
#  invalid sweep settings fail clearly at load time
# ----------------------------------------------------------------------
@pytest.mark.parametrize("bad,match", [
    ("not a dict", "object"),
    ({"contact": "d", "start": 0.0}, "missing"),
    ({"contact": "d", "start": 0.0, "stop": 1.0}, "missing"),
    ({"contact": "d", "start": float("nan"), "stop": 1.0, "step": 0.1},
     "finite"),
    ({"contact": "d", "start": 0.0, "stop": 1.0, "step": 0.0}, "nonzero"),
    ({"contact": "d", "start": 1.0, "stop": 0.0, "step": 0.5}, "toward"),
    ({"contact": "d", "start": 0.5, "stop": 0.5, "step": 0.1}, "2 points"),
    ("drain", "object"),
    ([0.0, 1.0, 0.1], "object"),
])
def test_invalid_sweep_fails_at_load_with_clear_error(tmp_path, bad, match):
    structure, mesh = _sample()
    path = str(tmp_path / "p.json")
    save_project(path, "P", structure, mesh, ProcessFlow(), SWEEP)
    data = json.load(open(path))
    if isinstance(bad, str) and bad not in ("drain",):
        bad = bad                              # keep as-is for JSON strings
    data["sweep"] = bad
    with open(path, "w") as fh:
        json.dump(data, fh)
    with pytest.raises(ValueError, match="sweep"):
        load_project(path)


def test_unsupported_newer_version_still_rejected(tmp_path):
    structure, mesh = _sample()
    data = {"schema_version": 99, "name": "x",
            "structure": structure.to_dict(), "mesh": mesh.to_dict()}
    path = str(tmp_path / "future.json")
    with open(path, "w") as fh:
        json.dump(data, fh)
    with pytest.raises(UnsupportedProjectVersionError):
        load_project(path)


# ----------------------------------------------------------------------
#  controller integration
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    yield QCoreApplication.instance() or QCoreApplication([])


def test_save_load_restores_armed_sweep_config(qapp, tmp_path):
    from gui.controllers.app_controller import AppController
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    app.setSweepConfig("drain", 0.0, 0.6, 0.2)

    path = str(tmp_path / "proj.json")
    app.saveProject(path, "My Project")

    app2 = AppController()
    fired = []
    app2.sweepChanged.connect(lambda: fired.append(1))
    app2.loadProject(path)
    assert app2.hasSweepConfig is True
    cfg = app2._sweep_config
    assert (cfg.contact, cfg.start, cfg.stop, cfg.step) == ("drain", 0.0, 0.6, 0.2)
    assert fired, "sweepChanged must fire so QML bindings refresh"


def test_loading_project_without_sweep_clears_config(qapp, tmp_path):
    from gui.controllers.app_controller import AppController
    app = AppController()
    app.loadStructureExample("mosfet_2d_structure")
    app.setSweepConfig("drain", 0.0, 0.6, 0.2)
    path = str(tmp_path / "proj.json")
    app.saveProject(path, "My Project")

    app.clearSweepConfig()
    # re-save without an armed sweep
    app.saveProject(path, "My Project")
    app.loadProject(path)
    assert app.hasSweepConfig is False


def test_loading_project_drops_stale_results(qapp, tmp_path):
    """A project file never contains results, so after loading one there
    must be no 'results loaded' state left over from whatever was solved
    before the load."""
    from gui.controllers.app_controller import AppController
    from gui.services.result_store import NpzResultStore

    app = AppController()
    d = {"dimensionality": np.array(1),
         "axis_x": np.array([0.0, 1e-4]),
         "field__potential": np.array([0.0, 1.0]),
         "unit__potential": np.array("V"),
         "solved_bias": np.array(False)}
    stale = str(tmp_path / "stale.npz")
    np.savez(stale + ".tmp.npz", **d)
    os.replace(stale + ".tmp.npz", stale)
    app._store = NpzResultStore(stale)
    assert app.hasResult is True

    other = AppController()
    other.loadStructureExample("mosfet_2d_structure")
    other.saveProject(str(tmp_path / "proj.json"), "Other")
    app.loadProject(str(tmp_path / "proj.json"))
    assert app.hasResult is False, \
        "loading a project must not keep a previous run's results on show"
