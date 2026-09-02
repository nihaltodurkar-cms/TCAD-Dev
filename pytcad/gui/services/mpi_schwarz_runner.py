"""MPI Schwarz domain-decomposed 3D solve -- one worker per rank.

    mpirun -np <ranks> python -m gui.services.mpi_schwarz_runner \
        <job.json> <tmp_result.npz>

Not launched directly by JobRunner: gui/services/solver_runner.py's
run_job() spawns this (via subprocess, relaying rank 0's stdout through
its own so JobRunner's existing PYTCAD_STAGE parsing keeps working
unchanged) when a job is 3D, above the size threshold, and mpi4py +
mpirun are both available -- see run_job()'s _solve_via_mpi_schwarz().
v1 scope: equilibrium (+ optional single bias point) only, no sweep or
transient -- those fall back to the normal single-process path.

ARCHITECTURE -- overlapping additive Schwarz, not a distributed matrix:
splits the mesh into `size` overlapping x-slabs, each rank solves its
own slab with the ordinary (fast, proven) direct solve, ranks exchange
one interior column of psi/n/p with their neighbor after each local
solve, and the outer loop repeats until the CORE region stops changing.
Confirmed directly (this session's benchmark record) on bjt_3d: 2
sweeps to convergence, exact to ~1.6e-17 relative error against the
single-process reference, and faster than either a plain or a GPU-
accelerated single-process direct solve at 4 ranks. Splitting along x
specifically: it is the axis every current 3D example either doesn't
vary along at all (bjt_3d, moscap_3d, jfet_3d, resistor_3d -- doping is
constant or only y-graded) or where contacts are localized WITHIN it
(mosfet_3d/finfet_3d source-gate-drain, pn_junction_3d's junction) --
the 2-sweep result is specific to bjt_3d's total x-independence, and
other geometries are only guaranteed STRUCTURALLY correct (every rank
is well-posed, doping/BCs translate correctly) by this module, not
verified to converge in as few sweeps. See run_job()'s own comment for
what has and hasn't been measured here.

CONFIRMED, NOT JUST SUSPECTED: splitting along a device's OWN doping
gradient is a genuine regression, not just "unverified." Tried on
pn_junction_3d (the junction sits inside the split, unlike bjt_3d's
x-independent layer stack): a middle rank's per-sweep bias solve took
39-45s (vs. bjt_3d's ~5s) and the run was killed before converging
rather than let it run to an unknown, possibly multi-minute
completion. run_job() refuses to route a job here at all when doping
varies by more than 1% of its own range along x (checked on the real
array, not a device-name list) -- this module has no such guard of its
own, since it trusts the caller to have already made that call.

A CORRECTNESS DETAIL THIS MODULE EXISTS TO GET RIGHT: Device3D derives
its entire dimensionless scaling (Ns, LD, J0, and even the mesh
coordinates -- xs = mesh.x / LD) from max(|doping|) of whatever array
it's built with. Two ranks seeing different SLICES of a device whose
doping varies along x (every example except bjt_3d) would derive
DIFFERENT LD/Ns and silently disagree on units -- confirmed as a real
risk before any of this was wired up, not assumed. Every local device
here is built with Ns_override pinned to the FULL device's own
max(|doping|), computed once from the complete (unsplit) array.
"""
import sys

import numpy as np
from mpi4py import MPI

from pytcad.device3d import Device3D, PinnedBC
from pytcad.mesh3d import Mesh3D
from pytcad.device import NewtonOptions

from .device_spec import DeviceSpec
from .solver_runner import register_contacts, extract_result, merge_bias

OVERLAP = 3
MAX_SCHWARZ = 20
SCHWARZ_TOL = 1e-4


def _split_x(nx, size, overlap):
    base = np.linspace(0, nx, size + 1).astype(int)
    core_lo, core_hi = base[:-1], base[1:] - 1
    lo = np.maximum(core_lo - overlap, 0)
    hi = np.minimum(core_hi + overlap, nx - 1)
    return lo, hi, core_lo, core_hi


def _filter_and_translate(nodes, lo, hi):
    """Global {'i','j','k'} node dict -> the subset with i in [lo,hi],
    i re-based to this slab's own local indexing. None if empty."""
    gi = np.asarray(nodes["i"], dtype=int)
    gj = np.asarray(nodes["j"], dtype=int)
    gk = np.asarray(nodes.get("k", np.zeros_like(gi)), dtype=int)
    mask = (gi >= lo) & (gi <= hi)
    if not mask.any():
        return None
    return {"i": (gi[mask] - lo).tolist(), "j": gj[mask].tolist(),
           "k": gk[mask].tolist()}


def _face_nodes(i_local, ny, nz):
    jj, kk = np.meshgrid(np.arange(ny), np.arange(nz))
    return jj.ravel(), kk.ravel(), np.full(jj.size, i_local)


def _build_local_device(spec, doping_full, ntotal_full, x, y, z,
                        lo, hi, Ns_global, pin):
    nz, ny, nx = doping_full.shape
    local_nx = hi - lo + 1
    mesh = Mesh3D(x[lo:hi + 1], y, z)
    local_doping = doping_full[:, :, lo:hi + 1]
    local_ntotal = None if ntotal_full is None else ntotal_full[:, :, lo:hi + 1]
    dev = Device3D(mesh, local_doping, Ntotal=local_ntotal, T=spec.T,
                   Ns_override=Ns_global)

    # Every contact this slab's x-range touches at all, translated to
    # local indices -- NOT restricted to this rank's "core" ownership:
    # a real physical contact must be applied everywhere it physically
    # exists, including in a neighbor's overlap region (redundant but
    # harmless there, since it's the same fixed value); only terminal-
    # CURRENT bookkeeping needs single ownership, and that is handled
    # later by recomputing it once on the reassembled global device,
    # not by any per-rank accounting here.
    for c in spec.contacts:
        local_nodes = _filter_and_translate(c.nodes, lo, hi)
        if local_nodes is None:
            continue
        if c.kind == "ohmic":
            dev.add_contact(c.name, V=c.V, **local_nodes)
        elif c.kind == "gate":
            dev.add_gate(c.name, tox_cm=c.tox_cm, Vfb=c.Vfb, Vg=c.V,
                         normal_axis=c.normal_axis, **local_nodes)

    if "left" in pin:
        jj, kk, ii0 = _face_nodes(0, ny, nz)
        psi0, n0, p0 = pin["left"]
        dev.bcs["_schwarz_left"] = PinnedBC(i=ii0, j=jj, k=kk, psi0=psi0, n0=n0, p0=p0)
    if "right" in pin:
        jj, kk, iiN = _face_nodes(local_nx - 1, ny, nz)
        psi0, n0, p0 = pin["right"]
        dev.bcs["_schwarz_right"] = PinnedBC(i=iiN, j=jj, k=kk, psi0=psi0, n0=n0, p0=p0)
    return dev


def main(argv):
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    size = comm.Get_size()

    job_path, out_path = argv[1], argv[2]
    spec = DeviceSpec.from_json(job_path)
    if spec.mesh.dimensionality != 3:
        raise ValueError("mpi_schwarz_runner is 3D-only")
    if spec.sweep is not None or spec.transient is not None:
        raise ValueError("mpi_schwarz_runner v1 does not support sweep/transient")

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

    lo_all, hi_all, core_lo_all, core_hi_all = _split_x(nx, size, OVERLAP)
    lo, hi = int(lo_all[rank]), int(hi_all[rank])
    core_lo, core_hi = int(core_lo_all[rank]), int(core_hi_all[rank])
    local_nx = hi - lo + 1

    if rank == 0:
        print("PYTCAD_STAGE=equilibrium", flush=True)

    opts = NewtonOptions(linsolve="direct")
    bias = merge_bias(spec) if spec.bias is not None else None

    pin = {}
    prev_core = None
    dev = None
    for sweep in range(MAX_SCHWARZ):
        dev = _build_local_device(spec, doping_full, ntotal_full, x, y, z,
                                  lo, hi, Ns_global, pin)
        dev.solve_equilibrium(opts)
        if bias is not None:
            local_bias = {name: V for name, V in bias.items() if name in dev.bcs}
            dev.solve_bias(local_bias, opts)

        # Sample at the GLOBAL position the receiving neighbor will
        # actually pin, not an arbitrary OVERLAP-column offset from my
        # own edge -- those are different physical locations whenever
        # OVERLAP != 1, which they were: sending my own core-edge value
        # (local index OVERLAP) and having the neighbor pin ITS outer
        # domain edge with it silently mismatched by OVERLAP-1 columns
        # (confirmed directly: with OVERLAP=3 that's a real 2-column
        # spatial offset). It happened not to matter for bjt_3d's
        # measured ~1e-17 error only because that device's field is
        # x-invariant by construction (every column has the same
        # value) -- for any device with real field curvature near a
        # subdomain edge this would converge to a subtly, silently
        # wrong answer with no way to detect it from the Schwarz
        # residual alone (that residual only checks each rank's own
        # core stabilizing, never cross-rank agreement at the true
        # shared boundary). lo_all/hi_all are already the same on
        # every rank (computed identically from the same job.json), so
        # each rank can compute exactly where ITS neighbor's edge sits
        # in GLOBAL coordinates and sample its own local array there.
        #
        # Raveled (C-order: z then y) to match _face_nodes()'s
        # jj/kk.ravel() ordering exactly -- PinnedBC.psi0/n0/p0 must be
        # flat arrays aligned 1:1 with its (i,j,k) node lists, the same
        # contract every other BC's node/value arrays already follow.
        send_left = None
        if rank > 0:
            li = int(hi_all[rank - 1]) - lo
            send_left = (dev.psi[:, :, li].ravel().copy(),
                        dev.n[:, :, li].ravel().copy(),
                        dev.p[:, :, li].ravel().copy())
        send_right = None
        if rank < size - 1:
            li = int(lo_all[rank + 1]) - lo
            send_right = (dev.psi[:, :, li].ravel().copy(),
                         dev.n[:, :, li].ravel().copy(),
                         dev.p[:, :, li].ravel().copy())

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

        core_psi = dev.psi[:, :, (core_lo - lo):(core_hi - lo + 1)]
        rel_change = (float("inf") if prev_core is None else
                     float(np.max(np.abs(core_psi - prev_core))
                           / max(1.0, float(np.max(np.abs(core_psi))))))
        prev_core = core_psi.copy()
        max_change = comm.allreduce(rel_change, op=MPI.MAX)
        pin = new_pin
        if max_change < SCHWARZ_TOL:
            break

    if bias is not None and rank == 0:
        print("PYTCAD_STAGE=bias", flush=True)

    # Gather each rank's CORE psi/n/p slice to rank 0 and reassemble
    # the full-device arrays -- core-only (not the overlap-extended
    # local range) so every global node is written exactly once.
    core_block = (dev.psi[:, :, (core_lo - lo):(core_hi - lo + 1)],
                 dev.n[:, :, (core_lo - lo):(core_hi - lo + 1)],
                 dev.p[:, :, (core_lo - lo):(core_hi - lo + 1)])
    gathered = comm.gather((core_lo, core_hi, core_block), root=0)

    if rank != 0:
        return

    print("PYTCAD_STAGE=extract", flush=True)
    full_psi = np.zeros((nz, ny, nx))
    full_n = np.zeros((nz, ny, nx))
    full_p = np.zeros((nz, ny, nx))
    for clo, chi, (bpsi, bn, bp) in gathered:
        full_psi[:, :, clo:chi + 1] = bpsi
        full_n[:, :, clo:chi + 1] = bn
        full_p[:, :, clo:chi + 1] = bp

    # One global (unsplit) device, built exactly as the normal
    # single-process path would -- its own Ns is already the correct
    # global reference since it sees the FULL doping array, so no
    # override is needed here. State is set directly from the
    # Schwarz-reassembled arrays rather than solved again.
    global_mesh = Mesh3D(x, y, z)
    global_dev = Device3D(global_mesh, doping_full, Ntotal=ntotal_full, T=spec.T)
    register_contacts(global_dev, spec)
    global_dev.psi, global_dev.n, global_dev.p = full_psi, full_n, full_p

    solved_bias = bias is not None
    if solved_bias:
        # Replicates solve_bias()'s own final four lines (device3d.py)
        # exactly, since psi/n/p were set directly here rather than by
        # calling solve_bias -- Jn_x/Jp_x/etc. are plain attributes set
        # once at the end of a real solve, not lazily computed
        # properties, so extract_result()'s current-density read would
        # otherwise hit a missing attribute.
        cur_voltages = {name: bc.V for name, bc in global_dev.bcs.items()
                        if hasattr(bc, "V")}
        _, _, Jn_x, Jn_y, Jn_z, Jp_x, Jp_y, Jp_z, _, _ = \
            global_dev._residual_jacobian(full_psi, full_n, full_p, cur_voltages)
        global_dev.Jn_x, global_dev.Jp_x = Jn_x * global_dev.J0, Jp_x * global_dev.J0
        global_dev.Jn_y, global_dev.Jp_y = Jn_y * global_dev.J0, Jp_y * global_dev.J0
        global_dev.Jn_z, global_dev.Jp_z = Jn_z * global_dev.J0, Jp_z * global_dev.J0

    result = extract_result(global_dev, spec, solved_bias)
    np.savez(out_path, **result)
    print(f"SCHWARZ_RESULT_PATH={out_path}", flush=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv) or 0)
