"""M30 Phase 11 acceptance tests: adaptive sweep.

Contract under test (workbench/adaptive_sweep.py):
  - adaptive_refine (pure algorithm) refines where a synthetic scalar
    function has a sharp feature, leaving a flat region coarse
    (G-REFINES-WHERE-NEEDED).
  - It terminates within its stated max_rounds bound even when the
    criterion never quiets down -- a `for`-bounded loop, no infinite-
    loop risk (G-TERMINATES).
  - run_adaptive_sweep (device-solving wrapper) dispatches every
    round's new points through workbench.batch.run_jobs_parallel, the
    SAME executor Phase 4/5 already use -- not a bespoke sequential
    reimplementation (G-REUSES-BATCH).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from workbench.adaptive_sweep import adaptive_refine, run_adaptive_sweep


# ----------------------------------------------------------------------
#  G-REFINES-WHERE-NEEDED
# ----------------------------------------------------------------------
def _step_function(v):
    """Flat at 0.0 below x=5.0, flat at 10.0 above -- a sharp feature
    localized entirely around x=5.0."""
    return 0.0 if v < 5.0 else 10.0


def test_adaptive_refine_samples_densely_near_a_sharp_feature():
    def evaluate(values):
        return {v: _step_function(v) for v in values}

    initial = [0.0, 2.5, 5.0, 7.5, 10.0]
    values, reduced, rounds_run = adaptive_refine(
        initial, evaluate, threshold=1.0, max_rounds=6)

    assert rounds_run > 0
    near_feature = [v for v in values if 4.0 <= v <= 6.0]
    far_from_feature = [v for v in values if v <= 1.0 or v >= 9.0]
    # denser sampling near the jump than in the genuinely flat regions
    assert len(near_feature) > len(far_from_feature)
    # the flat regions gained NO new points at all -- refinement is
    # localized, not a blanket global refinement
    assert far_from_feature == [0.0] or far_from_feature == [10.0] \
        or far_from_feature == [0.0, 10.0]


def test_adaptive_refine_stops_once_the_criterion_quiets_down():
    def evaluate(values):
        return {v: 1.0 for v in values}   # perfectly flat -- no gradient ever
    values, reduced, rounds_run = adaptive_refine(
        [0.0, 1.0, 2.0], evaluate, threshold=0.1, max_rounds=10)
    assert rounds_run == 0
    assert values == [0.0, 1.0, 2.0]


# ----------------------------------------------------------------------
#  G-TERMINATES: a pathological, never-quieting criterion still stops
#  at max_rounds, never hangs
# ----------------------------------------------------------------------
def test_adaptive_refine_terminates_on_a_pathological_criterion():
    import itertools
    counter = itertools.count()

    def evaluate(values):
        # alternating +-1e9 -- the gradient between ANY two adjacent
        # points always exceeds any realistic threshold, forever.
        return {v: (1e9 if next(counter) % 2 == 0 else -1e9) for v in values}

    values, reduced, rounds_run = adaptive_refine(
        [0.0, 10.0], evaluate, threshold=1.0, max_rounds=5)
    assert rounds_run == 5
    # bounded growth: at most one new midpoint per existing gap per
    # round -- never unbounded/runaway
    assert len(values) <= 2 + (2 ** 5)


def test_adaptive_refine_skips_a_failed_evaluation_pair():
    def evaluate(values):
        return {v: (None if v == 5.0 else 0.0) for v in values}
    values, reduced, rounds_run = adaptive_refine(
        [0.0, 5.0, 10.0], evaluate, threshold=0.5, max_rounds=3)
    assert rounds_run == 0          # neither pair touching the None can refine
    assert reduced[5.0] is None


# ----------------------------------------------------------------------
#  G-REUSES-BATCH: the device-solving wrapper dispatches through the
#  real Phase 4 executor, not a reimplementation
# ----------------------------------------------------------------------
_BASE = {"length_cm": 1e-4, "height_cm": 2e-5, "nx": 16, "ny": 6,
         "nd_cm3": 1e18}


def test_run_adaptive_sweep_dispatches_through_batch_executor(tmp_path, monkeypatch):
    import workbench.adaptive_sweep as aw_module

    calls = []
    real_run_jobs_parallel = aw_module.run_jobs_parallel

    def _spy(jobs, max_workers=None):
        calls.append(len(jobs))
        return real_run_jobs_parallel(jobs, max_workers=max_workers)
    monkeypatch.setattr(aw_module, "run_jobs_parallel", _spy)

    values, reduced, rounds_run, paths = run_adaptive_sweep(
        "pn_diode", _BASE, "na_cm3", [-1e18, -3e18],
        "doping", threshold=1e17, max_rounds=2, work_dir=str(tmp_path))

    assert calls, "run_jobs_parallel (Phase 4's executor) was never called"
    assert len(calls) >= 1
    for v in values:
        if reduced.get(v) is not None:
            assert v in paths


def test_run_adaptive_sweep_skips_a_template_rejected_value(tmp_path):
    values, reduced, rounds_run, paths = run_adaptive_sweep(
        "pn_diode", _BASE, "na_cm3", [-1e18, -1e30],   # -1e30 out of range
        "doping", threshold=1e17, max_rounds=1, work_dir=str(tmp_path))
    assert reduced[-1e30] is None
    assert -1e30 not in paths
    assert reduced[-1e18] is not None
