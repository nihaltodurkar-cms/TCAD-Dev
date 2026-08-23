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
import json
import os
import sys
import traceback

import numpy as np

from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D
from pytcad.device import Device1D, Models, NewtonOptions
from pytcad.device2d import Device2D
from pytcad.device3d import Device3D

from .device_spec import DeviceSpec


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


def build_device(spec, mesh_obj, doping, ntotal):
    models = Models(**spec.models)
    d = spec.mesh.dimensionality
    cls = {1: Device1D, 2: Device2D, 3: Device3D}[d]
    return cls(mesh_obj, doping, Ntotal=ntotal, T=spec.T, models=models)


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


def apply_bias(device, spec, opts):
    """Device1D takes a positional [V_left, V_right]; 2D/3D take a
    {name: V} dict.  Another pytcad asymmetry absorbed here."""
    if spec.mesh.dimensionality == 1:
        if len(spec.contacts) != 2:
            raise ValueError("a 1D device needs exactly two contacts "
                             f"(got {len(spec.contacts)})")
        device.solve_bias([spec.contacts[0].V if spec.bias is None
                           else spec.bias.get(spec.contacts[0].name, spec.contacts[0].V),
                           spec.contacts[1].V if spec.bias is None
                           else spec.bias.get(spec.contacts[1].name, spec.contacts[1].V)],
                          opts)
    else:
        device.solve_bias(spec.bias, opts)


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
#  Entry point
# ----------------------------------------------------------------------
def run_job(job_path, out_path):
    spec = DeviceSpec.from_json(job_path)
    mesh_obj = build_mesh(spec.mesh)
    doping, ntotal = build_doping(spec.doping, spec.mesh.shape())
    device = build_device(spec, mesh_obj, doping, ntotal)
    register_contacts(device, spec)

    # verbose=True is the v0.1 progress channel: JobRunner streams this
    # process's stdout into the console panel.  Cosmetic only -- results
    # are read from the .npz, never parsed from this text.
    opts = NewtonOptions(verbose=True)

    print("PYTCAD_STAGE=equilibrium", flush=True)
    device.solve_equilibrium(opts)

    solved_bias = spec.bias is not None
    if solved_bias:
        print("PYTCAD_STAGE=bias", flush=True)
        apply_bias(device, spec, opts)

    print("PYTCAD_STAGE=extract", flush=True)
    result = extract_result(device, spec, solved_bias)

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
