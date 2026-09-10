"""M30 Phase 4 acceptance tests: batch parallelism.

Contract under test (workbench/batch.py):
  - `run_jobs_parallel` runs N independent solver_runner jobs
    concurrently in a process pool, in the SAME order as given,
    isolating one bad job from the rest.
  - Each pool worker pins OPENBLAS_NUM_THREADS=1 before doing any work
    (CLAUDE.md's own documented oversubscription hazard).
  - `solve_split_matrix` wires workbench.splits.run_split_matrix (Phase
    1) into the parallel pool: a row that failed to BUILD never reaches
    the solver at all, and results are bit-identical to running the
    same rows sequentially through the ordinary run_job path --
    parallelism must not change answers.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from workbench.batch import (
    run_jobs_parallel, solve_split_matrix, worker_blas_thread_setting,
)
from workbench.workflow import run_deck_full


def _pn_diode_job(tmp_path, na_cm3, name):
    from workbench.adapters.spec import spec_from_domain
    from workbench.core.templates import get_template

    device = get_template("pn_diode").build(
        {"length_cm": 1e-4, "height_cm": 2e-5, "nx": 20, "ny": 6,
         "na_cm3": na_cm3, "nd_cm3": 1e18})
    spec = spec_from_domain(device)
    spec.bias = None
    spec.sweep = None
    job_path = str(tmp_path / f"{name}.json")
    out_path = str(tmp_path / f"{name}.npz")
    spec.to_json(job_path)
    return job_path, out_path


# ----------------------------------------------------------------------
#  G-PARALLEL-CORRECT: results match running the same jobs sequentially
# ----------------------------------------------------------------------
def test_run_jobs_parallel_matches_sequential_results(tmp_path):
    from gui.services.solver_runner import run_job

    jobs = [_pn_diode_job(tmp_path, na, f"job{i}")
            for i, na in enumerate([-1e18, -2e18, -3e18])]

    outcomes = run_jobs_parallel(jobs, max_workers=3)
    assert all(o.error is None for o in outcomes)

    for (job_path, _), outcome in zip(jobs, outcomes):
        seq_out = job_path.replace(".json", "-seq.npz")
        run_job(job_path, seq_out)
        with np.load(outcome.out_path) as par, np.load(seq_out) as seq:
            assert np.array_equal(par["field__potential"],
                                  seq["field__potential"]), \
                "parallel result differs from sequential -- parallelism " \
                "must not change answers"


def test_run_jobs_parallel_preserves_input_order(tmp_path):
    jobs = [_pn_diode_job(tmp_path, na, f"order{i}")
            for i, na in enumerate([-1e18, -2e18, -3e18, -4e18])]
    outcomes = run_jobs_parallel(jobs, max_workers=4)
    assert [o.out_path for o in outcomes] == [op for _, op in jobs]


def test_run_jobs_parallel_with_no_jobs_returns_empty():
    assert run_jobs_parallel([]) == []


# ----------------------------------------------------------------------
#  G-ISOLATION: one worker's job failure does not crash the pool or
#  lose other workers' results
# ----------------------------------------------------------------------
def test_run_jobs_parallel_isolates_a_bad_job(tmp_path):
    good1 = _pn_diode_job(tmp_path, -1e18, "good1")
    good2 = _pn_diode_job(tmp_path, -2e18, "good2")
    bad = (str(tmp_path / "does-not-exist.json"), str(tmp_path / "bad.npz"))

    outcomes = run_jobs_parallel([good1, bad, good2], max_workers=3)

    assert outcomes[0].error is None and outcomes[0].out_path is not None
    assert outcomes[1].error is not None and outcomes[1].out_path is None
    assert outcomes[2].error is None and outcomes[2].out_path is not None


# ----------------------------------------------------------------------
#  G-ENV-GUARD: pool workers actually run with OPENBLAS_NUM_THREADS=1
# ----------------------------------------------------------------------
def test_pool_workers_pin_single_threaded_blas():
    import concurrent.futures as cf

    from workbench.batch import _pin_single_threaded_blas
    with cf.ProcessPoolExecutor(
            max_workers=1, initializer=_pin_single_threaded_blas) as pool:
        setting = pool.submit(worker_blas_thread_setting).result()
    assert setting == "1"


# ----------------------------------------------------------------------
#  solve_split_matrix: wires Phase 1 splits into the parallel pool
# ----------------------------------------------------------------------
_MOS_DECK = """
go
template mos_capacitor
na_cm3 = -1e16
nx = 20
ny = 8
split tox_cm = 7e-7, 8e-7, 9e-7
end
"""


def test_solve_split_matrix_solves_every_row(tmp_path):
    run = run_deck_full(_MOS_DECK)
    paired = solve_split_matrix(run, work_dir=str(tmp_path))

    assert len(paired) == 3
    for row, outcome in paired:
        assert row.error is None and row.device is not None
        assert outcome is not None and outcome.error is None
        with np.load(outcome.out_path) as d:
            assert "field__potential" in d.files


def test_solve_split_matrix_skips_solving_a_build_error_row(tmp_path):
    deck = """
    go
    template mos_capacitor
    split tox_cm = 7e-7, -1.0, 9e-7
    end
    """
    run = run_deck_full(deck)
    paired = solve_split_matrix(run, work_dir=str(tmp_path))

    assert len(paired) == 3
    (row0, out0), (row1, out1), (row2, out2) = paired
    assert row0.error is None and out0 is not None and out0.error is None
    assert row1.error is not None and out1 is None       # never reached solve
    assert row2.error is None and out2 is not None and out2.error is None
