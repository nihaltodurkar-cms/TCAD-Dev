"""Re-measure P4's two diffusion-loop kernels through a reproducible
harness (2026-09-10) -- the item M32-BENCHMARK-PLAN.md section 7 and
M31-CPP-ARCHITECTURE-PLAN.md's P4 table flagged "still owed":
`p2_p3b_p4_remeasure.py` covered the three per-triangle AMR indicators
but explicitly did not cover `process.diffuse_numeric` /
`ted.diffuse_with_defects`, since a timestep loop is a different shape
(wall-clock time for one full run, not a per-item throughput rate).

METHODOLOGY, MATCHING THE ORIGINAL HAND-TAKEN CLAIM
----------------------------------------------------
The original claim (M31-CPP-ARCHITECTURE-PLAN.md's P4 section) is
"n=4000, t_s=1800 s": 0.325 s -> 0.098 s (3.3x) for diffuse_numeric,
24.6 s -> 6.07 s (4.1x) for diffuse_with_defects. Reproduced here with
the same grid size and anneal time, on the same implant-shaped starting
profile `tests/test_accel_parity.py`'s own bit-identity gates use
(`_diffusion_case`, imported directly rather than reimplemented) scaled
to n=4000. Warm (first call discarded), best of 3,
`time.perf_counter()`, `PYTCAD_ACCEL` toggled in-process between calls
on the SAME profile (copied before each call, since both kernels mutate
their own copy but the caller's `t_s`-scale step count must stay
identical between the two backends for the timings to be comparable).
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_accel_parity import _diffusion_case   # noqa: E402
from pytcad import process as _proc                    # noqa: E402
from pytcad import ted as _ted                          # noqa: E402


def _with_accel(value, fn, *a, **kw):
    old = os.environ.get("PYTCAD_ACCEL")
    os.environ["PYTCAD_ACCEL"] = value
    try:
        return fn(*a, **kw)
    finally:
        if old is None:
            os.environ.pop("PYTCAD_ACCEL", None)
        else:
            os.environ["PYTCAD_ACCEL"] = old


def _timeit(fn, repeats=3):
    fn()                               # warm
    best = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        dt = time.perf_counter() - t0
        if best is None or dt < best:
            best = dt
    return best


def measure_diffuse_numeric(n=4000, t_s=1800.0, repeats=3):
    x, C = _diffusion_case(n=n)

    def run(accel):
        return _timeit(lambda: _with_accel(
            accel, _proc.diffuse_numeric, x, C, "B", 1000.0, t_s), repeats)

    ref = run("0")
    cpp = run("1")
    return dict(ref_s=ref, cpp_s=cpp, speedup=ref / cpp)


def measure_diffuse_with_defects(n=4000, t_s=1800.0, repeats=3):
    x, C = _diffusion_case(n=n)
    kw = dict(n_total=None, ted_S0=25.0, ted_tau_s=8.0, oed_boost=0.4)

    def run(accel):
        return _timeit(lambda: _with_accel(
            accel, _ted.diffuse_with_defects, x, C, "B", 1000.0, t_s,
            **kw), repeats)

    ref = run("0")
    cpp = run("1")
    return dict(ref_s=ref, cpp_s=cpp, speedup=ref / cpp)


def main():
    print(f"## P4 -- diffusion-loop wall-clock time (n=4000, t_s=1800 s, "
          f"warm, best of 3)\n")
    print("| kernel | reference (Python) | compiled (C++) | speedup |")
    print("|---|---|---|---|")

    r = measure_diffuse_numeric()
    print(f"| `process.diffuse_numeric` | {r['ref_s']:.3f} s | "
          f"{r['cpp_s']:.3f} s | {r['speedup']:.1f}x |")

    r = measure_diffuse_with_defects()
    print(f"| `ted.diffuse_with_defects` | {r['ref_s']:.3f} s | "
          f"{r['cpp_s']:.3f} s | {r['speedup']:.1f}x |")


if __name__ == "__main__":
    main()
