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
import importlib.util
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import traceback
import warnings
from dataclasses import asdict, replace
from datetime import datetime, timezone

import numpy as np

# Optional: 4-rank MPI Schwarz domain decomposition for large 3D jobs
# (gui/services/mpi_schwarz_runner.py). Checked by presence, never
# imported at module load -- mpi4py is a real dependency of that OTHER
# module, not of this one, and a machine without it (or without an
# mpirun on PATH) must run this file exactly as before.
_HAVE_MPI = (importlib.util.find_spec("mpi4py") is not None
            and shutil.which("mpirun") is not None)
MPI_SCHWARZ_RANKS = 4

# Real, pre-existing bug fixed here (confirmed by actually running the
# MPI Schwarz path): the mpirun invocation below used to hardcode
# "--allow-run-as-root" unconditionally. That flag is Open MPI-
# specific (Open MPI refuses to run as root without it); MPICH's
# Hydra process manager -- what `mpirun` actually resolves to on a
# plain `conda install mpi4py mpich` machine, confirmed directly via
# `mpirun --version` printing "HYDRA build details" -- has no such
# concept at all and refuses to start with "unrecognized argument
# allow-run-as-root", failing EVERY MPI Schwarz job outright regardless
# of whether the process is actually running as root. Detected once,
# lazily (only when the MPI Schwarz path is actually about to run
# mpirun, not at import time -- this shells out) and cached, since a
# machine's MPI implementation does not change mid-session.
_mpirun_is_openmpi_cache = None


def _mpirun_is_openmpi():
    global _mpirun_is_openmpi_cache
    if _mpirun_is_openmpi_cache is None:
        try:
            out = subprocess.run(["mpirun", "--version"], capture_output=True,
                                 text=True, timeout=10).stdout
        except Exception:
            out = ""
        # Open MPI's own --version banner starts "mpirun (Open MPI)
        # X.Y.Z"; older releases said "Open RTE" instead -- MPICH/Hydra
        # prints "HYDRA build details" and never either string.
        _mpirun_is_openmpi_cache = "Open MPI" in out or "Open RTE" in out
    return _mpirun_is_openmpi_cache

# v0.6 Phase 2d: DeviceSpec.engine's valid values -- "auto" keeps
# run_job()'s existing node-count/dimensionality heuristic; any other
# value forces that engine (see run_job()'s own override block).
ENGINE_CHOICES = ("auto", "direct", "gpu_direct", "amg", "mpi_schwarz")

from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D
from pytcad.device import Device1D, Models, NewtonOptions
from pytcad.device2d import Device2D
from pytcad.device3d import Device3D
from pytcad.linsolve import LinearSolveError, _HAVE_PYAMG, _HAVE_CUPY
from pytcad.transient import (
    StepWaveform, RampWaveform, PulseWaveform, ConstantWaveform,
    solve_transient as solve_transient_1d,
)
from pytcad.transient2d import solve_transient as solve_transient_2d

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
    # grid is (Nx,) | (Nx,Ny) | (Nx,Ny,Nz) here (built along `names` =
    # x,y,z order, matching the mask/box logic above) -- but Device2D/
    # Device3D consume the flat list as row-major (Ny,Nx) / (Nz,Ny,Nx),
    # the same convention as MeshSpec.shape() and build_doping()'s
    # reshape(shape). Reversing the axes before ravel() converts between
    # the two conventions without touching the mask-building logic above.
    grid = np.transpose(grid, axes=tuple(reversed(range(d))))
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

    # Band diagram (GUI Band Diagram Viewer): Device1D.band_diagram()
    # returns (Ec, Ev, EFn, EFp) [eV], already heterojunction- and
    # Fermi-Dirac-aware -- computed HERE, in the subprocess where the
    # real solved Device1D object lives, and stamped into the .npz so
    # the GUI process (which only ever sees a NpzResultStore, never a
    # live Device object -- see job_runner.py's module docstring for
    # why the solve runs out-of-process at all) can read it back
    # without reimplementing the formula. Device2D/Device3D have no
    # equivalent method yet (confirmed: grep turns up nothing), so
    # band__available is False for d in (2, 3) and the GUI must show an
    # honest "not available" state rather than fabricate one.
    if d == 1 and hasattr(device, "band_diagram"):
        Ec, Ev, EFn, EFp = device.band_diagram()
        out["band__Ec"] = np.asarray(Ec, dtype=float)
        out["band__Ev"] = np.asarray(Ev, dtype=float)
        out["band__EFn"] = np.asarray(EFn, dtype=float)
        out["band__EFp"] = np.asarray(EFp, dtype=float)
        out["band__available"] = np.array(True)
    else:
        out["band__available"] = np.array(False)

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
              sweep__current__<channel>, unit__sweep_current, sweep__meta,
              plus (3D only) sweep__snapshot__voltages and
              sweep__snapshot__field__<name>__<idx> for every CONVERGED
              point -- the per-point field data gui/services/viewer3d.py's
              sweep-playback dock (ResultStore.sweep_snapshots()) needs
              to animate a bias sweep. 1D/2D never write these: neither
              has a 3D viewer to play them back in, and a 2D sweep's
              field history was already exercised via the plain
              per-point series above long before Phase 4 added 3D
              playback, so there is nothing to retrofit there.

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

    # Phase 4 (retrofit): 3D snapshot fields for animation playback.
    # Only the bias-dependent scalars -- doping never changes across a
    # sweep, so re-storing it at every point would just bloat the
    # result file for no playback benefit; the static (non-sweep)
    # field__doping written elsewhere already covers it.
    snapshot_field_names = ("potential", "electron_density", "hole_density")
    snapshot_accessors = {
        "potential": lambda dev: dev.psi_V,
        "electron_density": lambda dev: dev.n_cm3,
        "hole_density": lambda dev: dev.p_cm3,
    }
    snapshot_voltages = []
    snapshot_fields = {name: [] for name in snapshot_field_names}

    currents = {name: [] for name in channels}
    converged_flags = []
    fields = None

    voltages = sw.voltages()
    for i, V in enumerate(voltages):
        print(f"PYTCAD_STAGE=sweep point {i + 1}/{len(voltages)}", flush=True)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                apply_bias(device, spec, opts, override={sw.contact: V})
                ok = not any("did not converge" in str(w.message)
                             for w in caught)
            except LinearSolveError:
                # linsolve.solve_linear() (opts.linsolve="gmres"/
                # "bicgstab") signals non-convergence by raising rather
                # than warning like the direct-solve path -- treat it as
                # exactly the same kind of single-point failure instead
                # of letting it abort the whole sweep and discard every
                # already-converged point.
                ok = False
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
            if d == 3:
                snapshot_voltages.append(float(V))
                for name in snapshot_field_names:
                    snapshot_fields[name].append(
                        np.asarray(snapshot_accessors[name](device),
                                  dtype=float))

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

    if d == 3 and snapshot_voltages:
        series["sweep__snapshot__voltages"] = np.array(
            json.dumps(snapshot_voltages))
        for name, arrs in snapshot_fields.items():
            for idx, arr in enumerate(arrs):
                series[f"sweep__snapshot__field__{name}__{idx}"] = arr

    return fields if fields is not None else fallback_fields, series


# ----------------------------------------------------------------------
#  Transient runs (M17 phase 3)
# ----------------------------------------------------------------------
def _waveform_from_dict(w):
    """Build a real pytcad.transient.Waveform from a WaveformSpec --
    the SAME classes transient.py/transient2d.py already use, never
    reimplemented here."""
    if w.kind == "step":
        return StepWaveform(w.v0, w.v1, t_step=w.t0)
    if w.kind == "ramp":
        return RampWaveform(w.v0, w.v1, w.t0, w.t1)
    if w.kind == "pulse":
        return PulseWaveform(w.v0, w.v1, w.t0, w.t1)
    if w.kind == "constant":
        return ConstantWaveform(w.v0)
    raise ValueError(f"unknown waveform kind '{w.kind}'")


def run_transient(device, spec, opts=None):
    """Execute spec.transient on an EQUILIBRIUM-SOLVED device.

    Every contact other than spec.transient.contact holds its merged DC
    bias (ContactSpec.V, overridden by DeviceSpec.bias) for the whole
    run -- established by ONE solve_bias call at t=0 (the waveform's
    own v0, so there is no discontinuity between that DC solve and the
    transient's initial state), then handed to pytcad.transient /
    transient2d's own already-gated solve_transient, unmodified.

    Returns (fields, series) shaped like run_sweep's:
      fields  extract_result() at the FINAL transient state;
      series  transient__times, transient__current__<contact name> (one
              per contact the solver reports current for -- BOTH named
              contacts at 1D, since a transient state has no single
              well-defined "device" current the way a steady state
              does; every registered ohmic contact at 2D),
              unit__transient_current, transient__meta.
    """
    opts = opts or NewtonOptions(verbose=True)
    tr = spec.transient
    contact_names = [c.name for c in spec.contacts]
    tr.validate(contact_names)
    d = spec.mesh.dimensionality
    if d == 3:
        raise ValueError(
            "transient runs are only implemented for 1D/2D devices "
            "(M17 phase 3 has no Device3D transient module)")

    # Seed every contact's DC bias, INCLUDING the stimulus contact at
    # its waveform's own v0 -- see docstring.
    bias = merge_bias(spec, override={tr.contact: tr.waveform.v0})
    if d == 1:
        if len(spec.contacts) != 2:
            raise ValueError("a 1D device needs exactly two contacts "
                             f"(got {len(spec.contacts)})")
        device.solve_bias([bias[spec.contacts[0].name],
                           bias[spec.contacts[1].name]], opts)
    else:
        device.solve_bias(bias, opts)

    wf = _waveform_from_dict(tr.waveform)
    if d == 1:
        # pytcad.transient.solve_transient requires BOTH "left"/"right"
        # keys explicitly (unlike transient2d, which defaults an
        # unmentioned contact to its current bc.V) -- so the non-
        # stimulus contact is passed as its already-established DC
        # bias value, which _as_waveform wraps in a ConstantWaveform.
        stimulus_idx = contact_names.index(tr.contact)
        other_idx = 1 - stimulus_idx
        waveforms_1d = {("left" if stimulus_idx == 0 else "right"): wf,
                        ("left" if other_idx == 0 else "right"):
                            bias[spec.contacts[other_idx].name]}
        result = solve_transient_1d(device, waveforms_1d, tr.t_end, tr.dt0,
                                    theta=tr.theta, opts=opts)
        currents = {spec.contacts[0].name: result.terminal_current["left"],
                   spec.contacts[1].name: result.terminal_current["right"]}
    else:
        result = solve_transient_2d(device, {tr.contact: wf}, tr.t_end,
                                    tr.dt0, theta=tr.theta, opts=opts)
        currents = dict(result.terminal_current)

    fields = extract_result(device, spec, solved_bias=True)
    series = {
        "transient__times": np.asarray(result.times, dtype=float),
        "unit__transient_current": np.array(
            {1: "A/cm^2", 2: "A/cm", 3: "A"}[d]),
        "transient__meta": np.array(json.dumps({
            "contact": tr.contact, "waveform": tr.waveform.to_dict(),
            "t_end": tr.t_end, "dt0": tr.dt0, "theta": tr.theta,
            "dimensionality": d})),
    }
    for name, vals in currents.items():
        series[f"transient__current__{name}"] = np.asarray(vals, dtype=float)
    return fields, series



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
def _solve_all(device, spec, opts, linsolve_bias=None):
    """Equilibrium + (optional) bias or sweep, emitting the same
    PYTCAD_STAGE markers JobRunner has always streamed.  Returns the
    raw result dict in the v1 key shape.

    linsolve_bias: if given, overrides opts.linsolve for every solve
    AFTER equilibrium (bias/sweep/transient). Equilibrium and bias are
    different linear systems with different measured optimal solvers
    (see run_job()'s node-count gating below) -- one NewtonOptions
    object can only hold one opts.linsolve value at a time, so this
    mutates it in place between phases rather than threading a second
    NewtonOptions through every solve_bias/run_sweep/run_transient call
    site. NewtonOptions is a plain (non-frozen) dataclass, so this is
    the same kind of in-place field update opts.verbose already is
    everywhere else in this file -- not a new mutability contract.
    """
    print("PYTCAD_STAGE=equilibrium", flush=True)
    device.solve_equilibrium(opts)
    if linsolve_bias is not None:
        opts.linsolve = linsolve_bias

    if spec.transient is not None:
        print("PYTCAD_STAGE=transient", flush=True)
        fields, series = run_transient(device, spec, opts)
        result = fields
        result.update(series)
    elif spec.sweep is not None:
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


def _pick_mpi_split_axis(doping, spec):
    """Return (axis_name, array_axis) for the safest axis to Schwarz-
    split a 3D job along, or (None, None) if none qualifies.

    Generalizes the x-only check this file used to hard-code: a middle
    rank sitting on a real doping gradient converges an order of
    magnitude slower per Schwarz sweep than a rank whose slab is
    doping-invariant (confirmed directly on pn_junction_3d -- see
    mpi_schwarz_runner.py's module docstring). That risk is per-AXIS,
    not specific to x: mosfet_3d/finfet_3d localize their S/D/gate
    contacts along x (unsafe there) but are typically extruded
    uniformly along z (the device width), so checking every axis lets
    those devices take the MPI path along z instead of being refused
    outright the way an x-only check would.

    A SECOND, DISTINCT hazard the doping check alone does NOT catch,
    confirmed directly (not assumed) on finfet_3d: a GateBC's Robin/
    oxide-coupling term runs along its own `normal_axis` regardless of
    whether doping varies there at all -- finfet_3d's side gates have
    normal_axis="z", which passed the doping-uniformity test (the
    device IS doping-uniform along z) but produced a 1.4e-3 relative
    field error against the single-process reference when split along
    z anyway (vs. ~1e-17 for bjt_3d/pn_junction_3d's gate-free
    geometries) -- a genuine field-curvature mechanism from geometric/
    electrostatic confinement, not a doping gradient, that a doping-
    only check has no way to see. So any axis matching a registered
    gate's normal_axis is excluded as a candidate outright, regardless
    of its doping-variation score.

    `doping` is (Nz, Ny, Nx) -- array axis 2 is x, 1 is y, 0 is z.
    Candidates need at least 2 nodes per rank to split at all; among
    the axes that pass both the <=1%-of-range variation test and the
    gate-normal-axis exclusion, the one with the most nodes is chosen
    (best parallelization headroom).
    """
    gate_axes = {c.normal_axis for c in spec.contacts if c.kind == "gate"}
    total_range = float(np.abs(doping).max())
    if total_range <= 0 and not gate_axes:
        return "x", 2      # perfectly uniform, no gates at all: any
                           # axis is safe, x is the most-tested path
    candidates = []
    for axis_name, array_axis in (("x", 2), ("y", 1), ("z", 0)):
        if axis_name in gate_axes:
            continue
        n = doping.shape[array_axis]
        if n < 2 * MPI_SCHWARZ_RANKS:
            continue
        variation = float(np.max(doping.max(axis=array_axis)
                                 - doping.min(axis=array_axis)))
        if total_range <= 0 or variation < 0.01 * total_range:
            candidates.append((n, axis_name, array_axis))
    if not candidates:
        return None, None
    candidates.sort(reverse=True)
    _, axis_name, array_axis = candidates[0]
    return axis_name, array_axis


def _solve_via_mpi_schwarz(job_path, split_axis):
    """Run gui/services/mpi_schwarz_runner.py under mpirun and return
    the SAME result-dict shape _solve_all() returns, so run_job()'s
    surrounding stamping/atomic-write logic below needs no branching
    of its own -- MPI Schwarz is a drop-in alternative "engine" for
    producing that dict, not a separate output format.

    Scope: equilibrium, a single bias point, or a voltage sweep (Phase
    1a) -- transient is NOT, since Device3D has no transient module at
    all; the caller only reaches here when spec.transient is None
    (mpi_schwarz_runner.py itself also refuses transient, as a second
    check). Relays the worker's rank-0 stdout through this process's
    own stdout AS IT ARRIVES, so JobRunner's existing PYTCAD_STAGE
    regex parsing (gui/services/job_runner.py) sees the same markers
    live, exactly as it would from the plain single-process path --
    JobRunner and AppController stay completely unaware MPI is
    involved at all.

    split_axis ("x"/"y"/"z") is passed as a positional CLI arg -- the
    one piece of the gating decision above that the worker cannot
    re-derive on its own (every rank would need the SAME choice, and
    _pick_mpi_split_axis's tie-breaking by node count must only run
    once, not independently per rank).
    """
    tmp_out = job_path + ".schwarz_result.npz"
    cmd = ["mpirun"]
    if _mpirun_is_openmpi():
        cmd.append("--allow-run-as-root")
    cmd += ["-np", str(MPI_SCHWARZ_RANKS),
           sys.executable, "-m", "gui.services.mpi_schwarz_runner",
           job_path, tmp_out, split_axis]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1,
                            cwd=os.path.dirname(os.path.dirname(
                                os.path.dirname(os.path.abspath(__file__)))))
    lines = []
    for line in proc.stdout:
        lines.append(line)
        # Only the worker's own PYTCAD_STAGE markers need relaying for
        # JobRunner's progress display; its SCHWARZ_RESULT_PATH marker
        # is this function's own internal handshake, not part of the
        # documented solver_runner.py stdout contract, so it is not
        # relayed further.
        if line.startswith("PYTCAD_STAGE="):
            print(line, end="", flush=True)
    proc.wait()
    if proc.returncode != 0 or not os.path.exists(tmp_out):
        raise RuntimeError(
            "MPI Schwarz solve failed (mpirun exit "
            f"{proc.returncode}):\n" + "".join(lines[-40:]))
    try:
        with np.load(tmp_out, allow_pickle=False) as npz:
            result = {k: npz[k] for k in npz.files}
    finally:
        os.remove(tmp_out)
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
    if spec.transient is not None:
        spec.transient.validate([c.name for c in spec.contacts])

    # build_doping() alone is needed up front (the MPI-Schwarz gate
    # below reads the actual doping array); build_mesh/build_device/
    # register_contacts are deferred past that gate -- when the MPI
    # path is taken, mpi_schwarz_runner.py rebuilds an equivalent
    # device from scratch per rank inside its own subprocess, so
    # building one here first would be pure wasted work that scales
    # with mesh size, on exactly the jobs this feature targets.
    doping, ntotal = build_doping(spec.doping, spec.mesh.shape())

    # verbose=True is the v0.1 progress channel: JobRunner streams this
    # process's stdout into the console panel.  Cosmetic only -- results
    # are read from the .npz, never parsed from this text.
    #
    # 3D-only, size-gated iterative equilibrium solve: confirmed
    # directly (not assumed) that bicgstab+pyamg's algebraic-multigrid
    # preconditioner cuts the equilibrium Newton loop's wall time by
    # 8x-44x on genuinely large 3D meshes (bjt_3d 43.4s->1.0s,
    # pn_junction_3d 31.1s->0.8s, finfet_3d 33.1s->4.0s -- all agreeing
    # with the direct solve to a relative error of ~1e-17), because
    # direct sparse LU's fill-in on a 3D structured grid is the actual
    # bottleneck there. But the SAME setting made a smaller 3D mesh
    # slower, not faster (mosfet_3d's ~15.8k-node equilibrium: 2.1s ->
    # 21.4s) -- AMG hierarchy setup has real per-Newton-iteration cost
    # that only pays for itself once direct factorization is already
    # the expensive part. 20,000 nodes sits between the two measured
    # regimes (mosfet_3d below, bjt_3d/finfet_3d/pn_junction_3d above),
    # so it is used as the switch rather than turning this on
    # unconditionally. Also gated on pyamg actually being installed:
    # bicgstab with only the weaker ILU fallback preconditioner (no
    # pyamg) does NOT reliably converge across a full 3D equilibrium
    # trajectory -- confirmed directly, it made bjt_3d's equilibrium
    # solve slower (79-83s) than plain direct (41s) by repeatedly
    # trying and failing before device3d.py's own fallback kicked in.
    # solve_bias's block-Jacobi-preconditioned iterative path (gmres/
    # bicgstab) is left at "direct": measured net-neutral-to-slightly-
    # slower on every example tried (the coupled psi/n/p Jacobian
    # doesn't converge reliably under block-Jacobi, Schur, or AMG
    # preconditioning -- confirmed directly, not assumed), so there is
    # no measured case for using an ITERATIVE bias solver.
    #
    # A DIRECT solve run on the GPU (cuSOLVER via CuPy) is a different
    # story precisely because it sidesteps that convergence question
    # entirely -- confirmed directly on bjt_3d's real 121,824-unknown
    # bias Jacobian: 2.8x faster than scipy spsolve end to end (a full
    # multi-iteration solve_bias trajectory, not one sample matrix),
    # agreeing with the CPU result to a relative error of ~1e-17. But
    # GPU transfer/kernel-launch overhead is a real per-call cost that
    # a small matrix can't amortize -- measured 0.4x-0.7x (SLOWER) on
    # resistor_3d/moscap_3d/jfet_3d's few-thousand-unknown Jacobians,
    # ~1.1x (break-even) at mosfet_3d's 47,304, and a clear win from
    # pn_junction_3d's 99,360 up. The same 20,000-NODE threshold
    # already used for equilibrium happens to land in the right place
    # for this too (mosfet_3d below it, pn_junction_3d/bjt_3d/finfet_3d
    # above), so it is reused here rather than inventing a second
    # unvalidated constant. Also gated on cupy actually being
    # installed, same reasoning as pyamg above.
    node_count = int(np.prod(spec.mesh.shape()))
    is_large_3d = spec.mesh.dimensionality == 3 and node_count > 20_000
    use_amg_equilibrium = is_large_3d and _HAVE_PYAMG
    use_gpu_bias = is_large_3d and _HAVE_CUPY
    opts = NewtonOptions(verbose=True,
                        linsolve="bicgstab" if use_amg_equilibrium else "direct")
    # Always explicit, never None: _solve_all only overwrites
    # opts.linsolve when linsolve_bias is not None, so a machine with
    # pyamg but no cupy (equilibrium fast, bias not) would otherwise
    # leave opts.linsolve at "bicgstab" for the bias/sweep phase too --
    # exactly the iterative method this file's own comments above
    # document as NOT reliably convergent on the coupled Jacobian.
    # Falling back to direct every iteration is still correct (the
    # try/except in solve_bias catches it) but wastes a failed
    # bicgstab attempt each time for no reason once equilibrium is done.
    linsolve_bias = "gpu_direct" if use_gpu_bias else "direct"

    # 4-rank MPI Schwarz domain decomposition (gui/services/
    # mpi_schwarz_runner.py): confirmed directly on bjt_3d (a genuinely
    # different geometry+contact layout than every synthetic test this
    # file's other size-gated paths were validated on) -- 4 ranks, 2
    # Schwarz sweeps to convergence, 31.09s vs. this same job's 158.6s
    # single-process baseline (5.1x), exact to a relative L2 error of
    # 1.56e-17 against the plain single-process reference. Reuses the
    # SAME 20,000-node/3D-only gate as the equilibrium/bias paths
    # above, but is mutually exclusive with them at the job level (it
    # replaces the whole equilibrium+bias solve, not just one linear
    # solve inside it). A voltage sweep is ALSO routed here as of
    # Phase 1a (gui/services/mpi_schwarz_runner.py's _run_sweep --
    # warm-started per rank exactly like the single-process run_sweep()
    # is, just with an extra per-point Schwarz reconvergence in between
    # points). Transient still is NOT: Device3D has no transient module
    # at all (run_transient() raises outright for d==3), so there is
    # nothing for this path to parallelize there regardless of mesh
    # size. Gated on mpi4py AND an mpirun binary both actually being present,
    # same "optional dep changes nothing about correctness, only which
    # engine handles it" contract as _HAVE_PYAMG/_HAVE_CUPY above.
    #
    # CRITICAL, confirmed directly (not assumed): splitting along an
    # axis a device's doping actually VARIES along is a REGRESSION, not
    # a speedup -- tried splitting pn_junction_3d along x (the junction
    # sits inside the split, unlike bjt_3d's x-independent layer stack)
    # and a middle rank's per-sweep bias solve took 39-45s (vs. bjt_3d's
    # ~5s), still hadn't converged after the point bjt_3d always
    # finishes by, and was killed rather than let run to an unknown,
    # possibly multi-minute completion -- far worse than that same
    # job's already-working ~48s GPU/AMG single-process result. So
    # _pick_mpi_split_axis() (above) refuses any axis whose doping
    # varies by more than 1% of the array's total range, checked
    # directly on the actual array (not device-name-listed) --
    # bjt_3d's stacked layers vary only along y so x (or z) passes;
    # a lateral junction/channel profile fails on every axis it
    # actually varies along and correctly falls back to the plain
    # (already GPU/AMG-accelerated) path instead. Generalized past a
    # single hard-coded x check so a device localized along x (like
    # mosfet_3d/finfet_3d's S/D/gate) but uniform along z can still
    # take the MPI path split along z instead of being refused
    # outright -- see _pick_mpi_split_axis()'s own docstring.
    split_axis, split_array_axis = ((None, None) if not is_large_3d else
                                    _pick_mpi_split_axis(doping, spec))
    use_mpi_schwarz = (is_large_3d and _HAVE_MPI and split_axis is not None
                       and spec.transient is None)

    # v0.6 Phase 2d: spec.engine == "auto" (the default -- old job files
    # simply lack the key, see DeviceSpec.from_dict) leaves every choice
    # above exactly as the heuristic computed it. Any other value FORCES
    # that engine, discarding the heuristic's choice entirely and
    # refusing loudly for a dependency/structural mismatch instead of
    # silently falling back -- same "graceful refusal with a precise
    # message" contract every other optional-dependency gate in this
    # file already uses (_HAVE_PYAMG/_HAVE_CUPY/_HAVE_MPI above).
    engine = getattr(spec, "engine", "auto") or "auto"
    if engine not in ENGINE_CHOICES:
        raise ValueError(
            f"unknown engine {engine!r}; expected one of {ENGINE_CHOICES}")
    if engine != "auto":
        opts.linsolve = "direct"
        linsolve_bias = "direct"
        use_mpi_schwarz = False
        if engine == "gpu_direct":
            if not _HAVE_CUPY:
                raise ValueError(
                    "GPU direct solve requested but cupy is not installed "
                    "in this environment.")
            linsolve_bias = "gpu_direct"
        elif engine == "amg":
            if not _HAVE_PYAMG:
                raise ValueError(
                    "AMG (bicgstab) solve requested but pyamg is not "
                    "installed in this environment.")
            # AMG only replaces the EQUILIBRIUM linear solve, same as
            # the auto heuristic's own use_amg_equilibrium -- see
            # run_job()'s module-level comment above for why the bias/
            # sweep phase is left on "direct" (measured net-neutral-to-
            # slower under iterative preconditioning on the coupled
            # psi/n/p Jacobian, not a gap in this override).
            opts.linsolve = "bicgstab"
        elif engine == "mpi_schwarz":
            if spec.mesh.dimensionality != 3:
                raise ValueError(
                    "MPI Schwarz solve requires a 3D device; this job is "
                    f"{spec.mesh.dimensionality}D.")
            if spec.transient is not None:
                raise ValueError(
                    "MPI Schwarz solve does not support transient runs.")
            if not _HAVE_MPI:
                raise ValueError(
                    "MPI Schwarz solve requested but mpi4py/mpirun are not "
                    "available in this environment.")
            forced_axis, forced_array_axis = _pick_mpi_split_axis(doping, spec)
            if forced_axis is None:
                raise ValueError(
                    "MPI Schwarz solve requested but no mesh axis is safe "
                    "to split along for this device's doping profile/gate "
                    "layout (see _pick_mpi_split_axis's docstring).")
            split_axis, split_array_axis = forced_axis, forced_array_axis
            use_mpi_schwarz = True
        # engine == "direct" needs no further action: the reset above
        # (opts.linsolve/linsolve_bias = "direct", use_mpi_schwarz =
        # False) already is the plain, always-safe baseline.

    if not use_mpi_schwarz:
        mesh_obj = build_mesh(spec.mesh)
        device = build_device(spec, mesh_obj, doping, ntotal)
        register_contacts(device, spec)

    cap = _start_capture()
    try:
        if use_mpi_schwarz:
            result = _solve_via_mpi_schwarz(job_path, split_axis)
        else:
            result = _solve_all(device, spec, opts, linsolve_bias=linsolve_bias)
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

    # v0.6 Phase 2e: round-trip the region_materials wire field into the
    # result itself. build_material_grid() above already CONSUMES this
    # (rasterizing it into per-node materials for the physics solve),
    # but until now nothing carried it back OUT again -- the 3D viewer's
    # exploded-view feature (gui/services/viewer3d.py's
    # _build_exploded_view) reads exactly this shape back via
    # store.region_materials(), which every real result silently
    # returned None for (no store implemented it at all, see
    # result_store.py's ResultStore.region_materials), so exploded view
    # could never do anything for ANY device, heterojunction included.
    # Only stamped when non-empty, same "absent means N/A" convention
    # sweep__meta/transient__meta below already use.
    if spec.region_materials:
        result["region_materials__meta"] = np.array(
            json.dumps(spec.region_materials))
    # v0.6 Phase 2f: same round-trip, for a device with named
    # structural regions but no material difference for
    # region_materials above to carry (a homojunction MOSFET/BJT/JFET
    # built via the Structure workbench, or one of the 3D EXAMPLES
    # functions that now stamps this directly) -- see
    # DeviceSpec.structure_regions's own docstring.
    if spec.structure_regions:
        result["structure_regions__meta"] = np.array(
            json.dumps(spec.structure_regions))

    transient_meta = None
    if spec.transient is not None:
        transient_meta = json.loads(str(result["transient__meta"]))
    sweep_meta = None
    if spec.sweep is not None:
        sweep_meta = json.loads(str(result["sweep__meta"]))
        # Phase 3b: the per-stage continuation-record table needs a
        # real producer, not just a consumer -- run_sweep() already
        # computes exactly this (voltage + converged) per warm-started
        # point, so stamp it here rather than inventing separate
        # tracking. No per-stage node count: this pipeline's sweep
        # reuses one fixed mesh across every point, so there is no real
        # per-point value to report (the QML table already renders
        # that column blank when absent).
        voltages = np.asarray(result["sweep__voltage"], dtype=float)
        converged = np.asarray(result["sweep__converged"], dtype=bool)
        result["continuation__records"] = np.array(json.dumps([
            {"index": i, "parameter": float(v), "accepted": bool(c)}
            for i, (v, c) in enumerate(zip(voltages, converged))]))
    # `opts` reflects the equilibrium/bias linsolve CHOICE computed
    # above, but the MPI-Schwarz path never uses that opts object at
    # all -- mpi_schwarz_runner.py builds its own NewtonOptions(
    # linsolve="direct") per rank internally -- so stamping asdict(opts)
    # unconditionally would misreport which solver engine actually
    # produced this result whenever the MPI path was taken.
    numerics = asdict(opts)
    if use_mpi_schwarz:
        numerics["linsolve"] = "direct"
        numerics["engine"] = "mpi_schwarz"
        numerics["mpi_split_axis"] = split_axis
    result["record__meta"] = np.array(json.dumps({
        "schema_version": SOLVER_RESULT_SCHEMA_VERSION,
        "backend": "pytcad",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dimensionality": spec.mesh.dimensionality,
        "material": spec.material,
        "T": spec.T,
        "models": spec.models,
        "numerics": numerics,
        "sweep": sweep_meta,
        "transient": transient_meta,
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
        # v0.6 Phase 2c: JobRunner always spawns THIS module regardless
        # of which backend a job wants (AppController is the only
        # caller today, and it always used this module even before
        # DeviceSpec had a "backend" field at all) -- so backend
        # selection is dispatched here, from the job itself, rather
        # than by changing which module gets spawned. "pytcad" keeps
        # calling run_job() directly (bit-identical to pre-2c behavior,
        # not routed through get_backend("pytcad").run() even though
        # that is ALSO just run_job() under the hood -- no reason to
        # add a layer of indirection to the path every prior job used).
        backend_id = DeviceSpec.from_json(argv[1]).backend
        if backend_id == "pytcad":
            run_job(argv[1], argv[2])
        else:
            from workbench.solvers.base import SolveRequest, get_backend
            get_backend(backend_id).run(
                SolveRequest(job_json_path=argv[1], out_npz_path=argv[2]))
            print(f"RESULT_PATH={argv[2]}", flush=True)
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
