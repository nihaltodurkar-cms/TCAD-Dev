"""P3-S1 (NATIVE-DESKTOP-PLAN.md 4.3, 17.7): the structured progress channel.

1. Grammar, on real solver runs (subprocesses, as the apps start them):
   every PYTCAD_PROGRESS line is one JSON object of the v1 grammar; the
   records follow the PYTCAD_STAGE markers in order; sweep points carry
   the swept contact and bias; transient steps match the stored times;
   done names the result; a failing job ends in an error record matching
   its PYTCAD_ERROR payload.
2. The live newton records ARE the stored convergence trace: same stages,
   iterations and metric values (the rate limit's drops counted in done).
3. The tap itself: non-finite numbers as null, one newton record per
   (stage, iteration), at most 50 records a second with the essentials
   never dropped, relayed sweep lines with a null contact, pass-through
   unchanged.
4. The QML JobRunner (decision 7): progress records never reach the
   console; the child runs unbuffered, so a stage's Newton lines arrive
   while it runs (measured on the 2D MOSFET's bias stage); lines split
   across reads -- mid-UTF-8 too -- and a final line without a newline
   are read whole.
"""
import io
import json
import os
import subprocess
import sys
import time

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from gui.services import examples, progress_channel  # noqa: E402
from gui.services.device_spec import SweepSpec, TransientSpec, WaveformSpec  # noqa: E402
from gui.services.job_runner import JobRunner  # noqa: E402
from gui.services.result_store import NpzResultStore  # noqa: E402

EVENTS = {"stage", "sweep_point", "newton", "transient_step", "done", "error"}


def _run(module, job, out):
    """Run a runner the way the apps do; return (stdout lines, stderr, records)."""
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    p = subprocess.run([sys.executable, "-m", module, str(job), str(out)], cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=600)
    lines = p.stdout.splitlines()
    records = [progress_channel.parse_line(l) for l in lines if l.startswith(progress_channel.PREFIX)]
    return p.returncode, lines, p.stderr, records


def _job(tmp_path, name, spec):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(spec.to_dict()))
    return path


@pytest.fixture(scope="module")
def sweep_run(tmp_path_factory):
    d = tmp_path_factory.mktemp("progress_sweep")
    spec = examples.EXAMPLES["diode_1d"]()
    spec.sweep = SweepSpec(contact="anode", start=0.0, stop=0.6, step=0.1)
    out = d / "iv.npz"
    return (*_run("gui.services.solver_runner", _job(d, "iv", spec), out), out, spec)


def _check_grammar(records):
    last_t = -1.0
    for r in records:
        assert r["v"] == 1 and r["event"] in EVENTS, r
        assert isinstance(r["t"], float) and r["t"] >= last_t, r
        last_t = r["t"]


# ------------------------------------------------------------------ 1. grammar
def test_a_sweep_run_emits_the_v1_grammar_in_order(sweep_run):
    code, lines, _err, records, out, spec = sweep_run
    assert code == 0
    _check_grammar(records)
    # one stage or sweep_point record per PYTCAD_STAGE marker, in the same order
    markers = [l[len("PYTCAD_STAGE="):] for l in lines if l.startswith("PYTCAD_STAGE=")]
    staged = [r for r in records if r["event"] in ("stage", "sweep_point")]
    assert len(staged) == len(markers)
    for m, r in zip(markers, staged):
        if m.startswith("sweep point"):
            assert r["event"] == "sweep_point" and m == f"sweep point {r['index'] + 1}/{r['count']}"
        else:
            assert r == {**r, "event": "stage", "stage": m}
    # sweep points: the swept contact and its bias, every point once
    points = [r for r in records if r["event"] == "sweep_point"]
    volts = spec.sweep.voltages()
    assert [p["index"] for p in points] == list(range(len(volts)))
    assert all(p["contact"] == "anode" and p["count"] == len(volts) for p in points)
    assert [p["value"] for p in points] == [float(v) for v in volts]
    # done last, naming the result actually written
    assert records[-1]["event"] == "done" and records[-1]["result"] == str(out)
    assert os.path.exists(out)


def test_a_transient_run_reports_each_accepted_step(tmp_path):
    spec = examples.EXAMPLES["diode_1d"]()
    spec.transient = TransientSpec(contact="anode", waveform=WaveformSpec(kind="step", v0=0.3, v1=0.0, t0=0.0),
                                   t_end=1e-9, dt0=1e-10)
    out = tmp_path / "tr.npz"
    code, _lines, _err, records = _run("gui.services.solver_runner", _job(tmp_path, "tr", spec), out)
    assert code == 0
    _check_grammar(records)
    steps = [r for r in records if r["event"] == "transient_step"]
    times = NpzResultStore(str(out)).transient_result().times
    assert len(steps) == len(times) - 1 and len(steps) > 0      # every step after t = 0
    np.testing.assert_allclose([s["time"] for s in steps], times[1:], rtol=2e-3)   # printed at %.3e
    assert all(s["stage"] == "transient" and s["iters"] >= 1 and s["dt"] > 0 for s in steps)


def test_a_cv_run_reports_its_stage_and_done(tmp_path):
    job = tmp_path / "cv.json"
    job.write_text(json.dumps({"nsub_cm3": -1e17, "tox_nm": 5.0, "gate": "n+poly", "qf_cm2": 1e12,
                               "T": 300.0, "vstart": -1.0, "vstop": 1.0, "vstep": 0.5}))
    code, _lines, _err, records = _run("gui.services.moscap_runner", job, tmp_path / "cv.npz")
    assert code == 0
    assert [r["event"] for r in records] == ["stage", "done"] and records[0]["stage"] == "cv"


def test_a_failing_job_ends_in_an_error_record_matching_its_stderr(tmp_path):
    spec = examples.EXAMPLES["diode_1d"]()
    spec.sweep = SweepSpec(contact="no_such_contact", start=0.0, stop=0.2, step=0.1)
    code, _lines, err, records = _run("gui.services.solver_runner", _job(tmp_path, "bad", spec), tmp_path / "bad.npz")
    assert code == 1
    payload = json.loads(next(l for l in err.splitlines() if l.startswith("PYTCAD_ERROR="))[len("PYTCAD_ERROR="):])
    assert records[-1]["event"] == "error"
    assert records[-1]["error"] == payload["error"] and records[-1]["message"] == payload["message"]
    assert not any(r["event"] == "done" for r in records)


# ---------------------------------------- 2. the live records are the stored trace
def test_newton_records_are_the_stored_convergence_trace(sweep_run):
    _code, _lines, _err, records, out, _spec = sweep_run
    trace = NpzResultStore(str(out)).run_record().trace
    stored = [(s.stage, it, {k: v[i] for k, v in s.metrics.items()})
              for s in trace for i, it in enumerate(s.iterations)]
    live = [(r["stage"], r["iter"], r["residual"]) for r in records if r["event"] == "newton"]
    dropped = records[-1]["dropped"]
    assert len(live) + dropped == len(stored), (len(live), dropped, len(stored))
    assert len(live) > 0
    remaining = list(stored)
    for rec in live:                     # each live record IS a stored iteration, in order
        while remaining and remaining[0][:2] != rec[:2]:
            remaining.pop(0)
        assert remaining, f"live record {rec} is not in the stored trace"
        assert remaining.pop(0)[2] == rec[2]


# ------------------------------------------------------------------ 3. the tap
class _Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def _tap():
    out, clock = io.StringIO(), _Clock()
    return progress_channel.ProgressTap(out, clock=clock), out, clock


def _records(out):
    return [progress_channel.parse_line(l) for l in out.getvalue().splitlines()
            if l.startswith(progress_channel.PREFIX)]


def test_the_tap_passes_every_line_through_unchanged():
    tap, out, _ = _tap()
    text = "PYTCAD_STAGE=bias\n    it  1  |F|=1e-3  |dpsi|=2e-4\nsome other line\npartial"
    tap.write(text)
    plain = [l for l in out.getvalue().split("\n") if not l.startswith(progress_channel.PREFIX)]
    assert "\n".join(plain) == text


def test_a_record_emitted_mid_line_starts_its_own_line():
    tap, out, _ = _tap()
    tap.write("half a li")                      # e.g. a crash mid-print, then main()'s error record
    tap.emit("error", error="RuntimeError", message="boom")
    lines = out.getvalue().split("\n")
    assert lines[0] == "half a li"
    assert progress_channel.parse_line(lines[1])["event"] == "error"


def test_non_finite_numbers_are_written_as_null():
    tap, out, _ = _tap()
    tap.emit("newton", stage="bias", iter=1, residual={"F": float("nan"), "dpsi": float("inf")})
    rec = _records(out)[0]
    assert rec["residual"] == {"F": None, "dpsi": None}
    assert "NaN" not in out.getvalue() and "Infinity" not in out.getvalue()


def test_one_newton_record_per_stage_and_iteration():
    tap, out, _ = _tap()
    tap.write("PYTCAD_STAGE=bias\n")
    tap.write("    it  3  |dpsi|=1e-2\n    it  3  |dpsi|=1e-2\n    it  4  |dpsi|=1e-3\n")
    tap.write("PYTCAD_STAGE=sweep point 1/2\n    it  3  |dpsi|=5e-3\n")   # a new stage: 3 again is new
    newton = [(r["stage"], r["iter"]) for r in _records(out) if r["event"] == "newton"]
    assert newton == [("bias", 3), ("bias", 4), ("sweep:0", 3)]


def test_at_most_50_records_a_second_and_essentials_never_dropped():
    tap, out, clock = _tap()
    tap.write("PYTCAD_STAGE=bias\n")
    for i in range(200):
        tap.write(f"    it {i:3d}  |dpsi|=1e-3\n")
    tap.write("PYTCAD_STAGE=extract\n")              # essential: past the limit, still written
    recs = _records(out)
    assert len([r for r in recs if r["event"] == "newton"]) == 49  # 50 minus the first stage record
    assert recs[-1] == {**recs[-1], "event": "stage", "stage": "extract"}
    assert tap.dropped == 151
    clock.now += 1.0                                  # a second later the window is open again
    tap.write("    it 999  |dpsi|=1e-3\n")
    assert _records(out)[-1]["iter"] == 999


def test_a_relayed_sweep_line_has_a_null_contact_and_value():
    tap, out, _ = _tap()
    tap.set_sweep_context("gate", 0.25)
    tap.write("PYTCAD_STAGE=sweep point 1/3\nPYTCAD_STAGE=sweep point 2/3\n")   # the 2nd: no context set
    pts = [r for r in _records(out) if r["event"] == "sweep_point"]
    assert (pts[0]["contact"], pts[0]["value"]) == ("gate", 0.25)
    assert (pts[1]["contact"], pts[1]["value"]) == (None, None)


# ----------------------------------------------------- 4. the QML JobRunner
@pytest.fixture(scope="module")
def qapp():
    yield QCoreApplication.instance() or QCoreApplication([])


def _run_runner(runner, spec, timeout_ms=300000):
    loop = QEventLoop()
    outcome = {}
    runner.finished.connect(lambda p: (outcome.update(kind="finished", path=p), loop.quit()))
    runner.failed.connect(lambda s, d: (outcome.update(kind="failed", summary=s, details=d), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    runner.start(spec)
    loop.exec()
    return outcome


def test_qml_runner_is_live_and_hides_progress_records(qapp, tmp_path):
    """Decision 7, measured: the MOSFET's bias-stage Newton lines arrive
    WHILE the stage runs (before this fix all nine arrived together at its
    end), and no PYTCAD_PROGRESS record reaches the console."""
    runner = JobRunner(work_dir=str(tmp_path))
    events = []
    t0 = time.perf_counter()
    runner.stageChanged.connect(lambda s: events.append(("stage", s, time.perf_counter() - t0)))
    runner.residualChanged.connect(lambda r: events.append(("residual", r, time.perf_counter() - t0)))
    console = []
    runner.progressLine.connect(console.append)
    outcome = _run_runner(runner, examples.EXAMPLES["mosfet_2d"]())
    assert outcome.get("kind") == "finished", outcome
    assert not any(l.startswith(progress_channel.PREFIX) for l in console)
    stages = [e for e in events if e[0] == "stage"]
    i_bias = next(i for i, e in enumerate(events) if e[:2] == ("stage", "bias"))
    i_next = next(i for i in range(i_bias + 1, len(events)) if events[i][0] == "stage")
    bias = [e[2] for e in events[i_bias + 1:i_next] if e[0] == "residual"]
    assert len(bias) >= 3, stages
    # spread over the stage, not one burst at its end
    assert bias[-1] - bias[0] > 0.25 * (events[i_next][2] - events[i_bias][2]), (bias, stages)


def test_qml_runner_starts_the_child_unbuffered(qapp, tmp_path):
    """Decision 7 itself. The test above passes even without it, because
    solver_runner's tap flushes after each record -- so this child prints
    plain, unflushed lines (as the core does, and as lines the tap drops
    or does not parse arrive): only an unbuffered child delivers them as
    printed, 0.25 s apart, instead of all five at its exit."""
    runner = JobRunner(work_dir=str(tmp_path), module="gui.tests.fixtures.slow_printer")
    seen = []
    t0 = time.perf_counter()
    runner.residualChanged.connect(lambda r: seen.append(time.perf_counter() - t0))
    outcome = _run_runner(runner, examples.EXAMPLES["diode_1d"](), timeout_ms=60000)
    assert outcome.get("kind") == "finished", outcome
    assert len(seen) == 5
    assert seen[-1] - seen[0] > 0.6, seen          # 4 x 0.25 s apart, not one burst


def test_qml_runner_reads_lines_split_across_reads(qapp, tmp_path):
    runner = JobRunner(work_dir=str(tmp_path), module="gui.tests.fixtures.chunked_writer")
    stages, residuals, console = [], [], []
    runner.stageChanged.connect(stages.append)
    runner.residualChanged.connect(residuals.append)
    runner.progressLine.connect(console.append)
    outcome = _run_runner(runner, examples.EXAMPLES["diode_1d"](), timeout_ms=60000)
    assert outcome.get("kind") == "finished", outcome        # RESULT_PATH without a newline, read
    assert stages == ["equilibrium"]                          # not "equil"
    assert residuals == [1.25e-2]                             # not 1.0
    assert "note: µm ✓" in console                  # the split UTF-8 character intact
    assert not any("PYTCAD_PROGRESS" in l or l.startswith('"t"') for l in console)
