"""M22 phase 2 -- continuation drivers for Device1D bias ramps.

Two independent strategies (M22-LINSOLVE-PLAN.md section 1, phase 2):

  adaptive_bias_sweep -- fixed-direction bias ramp that halves its step
      and retries (from the last CONFIRMED-converged state, never from
      a failed iterate) when Newton fails to converge, instead of a
      fixed step silently landing on a diverged or barely-converged
      point.  Targets the plan's "-2V marginal points" acceptance item.

  arc_length_sweep -- pseudo-arclength continuation (Keller 1977) that
      parameterizes the solution branch by ARC LENGTH in (state, bias)
      space instead of by bias alone.  A bias-controlled Newton step
      cannot distinguish "no solution near here" from "converged to the
      wrong branch of a folded response curve" -- exactly the M15 R1b
      gap: avalanche onset folds the current-voltage curve, and damped
      Newton with a bias-controlled step basin-locks onto the weak
      branch without any sign of failure (see M15-IONIZATION-PLAN.md,
      "R1b ATTEMPT 2026-08-28").  Arc-length continuation can trace
      PAST such a fold because the step is measured along the branch,
      not along the bias axis, so it keeps making progress even where
      dV/d(arc length) passes through zero.

Both operate on an existing Device1D instance via its own
_residual_jacobian/_contact_values -- no device-internal state is
duplicated, and neither driver bypasses the FD-Jacobian-validated
residual assembly.
"""
import warnings


class ArcLengthStalled(RuntimeError):
    """arc_length_sweep could not converge even at ds_min.

    Carries `last_V` / `last_records`: the last successfully traced
    bias / full record list before the stall, so a caller that WANTS
    the stall itself as a signal (e.g. "this is the fold/breakdown
    voltage") doesn't have to parse it back out of the error message.
    """

    def __init__(self, message, last_V, last_records):
        super().__init__(message)
        self.last_V = last_V
        self.last_records = last_records

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

from .device import NewtonOptions


def _pack(psi, n, p):
    return np.stack([psi, n, p], axis=1).ravel()


def _unpack(u):
    return u[0::3].copy(), u[1::3].copy(), u[2::3].copy()


def adaptive_bias_sweep(device, v_end, step0, opts=None, *, v_start=0.0,
                         terminal=0, other_bias=0.0, min_step=None,
                         max_step=None, growth=1.5, shrink=0.5,
                         verbose=False):
    """Ramp `terminal`'s bias from v_start to v_end with step backoff.

    On Newton failure the step is halved and retried from the last
    CONFIRMED-converged state (device.psi/n/p are restored before the
    retry -- solve_bias mutates them even on failure, so retrying
    in place would warm-start the next attempt from a divergent
    iterate rather than a real solution).  Raises RuntimeError, never
    silently stops or returns as if converged, if the step shrinks
    below min_step without success.

    Returns a list of {"V", "J", "spread"} records, one per accepted
    step, in ramp order (v_start is NOT included).
    """
    opts = opts or NewtonOptions()
    if device.psi is None:
        device.solve_equilibrium(opts)

    def bias_at(v):
        return [v, other_bias] if terminal == 0 else [other_bias, v]

    direction = 1.0 if v_end >= v_start else -1.0
    step = abs(step0) * direction
    min_step = abs(min_step) if min_step is not None else abs(step0) / 64.0
    max_step = abs(max_step) if max_step is not None else abs(step0) * 8.0

    V = v_start
    records = []
    while abs(v_end - V) > 1e-12:
        if abs(step) > abs(v_end - V):
            step = (v_end - V)
        V_try = V + step

        psi0, n0, p0 = device.psi.copy(), device.n.copy(), device.p.copy()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            device.solve_bias(bias_at(V_try), opts)

        if device.last_converged:
            V = V_try
            j, spread = device.current_density()
            records.append({"V": V, "J": j, "spread": spread})
            if verbose:
                print(f"  [adaptive] V={V:+.4f}  J={j:+.4e}  step={step:+.4f}")
            if abs(step) < max_step:
                step = np.sign(step) * min(abs(step) * growth, max_step)
        else:
            device.psi, device.n, device.p = psi0, n0, p0
            step *= shrink
            if abs(step) < min_step:
                raise RuntimeError(
                    f"adaptive_bias_sweep stalled at V={V:.4f} approaching "
                    f"V={V_try:.4f}: step shrank below min_step={min_step:.2e} "
                    f"without Newton convergence")
            if verbose:
                print(f"  [adaptive] backoff at V_try={V_try:+.4f}, "
                      f"new step={step:+.4f}")
    return records


def _bordered_corrector(device, u_pred, V_pred, u_prev, V_prev, t_u, t_V,
                         ds, c_vec, bc_at, opts, tol, max_iter):
    """One pseudo-arclength corrector: Newton on the bordered system

        [ F(u, V)                              ]   = 0
        [ t_u.(u - u_prev) + t_V(V - V_prev) - ds ]

    built directly as a (3N+1)x(3N+1) sparse system each iteration and
    solved with scipy's direct sparse solver (this milestone's problem
    sizes are the same 1D device sizes the rest of M15/M22 already use
    spsolve for -- correctness first, no distributed/iterative solve
    attempted here).

    Convergence is judged the SAME way Device1D's own Newton loop judges
    it -- by the size of the UPDATE (max|dpsi|, max relative |dn|/n,
    |dp|/p), not by the raw residual norm.  F mixes a Poisson row and
    two continuity rows whose natural scaled magnitudes differ by many
    orders of magnitude, so a single absolute-residual threshold is not
    discriminating: an early version of this corrector used exactly
    that and reported "converged" after 0-2 iterations at points whose
    actual terminal current was 4-5 orders of magnitude off a plain
    voltage-controlled solve at the same bias.

    Backtracking (2-norm merit reduction on the FULL bordered residual,
    including the arc-length row) mirrors solve_bias's own II
    backtracking: with a stiff coupled term active, a full Newton step
    is frequently a non-descent direction, and an undamped corrector
    can take far more iterations than the same problem needs with
    damping, or fail to converge within max_iter at all (measured: a
    ds this small already needed 29/54/76 GROWING iterations across
    successive undamped steps near a stiff coupled term, before this
    was added).
    """
    u, V = u_pred.copy(), V_pred
    for it in range(max_iter):
        psi, n, p = _unpack(u)
        bc = bc_at(V)
        F, J, Jn, Jp = device._residual_jacobian(psi, n, p, bc)
        Narc = float(np.dot(t_u, u - u_prev) + t_V * (V - V_prev) - ds)
        resid = np.concatenate([F, [Narc]])
        base = 0.5 * float(np.dot(resid, resid))

        top = sp.hstack([J, sp.csr_matrix(c_vec.reshape(-1, 1))],
                         format="csr")
        bottom = sp.hstack([sp.csr_matrix(t_u.reshape(1, -1)),
                             sp.csr_matrix([[t_V]])], format="csr")
        A = sp.vstack([top, bottom], format="csc")
        delta = spsolve(A, -resid)
        du_full, dV_full = delta[:-1], delta[-1]

        dpsi_full = np.clip(du_full[0::3], -opts.max_dpsi, opts.max_dpsi)
        dn_full, dp_full = du_full[1::3], du_full[2::3]

        lam = 1.0
        for _ in range(40):
            psi_t = psi + lam * dpsi_full
            n_t = np.clip(n + lam * dn_full, 0.1 * n, 10.0 * n)
            p_t = np.clip(p + lam * dp_full, 0.1 * p, 10.0 * p)
            V_t = V + lam * dV_full
            Narc_t = float(np.dot(t_u, _pack(psi_t, n_t, p_t) - u_prev)
                           + t_V * (V_t - V_prev) - ds)
            Ft, *_ = device._residual_jacobian(psi_t, n_t, p_t, bc_at(V_t))
            resid_t = np.concatenate([Ft, [Narc_t]])
            merit_t = 0.5 * float(np.dot(resid_t, resid_t))
            if np.isfinite(merit_t) and merit_t <= base * (1.0 - 1e-4 * lam):
                break
            lam *= 0.5
        else:
            lam = 0.0

        n_old, p_old = n, p
        psi_new = psi + lam * dpsi_full
        n_new = np.clip(n + lam * dn_full, 0.1 * n, 10.0 * n)
        p_new = np.clip(p + lam * dp_full, 0.1 * p, 10.0 * p)
        V_new = V + lam * dV_full

        rel_n = np.abs(n_new / np.maximum(n_old, 1e-300) - 1.0).max()
        rel_p = np.abs(p_new / np.maximum(p_old, 1e-300) - 1.0).max()
        # err uses the UNSCALED (lam=1) step, like Device1D's own Newton
        # loop: if backtracking exhausts to lam=0, the ACTUAL movement is
        # zero and would spuriously look "converged" against a tolerance,
        # even though nothing happened and the true update the solver
        # wanted to take was large.
        err = max(float(np.abs(dpsi_full).max()), float(rel_n),
                  float(rel_p), float(abs(dV_full)))
        u = _pack(psi_new, n_new, p_new)
        V = V_new
        if err < tol:
            psi_f, n_f, p_f = _unpack(u)
            _, _, Jn, Jp = device._residual_jacobian(psi_f, n_f, p_f,
                                                       bc_at(V))
            return u, V, True, it + 1, (Jn, Jp)
    return u, V, False, max_iter, None


def _bordered_corrector_staged(device, u_pred, V_pred, u_prev, V_prev, t_u,
                                t_V, ds, c_vec, bc_at, opts, tol, max_iter,
                                strength_stages, strength_attr):
    """Run _bordered_corrector once per entry in strength_stages, ramping
    a generation-strength attribute on `device` from weak to full and
    warm-starting each stage from the previous stage's converged point.

    This is the arc-length-continuation analogue of Device1D.solve_bias's
    own generation-strength ladder (device.py's _II_STAGES): it exists
    because arc_length_sweep's corrector calls device._residual_jacobian
    directly, so it never goes through solve_bias's ladder at all.
    Without it, a stiff coupled term (e.g. M15's avalanche generation)
    is applied at FULL strength from the corrector's very first
    iteration at every arc-length step -- including ones far from
    wherever the ladder is actually needed -- which is exactly what
    stalled the first attempt at composing arc-length continuation with
    the coupled impact-ionization Jacobian (it stalled at a trivial
    bias, nowhere near the avalanche fold it was meant to trace through).

    If ANY stage fails to converge, the WHOLE attempt is reported as
    failed (so arc_length_sweep halves ds and retries) -- a partially-
    ramped intermediate state is never accepted as if it were the true,
    full-strength solution.  `device`'s strength attribute is always
    restored to the ladder's LAST (nominally full-strength) value
    before returning, success or failure, so a failed attempt cannot
    leave a stale partial-strength value for whatever call comes next
    (the next retry, the next accepted step's bookkeeping, or code
    outside this driver entirely).
    """
    u, V = u_pred, V_pred
    total_iters = 0
    ok = True
    jn_jp = None
    try:
        for stage in strength_stages:
            setattr(device, strength_attr, stage)
            u, V, converged, n_iter, jn_jp = _bordered_corrector(
                device, u, V, u_prev, V_prev, t_u, t_V, ds, c_vec, bc_at,
                opts, tol, max_iter)
            total_iters += n_iter
            if not converged:
                ok = False
                break
    finally:
        setattr(device, strength_attr, strength_stages[-1])
    return u, V, ok, total_iters, (jn_jp if ok else None)


def arc_length_sweep(device, v_start, v_end, ds0, opts=None, *,
                      terminal=0, other_bias=0.0, ds_min=None, ds_max=None,
                      max_steps=2000, corrector_tol=1e-8,
                      corrector_max_iter=30, seed_step=None, verbose=False,
                      strength_stages=None, strength_attr="_ii_strength"):
    """Trace device's (state, bias) solution branch by arc length.

    Unlike adaptive_bias_sweep, V is NOT guaranteed monotone along the
    returned records -- tracing THROUGH a fold is the point.  Stops
    when the traced V reaches v_end in the original direction, or after
    max_steps (a warning is issued, not silently treated as success).
    Raises RuntimeError if ds shrinks below ds_min without a converged
    corrector step.

    strength_stages: optional sequence of floats (e.g. device.py's
    _II_STAGES) ramping a generation-strength attribute on `device`
    (named by `strength_attr`, default "_ii_strength") from weak to
    full BEFORE each arc-length step's corrector solves at full
    strength.  Needed for any stiff coupled term (M15's avalanche
    generation is the motivating case) whose OWN Newton robustness
    depends on a strength ramp -- this corrector calls
    device._residual_jacobian directly, bypassing solve_bias's ladder
    entirely, so without this parameter a stiff term is applied at full
    strength from the very first iterate of every arc-length step.
    None (the default) skips staging and solves directly at whatever
    strength `device` is already set to -- the original, unramped
    behavior, unchanged for callers that don't need it.

    Returns a list of records in traced order:
        {"V", "J", "spread", "ds", "psi", "n", "p"}
    """
    opts = opts or NewtonOptions()
    if device.psi is None:
        device.solve_equilibrium(opts)

    VT = device.VT
    N = device.N
    direction = 1.0 if v_end >= v_start else -1.0

    def bias_at(v):
        return [v, other_bias] if terminal == 0 else [other_bias, v]

    def bc_at(v):
        return device._contact_values(bias_at(v))

    c_vec = np.zeros(3 * N)
    c_vec[0 if terminal == 0 else 3 * (N - 1)] = -1.0 / VT

    # Seed the initial tangent with two ordinary (voltage-controlled)
    # Newton solves -- robust far from any fold, which the starting
    # point always is by construction (a fold is what we're tracing
    # TOWARD, not starting from).
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        device.solve_bias(bias_at(v_start), opts)
    if not device.last_converged:
        raise RuntimeError(
            f"arc_length_sweep: could not seed the branch at V={v_start}")
    V0 = v_start
    u0 = _pack(device.psi, device.n, device.p)

    eps_v = abs(seed_step) if seed_step else min(abs(ds0) * 0.1, 0.5)
    V1 = V0 + direction * eps_v
    ok = False
    for _ in range(6):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            device.solve_bias(bias_at(V1), opts)
        if device.last_converged:
            ok = True
            break
        eps_v *= 0.5
        V1 = V0 + direction * eps_v
    if not ok:
        raise RuntimeError(
            f"arc_length_sweep: could not seed the initial tangent near "
            f"V={v_start}")
    u1 = _pack(device.psi, device.n, device.p)

    # Weighted arclength: the tangent/constraint metric only sees the
    # psi slots and V, not n/p.  Scaled densities span many orders of
    # magnitude across a device (contact-adjacent nodes O(1), depletion
    # nodes down to 1e-20 or smaller) -- an unweighted Euclidean metric
    # on the raw state vector is dominated by whichever node happens to
    # have the largest ABSOLUTE density swing, which has nothing to do
    # with the branch's actual shape, and makes the tangent numerically
    # meaningless (verified: it drove the corrector backward and then
    # into stalls immediately).  A RELATIVE-density weighting (1/n_i)
    # was tried as a refinement and made things WORSE -- it let whatever
    # node has the smallest (near-zero, depletion-region) density
    # dominate instead, stalling even the trivial near-equilibrium seed
    # step.  psi is smooth, O(1-100) everywhere, and is exactly the
    # variable that tracks the band-bending/depletion width a fold in
    # the I-V curve is about.  Restricting the METRIC to psi+V does not
    # restrict what the corrector solves -- F(u,V)=0 is still the full
    # coupled system every iteration; only how a step LENGTH is
    # measured changes.
    metric_mask = np.zeros(3 * N + 1, dtype=bool)
    metric_mask[0:3 * N:3] = True   # psi slots
    metric_mask[-1] = True          # V

    def _tangent_from(u_a, V_a, u_b, V_b):
        raw = np.concatenate([u_b - u_a, [V_b - V_a]])
        raw = raw * metric_mask
        nrm = np.linalg.norm(raw)
        return (raw / nrm, nrm) if nrm > 1e-300 else (None, 0.0)

    t_full, t_norm = _tangent_from(u0, V0, u1, V1)
    if t_full is None:
        raise RuntimeError("arc_length_sweep: degenerate initial tangent")
    t_u, t_V = t_full[:-1], t_full[-1]

    def _record(u, V):
        psi, n, p = _unpack(u)
        bc = bc_at(V)
        _, _, Jn, Jp = device._residual_jacobian(psi, n, p, bc)
        device.psi, device.n, device.p = psi, n, p
        device.Jn, device.Jp = Jn * device.J0, Jp * device.J0
        j, spread = device.current_density()
        return {"V": V, "J": j, "spread": spread,
                "psi": psi.copy(), "n": n.copy(), "p": p.copy()}

    records = [_record(u0, V0), _record(u1, V1)]

    u_prev, V_prev = u1, V1
    # ds is a magnitude, always positive: the tangent (t_u, t_V) already
    # encodes travel direction (its V-component has the same sign as
    # `direction` by construction of the seed secant), so signing ds by
    # `direction` on top of that would double-apply the direction and
    # send the predictor the WRONG way whenever direction is negative.
    ds = abs(ds0)
    ds_min = abs(ds_min) if ds_min is not None else abs(ds0) / 64.0
    ds_max = abs(ds_max) if ds_max is not None else abs(ds0) * 8.0
    reached = False

    for step_count in range(max_steps):
        u_pred = u_prev + ds * t_u
        V_pred = V_prev + ds * t_V

        if strength_stages is not None:
            u_c, V_c, converged, n_iter, _ = _bordered_corrector_staged(
                device, u_pred, V_pred, u_prev, V_prev, t_u, t_V, ds, c_vec,
                bc_at, opts, corrector_tol, corrector_max_iter,
                strength_stages, strength_attr)
        else:
            u_c, V_c, converged, n_iter, _ = _bordered_corrector(
                device, u_pred, V_pred, u_prev, V_prev, t_u, t_V, ds, c_vec,
                bc_at, opts, corrector_tol, corrector_max_iter)

        if not converged:
            ds *= 0.5
            if abs(ds) < ds_min:
                raise ArcLengthStalled(
                    f"arc_length_sweep stalled near V={V_prev:.4f}: ds "
                    f"shrank below ds_min={ds_min:.2e} without corrector "
                    f"convergence", last_V=V_prev, last_records=records)
            continue

        new_t_full, new_t_norm = _tangent_from(u_prev, V_prev, u_c, V_c)
        if new_t_full is not None:
            t_u, t_V = new_t_full[:-1], new_t_full[-1]

        rec = _record(u_c, V_c)
        rec["ds"] = ds
        records.append(rec)
        if verbose:
            print(f"  [arclen] step={step_count:4d}  V={V_c:+.4f}  "
                  f"J={rec['J']:+.4e}  ds={ds:+.4f}  iters={n_iter}")

        u_prev, V_prev = u_c, V_c
        # n_iter is a SUM across every strength stage when staging is on
        # (device.py's own ladder is 9 stages by default), so the growth
        # threshold must scale with the number of stages -- otherwise a
        # step that converged easily at EVERY stage never looks "easy"
        # by the unstaged threshold and ds never grows.
        n_stages = len(strength_stages) if strength_stages is not None else 1
        if n_iter <= n_stages * max(3, corrector_max_iter // 4):
            ds = min(ds * 1.5, ds_max)

        if (direction > 0 and V_c >= v_end) or (direction < 0 and V_c <= v_end):
            reached = True
            break

    if not reached:
        warnings.warn(
            f"arc_length_sweep hit max_steps={max_steps} before reaching "
            f"V={v_end} (last traced V={V_prev:.4f})")
    return records
