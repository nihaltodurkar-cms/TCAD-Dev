"""M32: gates for the benchmark suite and performance dashboard.

A benchmark suite that is not itself tested rots silently -- the failure
mode is not a red test, it is a table that quietly stops being produced,
or one that keeps being produced while measuring nothing. Both have
happened in this project's history (the G-E throughput floors ran
NOWHERE for two phases; M16/M20/M22-Schur sat "LANDED-PENDING-
VERIFICATION" with gates written but never executed).

So these gates check three things, in order of how badly they would hurt:

  1. The instrumentation RESTORES everything it patches. This is the one
     that could damage unrelated work: a leaked wrapper would stay on
     `linsolve.solve_linear` for the rest of the process, slowing and
     mis-measuring every later solve in the same pytest session.
  2. Every case still builds and runs. This is what stops a case from
     silently breaking when the API under it moves.
  3. The report is well-formed and keeps its caveats. The caveats are
     load-bearing: section 36's rule is about what a number may be
     claimed to mean, and a table that loses them becomes exactly the
     marketing language the rule forbids.
"""
import json
import subprocess
import sys
import os

import pytest

import benchmarks
from benchmarks import cases as bench_cases
from benchmarks.dashboard import render_markdown
from benchmarks.harness import Row, environment, run_case

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ----------------------------------------------------------------------
#  1. the instrumentation must not leak
# ----------------------------------------------------------------------
def test_instrumentation_restores_every_patch():
    """The probe swaps functions on live modules. If it ever failed to
    put them back, every subsequent solve in the process would run
    through a stale wrapper."""
    from pytcad import linsolve, device, device2d
    from benchmarks.instrument import instrumented

    before = {
        "solve_linear": linsolve.solve_linear,
        "_build_preconditioner": linsolve._build_preconditioner,
        "device.spsolve": device.spsolve,
        "device2d.spsolve": device2d.spsolve,
    }
    with instrumented():
        # Sanity: it really did patch, or this test proves nothing.
        assert linsolve.solve_linear is not before["solve_linear"]

    assert linsolve.solve_linear is before["solve_linear"]
    assert linsolve._build_preconditioner is before["_build_preconditioner"]
    assert device.spsolve is before["device.spsolve"]
    assert device2d.spsolve is before["device2d.spsolve"]


def test_instrumentation_restores_even_when_the_body_raises():
    """The interesting case: a benchmark that blows up mid-solve must
    still hand the solver back unwrapped."""
    from pytcad import linsolve
    from benchmarks.instrument import instrumented

    before = linsolve.solve_linear
    with pytest.raises(RuntimeError):
        with instrumented():
            raise RuntimeError("boom")
    assert linsolve.solve_linear is before


def test_instrumented_device_methods_are_restored():
    """The device probe shadows a CLASS method with an INSTANCE
    attribute; restoring means deleting it, not assigning the old value
    back (which would pin a bound method to the instance forever)."""
    import numpy as np
    from pytcad import Device1D
    from pytcad.mesh import uniform_mesh
    from benchmarks.instrument import instrumented

    x = uniform_mesh(1.0e-4, 40)
    dev = Device1D(x, np.where(x < 0.5e-4, -1e16, 1e17))
    with instrumented(dev):
        pass
    assert "_residual_jacobian" not in vars(dev), \
        "the wrapper is still shadowing the class method"
    assert dev._residual_jacobian.__self__ is dev


def test_the_probe_does_not_change_the_answer():
    """Instrumentation is a stopwatch, not a code path. The solve under
    it must be bit-identical to the same solve without it."""
    import numpy as np
    from pytcad import Device1D
    from pytcad.mesh import uniform_mesh
    from benchmarks.instrument import instrumented

    x = uniform_mesh(2.0e-4, 200)
    doping = np.where(x < 1.0e-4, -1e16, 1e17)

    plain = Device1D(x, doping)
    plain.solve_equilibrium()

    probed = Device1D(x, doping)
    with instrumented(probed):
        probed.solve_equilibrium()

    assert np.array_equal(probed.psi, plain.psi), \
        "instrumentation perturbed the solution"


# ----------------------------------------------------------------------
#  2. every case still builds and runs
# ----------------------------------------------------------------------
def test_all_nine_cases_are_declared():
    """Section 34 names B1-B7; B8/B9 were added for M31 P5 to give the
    unstructured path a row. A case quietly dropped from the list is
    the failure this asserts against."""
    assert [c.name for c in benchmarks.CASES] == \
        ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9"]
    for c in benchmarks.CASES:
        assert c.title and c.tests, f"{c.name} is missing its description"


@pytest.mark.parametrize("name", [c.name for c in bench_cases.CASES])
def test_case_runs_and_reports_a_real_measurement(name):
    """Each case, at quick size. Not a timing assertion -- a timing
    threshold here would fail on a loaded machine and teach everyone to
    ignore it. What is asserted is that the case RAN and that the
    dashboard's own columns got real values, which is what stops a case
    from silently measuring nothing."""
    row = run_case(bench_cases.get(name), size="quick")
    if row.skipped:
        pytest.skip(row.skipped)
    assert not row.error, row.error
    assert row.dof > 0, "no system size observed -- nothing was measured"
    assert row.nnz > row.dof, "NNZ should exceed DOF for any real stencil"
    assert row.linsolve_calls > 0, "no linear solve observed"
    assert row.total_s > 0.0


@pytest.mark.parametrize("name", ["B8", "B9"])
def test_the_unstructured_cases_report_a_real_assembly_time(name):
    """The unstructured cores assemble through MODULE-level functions,
    not through a device method, so the probe's device-handle branch
    cannot see them: before instrument.py patched them by name these
    rows reported assembly_s = 0, which reads as "assembly is free"
    rather than "assembly was not measured".

    This is the column M31 P5's justification rests on -- the phase
    ports exactly these functions -- so an absent number here is worse
    than a missing row."""
    row = run_case(bench_cases.get(name), size="quick")
    if row.skipped:
        pytest.skip(row.skipped)
    assert not row.error, row.error
    assert row.assembly_calls > 0, "assembly was not instrumented"
    assert row.assembly_s > 0.0, "assembly reported zero time"
    assert row.assembly_s < row.total_s, \
        "assembly cannot exceed the whole run"


def test_timing_and_memory_come_from_separate_runs():
    """tracemalloc's hook is not a uniform tax -- measured 1.19x on B3
    and 4.05x on B8 -- so a total_s taken under it is not comparable
    with anything. The harness runs the memory repeat separately; this
    pins that, because the failure mode is silent: the number still
    looks like a time.

    Asserted structurally rather than by comparing two timings, which
    would be a threshold test on a loaded machine."""
    row = run_case(bench_cases.get("B2"), size="quick", repeats=2)
    assert not row.error, row.error
    assert row.py_peak_mb > 0.0, "memory was not measured at all"
    assert not any("tracemalloc" in n for n in row.notes), \
        "a traced run's timings reached the row"


def test_repeats_of_one_admits_its_timing_is_inflated():
    """The honest fallback: with a single repeat there is no untraced
    run, so the row must SAY the timing carries tracemalloc rather than
    reporting it as if it did not."""
    row = run_case(bench_cases.get("B2"), size="quick", repeats=1)
    assert not row.error, row.error
    assert row.py_peak_mb > 0.0
    assert any("tracemalloc" in n for n in row.notes), \
        "an inflated timing was reported without saying so"


def test_a_failing_case_is_reported_as_a_row_not_an_exception():
    """A broken case must not deny you the other six. The row carries
    the error so the table shows what happened."""
    def _explode(size):
        raise ValueError("deliberate")

    bad = bench_cases.Case("BX", "broken", "nothing", _explode)
    row = run_case(bad, size="quick")
    assert not row.ok
    assert "deliberate" in row.error


def test_a_missing_optional_dependency_skips_rather_than_fails():
    """An absent optional dependency is a fact about the machine, not a
    regression -- so it must not read the same as a failure."""
    def _never_called(size):
        raise AssertionError("build must not run when a dep is missing")

    c = bench_cases.Case("BY", "needs a thing", "nothing", _never_called,
                         requires=("a_module_that_does_not_exist",))
    row = run_case(c, size="quick")
    assert row.skipped and not row.error


# ----------------------------------------------------------------------
#  3. the report keeps its caveats
# ----------------------------------------------------------------------
def test_environment_block_is_complete_enough_to_reproduce():
    """Section 36 lists reproducibility as a precondition for any
    performance claim, so a report without these is not a valid
    source for one."""
    env = environment()
    for key in ("python", "numpy", "scipy", "platform", "cpu_count",
                "OPENBLAS_NUM_THREADS", "accel", "timestamp"):
        assert key in env and env[key] not in (None, ""), f"missing {key}"


def test_report_renders_every_row_including_skips_and_failures():
    rows = [
        Row(name="B1", title="ok", tests="t", size="quick", dof=10, nnz=30,
            linsolve_calls=2, total_s=0.5),
        Row(name="B2", title="skipped", tests="t", size="quick",
            skipped="needs mpi4py"),
        Row(name="B3", title="failed", tests="t", size="quick",
            error="ValueError: nope"),
    ]
    md = render_markdown(rows, environment())
    for token in ("B1", "B2", "B3", "needs mpi4py", "ValueError: nope"):
        assert token in md, f"{token!r} missing from the report"


def test_the_report_states_what_its_numbers_are_not():
    """These caveats are the difference between a benchmark table and
    marketing language. If someone deletes them, this fails."""
    md = render_markdown([Row(name="B1", title="x", tests="t", size="quick")],
                         environment())
    assert "NOT Newton iterations" in md
    assert "residual AND Jacobian together" in md
    assert "tracemalloc" in md
    assert "Nothing here is a physics gate" in md


def test_size_is_always_recorded():
    """A quick-size number quoted as if it were full-size is the exact
    misreading this column exists to prevent."""
    for size in ("quick", "full"):
        row = Row(name="B1", title="x", tests="t", size=size)
        assert size in render_markdown([row], None)


# ----------------------------------------------------------------------
#  the CLI
# ----------------------------------------------------------------------
@pytest.mark.slow
def test_cli_runs_the_whole_suite_and_writes_json(tmp_path):
    """End-to-end: the entry point a human and CI both use."""
    out = tmp_path / "report.md"
    js = tmp_path / "report.json"
    proc = subprocess.run(
        [sys.executable, "-m", "benchmarks", "--out", str(out),
         "--json", str(js)],
        cwd=ROOT, capture_output=True, text=True,
        env=dict(os.environ, OPENBLAS_NUM_THREADS="1"))
    assert proc.returncode == 0, proc.stderr

    md = out.read_text()
    for c in benchmarks.CASES:
        assert f"**{c.name}**" in md

    data = json.loads(js.read_text())
    assert len(data["rows"]) == len(benchmarks.CASES)
    assert data["environment"]["numpy"]
    measured = [r for r in data["rows"] if not r["skipped"] and not r["error"]]
    assert measured, "the whole suite was skipped or failed"
    for r in measured:
        assert r["dof"] > 0 and r["total_s"] > 0.0
