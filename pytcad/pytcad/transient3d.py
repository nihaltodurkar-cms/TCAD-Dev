"""M45 -- time-dependent drift-diffusion for Device3D, closing the
"Transient / small-signal AC -> 3D" row of ARCHITECTURE.md's dimensional-
lift coverage matrix (section 5.3).

A direct lift of transient2d.py's own pattern one axis further (same
relationship transient2d.py has to transient.py): drives an existing
Device3D through its own _residual_jacobian from the OUTSIDE, adding the
backward-Euler/theta-scheme storage term to the non-contact rows only.
device3d.py is never touched.

Device3D's _residual_jacobian already returns the box-integration
continuity residual (F_n, F_p, shape (Nz,Ny,Nx)) as its last two
outputs -- the same quantity Device3D.terminal_current() itself uses,
scaled by J0*LD**2 (an AREA, not a length -- Device3D meshes every
physical dimension, so there is no remaining implicit unit-depth
assumption the way Device2D's A/cm convention has).

Time discretization identical to Phase 1/2:

    electron row:  theta*Fn(new) + (1-theta)*Fn(old) - dV*(n-n0)/dt = 0
    hole row:      theta*Fp(new) + (1-theta)*Fp(old) + dV*(p-p0)/dt = 0
    Poisson row:   unchanged (algebraic constraint)

Contact (Dirichlet) nodes are excluded from the storage term entirely,
exactly as in Phase 1/2. Time-varying GateBC voltage is NOT supported
here either -- same explicit sub-scope descope transient2d.py's own
docstring states, carried forward unchanged (no prior art in this
codebase closes that gap yet).

Two things found while gating a genuinely stiff transient (a diode
jumped straight from equilibrium to 0.3V forward bias in one
backward-Euler step -- tests/test_m45_transient3d.py's G4/G5; see
M45-TRANSIENT-AC-3D-PLAN.md section 8 for the full investigation):

  1. `_newton_step`'s line search could fail COMPLETELY (every damping
     factor down to ~2^-40 makes the merit worse, lam=0.0, state
     unchanged) -- the outer loop did not detect this and burned the
     entire opts.max_iter budget recomputing the IDENTICAL doomed
     attempt before giving up. Fixed: bail out of the Newton loop the
     first time lam==0.0 (bit-identical result either way -- the
     returned state is unchanged -- just without the wasted
     recomputation).

  2. A genuinely stiff step can still fail to converge for reasons that
     are NOT a bug: at a coarse z-resolution (Nz=3), the single
     interior z-node's control volume (dVz) is TWICE a boundary
     z-node's (standard box-integration convention -- a boundary cell
     only extends half the spacing to its one neighbor). The SAME
     single global line-search damping factor `lam` is shared across
     every node, so that one disproportionately-stressed node can force
     lam to 0 even when every other node (including the z-boundary
     ones, and a hypothetical 2D problem with no such node at all)
     would already have converged. Confirmed directly: the identical
     jump converges cleanly with Nz=7 (5 interior nodes instead of 1),
     no other change. Not something this module's solver choice has
     anything to do with -- a mesh-resolution property of the physical
     problem, not a numerical-core defect.
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

from .device import NewtonOptions
from .device3d import DirichletBC
from .transient import Waveform, _as_waveform


def _time_scale(device):
    return device.Ns / device.R0


class TransientResult3D:
    """times [s]; *_hist rows are one (Nz, Ny, Nx) snapshot per accepted
    step (row 0 is the initial condition); terminal_current is
    {contact_name: [...]} in real Amps [A] -- Device3D.terminal_current's
    own unit (full 3D device, no implicit unit-depth/width the way
    Device2D's A/cm convention carries)."""

    def __init__(self, times, psi_hist, n_hist, p_hist, terminal_current,
                 dt_hist):
        self.times = np.asarray(times, dtype=float)
        self.psi_hist = np.asarray(psi_hist, dtype=float)
        self.n_hist = np.asarray(n_hist, dtype=float)
        self.p_hist = np.asarray(p_hist, dtype=float)
        self.terminal_current = {k: np.asarray(v, dtype=float)
                                  for k, v in terminal_current.items()}
        self.dt_hist = np.asarray(dt_hist, dtype=float)

    def stored_charge(self, device):
        """Mobile charge, RELATIVE to the initial snapshot (always 0 at
        t=0 by construction), in real Coulombs [C]:

            Q(t) - Q(0) = q * sum_{i,j,k} [(n(t)-n(0)) - (p(t)-p(0))] * dV_ijk

        dV_ijk = device.dV * LD**3 [cm^3] (a scaled VOLUME in 3D, unlike
        2D's scaled area) -- computed as a delta rather than an absolute
        total for the identical float64-cancellation reason
        transient2d.py's own stored_charge docstring records (see
        M17-TRANSIENT-PLAN.md section 5)."""
        from .constants import Q
        dVol = device.dV * device.LD ** 3
        dn = (self.n_hist - self.n_hist[0]) * device.Ns
        dp = (self.p_hist - self.p_hist[0]) * device.Ns
        return Q * np.sum((dn - dp) * dVol, axis=(1, 2, 3))


def _non_contact_flat_index(device):
    Nx, Ny = device.Nx, device.Ny
    contact_mask = np.zeros((device.Nz, device.Ny, device.Nx), dtype=bool)
    for bc in device.bcs.values():
        if isinstance(bc, DirichletBC):
            contact_mask[bc.k, bc.j, bc.i] = True
    k_all = np.arange(device.N)
    return k_all[~contact_mask.ravel()]


def _step_residual_jacobian(device, psi, n, p, voltages_new, n_old, p_old,
                             F_old_n, F_old_p, dV, dt_s, theta, k_free):
    (F_new, J_new, Jn_x, Jn_y, Jn_z, Jp_x, Jp_y, Jp_z,
     F_n_raw, F_p_raw) = device._residual_jacobian(psi, n, p, voltages_new)
    F = F_new.copy()

    idx_n = 3 * k_free + 1
    idx_p = 3 * k_free + 2
    dVi = dV.ravel()[k_free]
    n_flat, p_flat = n.ravel()[k_free], p.ravel()[k_free]
    n0_flat, p0_flat = n_old.ravel()[k_free], p_old.ravel()[k_free]

    if theta != 1.0:
        Fn_old_flat = F_old_n.ravel()[k_free]
        Fp_old_flat = F_old_p.ravel()[k_free]
        F[idx_n] = theta * F[idx_n] + (1.0 - theta) * Fn_old_flat
        F[idx_p] = theta * F[idx_p] + (1.0 - theta) * Fp_old_flat
        row_scale = np.ones(F.shape[0])
        row_scale[idx_n] = theta
        row_scale[idx_p] = theta
        J = sp.diags(row_scale) @ J_new
    else:
        J = J_new

    F[idx_n] -= dVi / dt_s * (n_flat - n0_flat)
    F[idx_p] += dVi / dt_s * (p_flat - p0_flat)

    extra_rows = np.concatenate([idx_n, idx_p])
    extra_vals = np.concatenate([-dVi / dt_s, dVi / dt_s])
    J = J + sp.csr_matrix((extra_vals, (extra_rows, extra_rows)),
                           shape=J.shape)
    return F, J, F_n_raw, F_p_raw


def _newton_step(device, psi0, n0, p0, voltages_new, F_old_n, F_old_p, dV,
                  dt_s, theta, k_free, opts):
    psi, n, p = psi0.copy(), n0.copy(), p0.copy()
    Nz, Ny, Nx = device.Nz, device.Ny, device.Nx
    for it in range(opts.max_iter):
        F, J, F_n_raw, F_p_raw = _step_residual_jacobian(
            device, psi, n, p, voltages_new, n0, p0, F_old_n, F_old_p, dV,
            dt_s, theta, k_free)
        du = spsolve(J.tocsc(), -F)
        dpsi = du[0::3].reshape(Nz, Ny, Nx)
        dn = du[1::3].reshape(Nz, Ny, Nx)
        dp = du[2::3].reshape(Nz, Ny, Nx)
        dpsi = np.clip(dpsi, -opts.max_dpsi, opts.max_dpsi)

        base = 0.5 * float(np.dot(F, F))
        lam = 1.0
        for _ in range(40):
            psi_t = psi + lam * dpsi
            n_t = np.clip(n + lam * dn, 0.1 * n, 10.0 * n)
            p_t = np.clip(p + lam * dp, 0.1 * p, 10.0 * p)
            Ft, *_ = _step_residual_jacobian(
                device, psi_t, n_t, p_t, voltages_new, n0, p0, F_old_n,
                F_old_p, dV, dt_s, theta, k_free)
            merit = 0.5 * float(np.dot(Ft, Ft))
            if np.isfinite(merit) and merit <= base * (1.0 - 1e-4 * lam):
                break
            lam *= 0.5
        else:
            lam = 0.0

        n_old_iter, p_old_iter = n, p
        psi = psi + lam * dpsi
        n = np.clip(n + lam * dn, 0.1 * n, 10.0 * n)
        p = np.clip(p + lam * dp, 0.1 * p, 10.0 * p)

        # NOTE: `err` uses the RAW (lam-independent) `dpsi` magnitude,
        # not lam*dpsi -- this is deliberate and PRE-EXISTING (unchanged
        # from before the lam==0 short-circuit below was added): at
        # lam=0 the state is untouched (rel_n=rel_p=0 trivially, since
        # n_old_iter/p_old_iter ARE n/p here), so `err` collapses to
        # "how large was the correction the linear solve WANTED to
        # make" -- if that itself is already below tol_update (a
        # genuinely converged/steady point, e.g. an ohmic resistor at
        # its bias-point steady state, F already ~0 to machine
        # precision), THIS iteration correctly reports converged even
        # though the line search technically "failed" (there is
        # nothing left to improve). Checking this BEFORE the lam==0
        # bail below is required, not optional -- an earlier version of
        # that bail returned False unconditionally on lam==0 and
        # regressed exactly this case (caught by a GUI-wiring test on a
        # uniform-doping resistor fixture, not by any of M45's own
        # diode-based gates, none of which reach a genuinely-already-
        # converged interior time step).
        rel_n = (np.abs(n - n_old_iter) / np.maximum(n_old_iter, 1e-10)).max()
        rel_p = (np.abs(p - p_old_iter) / np.maximum(p_old_iter, 1e-10)).max()
        err = max(float(np.abs(dpsi).max()), float(rel_n), float(rel_p))
        if err < opts.tol_update:
            return psi, n, p, True, it + 1

        if lam == 0.0:
            # A fully-failed line search means every damping factor down
            # to ~2^-40 made the merit function worse -- state does not
            # change, so every further outer iteration would recompute
            # the IDENTICAL residual/Jacobian/line-search and fail the
            # same way (observed directly: a stiff step forcing this
            # branch looped unproductively for ~70+ of opts.max_iter=100
            # iterations, each re-running a 40-step line search, before
            # finally exhausting the budget -- ~800s wasted on a single
            # doomed step attempt with the state never once changing).
            # Bailing out immediately is bit-identical to letting the
            # loop run to max_iter (the returned (psi, n, p, False, ...)
            # state is unchanged either way -- caller shrinks dt and
            # retries), just without the wasted recomputation.
            return psi, n, p, False, it + 1
    return psi, n, p, False, opts.max_iter


def solve_transient(device, waveforms, t_end, dt0, theta=1.0, opts=None,
                     dt_min=None, dt_max=None, growth=1.5, shrink=0.5,
                     output_times=None, verbose=False):
    """Time-step Device3D from its CURRENT state to t_end.

    waveforms: {contact_name: Waveform|float} for every registered
    DirichletBC contact name (device.bcs); a name not mentioned keeps
    its current bc.V fixed for the whole run. Gate (GateBC) voltages are
    NOT time-varying in this phase, same restriction transient2d.py's
    own solve_transient carries.

    See transient.py's solve_transient for the theta/adaptive-dt
    semantics -- identical here, just on Device3D's 3D state arrays.
    """
    from .device3d import Device3D
    if not isinstance(device, Device3D):
        raise TypeError(
            "transient3d.solve_transient only supports Device3D; got "
            f"{type(device).__name__}. 1D/2D transient live in "
            "transient.py / transient2d.py.")

    opts = opts or NewtonOptions()
    if device.psi is None:
        raise RuntimeError(
            "solve_transient needs an initial condition: call "
            "solve_equilibrium() or solve_bias() first")

    wf = {name: _as_waveform(v) for name, v in waveforms.items()}
    contact_names = [name for name, bc in device.bcs.items()
                     if isinstance(bc, DirichletBC)]

    def voltages_at(t):
        return {name: (wf[name].value(t) if name in wf
                       else device.bcs[name].V) for name in contact_names}

    dV = device.dV
    k_free = _non_contact_flat_index(device)

    t0 = _time_scale(device)
    dt_s = dt0 / t0
    dt_min_s = (dt_min if dt_min is not None else dt0 / 1024.0) / t0
    dt_max_s = (dt_max if dt_max is not None else dt0 * 64.0) / t0

    t = 0.0
    psi, n, p = device.psi.copy(), device.n.copy(), device.p.copy()

    times = [t]
    psi_hist, n_hist, p_hist = [psi.copy()], [n.copy()], [p.copy()]
    dt_hist = []
    terminal_current = {name: [] for name in contact_names}

    def _record_current(psi_, n_, p_, voltages):
        *_, F_n_raw, F_p_raw = device._residual_jacobian(psi_, n_, p_,
                                                          voltages)
        for name in contact_names:
            bc = device.bcs[name]
            kk = bc.k * device.Ny * device.Nx + bc.j * device.Nx + bc.i
            I = float((F_n_raw.ravel()[kk] + F_p_raw.ravel()[kk]).sum()) \
                * device.J0 * device.LD ** 2
            terminal_current[name].append(I)

    _record_current(psi, n, p, voltages_at(0.0))

    out_times = sorted(output_times) if output_times else None
    out_idx = 0

    while t < t_end - 1e-15:
        step_dt_s = dt_s
        t_new = t + step_dt_s * t0
        if out_times is not None and out_idx < len(out_times):
            if t_new > out_times[out_idx]:
                t_new = out_times[out_idx]
                step_dt_s = (t_new - t) / t0
        if t_new > t_end:
            t_new = t_end
            step_dt_s = (t_new - t) / t0

        voltages_new = voltages_at(t_new)
        F_old_n = F_old_p = None
        if theta != 1.0:
            *_, F_old_n, F_old_p = device._residual_jacobian(
                psi, n, p, voltages_at(t))

        psi_new, n_new, p_new, converged, n_iter = _newton_step(
            device, psi, n, p, voltages_new, F_old_n, F_old_p, dV,
            step_dt_s, theta, k_free, opts)

        if converged:
            t = t_new
            psi, n, p = psi_new, n_new, p_new
            times.append(t)
            psi_hist.append(psi.copy())
            n_hist.append(n.copy())
            p_hist.append(p.copy())
            dt_hist.append(step_dt_s * t0)
            _record_current(psi, n, p, voltages_new)
            if verbose:
                print(f"  [transient3d] t={t:.3e}s  dt={step_dt_s*t0:.3e}s "
                      f" iters={n_iter}")
            if out_times is not None and out_idx < len(out_times) \
                    and abs(t - out_times[out_idx]) < 1e-15 * max(1.0, t):
                out_idx += 1
            if n_iter <= max(3, opts.max_iter // 4):
                dt_s = min(step_dt_s * growth, dt_max_s)
            else:
                dt_s = step_dt_s
        else:
            if verbose:
                print(f"  [transient3d] SHRINK step_dt_s={step_dt_s:.3e} "
                      f"n_iter={n_iter}")
            dt_s = step_dt_s * shrink
            if dt_s < dt_min_s:
                raise RuntimeError(
                    f"solve_transient stalled at t={t:.3e}s approaching "
                    f"t={t_new:.3e}s: dt shrank below dt_min="
                    f"{dt_min_s * t0:.3e}s without Newton convergence")

    device.psi, device.n, device.p = psi, n, p
    final_voltages = voltages_at(t)
    (_, _, Jn_x, Jn_y, Jn_z, Jp_x, Jp_y, Jp_z, _, _) = device._residual_jacobian(
        psi, n, p, final_voltages)
    device.Jn_x, device.Jp_x = Jn_x * device.J0, Jp_x * device.J0
    device.Jn_y, device.Jp_y = Jn_y * device.J0, Jp_y * device.J0
    device.Jn_z, device.Jp_z = Jn_z * device.J0, Jp_z * device.J0
    for name, bc in device.bcs.items():
        if isinstance(bc, DirichletBC) and name in final_voltages:
            bc.V = final_voltages[name]

    return TransientResult3D(times, psi_hist, n_hist, p_hist,
                              terminal_current, dt_hist)
