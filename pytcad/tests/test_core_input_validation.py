"""Malformed input to a compiled kernel must RAISE, never crash.

tcad/base/errors.hpp promises that every kernel taking connectivity
validates it once, up front, and raises IndexOutOfRange (-> IndexError)
rather than dereferencing out of bounds.  Before M43 phase 4 the
pure-Python reference path gave that for free (numpy fancy indexing);
once the fallback was removed, most kernels were found (2026-09-23,
under ASan/UBSan) to SEGV, overflow the heap, or divide by zero instead
-- taking the whole interpreter down with them.

Each case runs in a SUBPROCESS: a regression here is a crash, and a
crash in-process would kill the pytest worker and hide which kernel
caused it.  The child prints the exception class name it caught; the
test asserts both a clean exit and the expected class.
"""
import os
import subprocess
import sys
import textwrap

import pytest

from pytcad import _accel

pytestmark = pytest.mark.skipif(
    not _accel.HAVE_ACCEL, reason="compiled extension not built")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CHILD = textwrap.dedent("""
    import sys
    import numpy as np
    from pytcad import _core as c

    nodes = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1.]])
    i64 = lambda a: np.array(a, dtype=np.int64)
    f = lambda a: np.array(a, dtype=float)
    BIG, NEG = 99999, -1
    one = f([1.0])
    e0 = i64([0])

    def thermal(shape, T, dV, h, ke):
        n = len(T)
        return c.thermal_grid_residual_jacobian(
            i64(shape), f(T), f([0.0] * n), 300.0, f(dV), f(h), f(ke),
            f([0.0] * len(ke)), i64([0] * 2 * len(shape)),
            f([1.0] * 2 * len(shape)))

    def dg(kR, n_edges=(1, 0)):
        N = 2
        o = f([1, 1])
        return c.dg_grid_lambda_rows(
            N, i64(n_edges), i64([0]), i64([kR]), one, f([1] * 4),
            o, o, o, o, o, o, np.zeros(N, np.uint8), 1.0)

    def d3d_cont(fn, short):
        x = one
        return fn(e0, e0, x, short, x, x, e0, e0, x, x, x, x,
                  e0, e0, x, x, x, x)

    CASES = {
        "stencil2d_big": lambda: c.build_stencil2d(nodes, i64([[0, 1, BIG]]), 0.0),
        "stencil2d_neg": lambda: c.build_stencil2d(nodes, i64([[0, 1, NEG]]), 0.0),
        "stencil3d_big": lambda: c.build_stencil3d(nodes, i64([[0, 1, 2, BIG]]), 0.0),
        "flux2d_tri": lambda: c.build_flux_geometry2d(
            nodes, i64([[0, 1, BIG]]), i64([[0, 1]])),
        "flux2d_edge": lambda: c.build_flux_geometry2d(
            nodes, i64([[0, 1, 2]]), i64([[0, BIG]])),
        "flux3d_tet": lambda: c.build_flux_geometry3d(
            nodes, i64([[0, 1, 2, BIG]]), i64([[0, 1]])),
        "flux3d_edge": lambda: c.build_flux_geometry3d(
            nodes, i64([[0, 1, 2, 3]]), i64([[0, BIG]])),
        "faces3d": lambda: c.boundary_face_node_weights3d(nodes, i64([[0, 1, BIG]])),
        "u3d_eq": lambda: c.unstructured3d_residual_jacobian_equilibrium(
            f([1, 1]), f([1, 1]), f([0, 0]), f([1, 1]), e0, i64([BIG]), one, one),
        "u3d_coupled": lambda: c.unstructured3d_residual_jacobian_coupled(
            f([1, 1]), f([1, 1]), f([0, 0]), f([1, 1]), i64([NEG]), e0,
            one, one, one, one, one, one, one, one, one, 1.0,
            f([1, 1]), f([1, 1]), 1.0, 1.0, True, False, 0.0, 0.0),
        "d3d_flux_len": lambda: c.device3d_poisson_flux_row(
            e0, e0, f([]), e0, e0, one, e0, e0, one),
        "d3d_electron_len": lambda: d3d_cont(c.device3d_electron_continuity, f([])),
        "d3d_hole_len": lambda: d3d_cont(c.device3d_hole_continuity, f([])),
        "d3d_diag_ion_len": lambda: c.device3d_base_diagonal(
            3, f([1, 1, 1]), True, f([]), f([]), f([1, 1, 1]), f([1, 1, 1])),
        "dg_index": lambda: dg(BIG),
        "dg_neg_edges": lambda: dg(1, n_edges=(2, -1)),
        "thermal_concat_len": lambda: thermal([3, 3], [300] * 9, [], [], []),
        "thermal_zero_axis": lambda: thermal([0, 3], [], [1] * 3, [1] * 2, []),
    }

    try:
        CASES[sys.argv[1]]()
    except Exception as exc:
        print(type(exc).__name__)
    else:
        print("NO_ERROR")
""")

# Out-of-range node indices -> IndexError (numpy's class for the same
# mistake on the reference path); inconsistent lengths/shapes -> ValueError.
EXPECTED = {
    "stencil2d_big": "IndexError",
    "stencil2d_neg": "IndexError",
    "stencil3d_big": "IndexError",
    "flux2d_tri": "IndexError",
    "flux2d_edge": "IndexError",
    "flux3d_tet": "IndexError",
    "flux3d_edge": "IndexError",
    "faces3d": "IndexError",
    "u3d_eq": "IndexError",
    "u3d_coupled": "IndexError",
    "d3d_flux_len": "ValueError",
    "d3d_electron_len": "ValueError",
    "d3d_hole_len": "ValueError",
    "d3d_diag_ion_len": "ValueError",
    "dg_index": "IndexError",
    "dg_neg_edges": "ValueError",
    "thermal_concat_len": "ValueError",
    "thermal_zero_axis": "ValueError",
}


@pytest.mark.parametrize("case", sorted(EXPECTED))
def test_malformed_input_raises_not_crashes(case):
    out = subprocess.run([sys.executable, "-c", _CHILD, case],
                         capture_output=True, text=True, cwd=_ROOT)
    assert out.returncode == 0, (
        f"{case}: child exited {out.returncode} (crash, not an exception)\n"
        f"{out.stderr[-2000:]}")
    assert out.stdout.strip() == EXPECTED[case], out.stdout + out.stderr[-2000:]
