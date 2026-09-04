"""Performance pass (2026-09-04), item 5: timing regression gate for a
real 2D solve through the GUI's actual job pipeline.

Audit finding (cProfile on gui/services/solver_runner.py's run_job()
for mosfet_2d): 1.11s wall time, 91% (0.909s) in
scipy.sparse.linalg._dsolve._superlu.gssv -- the actual physics solve
(direct sparse LU), not GUI-layer overhead. This is explicitly NOT a
GUI-performance target: touching it means touching the frozen
numerical core (pytcad/pytcad/*.py), which AGENTS.md gates behind
explicit milestone sign-off + FD-Jacobian-first + bit-identical checks
-- out of scope for a "GUI performance" mandate. No core file is
modified by this pass for this item.

This test exists purely as a regression gate: run_job() itself (the
GUI-facing entry point, subprocess-isolated per AGENTS.md's layering
rule) must keep completing a real mosfet_2d solve within a generous
time bound, so a future accidental slowdown anywhere in the pipeline
-- GUI-side job setup, not just the core solve -- is caught.
"""
import json
import os
import tempfile
import time

from gui.services import examples
from gui.services.solver_runner import run_job


def test_mosfet_2d_solve_completes_within_a_generous_time_bound():
    spec = examples.mosfet_example_spec()
    d = tempfile.mkdtemp()
    job_path = os.path.join(d, "job.json")
    out_path = os.path.join(d, "out.npz")
    with open(job_path, "w") as fh:
        json.dump(spec.to_dict(), fh)

    t0 = time.perf_counter()
    run_job(job_path, out_path, capture_trace=False)
    elapsed = time.perf_counter() - t0

    assert os.path.exists(out_path)
    # Measured 1.11s; 10s is a generous ~9x margin, immune to normal
    # machine-load noise while still catching a real regression (e.g.
    # an accidental switch away from the direct sparse solve, or a
    # GUI-side job-setup regression unrelated to the core solve itself).
    assert elapsed < 10.0, (
        f"mosfet_2d solve via run_job() got slow: {elapsed:.2f}s "
        f"(measured baseline: 1.11s)"
    )
