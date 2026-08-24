"""Project file save/load.  Results (.npz) live in a separate results/
directory and are never embedded here -- only StructureModel/MeshModel's
scalars and short lists are.

A v3 project may hold any combination of structure=None, mesh=None, and
a process flow that is present or empty -- process-only projects,
structure-only projects, and structure+process projects all round-trip
correctly. No placeholder/fake geometry is ever synthesized here.
"""
import json

from .structure_model import StructureModel, MeshModel
from .process_model import ProcessFlow

SCHEMA_VERSION = 3


class UnsupportedProjectVersionError(Exception):
    pass


def save_project(path, name, structure, mesh_model, process_flow=None):
    data = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "structure": structure.to_dict() if structure is not None else None,
        "mesh": mesh_model.to_dict() if mesh_model is not None else None,
        "process": (process_flow or ProcessFlow()).to_dict(),
    }
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)


def load_project(path):
    with open(path) as fh:
        data = json.load(fh)
    version = data.get("schema_version")
    if version not in (2, 3):
        raise UnsupportedProjectVersionError(
            f"project schema version {version!r} is not supported "
            f"(this build supports 2 (migrated) and {SCHEMA_VERSION})")
    structure = StructureModel.from_dict(data["structure"]) if data.get("structure") else None
    mesh_model = MeshModel.from_dict(data["mesh"]) if data.get("mesh") else None
    process_flow = ProcessFlow.from_dict(data.get("process") or {"steps": []})
    return data["name"], structure, mesh_model, process_flow
