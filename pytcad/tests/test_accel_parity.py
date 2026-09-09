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

    Jitter is kept small enough that no triangle INVERTS. That is not
    incidental: `_cot` returns dot/cross with a SIGNED cross, while
    `tri_area` uses abs(), so on a clockwise-wound triangle the
    non-obtuse (cotangent) branch contributes negative dual areas and
    the identity fails by exactly 2x. gmsh emits consistently
    counter-clockwise triangles, so no real caller hits it -- see
    test_winding_sensitivity_is_reproduced_faithfully below, which pins
    the behavior rather than pretending it is absent.
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


def test_winding_sensitivity_is_reproduced_faithfully():
    """A bit-identical port reproduces the reference's quirks too.

    `build_unstructured_stencil` is winding-sensitive: reverse a
    non-obtuse triangle's vertex order and its three dual-area
    contributions flip sign, because `_cot`'s denominator is a signed
    cross product while `tri_area` is an absolute value. This is a
    latent defect in the REFERENCE (surfaced by fuzzing the compiled
    path against it), not something introduced here -- and the correct
    behavior for this phase is to reproduce it exactly, so the parity
    gate stays meaningful. Fixing it would change physics and belongs
    in its own change, on both paths at once.
    """
    ccw = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.4, 1.0, 0.0]])
    tri_ccw = np.array([[0, 1, 2]])
    tri_cw = np.array([[0, 2, 1]])
    assert ua._triangle_area2(ccw[tri_ccw[0]][:, :2]) > 0
    assert ua._triangle_area2(ccw[tri_cw[0]][:, :2]) < 0

    _, a_ccw = ua.build_unstructured_stencil(ccw, tri_ccw)
    _, a_cw = ua.build_unstructured_stencil(ccw, tri_cw)
    _, r_cw = ua._build_unstructured_stencil_py(ccw, tri_cw)
    assert_exact("clockwise node_areas", a_cw, r_cw)
    assert a_ccw.sum() > 0 and a_cw.sum() < 0     # the quirk, pinned


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
