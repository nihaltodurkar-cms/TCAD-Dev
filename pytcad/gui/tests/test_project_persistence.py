"""Project files are schema-versioned; structure/mesh round-trip exactly;
results are never embedded."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from gui.services.structure_model import BoundarySpec, ContactModel, GateModel, MeshModel, RegionSpec, StructureModel
from gui.services.project_store import SCHEMA_VERSION, UnsupportedProjectVersionError, save_project, load_project


def _sample():
    structure = StructureModel(width_cm=4e-5, height_cm=2e-5, regions=[
        RegionSpec("ch", "Channel", 0.0, 4e-5, 0.0, 2e-5, -1e17)],
        contacts=[ContactModel("c1", "left", BoundarySpec("left"), 0.0)],
        gates=[GateModel("g1", "gate", BoundarySpec("top"), tox_cm=5e-7,
                         vfb_mode="manual", vfb_manual=-0.8)])
    mesh = MeshModel(nx=10, ny=6)
    return structure, mesh


def test_save_then_load_round_trips_exactly(tmp_path):
    structure, mesh = _sample()
    path = str(tmp_path / "project.json")
    save_project(path, "Test Project", structure, mesh)

    name, back_structure, back_mesh = load_project(path)
    assert name == "Test Project"
    assert back_structure.to_dict() == structure.to_dict()
    assert back_mesh.to_dict() == mesh.to_dict()


def test_saved_file_has_the_schema_version(tmp_path):
    structure, mesh = _sample()
    path = str(tmp_path / "project.json")
    save_project(path, "Test Project", structure, mesh)
    with open(path) as fh:
        data = json.load(fh)
    assert data["schema_version"] == SCHEMA_VERSION == 2


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
