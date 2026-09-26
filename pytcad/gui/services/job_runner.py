"""Runs a DeviceSpec through the solver subprocess, without blocking Qt.

Why a process and not a thread: pytcad's Newton loops are synchronous,
have no cancellation hook, and spend their time inside SciPy's C-level
sparse LU.  A Python thread there cannot be interrupted safely and
cannot be killed at all.  A process can -- the OS reclaims everything --
so Stop is implemented as a process kill, which is exactly the "do not
terminate a numerical solver unsafely" requirement satisfied without
touching validated numerical code.
"""
import json
import math
import os
import re
import shutil
import sys
import tempfile
import uuid

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, QTimer, Signal, Property

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Cosmetic only.  pytcad's NewtonOptions(verbose=True) prints lines like
#   "    eq it  3  |dpsi|=1.234e-02"                        (equilibrium)
#   "   it  3  |F|=9.9e-01  |dpsi|=1.234e-02  |dn/n|=5.678e-03"  (bias)
# We scrape an iteration number and the leading residual out of them for
# the progress display and nothing else -- results always come from the
# .npz.  If this format ever changes, progress degrades to a plain
# running indicator; nothing breaks. Same two-regex convention already
# used by solver_runner.py's own _trace_from_output (_ITERATION/_METRIC)
# for the post-hoc convergence trace stamped into the result file --
# this is the LIVE (during-the-run) counterpart of that same text.
_ITER_RE = re.compile(r"\bit\s+(\d+)\b")
_RESIDUAL_RE = re.compile(r"\|\s*dpsi\s*\|\s*=\s*(-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?\d+)?)")
_STAGE_RE = re.compile(r"^PYTCAD_STAGE=(\w+)")
_RESULT_RE = re.compile(r"^RESULT_PATH=(.+)$")
_ERROR_RE = re.compile(r"^PYTCAD_ERROR=(.+)$")

_KILL_GRACE_MS = 3000


class JobRunner(QObject):
    started = Signal()
    progressLine = Signal(str)
    stageChanged = Signal(str)
    iterationChanged = Signal(int)
    residualChanged = Signal(float)  # latest |dpsi| Newton-update residual
    finished = Signal(str)          # result path
    failed = Signal(str, str)       # concise summary, expandable details
    canceled = Signal()

    def __init__(self, work_dir=None, parent=None, module="gui.services.solver_runner"):
        super().__init__(parent)
        self._work_dir = work_dir or tempfile.mkdtemp(prefix="pytcad-gui-")
        os.makedirs(self._work_dir, exist_ok=True)
        self._module = module
        self._proc = None
        self._canceling = False
        self._stderr = ""
        self._result_seen = None
        self._stdout_pending = b""
        self.result_path = ""
        self._job_path = ""

    # -- state --------------------------------------------------------
    @Property(bool, notify=started)
    def running(self):
        return self._proc is not None and self._proc.state() != QProcess.NotRunning

    # -- control ------------------------------------------------------
    def start(self, spec):
        if self.running:
            raise RuntimeError("a job is already running")
        run_id = uuid.uuid4().hex[:12]
        job_path = os.path.join(self._work_dir, f"job-{run_id}.json")
        # Unique per run: a canceled run's missing file can then never be
        # mistaken for some other run's completed result.
        self.result_path = os.path.join(self._work_dir, f"result-{run_id}.npz")
        self._job_path = job_path
        spec.to_json(job_path)

        self._canceling = False
        self._stderr = ""
        self._result_seen = None
        self._stdout_pending = b""

        self._proc = QProcess(self)
        self._proc.setWorkingDirectory(PROJECT_ROOT)
        # Unbuffered child stdout (NATIVE-DESKTOP-PLAN.md 17.7, decision 7):
        # the core's verbose Newton prints do not flush, so through a pipe a
        # stage's lines used to arrive all at once at the next PYTCAD_STAGE
        # marker -- measured: a 1.3 s MOSFET bias stage showed nothing, then
        # all nine lines at its end. The Solver Telemetry panel is live now.
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        # UTF-8 child stdio (17.10): a piped stdout on Windows is otherwise
        # cp1252, which garbled RESULT_PATH for a work dir under a non-ASCII
        # user name (the run reported failed) and crashed the final print
        # for a character outside cp1252.
        env.insert("PYTHONIOENCODING", "utf-8")
        self._proc.setProcessEnvironment(env)
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(self._on_finished)
        self._proc.start(sys.executable,
                         ["-m", self._module, job_path, self.result_path])
        self.started.emit()

    def cancel(self):
        if not self.running:
            return
        self._canceling = True
        proc = self._proc          # final-review I-5: kill THIS process
        self._proc.terminate()
        # The 3 s grace timer must target the process we're canceling,
        # not "whatever self._proc holds when the timer fires" -- a quick
        # cancel-then-restart would otherwise murder the fresh run.
        def _kill_canceled():
            import shiboken6
            # A canceled JobRunner's own owner (e.g. a Study's row pool,
            # M30 Phase 5) can be destroyed before this grace timer
            # fires -- confirmed directly via adversarial testing
            # (immediate cancel-then-teardown): accessing `proc.state()`
            # on an already-deleted QProcess raises a shiboken
            # RuntimeError rather than returning cleanly.
            if proc is not None and shiboken6.isValid(proc) and \
                    proc.state() != QProcess.NotRunning:
                proc.kill()
        QTimer.singleShot(_KILL_GRACE_MS, _kill_canceled)

    # -- subprocess plumbing ------------------------------------------
    def _on_stdout(self):
        # Whole lines only: a read can end mid-line (and mid-UTF-8
        # character), which the unbuffered child makes common. The
        # unfinished tail waits for the next read, or for _on_finished.
        data = self._stdout_pending + bytes(self._proc.readAllStandardOutput())
        *complete, self._stdout_pending = data.split(b"\n")
        for raw in complete:
            self._handle_line(raw.decode("utf-8", "replace").rstrip("\r"))

    def _handle_line(self, line):
        if not line.strip():
            return
        # The native app's structured progress records (P3-S1): not for
        # the QML console, which keeps showing the plain lines.
        if line.startswith("PYTCAD_PROGRESS "):
            return
        m = _RESULT_RE.match(line)
        if m:
            self._result_seen = m.group(1)
            return
        m = _STAGE_RE.match(line)
        if m:
            self.stageChanged.emit(m.group(1))
            return
        m = _ITER_RE.search(line)
        if m:
            self.iterationChanged.emit(int(m.group(1)))
        m = _RESIDUAL_RE.search(line)
        if m:
            try:
                val = float(m.group(1))
            except ValueError:
                val = None
            if val is not None and math.isfinite(val):
                self.residualChanged.emit(val)
        self.progressLine.emit(line)

    def _on_stderr(self):
        self._stderr += bytes(self._proc.readAllStandardError()).decode("utf-8", "replace")

    def _on_finished(self, exit_code, exit_status):
        # the last line may have no newline, or not have been read yet
        tail = self._stdout_pending + bytes(self._proc.readAllStandardOutput())
        self._stdout_pending = b""
        for raw in tail.split(b"\n"):
            if raw.strip():
                self._handle_line(raw.decode("utf-8", "replace").rstrip("\r"))
        proc, self._proc = self._proc, None
        proc.deleteLater()

        # The job-*.json input never gets an atomic-rename-away like the
        # .tmp.npz/.tmp.json result artifacts do -- solver_runner.py only
        # reads it, so nothing else ever removes it. Clean it up here on
        # every outcome (success, failure, or cancel) so a long GUI
        # session doesn't accumulate one orphaned file per run in the
        # temp work dir.
        if self._job_path and os.path.exists(self._job_path):
            try:
                os.remove(self._job_path)
            except OSError:
                pass

        if self._canceling:
            # Belt and braces: solver_runner's atomic rename already means
            # a killed run leaves nothing at result_path, but if a rename
            # landed in the same instant, drop it rather than present a
            # result the user asked to throw away.
            if os.path.exists(self.result_path):
                try:
                    os.remove(self.result_path)
                except OSError:
                    pass
            self._cleanup_tmp()
            self._cleanup_stale_state_dir()
            self.canceled.emit()
            return

        self._cleanup_tmp()

        if exit_code == 0 and self._result_seen and os.path.exists(self._result_seen):
            self.finished.emit(self._result_seen)
            return

        self._cleanup_stale_state_dir()
        summary, details = self._parse_failure()
        self.failed.emit(summary, details)

    def _cleanup_tmp(self):
        # ".tmp.npz" is solver_runner.py's own atomic-write suffix;
        # ".tmp.json" is process_runner.py's (its "result" is a JSON
        # manifest, not an .npz -- see run_flow()'s tmp_manifest). Both
        # are always renamed away on success, so removing them
        # unconditionally here is a no-op in that case and only ever
        # does something for a run that didn't finish cleanly.
        for suffix in (".tmp.npz", ".tmp.json"):
            tmp = self.result_path + suffix
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def _cleanup_stale_state_dir(self):
        """Some runner modules (process_runner.py) write per-run
        checkpoint artifacts into a sibling "<result-stem>-state/"
        directory instead of a single result file (see run_flow()'s
        state_dir). Only called on cancel/failure -- a successful run's
        state_dir is the ProcessResultStore's actual data and must
        never be touched. A no-op for runner modules (e.g.
        solver_runner.py) that never create one."""
        state_dir = os.path.splitext(self.result_path)[0] + "-state"
        if os.path.isdir(state_dir):
            shutil.rmtree(state_dir, ignore_errors=True)

    def _parse_failure(self):
        for line in self._stderr.splitlines():
            m = _ERROR_RE.match(line)
            if m:
                try:
                    payload = json.loads(m.group(1))
                    return (f"{payload['error']}: {payload['message']}",
                            payload.get("traceback", self._stderr))
                except (ValueError, KeyError):
                    break
        return ("Simulation failed (see details).", self._stderr or "no output")
