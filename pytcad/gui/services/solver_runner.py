"""Solver subprocess entry point.

    python -m gui.services.solver_runner <job.json> <out.npz>

Run in a SEPARATE PROCESS by the GUI (see gui/services/job_runner.py).
That is the whole non-blocking and cancellation design: pytcad's Newton
loops are synchronous with no progress callback and no cancellation hook,
and rather than modify the validated numerical code to add one, the GUI
runs them out-of-process.  Killing a process is always safe; killing a
Python thread mid-spsolve is not.

Deliberately imports NO Qt.  This file is a usable CLI on its own, which
is what keeps the backend reachable from a notebook, a script, or a
future non-Qt frontend (design spec section 20).

This module is also the ONLY place permitted to know pytcad's
per-dimensionality API differences -- see extract_result().
"""
import io
import json
import math
import os
import re
import sys
import traceback
import warnings
from dataclasses import asdict, replace
from datetime import datetime, timezone

import numpy as np

from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D
from pytcad.device import Device1D, Models, NewtonOptions
from pytcad.device2d import Device2D
from pytcad.device3d import Device3D

from .device_spec import DeviceSpec
from .solver_backend import (
    GEOM_STRUCTURED, SOLVER_RESULT_SCHEMA_VERSION, ConvergenceStep,
)


# ----------------------------------------------------------------------
#  Construction
# ----------------------------------------------------------------------
def build_mesh(mesh_spec):
    """Return the object pytcad's Device* constructor expects.

    Note the asymmetry, which is pytcad's and not ours to fix here:
    Device2D/Device3D take a Mesh2D/Mesh3D object, but Device1D takes a
    raw x array -- there is no Mesh1D class.  Special-case it explicitly
    rather than inventing a wrapper.
    """
    d = mesh_spec.dimensionality
    if d == 1:
        return np.asarray(mesh_spec.axes["x"], dtype=float)
    if d == 2:
        return Mesh2D(np.asarray(mesh_spec.axes["x"], dtype=float),
                      np.asarray(mesh_spec.axes["y"], dtype=float))
    if d == 3:
        return Mesh3D(np.asarray(mesh_spec.axes["x"], dtype=float),
                      np.asarray(mesh_spec.axes["y"], dtype=float),
                      np.asarray(mesh_spec.axes["z"], dtype=float))
    raise ValueError(f"dimensionality must be 1, 2 or 3, got {d}")


def build_doping(doping_spec, shape):
    if doping_spec.kind != "array":
        raise ValueError(f"unsupported doping kind '{doping_spec.kind}' "
                         f"(v0.1 supports 'array' only)")
    values = np.asarray(doping_spec.values, dtype=float).reshape(shape)
    ntotal = (None if doping_spec.ntotal is None
              else np.asarray(doping_spec.ntotal, dtype=float).reshape(shape))
    return values, ntotal


def build_material_grid(spec):
    """M11-S4/S5 pipeline wiring: resolve spec.material plus
    region_materials boxes into a flat per-node material list through
    the workbench MaterialLibrary (case-insensitive).  Returns None for
    an all-silicon device so the legacy single-material constructor
    path (and its bit-identity guarantees) stays untouched.  Unknown
    material names raise KeyError here -- loudly, before any solve."""
    from workbench.core.materials import MaterialLibrary
    entries = getattr(spec, "region_materials", None) or []
    lib = MaterialLibrary()
    d = spec.mesh.dimensionality
    names = ("x", "y", "z")[:d]
    axes = {a: np.asarray(spec.mesh.axes[a], dtype=float) for a in names}
    shape = tuple(axes[a].size for a in names)      # (Nx,) | (Ny,Nx) | (Nz,Ny,Nx)
    base = lib.get(spec.material)
    silicon_only = str(spec.material).upper() in ("SILICON", "SI") \
        and not entries
    if silicon_only:
        return None
    grid = np.empty(shape, dtype=object)
    grid[:] = base
    for k, entry in enumerate(entries):
        mat = lib.get(entry["material"])
        box = entry["box"]
        mask = np.ones(shape, dtype=bool)
        for ax_name, (lo, hi) in zip(names,
                                     (box[0:2], box[2:4], box[4:6])[:d]):
            a = axes[ax_name]
            tol = 1e-9 * max(1.0, float(np.abs(a).max()))
            sel = (a >= lo - tol) & (a <= hi + tol)
            # broadcast the axis selection across the other dimensions
            bshape = [1] * d
            bshape[names.index(ax_name)] = a.size
            mask = mask & sel.reshape(bshape)
        if not mask.any():
            raise ValueError(
                f"region_materials[{k}] ('{entry['material']}') selects "
                "no mesh nodes -- box does not intersect the mesh axes "
                "(boxes are mesh-aligned per the wire-format contract)")
        grid[mask] = mat          # later entries override earlier ones
    return grid.ravel().tolist()


def build_device(spec, mesh_obj, doping, ntotal):
    models = Models(**spec.models)
    mats = build_material_grid(spec)
    d = spec.mesh.dimensionality
    cls = {1: Device1D, 2: Device2D, 3: Device3D}[d]
    if mats is None:
        return cls(mesh_obj, doping, Ntotal=ntotal, T=spec.T,
                   models=models)
    return cls(mesh_obj, doping, Ntotal=ntotal, T=spec.T, models=models,
               material=mats)


def register_contacts(device, spec):
    """Attach contacts/gates.  Device1D has no contact registry at all --
    its ohmic ends are implicit and biased positionally in solve_bias --
    so there is nothing to register at 1D."""
    d = spec.mesh.dimensionality
    if d == 1:
        return
    for c in spec.contacts:
        idx = {"i": np.asarray(c.nodes["i"], dtype=int),
               "j": np.asarray(c.nodes["j"], dtype=int)}
        if d == 3:
            idx["k"] = np.asarray(c.nodes["k"], dtype=int)
        if c.kind == "ohmic":
            device.add_contact(c.name, V=c.V, **idx)
        elif c.kind == "gate":
            if d == 3:
                device.add_gate(c.name, tox_cm=c.tox_cm, Vfb=c.Vfb, Vg=c.V,
                                normal_axis=c.normal_axis, **idx)
            else:
                device.add_gate(c.name, tox_cm=c.tox_cm, Vfb=c.Vfb, Vg=c.V, **idx)
        else:
            raise ValueError(f"unknown contact kind '{c.kind}'")


def merge_bias(spec, override=None):
    """The full {contact_name: V} intent for a solve: ContactSpec.V
    defaults, overridden by DeviceSpec.bias, optionally overridden again
    by a per-sweep-point value.  Matches what register_contacts +
    apply_bias established in v0.1, made explicit so the sweep loop can
    override one name at a time."""
    bias = {c.name: c.V for c in spec.contacts}
    if spec.bias:
        bias.update(spec.bias)
    if override:
        bias.update(override)
    return bias


def apply_bias(device, spec, opts, override=None):
    """Device1D takes a positional [V_left, V_right]; 2D/3D take a
    {name: V} dict.  Another pytcad asymmetry absorbed here."""
    bias = merge_bias(spec, override)
    if spec.mesh.dimensionality == 1:
        if len(spec.contacts) != 2:
            raise ValueError("a 1D device needs exactly two contacts "
                             f"(got {len(spec.contacts)})")
        device.solve_bias([bias[spec.contacts[0].name],
                           bias[spec.contacts[1].name]], opts)
    else:
        device.solve_bias(bias, opts)


# ----------------------------------------------------------------------
#  Normalization -- the ONE place that knows the dimensional differences
# ----------------------------------------------------------------------
def _edge_to_node(a, axis):
    """Average an edge-centered array onto nodes along `axis`.

    pytcad reports current density on mesh EDGES (Jn_x is (Ny, Nx-1) in
    2D), but a viewport wants node-centered values that line up with the
    potential and the axis arrays.  Averaging the two edges touching each
    node -- and the single edge at a boundary node -- is the natural
    box-integration-consistent choice.
    """
    a = np.asarray(a, dtype=float)
    n = a.shape[axis] + 1
    shape = list(a.shape)
    shape[axis] = n
    out = np.zeros(shape)
    lo = [slice(None)] * a.ndim
    hi = [slice(None)] * a.ndim
    lo[axis] = slice(0, n - 1)
    hi[axis] = slice(1, n)
    out[tuple(lo)] += a
    out[tuple(hi)] += a
    w = np.zeros(n)
    w[:-1] += 1.0
    w[1:] += 1.0
    wshape = [1] * a.ndim
    wshape[axis] = n
    return out / w.reshape(wshape)


def extract_result(device, spec, solved_bias):
    """Normalize a solved pytcad device into dimensionality-independent
    arrays with explicit units.

    THIS IS THE ONLY FUNCTION ALLOWED TO KNOW that Device1D exposes
    Jn/Jp while Device2D exposes Jn_x/Jn_y and Device3D adds Jn_z, that
    terminal_current returns A/cm in 2D but real A in 3D, and that
    Device1D has no terminal_current at all.  Everything above this line
    -- ResultStore, controllers, QML -- sees one uniform convention.
    """
    d = spec.mesh.dimensionality
    out = {"dimensionality": np.array(d),
           "solved_bias": np.array(bool(solved_bias))}

    for name in ("x", "y", "z")[:d]:
        out[f"axis_{name}"] = np.asarray(spec.mesh.axes[name], dtype=float)

    scalars = {
        "potential": (device.psi_V, "V"),
        "electron_density": (device.n_cm3, "cm^-3"),
        "hole_density": (device.p_cm3, "cm^-3"),
        "doping": (device.doping, "cm^-3"),
    }
    for name, (arr, unit) in scalars.items():
        out[f"field__{name}"] = np.asarray(arr, dtype=float)
        out[f"unit__{name}"] = np.array(unit)

    if solved_bias:
        # Total current density Jn + Jp, per axis, moved onto nodes.
        # 1D: .Jn/.Jp (no suffix).  2D: _x,_y.  3D: _x,_y,_z.
        if d == 1:
            comps = {"x": (device.Jn + device.Jp, 0)}
        elif d == 2:
            comps = {"x": (device.Jn_x + device.Jp_x, 1),
                     "y": (device.Jn_y + device.Jp_y, 0)}
        else:
            comps = {"x": (device.Jn_x + device.Jp_x, 2),
                     "y": (device.Jn_y + device.Jp_y, 1),
                     "z": (device.Jn_z + device.Jp_z, 0)}
        for axis_name, (arr, axis_index) in comps.items():
            out[f"vector__current_density__{axis_name}"] = _edge_to_node(arr, axis_index)
        out["unit__current_density"] = np.array("A/cm^2")

        # terminal currents: 2D is per unit depth, 3D is a real current,
        # 1D has no terminal_current method at all.
        if d in (2, 3):
            unit = "A/cm" if d == 2 else "A"
            for c in spec.contacts:
                if c.kind != "ohmic":
                    continue
                out[f"terminal__{c.name}__value"] = np.array(
                    float(device.terminal_current(c.name)))
                out[f"terminal__{c.name}__unit"] = np.array(unit)
    return out


# ----------------------------------------------------------------------
#  Sweeps (v0.4)
# ----------------------------------------------------------------------
def run_sweep(device, spec, opts=None, fallback_fields=None):
    """Execute spec.sweep on an EQUILIBRIUM-SOLVED device.

    Warm-started ramp: one device object is reused across points, so each
    Newton solve starts from the previous bias's solution -- the same
    pattern as pytcad's own iv_sweep / mosfet.id_vg_sweep, applied here
    at the GUI boundary where any contact can be the swept one.  No
    numerical code is modified; divergence detection borrows pytcad's
    existing "did not converge" warnings instead of adding a callback.

    Returns (fields, series):
      fields  extract_result() dict from the last CONVERGED point, or
              `fallback_fields` if every point diverged -- callers pass
              the pre-sweep equilibrium snapshot here so a fully-diverged
              sweep can never present a diverged state as a biased result;
      series  flat npz keys: sweep__voltage, sweep__converged,
              sweep__current__<channel>, unit__sweep_current, sweep__meta.

    Channels are the ohmic terminal currents at 2D/3D (A/cm and A) and
    the single total current density at 1D (A/cm^2), matching
    extract_result's dimensional convention.
    """
    opts = opts or NewtonOptions(verbose=True)
    sw = spec.sweep
    sw.validate([c.name for c in spec.contacts])
    d = spec.mesh.dimensionality

    if d == 1:
        channels = ["device"]        # Device1D has no terminal registry
    else:
        channels = [c.name for c in spec.contacts if c.kind == "ohmic"]

    currents = {name: [] for name in channels}
    converged_flags = []
    fields = None

    voltages = sw.voltages()
    for i, V in enumerate(voltages):
        print(f"PYTCAD_STAGE=sweep point {i + 1}/{len(voltages)}", flush=True)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            apply_bias(device, spec, opts, override={sw.contact: V})
        ok = not any("did not converge" in str(w.message) for w in caught)
        converged_flags.append(ok)

        if d == 1:
            J_mean, _ = device.current_density()
            currents["device"].append(float(J_mean))
        else:
            for name in channels:
                currents[name].append(float(device.terminal_current(name)))

        # Keep only converged solutions for the stored field snapshot:
        # a diverged point must not overwrite good fields with a
        # nonphysical state.
        if ok:
            fields = extract_result(device, spec, solved_bias=True)

    series = {
        "sweep__voltage": np.asarray(voltages, dtype=float),
        "sweep__converged": np.asarray(converged_flags, dtype=bool),
        "unit__sweep_current": np.array(
            {1: "A/cm^2", 2: "A/cm", 3: "A"}[d]),
        "sweep__meta": np.array(json.dumps({
            "contact": sw.contact, "start": sw.start, "stop": sw.stop,
            "step": sw.step, "dimensionality": d})),
    }
    for name, vals in currents.items():
        series[f"sweep__current__{name}"] = np.asarray(vals, dtype=float)
    return fields if fields is not None else fallback_fields, series



# ----------------------------------------------------------------------
# v0.5.0 M2: provenance + convergence trace, with ZERO numerical changes.
# The core already prints its Newton progress when verbose=True; we tee
# this process's stdout (JobRunner streaming is unaffected -- everything
# captured still goes through to the console panel) and parse that text
# into per-stage traces, split on the runner's own PYTCAD_STAGE markers.
# A unit test pins the core line formats so silent drift fails loudly.
# ----------------------------------------------------------------------
class _Tee(io.TextIOBase):
    def __init__(self, *streams):
        self._streams = streams

    def write(self, text):
        for stream in self._streams:
            stream.write(text)
        return len(text)

    def flush(self):
        for stream in self._streams:
            stream.flush()


def _start_capture():
    """Begin teeing stdout into a buffer.  Returns an opaque handle for
    _stop_capture()."""
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = _Tee(real, buf)
    return buf, real


def _stop_capture(handle):
    buf, real = handle
    sys.stdout = real
    return buf.getvalue()


_STAGE_LINE = re.compile(r"^PYTCAD_STAGE=(\w+)(?:\s+(.*))?$")
_SWEEP_POINT = re.compile(r"point (\d+)/(\d+)")   # 'sweep' is consumed by
                                                  # _STAGE_LINE's group(1)
_ITERATION = re.compile(r"\bit\s+(\d+)\b")
_METRIC = re.compile(
    r"\|\s*([^|]+?)\s*\|\s*=\s*(-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?\d+)?)")


def _trace_from_output(text):
    """Parse verbose solver output into ConvergenceSteps.  Unknown lines
    are skipped, never fatal -- the trace is diagnostic, not load-bearing."""
    steps = []
    current = None

    def close():
        nonlocal current
        if current is not None and current.iterations:
            steps.append(current)
        # a stage whose solve produced no iteration lines (trivial/no-op)
        # carries no information and is dropped entirely

    for raw in text.splitlines():
        marker = _STAGE_LINE.match(raw.strip())
        if marker:
            name, extra = marker.group(1), marker.group(2) or ""
            if name == "sweep" and "point" in extra:
                point = _SWEEP_POINT.search(extra)
                stage = f"sweep:{int(point.group(1)) - 1}" if point else None
            elif name in ("equilibrium", "bias"):
                stage = name
            else:
                stage = None          # e.g. "extract": nothing to record
            close()
            current = None if stage is None else ConvergenceStep(stage=stage)
            continue
        if current is None:
            continue
        it = _ITERATION.search(raw)
        metrics = _METRIC.findall(raw)
        if it and metrics:
            new_metrics = {k: list(v) for k, v in current.metrics.items()}
            for name, val in metrics:
                x = float(val)
                # a diverged iterate can print inf/nan; those must never
                # reach the trace as bare Infinity/NaN tokens (invalid
                # strict JSON for every non-Python consumer)
                new_metrics.setdefault(name.strip(), []).append(
                    x if math.isfinite(x) else None)
            current = replace(current,
                              iterations=current.iterations +
                              (int(it.group(1)),),
                              metrics=new_metrics)
    close()
    return steps


def _node_coords(mesh_spec):
    """Flat node coordinates [cm], (N, dim), x-fastest -- exactly
    Mesh2D/Mesh3D's idx() ordering (ravel order='F')."""
    axes = [np.asarray(mesh_spec.axes[k], dtype=float)
            for k in ("x", "y", "z")[:mesh_spec.dimensionality]]
    grids = np.meshgrid(*axes, indexing="ij")
    return np.stack([g.ravel(order="F") for g in grids], axis=1)


# ----------------------------------------------------------------------
#  Entry point
# ----------------------------------------------------------------------
def _solve_all(device, spec, opts):
    """Equilibrium + (optional) bias or sweep, emitting the same
    PYTCAD_STAGE markers JobRunner has always streamed.  Returns the
    raw result dict in the v1 key shape."""
    print("PYTCAD_STAGE=equilibrium", flush=True)
    device.solve_equilibrium(opts)

    if spec.sweep is not None:
        print("PYTCAD_STAGE=sweep", flush=True)
        # Snapshot the equilibrium state BEFORE the sweep mutates the
        # device: if every point diverges, this (honestly labeled
        # solved_bias=False) is what gets stored -- never a diverged
        # nonphysical field set. (Final review finding I-4.)
        equilibrium_fields = extract_result(device, spec, solved_bias=False)
        fields, series = run_sweep(device, spec, opts,
                                   fallback_fields=equilibrium_fields)
        result = fields
        result.update(series)
    else:
        solved_bias = spec.bias is not None
        if solved_bias:
            print("PYTCAD_STAGE=bias", flush=True)
            apply_bias(device, spec, opts)

        print("PYTCAD_STAGE=extract", flush=True)
        result = extract_result(device, spec, solved_bias)
    return result


def run_job(job_path, out_path, capture_trace=True):
    spec = DeviceSpec.from_json(job_path)
    # M11-S4/S5: non-silicon jobs are SOLVED -- region_materials are
    # resolved through the MaterialLibrary and rasterized into per-node
    # material lists inside build_device.  Unknown material names fail
    # loudly there (KeyError), before any solve starts.
    if spec.sweep is not None:
        # Fail fast on an unexecutable sweep, BEFORE paying for the
        # equilibrium solve.
        spec.sweep.validate([c.name for c in spec.contacts])

    mesh_obj = build_mesh(spec.mesh)
    doping, ntotal = build_doping(spec.doping, spec.mesh.shape())
    device = build_device(spec, mesh_obj, doping, ntotal)
    register_contacts(device, spec)

    # verbose=True is the v0.1 progress channel: JobRunner streams this
    # process's stdout into the console panel.  Cosmetic only -- results
    # are read from the .npz, never parsed from this text.
    opts = NewtonOptions(verbose=True)

    cap = _start_capture()
    try:
        result = _solve_all(device, spec, opts)
    finally:
        # even a failed solve must hand the real stdout back -- the
        # except-handler in main() prints PYTCAD_ERROR through it
        output_text = _stop_capture(cap)

    # Stamp the documented result grammar (now schema v2): readers
    # validate against this via gui.services.solver_backend.
    # validate_result().  Everything here is ADDITIVE over v1 keys.
    result["result__schema"] = np.array(SOLVER_RESULT_SCHEMA_VERSION)
    result["geom__kind"] = np.array(GEOM_STRUCTURED)
    shape = spec.mesh.shape()
    result["mesh__shape"] = np.array(shape)
    coords = _node_coords(spec.mesh)
    result["nodes__count"] = np.array(int(coords.shape[0]))
    result["nodes__coords"] = coords

    sweep_meta = None
    if spec.sweep is not None:
        sweep_meta = json.loads(str(result["sweep__meta"]))
    result["record__meta"] = np.array(json.dumps({
        "schema_version": SOLVER_RESULT_SCHEMA_VERSION,
        "backend": "pytcad",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dimensionality": spec.mesh.dimensionality,
        "material": spec.material,
        "T": spec.T,
        "models": spec.models,
        "numerics": asdict(opts),
        "sweep": sweep_meta,
    }))

    if capture_trace:
        steps = _trace_from_output(output_text)
        flags = result.get("sweep__converged")
        patched = []
        for step in steps:
            if step.stage.startswith("sweep:") and flags is not None:
                idx = int(step.stage.split(":")[1])
                step = replace(step, converged=bool(np.asarray(flags)[idx]))
            patched.append(step)
        result["converge__trace"] = np.array(
            json.dumps([step.to_dict() for step in patched]))

    # Atomic write: a killed process must never leave a partial file at
    # the canonical path (see the design spec's cancellation-safety
    # section and test_kill_leaves_no_file_at_canonical_path).
    # np.savez appends ".npz" to a path that doesn't already end in it,
    # so the temp name must itself end in ".npz" -- otherwise this would
    # write "<out>.tmp.npz" while renaming a nonexistent "<out>.tmp".
    tmp_path = out_path + ".tmp.npz"
    np.savez(tmp_path, **result)
    os.replace(tmp_path, out_path)
    print(f"RESULT_PATH={out_path}", flush=True)


def main(argv):
    if len(argv) != 3:
        print("usage: python -m gui.services.solver_runner <job.json> <out.npz>",
              file=sys.stderr)
        return 2
    try:
        run_job(argv[1], argv[2])
    except Exception as exc:
        # Structured, parseable failure -- JobRunner turns this into a
        # concise message plus expandable details, and the GUI process
        # itself never crashes from a backend failure.
        payload = {"error": type(exc).__name__, "message": str(exc),
                   "traceback": traceback.format_exc()}
        print("PYTCAD_ERROR=" + json.dumps(payload), file=sys.stderr, flush=True)
        print(payload["traceback"], file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
