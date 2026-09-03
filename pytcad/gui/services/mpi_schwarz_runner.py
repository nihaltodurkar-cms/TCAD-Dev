"""MPI Schwarz domain-decomposed 3D solve -- one worker per rank.

    mpirun -np <ranks> python -m gui.services.mpi_schwarz_runner \
        <job.json> <tmp_result.npz> <split_axis: x|y|z>

Not launched directly by JobRunner: gui/services/solver_runner.py's
run_job() spawns this (via subprocess, relaying rank 0's stdout through
its own so JobRunner's existing PYTCAD_STAGE parsing keeps working
unchanged) when a job is 3D, above the size threshold, and mpi4py +
mpirun are both available -- see run_job()'s _solve_via_mpi_schwarz().
`split_axis` is chosen once by run_job()'s _pick_mpi_split_axis() and
passed in rather than re-derived per rank (every rank must agree).

SCOPE: equilibrium, a single bias point, AND (as of the Phase-1
generalization below) a voltage sweep -- transient still falls back to
the normal single-process path (Device3D itself has no transient
module at all, per run_transient()'s own guard, so there is nothing
this file could parallelize there).

ARCHITECTURE -- overlapping additive Schwarz, not a distributed matrix:
splits the mesh into `size` overlapping slabs along ONE axis (x, y, or
z -- generalized from an earlier x-only prototype, see below), each
rank solves its own slab with the ordinary (fast, proven) direct
solve, ranks exchange one interior plane of psi/n/p with their
neighbor after each local solve, and the outer loop repeats until the
CORE region stops changing. Confirmed directly (this session's
benchmark record) on bjt_3d split along x: 2 sweeps to convergence,
exact to ~1.6e-17 relative error against the single-process reference,
and faster than either a plain or a GPU-accelerated single-process
direct solve at 4 ranks. This exchange/convergence loop is factored
into _schwarz_loop() below so the sweep path reuses the EXACT same
tested code, not a hand-copied second implementation.

CONFIRMED, NOT JUST SUSPECTED: splitting along a device's OWN doping
gradient is a genuine regression, not just "unverified." Tried on
pn_junction_3d split along x (the junction sits inside the split,
unlike bjt_3d's x-independent layer stack): a middle rank's per-sweep
bias solve took 39-45s (vs. bjt_3d's ~5s) and the run was killed
before converging rather than let it run to an unknown, possibly
multi-minute completion. run_job()'s _pick_mpi_split_axis() refuses to
route a job here at all unless it finds SOME axis whose doping varies
by less than 1% of its own range (checked on the real array, not a
device-name list) -- this module has no such guard of its own, since
it trusts the caller to have already made that call and to have
picked the axis it names in argv[3].

A CORRECTNESS DETAIL THIS MODULE EXISTS TO GET RIGHT: Device3D derives
its entire dimensionless scaling (Ns, LD, J0, and even the mesh
coordinates -- xs = mesh.x / LD) from max(|doping|) of whatever array
it's built with. Two ranks seeing different SLICES of a device whose
doping varies along the split axis (every example except bjt_3d/
moscap_3d/jfet_3d/resistor_3d along x) would derive DIFFERENT LD/Ns
and silently disagree on units -- confirmed as a real risk before any
of this was wired up, not assumed. Every local device here is built
with Ns_override pinned to the FULL device's own max(|doping|),
computed once from the complete (unsplit) array.

SWEEP SUPPORT (Phase 1a): each sweep point re-runs the SAME Schwarz
outer loop as a single bias point, warm-started from the PREVIOUS
point's converged per-rank state -- Device3D.solve_bias already warm-
starts from self.psi/n/p when they are not None (device3d.py line
~910), so this is the identical warm-started-ramp idea
gui/services/solver_runner.py's own run_sweep() already uses for the
single-process path, just applied per-rank instead of to one device.
Unlike the single-bias-point path above, a sweep point's local device
skips solve_equilibrium() entirely after the first point -- there is
no need to re-derive the bulk equilibrium guess when the previous
point's converged bias state is a far better starting point, and
solve_bias's Newton loop converges to the correct answer regardless of
initial guess quality (the guess only affects HOW MANY iterations it
takes, never correctness). Terminal currents and 3D snapshot fields
(gui/services/viewer3d.py's sweep-playback dock) are computed exactly
like run_sweep()'s single-process path: only for CONVERGED points, via
one reassembled global Device3D per point (the SAME reassembly this
module already did once for a single bias point, just repeated -- no
new current-summation logic to audit, per this module's original
design note).
"""
import sys
import warnings

import numpy as np
from mpi4py import MPI

from pytcad.device3d import Device3D, DirichletBC, GateBC, PinnedBC
from pytcad.mesh3d import Mesh3D
from pytcad.device import NewtonOptions
from pytcad.linsolve import LinearSolveError

from .device_spec import DeviceSpec
from .solver_runner import register_contacts, extract_result, merge_bias

OVERLAP = 3
MAX_SCHWARZ = 20
SCHWARZ_TOL = 1e-4

# doping_full/psi/n/p arrays are always (Nz, Ny, Nx) -- array axis 2 is
# x, 1 is y, 0 is z, matching MeshSpec.shape()'s convention everywhere
# else in this pipeline. ContactSpec.nodes keys the same three axes as
# "i" (x), "j" (y), "k" (z) (see register_contacts/device_spec.py).
AXIS_TO_ARRAY = {"x": 2, "y": 1, "z": 0}
AXIS_TO_KEY = {"x": "i", "y": "j", "z": "k"}
ARRAY_TO_AXIS = {2: "x", 1: "y", 0: "z"}
ARRAY_TO_KEY = {2: "i", 1: "j", 0: "k"}


def _split_axis_range(n, size, overlap):
    """Overlapping [lo, hi] slabs (inclusive) covering [0, n) across
    `size` ranks, plus each rank's non-overlapping [core_lo, core_hi]."""
    base = np.linspace(0, n, size + 1).astype(int)
    core_lo, core_hi = base[:-1], base[1:] - 1
    lo = np.maximum(core_lo - overlap, 0)
    hi = np.minimum(core_hi + overlap, n - 1)
    return lo, hi, core_lo, core_hi


def _filter_and_translate(nodes, key, lo, hi):
    """Global {'i','j','k'} node dict -> the subset whose `key` index
    lies in [lo,hi], that index re-based to this slab's own local
    indexing. None if empty."""
    gi = np.asarray(nodes["i"], dtype=int)
    gj = np.asarray(nodes["j"], dtype=int)
    gk = np.asarray(nodes.get("k", np.zeros_like(gi)), dtype=int)
    g = {"i": gi, "j": gj, "k": gk}
    mask = (g[key] >= lo) & (g[key] <= hi)
    if not mask.any():
        return None
    out = {"i": gi[mask].tolist(), "j": gj[mask].tolist(), "k": gk[mask].tolist()}
    out[key] = (g[key][mask] - lo).tolist()
    return out


def _take(arr, array_axis, index):
    """arr sliced (not reduced-and-copied via fancy indexing) at
    `index` along `array_axis` -- a plain view, same as arr[:, :, index]
    would be for array_axis=2, generalized to any axis."""
    idx = [slice(None)] * arr.ndim
    idx[array_axis] = index
    return arr[tuple(idx)]


def _face_nodes(array_axis, local_index, shape):
    """Full-grid {'i','j','k'} arrays for the face perpendicular to
    `array_axis` at local index `local_index` of an array shaped
    `shape` -- ravel-ordered (C order, indexing='ij') to match
    `_take(arr, array_axis, local_index).ravel()` exactly, so
    PinnedBC's flat psi0/n0/p0 line up 1:1 with these flat i/j/k.
    """
    remaining = [a for a in (0, 1, 2) if a != array_axis]
    sizes = [shape[a] for a in remaining]
    grids = np.meshgrid(*[np.arange(s) for s in sizes], indexing="ij")
    out = {}
    for grid, a in zip(grids, remaining):
        out[ARRAY_TO_KEY[a]] = grid.ravel()
    out[ARRAY_TO_KEY[array_axis]] = np.full(grids[0].size, local_index)
    return out


def _build_local_device(spec, doping_full, ntotal_full, x, y, z,
                        array_axis, key, lo, hi, Ns_global, pin):
    split_name = ARRAY_TO_AXIS[array_axis]
    mesh_axes = {"x": x, "y": y, "z": z}
    mesh_axes[split_name] = mesh_axes[split_name][lo:hi + 1]
    mesh = Mesh3D(mesh_axes["x"], mesh_axes["y"], mesh_axes["z"])

    local_doping = _take(doping_full, array_axis, slice(lo, hi + 1))
    local_ntotal = (None if ntotal_full is None
                    else _take(ntotal_full, array_axis, slice(lo, hi + 1)))
    dev = Device3D(mesh, local_doping, Ntotal=local_ntotal, T=spec.T,
                   Ns_override=Ns_global)

    local_n = hi - lo + 1
    # Every contact this slab's split-axis range touches at all,
    # translated to local indices -- NOT restricted to this rank's
    # "core" ownership: a real physical contact must be applied
    # everywhere it physically exists, including in a neighbor's
    # overlap region (redundant but harmless there, since it's the
    # same fixed value); only terminal-CURRENT bookkeeping needs single
    # ownership, and that is handled later by recomputing it once on
    # the reassembled global device, not by any per-rank accounting
    # here.
    for c in spec.contacts:
        local_nodes = _filter_and_translate(c.nodes, key, lo, hi)
        if local_nodes is None:
            continue
        if c.kind == "ohmic":
            dev.add_contact(c.name, V=c.V, **local_nodes)
        elif c.kind == "gate":
            dev.add_gate(c.name, tox_cm=c.tox_cm, Vfb=c.Vfb, Vg=c.V,
                         normal_axis=c.normal_axis, **local_nodes)

    if "left" in pin:
        face = _face_nodes(array_axis, 0, local_doping.shape)
        psi0, n0, p0 = pin["left"]
        dev.bcs["_schwarz_left"] = PinnedBC(psi0=psi0, n0=n0, p0=p0, **face)
    if "right" in pin:
        face = _face_nodes(array_axis, local_n - 1, local_doping.shape)
        psi0, n0, p0 = pin["right"]
        dev.bcs["_schwarz_right"] = PinnedBC(psi0=psi0, n0=n0, p0=p0, **face)
    return dev


def _schwarz_loop(comm, rank, size, array_axis, lo, hi, core_lo, core_hi,
                  lo_all, hi_all, solve_fn, max_iters=MAX_SCHWARZ,
                  tol=SCHWARZ_TOL):
    """Run the overlapping-Schwarz outer loop.

    `solve_fn(pin)` builds and solves ONE rank's local device for the
    given interface pin values -- what it does internally (a pure
    equilibrium solve, an equilibrium+bias solve, or a warm-started
    bias-only solve for a sweep point) is opaque to this function, so
    the single-bias-point path and the sweep path below share this
    EXACT tested exchange/convergence code instead of two hand-copied
    implementations that could silently drift apart.

    Returns (dev, converged): `dev` is solve_fn's own return from the
    LAST iteration; `converged` is whether the CORE region's psi
    stopped changing within max_iters (Schwarz convergence) -- this
    says nothing about the inner Newton solve's own convergence, which
    solve_fn must track itself if the caller cares (see main()'s
    per-sweep-point Newton-convergence tracking below).
    """
    pin = {}
    prev_core = None
    dev = None
    converged = False
    for _ in range(max_iters):
        dev = solve_fn(pin)

        # Sample at the GLOBAL position the receiving neighbor will
        # actually pin, not an arbitrary OVERLAP-offset from my own
        # edge -- those are different physical locations whenever
        # OVERLAP != 1, which they were: sending my own core-edge value
        # (local index OVERLAP) and having the neighbor pin ITS outer
        # domain edge with it silently mismatched by OVERLAP-1 planes
        # (confirmed directly: with OVERLAP=3 that's a real 2-plane
        # spatial offset). lo_all/hi_all are already the same on every
        # rank (computed identically from the same job.json), so each
        # rank can compute exactly where ITS neighbor's edge sits in
        # GLOBAL coordinates and sample its own local array there.
        #
        # Raveled to match _face_nodes()'s ravel ordering exactly --
        # PinnedBC.psi0/n0/p0 must be flat arrays aligned 1:1 with its
        # (i,j,k) node lists, the same contract every other BC's
        # node/value arrays already follow.
        send_left = None
        if rank > 0:
            li = int(hi_all[rank - 1]) - lo
            send_left = (_take(dev.psi, array_axis, li).ravel().copy(),
                        _take(dev.n, array_axis, li).ravel().copy(),
                        _take(dev.p, array_axis, li).ravel().copy())
        send_right = None
        if rank < size - 1:
            li = int(lo_all[rank + 1]) - lo
            send_right = (_take(dev.psi, array_axis, li).ravel().copy(),
                         _take(dev.n, array_axis, li).ravel().copy(),
                         _take(dev.p, array_axis, li).ravel().copy())

        reqs = []
        if rank > 0:
            reqs.append(comm.isend(send_left, dest=rank - 1, tag=10 + rank))
        if rank < size - 1:
            reqs.append(comm.isend(send_right, dest=rank + 1, tag=20 + rank))

        new_pin = {}
        if rank > 0:
            new_pin["left"] = comm.recv(source=rank - 1, tag=20 + (rank - 1))
        if rank < size - 1:
            new_pin["right"] = comm.recv(source=rank + 1, tag=10 + (rank + 1))
        for r in reqs:
            r.wait()

        core_psi = _take(dev.psi, array_axis, slice(core_lo - lo, core_hi - lo + 1))
        rel_change = (float("inf") if prev_core is None else
                     float(np.max(np.abs(core_psi - prev_core))
                           / max(1.0, float(np.max(np.abs(core_psi))))))
        prev_core = core_psi.copy()
        max_change = comm.allreduce(rel_change, op=MPI.MAX)
        pin = new_pin
        if max_change < tol:
            converged = True
            break
    return dev, converged


def _gather_and_extract(comm, rank, size, spec, doping_full, ntotal_full,
                        x, y, z, nz, ny, nx, array_axis, dev, core_lo,
                        core_hi, lo, solved_bias, bias_override=None):
    """Gather every rank's CORE psi/n/p slice to rank 0, reassemble the
    full-device arrays, and run extract_result() on ONE ordinary
    (unsplit) global Device3D -- the same "no per-rank current
    summation to audit" design the single-bias-point path always used,
    just callable per sweep point too. Returns (global_dev, result) on
    rank 0, (None, None) elsewhere -- `global_dev` is returned (not
    just `result`) so a sweep can also reuse its psi/n/p as the next
    warm-start seed on rank 0's own core slab.

    `bias_override`, if given, is the {contact_name: V} this point
    actually solved -- register_contacts() alone only sets each
    contact to its ContactSpec default, which for a sweep is the
    voltage the SWEPT contact started at, not what THIS point solved.
    Applied the same way solve_bias() itself applies an override
    (DirichletBC.V / GateBC.Vg), so extract_result()'s terminal-current
    read sees the correct boundary voltage for this point's Jn_x/Jp_x.
    """
    core_block = (_take(dev.psi, array_axis, slice(core_lo - lo, core_hi - lo + 1)),
                 _take(dev.n, array_axis, slice(core_lo - lo, core_hi - lo + 1)),
                 _take(dev.p, array_axis, slice(core_lo - lo, core_hi - lo + 1)))
    gathered = comm.gather((core_lo, core_hi, core_block), root=0)
    if rank != 0:
        return None, None

    full_psi = np.zeros((nz, ny, nx))
    full_n = np.zeros((nz, ny, nx))
    full_p = np.zeros((nz, ny, nx))
    idx = [slice(None)] * 3
    for clo, chi, (bpsi, bn, bp) in gathered:
        idx[array_axis] = slice(clo, chi + 1)
        full_psi[tuple(idx)] = bpsi
        full_n[tuple(idx)] = bn
        full_p[tuple(idx)] = bp

    global_mesh = Mesh3D(x, y, z)
    global_dev = Device3D(global_mesh, doping_full, Ntotal=ntotal_full, T=spec.T)
    register_contacts(global_dev, spec)
    global_dev.psi, global_dev.n, global_dev.p = full_psi, full_n, full_p

    if bias_override:
        for name, V in bias_override.items():
            bc = global_dev.bcs.get(name)
            if isinstance(bc, DirichletBC):
                bc.V = V
            elif isinstance(bc, GateBC):
                bc.Vg = V

    if solved_bias:
        # Replicates solve_bias()'s own final four lines (device3d.py)
        # exactly, since psi/n/p were set directly here rather than by
        # calling solve_bias -- Jn_x/Jp_x/etc. are plain attributes set
        # once at the end of a real solve, not lazily computed
        # properties, so extract_result()'s current-density read would
        # otherwise hit a missing attribute.
        cur_voltages = {name: bc.V for name, bc in global_dev.bcs.items()
                        if isinstance(bc, DirichletBC)}
        _, _, Jn_x, Jn_y, Jn_z, Jp_x, Jp_y, Jp_z, _, _ = \
            global_dev._residual_jacobian(full_psi, full_n, full_p, cur_voltages)
        global_dev.Jn_x, global_dev.Jp_x = Jn_x * global_dev.J0, Jp_x * global_dev.J0
        global_dev.Jn_y, global_dev.Jp_y = Jn_y * global_dev.J0, Jp_y * global_dev.J0
        global_dev.Jn_z, global_dev.Jp_z = Jn_z * global_dev.J0, Jp_z * global_dev.J0

    return global_dev, extract_result(global_dev, spec, solved_bias)


def _run_sweep(comm, rank, size, spec, doping_full, ntotal_full, x, y, z,
              nz, ny, nx, array_axis, key, lo, hi, core_lo, core_hi,
              lo_all, hi_all, Ns_global, opts, equilibrium_dev):
    """Phase 1a: a voltage sweep over the MPI Schwarz path.

    Warm-started exactly like solver_runner.run_sweep()'s single-
    process ramp, just per-rank: each point's local device SKIPS
    solve_equilibrium() and starts Newton from the PREVIOUS point's
    converged local psi/n/p (device3d.py's solve_bias already warm-
    starts from self.psi/n/p when set) -- correctness never depends on
    the initial guess, only iteration count does, so this is a pure
    speedup over redoing the bulk-guess equilibrium solve at every
    sweep point the way the combined equilibrium+bias Schwarz loop
    above does for its one point.

    Returns (fields, series) in exactly run_sweep()'s own key shape,
    called on rank 0 only by main() -- rank 0's return value is the
    only one that matters (mirrors _gather_and_extract's own rank-0-
    only return convention).
    """
    import json as _json

    sw = spec.sweep
    voltages = sw.voltages()
    channels = [c.name for c in spec.contacts if c.kind == "ohmic"]

    snapshot_field_names = ("potential", "electron_density", "hole_density")
    snapshot_accessors = {
        "potential": lambda dev: dev.psi_V,
        "electron_density": lambda dev: dev.n_cm3,
        "hole_density": lambda dev: dev.p_cm3,
    }
    snapshot_voltages, snapshot_fields = [], {n: [] for n in snapshot_field_names}
    currents = {name: [] for name in channels}
    converged_flags = []
    fields = None

    warm_psi = equilibrium_dev.psi.copy()
    warm_n = equilibrium_dev.n.copy()
    warm_p = equilibrium_dev.p.copy()

    for i, V in enumerate(voltages):
        if rank == 0:
            print(f"PYTCAD_STAGE=sweep point {i + 1}/{len(voltages)}", flush=True)
        override_bias = merge_bias(spec, override={sw.contact: V})
        point_ok = {"value": True}

        def solve_fn(pin, override_bias=override_bias, point_ok=point_ok,
                    warm_psi=warm_psi, warm_n=warm_n, warm_p=warm_p):
            dev = _build_local_device(spec, doping_full, ntotal_full, x, y, z,
                                      array_axis, key, lo, hi, Ns_global, pin)
            dev.psi, dev.n, dev.p = warm_psi.copy(), warm_n.copy(), warm_p.copy()
            local_bias = {name: Vv for name, Vv in override_bias.items()
                         if name in dev.bcs}
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                try:
                    dev.solve_bias(local_bias, opts)
                    point_ok["value"] = not any(
                        "did not converge" in str(w.message) for w in caught)
                except LinearSolveError:
                    point_ok["value"] = False
            return dev

        dev, schwarz_converged = _schwarz_loop(
            comm, rank, size, array_axis, lo, hi, core_lo, core_hi,
            lo_all, hi_all, solve_fn)
        warm_psi, warm_n, warm_p = dev.psi.copy(), dev.n.copy(), dev.p.copy()

        point_converged = schwarz_converged and comm.allreduce(
            point_ok["value"], op=MPI.LAND)
        converged_flags.append(point_converged)

        global_dev, point_fields = _gather_and_extract(
            comm, rank, size, spec, doping_full, ntotal_full, x, y, z,
            nz, ny, nx, array_axis, dev, core_lo, core_hi, lo,
            solved_bias=True, bias_override=override_bias)

        if rank == 0:
            for name in channels:
                currents[name].append(float(global_dev.terminal_current(name)))
            if point_converged:
                fields = point_fields
                snapshot_voltages.append(float(V))
                for name in snapshot_field_names:
                    snapshot_fields[name].append(
                        np.asarray(snapshot_accessors[name](global_dev), dtype=float))

    if rank != 0:
        return None, None

    d = 3
    series = {
        "sweep__voltage": np.asarray(voltages, dtype=float),
        "sweep__converged": np.asarray(converged_flags, dtype=bool),
        "unit__sweep_current": np.array("A"),
        "sweep__meta": np.array(_json.dumps({
            "contact": sw.contact, "start": sw.start, "stop": sw.stop,
            "step": sw.step, "dimensionality": d})),
    }
    for name, vals in currents.items():
        series[f"sweep__current__{name}"] = np.asarray(vals, dtype=float)
    if snapshot_voltages:
        series["sweep__snapshot__voltages"] = np.array(_json.dumps(snapshot_voltages))
        for name, arrs in snapshot_fields.items():
            for idx, arr in enumerate(arrs):
                series[f"sweep__snapshot__field__{name}__{idx}"] = arr

    if fields is None:
        # Every point diverged -- fall back to the pre-sweep EQUILIBRIUM
        # state (solved_bias=False), never a diverged nonphysical field
        # set, matching run_sweep()'s own fallback_fields contract.
        _, fields = _gather_and_extract(
            comm, rank, size, spec, doping_full, ntotal_full, x, y, z,
            nz, ny, nx, array_axis, equilibrium_dev, core_lo, core_hi,
            lo, solved_bias=False)
    return fields, series


def main(argv):
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()

    job_path, out_path = argv[1], argv[2]
    split_axis = argv[3] if len(argv) > 3 else "x"
    if split_axis not in AXIS_TO_ARRAY:
        raise ValueError(f"split_axis must be x, y or z, got {split_axis!r}")
    array_axis = AXIS_TO_ARRAY[split_axis]
    key = AXIS_TO_KEY[split_axis]

    spec = DeviceSpec.from_json(job_path)
    if spec.mesh.dimensionality != 3:
        raise ValueError("mpi_schwarz_runner is 3D-only")
    if spec.transient is not None:
        raise ValueError("mpi_schwarz_runner does not support transient runs "
                         "(Device3D has no transient module at all)")

    x = np.asarray(spec.mesh.axes["x"], dtype=float)
    y = np.asarray(spec.mesh.axes["y"], dtype=float)
    z = np.asarray(spec.mesh.axes["z"], dtype=float)
    nz, ny, nx = z.size, y.size, x.size
    doping_full = np.asarray(spec.doping.values, dtype=float).reshape(nz, ny, nx)
    ntotal_full = (None if spec.doping.ntotal is None else
                  np.asarray(spec.doping.ntotal, dtype=float).reshape(nz, ny, nx))
    # Matches Device3D's own Ns formula (max(|doping|, ni)) exactly,
    # just evaluated once on the FULL doping array so every rank pins
    # to the same reference -- see Ns_override's docstring in
    # device3d.py for why this must be global, not per-slab.
    from pytcad.materials import SILICON
    Ns_global = max(float(np.abs(doping_full).max()), SILICON.ni(spec.T))

    n_split = doping_full.shape[array_axis]
    lo_all, hi_all, core_lo_all, core_hi_all = _split_axis_range(n_split, size, OVERLAP)
    lo, hi = int(lo_all[rank]), int(hi_all[rank])
    core_lo, core_hi = int(core_lo_all[rank]), int(core_hi_all[rank])

    if rank == 0:
        print("PYTCAD_STAGE=equilibrium", flush=True)

    opts = NewtonOptions(linsolve="direct")

    if spec.sweep is not None:
        # Phase A: pure equilibrium, Schwarz-converged, no bias -- the
        # warm-start seed both for the sweep loop below and for the
        # all-points-diverged fallback fields.
        def eq_solve_fn(pin):
            dev = _build_local_device(spec, doping_full, ntotal_full, x, y, z,
                                      array_axis, key, lo, hi, Ns_global, pin)
            dev.solve_equilibrium(opts)
            return dev

        equilibrium_dev, _ = _schwarz_loop(
            comm, rank, size, array_axis, lo, hi, core_lo, core_hi,
            lo_all, hi_all, eq_solve_fn)

        if rank == 0:
            print("PYTCAD_STAGE=sweep", flush=True)
        fields, series = _run_sweep(
            comm, rank, size, spec, doping_full, ntotal_full, x, y, z,
            nz, ny, nx, array_axis, key, lo, hi, core_lo, core_hi,
            lo_all, hi_all, Ns_global, opts, equilibrium_dev)

        if rank != 0:
            return
        print("PYTCAD_STAGE=extract", flush=True)
        result = fields
        result.update(series)
        np.savez(out_path, **result)
        print(f"SCHWARZ_RESULT_PATH={out_path}", flush=True)
        return

    # Single bias point (or equilibrium only) -- unchanged from the
    # original shipped path: one combined equilibrium+bias Schwarz
    # loop, byte-identical to before the sweep path above was added
    # (verified: bjt_3d still 32.5s / ~1e-17 after this refactor).
    bias = merge_bias(spec) if spec.bias is not None else None

    def solve_fn(pin):
        dev = _build_local_device(spec, doping_full, ntotal_full, x, y, z,
                                  array_axis, key, lo, hi, Ns_global, pin)
        dev.solve_equilibrium(opts)
        if bias is not None:
            local_bias = {name: V for name, V in bias.items() if name in dev.bcs}
            dev.solve_bias(local_bias, opts)
        return dev

    dev, _ = _schwarz_loop(comm, rank, size, array_axis, lo, hi, core_lo,
                           core_hi, lo_all, hi_all, solve_fn)

    if bias is not None and rank == 0:
        print("PYTCAD_STAGE=bias", flush=True)

    if rank == 0:
        print("PYTCAD_STAGE=extract", flush=True)
    _, result = _gather_and_extract(
        comm, rank, size, spec, doping_full, ntotal_full, x, y, z,
        nz, ny, nx, array_axis, dev, core_lo, core_hi, lo,
        solved_bias=bias is not None)

    if rank != 0:
        return
    np.savez(out_path, **result)
    print(f"SCHWARZ_RESULT_PATH={out_path}", flush=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv) or 0)
