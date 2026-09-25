// The PETSc KSP/PC configuration (M31 P3b).  See the header for what
// this owns and, more importantly, what it deliberately does not.
#include "tcad/solver/petsc_ksp.hpp"

#include <algorithm>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <mutex>
#include <string>
#include <vector>

#include "tcad/base/errors.hpp"

#ifdef TCAD_HAVE_PETSC
#include <petscksp.h>

// A complex or single-precision PETSc would silently reinterpret the
// double buffers this boundary passes.  Fail at BUILD time rather than
// producing plausible-looking garbage at run time; the CMake probe
// already reports which PETSc was found.
#if defined(PETSC_USE_COMPLEX)
#error "pytcad requires a real-scalar PETSc; this one is configured --with-scalar-type=complex"
#endif
#if !defined(PETSC_USE_REAL_DOUBLE)
#error "pytcad requires a double-precision PETSc (--with-precision=double)"
#endif
#endif  // TCAD_HAVE_PETSC

namespace tcad::solver {

#ifndef TCAD_HAVE_PETSC

// ----------------------------------------------------------------------
//  Built without PETSc.  This is a supported configuration, not a
//  degraded one: the existing CI job builds the extension from a plain
//  pip environment where PETSc does not exist, and Python's
//  linsolve.solve_linear(method="petsc") falls back to petsc4py -- or,
//  failing that, raises the documented LinearSolveError.  So the only
//  thing this half owes anyone is an honest answer to have_petsc() and
//  a message that says which of the two routes to take.
// ----------------------------------------------------------------------
bool have_petsc() { return false; }
bool have_mumps() { return false; }
const char* petsc_version() { return ""; }
int petsc_index_bytes() { return 0; }

KspResult solve_csr(std::int64_t, std::int64_t, const std::int64_t*,
                    const std::int64_t*, const double*, const double*, double*,
                    const KspConfig&) {
    throw LinearSolveFailure(
        "pytcad._core was built without PETSc, so the compiled petsc "
        "backend is unavailable. Either rebuild against a PETSc "
        "installation (conda-forge: `conda install -c conda-forge petsc`, "
        "then reconfigure CMake) or install petsc4py for the Python "
        "backend -- linsolve.solve_linear(method='petsc') prefers the "
        "compiled path but uses petsc4py whenever this one is absent.");
}

#else

namespace {

// ----------------------------------------------------------------------
//  Process-global PETSc state
// ----------------------------------------------------------------------
// PETSc has exactly one initialization per process, one options
// database, and one error-handler stack.  In THIS process petsc4py may
// well be holding all three already -- the P3a Python backend lives in
// the same interpreter and tests/test_accel_parity.py runs both backends
// back to back.  So the rules here are:
//
//   * initialize only if nobody has (PetscInitialized), so we never
//     fight petsc4py for it and never double-initialize MPI;
//   * finalize only if WE initialized, and only at process exit, so we
//     never pull PETSc out from under petsc4py mid-session;
//   * never touch the error-handler stack.  PetscPushErrorHandler is
//     global, and petsc4py installs its own to turn PETSc errors into
//     Python exceptions; pushing ours would break the Python backend's
//     error reporting for as long as it stayed pushed.  The cost is that
//     a genuine PETSc error prints its traceback to stderr before we
//     translate it -- which is exactly what the petsc4py path already
//     does, so the two backends stay symmetric.
std::mutex& petsc_lock() {
    static std::mutex m;
    return m;
}

bool g_we_initialized = false;

void check(PetscErrorCode ierr, const char* what) {
    if (ierr == PETSC_SUCCESS) return;
    const char* text = nullptr;
    PetscErrorMessage(ierr, &text, nullptr);
    throw LinearSolveFailure(std::string("petsc ") + what +
                             " failed (PetscErrorCode " +
                             std::to_string(static_cast<int>(ierr)) + ": " +
                             (text ? text : "unknown") + ")");
}

void finalize_at_exit() {
    PetscBool inited = PETSC_FALSE;
    if (PetscInitialized(&inited) == PETSC_SUCCESS && inited) PetscFinalize();
}

void ensure_initialized() {
    PetscBool inited = PETSC_FALSE;
    check(PetscInitialized(&inited), "PetscInitialized");
    if (inited) return;
    check(PetscInitializeNoArguments(), "PetscInitialize");
    g_we_initialized = true;
    // Only when we are the initializer: petsc4py registers its own
    // finalizer in the case where IT initialized, and MPICH complains at
    // exit about an un-finalized MPI otherwise.
    std::atexit(finalize_at_exit);
}

/// Destroy-on-scope-exit for a PETSc handle.  Ordinary RAII, but the
/// reason it is here rather than a bare destroy at the end is the
/// repo-wide rule that a failed call leaves nothing behind: every check()
/// above can throw, and each of these unwinds cleanly when it does.
template <class T>
struct Owned {
    using Destroy = PetscErrorCode (*)(T*);
    explicit Owned(Destroy d) : destroy(d) {}
    ~Owned() {
        if (obj) destroy(&obj);
    }
    Owned(const Owned&) = delete;
    Owned& operator=(const Owned&) = delete;
    T obj = nullptr;
    Destroy destroy;
};

/// A PetscInt view of an int64 index array.
///
/// The boundary is int64 in both directions (see the header for why),
/// but conda-forge's PETSc -- the supported channel -- is built with
/// 32-bit indices.  When the two widths agree this aliases and costs
/// nothing; when they do not it converts into `scratch`, range-checking
/// every entry.  An index too large to fit is a thrown error, never a
/// silent truncation that would corrupt the matrix into something that
/// still solves and still returns a plausible answer.
const PetscInt* as_petsc_int(const std::int64_t* src, std::int64_t count,
                             std::vector<PetscInt>& scratch, const char* what) {
    if (count == 0) return nullptr;
    if constexpr (sizeof(PetscInt) == sizeof(std::int64_t)) {
        return reinterpret_cast<const PetscInt*>(src);
    } else {
        constexpr std::int64_t lim = std::numeric_limits<PetscInt>::max();
        scratch.resize(static_cast<std::size_t>(count));
        for (std::int64_t k = 0; k < count; ++k) {
            if (src[k] > lim || src[k] < 0)
                throw LinearSolveFailure(
                    std::string("petsc: ") + what + "[" + std::to_string(k) +
                    "] = " + std::to_string(src[k]) +
                    " does not fit this PETSc's " +
                    std::to_string(sizeof(PetscInt) * 8) +
                    "-bit PetscInt -- rebuild PETSc with "
                    "--with-64-bit-indices for a problem this large");
            scratch[static_cast<std::size_t>(k)] = static_cast<PetscInt>(src[k]);
        }
        return scratch.data();
    }
}

}  // namespace

bool have_petsc() { return true; }

bool have_mumps() {
#if defined(PETSC_HAVE_MUMPS)
    return true;
#else
    return false;
#endif
}

const char* petsc_version() {
    static const std::string v = std::to_string(PETSC_VERSION_MAJOR) + "." +
                                 std::to_string(PETSC_VERSION_MINOR) + "." +
                                 std::to_string(PETSC_VERSION_SUBMINOR);
    return v.c_str();
}

int petsc_index_bytes() { return static_cast<int>(sizeof(PetscInt)); }

KspResult solve_csr(std::int64_t n, std::int64_t nnz,
                    const std::int64_t* indptr, const std::int64_t* indices,
                    const double* values, const double* b, double* x,
                    const KspConfig& cfg) {
    if (n <= 0) throw InvalidArgument("solve_csr: n must be positive");
    if (nnz < 0) throw InvalidArgument("solve_csr: nnz must not be negative");
    if (indptr[n] != nnz)
        throw InvalidArgument("solve_csr: indptr[n] = " +
                              std::to_string(indptr[n]) + " disagrees with nnz = " +
                              std::to_string(nnz));
    if (cfg.direct_lu && !have_mumps())
        throw LinearSolveFailure(
            "petsc: MUMPS LU requested, but this PETSc was built without "
            "MUMPS (conda-forge's petsc has it)");
    if (n > std::numeric_limits<PetscInt>::max())
        throw LinearSolveFailure(
            "petsc: matrix dimension " + std::to_string(n) +
            " exceeds this PETSc's PetscInt range");

    // PETSc's default build is not thread-safe (one options database,
    // one error-handler stack, one logging state), and the binding
    // releases the GIL around this call.  Serializing whole solves is
    // both cheap -- a solve is milliseconds to seconds, the lock is
    // nanoseconds -- and consistent with runtime/threads.hpp's
    // single-threaded default.
    std::lock_guard<std::mutex> guard(petsc_lock());
    ensure_initialized();

    // n >= 1 above, so indptr always has at least two entries and `ip` is
    // never null.  `jj` legitimately is when nnz == 0 (an all-empty-rows
    // matrix), which PETSc accepts.
    std::vector<PetscInt> ip_buf, jj_buf;
    const PetscInt* ip = as_petsc_int(indptr, n + 1, ip_buf, "indptr");
    const PetscInt* jj = as_petsc_int(indices, nnz, jj_buf, "indices");

    const MPI_Comm comm = PETSC_COMM_SELF;
    const PetscInt N = static_cast<PetscInt>(n);

    // ---- the matrix.  Construction ORDER mirrors the petsc4py backend
    // exactly (create / set type / preallocate from CSR / set block size
    // / assemble), because "the same configuration" is what P3b claims
    // and tests/test_accel_parity.py checks that claim with
    // np.array_equal rather than a tolerance.
    Owned<Mat> A(MatDestroy);
    check(MatCreate(comm, &A.obj), "MatCreate");
    check(MatSetSizes(A.obj, PETSC_DECIDE, PETSC_DECIDE, N, N), "MatSetSizes");
    check(MatSetType(A.obj, MATAIJ), "MatSetType");
    check(MatSeqAIJSetPreallocationCSR(A.obj, ip, jj, values),
          "MatSeqAIJSetPreallocationCSR");
    // Point-block structure, when the caller's unknowns really are
    // grouped that way (every device core in this tree interleaves
    // psi/n/p per node, hence block_size=3).  Set AFTER preallocation
    // and before assembly -- confirmed to stick, and it is what makes
    // PCPBJACOBI a point-block preconditioner rather than plain Jacobi.
    if (cfg.block_size > 1 && n % cfg.block_size == 0)
        check(MatSetBlockSize(A.obj, static_cast<PetscInt>(cfg.block_size)),
              "MatSetBlockSize");
    check(MatAssemblyBegin(A.obj, MAT_FINAL_ASSEMBLY), "MatAssemblyBegin");
    check(MatAssemblyEnd(A.obj, MAT_FINAL_ASSEMBLY), "MatAssemblyEnd");

    // ---- vectors.  The solution is accumulated in a buffer we own and
    // copied to `x` only after a normal return, so a throw anywhere below
    // leaves the caller's array untouched: the same "a failed call never
    // returns half-state" rule the mesh bindings make structural.
    std::vector<PetscScalar> xbuf(static_cast<std::size_t>(n), 0.0);
    if (cfg.nonzero_guess) std::copy(x, x + n, xbuf.begin());

    Owned<Vec> bv(VecDestroy), xv(VecDestroy);
    check(VecCreateSeq(comm, N, &bv.obj), "VecCreateSeq");
    {
        PetscScalar* ba = nullptr;
        check(VecGetArrayWrite(bv.obj, &ba), "VecGetArrayWrite");
        std::copy(b, b + n, ba);
        check(VecRestoreArrayWrite(bv.obj, &ba), "VecRestoreArrayWrite");
    }
    check(VecCreateSeqWithArray(comm, 1, N, xbuf.data(), &xv.obj),
          "VecCreateSeqWithArray");

    // ---- the KSP.  This block IS phase P3b: the configuration that
    // used to be a dozen petsc4py calls in linsolve.py.
    Owned<KSP> ksp(KSPDestroy);
    check(KSPCreate(comm, &ksp.obj), "KSPCreate");
    check(KSPSetOperators(ksp.obj, A.obj, A.obj), "KSPSetOperators");
    PC pc = nullptr;
    check(KSPGetPC(ksp.obj, &pc), "KSPGetPC");
    if (cfg.direct_lu) {
#if defined(PETSC_HAVE_MUMPS)
        // One exact factor-and-solve: no Krylov iteration, no
        // preconditioner choice, no tolerance.  MUMPS picks its own
        // fill-reducing ordering, which is what makes this cheap on the
        // cube-shaped meshes where SuperLU's COLAMD fills in badly.
        // Mirrored step for step by linsolve._solve_petsc_py.
        check(KSPSetType(ksp.obj, KSPPREONLY), "KSPSetType");
        check(PCSetType(pc, PCLU), "PCSetType");
        check(PCFactorSetMatSolverType(pc, MATSOLVERMUMPS),
              "PCFactorSetMatSolverType");
#endif
        check(KSPSetFromOptions(ksp.obj), "KSPSetFromOptions");
        check(KSPSolve(ksp.obj, bv.obj, xv.obj), "KSPSolve");
        KSPConvergedReason reason = KSP_CONVERGED_ITERATING;
        PetscInt its = 0;
        check(KSPGetConvergedReason(ksp.obj, &reason), "KSPGetConvergedReason");
        check(KSPGetIterationNumber(ksp.obj, &its), "KSPGetIterationNumber");
        KspResult r;
        r.iterations = static_cast<int>(its);
        r.converged_reason = static_cast<int>(reason);
        std::copy(xbuf.begin(), xbuf.end(), x);
        return r;
    }
    check(KSPSetType(ksp.obj, KSPGMRES), "KSPSetType");
    // GMRES(m) forgets its Krylov basis every m steps; PETSc's default
    // m = 30 made no visible progress on this codebase's coupled 3D
    // device Jacobian -- the same stall linsolve.py's scipy gmres branch
    // documents for the same reason.  The caller has already clamped
    // this to <= n.
    check(KSPGMRESSetRestart(ksp.obj, static_cast<PetscInt>(std::max(1, cfg.restart))),
          "KSPGMRESSetRestart");
    const bool point_block = cfg.block_size > 1 && n % cfg.block_size == 0;
    check(PCSetType(pc, point_block ? PCPBJACOBI : PCBJACOBI), "PCSetType");
    check(KSPSetTolerances(ksp.obj, cfg.rtol, cfg.atol, PETSC_CURRENT,
                           static_cast<PetscInt>(cfg.maxiter)),
          "KSPSetTolerances");
    if (cfg.nonzero_guess)
        check(KSPSetInitialGuessNonzero(ksp.obj, PETSC_TRUE),
              "KSPSetInitialGuessNonzero");
    // Kept so a user can still override anything above from PETSC_OPTIONS
    // or ~/.petscrc, exactly as the petsc4py backend allows.  Both
    // backends read the same options database, so an override moves them
    // together rather than silently splitting them apart.
    check(KSPSetFromOptions(ksp.obj), "KSPSetFromOptions");
    check(KSPSolve(ksp.obj, bv.obj, xv.obj), "KSPSolve");

    KSPConvergedReason reason = KSP_CONVERGED_ITERATING;
    PetscInt its = 0;
    check(KSPGetConvergedReason(ksp.obj, &reason), "KSPGetConvergedReason");
    check(KSPGetIterationNumber(ksp.obj, &its), "KSPGetIterationNumber");

    KspResult r;
    r.iterations = static_cast<int>(its);
    r.converged_reason = static_cast<int>(reason);
    std::copy(xbuf.begin(), xbuf.end(), x);
    return r;
}

#endif  // TCAD_HAVE_PETSC

}  // namespace tcad::solver
