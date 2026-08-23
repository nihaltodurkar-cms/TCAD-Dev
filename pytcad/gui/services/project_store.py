"""Project file save/load.  Results (.npz) live in a separate results/
directory and are never embedded here -- only StructureModel/MeshModel's
scalars and short lists are.
"""
import json

from .structure_model import StructureModel, MeshModel

SCHEMA_VERSION = 2


class UnsupportedProjectVersionError(Exception):
    pass


def save_project(path, name, structure, mesh_model):
    data = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "structure": structure.to_dict(),
        "mesh": mesh_model.to_dict(),
    }
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)


def load_project(path):
    with open(path) as fh:
        data = json.load(fh)
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        raise UnsupportedProjectVersionError(
            f"project schema version {version!r} is not supported "
            f"(this build supports {SCHEMA_VERSION})")
    structure = StructureModel.from_dict(data["structure"])
    mesh_model = MeshModel.from_dict(data["mesh"])
    return data["name"], structure, mesh_model
