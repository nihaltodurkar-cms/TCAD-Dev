"""M47 Step 0 -- decide which 3D assembly path (structured device3d.py
vs unstructured unstructured_dd3d.py) gets ported to C++ first, per
CLAUDE.md's M32 rule ("a performance number that did not come from a
benchmark run does not belong in a plan doc"). Same shape as
`m44_s2_hydro_measure.py`: a one-off decision script using the
project's own reproducible instrumentation (`benchmarks/instrument.py`
-- the SAME wrapper that produced BASELINE.md's B4/B9 assembly_s
numbers), not a new permanent B1-B9 dashboard case.

METHODOLOGY: reuse the existing B4 (3D MOSFET, structured) and B9 (3D
unstructured DD) case builders from `benchmarks/cases.py` UNCHANGED --
these are already the project's own size-controlled, reproducible 3D
fixtures, so this script adds no new device/mesh construction, only
the side-by-side assembly-only comparison BASELINE.md's per-case table
never puts in one place. `instrument.instrumented()` patches
`_residual_jacobian` (structured, a bound device method) and
`_residual_jacobian_poisson3d`/`_residual_jacobian_dd3d` (unstructured,
module-level functions) transparently -- the exact split M31 P5's own
docstring says this instrumentation exists to produce. Warm run
discarded implicitly by the case's own equilibrium solve; each case
then runs ONE full solve under instrumentation (assembly_s is the SUM
over every Newton iterate's assembly call within that one solve, not a
single call -- comparable directly to BASELINE.md's own numbers, which
report the same sum).

Both "quick" and "full" sizes are run, per README.md's own two-size
discipline -- a single size would be exactly the "quoted forever, never
re-measured" number section 36 exists to prevent.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from benchmarks.cases import _b4, _b9   # noqa: E402
from benchmarks.instrument import instrumented   # noqa: E402


def _measure_structured(size):
    dev, run = _b4(size)
    with instrumented(device=dev) as probe:
        run()
    return probe


def _measure_unstructured(size):
    dev, run = _b9(size)   # dev is always None for B9 -- module-level assembly
    with instrumented(device=dev) as probe:
        run()
    return probe


def _row(label, size, probe):
    per_call = probe.assembly_s / probe.assembly_calls if probe.assembly_calls else float("nan")
    per_dof = probe.assembly_s / probe.dof if probe.dof else float("nan")
    print(f"| {label} | {size} | {probe.dof} | {probe.nnz} | "
          f"{probe.assembly_calls} | {probe.assembly_s:.4f} | "
          f"{per_call*1e3:.4f} | {per_dof*1e6:.4f} | "
          f"{probe.linsolve_s:.4f} | "
          f"{probe.assembly_s / (probe.assembly_s + probe.linsolve_s):.1%} |")
    return probe


def main():
    print("## M47 Step 0 -- structured (B4) vs unstructured (B9) 3D "
          "assembly-only wall time\n")
    print("Methodology: benchmarks/instrument.py's existing "
          "_residual_jacobian wrapper (same one BASELINE.md's assembly "
          "column comes from), one full solve per row, best-effort "
          "single run (this script does not repeat/take-best -- see "
          "notes below for why that is fine for an assembly-share "
          "decision, not a headline timing claim).\n")
    print("| case | size | DOF | NNZ | assembly calls | assembly_s (sum) | "
          "ms/call | us/DOF | linsolve_s | assembly share of (asm+solve) |")
    print("|---|---|---|---|---|---|---|---|---|---|")

    results = {}
    for size in ("quick", "full"):
        results[("structured", size)] = _row("B4 structured", size,
                                              _measure_structured(size))
        results[("unstructured", size)] = _row("B9 unstructured", size,
                                                _measure_unstructured(size))

    print("\n## Per-DOF ratio (unstructured / structured), same size\n")
    for size in ("quick", "full"):
        s = results[("structured", size)]
        u = results[("unstructured", size)]
        s_per_dof = s.assembly_s / s.dof
        u_per_dof = u.assembly_s / u.dof
        print(f"- {size}: structured {s_per_dof*1e6:.4f} us/DOF, "
              f"unstructured {u_per_dof*1e6:.4f} us/DOF, "
              f"ratio {u_per_dof / s_per_dof:.2f}x")


if __name__ == "__main__":
    main()
