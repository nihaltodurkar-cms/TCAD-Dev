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
    """Reads the key convention solver_runner.extract_result() writes."""

    def __init__(self, path):
        self.path = path
        self._d = np.load(path)

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
