// The PETSc KSP/PC configuration, owned by the engine (M31 P3b).
//
// P3a put this configuration in pytcad/linsolve.py, driven through
// petsc4py.  P3b moves the CONFIGURATION -- which Krylov method, which
// preconditioner, which restart, which tolerances -- down here, where
// the rest of the engine will eventually live.  Everything else about
// the contract is deliberately UNCHANGED and stays in Python:
//
//   * the true-residual acceptance test and the LinearSolveError message
//     stay in linsolve.py, so both backends make the same accept/reject
//     decision with the same wording.  Two backends that disagree about
//     when a solve "converged" would be a parity hole that no test could
//     paper over;
//   * the CSR normalization (sorted indices, summed duplicates) stays in
//     linsolve.py, so both backends are handed the identical matrix.
//
// What that buys is the gate in tests/test_accel_parity.py: because both
// paths bottom out in the SAME libpetsc.so with the same configuration
// on the same input, they are checked with np.array_equal, not a
// tolerance -- the same standard P2's mesh kernels are held to, and for
// once it is achievable for a Krylov solve.
//
// PETSc is OPTIONAL AT BUILD TIME.  This header and its .cpp compile
// with or without it; without, have_petsc() is false and solve_csr()
// throws LinearSolveFailure.  The existing CI job that builds the
// extension from a plain pip environment has no PETSc and must keep
// passing (gate G-F applies to PETSc too, not just to the whole
// extension).
#pragma once

#include <cstdint>

namespace tcad::solver {

/// True when the engine was compiled against PETSc.  When false,
/// solve_csr() throws rather than silently doing something else.
bool have_petsc();

/// "3.25.4" for the PETSc this was compiled against, or "" without it.
const char* petsc_version();

/// sizeof(PetscInt) in the PETSc this was compiled against, or 0.
/// Informational only -- the boundary below is int64 regardless (see
/// solve_csr), so no caller has to branch on this.  It is reported by
/// pytcad._accel.status() because a 4 here is a real capability limit:
/// a 32-bit-index PETSc cannot address a matrix with >2^31 nonzeros.
int petsc_index_bytes();

/// Everything P3a configured on the KSP, in one place.
struct KspConfig {
    double rtol = 1e-10;
    double atol = 1e-50;   ///< PETSc's own default; 0.0 is not accepted
    int maxiter = 500;
    int restart = 100;     ///< GMRES(m); the caller has already clamped it to <= n
    int block_size = 0;    ///< 0 -> no point-block structure -> PCBJACOBI
    bool nonzero_guess = false;  ///< x holds an initial guess on entry
};

/// What the solve reports back.  Note what is NOT here: a verdict.  The
/// caller recomputes the true residual and decides, identically for both
/// backends -- see the header comment.
struct KspResult {
    int iterations = 0;
    int converged_reason = 0;  ///< KSPConvergedReason: >0 converged, <0 failed
};

/// Solve A x = b for a square sequential CSR matrix.
///
/// The index boundary is int64 in BOTH directions regardless of how
/// PETSc was configured, matching the rule pytcad/_accel.py states for
/// every other kernel: numpy's `dtype=int` is C `long`, which is int64
/// on Linux and int32 on Windows, so pinning to int64 keeps the
/// extension's ABI identical on both.  When PetscInt is narrower (the
/// conda-forge default is 32-bit) the indices are converted here, once,
/// which costs one pass over nnz against a solve that costs hundreds of
/// iterations over the same data.  An index that does not fit is a
/// thrown LinearSolveFailure, never a truncation.
///
/// `x` is both the initial guess (when cfg.nonzero_guess) and the
/// output buffer.  It is written ONLY on a normal return.
///
/// Throws tcad::LinearSolveFailure for a PETSc API failure or a build
/// without PETSc; tcad::InvalidArgument for a structurally impossible
/// argument.  A solve that merely fails to converge is NOT an exception
/// here -- it comes back in converged_reason for the caller to judge.
KspResult solve_csr(std::int64_t n, std::int64_t nnz,
                    const std::int64_t* indptr, const std::int64_t* indices,
                    const double* values, const double* b, double* x,
                    const KspConfig& cfg);

}  // namespace tcad::solver
