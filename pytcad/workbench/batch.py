"""M30 Phase 4: batch parallelism.

Runs several INDEPENDENT jobs (split-matrix rows, calibration trials,
or any other DeviceSpec job/result pair) concurrently via a plain
`concurrent.futures.ProcessPoolExecutor`, reusing the existing
gui.services.solver_runner.run_job entry point per worker unchanged --
this parallelizes many separate jobs, NOT one job's internal linear
algebra (that is M22's already-shipped MPI-Schwarz work, a different
axis entirely; see pytcad/M30-WORKBENCH-PLAN.md section 6).

Each worker process gets OPENBLAS_NUM_THREADS pinned to "1" before
doing any work -- CLAUDE.md's own documented oversubscription hazard
for `pytest -n` applies identically here: without the pin, each pool
worker's own BLAS calls would spawn their own thread pool,
oversubscribing every core across all workers simultaneously.
"""
import concurrent.futures as cf
import os
import tempfile
from dataclasses import dataclass
from typing import Optional


def _pin_single_threaded_blas():
    """Pool initializer: runs once per worker process, before it picks
    up any job."""
    os.environ["OPENBLAS_NUM_THREADS"] = "1"


def worker_blas_thread_setting():
    """Test hook: returns this process's OPENBLAS_NUM_THREADS, so a
    test can confirm the pool initializer actually ran inside a real
    worker process (not just the parent)."""
    return os.environ.get("OPENBLAS_NUM_THREADS")


def _run_one(job_path, out_path):
    from gui.services.solver_runner import run_job
    try:
        run_job(job_path, out_path)
        return (out_path, None)
    except Exception as exc:
        return (None, f"{type(exc).__name__}: {exc}")


@dataclass
class BatchOutcome:
    out_path: Optional[str]
    error: Optional[str]


def default_worker_count(n_jobs):
    """Same conservative cap CLAUDE.md's own `-n 6` guidance already
    reasons about this machine with -- never more workers than jobs,
    never more than the CPU count, never more than 6."""
    return max(1, min(6, os.cpu_count() or 1, n_jobs))


def run_jobs_parallel_iter(jobs, max_workers=None):
    """Like run_jobs_parallel, but yields (index, BatchOutcome) as each
    job actually finishes (completion order, not input order) instead
    of collecting everything into a list first -- lets a caller (e.g.
    workbench.study_manifest's incremental save) react to each
    completion as it happens rather than waiting for the whole batch."""
    jobs = list(jobs)
    if not jobs:
        return
    max_workers = max_workers or default_worker_count(len(jobs))
    with cf.ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=_pin_single_threaded_blas) as pool:
        futures = {pool.submit(_run_one, jp, op): i
                  for i, (jp, op) in enumerate(jobs)}
        for fut in cf.as_completed(futures):
            i = futures[fut]
            out_path, error = fut.result()
            yield i, BatchOutcome(out_path=out_path, error=error)


def run_jobs_parallel(jobs, max_workers=None):
    """`jobs`: a sequence of (job_json_path, out_npz_path) pairs, each
    an ordinary solver_runner job.  Runs them concurrently, one bad job
    isolated from the rest (mirrors workbench.splits.run_split_matrix's
    per-row isolation, generalized to the solve step).  Returns a list
    of BatchOutcome in the SAME ORDER as `jobs`, not completion order."""
    jobs = list(jobs)
    outcomes = [None] * len(jobs)
    for i, outcome in run_jobs_parallel_iter(jobs, max_workers=max_workers):
        outcomes[i] = outcome
    return outcomes


def solve_split_matrix(run, work_dir=None, max_workers=None, executor=None):
    """Build every row of `run`'s split matrix (workbench.splits.
    run_split_matrix) and solve the ones that built successfully, in
    parallel.  Returns a list of (SplitRow, BatchOutcome | None) pairs
    in row order -- BatchOutcome is None for a row whose SplitRow.error
    is already set, since it never reaches the solver at all (the same
    build/solve isolation boundary Phase 1 established).

    `executor`: an optional `workbench.executor.Executor` (M30 Phase
    12) -- defaults to the local `ProcessPoolExecutor` path via
    `run_jobs_parallel` when omitted, so existing callers are
    unaffected. Pass a `workbench.remote_executor.RemoteExecutor` to
    dispatch the same rows to remote workers instead
    (G-PROTOCOL-PARITY: this function does not change either way)."""
    from .adapters.spec import spec_from_domain
    from .splits import run_split_matrix

    work_dir = work_dir or tempfile.mkdtemp(prefix="pytcad-batch-")
    rows = run_split_matrix(run)

    solvable_idx, jobs = [], []
    for i, row in enumerate(rows):
        if row.device is None:
            continue
        spec = spec_from_domain(row.device)
        spec.bias = dict(run.bias) if run.bias else None
        if run.sweep:
            from gui.services.device_spec import SweepSpec
            spec.sweep = SweepSpec(**run.sweep)
        job_path = os.path.join(work_dir, f"job-{i}.json")
        out_path = os.path.join(work_dir, f"result-{i}.npz")
        spec.to_json(job_path)
        jobs.append((job_path, out_path))
        solvable_idx.append(i)

    if executor is None:
        outcomes = run_jobs_parallel(jobs, max_workers=max_workers)
    else:
        outcomes = executor.run_jobs(jobs, max_workers=max_workers)
    paired = [None] * len(rows)
    for idx, outcome in zip(solvable_idx, outcomes):
        paired[idx] = outcome
    return list(zip(rows, paired))
