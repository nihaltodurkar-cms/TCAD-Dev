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

# GPU direct sparse solve (cuSOLVER via CuPy) -- confirmed directly on a
# real device Jacobian (bjt_3d's 121824-unknown coupled bias solve):
# 2.8x faster than scipy spsolve on that matrix (130.9s -> 46.1s),
# agreeing to a relative error of ~1e-17, and unlike every Krylov
# method tried in this file, a DIRECT solve has no convergence-failure
# mode to guard against. But the same GPU transfer/kernel-launch
# overhead that this buys nothing on a small matrix: measured 0.4-3x
# SLOWER than CPU spsolve below ~50,000 unknowns (resistor_3d,
# moscap_3d, jfet_3d), roughly break-even at mosfet_3d's 47,304, and a
# clear win from pn_junction_3d's 99,360 unknowns up. Callers (gui/
# services/solver_runner.py) gate on mesh size before requesting this;
# absence of cupy changes nothing here beyond this method not being
# offered -- optional dep stays optional, same as pyamg above.
try:
    import cupy as _cupy
    import cupyx.scipy.sparse as _cusp
    import cupyx.scipy.sparse.linalg as _cuspla
    _HAVE_CUPY = True
except ImportError:
    _HAVE_CUPY = False

__all__ = ["solve_linear", "LinearSolveError"]

_METHODS = ("direct", "gmres", "bicgstab", "gpu_direct")

# Preconditioner flavor selector values (solve_linear `precond=`).
_PRECOND = ("auto", "block_jacobi", "schur")


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


def _build_schur_preconditioner(A, block_size=3):
    """Physics-structured block-triangular (Schur-style) preconditioner.

    M22-LINSOLVE-PLAN.md section 7's flagged next step beyond plain node
    block-Jacobi: respect the EQUATION structure, not just the node
    grouping.  With the unknowns interleaved per node as (psi, n, p),
    permute to equation-major order (all-psi | all-n | all-p):

        J = [[A_pp, A_pn, A_pq],      (row: Poisson)
             [A_np, A_nn, A_nq],      (row: electron continuity)
             [A_qp, A_qn, A_qq]]      (row: hole continuity)

    The Poisson block A_pp is the stiffest, best-conditioned equation
    (symmetric-positive-definite-like Laplacian + reaction); the
    literature's approximate-block-factorization lesson (plan sec 7,
    Sandia-line AMG-for-DD work) is to eliminate it FIRST.  We build the
    block-LOWER-TRIANGULAR approximation

        M = [[A_pp,      0,      0   ],
             [A_np,  D_nn,        0   ],
             [A_qp,      0,   D_qq]],

    where A_pp is applied via ILU (spilu on the permuted Poisson block
    alone -- far better conditioned than the coupled matrix, so the
    3-tier tolerance chain is not needed) and D_nn/D_qq are the per-node
    density-block diagonal approximations solved exactly (node-block
    Jacobi restricted to the density rows -- the density equations are
    dominated by their diagonal SG/recombination terms, the same
    observation that made full node-block-Jacobi work).  Applying M^-1
    is three triangular solves: psi via ILU, then each density block
    minus its coupling to the psi solve.  This is an approximate
    Schur/Lower-block factorization: the (n,p)-coupling blocks A_nq/
    A_qn are dropped (they enter only through the outer Krylov
    iteration), which is the standard price of a preconditioner.

    Returns None on any structural failure (shape mismatch, singular
    block, ILU failure) -- callers fall through to the next candidate.
    """
    n = A.shape[0]
    if block_size != 3 or n % block_size != 0:
        return None
    nnode = n // block_size
    Ac = A.tocsr()

    # --- permutation to equation-major order: [all psi | all n | all p]
    # interleaved index of unknown k: node = k//3, var = k%3 (0=psi,1=n,2=p)
    k = np.arange(n)
    node, var = k // block_size, k % block_size
    perm = var * nnode + node          # equation-major position
    P = sp.csr_matrix((np.ones(n), (perm, k)), shape=(n, n))
    Ap = (P @ Ac @ P.T).tocsr()        # permuted Jacobian

    # --- extract the diagonal blocks (row-slice then column-slice;
    # scipy sparse fancy indexing takes 1-D index arrays, not np.ix_)
    def _block(rows, cols):
        return Ap[rows][:, cols].tocsc()

    psi_idx = np.arange(nnode)
    n_idx = np.arange(nnode, 2 * nnode)
    p_idx = np.arange(2 * nnode, n)

    A_pp = _block(psi_idx, psi_idx)
    A_np = _block(n_idx, psi_idx)
    A_qp = _block(p_idx, psi_idx)
    # Density diagonal approximations: the per-node diagonal entries of
    # the permuted density blocks, via the matrix diagonal (paired
    # fancy-indexing on sparse rows is fragile across scipy versions).
    diag_all = Ap.diagonal()
    Ann_d = diag_all[nnode:2 * nnode]
    Aqq_d = diag_all[2 * nnode:]

    if np.any(~np.isfinite(Ann_d)) or np.any(~np.isfinite(Aqq_d)):
        return None
    if np.any(np.abs(Ann_d) < 1e-300) or np.any(np.abs(Aqq_d) < 1e-300):
        return None

    try:
        ilu_pp = spilu(A_pp, drop_tol=1e-6, fill_factor=20)
    except (RuntimeError, ValueError):
        return None

    def apply(x):
        # x, y in EQUATION-MAJOR order internally; caller passes
        # interleaved order, so permute on entry and exit.
        xe = P @ x
        # 1. psi solve: A_pp dpsi = xe[:nnode]
        dpsi = ilu_pp.solve(xe[:nnode])
        # 2. density solves minus the psi coupling
        dn = (xe[nnode:2 * nnode] - A_np @ dpsi) / Ann_d
        dp = (xe[2 * nnode:] - A_qp @ dpsi) / Aqq_d
        ye = np.concatenate([dpsi, dn, dp])
        return P.T @ ye

    return LinearOperator(A.shape, apply)


def _build_preconditioner(A, block_size=None, precond="auto"):
    """Physics-structured first (when requested and structurally
    possible), then node block-Jacobi, then ILU, then algebraic
    multigrid when pyamg is installed (optional dep stays optional --
    absence changes nothing about the result, only the iteration count).

    `precond` selects the flavor: "auto" (the default -- UNCHANGED M22
    phase-1 behavior: node block-Jacobi when `block_size` is given,
    else the ILU chain), "block_jacobi" (force the node-block path),
    or "schur" (the equation-structured Schur-style factorization of
    plan section 7; falls through the chain on structural failure).

    """
    if precond == "schur" and block_size is not None:
        M = _build_schur_preconditioner(A, block_size)
        if M is not None:
            return M
    if block_size is not None and precond in ("auto", "block_jacobi"):
        M = _build_block_jacobi_preconditioner(A, block_size)
        if M is not None:
            return M
    if _HAVE_PYAMG:
        try:
            ml = pyamg.ruge_stuben_solver(A.tocsr())
            M = ml.aspreconditioner()
            # Confirmed directly: pyamg's coarsening can SUCCEED (no
            # exception) while producing a degenerate hierarchy on a
            # matrix its Ruge-Stuben algorithm isn't suited to -- an
            # interleaved multi-physics (psi/n/p) system with no
            # block_size given to guide it, as opposed to the scalar
            # (one-unknown-per-node) systems it handles well. The
            # failure then only shows up later, as NaN, the first time
            # the preconditioner is actually APPLIED inside gmres/
            # bicgstab's matvec loop -- past this function's own
            # try/except, so it was reaching the caller as an
            # unhandled NaN/pinv crash instead of the documented
            # LinearSolveError contract. One matvec on an all-ones
            # probe vector here catches that before this preconditioner
            # is ever returned, so a bad hierarchy falls through to ILU
            # exactly like a construction-time exception already does.
            probe = M.matvec(np.ones(A.shape[0]))
            if np.all(np.isfinite(probe)):
                return M
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
                 maxiter=500, x0=None, restart=None, block_size=None,
                 precond="auto"):
    """Solve A x = b.  Returns (x, info).

    method="direct" is EXACTLY scipy.sparse.linalg.spsolve -- bit-
    identical to every pre-M22 call site, gated by G2.  "gmres" and
    "bicgstab" precondition with a node-block-Jacobi operator (when
    `block_size` is given -- pass 3 for every device core in this
    tree, which interleaves psi/n/p per node), falling back to ILU (or
    algebraic multigrid when pyamg is installed) and converge to
    `rtol` relative to ||b||.  `block_size=None` (the default) skips
    straight to ILU, unchanged from M22 phase 1's original behavior.

    `precond` picks the structured flavor when `block_size` is given:
    "auto" (default, node block-Jacobi -- the exact M22 phase-1 G6
    behavior, unchanged), "block_jacobi" (same, explicit), or "schur"
    (the equation-structured Schur-style factorization of plan
    section 7: exact-ish ILU solve of the permuted Poisson block,
    then diagonal density solves carrying the psi coupling).  A
    structurally impossible "schur" request falls through the normal
    chain rather than raising.

    info = {"method", "iterations", "converged", "residual"}.  An
    iterative method that does not reach `rtol` within `maxiter` RAISES
    LinearSolveError rather than returning the unconverged iterate.
    """
    if method not in _METHODS:
        raise ValueError(
            f"unknown method {method!r}; choose from {_METHODS}")
    if precond not in _PRECOND:
        raise ValueError(
            f"unknown precond {precond!r}; choose from {_PRECOND}")

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

    if method == "gpu_direct":
        if not _HAVE_CUPY:
            raise LinearSolveError(
                "gpu_direct requested but cupy is not installed "
                "(pip install cupy-cudaXXx, matching the local CUDA "
                "toolkit major version) -- callers already fall back "
                "to method='direct' on LinearSolveError, so this alone "
                "is enough to keep a cupy-less environment working.")
        if not sp.issparse(A):
            A = sp.csr_matrix(A)
        _check_finite(A, b, method)
        try:
            Ag = _cusp.csr_matrix(A.tocsr())
            bg = _cupy.asarray(b)
            xg = _cuspla.spsolve(Ag.tocsc(), bg)
            _cupy.cuda.Stream.null.synchronize()
            x = _cupy.asnumpy(xg)
        except Exception as exc:
            raise LinearSolveError(
                f"gpu_direct solve failed: {exc}") from exc
        if not np.all(np.isfinite(x)):
            raise LinearSolveError(
                "gpu_direct solve returned a non-finite result "
                "(A is likely singular)")
        resid = float(np.linalg.norm(A @ x - b)) / max(
            float(np.linalg.norm(b)), 1e-300)
        return x, {"method": "gpu_direct", "iterations": 1,
                   "converged": True, "residual": resid}

    # Only the iterative methods need a consistent format (CSR, for
    # the preconditioner/matvec machinery below) -- "direct" above
    # deliberately never reaches here so it never gets reformatted.
    # (A plain ndarray has no .tocsr() method -- convert to sparse
    # first rather than calling it on both branches of the ternary,
    # which would raise AttributeError for a dense A.)
    A = sp.csr_matrix(A) if not sp.issparse(A) else A.tocsr()
    _check_finite(A, b, method)
    M = _build_preconditioner(A, block_size=block_size, precond=precond)
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
