"""M31 P5-0 -- the Python-side prerequisites for P5.

See `M31-P5-ASSEMBLY-NEWTON-PLAN.md` sections 4 (P5-0) and 6.  Two
changes to the unstructured cores, neither of them C++:

  1. the Dirichlet contact rows are stamped on the assembled CSR
     instead of via `J.tolil()` + LIL row assignment, and
  2. the Newton update goes through `linsolve.solve_linear`, so
     `NewtonOptions.linsolve` -- and therefore M22's Krylov methods and
     M31 P3a/P3b's PETSc stack -- reach these cores at all.  Before this
     they called `spsolve` directly and could not.

WHY BOTH ARE GATED BIT-IDENTICAL, NOT "CLOSE"
---------------------------------------------
The profile that motivated P5-0 (plan section 6) says assembly is
1.5-8.9% of an unstructured solve while the linear solve is 52-91% and
the LIL stamping is most of what is left.  That makes this change worth
making -- and makes it exactly the kind of change that can move results
at 1e-16 and be waved through as "the same".  It is a substitution of
one construction of the SAME matrix for another, so the honest gate is
byte-identity of the matrix and `np.array_equal` on the solve, not a
tolerance.

WHAT IS PROVED, AND HOW THE REST FOLLOWS
----------------------------------------
Four cores share one loop shape (assemble -> stamp contact rows ->
`eliminate_csr` -> solve).  Rather than transcribe four Newton loops,
this file proves the two pieces that changed:

  * `stamp_dirichlet_rows` produces a matrix BYTE-identical to the LIL
    transcription (indptr, indices AND data), on a real assembled
    Jacobian and under a fuzz, and
  * `solve_linear(A, b, method="direct")` is bit-identical to
    `spsolve(A, b)` for the exact call shape these cores use.

Identical matrix plus identical rhs through an identical solver gives
an identical iterate, so the loops compose.  The 2D coupled DD loop is
ALSO transcribed end to end (`test_2d_dd_bias_is_bit_identical...`),
because composition arguments are how a real difference gets argued
away, and one full end-to-end check costs a fixture.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
import numpy as np
import pytest
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

gmsh = pytest.importorskip("gmsh")

from pytcad.dirichlet import stamp_dirichlet_rows, eliminate_csr
from pytcad.linsolve import solve_linear
from pytcad.gmsh_mesh import build_diode_mesh
from pytcad.region_resolver import resolve_regions, resolve_contacts
from pytcad.unstructured_assembly import (
    build_unstructured_stencil, build_edge_flux_geometry)
from pytcad.unstructured_poisson import evaluate_doping_at_nodes
import pytcad.unstructured_dd as ud
from pytcad.device import NewtonOptions

warnings.simplefilter("ignore")

DOPING = {"p_region": -1e17, "n_region": 1e17}
BIAS = {"left_contact": 0.5, "right_contact": 0.0}


def _lil_reference(J, rows):
    """The pre-P5-0 construction, kept as the oracle."""
    Jl = J.tolil()
    Jl[rows, :] = 0.0
    Jl[rows, rows] = 1.0
    return Jl.tocsr()


def _assert_byte_identical(new, old, what):
    new = new.tocsr(); new.sort_indices()
    old = old.tocsr(); old.sort_indices()
    assert np.array_equal(new.indptr, old.indptr), f"{what}: indptr differs"
    assert np.array_equal(new.indices, old.indices), f"{what}: indices differ"
    assert np.array_equal(new.data, old.data), f"{what}: DATA differs"


@pytest.fixture(scope="module")
def geom():
    mesh = build_diode_mesh(Lx=4.0e-4, Ly=1.0e-4, Xj=2.0e-4)
    regions = resolve_regions(mesh)
    contacts = resolve_contacts(mesh)
    edge_list, node_areas = build_unstructured_stencil(mesh.nodes, mesh.triangles)
    interior_edges, trans_geom = build_edge_flux_geometry(
        mesh.nodes, mesh.triangles, edge_list)
    rot = np.empty(mesh.n_triangles(), dtype=object)
    for name, idx in regions.items():
        rot[idx] = name
    C = evaluate_doping_at_nodes(mesh.nodes, mesh.triangles, rot, DOPING)
    return dict(mesh=mesh, contacts=contacts, edge_list=edge_list,
                node_areas=node_areas, interior_edges=interior_edges,
                trans_geom=trans_geom, C=C)


def _solve_args(g):
    m = g["mesh"]
    return (m.nodes, m.triangles, g["edge_list"], g["node_areas"],
            g["interior_edges"], g["trans_geom"], g["C"], g["contacts"])


# ----------------------------------------------------------------------
#  1. the stamping helper
# ----------------------------------------------------------------------
def test_stamping_matches_the_lil_reference_on_a_real_jacobian(geom):
    """The case that matters: a real coupled [psi,n,p] Jacobian off the
    unstructured assembler, not a synthetic matrix."""
    captured = {}
    raw = ud._residual_jacobian

    def spy(*a, **k):
        out = raw(*a, **k)
        captured.setdefault("J", out[1])
        return out

    ud._residual_jacobian = spy
    try:
        ud.solve_bias(*_solve_args(geom), BIAS)
    finally:
        ud._residual_jacobian = raw

    J = captured["J"]
    N = J.shape[0]
    base = np.arange(0, N // 3, max(1, (N // 3) // 20))
    rows = np.sort(np.concatenate([3 * base + c for c in range(3)]))
    _assert_byte_identical(stamp_dirichlet_rows(J, rows),
                           _lil_reference(J, rows), "real Jacobian")


@pytest.mark.parametrize("seed", range(8))
def test_stamping_matches_the_lil_reference_under_fuzz(seed):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(6, 60))
    density = float(rng.uniform(0.05, 0.4))
    A = sp.random(n, n, density=density, format="csr", random_state=seed)
    A = A + sp.eye(n, format="csr")          # a populated diagonal, as assembled
    k = int(rng.integers(0, n))
    rows = np.sort(rng.choice(n, k, replace=False)) if k else np.array([], dtype=int)
    _assert_byte_identical(stamp_dirichlet_rows(A, rows),
                           _lil_reference(A, rows), f"fuzz seed={seed}")


def test_stamping_handles_the_two_degenerate_row_sets():
    """No constrained rows, and every row constrained. Both reachable
    (a mesh with no contacts refuses earlier, but the helper must not
    be the thing that breaks) and both are where an index-mask
    implementation goes wrong."""
    A = (sp.random(12, 12, density=0.3, format="csr", random_state=1)
         + sp.eye(12, format="csr"))
    for rows in (np.array([], dtype=int), np.arange(12)):
        _assert_byte_identical(stamp_dirichlet_rows(A, rows),
                               _lil_reference(A, rows), f"rows={rows.size}")


def test_stamping_does_not_mutate_its_input():
    """The LIL path built a copy; a caller that reuses J -- as the
    current-extraction step does -- must not see a stamped matrix."""
    A = (sp.random(20, 20, density=0.3, format="csr", random_state=2)
         + sp.eye(20, format="csr")).tocsr()
    before = (A.indptr.copy(), A.indices.copy(), A.data.copy())
    stamp_dirichlet_rows(A, np.array([3, 7, 11]))
    assert np.array_equal(A.indptr, before[0])
    assert np.array_equal(A.indices, before[1])
    assert np.array_equal(A.data, before[2])


def test_stamped_rows_really_are_the_unit_row():
    """Byte-identity to the reference is the gate; this asserts the
    reference itself still means what the solver assumes, so a wrong
    ORACLE cannot pass both sides."""
    A = (sp.random(15, 15, density=0.4, format="csr", random_state=3)
         + sp.eye(15, format="csr"))
    rows = np.array([2, 5, 9])
    S = stamp_dirichlet_rows(A, rows).tocsr()
    D = np.asarray(S.todense())
    for k in rows:
        e = np.zeros(15); e[k] = 1.0
        assert np.array_equal(D[k], e), f"row {k} is not e_k"


# ----------------------------------------------------------------------
#  2. the solver indirection
# ----------------------------------------------------------------------
def test_solve_linear_direct_is_bit_identical_to_spsolve(geom):
    """M22's G2 rule, asserted for the exact call shape these cores use:
    a CSC matrix out of eliminate_csr. If solve_linear ever reformats,
    P5-0 silently stops being bit-identical."""
    captured = {}
    raw = ud._residual_jacobian

    def spy(*a, **k):
        out = raw(*a, **k)
        captured.setdefault("FJ", (out[0], out[1]))
        return out

    ud._residual_jacobian = spy
    try:
        ud.solve_bias(*_solve_args(geom), BIAS)
    finally:
        ud._residual_jacobian = raw

    F, J = captured["FJ"]
    N = J.shape[0]
    base = np.arange(0, N // 3, max(1, (N // 3) // 20))
    rows = np.sort(np.concatenate([3 * base + c for c in range(3)]))
    Jc, rhs = eliminate_csr(stamp_dirichlet_rows(J, rows), -F, rows)
    A = Jc.tocsc()
    x_ref = spsolve(A, rhs)
    x_new, info = solve_linear(A, rhs, method="direct")
    assert np.array_equal(x_new, x_ref), "solve_linear != spsolve, bit for bit"
    assert info["method"] == "direct"


# ----------------------------------------------------------------------
#  3. end to end
# ----------------------------------------------------------------------
def test_2d_dd_bias_is_bit_identical_to_the_pre_p50_loop(geom):
    """The whole Newton loop, against a transcription of the pre-P5-0
    body. This is the gate the plan calls P5-0-1."""
    psi, n, p, scale, I = ud.solve_bias(*_solve_args(geom), BIAS)

    # --- transcription of the pre-P5-0 inner block -------------------
    captured = []
    raw_stamp = ud.stamp_dirichlet_rows
    raw_solve = ud.solve_linear

    def old_stamp(J, rows):
        return _lil_reference(J, rows)

    def old_solve(A, b, **kw):
        captured.append(kw.get("method"))
        return spsolve(A, b), {"method": "direct"}

    ud.stamp_dirichlet_rows = old_stamp
    ud.solve_linear = old_solve
    try:
        psi_o, n_o, p_o, scale_o, I_o = ud.solve_bias(*_solve_args(geom), BIAS)
    finally:
        ud.stamp_dirichlet_rows = raw_stamp
        ud.solve_linear = raw_solve

    assert captured and all(m == "direct" for m in captured), \
        "the default path must ask for method='direct'"
    assert np.array_equal(psi, psi_o), "psi moved"
    assert np.array_equal(n, n_o), "n moved"
    assert np.array_equal(p, p_o), "p moved"
    for name in I:
        assert I[name] == I_o[name], f"terminal current {name} moved"
    assert scale["last_converged"] == scale_o["last_converged"]


# ----------------------------------------------------------------------
#  3b. the 3D gate coupling -- a SECOND substitution, gated separately
# ----------------------------------------------------------------------
def test_gate_diagonal_accumulation_matches_the_lil_stamping():
    """`unstructured_dd3d` stamped a gate's Robin coupling one entry at
    a time through a LIL view (`J[k,k] -= gt`); P5-0 accumulates it into
    a diagonal and adds once.

    This is a DIFFERENT substitution from the row stamping and does not
    follow from that gate, so it gets its own. It is bit-identical
    because `d + (-gt)` and `d - gt` are the same IEEE-754 operation --
    but only while each node is touched once per pass, which is what the
    accumulate-then-add form makes true by construction and the
    incremental form made true by luck. A gate whose faces share a node
    (the wrap-around case `unstructured_dd3d`'s own docstring warns
    about) is exactly where the two could part company, so it is
    included below."""
    rng = np.random.default_rng(11)
    n = 40
    A = (sp.random(n, n, density=0.25, format="csr", random_state=11)
         + sp.eye(n, format="csr")).tocsr()

    for label, idx in (("distinct nodes", np.array([3, 8, 15, 22])),
                       ("a repeated node", np.array([3, 8, 8, 15]))):
        gt = rng.uniform(0.1, 5.0, size=idx.size)

        Jl = A.tolil()
        for k, g in zip(idx, gt):
            Jl[k, k] -= g
        old_way = Jl.tocsr()

        diag = np.zeros(n)
        for k, g in zip(idx, gt):
            diag[k] -= g
        new_way = A.tocsr() + sp.diags(diag, format="csr")

        _assert_byte_identical(new_way, old_way, f"gate diagonal, {label}")


def test_3d_poisson_with_a_gate_is_bit_identical_to_the_pre_p50_loop():
    """End to end on the 3D core, including the gate path -- the loop
    that carries BOTH substitutions at once."""
    from pytcad.gmsh_mesh3d import build_gated_slab_mesh3d
    from pytcad.unstructured_assembly3d import (
        build_unstructured_stencil3d, build_edge_flux_geometry3d)
    import pytcad.unstructured_dd3d as ud3

    mesh = build_gated_slab_mesh3d(Lx=1.0e-4, Ly=5.0e-5, Lz=2.5e-5, Na=1e17)
    edge_list, node_vols = build_unstructured_stencil3d(mesh.nodes, mesh.tets)
    edges, trans = build_edge_flux_geometry3d(mesh.nodes, mesh.tets, edge_list)
    C = np.full(mesh.nodes.shape[0], -1e17)
    contacts = {k: v for k, v in mesh.face_tags.items() if "contact" in k}
    gate_faces = next((v for k, v in mesh.face_tags.items() if "gate" in k), None)
    if not contacts or gate_faces is None:
        pytest.skip("the gated slab fixture does not expose contact+gate tags")
    gates = {"gate": {"faces": gate_faces, "tox_cm": 3e-7, "Vfb": 0.0, "Vg": 1.0}}

    args = (mesh.nodes, mesh.tets, edges, node_vols, trans, C, contacts)
    psi, scale = ud3.solve_poisson_equilibrium3d(*args, gates=gates)

    raw_stamp = ud3.stamp_dirichlet_rows
    raw_solve = ud3.solve_linear
    ud3.stamp_dirichlet_rows = lambda J, rows: _lil_reference(J, rows)
    ud3.solve_linear = lambda A, b, **kw: (spsolve(A, b), {"method": "direct"})
    try:
        psi_o, scale_o = ud3.solve_poisson_equilibrium3d(*args, gates=gates)
    finally:
        ud3.stamp_dirichlet_rows = raw_stamp
        ud3.solve_linear = raw_solve

    assert np.array_equal(psi, psi_o), "3D gated psi moved"


# ----------------------------------------------------------------------
#  4. the capability P5-0 exists to unlock
# ----------------------------------------------------------------------
def test_krylov_methods_now_reach_the_unstructured_core(geom):
    """Before P5-0 these cores called spsolve directly, so
    NewtonOptions.linsolve was silently ignored. A tolerance gate, not
    bit-identity: a Krylov solve is a different computation."""
    psi_d, n_d, p_d, _, I_d = ud.solve_bias(
        *_solve_args(geom), BIAS, opts=NewtonOptions(linsolve="direct"))
    psi_g, n_g, p_g, _, I_g = ud.solve_bias(
        *_solve_args(geom), BIAS,
        opts=NewtonOptions(linsolve="gmres", linsolve_rtol=1e-12))

    assert np.allclose(psi_g, psi_d, rtol=1e-6, atol=1e-9)
    assert np.allclose(n_g, n_d, rtol=1e-5, atol=0.0)
    for name in I_d:
        assert I_g[name] == pytest.approx(I_d[name], rel=1e-4)


def test_an_unknown_linsolve_method_is_refused_not_ignored(geom):
    """The failure mode P5-0 replaces was silence: an option that did
    nothing. A bad method must now raise."""
    with pytest.raises(ValueError, match="unknown method"):
        ud.solve_bias(*_solve_args(geom), BIAS,
                      opts=NewtonOptions(linsolve="nonesuch"))
