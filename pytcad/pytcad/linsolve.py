"""M22 phase 1: linear-solve abstraction (Krylov + ILU) behind the
existing spsolve interface.

Spec: M22-LINSOLVE-PLAN.md.

Motivation (measured): profiling a 27^3 = 19683-node 3D resistor
equilibrium solve put 98% of the time in scipy spsolve (direct sparse
LU).  Direct factorization is also what blocks distribution -- a
Krylov method is the prerequisite for any GPU or MPI solve, since those
need a distributed/accelerated matvec + preconditioner apply, not a
distributed LU.

Only one pytcad import, and it points DOWNWARD: `_accel`, the
soft-import shim for the optional C++ engine (M31 P3b gave
method="petsc" a compiled backend).  `_accel` itself imports nothing but
os and numpy and cannot raise at import time, so this module is still
pure in the sense that matters -- it is a driver below nothing, device.py
calls it and it never calls back into device.py.
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
# Performance pass (2026-09-04): the actual `import cupy`/`cupyx.*`
# statements are deferred to solve_linear()'s gpu_direct branch below,
# the one place that actually needs them, rather than paid by every
# process that merely imports this module -- confirmed via
# `python3 -X importtime` that a real cupy import costs ~85-124ms
# (CUDA driver detection, extension loading), overwhelmingly the
# largest single contributor to this codebase's ~505ms cold-start
# import chain, even though most sessions never touch gpu_direct.
# _HAVE_CUPY itself stays a plain, eagerly-computed module-level bool
# (0.04ms via importlib.util.find_spec, which locates the package
# without executing its __init__.py) because gui/services/
# solver_runner.py imports it directly as a name
# (`from pytcad.linsolve import ..., _HAVE_CUPY`) and reads it as a
# plain flag, not a function call -- it must see accurate availability
# with no behavior change on that side.
import importlib.util as _importlib_util
_HAVE_CUPY = _importlib_util.find_spec("cupy") is not None

# petsc4py (M31 P3a): same lazy-import contract as cupy above -- the
# `import petsc4py` line alone triggers PETSc's own start-up (option
# parsing, MPI init via petsc4py.init()), so it stays deferred to
# solve_linear()'s "petsc" branch, the one place that needs it.
# petsc4py/PETSc are conda-forge-only in practice (M31-CPP-
# ARCHITECTURE-PLAN.md sec 2/5): find_spec is enough to detect them
# without paying that start-up cost in every process that imports this
# module, exactly like _HAVE_CUPY.
_HAVE_PETSC4PY = _importlib_util.find_spec("petsc4py") is not None

# The compiled PETSc backend (M31 P3b).  _accel is the ONE module allowed
# to know whether pytcad._core exists (enforced by
# tests/test_architecture_boundaries.py), it imports nothing but os and
# numpy, and it is contractually forbidden from raising at import time --
# so importing it here costs nothing and cannot break a checkout with no
# compiler.  Whether the compiled backend is actually USED is decided per
# call by _accel.have_petsc(), not here.
from . import _accel


_PETSC4PY_MUMPS = None


def _petsc4py_has_mumps():
    """True if petsc4py is installed and its PETSc has MUMPS.  Imports
    petsc4py (PETSc start-up) on first call only, so it is asked only
    when the compiled backend cannot serve method="mumps"."""
    global _PETSC4PY_MUMPS
    if _PETSC4PY_MUMPS is None:
        if not _HAVE_PETSC4PY:
            _PETSC4PY_MUMPS = False
        else:
            try:
                import petsc4py
                petsc4py.init()
                from petsc4py import PETSc
                _PETSC4PY_MUMPS = bool(PETSc.Sys.hasExternalPackage("mumps"))
            except Exception:
                _PETSC4PY_MUMPS = False
    return _PETSC4PY_MUMPS


def mumps_available():
    """True if method="mumps" can run on some backend: the compiled
    PETSc path (pytcad._core) or petsc4py, each only if its PETSc has
    MUMPS."""
    return _accel.have_mumps() or _petsc4py_has_mumps()

__all__ = ["solve_linear", "LinearSolveError", "select_auto"]

# ----------------------------------------------------------------------
#  M31 P5-1 Phase D: NewtonOptions.linsolve="auto"
# ----------------------------------------------------------------------
# Every entry is a REAL measurement from
# M31-P5-1-SOLVER-SELECTION-PLAN.md's Phase A -- not a guess, and not a
# rule tuned on itself and then checked against itself. Every
# (dim, unstructured, coupled) combination NOT listed here, and every
# `dof` below a listed entry's own `min_dof` (the smallest size Phase A
# actually measured for that combination -- "quick" size, not chosen
# separately), refuses to "direct" rather than extrapolating.
#
# The precedent for taking this refusal seriously is in-tree
# (CLAUDE.md's M22 MPI-Schwarz split-axis picker): a safety/selection
# heuristic built from evidence for ONE case does not automatically
# cover a case that merely resembles it. An absent entry always means
# "never measured", never "assumed safe".
#
# As of Phase A-2 (2026-09-10) every cell that a caller can actually
# REACH through "auto" has a measured entry -- all eight select_auto
# dispatch sites in the tree. The refusal path above is still live and
# still gated, but it now guards only combinations that do not exist
# (e.g. 1D unstructured).
#
# WHAT THE EIGHT CELLS ACTUALLY SAY, since the obvious summary is
# wrong: the discriminator is NOT dimension, it is COUPLING.
#   * SCALAR (one unknown per node, Poisson-only) systems favour an
#     iterative solve wherever they are big enough to amortise setup --
#     including in 2D (U2DP, 12x at 11,341 DOF). B4's 82-119x is the
#     same phenomenon in 3D.
#   * COUPLED psi/n/p systems favour a DIRECT solve in 1D and 2D
#     (B2, B3, B8 -- in 1D most iterative configurations do not
#     converge at all) and an iterative one only in 3D (S3D 27.9x,
#     B9 3.9x).
# A rule of the form "use petsc in 3D" would have been wrong in both
# directions: wrong for small 3D meshes (U3DP is 24x SLOWER with petsc
# at 963 DOF) and wrong by omission for large 2D scalar ones.
_AUTO_EVIDENCE = {
    # (dim, unstructured, coupled): dict(method, min_dof, reason)
    (3, False, False): dict(
        method="petsc", min_dof=4913,
        reason="B4 (Phase A): structured 3D Poisson-equilibrium -- "
               "petsc measured 82-119x faster than direct with ZERO "
               "fallbacks across a full 9-iterate Newton sequence "
               "(179.0s -> 1.51s at 68,921 DOF). Not measured below "
               "4,913 DOF (B4 quick size); refusing below that rather "
               "than extrapolating."),
    (3, True, True): dict(
        method="petsc", min_dof=2889,
        reason="B9 (Phase A): 3D unstructured coupled drift-diffusion "
               "-- petsc measured 10.6x-11.5x faster than direct "
               "(7.85s -> 0.68s at 7,464 DOF). Not measured below "
               "2,889 DOF (B9 quick size); refusing below that rather "
               "than extrapolating."),
    # ---- Phase A-2 (2026-09-10) ------------------------------------
    # Five cells that were absent until now. Adding them changes only
    # what `linsolve="auto"` RESOLVES TO; `NewtonOptions.linsolve` still
    # defaults to "direct", so no existing caller moves and no golden
    # can shift. See the plan's "Phase A-2" section for every number.
    (1, False, True): dict(
        method="direct", min_dof=0,
        reason="B2 (Phase A-2): 1D coupled drift-diffusion -- MEASURED, "
               "and not a close call: SIX of the seven iterative "
               "configurations tried do not converge on this Jacobian "
               "at all (gmres and bicgstab x block_jacobi/ILU/schur, "
               "plus petsc), and the one that does (gmres/schur, 3.02s) "
               "is ~300x slower than direct's 0.01s at 1,206 DOF. "
               "min_dof=0: direct wins at every size, and a 1D system "
               "only gets easier for a direct factorization as it "
               "grows narrower."),
    (2, False, True): dict(
        method="direct", min_dof=0,
        reason="B3 (Phase A-2): 2D structured coupled drift-diffusion "
               "-- MEASURED at two sizes and direct wins both: 0.22s vs "
               "0.74s best iterative at 11,640 DOF, and 3.30s vs 10.07s "
               "at 72,912 DOF, where five of seven iterative configs "
               "also failed to reach rtol=1e-10 outright. Note some of "
               "those failures are MARGINAL (bicgstab/ILU reached "
               "1.223e-10 against a 1.0e-10 target) -- but petsc needed "
               "7.08s to get to 1.120e-09, already 2x direct's time, so "
               "the ranking does not depend on the tolerance nuance."),
    (3, True, False): dict(
        method="petsc", min_dof=2488,
        reason="U3DP (Phase A-2): 3D unstructured SCALAR Poisson "
               "equilibrium -- petsc 0.04s vs direct 0.16s (4.0x) at "
               "2,488 DOF. min_dof here is a MEASURED CROSSOVER, not "
               "just the smallest size tried: at 963 DOF the same petsc "
               "configuration is 0.97s against direct's 0.04s, i.e. 24x "
               "SLOWER, because KSP/PC setup dominates a system that "
               "small. Refusing below 2,488 is therefore backed by a "
               "measurement showing direct genuinely wins there."),
    (3, False, True): dict(
        method="mumps", min_dof=6591,
        reason="S3D + F3D (2026-09-24 re-measurement, "
               "benchmarks/mumps_out/study.md): 3D structured coupled "
               "bias. This cell used to resolve to gmres on S3D alone "
               "(a cube diode: 48.31s direct vs 1.59s gmres at 27,783 "
               "DOF). F3D -- the M26 tri-gate FinFET, a thin gated mesh "
               "-- INVERTS that ranking: gmres 91.01s vs direct 18.71s "
               "over a 12-point Vg sweep at 21,888 DOF, gmres slowing as "
               "the channel inverts. MUMPS LU is exact and near the best "
               "on BOTH shapes: 5.61s on F3D (16x faster than gmres, "
               "3.3x faster than direct) and 2.05s on S3D (1.3x slower "
               "than gmres, 24x faster than direct); 0.34s vs gmres "
               "0.26s at S3D quick (6,591 DOF). petsc (GMRES) won S3D "
               "full (0.81s) but was 16.11s on F3D, and failed to "
               "converge at maxiter=500 on late F3D iterates in a "
               "direct probe. Needs a MUMPS-capable PETSc; select_auto "
               "resolves to direct when none is available. Not measured "
               "below 6,591 DOF; refusing there."),
    (2, True, False): dict(
        method="petsc", min_dof=11341,
        reason="U2DP (Phase A-2): 2D unstructured SCALAR Poisson "
               "equilibrium -- petsc 0.01s vs direct 0.12s (12x) at "
               "11,341 DOF, and 4x faster than the best scipy iterative "
               "config (0.04s), so unlike S3D above this is NOT a tie "
               "and petsc earns its dependency. Note this is the FIRST "
               "2D cell where iterative wins: the discriminator is not "
               "dimension but COUPLING -- a one-unknown-per-node Poisson "
               "system behaves like B4's scalar 3D case, not like B3/B8's "
               "coupled ones. Not measured below 11,341 DOF: at 1,001 "
               "the whole solve is 2 Newton steps and all eight configs "
               "sit at 0.01s, which is timer resolution, not a result."),
    (2, True, True): dict(
        method="direct", min_dof=0,
        reason="B8 (Phase A): 2D unstructured coupled drift-diffusion "
               "-- MEASURED, not merely untested: every iterative "
               "configuration's preconditioner SETUP cost (this "
               "machine's installed pyamg building an AMG hierarchy, "
               "or node-block-Jacobi's per-node inversion -- 93% of "
               "every call, isolated and timed directly) exceeded "
               "direct's whole-solve time at every size tried (34,023 "
               "DOF full, 3.43s direct vs 8.41s best iterative). "
               "Direct wins on the evidence; auto agrees, not by "
               "default but because this is what was measured."),
}


def select_auto(dim, unstructured, coupled, dof):
    """Resolve `NewtonOptions.linsolve="auto"` to a concrete method.

    Returns `(method, reason)`. `reason` is ALWAYS a non-empty string
    naming the evidence a choice rests on, or the absence of it -- Gate
    D-2 (M31-P5-1-SOLVER-SELECTION-PLAN.md section 4): a caller, or a
    test, can always ask why a choice was made, and the answer names a
    real benchmark case and number rather than "trust me".

    Gate D-3, the refusal path: any `(dim, unstructured, coupled)` this
    project has not actually measured, and any `dof` below the smallest
    size measured for a combination it HAS, returns `method="direct"`
    with a reason saying so explicitly. Refusing is a different claim
    from "direct is best here" -- it only ever claims "there is no
    evidence for anything else here", which is the honest and total
    truth of what Phase A covers today.

    This function makes a recommendation; it does not solve anything
    and never raises -- every caller still goes through its own
    fallback-to-direct path (M31 P5-1 Phase C) if the recommended
    method fails to converge.
    """
    entry = _AUTO_EVIDENCE.get((dim, unstructured, coupled))
    if entry is None:
        return "direct", (
            f"no Phase A measurement exists for dim={dim}, "
            f"unstructured={unstructured}, coupled={coupled} -- "
            "refusing to guess (Gate D-3)")
    if dof < entry["min_dof"]:
        return "direct", (
            entry["reason"] + f" This solve's {dof} DOF is below that "
            f"floor ({entry['min_dof']}) -- refusing to extrapolate "
            "below the smallest size actually measured.")
    if entry["method"] == "mumps" and not mumps_available():
        # The measured winner needs an optional dependency this process
        # does not have. Resolve to what CAN run rather than let every
        # Newton iterate pay a failed attempt before its direct fallback.
        return "direct", (
            entry["reason"] + " No MUMPS-capable PETSc backend is "
            "available in this environment (compiled _core or petsc4py), "
            "so resolving to direct.")
    return entry["method"], entry["reason"]

_METHODS = ("direct", "gmres", "bicgstab", "gpu_direct", "petsc", "mumps")

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
    # A[3i+r, 3i+c] sits on the (c-r)-th matrix diagonal for every node
    # i, so block_size**2 calls to the sparse matrix's own .diagonal()
    # (a fast, C-level pass over the stored entries) extract every
    # block in one shot per (r, c) pair -- no per-node Python loop, and
    # no sparse fancy-indexing (which scipy implements comparatively
    # slowly) as the previous row = Ac[idx + r]; row[arange(nblk),
    # idx + c] approach did. scipy's diagonal(k) is indexed by ROW for
    # k >= 0 (d[m] = A[m, m+k]) but by COLUMN for k < 0 (d[m] =
    # A[m-k, m]) -- confirmed directly against a dense reference matrix
    # before relying on it here -- so which of idx+r / idx+c to index
    # the returned diagonal with must switch on the sign of (c - r).
    for r in range(block_size):
        for c in range(block_size):
            offset = c - r
            diag = Ac.diagonal(offset)
            blocks[:, r, c] = diag[idx + r] if offset >= 0 else diag[idx + c]
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
    # A failed/structurally-impossible "schur" request falls through to
    # block-Jacobi too (not just "auto"/"block_jacobi"), matching this
    # function's own docstring ("falls through the chain on structural
    # failure") -- excluding "schur" here would skip the one preconditioner
    # actually effective on this codebase's interleaved psi/n/p Jacobians
    # (see _build_block_jacobi_preconditioner's MOTIVATION) and drop
    # straight to scalar ILU/PyAMG, which this repo's own measurements
    # found does not make visible GMRES progress on these systems.
    if block_size is not None and precond in ("auto", "block_jacobi", "schur"):
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


# ----------------------------------------------------------------------
#  PETSc backends (M31 P3a / P3b)
# ----------------------------------------------------------------------
# Two implementations of ONE configuration.  `_solve_petsc_py` is the
# P3a reference and stays reachable forever, exactly like every
# `_<name>_py` body in the mesh modules: it is the oracle
# tests/test_accel_parity.py diffs the compiled path against, and it is
# what runs wherever the extension was not built or was built without
# PETSc (the existing pip-only CI job builds precisely that way).
#
# Both take an ALREADY-canonical CSR matrix and an already-clamped
# restart, and both return the raw (x, iterations, KSPConvergedReason)
# without judging it.  The acceptance test -- recomputing the true
# residual and raising LinearSolveError -- lives once, in solve_linear
# below, so the two backends cannot drift apart on the one thing that
# matters most: whether a solve counts as converged.
#
# That discipline is what makes the parity gate strict rather than
# approximate.  Both paths call the SAME libpetsc.so with the same KSP
# type, the same restart, the same PC, the same tolerances and the same
# matrix, so their answers are compared with np.array_equal -- confirmed
# bit-identical, not merely close.
def _solve_petsc_py(A, b, *, rtol, atol, maxiter, restart, block_size, x0,
                    direct_lu=False):
    """petsc4py backend (M31 P3a).  See the block comment above."""
    try:
        import petsc4py
        petsc4py.init()
        from petsc4py import PETSc
    except Exception as exc:
        raise LinearSolveError(
            f"petsc4py import/init failed: {exc}") from exc
    try:
        n = A.shape[0]
        # MATAIJ from the scalar CSR we already have -- BAIJ's csr=
        # constructor wants BLOCK-row indptr/BLOCK-column indices/
        # block-dense data, not this module's plain scalar CSR, so
        # building a true MATBAIJ would mean re-deriving block
        # structure by hand. setBlockSize() on a MATAIJ gets the
        # same point-block PBJACOBI preconditioning (plan sec 2)
        # without that reformat -- confirmed: PETSc's PCPBJACOBI
        # only needs the matrix's block size set, not MATBAIJ
        # storage.
        M = PETSc.Mat().createAIJ(
            (n, n), csr=(A.indptr, A.indices, A.data))
        point_block = bool(block_size) and n % block_size == 0
        if point_block:
            M.setBlockSize(block_size)
        M.assemble()
        bv = PETSc.Vec().createWithArray(b)
        xv = PETSc.Vec().createWithArray(np.zeros(n))

        ksp = PETSc.KSP().create()
        ksp.setOperators(M)
        if direct_lu:
            # method="mumps": exact LU, mirroring petsc_ksp.cpp's
            # direct_lu branch step for step (PREONLY + LU + MUMPS).
            ksp.setType(PETSc.KSP.Type.PREONLY)
            pc = ksp.getPC()
            pc.setType(PETSc.PC.Type.LU)
            pc.setFactorSolverType("mumps")
            ksp.setFromOptions()
            ksp.solve(bv, xv)
            reason = ksp.getConvergedReason()
            iters = ksp.getIterationNumber()
            x = xv.getArray().copy()
            ksp.destroy(); M.destroy(); bv.destroy(); xv.destroy()
            return x, int(iters), int(reason)
        ksp.setType(PETSc.KSP.Type.GMRES)
        # Same restart-too-small stall as scipy's gmres branch below
        # (this file's own restart comment there): PETSc's default
        # GMRES restart (30) made no visible progress on the
        # coupled 3D device Jacobian either -- confirmed directly.
        ksp.setGMRESRestart(restart)
        pc = ksp.getPC()
        # Block-Jacobi (PCPBJACOBI, plan sec 2) when the interleaved
        # block structure applies -- the point-block analogue of
        # this module's own node-block-Jacobi preconditioner above
        # -- else scalar block-Jacobi/ILU, PETSc's usual default.
        pc.setType(PETSc.PC.Type.PBJACOBI if point_block
                   else PETSc.PC.Type.BJACOBI)
        ksp.setTolerances(rtol=rtol, atol=atol, max_it=maxiter)
        if x0 is not None:
            # setInitialGuessNonzero is NOT optional decoration: PETSc
            # zeroes the solution vector at the top of KSPSolve unless
            # it is set, so seeding xv alone was silently ignored --
            # confirmed by measurement (identical iteration count and
            # bit-identical answer from an EXACT initial guess, versus
            # 0 iterations once the flag is set). That was a real defect
            # in the P3a code this function was extracted from; it is
            # fixed here and in the compiled backend at the same time,
            # so the two cannot disagree about it.
            ksp.setInitialGuessNonzero(True)
            xv.setArray(np.asarray(x0, dtype=float))
        ksp.setFromOptions()
        ksp.solve(bv, xv)
        reason = ksp.getConvergedReason()
        iters = ksp.getIterationNumber()
        x = xv.getArray().copy()
        ksp.destroy(); M.destroy(); bv.destroy(); xv.destroy()
    except LinearSolveError:
        raise
    except Exception as exc:
        raise LinearSolveError(f"petsc solve failed: {exc}") from exc
    return x, int(iters), int(reason)


def _solve_petsc_cpp(A, b, *, rtol, atol, maxiter, restart, block_size, x0,
                     direct_lu=False):
    """Compiled backend (M31 P3b): the same configuration, in
    core/src/solver/petsc_ksp.cpp.

    Nothing is decided here.  The KSP/PC choices moved to C++; this
    function only marshals the CSR triple across the boundary (int64 by
    the rule pytcad/_accel.py states for every kernel -- the C++ side
    converts to PetscInt once, range-checked) and hands back the same
    (x, iterations, reason) triple the petsc4py backend returns.
    """
    try:
        x, iters, reason = _accel.core.petsc_solve_csr(
            _accel.as_csr_index(A.indptr), _accel.as_csr_index(A.indices),
            np.ascontiguousarray(A.data, dtype=float),
            np.ascontiguousarray(b, dtype=float),
            None if x0 is None else np.ascontiguousarray(x0, dtype=float),
            float(rtol), float(atol), int(maxiter), int(restart),
            int(block_size or 0), bool(direct_lu))
    except LinearSolveError:
        # Already the documented class -- the C++ exception translator in
        # core/bindings/module.cpp maps tcad::LinearSolveFailure onto
        # THIS module's LinearSolveError, so it must pass through
        # unwrapped rather than be re-wrapped into a second message.
        raise
    except Exception as exc:
        raise LinearSolveError(f"petsc solve failed: {exc}") from exc
    return x, int(iters), int(reason)


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

    method="petsc" (M31-CPP-ARCHITECTURE-PLAN.md sec 2/4) is GMRES via
    PETSc's KSP on a `MATAIJ` built from this module's own scalar CSR,
    with its block size set to `block_size` when that divides the system
    evenly (point-block PCPBJACOBI preconditioner, plan sec 2's target),
    else plain PCBJACOBI -- the PETSc analogue of this module's own
    node-block-Jacobi path.  It is kept as a SEPARATE method rather than
    folded into "gmres" because it exercises a genuinely different solver
    stack.

    Two interchangeable backends run that one configuration, and which
    one you get is reported in info["backend"]:

      "cpp"      -- core/src/solver/petsc_ksp.cpp through pytcad._core
                    (M31 P3b).  Preferred when the extension was built
                    against PETSc and PYTCAD_ACCEL has not forced the
                    Python path.
      "petsc4py" -- the P3a reference, kept forever as the oracle the
                    compiled path is diffed against, and what runs
                    wherever the extension is absent or was built
                    without PETSc.

    They are held to np.array_equal against each other, not a tolerance
    (tests/test_accel_parity.py): both call the same libpetsc with the
    same configuration on the same canonicalized matrix.  PETSc is
    optional in both forms and conda-forge is the supported channel; with
    neither available this raises LinearSolveError, not ImportError, so
    callers that already fall back to "direct"/"gmres" on
    LinearSolveError need no new branch.

    One caveat specific to this method: PETSc's internal convergence test
    runs on the (left-)PRECONDITIONED residual, while `info["residual"]`
    and the acceptance test here use the plain ||Ax-b||/||b||.  The two
    can differ by an order of magnitude, so `rtol` is not the tight bound
    on the returned solution that it is for scipy's methods.

    method="mumps" is an EXACT sparse LU (MUMPS) through the same two
    PETSc backends (KSPPREONLY + PCLU), chosen by `select_auto` where a
    direct factorization wins but SuperLU's fill-in does not (3D
    structured coupled solves -- see _AUTO_EVIDENCE). rtol/maxiter/
    restart/block_size/precond are ignored. Needs a PETSc with MUMPS
    (conda-forge's has it); without one it raises LinearSolveError,
    which every caller already falls back on, and `select_auto` never
    recommends it. It matches "direct" to factorization precision, not
    bit-for-bit (a different LU with a different ordering).

    info = {"method", "backend", "iterations", "converged", "residual"}
    ("backend" only for method="petsc"/"mumps").  An iterative method that does
    not reach `rtol` within `maxiter` RAISES LinearSolveError rather than
    returning the unconverged iterate.
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
            import cupy as _cupy
            import cupyx.scipy.sparse as _cusp
            import cupyx.scipy.sparse.linalg as _cuspla
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

    if method in ("petsc", "mumps"):
        direct_lu = method == "mumps"
        # Backend choice, in this order and for this reason: the compiled
        # one when it exists (that is what P3b built, and it is the path
        # the later distributed/DMPlex phases extend), petsc4py when it
        # does not.  PYTCAD_ACCEL=0 forces the Python backend -- which is
        # how tests/test_accel_parity.py gets to run both in one process
        # and diff them.
        use_cpp = _accel.have_mumps() if direct_lu else _accel.have_petsc()
        if direct_lu and not use_cpp and not _petsc4py_has_mumps():
            raise LinearSolveError(
                "mumps requested but no MUMPS-capable PETSc backend is "
                "available: pytcad._core was built without PETSc/MUMPS and "
                "petsc4py is missing or its PETSc lacks MUMPS "
                "(`conda install -c conda-forge petsc4py` provides both). "
                "Callers fall back to method='direct' on LinearSolveError.")
        if not use_cpp and not _HAVE_PETSC4PY:
            raise LinearSolveError(
                "petsc requested but neither backend is available: the "
                "compiled backend (M31 P3b) needs pytcad._core built "
                "against PETSc, and the Python backend (P3a) needs "
                "petsc4py. conda-forge is the supported channel for both "
                "(`conda install -c conda-forge petsc4py`); pip has no "
                "practical PETSc wheel (M31-CPP-ARCHITECTURE-PLAN.md "
                "sec 2/5). Callers already fall back to "
                "method='direct'/'gmres' on LinearSolveError, so this "
                "alone keeps a PETSc-less environment working.")
        if not sp.issparse(A):
            A = sp.csr_matrix(A)
        A = A.tocsr()
        # Canonicalize ONCE, here, so both backends are handed the
        # identical matrix -- which is what lets the parity gate use
        # np.array_equal rather than a tolerance. Not a bug fix: PETSc
        # 3.25's MatSeqAIJSetPreallocationCSR was checked directly and
        # does sort a reversed-index CSR correctly. It is insurance,
        # because sorted-within-row is what PETSc's CSR contract asks
        # for and scipy does not guarantee it, and it removes a way the
        # two backends could ever be handed different matrices. Copy
        # only when the flag says it is needed, so a caller's (already
        # canonical) assembled Jacobian is never mutated behind its back.
        if not A.has_canonical_format:
            A = A.copy()
            A.sum_duplicates()          # sorts indices as well
        _check_finite(A, b, method)
        backend = _solve_petsc_cpp if use_cpp else _solve_petsc_py
        x, iters, reason = backend(
            A, b, rtol=rtol, atol=atol or 1e-50, maxiter=maxiter,
            # PETSc's own default restart of 30 stalls on this codebase's
            # coupled device Jacobians; clamped here, once, so neither
            # backend has to know the rule.
            restart=min(restart or 100, A.shape[0]),
            block_size=block_size, x0=x0, direct_lu=direct_lu)
        # The acceptance test is deliberately OUTSIDE both backends: one
        # residual, one threshold, one message, so "converged" means
        # exactly the same thing whichever one ran.
        bnorm = max(float(np.linalg.norm(b)), 1e-300)
        resid = float(np.linalg.norm(A @ x - b)) / bnorm
        converged = (reason > 0) and np.all(np.isfinite(x)) and resid <= max(
            rtol, 1e-6)
        if not converged:
            if direct_lu:
                raise LinearSolveError(
                    f"mumps LU failed (KSPConvergedReason={reason}, "
                    f"relative residual={resid:.3e}) -- A is likely "
                    f"singular; refusing to return the result")
            raise LinearSolveError(
                f"petsc did not converge within {maxiter} iterations "
                f"(KSPConvergedReason={reason}, relative residual="
                f"{resid:.3e}, target rtol={rtol:.3e}) -- refusing to "
                f"return the unconverged iterate")
        return x, {"method": method,
                   "backend": "cpp" if use_cpp else "petsc4py",
                   "iterations": iters, "converged": True, "residual": resid}

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
