"""Result access, deliberately abstracted away from the storage format.

v0.1 stores results as .npz, but nothing above this module is allowed to
know that: controllers and QML see only the ResultStore interface and the
small frozen dataclasses below.  Swapping in HDF5 or a custom layout
later is then a new subclass, not a rewrite of everything that reads
results.

SpecResultStore exists for the same reason in the other direction: the
viewport must be able to draw a structure BEFORE any solve has happened,
and rather than give the viewport a second code path for that case, a
DeviceSpec is presented as a read-only, doping-only ResultStore.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
import json

import numpy as np


@dataclass(frozen=True)
class MeshAxes:
    axes: dict            # {"x": ndarray, ...} node positions [cm]
    dimensionality: int


@dataclass(frozen=True)
class ScalarField:
    name: str
    values: np.ndarray
    unit: str


@dataclass(frozen=True)
class VectorField:
    name: str
    components: dict      # {"x": ndarray, ...}
    unit: str


@dataclass(frozen=True)
class TerminalCurrent:
    name: str
    value: float
    unit: str             # "A/cm" in 2D, "A" in 3D -- never render without it


@dataclass(frozen=True)
class SweepResult:
    """One executed voltage sweep, kept SEPARATE from single-run data.

    voltages/converged cover every ATTEMPTED point; a point whose Newton
    solve diverged has converged=False and its per-channel value is NaN,
    so no consumer can present it as valid measurement.  `channels` maps
    an ohmic contact name (or "device" at 1D) to the current series;
    `unit` applies to every channel ("A/cm^2" at 1D, "A/cm" at 2D, "A"
    at 3D).  `meta` carries the ramp parameters as written by
    solver_runner.run_sweep().
    """
    contact: str            # swept contact/gate name
    meta: dict              # {"contact","start","stop","step","dimensionality"}
    voltages: np.ndarray    # [V] per attempted point
    converged: np.ndarray   # bool per attempted point
    channels: dict          # {name: ndarray}; NaN where not converged
    unit: str

    def n_points(self):
        return int(self.voltages.size)

    def n_valid(self):
        return int(self.converged.sum())


class ResultStore(ABC):
    @abstractmethod
    def mesh_axes(self): ...

    @abstractmethod
    def scalar_field(self, name): ...

    @abstractmethod
    def vector_field(self, name): ...

    @abstractmethod
    def terminal_current(self, name): ...

    @abstractmethod
    def available_scalars(self): ...

    @abstractmethod
    def available_terminals(self): ...


class NpzResultStore(ResultStore):
    """Reads the key convention solver_runner.extract_result() writes.

    Opening validates the file against the documented result grammar
    (gui/services.solver_backend) and fails fast with a
    ResultSchemaError on corruption or an unsupported schema version --
    a broken file must be reported at load, not surface later as a
    cryptic KeyError deep inside a plot.
    """

    def __init__(self, path):
        self.path = path
        self._d = np.load(path)
        from .solver_backend import validate_result
        validate_result(self._d)   # validates our open handle, no re-read

    def mesh_axes(self):
        d = int(self._d["dimensionality"])
        axes = {name: self._d[f"axis_{name}"] for name in ("x", "y", "z")[:d]}
        return MeshAxes(axes=axes, dimensionality=d)

    def available_scalars(self):
        return sorted(k[len("field__"):] for k in self._d.files
                      if k.startswith("field__"))

    def scalar_field(self, name):
        key = f"field__{name}"
        if key not in self._d:
            raise KeyError(f"no scalar field '{name}' in {self.path}")
        return ScalarField(name=name, values=self._d[key],
                           unit=str(self._d[f"unit__{name}"]))

    def vector_field(self, name):
        prefix = f"vector__{name}__"
        comps = {k[len(prefix):]: self._d[k] for k in self._d.files
                 if k.startswith(prefix)}
        if not comps:
            raise KeyError(f"no vector field '{name}' in {self.path}")
        return VectorField(name=name, components=comps,
                           unit=str(self._d[f"unit__{name}"]))

    def available_terminals(self):
        return sorted(k[len("terminal__"):-len("__value")] for k in self._d.files
                      if k.startswith("terminal__") and k.endswith("__value"))

    def terminal_current(self, name):
        key = f"terminal__{name}__value"
        if key not in self._d:
            raise KeyError(f"no terminal current '{name}' in {self.path}")
        return TerminalCurrent(name=name, value=float(self._d[key]),
                               unit=str(self._d[f"terminal__{name}__unit"]))

    # -- sweep series (v0.4) ------------------------------------------
    def has_sweep(self):
        return "sweep__voltage" in self._d

    def sweep_result(self):
        """The executed sweep as a SweepResult, or KeyError for a plain
        single-run result.  Non-converged points are NaN'd here at the
        boundary; their identity survives in `converged`."""
        if not self.has_sweep():
            raise KeyError(f"no sweep series in {self.path}")
        meta = json.loads(str(self._d["sweep__meta"]))
        converged = np.asarray(self._d["sweep__converged"], dtype=bool)
        prefix = "sweep__current__"
        channels = {}
        for k in self._d.files:
            if k.startswith(prefix):
                vals = np.asarray(self._d[k], dtype=float).copy()
                vals[~converged] = np.nan
                channels[k[len(prefix):]] = vals
        return SweepResult(
            contact=meta.get("contact", ""),
            meta=meta,
            voltages=np.asarray(self._d["sweep__voltage"], dtype=float),
            converged=converged,
            channels=channels,
            unit=str(self._d["unit__sweep_current"]),
        )


class SpecResultStore(ResultStore):
    """A DeviceSpec presented as a doping-only ResultStore, so the
    structure can be drawn before (or instead of) a solve."""

    def __init__(self, spec):
        self._spec = spec
        self._doping = np.asarray(spec.doping.values,
                                  dtype=float).reshape(spec.mesh.shape())

    def mesh_axes(self):
        d = self._spec.mesh.dimensionality
        axes = {name: np.asarray(self._spec.mesh.axes[name], dtype=float)
                for name in ("x", "y", "z")[:d]}
        return MeshAxes(axes=axes, dimensionality=d)

    def available_scalars(self):
        return ["doping"]

    def scalar_field(self, name):
        if name != "doping":
            raise KeyError(f"a structure preview has only 'doping', not '{name}'")
        return ScalarField(name="doping", values=self._doping, unit="cm^-3")

    def vector_field(self, name):
        raise KeyError("a structure preview has no vector fields")

    def available_terminals(self):
        return []

    def terminal_current(self, name):
        raise KeyError("a structure preview has no terminal currents")

    def has_sweep(self):
        return False

    def sweep_result(self):
        raise KeyError("a structure preview has no sweep series")
