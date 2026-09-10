"""Symmetric elimination of Dirichlet constraints from a Newton system.

WHAT THIS REPLACES, AND WHY IT IS NOT A STYLE CHANGE
----------------------------------------------------
Every solver core in this tree used to impose a Dirichlet contact by
eliminating the ROW only:

    J[k, :] = 0.0
    J[k, k]  = 1.0            # then solve J du = -F

That is correct -- `du[k]` comes out as `-F[k]`, which is the wanted
value -- and it is what produced every golden in `tests/goldens/`.  What
it is not is TRANSPOSABLE.  Row elimination leaves the column entries
`J[i, k]` (i not constrained) in place, so `J^T` has those as ROW
entries and does not impose the same constraint on the adjoint problem.
An adjoint/sensitivity solve applies `J^T`; PETSc gives that essentially
free for MATAIJ/MATBAIJ, but only if the assembly has not baked in
something that destroys it, and row elimination is exactly that.

`M31-CPP-ARCHITECTURE-PLAN.md`'s P5 addendum flags this: the decision is
free until the C++ assembler lands and a rewrite afterwards.  This module
makes the Python path symmetric FIRST, so that when P5 ports the
assembler it has a bit-identical oracle for the very piece that changed.

THE SUBSTITUTION, AND WHY IT IS EXACT
-------------------------------------
Write the constrained system with D the set of constrained indices and
`g_k` the known update there (`g_k = rhs[k]`, since the constrained row
is already `e_k`):

    row k in D    :  du_k = g_k
    row i not in D:  sum_j  J[i,j] du_j = rhs[i]

Substituting the known `du_k` out of the second line gives

    row i not in D:  sum_{j not in D} J[i,j] du_j
                        = rhs[i] - sum_{k in D} J[i,k] g_k

which is the SAME system -- the same solution, exactly, in exact
arithmetic -- with the known values moved to the right-hand side and the
constrained columns now empty.  Nothing is approximated, dropped or
lumped: this is substitution, not a modified boundary condition.

So the physics and the BC semantics are unchanged by construction. What
DOES change is the floating-point path: a different matrix reaches
SuperLU, which pivots differently, so results move at the 1e-16 level.
That is why this lands as its own change with a deliberate golden
re-baseline rather than riding along inside a larger one.

THREE ENTRY POINTS
------------------
`stamp_dirichlet_rows` performs the step that comes FIRST -- making each
constrained row the unit row -- which the cores used to do through a LIL
conversion.  It is a pure performance change, gated byte-identical; see
its own docstring.

The other two:

`eliminate_coo` works on the (rows, cols, vals) triplets most cores
already build, and is the cheap path -- it never materializes an
intermediate matrix.  `eliminate_csr` works on an assembled matrix, for
the cores that build one before constraining it.  Both leave the
constrained row as `e_k` with `rhs[k] = g_k`, so a caller's downstream
code (which reads `du[k]`) is unaffected.
"""
import numpy as np
import scipy.sparse as sp


def _mask(n, dirichlet):
    m = np.zeros(n, dtype=bool)
    m[dirichlet] = True
    return m


def eliminate_coo(rows, cols, vals, rhs, dirichlet, n=None):
    """Symmetrically eliminate `dirichlet` indices from COO triplets.

    The caller has already stamped the constrained rows: row k contains
    exactly the unit diagonal, and `rhs[k]` is the known update `g_k`.
    This removes the constrained COLUMNS, folding their contribution
    into `rhs`.

    Returns `(rows, cols, vals, rhs)` -- new arrays, the caller's
    untouched.  Building the matrix stays the caller's job because the
    cores disagree about the format they want it in.
    """
    rows = np.asarray(rows)
    cols = np.asarray(cols)
    vals = np.asarray(vals, dtype=float)
    rhs = np.array(rhs, dtype=float, copy=True)
    n = int(rhs.shape[0]) if n is None else int(n)

    is_d = _mask(n, dirichlet)
    if not is_d.any():
        return rows, cols, vals, rhs

    # An entry contributes to the substitution iff it sits in a
    # constrained COLUMN of an UNCONSTRAINED row. Entries in constrained
    # rows are the unit diagonal we must keep; entries in unconstrained
    # columns are the system we are still solving.
    in_d_col = is_d[cols]
    move = in_d_col & ~is_d[rows]

    if move.any():
        # rhs[i] -= J[i,k] * g_k, accumulated in index order. np.add.at
        # is used rather than a bincount so that repeated (i,k) triplets
        # -- which the cores DO emit, since they `add()` contributions
        # incrementally -- are all counted.
        np.add.at(rhs, rows[move], -vals[move] * rhs[cols[move]])

    # Drop every entry in a constrained column, including the ones in
    # constrained rows: the unit diagonal is re-added by the caller's
    # own stamping, and dropping then re-adding would be fragile. Keep
    # the diagonal entries that are already there.
    keep = ~in_d_col | (is_d[rows] & (rows == cols))
    return rows[keep], cols[keep], vals[keep], rhs


def stamp_dirichlet_rows(J, dirichlet):
    """Replace each `dirichlet` row of `J` with the unit row `e_k`.

    This is the step every core performs before `eliminate_*`: the
    constrained row must read `du_k = g_k`, so it carries exactly the
    unit diagonal and nothing else.

    WHY THIS EXISTS RATHER THAN `J.tolil()` (M31 P5-0)
    --------------------------------------------------
    Every core used to do

        Jl = J.tolil()
        Jl[rows, :] = 0.0
        Jl[rows, rows] = 1.0

    which is correct and was measurably expensive: LIL row assignment
    goes through `ndarray.tolist` per row (~66k calls per solve on the
    B8 benchmark), and the whole block was 115 ms of a 440 ms Newton
    iteration on B8 at full size -- more than four times the cost of
    the assembly M31 P5 was proposing to port to C++.  Measured on the
    same fixture, this construction is **44.8x** faster (115.4 ms ->
    2.6 ms) and BYTE-identical: same indptr, same indices, same data.

    Byte-identity is not incidental, it is the whole point.  Left
    multiplication by a 0/1 diagonal scales every surviving entry by
    exactly 1.0 (an exact operation, not an approximate one) and drops
    the constrained rows structurally, which is what LIL assignment
    also did; adding the unit diagonal back is then exact.  Gated in
    `tests/test_m31_p50_unstructured_linsolve.py` against a
    transcription of the LIL body, on a real assembled Jacobian and
    under a fuzz.

    Returns a new CSR matrix; `J` is not modified.
    """
    n = J.shape[0]
    is_d = _mask(n, dirichlet)
    keep_rows = sp.diags((~is_d).astype(float), format="csr")
    return (keep_rows @ J.tocsr()) + sp.diags(is_d.astype(float),
                                              format="csr")


def eliminate_csr(J, rhs, dirichlet):
    """Symmetrically eliminate `dirichlet` indices from an assembled `J`.

    Same contract as `eliminate_coo`: the constrained rows are already
    `e_k` and `rhs[k]` already holds the known update. Returns
    `(J, rhs)`, both new.
    """
    n = J.shape[0]
    rhs = np.array(rhs, dtype=float, copy=True)
    is_d = _mask(n, dirichlet)
    if not is_d.any():
        return J.tocsr(), rhs

    g = np.zeros(n, dtype=float)
    g[is_d] = rhs[is_d]

    Jc = J.tocsr()
    # J @ g touches only constrained columns because g is zero
    # elsewhere -- so this IS sum_k J[i,k] g_k, without slicing out a
    # submatrix.
    correction = Jc @ g
    rhs = rhs - correction
    # The constrained rows are e_k, so their correction was exactly
    # g_k; restore them rather than special-casing the product.
    rhs[is_d] = g[is_d]

    # Zero the constrained columns, keeping the unit diagonal.
    keep_cols = sp.diags((~is_d).astype(float), format="csr")
    Jout = Jc @ keep_cols
    Jout = Jout + sp.diags(is_d.astype(float), format="csr")
    return Jout.tocsr(), rhs
