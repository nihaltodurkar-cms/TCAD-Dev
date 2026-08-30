"""M17 phase 2 -- time-dependent drift-diffusion for Device2D.

Same pattern as transient.py (Phase 1, 1D): drives an existing
Device2D through its own _residual_jacobian from the OUTSIDE, adding
the backward-Euler/theta-scheme storage term to the already-returned
(F, J) for the non-contact nodes only. device2d.py is never touched.

Two things are actually SIMPLER here than in 1D:

  - Device2D._residual_jacobian(psi, n, p, voltages) already takes a
    {contact_name: V} dict directly -- there is no separate
    _contact_values() step to call first (device.py's Device1D needs
    that because its Dirichlet nodes are always exactly the two array
    ends; Device2D's DirichletBC objects carry arbitrary (i, j) node
    sets, so the dict IS the contact interface).

  - Device2D._residual_jacobian already returns the pre-Dirichlet-
    overwrite box-integration continuity residual (F_n, F_p, shape
    (Ny, Nx)) as its last two outputs -- exactly what
    Device2D.terminal_current() itself uses to extract a current-
    conserving terminal current. The transient storage term is never
    added at contact nodes (see below), so F_n/F_p at those nodes keep
    meaning exactly what terminal_current()'s docstring says, and
    per-step terminal currents are extracted the same way, for EVERY
    registered contact (not just two), not just left/right.

Time discretization identical to Phase 1: for a non-contact node,

    electron row:  theta*Fn(new) + (1-theta)*Fn(old) - dV*(n-n0)/dt = 0
    hole row:      theta*Fp(new) + (1-theta)*Fp(old) + dV*(p-p0)/dt = 0
    Poisson row:   unchanged (algebraic constraint)

Contact (Dirichlet) nodes are excluded from the storage term entirely
-- their rows are already pinned to the (time-varying) waveform value
at the new time by Device2D._residual_jacobian itself, the same way
Phase 1 leaves Device1D's two boundary rows untouched.
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

from .constants import Q
from .device import NewtonOptions
from .device2d import DirichletBC
from .transient import Waveform, _as_waveform


def _time_scale(device):
    return device.Ns / device.R0


class TransientResult2D:
    """times [s]; *_hist rows are one (Ny, Nx) snapshot per accepted
    step (row 0 is the initial condition); terminal_current is
    {contact_name: [...]} in A/cm (Device2D.terminal_current's own
    unit -- current per unit depth)."""

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
        """Mobile charge per unit depth [C/cm], RELATIVE to the initial
        snapshot (always 0 at t=0 by construction):

            Q(t) - Q(0) = q * sum_{i,j} [(n_ij(t)-n_ij(0))
                                          - (p_ij(t)-p_ij(0))] * dA_ij

        dA_ij = dV_ij * LD**2 [cm^2] (dV is a scaled AREA in 2D, unlike
        1D's scaled length). Computed as a delta, not an absolute total,
        because at this mesh's node count the ABSOLUTE sum of n and p
        over the whole domain (dominated by near-cancelling majority-
        carrier bulk regions on each side of a diode) loses the actual
        (much smaller) transient signal to float64 cancellation --
        found directly while gating G4 (see M17-TRANSIENT-PLAN.md
        section 5): the naive absolute-sum version returned values
        ~1e8x smaller than the real, physically-consistent answer.
        Computing the delta directly (rather than differencing two
        already-cancelled absolute totals after the fact) avoids
        summing the large, non-time-varying bulk term at all."""
        dA = device.dV * device.LD ** 2
        dn = (self.n_hist - self.n_hist[0]) * device.Ns
        dp = (self.p_hist - self.p_hist[0]) * device.Ns
        return Q * np.sum((dn - dp) * dA, axis=(1, 2))


def _non_contact_flat_index(device):
    Nx = device.Nx
    contact_mask = np.zeros((device.Ny, Nx), dtype=bool)
    for bc in device.bcs.values():
        if isinstance(bc, DirichletBC):
            contact_mask[bc.j, bc.i] = True
    k_all = np.arange(device.N)
    return k_all[~contact_mask.ravel()]


def _step_residual_jacobian(device, psi, n, p, voltages_new, n_old, p_old,
                             F_old_n, F_old_p, dV, dt_s, theta, k_free):
    (F_new, J_new, Jn_x, Jn_y, Jp_x, Jp_y,
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
    Ny, Nx = device.Ny, device.Nx
    for it in range(opts.max_iter):
        F, J, F_n_raw, F_p_raw = _step_residual_jacobian(
            device, psi, n, p, voltages_new, n0, p0, F_old_n, F_old_p, dV,
            dt_s, theta, k_free)
        du = spsolve(J.tocsc(), -F)
        dpsi = du[0::3].reshape(Ny, Nx)
        dn = du[1::3].reshape(Ny, Nx)
        dp = du[2::3].reshape(Ny, Nx)
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

        rel_n = (np.abs(n - n_old_iter) / np.maximum(n_old_iter, 1e-10)).max()
        rel_p = (np.abs(p - p_old_iter) / np.maximum(p_old_iter, 1e-10)).max()
        err = max(float(np.abs(dpsi).max()), float(rel_n), float(rel_p))
        if err < opts.tol_update:
            return psi, n, p, True, it + 1
    return psi, n, p, False, opts.max_iter


def solve_transient(device, waveforms, t_end, dt0, theta=1.0, opts=None,
                     dt_min=None, dt_max=None, growth=1.5, shrink=0.5,
                     output_times=None, verbose=False):
    """Time-step Device2D from its CURRENT state to t_end.

    waveforms: {contact_name: Waveform|float} for every registered
    DirichletBC contact name (device.bcs); a name not mentioned keeps
    its current bc.V fixed for the whole run. Gate (GateBC) voltages
    are NOT time-varying in this phase -- left at whatever bc.Vg
    already is, same restriction Device2D.solve_bias itself has none
    of, but which this phase doesn't lift (see M17-TRANSIENT-PLAN.md
    section 5, phase 2 sub-scope).

    See transient.py's solve_transient for the theta/adaptive-dt
    semantics -- identical here, just on Device2D's 2D state arrays.
    """
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
            kk = bc.j * device.Nx + bc.i
            I = float((F_n_raw.ravel()[kk] + F_p_raw.ravel()[kk]).sum()) \
                * device.J0 * device.LD
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
                print(f"  [transient2d] t={t:.3e}s  dt={step_dt_s*t0:.3e}s "
                      f" iters={n_iter}")
            if out_times is not None and out_idx < len(out_times) \
                    and abs(t - out_times[out_idx]) < 1e-15 * max(1.0, t):
                out_idx += 1
            if n_iter <= max(3, opts.max_iter // 4):
                dt_s = min(step_dt_s * growth, dt_max_s)
            else:
                dt_s = step_dt_s
        else:
            dt_s = step_dt_s * shrink
            if dt_s < dt_min_s:
                raise RuntimeError(
                    f"solve_transient stalled at t={t:.3e}s approaching "
                    f"t={t_new:.3e}s: dt shrank below dt_min="
                    f"{dt_min_s * t0:.3e}s without Newton convergence")

    device.psi, device.n, device.p = psi, n, p
    final_voltages = voltages_at(t)
    (_, _, Jn_x, Jn_y, Jp_x, Jp_y, _, _) = device._residual_jacobian(
        psi, n, p, final_voltages)
    device.Jn_x, device.Jp_x = Jn_x * device.J0, Jp_x * device.J0
    device.Jn_y, device.Jp_y = Jn_y * device.J0, Jp_y * device.J0
    for name, bc in device.bcs.items():
        if isinstance(bc, DirichletBC) and name in final_voltages:
            bc.V = final_voltages[name]

    return TransientResult2D(times, psi_hist, n_hist, p_hist,
                              terminal_current, dt_hist)
