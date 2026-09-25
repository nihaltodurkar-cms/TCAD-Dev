"""M47 follow-up (2026-09-24): did replacing the device3d/unstructured3d
bindings' per-call `to_vec` input copies with zero-copy views
(core/include/tcad/base/view.hpp) and releasing the GIL change assembly
cost?

Measures ASSEMBLY ms/call (benchmarks/instrument.py's own
`_residual_jacobian*` wrapper -- the same one BASELINE.md's assembly
column comes from) on the two cases that reach the COUPLED compiled
kernels, where the copies were:

  * B9  full -- unstructured_dd3d coupled kernel (M47 Slice 1);
  * S3D full -- Device3D coupled kernels (M47 Slice 2a), via
    benchmarks/preconditioners.py's study fixture.

Per call rather than per solve, so a different Newton iteration count
between two builds cannot masquerade as an assembly change. Best of
`--repeats` whole solves (default 5). Run it once per build and compare;
it does not know which build it is measuring.

    OPENBLAS_NUM_THREADS=1 python benchmarks/m47_views_measure.py
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from benchmarks.cases import _b9          # noqa: E402
from benchmarks.instrument import instrumented   # noqa: E402
from benchmarks.preconditioners import _s3d_coupled   # noqa: E402


def _per_call(build, size):
    dev, run = build(size)
    with instrumented(device=dev) as probe:
        run()
    return probe.assembly_s / max(probe.assembly_calls, 1), probe.assembly_calls


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--size", default="full", choices=("quick", "full"))
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args(argv)

    print("| case | size | assembly calls | best ms/call | all runs ms/call |")
    print("|---|---|---|---|---|")
    for label, build in (("B9 unstructured coupled", _b9),
                         ("S3D structured coupled", _s3d_coupled)):
        runs = [_per_call(build, args.size) for _ in range(args.repeats)]
        ms = [r[0] * 1e3 for r in runs]
        print(f"| {label} | {args.size} | {runs[0][1]} | {min(ms):.3f} | "
              f"{', '.join(f'{m:.3f}' for m in ms)} |", flush=True)


if __name__ == "__main__":
    main()
