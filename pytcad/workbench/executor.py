"""M30 Phase 12: the `Executor` seam.

`workbench.batch.solve_split_matrix` (Phase 4) always drove its own
`ProcessPoolExecutor` directly. This module pulls that dispatch surface
out into a small protocol -- matching the `SolverBackend` precedent in
`workbench/solvers/base.py` -- so a caller can swap in a different
backend (e.g. `workbench.remote_executor.RemoteExecutor`) without
`solve_split_matrix` itself changing: both implementations take the
same `[(job_json_path, out_npz_path), ...]` input and return the same
`list[BatchOutcome]` in input order.
"""
from typing import List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from .batch import BatchOutcome, run_jobs_parallel


@runtime_checkable
class Executor(Protocol):
    id: str

    def run_jobs(self, jobs: Sequence[Tuple[str, str]],
                 max_workers: Optional[int] = None) -> List[BatchOutcome]:
        """Run each (job_json_path, out_npz_path) job, returning a
        BatchOutcome per job in the SAME order as `jobs`. One job's
        failure must never abort or lose another job's result."""
        ...


class LocalExecutor:
    """Reference implementation: today's Phase 4 path
    (`workbench.batch.run_jobs_parallel`'s local `ProcessPoolExecutor`),
    wrapped to satisfy `Executor`."""
    id = "local"

    def run_jobs(self, jobs, max_workers=None):
        return run_jobs_parallel(jobs, max_workers=max_workers)
