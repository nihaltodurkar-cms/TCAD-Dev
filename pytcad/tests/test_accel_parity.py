"""Gate G-A: the compiled kernels must equal the Python reference EXACTLY.

`np.array_equal`, never `allclose`. That is the whole point of the
dual-path design: the Python bodies (`_<name>_py`) are kept forever as
the oracle, and a compiled kernel earns its place by reproducing them
bit for bit -- not by being close enough.

This is achievable because the numpy primitives these kernels use were
measured to be plain scalar arithmetic at these sizes (no BLAS dispatch)
before any C++ was written; see core/include/tcad/geom/simplex.hpp.

The gates in this file:
  G-A  outputs identical on structured, jittered, and real gmsh meshes
  G-C  identical exception TYPE and MESSAGE on degenerate/non-manifold input
  G-D  identical results at PYTCAD_NUM_THREADS in {1, 2, 4, 8}
  G-E  absolute throughput floors (marked slow)

Covering, in order: the mesh geometry kernels (P2), the two PETSc
solver backends (P3b), and the process/adaptivity kernels (P4).
"""
import os
import subprocess
import sys

import numpy as np
import pytest

from pytcad import _accel
from pytcad.errors import DegenerateMeshError
from pytcad import unstructured_assembly as ua
from pytcad import unstructured_assembly3d as ua3

pytestmark = pytest.mark.skipif(
    not _accel.HAVE_ACCEL, reason="compiled extension not built")

# The guard above asks whether the extension is BUILT (`HAVE_ACCEL` is an
# import-time constant). Most tests in this file are parity checks that
# set PYTCAD_ACCEL themselves via monkeypatch, so that is the right
# question for them. It is NOT the right question for the absolute
# throughput floors (G-E): those time whatever path the AMBIENT
# PYTCAD_ACCEL selects, and a floor calibrated on the compiled kernel is
# meaningless against the Python reference path.
#
# Found by actually running the owed `-m slow` battery both ways
# (2026-09-10): under `PYTCAD_ACCEL=0` on a machine where the extension
# IS built, `test_indicator_throughput_floor[curvature]` measured
# 2.54e5 tri/s against its 5.0e7 floor -- which is not a regression and
# not CPU contention, it is exactly the 0.27M tri/s PYTHON reference
# rate that test's own docstring records for that kernel. Same story for
# test_throughput_floor[flux3d]: 3.51e3/s against a 3.0e5 floor.
#
# `use_accel()` is the per-call reader of PYTCAD_ACCEL, and it RAISES
# when PYTCAD_ACCEL=1 with no extension -- so short-circuit on
# HAVE_ACCEL first rather than letting that raise at import time.
_ACCEL_ACTIVE = _accel.HAVE_ACCEL and _accel.use_accel()

needs_active_accel = pytest.mark.skipif(
    not _ACCEL_ACTIVE,
    reason="absolute throughput floors time the compiled path; "
           "PYTCAD_ACCEL=0 selects the Python reference path, against "
           "which these floors are meaningless by construction")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ----------------------------------------------------------------------
#  meshes
# ----------------------------------------------------------------------
def tri_grid(n, jitter=0.0, seed=0):
    rng = np.random.default_rng(seed)
    xs = np.linspace(0.0, 1.0, n)
    X, Y = np.meshgrid(xs, xs)
    if jitter:
        X = X + rng.normal(0.0, jitter / n, X.shape)
        Y = Y + rng.normal(0.0, jitter / n, Y.shape)
    nodes = np.column_stack([X.ravel(), Y.ravel(), np.zeros(n * n)])
    idx = np.arange(n * n).reshape(n, n)
    a, b = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel()
    c, d = idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
    tris = np.concatenate([np.column_stack([a, b, c]), np.column_stack([a, c, d])])
    return nodes, tris


def tet_grid(n, jitter=0.0, seed=1):
    rng = np.random.default_rng(seed)
    xs = np.linspace(0.0, 1.0, n)
    G = np.meshgrid(xs, xs, xs, indexing="ij")
    P = np.column_stack([g.ravel() for g in G])
    if jitter:
        P = P + rng.normal(0.0, jitter / n, P.shape)
    idx = np.arange(n ** 3).reshape(n, n, n)
    v = [idx[:-1, :-1, :-1], idx[1:, :-1, :-1], idx[1:, 1:, :-1], idx[:-1, 1:, :-1],
         idx[:-1, :-1, 1:], idx[1:, :-1, 1:], idx[1:, 1:, 1:], idx[:-1, 1:, 1:]]
    v = [a.ravel() for a in v]
    pat = [(0, 1, 3, 7), (0, 1, 7, 4), (1, 4, 5, 7),
           (1, 2, 3, 7), (1, 2, 7, 6), (1, 5, 6, 7)]
    tets = np.concatenate([np.column_stack([v[i] for i in p]) for p in pat])
    return P, tets


MESHES_2D = [("uniform", tri_grid(40)), ("jittered", tri_grid(40, 0.3, 7))]
MESHES_3D = [("uniform", tet_grid(9)), ("jittered", tet_grid(9, 0.25, 5))]


def assert_exact(name, got, ref):
    assert got.shape == ref.shape, f"{name}: shape {got.shape} != {ref.shape}"
    assert got.dtype == ref.dtype, f"{name}: dtype {got.dtype} != {ref.dtype}"
    if not np.array_equal(got, ref):
        d = np.abs(got.astype(float) - ref.astype(float))
        n = int(np.count_nonzero(got != ref))
        pytest.fail(f"{name}: NOT bit-identical -- {n}/{got.size} differ, "
                    f"max abs {d.max():.3e}")


# ----------------------------------------------------------------------
#  G-A: outputs
# ----------------------------------------------------------------------
@pytest.mark.parametrize("label,mesh", MESHES_2D, ids=[m[0] for m in MESHES_2D])
def test_stencil2d_is_bit_identical(label, mesh):
    nodes, tris = mesh
    e_ref, a_ref = ua._build_unstructured_stencil_py(nodes, tris)
    e_got, a_got = ua.build_unstructured_stencil(nodes, tris)
    assert_exact("edge_list", e_got, e_ref)
    assert_exact("node_areas", a_got, a_ref)


@pytest.mark.parametrize("label,mesh", MESHES_2D, ids=[m[0] for m in MESHES_2D])
def test_flux_geometry2d_is_bit_identical(label, mesh):
    nodes, tris = mesh
    edges, _ = ua._build_unstructured_stencil_py(nodes, tris)
    ie_ref, tr_ref = ua._build_edge_flux_geometry_py(nodes, tris, edges)
    ie_got, tr_got = ua.build_edge_flux_geometry(nodes, tris, edges)
    assert_exact("interior_edges", ie_got, ie_ref)
    assert_exact("trans", tr_got, tr_ref)


@pytest.mark.parametrize("label,mesh", MESHES_3D, ids=[m[0] for m in MESHES_3D])
def test_stencil3d_is_bit_identical(label, mesh):
    nodes, tets = mesh
    e_ref, v_ref = ua3._build_unstructured_stencil3d_py(nodes, tets)
    e_got, v_got = ua3.build_unstructured_stencil3d(nodes, tets)
    assert_exact("edge_list", e_got, e_ref)
    assert_exact("node_volumes", v_got, v_ref)


@pytest.mark.parametrize("label,mesh", MESHES_3D, ids=[m[0] for m in MESHES_3D])
def test_flux_geometry3d_is_bit_identical(label, mesh):
    """The kernel this whole phase exists for (3.5k tets/s -> 1.99M)."""
    nodes, tets = mesh
    edges, _ = ua3._build_unstructured_stencil3d_py(nodes, tets)
    _, tr_ref = ua3._build_edge_flux_geometry3d_py(nodes, tets, edges)
    el_got, tr_got = ua3.build_edge_flux_geometry3d(nodes, tets, edges)
    assert_exact("trans", tr_got, tr_ref)
    assert el_got is edges, "the reference returns edge_list itself, not a copy"


@pytest.mark.parametrize("label,mesh", MESHES_3D, ids=[m[0] for m in MESHES_3D])
def test_boundary_face_weights_is_bit_identical(label, mesh):
    nodes, tets = mesh
    faces = np.ascontiguousarray(tets[:, :3])
    ni_ref, w_ref = ua3._boundary_face_node_weights3d_py(nodes, faces)
    ni_got, w_got = ua3.boundary_face_node_weights3d(nodes, faces)
    assert_exact("node_idx", ni_got, ni_ref)
    assert_exact("weights", w_got, w_ref)


def test_partition_identities_still_hold():
    """The reference's own G7 gate: the dual measures partition the mesh
    exactly. Checked on the compiled path, not just inherited.

    The fixture is deliberately untangled (every triangle
    counter-clockwise), which used to be load-bearing: `_cot` divided by
    a SIGNED cross while `tri_area` took abs(), so an inverted triangle
    broke the identity by exactly 2x. That is fixed (M31 P2b) and
    test_winding_is_irrelevant_to_the_dual_areas below now gates the
    fix, but the untangled assertion is kept: it makes a fixture that
    silently starts producing inverted triangles fail HERE, saying so,
    instead of quietly weakening this gate.
    """
    nodes, tris = tri_grid(30, 0.05, 3)
    assert all(ua._triangle_area2(nodes[t][:, :2]) > 0 for t in tris), \
        "fixture must be untangled for this identity to hold"
    _, areas = ua.build_unstructured_stencil(nodes, tris)
    total = sum(0.5 * abs(ua._triangle_area2(nodes[t][:, :2])) for t in tris)
    assert areas.sum() == pytest.approx(total, rel=1e-12)

    P, tets = tet_grid(8, 0.2, 4)
    _, vol = ua3.build_unstructured_stencil3d(P, tets)
    tot = sum(abs(ua3._tet_volume(P[t])) for t in tets)
    assert vol.sum() == pytest.approx(tot, rel=1e-12)


#  The three ways to write a triangle, each paired with its REVERSAL
#  (same first vertex, other two swapped). All six describe the same
#  triangle, so all six must produce the same dual areas -- but only
#  within a pair is that expected BIT-for-bit, and the distinction is
#  not pedantry: `_triangle_area2` is a difference of two products, and
#  a reversal merely negates it (exact), while a cyclic rotation
#  recomputes it from different coordinate differences and lands a ulp
#  or two away. So a pair is compared with array_equal and the pairs
#  with each other only to 1e-14.
_WINDING_PAIRS = [((0, 1, 2), (0, 2, 1)),
                  ((1, 2, 0), (1, 0, 2)),
                  ((2, 0, 1), (2, 1, 0))]


@pytest.mark.parametrize("label,pts", [
    # Non-obtuse: takes the cotangent branch, which is where the defect
    # lived. Obtuse: takes the 1/2-1/4-1/4 branch, which never had it --
    # included so the test would catch a "fix" that broke that branch.
    ("acute", [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.4, 1.0, 0.0]]),
    ("right", [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
    ("obtuse", [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [-0.8, 0.3, 0.0]]),
])
def test_winding_is_irrelevant_to_the_dual_areas(label, pts):
    """M31 P2b: the dual areas depend on the triangle, not on the order
    its vertices were listed in.

    This was a real defect, surfaced by fuzzing the compiled path
    against the reference on a mesh jittered hard enough to invert a
    triangle: `_cot` divided by a SIGNED cross product while `tri_area`
    took abs(), so reversing a non-obtuse triangle flipped all three of
    its dual-area contributions negative and the partition identity
    failed by exactly 2x. It was pinned rather than fixed in P2 because
    fixing it changes physics and had to land on both paths at once --
    which is what this test now gates.

    Reversing a triangle is bit-exact, and asking only for `approx`
    there would hide a genuine reordering bug: the reversal negates
    every `cross` (and `abs` of a negated double is exact), leaves
    `dot` alone (it is symmetric in its arguments), leaves the squared
    side lengths alone (a negated difference squares identically), and
    merely swaps the order of the two terms each node receives. See
    _WINDING_PAIRS for why a cyclic ROTATION is the looser comparison.
    """
    nodes = np.array(pts)
    first = None
    for ccw, cw in _WINDING_PAIRS:
        got = {}
        for order in (ccw, cw):
            tri = np.array([order], dtype=int)
            signed = ua._triangle_area2(nodes[tri[0]][:, :2])
            _, areas = ua.build_unstructured_stencil(nodes, tri)
            _, areas_py = ua._build_unstructured_stencil_py(nodes, tri)
            assert_exact(f"{label} {order} compiled vs reference", areas, areas_py)
            # The partition identity, per triangle: what used to fail by 2x.
            assert areas.sum() == pytest.approx(0.5 * abs(signed), rel=1e-14)
            assert np.all(areas > 0.0), "a dual area is never negative"
            got[order] = (areas, signed)

        assert got[ccw][1] > 0 and got[cw][1] < 0, "the pair must differ in winding"
        assert_exact(f"{label} {cw} vs {ccw}", got[cw][0], got[ccw][0])

        if first is None:
            first = got[ccw][0]
        else:
            assert got[ccw][0] == pytest.approx(first, rel=1e-14)


def test_an_inverted_mesh_still_partitions_exactly():
    """The whole-mesh version of the above: reverse EVERY triangle and
    the dual areas are unchanged, so the G7 partition identity survives
    a mesh generator that winds the other way.

    The flip keeps each triangle's first vertex, so the comparison can
    be bit-exact -- see _WINDING_PAIRS.
    """
    nodes, tris = tri_grid(20, 0.05, 7)
    flipped = np.ascontiguousarray(tris[:, [0, 2, 1]])
    assert all(ua._triangle_area2(nodes[t][:, :2]) < 0 for t in flipped)

    _, areas = ua.build_unstructured_stencil(nodes, tris)
    _, areas_flipped = ua.build_unstructured_stencil(nodes, flipped)
    assert_exact("flipped node_areas", areas_flipped, areas)

    total = sum(0.5 * abs(ua._triangle_area2(nodes[t][:, :2])) for t in tris)
    assert areas_flipped.sum() == pytest.approx(total, rel=1e-12)


# ----------------------------------------------------------------------
#  empty / odd-shaped inputs
# ----------------------------------------------------------------------
def test_empty_mesh_matches_the_reference_shapes():
    """The reference returns shape (0,) for an empty edge list, not
    (0, 2) -- `np.array(sorted({}), dtype=int)` has no second axis."""
    n0 = np.zeros((0, 3))
    e_ref, a_ref = ua._build_unstructured_stencil_py(n0, np.zeros((0, 3), dtype=int))
    e_got, a_got = ua.build_unstructured_stencil(n0, np.zeros((0, 3), dtype=int))
    assert_exact("empty edges", e_got, e_ref)
    assert_exact("empty areas", a_got, a_ref)

    e_ref, v_ref = ua3._build_unstructured_stencil3d_py(n0, np.zeros((0, 4), dtype=int))
    e_got, v_got = ua3.build_unstructured_stencil3d(n0, np.zeros((0, 4), dtype=int))
    assert_exact("empty edges 3d", e_got, e_ref)
    assert_exact("empty vol", v_got, v_ref)


def test_two_column_nodes_are_accepted_like_the_reference():
    """2D callers may pass xy only; the kernels read 3 columns."""
    nodes2 = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    tris = np.array([[0, 1, 2], [1, 3, 2]])
    e_ref, a_ref = ua._build_unstructured_stencil_py(nodes2, tris)
    e_got, a_got = ua.build_unstructured_stencil(nodes2, tris)
    assert_exact("edges", e_got, e_ref)
    assert_exact("areas", a_got, a_ref)


def test_non_contiguous_input_is_handled_not_silently_wrong():
    """A sliced array is not c-contiguous; normalization happens in the
    shim, visibly, rather than as a hidden conversion in the binding."""
    nodes, tris = tri_grid(12)
    padded = np.zeros((nodes.shape[0], 5))
    padded[:, :3] = nodes
    view = padded[:, :3]
    assert not view.flags["C_CONTIGUOUS"]
    e_ref, a_ref = ua._build_unstructured_stencil_py(view, tris)
    e_got, a_got = ua.build_unstructured_stencil(view, tris)
    assert_exact("edges", e_got, e_ref)
    assert_exact("areas", a_got, a_ref)


# ----------------------------------------------------------------------
#  G-C: identical exception type AND message
# ----------------------------------------------------------------------
def _message(fn, *a):
    try:
        fn(*a)
    except DegenerateMeshError as exc:
        return str(exc)
    pytest.fail(f"{fn.__name__} did not raise")


def test_degenerate_triangle_message_matches_exactly():
    nodes = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    tris = np.array([[0, 1, 2]])
    assert (_message(ua.build_unstructured_stencil, nodes, tris) ==
            _message(ua._build_unstructured_stencil_py, nodes, tris))


def test_non_manifold_edge_message_matches_exactly():
    nodes = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.5, 1.0, 0.0],
                      [0.5, -1.0, 0.0], [0.5, 2.0, 0.0]])
    tris = np.array([[0, 1, 2], [0, 1, 3], [0, 1, 4]])
    assert (_message(ua.build_unstructured_stencil, nodes, tris) ==
            _message(ua._build_unstructured_stencil_py, nodes, tris))


def test_degenerate_tet_message_matches_exactly():
    nodes = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                      [2.0, 0.0, 0.0], [3.0, 0.0, 0.0]])
    tets = np.array([[0, 1, 2, 3]])
    assert (_message(ua3.build_unstructured_stencil3d, nodes, tets) ==
            _message(ua3._build_unstructured_stencil3d_py, nodes, tets))


def test_existing_match_patterns_still_catch_the_compiled_path():
    """tests/test_m21_phase3.py greps these messages; the compiled path
    must satisfy the same patterns with no test edit."""
    nodes = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    with pytest.raises(DegenerateMeshError, match="degenerate"):
        ua.build_unstructured_stencil(nodes, np.array([[0, 1, 2]]))
    nodes = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.5, 1.0, 0.0],
                      [0.5, -1.0, 0.0], [0.5, 2.0, 0.0]])
    with pytest.raises(DegenerateMeshError, match="non-manifold|shared by"):
        ua.build_unstructured_stencil(nodes, np.array([[0, 1, 2], [0, 1, 3], [0, 1, 4]]))


def test_a_failed_call_returns_nothing_at_all():
    """No half-state: the kernel's scratch is only published to numpy
    after a normal return, so a throw leaves no partial output."""
    nodes = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    result = "untouched"
    try:
        result = ua.build_unstructured_stencil(nodes, np.array([[0, 1, 2]]))
    except DegenerateMeshError:
        pass
    assert result == "untouched"


# ----------------------------------------------------------------------
#  G-D: thread invariance
# ----------------------------------------------------------------------
@pytest.mark.parametrize("threads", [1, 2, 4, 8])
def test_flux_geometry3d_is_identical_at_every_thread_count(threads):
    """A kernel may only use threads if its result does not depend on
    how many. build_flux_geometry3d parallelizes over OUTPUT edges with
    a thread-private accumulator, so its float addition order is fixed.
    A kernel that fails this loses its pragma, not its gate.
    """
    code = (
        "import numpy as np, sys; sys.path.insert(0, %r)\n"
        "from tests.test_accel_parity import tet_grid\n"
        "from pytcad import unstructured_assembly3d as ua3\n"
        "P, T = tet_grid(9, 0.25, 5)\n"
        "e, _ = ua3.build_unstructured_stencil3d(P, T)\n"
        "_, tr = ua3.build_edge_flux_geometry3d(P, T, e)\n"
        "sys.stdout.write(tr.tobytes().hex())\n" % ROOT
    )
    env = dict(os.environ)
    env["PYTCAD_NUM_THREADS"] = str(threads)
    env["PYTCAD_ACCEL"] = "1"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, env=env, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    if threads == 1:
        test_flux_geometry3d_is_identical_at_every_thread_count.baseline = out.stdout
    else:
        base = getattr(test_flux_geometry3d_is_identical_at_every_thread_count,
                       "baseline", None)
        if base is not None:
            assert out.stdout == base, (
                f"flux_geometry3d differs at {threads} threads -- a parallel "
                f"reduction reordered a float sum")


# ----------------------------------------------------------------------
#  G-E: absolute throughput floors
# ----------------------------------------------------------------------
@needs_active_accel
@pytest.mark.slow
@pytest.mark.parametrize("name,floor,build", [
    ("stencil2d", 2.0e6, "2d"),
    ("stencil3d", 1.0e6, "3d"),
    ("flux3d", 3.0e5, "flux3d"),
])
def test_throughput_floor(name, floor, build):
    """Absolute, not a ratio, so this only fails on a real regression.

    Reference rates when these kernels were written: 77k tri/s
    (stencil2d), 48k tet/s (stencil3d), 3.7k tet/s (flux3d).
    """
    import time
    if build == "2d":
        nodes, tris = tri_grid(300)
        ua.build_unstructured_stencil(nodes, tris)
        t0 = time.perf_counter()
        ua.build_unstructured_stencil(nodes, tris)
        rate = len(tris) / (time.perf_counter() - t0)
    elif build == "3d":
        P, tets = tet_grid(30)
        ua3.build_unstructured_stencil3d(P, tets)
        t0 = time.perf_counter()
        ua3.build_unstructured_stencil3d(P, tets)
        rate = len(tets) / (time.perf_counter() - t0)
    else:
        P, tets = tet_grid(22)
        e, _ = ua3.build_unstructured_stencil3d(P, tets)
        ua3.build_edge_flux_geometry3d(P, tets, e)
        t0 = time.perf_counter()
        ua3.build_edge_flux_geometry3d(P, tets, e)
        rate = len(tets) / (time.perf_counter() - t0)
    assert rate >= floor, f"{name}: {rate:.3g}/s below floor {floor:.3g}/s"


# ----------------------------------------------------------------------
#  G-A for the solver: the two PETSc backends (M31 P3b)
# ----------------------------------------------------------------------
# The mesh kernels above earn np.array_equal because their numpy
# primitives were measured to be plain scalar arithmetic.  A Krylov
# solve has no such argument -- and does not need one.  Both backends
# call the SAME libpetsc.so, with the same KSP type, restart, PC,
# tolerances and canonicalized matrix; the only thing P3b changed is
# WHERE those calls are made from.  So the honest bar is still exact
# equality, and it is met: measured bit-identical on random systems, on
# a real interleaved psi/n/p device Jacobian, and with a nonzero initial
# guess.
#
# The lever is PYTCAD_ACCEL, read per call by _accel.use_accel(), so
# both backends run in this one process against the same fixtures --
# which is the only way a parity test is cheap enough to run every time.
import scipy.sparse as _sp                                   # noqa: E402
from scipy.sparse.linalg import spsolve as _spsolve          # noqa: E402

from pytcad import linsolve                                  # noqa: E402

_petsc_both = pytest.mark.skipif(
    not (_accel.have_petsc() and linsolve._HAVE_PETSC4PY),
    reason="needs BOTH petsc backends: a PETSc-enabled pytcad._core and "
           "petsc4py (conda-forge)")


def _spd(n, seed, density=0.02):
    rng = np.random.default_rng(seed)
    A = _sp.random(n, n, density=density, random_state=rng,
                   data_rvs=lambda k: rng.standard_normal(k)).tocsr()
    A = A + A.T
    A = A + _sp.diags(np.abs(A).sum(axis=1).A1 + 1.0)
    return A.tocsr(), rng.standard_normal(n)


def _device_jacobian():
    """The matrix that actually matters: unknowns interleaved per node as
    (psi, n, p), which is what block_size=3 and PCPBJACOBI exist for."""
    from pytcad import Device1D, Models
    from pytcad.mesh import uniform_mesh

    xs = uniform_mesh(6.0e-4, 200)
    dop = np.where(xs < 3.0e-4, -1e16, 1e17)
    dev = Device1D(xs, dop, T=300.0, models=Models(srh=True))
    dev.solve_equilibrium()
    bc = dev._contact_values([0.3, 0.0])
    psi, n, p = dev.psi.copy(), dev.n.copy(), dev.p.copy()
    psi[0], n[0], p[0] = bc[0]
    psi[-1], n[-1], p[-1] = bc[1]
    F, J, _, _ = dev._residual_jacobian(psi, n, p, bc)
    return J, -F


def _both_backends(monkeypatch, A, b, **kw):
    """(cpp_result, py_result), each an (x, info) pair."""
    monkeypatch.setenv("PYTCAD_ACCEL", "1")
    cpp = linsolve.solve_linear(A, b, method="petsc", **kw)
    monkeypatch.setenv("PYTCAD_ACCEL", "0")
    py = linsolve.solve_linear(A, b, method="petsc", **kw)
    assert cpp[1]["backend"] == "cpp"
    assert py[1]["backend"] == "petsc4py"
    return cpp, py


@_petsc_both
@pytest.mark.parametrize("n,seed,block_size", [
    (30, 20, None), (300, 21, None), (600, 23, 3), (2001, 22, 3),
])
def test_petsc_backends_are_bit_identical(monkeypatch, n, seed, block_size):
    (xc, ic), (xp, ip) = _both_backends(
        monkeypatch, *_spd(n, seed), rtol=1e-10, block_size=block_size)
    assert ic["iterations"] == ip["iterations"]
    assert ic["residual"] == ip["residual"]
    assert_exact(f"petsc n={n} bs={block_size}", xc, xp)


@_petsc_both
def test_petsc_backends_are_bit_identical_on_a_device_jacobian(monkeypatch):
    """The random systems above converge in a handful of iterations; this
    one takes hundreds, so it is the case where any divergence between
    the two configurations would have room to show up."""
    J, rhs = _device_jacobian()
    (xc, ic), (xp, ip) = _both_backends(
        monkeypatch, J, rhs, rtol=1e-8, maxiter=500, block_size=3)
    assert ic["iterations"] == ip["iterations"] > 10
    assert_exact("petsc device jacobian", xc, xp)


@_petsc_both
def test_petsc_backends_agree_with_a_nonzero_initial_guess(monkeypatch):
    """x0 goes through KSPSetInitialGuessNonzero on both sides -- the
    P3a code set only the vector, so the flag is new on both paths and
    has to be gated on both."""
    A, b = _spd(200, 24)
    exact = _spsolve(A.tocsc(), b)
    (xc, ic), (xp, ip) = _both_backends(monkeypatch, A, b, rtol=1e-10, x0=exact)
    assert ic["iterations"] == ip["iterations"] == 0
    assert_exact("petsc x0", xc, xp)


@_petsc_both
def test_petsc_backends_fail_the_same_way(monkeypatch):
    """G-C for the solver: a matrix PETSc cannot precondition must raise
    the same CLASS from both backends.  Not the same message -- the
    compiled path reports PETSc's own error text ("Object is in wrong
    state") where petsc4py reports only a numeric code, which is an
    improvement rather than a divergence, so only the class is pinned.
    """
    A = _sp.csr_matrix(np.zeros((10, 10)))
    b = np.ones(10)
    for mode in ("1", "0"):
        monkeypatch.setenv("PYTCAD_ACCEL", mode)
        with pytest.raises(linsolve.LinearSolveError):
            linsolve.solve_linear(A, b, method="petsc", maxiter=20)


@pytest.mark.skipif(not _accel.have_petsc(),
                    reason="pytcad._core was not built against PETSc")
def test_petsc_solve_csr_rejects_mismatched_arrays():
    """The binding validates shapes rather than trusting them: a wrong
    length here would be an out-of-bounds read inside PETSc, not an
    exception."""
    core = _accel.core
    ip = np.array([0, 1], dtype=np.int64)
    idx = np.array([0], dtype=np.int64)
    val = np.array([2.0])
    rhs = np.array([1.0])
    with pytest.raises(ValueError):
        core.petsc_solve_csr(ip, idx, np.array([2.0, 3.0]), rhs, None,
                             1e-10, 1e-50, 10, 10, 0)
    with pytest.raises(ValueError):
        core.petsc_solve_csr(ip, idx, val, np.array([1.0, 2.0]), None,
                             1e-10, 1e-50, 10, 10, 0)
    with pytest.raises(ValueError):
        core.petsc_solve_csr(ip, idx, val, rhs, np.array([1.0, 2.0]),
                             1e-10, 1e-50, 10, 10, 0)


# ----------------------------------------------------------------------
#  G-A for the process/adaptivity kernels (M31 P4)
# ----------------------------------------------------------------------
# Same bar as the mesh kernels: np.array_equal, on both the AMR
# indicators and the 1D diffusion time loops.
#
# What makes that achievable is the split documented in
# core/include/tcad/process/kernels.hpp -- every transcendental that acts
# on a whole array (np.log for the log-density indicator,
# mesh.debye_length for the Debye ratio, the peak normalisation for
# curvature) is computed in numpy and only its RESULT crosses the
# boundary, so the kernels are pure comparison-and-arithmetic reductions.
# The one exception, the TED supersaturation's scalar exp, is covered by
# test_ted_exp_matches_numpy below rather than by assertion.
from pytcad import adapt_unstructured as _au                 # noqa: E402
from pytcad import process as _proc                          # noqa: E402
from pytcad import process2d as _p2d                         # noqa: E402
from pytcad import ted as _ted                               # noqa: E402


class _Mesh:
    """The two attributes the indicators actually read. Deliberately not
    a real UnstructuredMesh2D: these kernels have no business needing
    one, and a stub proves it."""
    def __init__(self, nodes, triangles):
        self.nodes, self.triangles = nodes, triangles


def _indicator_mesh(n=40, jitter=0.3, seed=5):
    nodes, tris = tri_grid(n, jitter, seed)
    return _Mesh(nodes, tris)


def _fields(mesh, seed=11):
    """psi / n / p / doping with the dynamic range a real device has --
    n and p span ~30 decades across a junction, which is exactly where a
    sloppy log or a reordered max would show up."""
    rng = np.random.default_rng(seed)
    xy = mesh.nodes[:, :2]
    psi = 0.8 * np.tanh((xy[:, 0] - 0.5) * 12.0) + 0.05 * rng.standard_normal(len(xy))
    n = 1e17 * np.exp(psi / 0.02585)
    p = 1e17 * np.exp(-psi / 0.02585)
    C = np.where(xy[:, 0] < 0.5, -1e16, 1e18)
    return psi, n, p, C


@pytest.mark.parametrize("jitter", [0.0, 0.3])
def test_amr_indicators_are_bit_identical(jitter):
    mesh = _indicator_mesh(jitter=jitter)
    psi, n, p, C = _fields(mesh)
    assert_exact("curvature",
                 _au.indicator_curvature_tri(mesh, psi),
                 _au._indicator_curvature_tri_py(mesh, psi))
    assert_exact("log_density",
                 _au.indicator_log_density_tri(mesh, n, p),
                 _au._indicator_log_density_tri_py(mesh, n, p))
    assert_exact("debye_ratio",
                 _au.debye_ratio_tri(mesh, C),
                 _au._debye_ratio_tri_py(mesh, C))


def test_amr_indicators_agree_on_the_degenerate_edges_of_their_domain():
    """The clamps are part of the contract, not defensive padding:
    `n`/`p` are floored at 1e-300 before the log, and the Debye ratio
    divides by max(ld_min, 1e-300). A kernel that clamped differently
    would still look right on ordinary input."""
    mesh = _indicator_mesh(n=12, jitter=0.0)
    N = len(mesh.nodes)
    zero = np.zeros(N)
    tiny = np.full(N, 1e-320)          # subnormal, below the 1e-300 floor
    assert_exact("log_density at zero",
                 _au.indicator_log_density_tri(mesh, zero, tiny),
                 _au._indicator_log_density_tri_py(mesh, zero, tiny))
    assert_exact("debye at zero doping",
                 _au.debye_ratio_tri(mesh, zero),
                 _au._debye_ratio_tri_py(mesh, zero))
    # A constant psi makes every edge difference exactly 0, so `scale`
    # falls back on its own 1e-300 floor and the result is 0/1e-300.
    flat = np.zeros(N)
    assert_exact("curvature on a flat field",
                 _au.indicator_curvature_tri(mesh, flat),
                 _au._indicator_curvature_tri_py(mesh, flat))


def test_an_out_of_range_node_index_raises_instead_of_reading_memory():
    """The reference gets this from numpy fancy-indexing. The kernels
    dereference raw pointers, so they validate the index range once up
    front -- and must raise the SAME class, since that is what a caller
    can catch. The message text is not claimed to match numpy's."""
    mesh = _indicator_mesh(n=6, jitter=0.0)
    N = len(mesh.nodes)
    bad = _Mesh(mesh.nodes, np.array([[0, 1, N]]))       # one past the end
    psi = np.zeros(N)
    with pytest.raises(IndexError):
        _au.indicator_curvature_tri(bad, psi)
    with pytest.raises(IndexError):
        _au.debye_ratio_tri(bad, np.full(N, 1e16))
    with pytest.raises(IndexError):
        _au.indicator_log_density_tri(bad, np.full(N, 1e10), np.full(N, 1e10))


def _diffusion_case(n=250, L=2.0e-4):
    x = np.linspace(0.0, L, n)
    return x, _proc.implant(x, "B", 50.0, 1e15)


@pytest.mark.parametrize("reflecting", [True, False])
@pytest.mark.parametrize("t_s", [1.0, 60.0])
def test_diffuse_numeric_is_bit_identical(monkeypatch, reflecting, t_s):
    x, C = _diffusion_case()
    monkeypatch.setenv("PYTCAD_ACCEL", "0")
    ref = _proc.diffuse_numeric(x, C, "B", 1000.0, t_s, reflecting=reflecting)
    monkeypatch.setenv("PYTCAD_ACCEL", "1")
    got = _proc.diffuse_numeric(x, C, "B", 1000.0, t_s, reflecting=reflecting)
    assert_exact(f"diffuse_numeric t={t_s} reflecting={reflecting}", got, ref)


@pytest.mark.parametrize("kwargs", [
    dict(n_total=None, ted_S0=25.0, ted_tau_s=8.0, oed_boost=0.0),
    dict(n_total="doped", ted_S0=0.0, ted_tau_s=None, oed_boost=0.4),
    dict(n_total="doped", ted_S0=25.0, ted_tau_s=8.0, oed_boost=0.4),
])
def test_diffuse_with_defects_is_bit_identical(monkeypatch, kwargs):
    """Covers all three enhancement mechanisms, and in particular the
    ted_S0 == 0 short circuit -- where the reference never evaluates the
    exponential at all and ted_tau_s is legitimately None, so the kernel
    must not read it either."""
    x, C = _diffusion_case()
    kw = dict(kwargs)
    if kw["n_total"] == "doped":
        kw["n_total"] = np.full_like(x, 5e19)

    monkeypatch.setenv("PYTCAD_ACCEL", "0")
    ref = _ted.diffuse_with_defects(x, C, "B", 1000.0, 30.0, **kw)
    monkeypatch.setenv("PYTCAD_ACCEL", "1")
    got = _ted.diffuse_with_defects(x, C, "B", 1000.0, 30.0, **kw)
    assert_exact(f"diffuse_with_defects {kwargs}", got, ref)


def test_the_diffusion_kernels_never_write_through_to_the_caller():
    """The reference copies C before the loop. A kernel that mutated the
    caller's array instead would pass every value comparison above and
    still be a behavioural difference between the two paths."""
    x, C = _diffusion_case(n=120)
    before = C.copy()
    _proc.diffuse_numeric(x, C, "B", 1000.0, 5.0)
    assert_exact("caller's C after diffuse_numeric", C, before)
    _ted.diffuse_with_defects(x, C, "B", 1000.0, 5.0, ted_S0=10.0, ted_tau_s=3.0)
    assert_exact("caller's C after diffuse_with_defects", C, before)


def test_ted_exp_matches_numpy(monkeypatch):
    """The ONE transcendental the C++ side computes for itself.

    Everything else is handed down already evaluated. This one is not,
    because keeping it in Python would mean materializing one double per
    timestep -- millions of them on a fine grid -- purely to hand back.
    So the agreement is checked directly, over the argument range the
    decay actually reaches, instead of being assumed.
    """
    x, C = _diffusion_case(n=60)
    # tau small against the anneal time, so -t/tau sweeps deep into the
    # tail rather than staying near 0 where any two exps agree.
    for tau in (0.05, 1.0, 50.0):
        monkeypatch.setenv("PYTCAD_ACCEL", "0")
        ref = _ted.diffuse_with_defects(x, C, "B", 1000.0, 20.0,
                                        ted_S0=1e3, ted_tau_s=tau)
        monkeypatch.setenv("PYTCAD_ACCEL", "1")
        got = _ted.diffuse_with_defects(x, C, "B", 1000.0, 20.0,
                                        ted_S0=1e3, ted_tau_s=tau)
        assert_exact(f"ted exp tau={tau}", got, ref)


def test_implant_2d_lateral_smoothing_is_unchanged_by_the_hoist():
    """M31 P4 made implant_2d build its smoothing matrix once instead of
    once per depth row (939 ms -> 15 ms at 400x600). That is a pure
    hoist, so it has to be BIT-identical, and this reconstructs the old
    per-row form to prove it rather than trusting the argument."""
    Nx, Ny = 90, 70
    x = np.linspace(0.0, 2.0e-4, Nx)
    y = np.linspace(0.0, 1.0e-4, Ny)
    geom = _p2d.ProcessGeometry2D(x)
    geom.surface_um = np.linspace(0.0, 0.2, Nx)
    mask = np.zeros(Nx, dtype=bool)
    mask[Nx // 4:3 * Nx // 4] = True

    got = _p2d.implant_2d(x, y, geom, "B", 50.0, 1e15, mask=mask)

    # The pre-hoist body, transcribed.
    Rp, dRp = _proc.implant_moments("B", 50.0)
    ref = np.zeros((Ny, Nx))
    surf_cm = -geom.surface_um * 1e-4
    for i in range(Nx):
        if not mask[i]:
            continue
        depth = y - surf_cm[i]
        ref[:, i] = 1e15 / (np.sqrt(2.0 * np.pi) * dRp) * np.exp(
            -((depth - Rp) ** 2) / (2.0 * dRp ** 2))
    sigma = 0.8 * dRp
    for j in range(Ny):
        xx = np.asarray(x, dtype=float)
        dx = xx[:, None] - xx[None, :]
        k = np.exp(-0.5 * (dx / sigma) ** 2)
        k /= k.sum(axis=1, keepdims=True)
        ref[j, :] = k @ ref[j, :]

    assert_exact("implant_2d after the hoist", got, ref)


@needs_active_accel
@pytest.mark.slow
@pytest.mark.parametrize("name,floor", [
    ("curvature", 5.0e7),
    ("log_density", 2.0e7),
    ("debye_ratio", 5.0e7),
])
def test_indicator_throughput_floor(name, floor):
    """G-E for P4. Absolute, and set roughly 4x below what was measured
    when these landed (227M / 99M / 242M tri/s), so this fails on a
    regression and not on a slower machine. Python reference rates for
    the same three: 0.27M, 0.80M, 0.28M tri/s.
    """
    import time
    mesh = _indicator_mesh(n=200, jitter=0.0)
    psi, n, p, C = _fields(mesh)
    fn = {"curvature": lambda: _au.indicator_curvature_tri(mesh, psi),
          "log_density": lambda: _au.indicator_log_density_tri(mesh, n, p),
          "debye_ratio": lambda: _au.debye_ratio_tri(mesh, C)}[name]
    fn()                                     # warm
    t0 = time.perf_counter()
    fn()
    rate = len(mesh.triangles) / (time.perf_counter() - t0)
    assert rate >= floor, f"{name}: {rate:.3g} tri/s below floor {floor:.3g}"
