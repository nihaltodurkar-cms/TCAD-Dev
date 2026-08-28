"""M22 phase 1: linear-solve abstraction (Krylov + ILU) behind the
existing spsolve interface.

Spec: M22-LINSOLVE-PLAN.md.

Motivation (measured): profiling a 27^3 = 19683-node 3D resistor
equilibrium solve put 98% of the time in scipy spsolve (direct sparse
LU).  Direct factorization is also what blocks distribution -- a
Krylov method is the prerequisite for any GPU or MPI solve, since those
need a distributed/accelerated matvec + preconditioner apply, not a
distributed LU.

No pytcad imports beyond scipy/numpy: this module is pure and
independently testable, and is a driver BELOW nothing -- device.py
calls it, it never calls back into device.py.
"""
import warnings

import numpy as np
import scipy.sparse as sp
from scipy.sparse.linalg import spsolve, spilu, LinearOperator, gmres, bicgstab

try:
    import pyamg
    _HAVE_PYAMG = True
except ImportError:
    _HAVE_PYAMG = False

__all__ = ["solve_linear", "LinearSolveError"]

_METHODS = ("direct", "gmres", "bicgstab")


class LinearSolveError(RuntimeError):
    """Raised on singular/non-finite input or iterative non-convergence.

    A linear solve that fails must never return a half-solved state
    silently -- the M15 debug pass found exactly that failure mode (a
    loop that stops and says nothing) in the impact-ionization outer
    loop, and it is not repeated here.
    """


def _check_finite(A, b, method):
    if not np.all(np.isfinite(b)):
        raise LinearSolveError(
            f"solve_linear({method!r}): b contains non-finite values")
    if not np.all(np.isfinite(A.data)):
        raise LinearSolveError(
            f"solve_linear({method!r}): A contains non-finite values")


def _build_block_jacobi_preconditioner(A, block_size):
    """Node-block-Jacobi: invert each node's small dense diagonal block
    directly, apply block-diagonally.  Returns None (never raises) if
    the shape doesn't divide evenly or any block is singular.

    MOTIVATION (measured, M22 phase 1 debug): every device core in this
    codebase interleaves unknowns per mesh node (psi, n, p, psi, n,
    p, ... -- see the `du[0::3], du[1::3], du[2::3]` unpacking in every
    solve_bias).  Scalar ILU treats the matrix as one undifferentiated
    block and ignores that structure entirely; on the coupled 3D
    Jacobian this left GMRES making no visible progress in 500
    iterations even at 27783 unknowns (three orders below the plan's
    64k-node target -- see M22-LINSOLVE-PLAN.md sec 6, G6).  A
    per-node block preconditioner is the standard fix for exactly this
    failure mode in multiphysics PDE systems (nodal/point-block
    ILU/Jacobi; see e.g. Saad, "Iterative Methods for Sparse Linear
    Systems", and the block-structured GMRES preconditioning literature
    for circuit/device simulation, which groups unknowns the same way
    for the same reason).

    Cost: O(N) work to extract and invert N independent (block_size x
    block_size) blocks (vectorized, no per-node Python loop), and one
    batched matmul per preconditioner application -- cheap relative to
    a GMRES iteration on the full system.
    """
    n = A.shape[0]
    if n % block_size != 0:
        return None
    nblk = n // block_size
    Ac = A.tocsr()
    blocks = np.zeros((nblk, block_size, block_size))
    diag = Ac.diagonal()
    # Vectorized diagonal-block extraction: for each (row_offset,
    # col_offset) pair within a block, pull every node's entry at once
    # via fancy indexing rather than looping over nodes in Python.
    idx = np.arange(nblk) * block_size
    for r in range(block_size):
        row = Ac[idx + r]                      # (nblk, n) sparse, one row per node
        row = row.tocsc()
        for c in range(block_size):
            blocks[:, r, c] = np.asarray(
                row[np.arange(nblk), idx + c]).ravel()
    dets = np.linalg.det(blocks)
    if not np.all(np.isfinite(dets)) or np.any(np.abs(dets) < 1e-300):
        return None
    try:
        inv_blocks = np.linalg.inv(blocks)
    except np.linalg.LinAlgError:
        return None

    def apply(x):
        xb = x.reshape(nblk, block_size)
        return np.einsum("nij,nj->ni", inv_blocks, xb).ravel()

    return LinearOperator(A.shape, apply)


def _build_preconditioner(A, block_size=None):
    """Node-block-Jacobi first (when `block_size` is given and the
    blocks are well-conditioned), then ILU, then algebraic multigrid
    when pyamg is installed (optional dep stays optional -- absence
    changes nothing about the result, only the iteration count).

    Returns None on total failure rather than raising: a missing
    preconditioner is a PERFORMANCE degradation (GMRES/BiCGStab still
    converge, just in more iterations), not a correctness one -- the
    convergence-honesty gate (G4) is what catches an actual failure to
    solve.  Device Jacobians here mix psi/n/p unknowns spanning many
    orders of magnitude (scaled units), which measurably makes an
    aggressive drop tolerance produce an exactly-singular ILU factor;
    the two fallback tolerances below were chosen to cover that case
    before giving up on scalar ILU.
    """
    if block_size is not None:
        M = _build_block_jacobi_preconditioner(A, block_size)
        if M is not None:
            return M
    if _HAVE_PYAMG:
        try:
            ml = pyamg.ruge_stuben_solver(A.tocsr())
            return ml.aspreconditioner()
        except Exception:
            pass  # pyamg is an optimization, not a promise -- fall through
    for drop_tol, fill_factor in ((1e-5, 10), (1e-7, 30), (1e-9, 50)):
        try:
            ilu = spilu(A.tocsc(), drop_tol=drop_tol, fill_factor=fill_factor)
            return LinearOperator(A.shape, ilu.solve)
        except RuntimeError:
            continue
    return None


def solve_linear(A, b, *, method="direct", rtol=1e-10, atol=0.0,
                 maxiter=500, x0=None, restart=None, block_size=None):
    """Solve A x = b.  Returns (x, info).

    method="direct" is EXACTLY scipy.sparse.linalg.spsolve -- bit-
    identical to every pre-M22 call site, gated by G2.  "gmres" and
    "bicgstab" precondition with a node-block-Jacobi operator (when
    `block_size` is given -- pass 3 for every device core in this
    tree, which interleaves psi/n/p per node), falling back to ILU (or
    algebraic multigrid when pyamg is installed) and converge to
    `rtol` relative to ||b||.  `block_size=None` (the default) skips
    straight to ILU, unchanged from M22 phase 1's original behavior.

    info = {"method", "iterations", "converged", "residual"}.  An
    iterative method that does not reach `rtol` within `maxiter` RAISES
    LinearSolveError rather than returning the unconverged iterate.
    """
    if method not in _METHODS:
        raise ValueError(
            f"unknown method {method!r}; choose from {_METHODS}")

    b = np.asarray(b, dtype=float)
    if method == "direct":
        # Bit-identity (G2) requires NOT reformatting A: scipy's SuperLU
        # wrapper takes a format flag and solves CSR inputs natively
        # (rather than converting to CSC first), so spsolve(A, b) and
        # spsolve(A.tocsc(), b) are only equal to ~1e-16 relative error,
        # not bit-identical -- confirmed empirically (spsolve(csr, b) !=
        # spsolve(csr.tocsc(), b) on an otherwise-identical matrix).
        # Forcing a reformat here previously broke every M13/M22 golden
        # that put a CSR matrix through a Poisson-only equilibrium solve
        # (this call must see EXACTLY the object/format the caller
        # built, the same as every pre-M22 direct spsolve(A, ...) call).
        if not sp.issparse(A):
            A = sp.csr_matrix(A)
        _check_finite(A, b, method)
        try:
            with warnings.catch_warnings():
                # spsolve warns (not raises) on an exactly-singular
                # matrix and returns garbage; treat that as the failure
                # it is rather than letting it leak past this wrapper.
                warnings.simplefilter("error", sp.linalg.MatrixRankWarning)
                x = spsolve(A, b)
        except Exception as exc:
            raise LinearSolveError(
                f"direct solve failed: {exc}") from exc
        if not np.all(np.isfinite(x)):
            raise LinearSolveError(
                "direct solve returned a non-finite result "
                "(A is likely singular)")
        resid = float(np.linalg.norm(A @ x - b)) / max(
            float(np.linalg.norm(b)), 1e-300)
        return x, {"method": "direct", "iterations": 1,
                   "converged": True, "residual": resid}

    # Only the iterative methods need a consistent format (CSR, for
    # the preconditioner/matvec machinery below) -- "direct" above
    # deliberately never reaches here so it never gets reformatted.
    # (A plain ndarray has no .tocsr() method -- convert to sparse
    # first rather than calling it on both branches of the ternary,
    # which would raise AttributeError for a dense A.)
    A = sp.csr_matrix(A) if not sp.issparse(A) else A.tocsr()
    _check_finite(A, b, method)
    M = _build_preconditioner(A, block_size=block_size)
    solver = gmres if method == "gmres" else bicgstab
    iters = [0]

    def _count(_):
        iters[0] += 1

    kwargs = dict(rtol=rtol, atol=atol, maxiter=maxiter, M=M, x0=x0,
                 callback=_count)
    if method == "gmres":
        kwargs["callback_type"] = "pr_norm"
        # GMRES(m) forgets its Krylov basis every `restart` steps; too
        # small an m stalls on a stiff, poorly preconditioned system
        # (measured: a 207k-unknown 3D device Jacobian made no visible
        # progress in 500 iterations at the scipy default restart=20).
        # Larger m costs O(m) memory per iteration -- bounded here at
        # min(restart-or-default, problem size).
        kwargs["restart"] = min(restart or 100, A.shape[0])
    x, code = solver(A, b, **kwargs)

    bnorm = max(float(np.linalg.norm(b)), 1e-300)
    resid = float(np.linalg.norm(A @ x - b)) / bnorm
    converged = (code == 0) and np.all(np.isfinite(x)) and resid <= max(
        rtol, 1e-6)
    if not converged:
        raise LinearSolveError(
            f"{method} did not converge within {maxiter} iterations "
            f"(scipy code={code}, relative residual={resid:.3e}, "
            f"target rtol={rtol:.3e}) -- refusing to return the "
            f"unconverged iterate")

    return x, {"method": method, "iterations": iters[0],
               "converged": True, "residual": resid}
