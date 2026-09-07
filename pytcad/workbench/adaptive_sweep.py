"""M30 Phase 11: adaptive sweep.

The smallest useful adaptive-sampling criterion over a SINGLE parameter
axis: start from a coarse grid, evaluate a scalar reduction at every
point, then insert the midpoint between any two ADJACENT points whose
reduced values differ by more than `threshold`, repeating for up to
`max_rounds`. This is intentionally NOT a general DOE/adaptive-sampling
framework -- one parameter, one scalar criterion, midpoint bisection
only -- matching this repo's consistent "simple, stated, bounded
scope" pattern (the same spirit as Phase 2's "simple Nelder-Mead" and
Phase 10's narrow constraint vocabulary).

Split into a pure algorithm (`adaptive_refine`, no solver/Qt/IO
dependency -- easy to test with a synthetic scalar function) and a
device-solving wrapper (`run_adaptive_sweep`) that dispatches each
round's new points through workbench.batch's real parallel executor,
never a bespoke sequential loop.
"""
import os
import tempfile

import numpy as np

from .batch import run_jobs_parallel


def _refine_once(values, reduced, threshold):
    """New midpoints to sample this round: between any two adjacent
    sampled `values` whose `reduced` scalars differ by more than
    `threshold`.  A pair with a None reduction (a failed evaluation) is
    skipped -- refining around a failure cannot be judged by this
    criterion.  Returns a list, possibly empty."""
    sorted_vals = sorted(values)
    new_points = []
    for a, b in zip(sorted_vals, sorted_vals[1:]):
        ra, rb = reduced.get(a), reduced.get(b)
        if ra is None or rb is None:
            continue
        if abs(rb - ra) > threshold:
            mid = (a + b) / 2.0
            if mid not in reduced:
                new_points.append(mid)
    return new_points


def adaptive_refine(initial_values, evaluate, threshold, max_rounds=5):
    """Pure refinement loop.  `evaluate(values)` is called once per
    round with the list of NEW values needing a reduction this round
    (the first call gets `initial_values` itself) and must return a
    {value: reduced_scalar_or_None} mapping for exactly those values --
    batching every round's points into one `evaluate` call is what lets
    a caller parallelize a whole round at once (see run_adaptive_sweep
    below).  Terminates after `max_rounds` rounds NO MATTER WHAT the
    criterion does -- a `for` loop bounded by `max_rounds`, not a
    `while True`, so a pathological, never-quieting criterion cannot
    hang this function (gate G-TERMINATES).

    Returns (all_values_sorted, reduced_dict, rounds_run)."""
    values = sorted(set(float(v) for v in initial_values))
    reduced = dict(evaluate(values))
    rounds_run = 0
    for _ in range(max_rounds):
        new_points = _refine_once(values, reduced, threshold)
        if not new_points:
            break
        reduced.update(evaluate(new_points))
        values = sorted(set(values) | set(new_points))
        rounds_run += 1
    return values, reduced, rounds_run


def run_adaptive_sweep(template_id, base_values, param_name, initial_values,
                       field_name, threshold, max_rounds=5, max_workers=None,
                       work_dir=None):
    """Device-solving wrapper: `evaluate` builds+solves one batch of
    trial values (through the existing template path and
    workbench.batch.run_jobs_parallel -- the SAME parallel executor
    Phase 4/5 already use, not a reimplementation) and reduces each
    result's `field_name` scalar field to max(...), the same reduction
    convention Phase 6's matrix viewer already uses.  A value the
    template rejects, or whose job fails to solve, reduces to None
    (skipped by the refinement criterion, never crashes the sweep).

    Returns (values, reduced, rounds_run, result_paths) --
    `result_paths` maps each successfully-solved value to its `.npz`
    path."""
    from .adapters.spec import spec_from_domain
    from .core.templates import get_template
    from gui.services.result_store import NpzResultStore

    work_dir = work_dir or tempfile.mkdtemp(prefix="pytcad-adaptive-")
    os.makedirs(work_dir, exist_ok=True)
    template = get_template(template_id)
    result_paths = {}
    _counter = {"n": 0}

    def evaluate(batch_values):
        jobs, job_values = [], []
        out = {}
        for v in batch_values:
            row = dict(base_values)
            row[param_name] = v
            try:
                device = template.build(row)
            except (ValueError, KeyError):
                out[v] = None
                continue
            spec = spec_from_domain(device)
            spec.bias = None
            spec.sweep = None
            _counter["n"] += 1
            job_path = os.path.join(work_dir, f"job-{_counter['n']}.json")
            out_path = os.path.join(work_dir, f"result-{_counter['n']}.npz")
            spec.to_json(job_path)
            jobs.append((job_path, out_path))
            job_values.append(v)

        outcomes = run_jobs_parallel(jobs, max_workers=max_workers)
        for v, outcome in zip(job_values, outcomes):
            if outcome.error is not None:
                out[v] = None
                continue
            store = NpzResultStore(outcome.out_path)
            out[v] = float(np.max(store.scalar_field(field_name).values))
            result_paths[v] = outcome.out_path
        return out

    values, reduced, rounds_run = adaptive_refine(
        initial_values, evaluate, threshold, max_rounds=max_rounds)
    return values, reduced, rounds_run, result_paths
