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


def extract_line_cut(axes: MeshAxes, field: ScalarField, orientation: str,
                     position_cm: float):
    """A 1D slice through a 2D scalar field, at the mesh row/column
    NEAREST to `position_cm` -- nearest-node, not interpolated, and
    honestly labeled that way (the mesh may be non-uniform, so "the
    row closest to y=1.2e-4 cm" and "the row at exactly y=1.2e-4 cm"
    are genuinely different claims; only the former is made here).

    orientation="horizontal": cut at the nearest y, values vary along x.
    orientation="vertical":   cut at the nearest x, values vary along y.

    Returns (coord_cm, value, actual_position_cm): `actual_position_cm`
    is the coordinate of the node actually used, so a caller can report
    "cut at y=1.234e-4 cm (nearest to the requested 1.2e-4 cm)" rather
    than silently pretending the requested position was hit exactly.
    """
    if axes.dimensionality != 2:
        raise ValueError(
            f"line cuts require a 2D field, got dimensionality="
            f"{axes.dimensionality}")
    x = np.asarray(axes.axes["x"], dtype=float)
    y = np.asarray(axes.axes["y"], dtype=float)
    values = np.asarray(field.values, dtype=float)
    if orientation == "horizontal":
        j = int(np.argmin(np.abs(y - position_cm)))
        return x, values[j, :], float(y[j])
    if orientation == "vertical":
        i = int(np.argmin(np.abs(x - position_cm)))
        return y, values[:, i], float(x[i])
    raise ValueError(
        f"orientation must be 'horizontal' or 'vertical', got "
        f"{orientation!r}")


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


@dataclass(frozen=True)
class TransientResult:
    """One executed transient (time-domain) run (M17 phase 3).

    `channels` maps a contact name to its current-vs-time series (BOTH
    named contacts at 1D -- a transient state has no single
    well-defined "device" current the way a steady state does; every
    registered ohmic contact at 2D). `meta` carries the waveform/
    timing parameters as written by solver_runner.run_transient().
    """
    contact: str            # stimulus contact/gate name
    meta: dict              # {"contact","waveform","t_end","dt0","theta","dimensionality"}
    times: np.ndarray       # [s] per accepted time step
    channels: dict          # {name: ndarray}
    unit: str

    def n_points(self):
        return int(self.times.size)


@dataclass(frozen=True)
class SweepSnapshots:
    """Sweep field snapshots for animated 3D playback.

    Stores a snapshot of every scalar field at each converged sweep
    point. The viewer reconstructs 3D arrays from the flattened
    snapshots using the mesh shape from the ResultStore.

    voltages: [V] per converged point (only converged points have
        snapshots).
    field_names: sorted list of scalar field names that have snapshots.
    shape: the mesh shape (Nz, Ny, Nx) for reshaping flattened arrays.
    _data: flat mapping (field_name, index) -> flattened ndarray.
    """
    voltages: np.ndarray
    field_names: list
    shape: tuple
    _data: dict   # {(name, idx): flattened_arr}

    def n_snapshots(self):
        """Number of converged sweep points with snapshots."""
        return self.voltages.size

    def field(self, field_name, idx):
        """Return the 3D field array at snapshot index `idx`.

        Raises KeyError if `field_name` is not one of the snapshot
        field names or if `idx` is out of range.
        """
        if field_name not in self.field_names:
            raise KeyError(
                f"no snapshot for field '{field_name}' "
                f"(available: {self.field_names})")
        if idx < 0 or idx >= self.n_snapshots():
            raise IndexError(
                f"snapshot index {idx} out of range [0, {self.n_snapshots()})")
        flat = self._data[(field_name, idx)]
        return flat.reshape(self.shape)

    def voltage(self, idx):
        """Return the voltage at snapshot index `idx`."""
        if idx < 0 or idx >= self.n_snapshots():
            raise IndexError(
                f"snapshot index {idx} out of range [0, {self.n_snapshots()})")
        return float(self.voltages[idx])


class ResultStore(ABC):
    """The store contract.  Controllers and the visualization layer must
    ask STORES these questions -- never type-check concrete classes --
    so a future backend's store plugs in by satisfying this interface,
    not by being whitelisted anywhere.

    Sweep and solved-result support are protocol members with honest
    defaults rather than abstractmethods: most stores legitimately carry
    neither."""

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

    # -- protocol with defaults ------------------------------------------
    def is_solved_result(self):
        """True only for stores wrapping an actual solve output.
        Previews (e.g. SpecResultStore) must stay False so 'results
        loaded' UI state never lies."""
        return False

    def has_sweep(self):
        return False

    def sweep_result(self):
        raise KeyError("this store carries no executed voltage sweep")

    def has_transient(self):
        return False

    def transient_result(self):
        raise KeyError("this store carries no executed transient run")


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

    def is_solved_result(self):
        return True

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

    # -- run provenance (v2) --------------------------------------------
    def has_record(self):
        return "record__meta" in self._d

    def run_record(self):
        """The RunRecord (provenance + convergence trace), or None for
        pre-v2 files, which simply have no recorded provenance."""
        from .solver_backend import RunRecord
        if not self.has_record():
            return None
        return RunRecord.from_npz_keys(self._d)

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

    # -- transient series (M17 phase 3) ---------------------------------
    def has_transient(self):
        return "transient__times" in self._d

    def transient_result(self):
        """The executed transient run as a TransientResult, or KeyError
        for a result with no transient block."""
        if not self.has_transient():
            raise KeyError(f"no transient series in {self.path}")
        meta = json.loads(str(self._d["transient__meta"]))
        prefix = "transient__current__"
        channels = {k[len(prefix):]: np.asarray(self._d[k], dtype=float)
                   for k in self._d.files if k.startswith(prefix)}
        return TransientResult(
            contact=meta.get("contact", ""),
            meta=meta,
            times=np.asarray(self._d["transient__times"], dtype=float),
            channels=channels,
            unit=str(self._d["unit__transient_current"]),
        )

    # -- sweep snapshots (Phase 4) --------------------------------------
    def has_sweep_snapshots(self):
        """True when the npz contains sweep snapshot voltages.

        Field data may be absent -- `sweep_snapshots()` will raise
        KeyError in that case.
        """
        return "sweep__snapshot__voltages" in self._d

    def sweep_snapshots(self):
        """Return SweepSnapshots for animation playback.

        Raises KeyError if voltages are present but no field data exists.
        """
        if not self.has_sweep_snapshots():
            raise KeyError("no sweep snapshots in this store")
        voltages_data = self._d["sweep__snapshot__voltages"]
        # Handle both JSON string and numpy array storage -- same fragility
        # (and same fallback) as mesh__shape just below: a backend that
        # saves this field as a raw numpy array gets a str() like
        # "[0.1 0.2 0.3]" (no commas), which json.loads() can't parse.
        voltages_str = str(voltages_data)
        if voltages_str.startswith("[") and "," not in voltages_str:
            voltages = np.asarray([float(x) for x in voltages_str.strip("[]").split()])
        else:
            voltages = np.asarray(json.loads(voltages_str))
        mesh_shape_data = self._d["mesh__shape"]
        # Handle both JSON string and numpy array storage
        mesh_shape_str = str(mesh_shape_data)
        if mesh_shape_str.startswith("[") and "," not in mesh_shape_str:
            # numpy array string representation like "[4 5]"
            mesh_shape = tuple(int(x) for x in mesh_shape_str.strip("[]").split())
        else:
            mesh_shape = tuple(json.loads(mesh_shape_str))
        prefix = "sweep__snapshot__field__"
        field_names = sorted(set(
            k[len(prefix):].rsplit("__", 1)[0]
            for k in self._d.files
            if k.startswith(prefix)
        ))
        if not field_names:
            raise KeyError("no field data for sweep snapshots")
        _data = {}
        for fname in field_names:
            # Find all indices for this field
            indices = sorted(set(
                int(k.rsplit("__", 1)[1])
                for k in self._d.files
                if k.startswith(f"{prefix}{fname}__")
            ))
            for idx in indices:
                key = f"{prefix}{fname}__{idx}"
                _data[(fname, idx)] = np.asarray(self._d[key]).reshape(mesh_shape)
        return SweepSnapshots(
            voltages=voltages,
            field_names=field_names,
            shape=mesh_shape,
            _data=_data,
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
