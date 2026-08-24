"""The solver-backend boundary, formalized (v0.5.0 task 1).

Every solver backend -- today gui.services.solver_runner (the homegrown
FD/Newton core), tomorrow potentially a DEVSIM adapter -- must honor the
same contract:

    INPUT   a DeviceSpec JSON file (gui/services/device_spec.py; pure
            data, no Qt, no pytcad imports)
    OUTPUT  an .npz result file written atomically (write to
            <out>.tmp.npz, then os.replace), obeying the key grammar
            below and stamped with result__schema.

Qt-free by design: this module may be imported from inside the solver
subprocess just as well as from the UI process.

THE RESULT KEY GRAMMAR (canonical reference)
--------------------------------------------
Common, every dimensionality:
    dimensionality                  int scalar, 1 | 2 | 3
    solved_bias                     bool scalar
    axis_x [, axis_y [, axis_z]]    node positions [cm], one per dim,
                                    lengths prod() to every field shape
    field__<name>                   node-centered scalar field;
                                    potential/electron_density/
                                    hole_density/doping are always
                                    written by the reference backend
    unit__<name>                    unit string for field__<name> AND for
                                    vector__<name>__* ("V", "cm^-3", ...)
    vector__<name>__<axis>          node-averaged current-density
                                    components, one per axis of the
                                    dimensionality; canonical name
                                    "current_density"
    unit__current_density           "A/cm^2" (1D) | "A/cm" (2D) | "A" (3D)
    result__schema                  int, SOLVER_RESULT_SCHEMA_VERSION
                                    (absent on pre-v0.5 files = legacy v1)
2D/3D only:
    terminal__<contact>__value      terminal current scalar
    terminal__<contact>__unit       "A/cm" (2D) | "A" (3D)
Swept runs only (complete block, never partial):
    sweep__voltage                  [V] per attempted point
    sweep__converged                bool per attempted point
    sweep__current__<channel>       per-channel series, same length;
                                    channel = ohmic contact name at 2D/3D,
                                    "device" at 1D; NaN where diverged is
                                    applied by the STORE, not the writer
    unit__sweep_current             same unit convention as above
    sweep__meta                     JSON string: {"contact", "start",
                                    "stop", "step", "dimensionality"}

Validation here is STRUCTURAL, not an inventory: a legal file may carry
any subset of fields (tests write minimal fixtures), but whatever it
carries must be internally consistent.  A future backend that cannot
honor this grammar should not exist; fix it at the backend, not here.
"""
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

# Schema history: 1 = the v0.5.0 grammar (stamped or legacy-absent),
# 2 = v2 adds geom/mesh/node keys plus record__meta provenance and an
# optional converge__trace.  Everything is ADDITIVE -- a v2 file is a
# valid v1 file with more keys, so v1 readers keep working untouched.
SOLVER_RESULT_SCHEMA_VERSION = 2
KNOWN_RESULT_SCHEMA_VERSIONS = frozenset({1, 2})

GEOM_STRUCTURED = "structured_rectilinear"
GEOM_POINT_CLOUD = "point_cloud"      # RESERVED: validated as declared-but-
                                      # unreadable until a backend produces it
_KNOWN_GEOM_KINDS = (GEOM_STRUCTURED, GEOM_POINT_CLOUD)


@dataclass(frozen=True)
class ConvergenceStep:
    """One solver stage's Newton history, parsed from the core's own
    verbose output (no numerical code is modified to produce this)."""
    stage: str                       # "equilibrium" | "bias" | "sweep:<i>"
    iterations: tuple = ()           # int per Newton iteration
    metrics: dict = field(default_factory=dict)   # {"|dpsi|": [...], ...}
    converged: bool = True

    def to_dict(self):
        return {"stage": self.stage, "iterations": list(self.iterations),
                "metrics": {k: list(v) for k, v in self.metrics.items()},
                "converged": self.converged}

    @classmethod
    def from_dict(cls, d):
        return cls(stage=str(d.get("stage", "?")),
                   iterations=tuple(d.get("iterations", [])),
                   metrics=dict(d.get("metrics", {})),
                   converged=bool(d.get("converged", True)))


@dataclass(frozen=True)
class RunRecord:
    """Provenance of one executed solve: what was asked, with which
    physics and numerics, and how convergence actually went.  This is
    the substrate the Physics Lab will render; nothing here is parsed
    from results text -- it is written by the runner that did the work."""
    backend: str
    created_utc: str
    dimensionality: int
    material: str
    T: float
    models: dict
    numerics: dict
    sweep: dict = None
    trace: tuple = ()                  # ConvergenceStep tuples
    schema_version: int = SOLVER_RESULT_SCHEMA_VERSION

    @classmethod
    def from_npz_keys(cls, d):
        """Parse record__meta (+ optional converge__trace) from an open
        npz mapping.  Returns None when the file carries no record --
        pre-v2 files simply have provenance 'unknown'."""
        if "record__meta" not in getattr(d, "files", ()):
            return None
        meta = json.loads(str(np.asarray(d["record__meta"]).reshape(())))
        trace = ()
        if "converge__trace" in getattr(d, "files", ()):
            raw = json.loads(str(np.asarray(d["converge__trace"]).reshape(())))
            trace = tuple(ConvergenceStep.from_dict(s) for s in raw)
        # report the version the FILE is stamped with, falling back to
        # the record's own claim for legacy unstamped writers
        stamped = meta.get("schema_version", 2)
        if "result__schema" in getattr(d, "files", ()):
            stamped = int(np.asarray(d["result__schema"]).reshape(()))
        return cls(
            backend=meta.get("backend", ""), created_utc=meta.get("created_utc", ""),
            dimensionality=int(meta.get("dimensionality", 0)),
            material=meta.get("material", ""), T=float(meta.get("T", 0.0)),
            models=dict(meta.get("models", {})),
            numerics=dict(meta.get("numerics", {})),
            sweep=meta.get("sweep"), trace=trace,
            schema_version=int(stamped))


class ResultSchemaError(ValueError):
    """A result file violates the documented npz grammar."""


def _as_int(d, key, path):
    if key not in d.files:
        raise ResultSchemaError(f"{path}: missing required key '{key}'")
    try:
        return int(np.asarray(d[key]).reshape(()))
    except Exception:
        raise ResultSchemaError(f"{path}: '{key}' must be a scalar integer")


def _require(d, key, why, path):
    if key not in d.files:
        raise ResultSchemaError(f"{path}: missing required key "
                                f"'{key}' ({why})")


def validate_result(npz):
    """Validate an npz result against the documented grammar.

    `npz` is a filesystem path OR an already-opened numpy NpzFile (the
    store validates its own handle to avoid double-opening).  Raises
    ResultSchemaError with an actionable message; returns the schema
    version found (legacy files without a stamp count as version 1).
    """
    opened_here = False
    if isinstance(npz, str):
        if not npz.endswith(".npz") or not os.path.isfile(npz):
            raise ResultSchemaError(
                f"{npz}: result file not found or not an .npz path")
        try:
            d = np.load(npz)
            opened_here = True
        except Exception as exc:
            raise ResultSchemaError(f"{npz}: not a readable npz archive "
                                    f"({exc})") from exc
    else:
        d = npz
    try:
        return _validate_mapping(d, getattr(d, "filename", None) or "<npz>")
    finally:
        if opened_here:
            d.close()


def _validate_mapping(d, path):
    # -- not an npz at all ------------------------------------------------
    files = set(getattr(d, "files", None) or ())
    if not files:
        raise ResultSchemaError(f"{path}: not an npz result archive")

    # -- schema stamp (optional => legacy v1) ------------------------------
    schema_found = SOLVER_RESULT_SCHEMA_VERSION
    if "result__schema" in files:
        schema_found = _as_int(d, "result__schema", path)
        if schema_found not in KNOWN_RESULT_SCHEMA_VERSIONS:
            raise ResultSchemaError(
                f"{path}: result schema version {schema_found} unsupported "
                f"(this build reads "
                f"{sorted(KNOWN_RESULT_SCHEMA_VERSIONS)}); re-run the solver")

    # -- dimensionality + axes ---------------------------------------------
    _require(d, "solved_bias", "always required", path)
    dim = _as_int(d, "dimensionality", path)
    if dim not in (1, 2, 3):
        raise ResultSchemaError(f"{path}: dimensionality must be 1, 2 or 3, "
                                f"got {dim}")
    axes = {}
    n_nodes = 1
    for name in ("x", "y", "z")[:dim]:
        key = f"axis_{name}"
        _require(d, key, f"a {dim}D result needs it", path)
        arr = np.asarray(d[key])
        if arr.ndim != 1 or arr.size == 0:
            raise ResultSchemaError(f"{path}: '{key}' must be a non-empty "
                                    "1D array of node positions")
        axes[name] = arr
        n_nodes *= arr.size
    # Field arrays are (Nx) / (Ny,Nx) / (Nz,Ny,Nx): x-fastest, matching
    # Mesh2D/Mesh3D's row-major idx() convention.
    field_shape = tuple(axes[a].size
                        for a in reversed(("x", "y", "z")[:dim]))

    # -- scalar fields need units and honest shapes --------------------------
    for key in sorted(files):
        if not key.startswith("field__"):
            continue
        name = key[len("field__"):]
        unit_key = f"unit__{name}"
        _require(d, unit_key, f"field__{name} has no declared unit", path)
        values = np.asarray(d[key])
        if values.shape != field_shape:
            raise ResultSchemaError(
                f"{path}: field__{name} shape {values.shape} does not match "
                f"the {dim}D mesh axes {field_shape}")

    # -- vector fields: components per axis + shared unit --------------------
    vec_groups = {}
    for key in sorted(files):
        if key.startswith("vector__"):
            rest = key[len("vector__"):]
            if "__" not in rest:
                raise ResultSchemaError(f"{path}: malformed vector key "
                                        f"'{key}'")
            name, comp = rest.rsplit("__", 1)
            vec_groups.setdefault(name, []).append(comp)
    for name, comps in vec_groups.items():
        _require(d, f"unit__{name}", f"vector__{name}__* has no unit", path)
        expected_axes = list(axes.keys())
        if sorted(comps) != sorted(expected_axes):
            raise ResultSchemaError(
                f"{path}: vector__{name}__ components {sorted(comps)} do "
                f"not match the {dim}D axes {expected_axes}")
        for comp in comps:
            values = np.asarray(d[f"vector__{name}__{comp}"])
            if values.shape != field_shape:
                raise ResultSchemaError(
                    f"{path}: vector__{name}__{comp} shape {values.shape} "
                    "does not match the mesh axes")

    # -- v2: geometry kind, mesh shape, flat node coordinates -------------
    # Consistency checks fire whenever ANY geometry key is present --
    # gating them on geom__kind would let a malformed count slip through
    # an otherwise-v1 file.  point_cloud is RESERVED by schema 2 but no
    # producer or reader exists yet: reject it explicitly instead of
    # failing later with misleading structured-mesh errors.
    if "geom__kind" in files:
        kind = str(np.asarray(d["geom__kind"]).reshape(()))
        if kind not in _KNOWN_GEOM_KINDS:
            raise ResultSchemaError(
                f"{path}: unknown geom__kind '{kind}' (known: "
                f"{', '.join(_KNOWN_GEOM_KINDS)})")
        if kind == GEOM_POINT_CLOUD:
            raise ResultSchemaError(
                f"{path}: geom__kind 'point_cloud' is reserved by schema 2 "
                "but not readable by this build; structured results only")
    if "geom__kind" in files or \
            files & {"mesh__shape", "nodes__count", "nodes__coords"}:
        n_from_shape = None
        if "mesh__shape" in files:
            shape = [int(x) for x in np.asarray(d["mesh__shape"]).ravel()]
            if sorted(shape) != sorted(a.size for a in axes.values()):
                raise ResultSchemaError(
                    f"{path}: mesh__shape {shape} does not match the axes "
                    f"{[a.size for a in axes.values()]}")
            n_from_shape = int(np.prod(shape))
        if "nodes__count" in files:
            count = _as_int(d, "nodes__count", path)
            expected = n_from_shape or int(np.prod([a.size for a in axes.values()]))
            if count != expected:
                raise ResultSchemaError(
                    f"{path}: nodes__count {count} disagrees with the "
                    f"{dim}D mesh ({expected} nodes)")
        else:
            count = n_from_shape
        if "nodes__coords" in files:
            # validated whenever present -- with OR without a declared
            # count (gating this on the count was a validation bypass)
            coords = np.asarray(d["nodes__coords"])
            if coords.ndim != 2 or coords.shape[1] != dim:
                raise ResultSchemaError(
                    f"{path}: nodes__coords shape {coords.shape} must be "
                    f"(N, {dim})")
            if count is not None and coords.shape[0] != count:
                raise ResultSchemaError(
                    f"{path}: nodes__coords has {coords.shape[0]} rows but "
                    f"the mesh declares {count} nodes")

    # -- v2: run record + convergence trace are parseable JSON -------------
    for key, what in (("record__meta", "a JSON object"),
                      ("converge__trace", "a JSON list")):
        if key not in files:
            continue
        try:
            parsed = json.loads(str(np.asarray(d[key]).reshape(())))
        except Exception as exc:
            raise ResultSchemaError(
                f"{path}: {key} is not valid JSON ({exc})") from exc
        if what.endswith("object") and not isinstance(parsed, dict):
            raise ResultSchemaError(f"{path}: {key} must be {what}")
        if what.endswith("list") and not isinstance(parsed, list):
            raise ResultSchemaError(f"{path}: {key} must be {what}")

    # -- terminals come in value/unit pairs (both directions) -----------------
    for key in sorted(files):
        if key.startswith("terminal__") and key.endswith("__value"):
            name = key[len("terminal__"):-len("__value")]
            _require(d, f"terminal__{name}__unit",
                     f"terminal__{name}__value has no unit", path)
        elif key.startswith("terminal__") and key.endswith("__unit"):
            name = key[len("terminal__"):-len("__unit")]
            _require(d, f"terminal__{name}__value",
                     f"orphan terminal__{name}__unit has no value", path)

    # -- sweep block: all-or-nothing, consistent lengths, parseable meta ------
    sweep_keys = [k for k in files if k.startswith("sweep__")]
    if sweep_keys:
        for required in ("sweep__voltage", "sweep__converged",
                         "unit__sweep_current", "sweep__meta"):
            _require(d, required, "an incomplete sweep block is invalid",
                     path)
        voltage = np.asarray(d["sweep__voltage"], dtype=float)
        converged = np.asarray(d["sweep__converged"])
        if converged.shape != voltage.shape or converged.ndim != 1:
            raise ResultSchemaError(
                f"{path}: sweep__converged {converged.shape} must be a 1D "
                f"bool array matching sweep__voltage {voltage.shape}")
        channels = [k for k in sweep_keys
                    if k.startswith("sweep__current__")]
        if not channels:
            raise ResultSchemaError(f"{path}: sweep block has no "
                                    "sweep__current__<channel> series")
        for ch in channels:
            vals = np.asarray(d[ch], dtype=float)
            if vals.shape != voltage.shape:
                raise ResultSchemaError(
                    f"{path}: {ch} length {vals.size} does not match "
                    f"sweep__voltage length {voltage.size}")
        raw_meta = str(np.asarray(d["sweep__meta"]).reshape(()))
        try:
            meta = json.loads(raw_meta)
        except Exception as exc:
            raise ResultSchemaError(f"{path}: sweep__meta is not valid JSON "
                                    f"({exc})") from exc
        if not isinstance(meta, dict) or \
                not isinstance(meta.get("dimensionality"), int):
            raise ResultSchemaError(
                f"{path}: sweep__meta must be a JSON object with an integer "
                "'dimensionality'")

    return schema_found
