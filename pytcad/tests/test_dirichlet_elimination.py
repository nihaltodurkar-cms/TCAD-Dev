"""Gates for symmetric Dirichlet elimination (pytcad/dirichlet.py).

The claim this module rests on is that symmetric elimination is a
SUBSTITUTION, not a modified boundary condition: it solves the same
system, so the answer is the same and only the floating-point path
differs. That claim is what these tests check, and they check it before
any solver core uses the helper.

Two properties matter and they pull in opposite directions:

  * the SOLUTION must match row-only elimination to solver precision
    (it is the same system);
  * the MATRIX must not match -- the whole point is that the constrained
    columns are gone, which is what makes J^T impose the same
    constraint.

A test suite that only checked the first would pass on a no-op.
"""
import numpy as np
import pytest
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve

from pytcad.dirichlet import eliminate_coo, eliminate_csr


def _system(n=40, seed=0, n_dirichlet=6):
    """A random, diagonally-dominant system with some rows already
    stamped as Dirichlet (unit diagonal, known value in the rhs) --
    the exact shape every core hands the helper."""
    rng = np.random.default_rng(seed)
    A = sp.random(n, n, density=0.2, random_state=rng,
                  data_rvs=lambda k: rng.standard_normal(k)).tolil()
    A.setdiag(np.abs(A).sum(axis=1).A1 + 1.0)
    rhs = rng.standard_normal(n)

    dirichlet = np.sort(rng.choice(n, size=n_dirichlet, replace=False))
    for k in dirichlet:                       # row-only elimination
        A[k, :] = 0.0
        A[k, k] = 1.0
    return A.tocsr(), rhs, dirichlet


def _as_coo(A):
    C = A.tocoo()
    return C.row.copy(), C.col.copy(), C.data.copy()


# ----------------------------------------------------------------------
#  the substitution is exact
# ----------------------------------------------------------------------
@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_csr_elimination_solves_the_same_system(seed):
    A, rhs, d = _system(seed=seed)
    ref = spsolve(A.tocsc(), rhs)

    A2, rhs2 = eliminate_csr(A, rhs, d)
    got = spsolve(A2.tocsc(), rhs2)

    assert np.allclose(got, ref, rtol=1e-12, atol=1e-14), \
        f"max |diff| = {np.abs(got - ref).max():.3e}"


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_coo_elimination_solves_the_same_system(seed):
    A, rhs, d = _system(seed=seed)
    ref = spsolve(A.tocsc(), rhs)

    r, c, v = _as_coo(A)
    r2, c2, v2, rhs2 = eliminate_coo(r, c, v, rhs, d, n=A.shape[0])
    A2 = sp.coo_matrix((v2, (r2, c2)), shape=A.shape).tocsc()
    got = spsolve(A2, rhs2)

    assert np.allclose(got, ref, rtol=1e-12, atol=1e-14), \
        f"max |diff| = {np.abs(got - ref).max():.3e}"


def test_the_two_entry_points_agree_with_each_other():
    A, rhs, d = _system(seed=7)
    A_csr, rhs_csr = eliminate_csr(A, rhs, d)

    r, c, v = _as_coo(A)
    r2, c2, v2, rhs_coo = eliminate_coo(r, c, v, rhs, d, n=A.shape[0])
    A_coo = sp.coo_matrix((v2, (r2, c2)), shape=A.shape).tocsr()

    assert np.allclose(rhs_csr, rhs_coo, rtol=1e-13, atol=1e-15)
    assert np.abs((A_csr - A_coo)).max() < 1e-15


def test_repeated_triplets_are_all_counted():
    """The cores build their matrices by incremental `add()` calls, so
    the same (i, j) appears several times. A substitution that used
    bincount-style deduplication would silently drop all but one."""
    n = 4
    rows = np.array([1, 1, 1, 0, 2, 3])
    cols = np.array([0, 0, 0, 0, 2, 3])       # three entries at (1, 0)
    vals = np.array([2.0, 3.0, 5.0, 1.0, 1.0, 1.0])
    rhs = np.array([7.0, 0.0, 0.0, 0.0])      # g_0 = 7
    _, _, _, rhs2 = eliminate_coo(rows, cols, vals, rhs, [0], n=n)
    # row 1 must lose (2+3+5) * 7 = 70
    assert rhs2[1] == pytest.approx(-70.0)


# ----------------------------------------------------------------------
#  ... and it actually changes the matrix (this is the point)
# ----------------------------------------------------------------------
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_the_constrained_columns_are_actually_gone(seed):
    A, rhs, d = _system(seed=seed)
    before = np.abs(A.tocsc()[:, d]).sum()
    assert before > 0, "fixture has no column coupling -- test proves nothing"

    A2, _ = eliminate_csr(A, rhs, d)
    col = A2.tocsc()[:, d]
    # Only the unit diagonal may remain in a constrained column.
    assert col.nnz == len(d)
    assert np.allclose(col.sum(), len(d))


def test_the_result_is_transposable():
    """The reason the change exists: J^T must impose the SAME constraint
    on the adjoint problem. After row-only elimination it does not."""
    A, rhs, d = _system(seed=3)

    # row-only: the transpose's constrained rows are NOT e_k
    rowonly_T = A.T.tocsr()[d, :]
    off = np.abs(rowonly_T).sum() - len(d)
    assert off > 1e-6, "fixture does not exhibit the defect"

    A2, _ = eliminate_csr(A, rhs, d)
    sym_T = A2.T.tocsr()[d, :]
    assert sym_T.nnz == len(d)
    assert np.allclose(sym_T.sum(), len(d))


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_transpose_solve_matches_a_dense_reference(seed):
    """P5 adjoint-readiness gate 1, on the Python path: `J^T x` from the
    symmetric assembly matches a dense-transpose reference."""
    A, rhs, d = _system(n=30, seed=seed)
    A2, _ = eliminate_csr(A, rhs, d)

    rng = np.random.default_rng(seed)
    x = rng.standard_normal(A2.shape[0])
    got = A2.T @ x
    ref = np.asarray(A2.todense()).T @ x
    assert np.allclose(got, ref, rtol=1e-12, atol=1e-14)


# ----------------------------------------------------------------------
#  degenerate inputs
# ----------------------------------------------------------------------
def test_no_constraints_is_a_no_op():
    A, rhs, _ = _system(seed=5, n_dirichlet=0)
    A2, rhs2 = eliminate_csr(A, rhs, [])
    assert np.array_equal(rhs2, rhs)
    assert np.abs(A2 - A.tocsr()).max() == 0.0

    r, c, v = _as_coo(A)
    r2, c2, v2, rhs3 = eliminate_coo(r, c, v, rhs, [], n=A.shape[0])
    assert np.array_equal(rhs3, rhs)
    assert np.array_equal(v2, v)


def test_the_callers_arrays_are_never_mutated():
    A, rhs, d = _system(seed=6)
    r, c, v = _as_coo(A)
    rhs_before = rhs.copy()
    v_before = v.copy()

    eliminate_coo(r, c, v, rhs, d, n=A.shape[0])
    eliminate_csr(A, rhs, d)

    assert np.array_equal(rhs, rhs_before)
    assert np.array_equal(v, v_before)


def test_every_index_constrained():
    """Degenerate but reachable: a system where every unknown is pinned
    must come back as the identity with the rhs untouched."""
    n = 5
    A = sp.identity(n, format="csr")
    rhs = np.arange(n, dtype=float)
    A2, rhs2 = eliminate_csr(A, rhs, np.arange(n))
    assert np.array_equal(rhs2, rhs)
    assert np.allclose(A2.todense(), np.eye(n))


# ----------------------------------------------------------------------
#  on a REAL device Jacobian: M31 P5 adjoint-readiness gate 1
# ----------------------------------------------------------------------
def _biased_device():
    from pytcad import Device1D, Models
    from pytcad.mesh import uniform_mesh
    x = uniform_mesh(2.0e-4, 60)
    dev = Device1D(x, np.where(x < 1.0e-4, -1e17, 1e17),
                   models=Models(srh=True))
    dev.solve_equilibrium()
    dev.solve_bias([0.4, 0.0])
    return dev


def test_real_device_jacobian_is_transposable():
    """`M31-CPP-ARCHITECTURE-PLAN.md`'s P5 addendum, gate 1, on the
    Python path: the assembled Jacobian's transpose must impose the SAME
    constraint on the adjoint problem.

    The fixture asserts the defect exists before the fix is applied, so
    this cannot pass vacuously on a matrix that never had column
    coupling in the first place.
    """
    dev = _biased_device()
    F, J, _, _ = dev._residual_jacobian(
        dev.psi, dev.n, dev.p, dev._contact_values([0.4, 0.0]))
    d = dev._dirichlet_rows
    assert len(d) == 6, "1D has psi/n/p Dirichlet at both contacts"

    # Row-only elimination: J^T's constrained rows are NOT e_k.
    assert J.T.tocsr()[d, :].nnz > len(d), \
        "fixture does not exhibit the defect -- test proves nothing"

    Jd, _ = eliminate_csr(J, -F, d)
    sym = Jd.T.tocsr()[d, :]
    assert sym.nnz == len(d)
    assert np.allclose(sym.sum(), len(d))


def test_real_device_transpose_matches_dense_reference():
    """P5 gate 1's numeric half: J^T x from the assembler matches a
    dense-transpose reference."""
    dev = _biased_device()
    F, J, _, _ = dev._residual_jacobian(
        dev.psi, dev.n, dev.p, dev._contact_values([0.4, 0.0]))
    Jd, _ = eliminate_csr(J, -F, dev._dirichlet_rows)

    x = np.random.default_rng(0).standard_normal(Jd.shape[0])
    got = Jd.T @ x
    ref = np.asarray(Jd.todense()).T @ x
    assert np.allclose(got, ref, rtol=1e-12, atol=1e-12)


def test_robin_rows_are_never_eliminated():
    """M14's S_n/S_p surface recombination replaces the Dirichlet
    density rows with a Robin flux balance. A Robin row is an EQUATION,
    not a constraint -- eliminating its column would delete real
    physics. The recorded Dirichlet set must shrink accordingly."""
    from pytcad import Device1D, Models
    from pytcad.mesh import uniform_mesh
    x = uniform_mesh(2.0e-4, 40)
    dop = np.where(x < 1.0e-4, -1e17, 1e17)

    plain = Device1D(x, dop, models=Models(srh=True))
    plain.solve_equilibrium()
    plain._residual_jacobian(plain.psi, plain.n, plain.p,
                             plain._contact_values([0.0, 0.0]))
    assert len(plain._dirichlet_rows) == 6      # psi, n, p at both ends

    robin = Device1D(x, dop, models=Models(srh=True, S_n=1e4, S_p=1e4))
    robin.solve_equilibrium()
    robin._residual_jacobian(robin.psi, robin.n, robin.p,
                             robin._contact_values([0.0, 0.0]))
    assert len(robin._dirichlet_rows) == 2, \
        "only the two psi rows stay Dirichlet when S_n/S_p != 0"
    assert set(robin._dirichlet_rows) == {0, 3 * (x.size - 1)}
