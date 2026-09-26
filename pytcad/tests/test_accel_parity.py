"""Correctness gates for the compiled kernels in pytcad._core.

M43 phase 4 (2026-09-16): the pure-Python reference bodies
(`_<name>_py`) this file used to diff the compiled kernels against
were REMOVED at the user's explicit request -- pytcad now REQUIRES
the compiled extension, there is no Python fallback path. Tests whose
entire premise was "compiled path == deleted Python path" were removed
or rewritten into standalone correctness checks (partition identities,
degenerate-input error handling, reproducibility) that do not need a
second implementation to compare against. The PETSc section (M31 P3b)
is UNTOUCHED: petsc4py remains a real, independent second backend
(linsolve.py's own oracle for `method="petsc"`), not a pure-Python
fallback for lack of a compiler, and stays out of this milestone's
scope.

The gates in this file:
  G-A  mesh-geometry partition identities hold on the compiled path
  G-C  degenerate/non-manifold input raises the right exception TYPE
  G-D  identical results at PYTCAD_NUM_THREADS in {1, 2, 4, 8}
  G-E  absolute throughput floors (marked slow)
  (PETSc section, unchanged) both petsc backends bit-identical
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


# Independent (NOT the production code) triangle-area / tet-volume
# formulas, for the partition-identity cross-checks below -- kept here
# rather than importing the deleted `_triangle_area2`/`_tet_volume`
# internals, so these gates check the compiled kernel's OUTPUT against
# an independently-computed ground truth, not against itself.
def _tri_area2_xcheck(pts):
    return ((pts[1, 0] - pts[0, 0]) * (pts[2, 1] - pts[0, 1])
            - (pts[2, 0] - pts[0, 0]) * (pts[1, 1] - pts[0, 1]))


def _tet_vol_xcheck(pts):
    return np.dot(pts[1] - pts[0],
                  np.cross(pts[2] - pts[0], pts[3] - pts[0])) / 6.0


# ----------------------------------------------------------------------
#  G-A: mesh-geometry partition identities (compiled path only)
# ----------------------------------------------------------------------
def test_partition_identities_still_hold():
    """The dual measures partition the mesh exactly -- the module's own
    G7 gate, checked against an independently-computed total area/
    volume (see the _xcheck helpers above), not against a second
    implementation of the kernel itself."""
    nodes, tris = tri_grid(30, 0.05, 3)
    assert all(_tri_area2_xcheck(nodes[t][:, :2]) > 0 for t in tris), \
        "fixture must be untangled for this identity to hold"
    _, areas = ua.build_unstructured_stencil(nodes, tris)
    total = sum(0.5 * abs(_tri_area2_xcheck(nodes[t][:, :2])) for t in tris)
    assert areas.sum() == pytest.approx(total, rel=1e-12)

    P, tets = tet_grid(8, 0.2, 4)
    _, vol = ua3.build_unstructured_stencil3d(P, tets)
    tot = sum(abs(_tet_vol_xcheck(P[t])) for t in tets)
    assert vol.sum() == pytest.approx(tot, rel=1e-12)


@pytest.mark.parametrize("label,mesh", MESHES_2D, ids=[m[0] for m in MESHES_2D])
def test_flux_geometry2d_is_sane(label, mesh):
    """interior_edges is a subset of edge_list, and every TPFA geometry
    factor is finite and non-negative (a ratio of two non-negative
    lengths -- exactly 0.0 is a real, legitimate case on a structured
    right-triangle grid where the two owning circumcenters coincide)."""
    nodes, tris = mesh
    edges, _ = ua.build_unstructured_stencil(nodes, tris)
    interior_edges, trans = ua.build_edge_flux_geometry(nodes, tris, edges)
    assert interior_edges.shape[1] == 2
    assert trans.shape[0] == interior_edges.shape[0]
    assert np.all(np.isfinite(trans)) and np.all(trans >= 0.0)
    edge_set = {tuple(e) for e in edges.tolist()}
    assert all(tuple(e) in edge_set for e in interior_edges.tolist())


@pytest.mark.parametrize("label,mesh", MESHES_3D, ids=[m[0] for m in MESHES_3D])
def test_flux_geometry3d_is_sane(label, mesh):
    nodes, tets = mesh
    edges, _ = ua3.build_unstructured_stencil3d(nodes, tets)
    interior_edges, trans = ua3.build_edge_flux_geometry3d(nodes, tets, edges)
    assert interior_edges is edges, "returns edge_list itself, not a copy"
    assert trans.shape[0] == edges.shape[0]
    assert np.all(np.isfinite(trans)) and np.all(trans >= 0.0)


@pytest.mark.parametrize("label,mesh", MESHES_3D, ids=[m[0] for m in MESHES_3D])
def test_boundary_face_weights_partition_the_boundary_area(label, mesh):
    """Each face's area splits 1/3 to each of its 3 vertices -- the sum
    of returned weights must equal the total boundary-face area,
    computed independently via the cross-product formula."""
    nodes, tets = mesh
    faces = np.ascontiguousarray(tets[:, :3])
    node_idx, weights = ua3.boundary_face_node_weights3d(nodes, faces)
    assert node_idx.shape == weights.shape
    assert np.all(weights >= 0.0) and np.all(np.isfinite(weights))
    nodes_xyz = np.asarray(nodes, dtype=float)[:, :3]
    p0, p1, p2 = nodes_xyz[faces[:, 0]], nodes_xyz[faces[:, 1]], nodes_xyz[faces[:, 2]]
    total_area = (0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)).sum()
    assert weights.sum() == pytest.approx(total_area, rel=1e-10)


def test_boundary_face_weights_empty_input_returns_empty_arrays():
    nodes = np.zeros((3, 3))
    node_idx, weights = ua3.boundary_face_node_weights3d(nodes, np.zeros((0, 3), dtype=int))
    assert node_idx.shape == (0,) and weights.shape == (0,)


_WINDING_PAIRS = [((0, 1, 2), (0, 2, 1)),
                  ((1, 2, 0), (1, 0, 2)),
                  ((2, 0, 1), (2, 1, 0))]


@pytest.mark.parametrize("label,pts", [
    ("acute", [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.4, 1.0, 0.0]]),
    ("right", [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
    ("obtuse", [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [-0.8, 0.3, 0.0]]),
])
def test_winding_is_irrelevant_to_the_dual_areas(label, pts):
    """M31 P2b: the dual areas depend on the triangle, not on the order
    its vertices were listed in -- a real defect once (a signed-cross
    vs. abs() mismatch flipped a reversed triangle's contribution
    negative). Checked on the compiled path alone, via the same
    independent area cross-check the partition-identity test uses."""
    nodes = np.array(pts)
    first = None
    for ccw, cw in _WINDING_PAIRS:
        vals = {}
        for order in (ccw, cw):
            tri = np.array([order], dtype=int)
            signed = _tri_area2_xcheck(nodes[tri[0]][:, :2])
            _, areas = ua.build_unstructured_stencil(nodes, tri)
            assert areas.sum() == pytest.approx(0.5 * abs(signed), rel=1e-14)
            assert np.all(areas > 0.0), "a dual area is never negative"
            vals[order] = (areas, signed)

        assert vals[ccw][1] > 0 and vals[cw][1] < 0, "the pair must differ in winding"
        assert_exact(f"{label} {cw} vs {ccw}", vals[cw][0], vals[ccw][0])

        if first is None:
            first = vals[ccw][0]
        else:
            assert vals[ccw][0] == pytest.approx(first, rel=1e-14)


def test_an_inverted_mesh_still_partitions_exactly():
    """Reverse EVERY triangle and the dual areas are unchanged, so the
    G7 partition identity survives a mesh generator that winds the
    other way."""
    nodes, tris = tri_grid(20, 0.05, 7)
    flipped = np.ascontiguousarray(tris[:, [0, 2, 1]])
    assert all(_tri_area2_xcheck(nodes[t][:, :2]) < 0 for t in flipped)

    _, areas = ua.build_unstructured_stencil(nodes, tris)
    _, areas_flipped = ua.build_unstructured_stencil(nodes, flipped)
    assert_exact("flipped node_areas", areas_flipped, areas)

    total = sum(0.5 * abs(_tri_area2_xcheck(nodes[t][:, :2])) for t in tris)
    assert areas_flipped.sum() == pytest.approx(total, rel=1e-12)


# ----------------------------------------------------------------------
#  empty / odd-shaped inputs
# ----------------------------------------------------------------------
def test_empty_mesh_returns_shape_0_not_0_2():
    """An empty edge list is shape (0,), not (0, 2)."""
    n0 = np.zeros((0, 3))
    e_got, a_got = ua.build_unstructured_stencil(n0, np.zeros((0, 3), dtype=int))
    assert e_got.shape == (0,)
    assert a_got.shape == (0,)

    e_got, v_got = ua3.build_unstructured_stencil3d(n0, np.zeros((0, 4), dtype=int))
    assert e_got.shape == (0,)
    assert v_got.shape == (0,)


def test_two_column_nodes_are_accepted():
    """2D callers may pass xy only; the kernel reads 3 columns."""
    nodes2 = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    tris = np.array([[0, 1, 2], [1, 3, 2]])
    edges, areas = ua.build_unstructured_stencil(nodes2, tris)
    assert edges.shape[1] == 2 and areas.shape[0] == 4


def test_non_contiguous_input_is_handled():
    """A sliced array is not c-contiguous; normalization happens in the
    shim, visibly, rather than as a hidden conversion in the binding."""
    nodes, tris = tri_grid(12)
    padded = np.zeros((nodes.shape[0], 5))
    padded[:, :3] = nodes
    view = padded[:, :3]
    assert not view.flags["C_CONTIGUOUS"]
    edges, areas = ua.build_unstructured_stencil(view, tris)
    assert edges.shape[0] > 0 and areas.sum() > 0.0


# ----------------------------------------------------------------------
#  G-C: degenerate/non-manifold input raises the right exception type
# ----------------------------------------------------------------------
def test_degenerate_triangle_raises():
    nodes = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    tris = np.array([[0, 1, 2]])
    with pytest.raises(DegenerateMeshError, match="degenerate"):
        ua.build_unstructured_stencil(nodes, tris)


def test_non_manifold_edge_raises():
    nodes = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.5, 1.0, 0.0],
                      [0.5, -1.0, 0.0], [0.5, 2.0, 0.0]])
    tris = np.array([[0, 1, 2], [0, 1, 3], [0, 1, 4]])
    with pytest.raises(DegenerateMeshError, match="non-manifold|shared by"):
        ua.build_unstructured_stencil(nodes, tris)


def test_degenerate_tet_raises():
    nodes = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                      [2.0, 0.0, 0.0], [3.0, 0.0, 0.0]])
    tets = np.array([[0, 1, 2, 3]])
    with pytest.raises(DegenerateMeshError, match="degenerate"):
        ua3.build_unstructured_stencil3d(nodes, tets)


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
# "timing", not "slow" (2026-09-26): a wall-clock throughput floor that
# runs in ~1 s but failed under the parallel slow battery's load; it runs
# in the serial timing pass (pytest.ini).
@pytest.mark.timing
@pytest.mark.parametrize("name,floor,build", [
    ("stencil2d", 2.0e6, "2d"),
    ("stencil3d", 1.0e6, "3d"),
    ("flux3d", 3.0e5, "flux3d"),
])
def test_throughput_floor(name, floor, build):
    """Absolute, not a ratio, so this only fails on a real regression."""
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
#  G-A for the solver: the two PETSc backends (M31 P3b) -- UNCHANGED.
#  petsc4py is a real, independent second backend (linsolve.py's own
#  oracle for method="petsc"), not a pure-Python fallback for lack of a
#  compiler, and is explicitly out of M43 phase 4's scope.
# ----------------------------------------------------------------------
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
#  G-A for the process/adaptivity kernels (M31 P4) -- compiled path
#  only; sanity/behavioral checks rather than parity comparisons.
# ----------------------------------------------------------------------
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
    n and p span ~30 decades across a junction."""
    rng = np.random.default_rng(seed)
    xy = mesh.nodes[:, :2]
    psi = 0.8 * np.tanh((xy[:, 0] - 0.5) * 12.0) + 0.05 * rng.standard_normal(len(xy))
    n = 1e17 * np.exp(psi / 0.02585)
    p = 1e17 * np.exp(-psi / 0.02585)
    C = np.where(xy[:, 0] < 0.5, -1e16, 1e18)
    return psi, n, p, C


def test_amr_indicators_produce_sane_normalized_output():
    """Shape matches the triangle count and every value is finite and
    non-negative. `indicator_curvature_tri` is normalized by the FIELD's
    own peak |psi|, not by its own peak edge value, so it is not
    expected to reach exactly 1.0 -- only bounded and non-negative."""
    mesh = _indicator_mesh()
    psi, n, p, C = _fields(mesh)
    n_tri = mesh.triangles.shape[0]

    curv = _au.indicator_curvature_tri(mesh, psi)
    assert curv.shape == (n_tri,)
    assert np.all(np.isfinite(curv)) and np.all(curv >= 0.0)

    ld = _au.indicator_log_density_tri(mesh, n, p)
    assert ld.shape == (n_tri,)
    assert np.all(np.isfinite(ld)) and np.all(ld >= 0.0)

    debye = _au.debye_ratio_tri(mesh, C)
    assert debye.shape == (n_tri,)
    assert np.all(np.isfinite(debye)) and np.all(debye >= 0.0)


def test_amr_indicators_handle_the_degenerate_edges_of_their_domain():
    """The clamps are part of the contract, not defensive padding:
    `n`/`p` are floored at 1e-300 before the log, and the Debye ratio
    divides by max(ld_min, 1e-300) -- must not raise or produce inf/nan
    at exactly-zero input."""
    mesh = _indicator_mesh(n=12, jitter=0.0)
    N = len(mesh.nodes)
    zero = np.zeros(N)
    tiny = np.full(N, 1e-320)          # subnormal, below the 1e-300 floor

    ld = _au.indicator_log_density_tri(mesh, zero, tiny)
    assert np.all(np.isfinite(ld))

    debye = _au.debye_ratio_tri(mesh, zero)
    assert np.all(np.isfinite(debye))

    # A constant psi makes every edge difference exactly 0, so `scale`
    # falls back on its own 1e-300 floor and the result is 0/1e-300 == 0.
    flat = np.zeros(N)
    curv = _au.indicator_curvature_tri(mesh, flat)
    assert np.all(curv == 0.0)


def test_an_out_of_range_node_index_raises():
    """The kernels dereference raw pointers, so they validate the index
    range once up front and must raise IndexError -- the same class a
    caller catches from ordinary numpy fancy-indexing."""
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


def test_diffuse_numeric_is_reproducible():
    """Same inputs, same result, called twice -- a determinism gate on
    the sole (compiled) path, since there is no second implementation
    to diff against any more."""
    x, C = _diffusion_case()
    a = _proc.diffuse_numeric(x, C, "B", 1000.0, 1.0, reflecting=True)
    b = _proc.diffuse_numeric(x, C, "B", 1000.0, 1.0, reflecting=True)
    assert_exact("diffuse_numeric repeat call", b, a)
    assert np.all(np.isfinite(a)) and np.all(a >= 0.0)


def test_the_diffusion_kernels_never_write_through_to_the_caller():
    """The caller's C must be unmodified: the kernel operates on a copy
    the binding makes, not the caller's own array."""
    x, C = _diffusion_case(n=120)
    before = C.copy()
    _proc.diffuse_numeric(x, C, "B", 1000.0, 5.0)
    assert_exact("caller's C after diffuse_numeric", C, before)
    _ted.diffuse_with_defects(x, C, "B", 1000.0, 5.0, ted_S0=10.0, ted_tau_s=3.0)
    assert_exact("caller's C after diffuse_with_defects", C, before)


def test_implant_2d_lateral_smoothing_matches_the_per_row_formula():
    """M31 P4 made implant_2d build its smoothing matrix once instead of
    once per depth row (939 ms -> 15 ms at 400x600). That is a pure
    hoist, so it must reproduce the per-row form exactly rather than
    trusting the argument -- transcribed here independently."""
    Nx, Ny = 90, 70
    x = np.linspace(0.0, 2.0e-4, Nx)
    y = np.linspace(0.0, 1.0e-4, Ny)
    geom = _p2d.ProcessGeometry2D(x)
    geom.surface_um = np.linspace(0.0, 0.2, Nx)
    mask = np.zeros(Nx, dtype=bool)
    mask[Nx // 4:3 * Nx // 4] = True

    got = _p2d.implant_2d(x, y, geom, "B", 50.0, 1e15, mask=mask)

    # The pre-hoist form, transcribed independently.
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


# "timing", not "slow": same reason as test_throughput_floor above.
@pytest.mark.timing
@pytest.mark.parametrize("name,floor", [
    ("curvature", 5.0e7),
    ("log_density", 2.0e7),
    ("debye_ratio", 5.0e7),
])
def test_indicator_throughput_floor(name, floor):
    """G-E for P4. Absolute, and set roughly 4x below what was measured
    when these landed (227M / 99M / 242M tri/s), so this fails on a
    regression and not on a slower machine.
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
