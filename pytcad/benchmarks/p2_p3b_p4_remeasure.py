"""Re-measure P2/P3b/P4's headline numbers through a reproducible
harness (2026-09-10) -- M32-BENCHMARK-PLAN.md section 7's first open
item, "doubly owed" since the M32 harness itself was found inflating
timings before this date (see that section, and
`M31-P5-ASSEMBLY-NEWTON-PLAN.md` section 6.1 for the same class of
defect on the unstructured-DD path).

WHY THIS LIVES HERE AND NOT IN `cases.py`
--------------------------------------------
P2/P3b/P4's headline numbers are KERNEL-level (mesh-stencil throughput,
one Krylov-solve timing, AMR-indicator throughput) -- not device-level
solves, so they do not belong as `benchmarks/cases.py` B-rows (which
report `assembly_s`/`linsolve_s`/`total_s` for a whole Newton solve).
They ARE, however, exactly the numbers `tests/test_accel_parity.py`'s
`@pytest.mark.slow` throughput-floor gates already watch on every run
of the slow suite -- this script reuses those same fixture builders
(`tri_grid`/`tet_grid`/`_indicator_mesh`/`_fields`/`_device_jacobian`,
imported directly rather than reimplemented, so this measures the exact
same thing the gates protect) and reports the actual current numbers,
which the gates themselves do not print on a pass.

METHODOLOGY, MATCHING THE ORIGINAL HAND-TAKEN CLAIMS
-------------------------------------------------------
Warm (first call discarded), best of 3, `time.perf_counter()`. P2/P4
throughput toggles `PYTCAD_ACCEL` between calls in the SAME process
(the lever `_accel.use_accel()` reads per call -- confirmed directly by
`test_accel_parity.py`'s own G-A parity tests using the identical
technique) so reference and compiled rates come from one run, not two
separately-invoked processes that could drift apart in warm-up state.
P3b's comparison uses `_both_backends`'s own `monkeypatch`-free
equivalent (plain `os.environ` assignment) on the SAME 603-unknown
interleaved psi/n/p Jacobian the original claim was measured on.
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests.test_accel_parity import (          # noqa: E402
    tri_grid, tet_grid, _indicator_mesh, _fields, _device_jacobian)
from pytcad import unstructured_assembly as ua       # noqa: E402
from pytcad import unstructured_assembly3d as ua3    # noqa: E402
from pytcad import adapt_unstructured as _au         # noqa: E402
from pytcad import linsolve                          # noqa: E402
from pytcad import _accel                            # noqa: E402


def _rate(fn, n_items, repeats=3):
    fn()                              # warm
    best = 0.0
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        r = n_items / (time.perf_counter() - t0)
        best = max(best, r)
    return best


def _with_accel(value, fn, *a):
    old = os.environ.get("PYTCAD_ACCEL")
    os.environ["PYTCAD_ACCEL"] = value
    try:
        return fn(*a)
    finally:
        if old is None:
            os.environ.pop("PYTCAD_ACCEL", None)
        else:
            os.environ["PYTCAD_ACCEL"] = old


def measure_p2():
    rows = []

    nodes, tris = tri_grid(300)
    ref = _with_accel("0", _rate, lambda: ua.build_unstructured_stencil(nodes, tris), len(tris))
    cpp = _with_accel("1", _rate, lambda: ua.build_unstructured_stencil(nodes, tris), len(tris))
    rows.append(("build_unstructured_stencil (2D)", ref, cpp, len(tris)))

    P, tets = tet_grid(30)
    ref = _with_accel("0", _rate, lambda: ua3.build_unstructured_stencil3d(P, tets), len(tets))
    cpp = _with_accel("1", _rate, lambda: ua3.build_unstructured_stencil3d(P, tets), len(tets))
    rows.append(("build_unstructured_stencil3d", ref, cpp, len(tets)))

    P2, tets2 = tet_grid(22)
    e, _ = ua3.build_unstructured_stencil3d(P2, tets2)
    ref = _with_accel("0", _rate, lambda: ua3.build_edge_flux_geometry3d(P2, tets2, e), len(tets2))
    cpp = _with_accel("1", _rate, lambda: ua3.build_edge_flux_geometry3d(P2, tets2, e), len(tets2))
    rows.append(("build_edge_flux_geometry3d", ref, cpp, len(tets2)))

    return rows


def measure_p4():
    rows = []
    mesh = _indicator_mesh(n=200, jitter=0.0)
    psi, n, p, C = _fields(mesh)
    n_tri = len(mesh.triangles)

    for label, fn in [
        ("indicator_curvature_tri", lambda: _au.indicator_curvature_tri(mesh, psi)),
        ("indicator_log_density_tri", lambda: _au.indicator_log_density_tri(mesh, n, p)),
        ("debye_ratio_tri", lambda: _au.debye_ratio_tri(mesh, C)),
    ]:
        ref = _with_accel("0", _rate, fn, n_tri)
        cpp = _with_accel("1", _rate, fn, n_tri)
        rows.append((label, ref, cpp, n_tri))
    return rows


def measure_p3b(repeats=8):
    if not (_accel.have_petsc()):
        return None, "compiled extension has no PETSc -- skipped"
    try:
        import petsc4py  # noqa: F401
    except ImportError:
        return None, "petsc4py not installed -- skipped"

    J, rhs = _device_jacobian()
    kw = dict(rtol=1e-8, maxiter=500, block_size=3)

    def best_of(accel_value):
        old = os.environ.get("PYTCAD_ACCEL")
        os.environ["PYTCAD_ACCEL"] = accel_value
        try:
            x, info = linsolve.solve_linear(J, rhs, method="petsc", **kw)  # warm
            best = None
            for _ in range(repeats):
                t0 = time.perf_counter()
                x, info = linsolve.solve_linear(J, rhs, method="petsc", **kw)
                dt = time.perf_counter() - t0
                if best is None or dt < best:
                    best = dt
            return best, info["backend"], info["iterations"]
        finally:
            if old is None:
                os.environ.pop("PYTCAD_ACCEL", None)
            else:
                os.environ["PYTCAD_ACCEL"] = old

    cpp_t, cpp_backend, cpp_iters = best_of("1")
    py_t, py_backend, py_iters = best_of("0")
    assert cpp_backend == "cpp" and py_backend == "petsc4py", \
        f"expected cpp/petsc4py backends, got {cpp_backend}/{py_backend}"
    return dict(cpp_ms=cpp_t * 1e3, py_ms=py_t * 1e3,
               cpp_iters=cpp_iters, py_iters=py_iters,
               dof=J.shape[0]), None


def main():
    print("## P2 -- mesh-kernel throughput (warm, best of 3)\n")
    print("| kernel | reference (Python) | compiled (C++) | speedup | n |")
    print("|---|---|---|---|---|")
    for label, ref, cpp, n in measure_p2():
        print(f"| `{label}` | {ref/1e3:.0f}k/s | {cpp/1e6:.2f}M/s | "
             f"{cpp/ref:.0f}x | {n} |")

    print("\n## P4 -- AMR indicator throughput (warm, best of 3)\n")
    print("| kernel | reference (Python) | compiled (C++) | speedup | n |")
    print("|---|---|---|---|---|")
    for label, ref, cpp, n in measure_p4():
        print(f"| `{label}` | {ref/1e6:.2f}M tri/s | {cpp/1e6:.0f}M tri/s | "
             f"{cpp/ref:.0f}x | {n} |")

    print("\n## P3b -- PETSc backend timing, 603-unknown device Jacobian "
         "(warm, best of 8)\n")
    result, skip_reason = measure_p3b()
    if skip_reason:
        print(f"SKIPPED: {skip_reason}")
    else:
        print(f"| backend | time | iterations |")
        print(f"|---|---|---|")
        print(f"| cpp | {result['cpp_ms']:.2f} ms | {result['cpp_iters']} |")
        print(f"| petsc4py | {result['py_ms']:.2f} ms | {result['py_iters']} |")
        print(f"\ndof={result['dof']}")


if __name__ == "__main__":
    main()
