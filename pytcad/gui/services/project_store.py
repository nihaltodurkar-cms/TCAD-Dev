"""Project file save/load.  Results (.npz) live in a separate results/
directory and are never embedded here -- only StructureModel/MeshModel's
scalars and short lists are.

A v4 project may hold any combination of structure=None, mesh=None, and
a process flow that is present or empty -- process-only projects,
structure-only projects, and structure+process projects all round-trip
correctly. No placeholder/fake geometry is ever synthesized here.
v2/v3 files load migrated (v2: empty process flow; v2/v3: sweep=None).
v5 adds one further optional key: "models" (the Physics Lab's
ModelCatalog config dict, or null) -- v2/v3/v4 files simply lack the key,
which loads as None, exactly like a v4 file's absent "sweep" key before it.
"""
import json

from .structure_model import StructureModel, MeshModel
from .process_model import ProcessFlow
from .device_spec import SweepSpec

SCHEMA_VERSION = 5


class UnsupportedProjectVersionError(Exception):
    pass


def save_project(path, name, structure, mesh_model, process_flow=None,
                 sweep=None, model_config=None):
    """v5 adds one optional key: "models" (the Physics Lab's per-model
    enabled/disabled config, as a plain dict or null). Results are still
    never embedded -- a saved project is configuration, never in-progress
    or stale output."""
    data = {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "structure": structure.to_dict() if structure is not None else None,
        "mesh": mesh_model.to_dict() if mesh_model is not None else None,
        "process": (process_flow or ProcessFlow()).to_dict(),
        "sweep": sweep.to_dict() if sweep is not None else None,
        "models": dict(model_config) if model_config is not None else None,
    }
    with open(path, "w") as fh:
        json.dump(data, fh, indent=2)


def load_project(path):
    with open(path) as fh:
        data = json.load(fh)
    version = data.get("schema_version")
    if version not in (2, 3, 4, 5):
        raise UnsupportedProjectVersionError(
            f"project schema version {version!r} is not supported "
            f"(this build supports 2 and 3 (migrated), 4, and {SCHEMA_VERSION})")
    structure = StructureModel.from_dict(data["structure"]) if data.get("structure") else None
    mesh_model = MeshModel.from_dict(data["mesh"]) if data.get("mesh") else None
    process_flow = ProcessFlow.from_dict(data.get("process") or {"steps": []})
    # v2/v3 files have no "sweep" key; v4+ files carry a dict or null.
    # Missing -> safe default None.  Present-but-invalid -> clear error
    # here, at load time, not later as a failed solver job.  Contact-name
    # validity can only be judged against the real spec at Run time
    # (AppController.run() does exactly that via SweepSpec.validate).
    raw_sweep = data.get("sweep")
    sweep = SweepSpec.from_dict(raw_sweep) if raw_sweep is not None else None
    # v2/v3/v4 files have no "models" key at all; v5 files carry a dict
    # or null. Missing/null -> None, telling the caller to leave whatever
    # Physics Lab config is already in effect (i.e. the catalog defaults)
    # untouched -- exactly the pre-v5 behavior, so old projects keep
    # loading byte-identically. Structural validation (dict of known keys
    # to bools) is ModelCatalog's job, not this module's -- the caller
    # already applies it via PhysicsLabController.setModelConfig().
    raw_models = data.get("models")
    model_config = dict(raw_models) if isinstance(raw_models, dict) else None
    return data["name"], structure, mesh_model, process_flow, sweep, model_config
