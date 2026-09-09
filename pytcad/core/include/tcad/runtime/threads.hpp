// Thread-count policy for every kernel in the engine.
//
// THE DEFAULT IS 1, and that is deliberate.  Two independent reasons,
// the second of which is the hard constraint:
//
//   1. workbench/batch.py pins OPENBLAS_NUM_THREADS=1 per pool worker
//      precisely to stop BLAS from spawning a thread pool PER worker and
//      oversubscribing the machine.  A kernel that spawns nproc threads
//      inside each of those workers reintroduces exactly the bug that
//      pin exists to prevent.
//
//   2. Parallel floating-point reductions destroy bit-identity.  A
//      scatter-add accumulated in nondeterministic thread order gives
//      different last bits run to run, which is fatal against this
//      repo's np.array_equal goldens.
//
// So: a kernel may use threads ONLY if it is bit-identical across thread
// counts, which is achieved by parallelizing over the OUTPUT index and
// never the input.  Gate G-D checks exactly this (PYTCAD_NUM_THREADS in
// {1,2,4,8} must agree under np.array_equal); a kernel that fails loses
// its `#pragma omp` rather than its gate.
#pragma once

namespace tcad::runtime {

/// Threads a kernel may use.  Reads PYTCAD_NUM_THREADS, then
/// OMP_NUM_THREADS, else returns 1.  Never omp_get_max_threads()
/// implicitly.  Evaluated once and cached; always >= 1.
int thread_count();

}  // namespace tcad::runtime
