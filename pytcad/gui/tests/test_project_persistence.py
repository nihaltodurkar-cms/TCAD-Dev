"""Project files are schema-versioned; structure/mesh round-trip exactly;
results are never embedded."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from gui.services.structure_model import BoundarySpec, ContactModel, GateModel, MeshModel, RegionSpec, StructureModel
from gui.services.project_store import SCHEMA_VERSION, UnsupportedProjectVersionError, save_project, load_project
from gui.services.process_model import ProcessFlow, ProcessStep


def _sample():
    structure = StructureModel(width_cm=4e-5, height_cm=2e-5, regions=[
        RegionSpec("ch", "Channel", 0.0, 4e-5, 0.0, 2e-5, -1e17)],
        contacts=[ContactModel("c1", "left", BoundarySpec("left"), 0.0)],
        gates=[GateModel("g1", "gate", BoundarySpec("top"), tox_cm=5e-7,
                         vfb_mode="manual", vfb_manual=-0.8)])
    mesh = MeshModel(nx=10, ny=6)
    return structure, mesh


# _sample() doubles as the "mosfet_example_structure" fixture referenced
# by the task brief -- same shape (StructureModel, MeshModel) pair.
mosfet_example_structure = _sample


def test_save_then_load_round_trips_exactly(tmp_path):
    structure, mesh = _sample()
    path = str(tmp_path / "project.json")
    save_project(path, "Test Project", structure, mesh)

    name, back_structure, back_mesh, back_flow, _sweep, _models = load_project(path)
    assert name == "Test Project"
    assert back_structure.to_dict() == structure.to_dict()
    assert back_mesh.to_dict() == mesh.to_dict()
    assert back_flow.steps == []


def test_saved_file_has_the_schema_version(tmp_path):
    structure, mesh = _sample()
    path = str(tmp_path / "project.json")
    save_project(path, "Test Project", structure, mesh)
    with open(path) as fh:
        data = json.load(fh)
    assert data["schema_version"] == SCHEMA_VERSION


def test_saved_file_never_embeds_large_arrays(tmp_path):
    structure, mesh = _sample()
    path = str(tmp_path / "project.json")
    save_project(path, "Test Project", structure, mesh)
    with open(path) as fh:
        data = json.load(fh)
    assert "results" not in data
    assert "doping" not in json.dumps(data["structure"]).lower() or \
        "net_doping_cm3" in json.dumps(data["structure"])  # only per-region scalars, no arrays


def test_unsupported_schema_version_is_rejected(tmp_path):
    path = str(tmp_path / "old_project.json")
    with open(path, "w") as fh:
        json.dump({"schema_version": 1, "name": "old", "structure": {}, "mesh": {}}, fh)
    with pytest.raises(UnsupportedProjectVersionError):
        load_project(path)


def test_v3_project_round_trips_process_flow(tmp_path):
    structure, mesh = mosfet_example_structure()
    flow = ProcessFlow(steps=[ProcessStep(id="a", name="Substrate", operation="substrate",
                                          parameters={"length_cm": 3e-4})])
    path = str(tmp_path / "v3.json")
    save_project(path, "V3 Project", structure, mesh, flow)
    name, s2, m2, f2, _sweep, _models = load_project(path)
    assert f2.steps[0].id == "a"
    assert f2.steps[0].parameters == {"length_cm": 3e-4}


def test_v2_project_loads_with_empty_process_flow(tmp_path):
    """A v2 file has no "process" key -- must still load, structure/mesh
    unchanged, process flow empty. Build a v2 fixture directly (not
    through save_project, which now always writes v3) to genuinely test
    the migration path."""
    structure, mesh = mosfet_example_structure()
    v2_data = {"schema_version": 2, "name": "Old Project",
              "structure": structure.to_dict(), "mesh": mesh.to_dict()}
    path = str(tmp_path / "v2.json")
    with open(path, "w") as fh:
        json.dump(v2_data, fh)
    name, s2, m2, f2, _sweep, _models = load_project(path)
    assert name == "Old Project"
    assert len(s2.regions) == len(structure.regions)
    assert s2.to_dict() == structure.to_dict()
    assert m2.to_dict() == mesh.to_dict()
    assert f2.steps == []


def test_v1_project_still_raises_a_clear_error(tmp_path):
    path = str(tmp_path / "v1.json")
    with open(path, "w") as fh:
        json.dump({"schema_version": 1}, fh)
    with pytest.raises(UnsupportedProjectVersionError):
        load_project(path)


def test_process_only_project_round_trips_with_no_structure(tmp_path):
    """structure=None, mesh_model=None, a non-empty ProcessFlow: must
    save/load without ever synthesizing placeholder geometry, and
    structure/mesh must come back None."""
    flow = ProcessFlow(steps=[ProcessStep(id="a", name="Substrate", operation="substrate",
                                          parameters={"length_cm": 3e-4}),
                              ProcessStep(id="b", name="Implant", operation="implant",
                                          parameters={"species": "boron", "dose_cm2": 1e13})])
    path = str(tmp_path / "process_only.json")
    save_project(path, "Process Only", None, None, flow)

    with open(path) as fh:
        data = json.load(fh)
    assert data["structure"] is None
    assert data["mesh"] is None

    name, structure, mesh_model, process_flow, _sweep, _models = load_project(path)
    assert name == "Process Only"
    assert structure is None
    assert mesh_model is None
    assert [s.id for s in process_flow.steps] == ["a", "b"]
    assert process_flow.steps[1].parameters == {"species": "boron", "dose_cm2": 1e13}


def test_structure_only_project_round_trips_with_empty_process_flow(tmp_path):
    """A real structure/mesh with an empty ProcessFlow round-trips, and
    process_flow.steps == [] on load."""
    structure, mesh = mosfet_example_structure()
    path = str(tmp_path / "structure_only.json")
    save_project(path, "Structure Only", structure, mesh, ProcessFlow())

    name, s2, m2, f2, _sweep, _models = load_project(path)
    assert name == "Structure Only"
    assert s2.to_dict() == structure.to_dict()
    assert m2.to_dict() == mesh.to_dict()
    assert f2.steps == []


def test_structure_and_process_project_round_trips_both(tmp_path):
    """Both structure/mesh and a non-empty process flow are real: both
    must round-trip."""
    structure, mesh = mosfet_example_structure()
    flow = ProcessFlow(steps=[ProcessStep(id="a", name="Substrate", operation="substrate",
                                          parameters={"length_cm": 3e-4})])
    path = str(tmp_path / "both.json")
    save_project(path, "Both", structure, mesh, flow)

    name, s2, m2, f2, _sweep, _models = load_project(path)
    assert name == "Both"
    assert s2.to_dict() == structure.to_dict()
    assert m2.to_dict() == mesh.to_dict()
    assert f2.steps[0].id == "a"
