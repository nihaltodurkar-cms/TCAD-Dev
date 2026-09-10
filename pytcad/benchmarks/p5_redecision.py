"""M31 P5 re-decision measurement (2026-09-10).

P5's own plan (`M31-P5-ASSEMBLY-NEWTON-PLAN.md` section 6) measured
assembly at 1.5-3.5% of an unstructured solve, using the DEFAULT
(`linsolve="direct"`) dashboard rows. M31 P5-1 (all 5 phases, LANDED
same day) makes `linsolve="auto"` reachable, and Phase A's own numbers
say it changes the total dramatically for B4 and B9. Since assembly's
ABSOLUTE cost does not move when the linear solve gets faster, its
SHARE of the total necessarily rises -- this script measures that rise
for real, through the M32 harness (`instrument.py`/`harness.py`),
rather than by hand-extrapolating the two numbers together, per
`Architecture_Master_Plan.md` section 36.

`benchmarks/cases.py`'s `_b4`/`_b8`/`_b9` gained an OPTIONAL `opts=`
parameter for exactly this (default `None` reproduces the dashboard's
own row bit-for-bit -- confirmed by `tests/test_m32_benchmarks.py`
still passing unchanged). This script is a one-off study, in the same
spirit as `preconditioners.py` -- it does not add a permanent dashboard
column, because `linsolve="auto"` is an opt-in configuration (M31 P5-1
Phase E chose E-opt-in: the default stays `direct`), not the case's
own default behavior.
"""
from __future__ import annotations

import sys

from pytcad.device import NewtonOptions
from .cases import get
from .instrument import instrumented

CASES = ["B4", "B8", "B9"]


def measure(name, size="full", repeats=3):
    case = get(name)
    opts = NewtonOptions(linsolve="auto")

    # Untraced repeats only (tracemalloc inflates timings unevenly --
    # see instrument.py's own "MEMORY COSTS TIME" section); best-of.
    best = None
    all_times = []
    device = None
    for _ in range(repeats):
        device, run = case.build(size, opts=opts)
        with instrumented(device, memory=False) as probe:
            run()
        all_times.append(probe.total_s)
        if best is None or probe.total_s < best.total_s:
            best = probe
    # Device-based cases (B4) expose which concrete method "auto"
    # resolved to; module-level cases (B8/B9) don't return it through
    # this thin wrapper (their own opts= plumbing is what
    # test_m31_p51_phase_d.py already gates directly) -- None here
    # means "not observed by this script", not "resolved to nothing".
    auto_method = getattr(device, "last_auto_method", None)
    return best, all_times, auto_method


def main():
    print(f"{'case':<4} {'assembly_s':>11} {'linsolve_s':>11} "
         f"{'total_s':>9} {'assembly %':>11}  auto_method  all_repeats")
    for name in CASES:
        probe, all_times, auto_method = measure(name, repeats=5)
        pct = 100.0 * probe.assembly_s / probe.total_s if probe.total_s else float("nan")
        times_str = ", ".join(f"{t:.3f}" for t in all_times)
        print(f"{name:<4} {probe.assembly_s:11.4f} {probe.linsolve_s:11.4f} "
             f"{probe.total_s:9.4f} {pct:10.2f}%  {str(auto_method):<11} [{times_str}]")
        sys.stderr.write(f"[{name}] assembly_calls={probe.assembly_calls} "
                         f"linsolve_calls={probe.linsolve_calls} "
                         f"dof={probe.dof} nnz={probe.nnz}\n")


if __name__ == "__main__":
    main()
