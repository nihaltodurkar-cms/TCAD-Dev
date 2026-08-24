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
import os
import re
import shutil
import sys
import tempfile
import uuid

from PySide6.QtCore import QObject, QProcess, QTimer, Signal, Property

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Cosmetic only.  pytcad's NewtonOptions(verbose=True) prints lines like
#   "    it  3  |dpsi|=1.234e-02  |dn/n|=5.678e-03"
# We scrape an iteration number out of them for the progress display and
# nothing else -- results always come from the .npz.  If this format ever
# changes, progress degrades to a plain running indicator; nothing breaks.
_ITER_RE = re.compile(r"\bit\s+(\d+)\b")
_STAGE_RE = re.compile(r"^PYTCAD_STAGE=(\w+)")
_RESULT_RE = re.compile(r"^RESULT_PATH=(.+)$")
_ERROR_RE = re.compile(r"^PYTCAD_ERROR=(.+)$")

_KILL_GRACE_MS = 3000


class JobRunner(QObject):
    started = Signal()
    progressLine = Signal(str)
    stageChanged = Signal(str)
    iterationChanged = Signal(int)
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
        self.result_path = ""

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
        spec.to_json(job_path)

        self._canceling = False
        self._stderr = ""
        self._result_seen = None

        self._proc = QProcess(self)
        self._proc.setWorkingDirectory(PROJECT_ROOT)
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
            if proc is not None and proc.state() != QProcess.NotRunning:
                proc.kill()
        QTimer.singleShot(_KILL_GRACE_MS, _kill_canceled)

    # -- subprocess plumbing ------------------------------------------
    def _on_stdout(self):
        text = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in text.splitlines():
            if not line.strip():
                continue
            m = _RESULT_RE.match(line)
            if m:
                self._result_seen = m.group(1)
                continue
            m = _STAGE_RE.match(line)
            if m:
                self.stageChanged.emit(m.group(1))
                continue
            m = _ITER_RE.search(line)
            if m:
                self.iterationChanged.emit(int(m.group(1)))
            self.progressLine.emit(line)

    def _on_stderr(self):
        self._stderr += bytes(self._proc.readAllStandardError()).decode("utf-8", "replace")

    def _on_finished(self, exit_code, exit_status):
        proc, self._proc = self._proc, None
        proc.deleteLater()

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
