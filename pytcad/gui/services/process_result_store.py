"""Read-only view onto process_runner.py's per-step .npz checkpoints.

Separate from NpzResultStore/SpecResultStore (gui/services/result_store.py,
design section 7) -- the semantics differ (a per-species doping
checkpoint produced while walking a process flow, not a solved device
field) -- but this class implements the same minimal
mesh_axes()/scalar_field() interface those two already expose, so the
viewport's existing rendering pipeline (gui/visualization/
mpl_canvas_item.py) can be reused for process-flow previews rather than
given a second code path.

Checkpoint .npz keys, exactly as process_runner.run_flow() writes them:
x, background, net_doping, ntotal, species_{species} (one per species
present so far), bookkeeping_{key} (oxidize steps only). See
process_runner.py's module docstring for the state model.
"""
import numpy as np

from .result_store import MeshAxes, ScalarField


class ProcessResultStore:
    """Wraps a process_runner.py manifest dict
    ({"step_ids": [...], "state_paths": {step_id: npz_path}}).

    A "selected" step (defaulting to the last one in the flow) drives
    mesh_axes()/scalar_field()/available_scalars(), mirroring how
    NpzResultStore is scoped to a single result file -- select_step()
    lets a caller (e.g. a step-by-step preview scrubber) move that
    selection without constructing a new store.
    """

    def __init__(self, manifest):
        self._step_ids = list(manifest["step_ids"])
        self._state_paths = dict(manifest["state_paths"])
        self._selected = self._step_ids[-1] if self._step_ids else None

    def step_ids(self):
        return list(self._step_ids)

    def select_step(self, step_id):
        if step_id not in self._state_paths:
            raise KeyError(step_id)
        self._selected = step_id

    def state_for(self, step_id):
        """Loads one checkpoint fresh from disk every call -- these files
        are small per-step doping snapshots, not solved 2D/3D fields, so
        there is no caching contract to honor here (unlike NpzResultStore,
        which keeps its np.load handle open for the store's lifetime)."""
        path = self._state_paths[step_id]
        with np.load(path) as d:
            state = {
                "x": d["x"],
                "background": float(d["background"]),
                "net_doping": d["net_doping"],
                "ntotal": d["ntotal"],
                "species_profiles": {},
                "bookkeeping": {},
            }
            for key in d.files:
                if key.startswith("species_"):
                    state["species_profiles"][key[len("species_"):]] = d[key]
                elif key.startswith("bookkeeping_"):
                    state["bookkeeping"][key[len("bookkeeping_"):]] = float(d[key])
        return state

    def mesh_axes(self):
        state = self.state_for(self._selected)
        return MeshAxes(axes={"x": state["x"]}, dimensionality=1)

    def available_scalars(self):
        state = self.state_for(self._selected)
        return ["net_doping", "ntotal"] + list(state["species_profiles"])

    def scalar_field(self, name):
        state = self.state_for(self._selected)
        if name in ("net_doping", "ntotal"):
            values = state[name]
        elif name in state["species_profiles"]:
            values = state["species_profiles"][name]
        else:
            raise KeyError(f"no scalar field '{name}' in process state '{self._selected}'")
        return ScalarField(name=name, values=values, unit="cm^-3")
