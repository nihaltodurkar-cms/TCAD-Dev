"""M17 phase 1 -- time-dependent drift-diffusion for Device1D.

Mirrors continuation.py's shape: this module drives an existing
Device1D through its own _residual_jacobian/_contact_values from the
OUTSIDE, exactly like adaptive_bias_sweep/arc_length_sweep do for bias
continuation.  device.py is never modified -- the backward-Euler /
theta-scheme storage term is added to the already-returned (F, J) for
the interior electron/hole continuity rows only, post-hoc, the same
way continuation.py treats the residual as a black box.

Time discretization (per accepted step, old state (psi0,n0,p0) at
t_old -> new state at t_new = t_old + dt):

    electron row:  theta*Fn(new) + (1-theta)*Fn(old)
                   - dV*(n - n0)/dt = 0
    hole row:      theta*Fp(new) + (1-theta)*Fp(old)
                   + dV*(p - p0)/dt = 0
    Poisson row:   unchanged (algebraic constraint, no time derivative)

where Fn/Fp are Device1D's own steady-state continuity residual rows
(device.py:1228/1253, `Jn_diff -+ Rs*dV`).  theta=1 (backward Euler,
the default and the only theta value the acceptance gates exercise) is
unconditionally stable and needs no F(old) term at all, so that path
never evaluates the old-state residual.  theta<1 (Crank-Nicolson etc)
is implemented for interface completeness but NOT gated -- see
M17-TRANSIENT-PLAN.md section 5 (Honest Limits).

Time is scaled the same way every other rate quantity in Device1D is:
t0 = Ns/R0 = LD**2/D0_REF seconds (the diffusion time implied by the
same reference diffusivity D0_REF that sets device.R0), so that
dV*(n-n0)/dt_s lands at the same order of magnitude as the Rs*dV term
it is added next to.
"""
import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

from .constants import Q
from .device import NewtonOptions


# ----------------------------------------------------------------------
#  Waveforms: per-contact bias as a function of time [s]
# ----------------------------------------------------------------------
class Waveform:
    """Base class: .value(t) -> bias [V] at time t [s]."""

    def value(self, t):
        raise NotImplementedError


class StepWaveform(Waveform):
    """v0 for t < t_step, v1 for t >= t_step."""

    def __init__(self, v0, v1, t_step=0.0):
        self.v0, self.v1, self.t_step = float(v0), float(v1), float(t_step)

    def value(self, t):
        return self.v1 if t >= self.t_step else self.v0


class RampWaveform(Waveform):
    """Linear ramp from v0 to v1 over [t0, t1]; constant outside it."""

    def __init__(self, v0, v1, t0, t1):
        if t1 <= t0:
            raise ValueError("RampWaveform requires t1 > t0")
        self.v0, self.v1, self.t0, self.t1 = float(v0), float(v1), float(t0), float(t1)

    def value(self, t):
        if t <= self.t0:
            return self.v0
        if t >= self.t1:
            return self.v1
        frac = (t - self.t0) / (self.t1 - self.t0)
        return self.v0 + frac * (self.v1 - self.v0)


class PulseWaveform(Waveform):
    """v_base outside [t_start, t_start+width], v_pulse inside it."""

    def __init__(self, v_base, v_pulse, t_start, width):
        if width <= 0.0:
            raise ValueError("PulseWaveform requires width > 0")
        self.v_base = float(v_base)
        self.v_pulse = float(v_pulse)
        self.t_start = float(t_start)
        self.width = float(width)

    def value(self, t):
        return self.v_pulse if self.t_start <= t < self.t_start + self.width \
            else self.v_base


class ConstantWaveform(Waveform):
    """A fixed bias -- lets every contact take a Waveform uniformly."""

    def __init__(self, v):
        self.v = float(v)

    def value(self, t):
        return self.v


def _as_waveform(v):
    return v if isinstance(v, Waveform) else ConstantWaveform(v)


# ----------------------------------------------------------------------
#  Result container
# ----------------------------------------------------------------------
class TransientResult:
    """times [s]; *_hist rows are one snapshot per ACCEPTED step (row 0
    is the initial condition); terminal_current is {"left": ..., "right":
    ...} in A/cm^2 (device.py's own current_density() convention: this
    is a 1D two-terminal device of implicit unit cross-sectional area,
    so a current DENSITY doubles as a terminal current)."""

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
        """Total mobile charge per unit area [C/cm^2] at every snapshot:
        Q(t) = q * sum_i (n_i - p_i) * dx_i, dx_i = dV_i * LD [cm]."""
        dx = device.dV * device.LD
        n_phys = self.n_hist * device.Ns
        p_phys = self.p_hist * device.Ns
        return Q * np.sum((n_phys - p_phys) * dx, axis=1)


def _time_scale(device):
    """Seconds per unit of Device1D's own scaled time (Ns/R0 ==
    LD**2/D0_REF -- the diffusion time set by the same reference
    diffusivity device.R0 is already built from)."""
    return device.Ns / device.R0


def _pack(psi, n, p):
    return np.stack([psi, n, p], axis=1).ravel()


def _unpack(u):
    return u[0::3].copy(), u[1::3].copy(), u[2::3].copy()


def _step_residual_jacobian(device, psi, n, p, bc_new, n_old, p_old,
                             F_old, dV, dt_s, theta, idx_n, idx_p):
    """One theta-scheme transient residual/Jacobian, built by adding the
    storage term (and, for theta != 1, blending in F_old) to Device1D's
    own steady-state (F, J) -- device.py is never touched."""
    F_new, J_new, Jn, Jp = device._residual_jacobian(psi, n, p, bc_new)
    F = F_new.copy()

    if theta != 1.0:
        F[idx_n] = theta * F_new[idx_n] + (1.0 - theta) * F_old[idx_n]
        F[idx_p] = theta * F_new[idx_p] + (1.0 - theta) * F_old[idx_p]
        row_scale = np.ones(F.shape[0])
        row_scale[idx_n] = theta
        row_scale[idx_p] = theta
        J = sp.diags(row_scale) @ J_new
    else:
        J = J_new

    dVi = dV[1:-1]
    F[idx_n] -= dVi / dt_s * (n[1:-1] - n_old[1:-1])
    F[idx_p] += dVi / dt_s * (p[1:-1] - p_old[1:-1])

    extra_rows = np.concatenate([idx_n, idx_p])
    extra_cols = extra_rows  # diagonal: d/dn[i] for idx_n, d/dp[i] for idx_p
    extra_vals = np.concatenate([-dVi / dt_s, dVi / dt_s])
    J = J + sp.csr_matrix((extra_vals, (extra_rows, extra_cols)),
                           shape=J.shape)
    return F, J, Jn, Jp


def _newton_step(device, psi0, n0, p0, bc_new, F_old, dV, dt_s, theta,
                  idx_n, idx_p, opts):
    """Damped Newton solve of one transient step, mirroring
    continuation.py's _bordered_corrector: merit-function backtracking,
    convergence judged by the size of the update (same tol_update
    convention as Device1D.solve_bias), never by raw residual norm."""
    psi, n, p = psi0.copy(), n0.copy(), p0.copy()
    for it in range(opts.max_iter):
        F, J, Jn, Jp = _step_residual_jacobian(
            device, psi, n, p, bc_new, n0, p0, F_old, dV, dt_s, theta,
            idx_n, idx_p)
        du = spsolve(J.tocsc(), -F)
        dpsi, dn, dp = du[0::3], du[1::3], du[2::3]
        dpsi = np.clip(dpsi, -opts.max_dpsi, opts.max_dpsi)

        base = 0.5 * float(np.dot(F, F))
        lam = 1.0
        for _ in range(40):
            psi_t = psi + lam * dpsi
            n_t = np.clip(n + lam * dn, 0.1 * n, 10.0 * n)
            p_t = np.clip(p + lam * dp, 0.1 * p, 10.0 * p)
            Ft, *_ = _step_residual_jacobian(
                device, psi_t, n_t, p_t, bc_new, n0, p0, F_old, dV, dt_s,
                theta, idx_n, idx_p)
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

        rel_n = np.abs(n / np.maximum(n_old_iter, 1e-300) - 1.0).max()
        rel_p = np.abs(p / np.maximum(p_old_iter, 1e-300) - 1.0).max()
        err = max(float(np.abs(dpsi).max()), float(rel_n), float(rel_p))
        if err < opts.tol_update:
            _, _, Jn, Jp = device._residual_jacobian(psi, n, p, bc_new)
            return psi, n, p, True, it + 1, Jn, Jp
    return psi, n, p, False, opts.max_iter, Jn, Jp


def solve_transient(device, waveforms, t_end, dt0, theta=1.0, opts=None,
                     dt_min=None, dt_max=None, growth=1.5, shrink=0.5,
                     output_times=None, verbose=False):
    """Time-step Device1D from its CURRENT state (device.psi/n/p; call
    solve_equilibrium or solve_bias first to set the initial condition)
    to t_end, applying `waveforms` (a {"left": Waveform|float, "right":
    Waveform|float} dict; a bare float is treated as a ConstantWaveform)
    as the two contacts' bias vs time.

    theta=1.0 (default) is backward Euler -- unconditionally stable,
    the only path the M17 acceptance gates exercise.  Adaptive dt grows
    by `growth` after an easy Newton solve and shrinks by `shrink`
    (retrying from the last accepted state, never from a failed
    iterate) on Newton failure, the same control-loop shape
    continuation.py's adaptive_bias_sweep already uses for bias ramps.

    output_times, if given, are the times to actually keep a snapshot
    at (interpolated onto step boundaries is NOT done -- the stepper
    lands exactly on each requested output time by shortening the step
    that would otherwise overshoot it); default is to keep every
    accepted step.

    Raises RuntimeError, never silently stops, if dt shrinks below
    dt_min without Newton convergence.
    """
    opts = opts or NewtonOptions()
    if device.psi is None:
        raise RuntimeError(
            "solve_transient needs an initial condition: call "
            "solve_equilibrium() or solve_bias() first")

    wf_left = _as_waveform(waveforms.get("left", waveforms.get(0)))
    wf_right = _as_waveform(waveforms.get("right", waveforms.get(1)))

    def bias_at(t):
        return [wf_left.value(t), wf_right.value(t)]

    N = device.N
    dV = device.dV
    idx_n = 3 * np.arange(1, N - 1) + 1
    idx_p = 3 * np.arange(1, N - 1) + 2

    t0 = _time_scale(device)
    dt_s = dt0 / t0
    dt_min_s = (dt_min if dt_min is not None else dt0 / 1024.0) / t0
    dt_max_s = (dt_max if dt_max is not None else dt0 * 64.0) / t0

    t = 0.0
    psi, n, p = device.psi.copy(), device.n.copy(), device.p.copy()

    times = [t]
    psi_hist, n_hist, p_hist = [psi.copy()], [n.copy()], [p.copy()]
    dt_hist = []
    left_I, right_I = [], []

    def _record_current(psi_, n_, p_, bc):
        _, _, Jn, Jp = device._residual_jacobian(psi_, n_, p_, bc)
        left_I.append(float((Jn[0] + Jp[0]) * device.J0))
        right_I.append(float((Jn[-1] + Jp[-1]) * device.J0))

    _record_current(psi, n, p, device._contact_values(bias_at(0.0)))

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

        bc_old = device._contact_values(bias_at(t))
        bc_new = device._contact_values(bias_at(t_new))
        F_old = None
        if theta != 1.0:
            F_old, *_ = device._residual_jacobian(psi, n, p, bc_old)

        psi_new, n_new, p_new, converged, n_iter, Jn, Jp = _newton_step(
            device, psi, n, p, bc_new, F_old, dV, step_dt_s, theta,
            idx_n, idx_p, opts)

        if converged:
            t = t_new
            psi, n, p = psi_new, n_new, p_new
            times.append(t)
            psi_hist.append(psi.copy())
            n_hist.append(n.copy())
            p_hist.append(p.copy())
            dt_hist.append(step_dt_s * t0)
            _record_current(psi, n, p, bc_new)
            if verbose:
                print(f"  [transient] t={t:.3e}s  dt={step_dt_s*t0:.3e}s  "
                      f"iters={n_iter}")
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
    _, _, Jn, Jp = device._residual_jacobian(psi, n, p,
                                              device._contact_values(bias_at(t)))
    device.Jn, device.Jp = Jn * device.J0, Jp * device.J0

    return TransientResult(times, psi_hist, n_hist, p_hist,
                            {"left": left_I, "right": right_I}, dt_hist)
