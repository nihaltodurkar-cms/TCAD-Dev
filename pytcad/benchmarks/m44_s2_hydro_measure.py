"""M44 Slice 2 -- decide whether Models.energy_balance's 1D assembly
justifies a C++ compile, per CLAUDE.md's M32 rule ("a performance
number that did not come from a benchmark run does not belong in a
plan doc"). Same shape as `p4_diffusion_remeasure.py`: a one-off
decision script using the harness's own reproducible timing
methodology, not a permanent B1-B9 dashboard case (this measurement's
job is a yes/no architectural call, not a tracked capability).

METHODOLOGY: warm run discarded, best of 5, `time.perf_counter()`,
comparing `solve_bias` wall time with `Models(energy_balance=True)`
against the plain `Models()` baseline on the SAME mesh/doping/bias,
plus a breakdown isolating the NEW Tn-block assembly cost (the
Python `for i in range(1, N-1)` loop in `_residual_jacobian`) from the
linear-solve cost increase (3*N -> 4*N unknowns) -- the plan's own
stated expectation (see M44-HYDRODYNAMIC-PLAN.md Slice 2) is that
assembly is O(N) and the whole thing stays solve-dominated, so a
compile is likely NOT justified at 1D scale; this is what actually
checks that expectation rather than assuming it.
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pytcad.device import Device1D, Models, NewtonOptions   # noqa: E402


def _diode(N):
    x = np.linspace(0.0, 1e-4, N)
    doping = np.where(x < 0.5e-4, 1e17, -1e17)
    return x, doping


def _timeit(fn, repeats=5):
    fn()                               # warm
    best = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        dt = time.perf_counter() - t0
        if best is None or dt < best:
            best = dt
    return best


def _solve(N, energy_balance, repeats=5):
    x, doping = _diode(N)

    def run():
        dev = Device1D(x, doping, models=Models(energy_balance=energy_balance))
        opts = NewtonOptions()
        dev.solve_equilibrium(opts)
        dev.solve_bias([0.0, 0.6], opts)
        return dev

    dev = run()
    assert dev.last_converged, f"N={N} energy_balance={energy_balance} did not converge"
    return _timeit(run, repeats)


def _assembly_only(N, repeats=5):
    """Isolate the NEW Tn-block assembly loop's own cost: one
    `_residual_jacobian` call with theta, vs one without, on the same
    converged state -- the part of solve_bias's per-iterate cost that
    is genuinely new Python code, separate from the linear solve."""
    x, doping = _diode(N)
    dev = Device1D(x, doping, models=Models(energy_balance=True))
    opts = NewtonOptions()
    dev.solve_equilibrium(opts)
    dev.solve_bias([0.0, 0.6], opts)
    psi, n, p = dev.psi, dev.n, dev.p
    bc = dev._contact_values([0.0, 0.6])
    theta = dev.Tn / dev.T
    n_lag = n.copy()
    Jn_lag = np.zeros(N - 1)
    Qheat_lag = np.zeros(N)

    t_off = _timeit(lambda: dev._residual_jacobian(psi, n, p, bc), repeats)
    t_on = _timeit(lambda: dev._residual_jacobian(
        psi, n, p, bc, theta=theta, n_lag=n_lag, Jn_lag=Jn_lag,
        Qheat_lag=Qheat_lag), repeats)
    return t_off, t_on


def main():
    print("## M44 Slice 2 -- energy_balance 1D wall-clock time "
          "(V=[0,0.6], warm, best of 5)\n")
    print("| N | off (s) | on (s) | overhead | assembly-only off (s) | "
          "assembly-only on (s) | assembly overhead |")
    print("|---|---|---|---|---|---|---|")
    for N in (41, 161, 641, 2561):
        t_off = _solve(N, False)
        t_on = _solve(N, True)
        a_off, a_on = _assembly_only(N)
        print(f"| {N} | {t_off:.4f} | {t_on:.4f} | {t_on / t_off:.2f}x | "
              f"{a_off:.6f} | {a_on:.6f} | {a_on / a_off:.2f}x |")


if __name__ == "__main__":
    main()
