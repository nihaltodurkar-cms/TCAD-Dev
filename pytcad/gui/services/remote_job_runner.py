"""M30 Phase 12 (GUI wiring): runs a DeviceSpec on a remote host over
SSH, without blocking Qt.

Same non-blocking design as `job_runner.JobRunner` (every step is a
QProcess, never a Python thread, so Stop is always a safe OS-level
kill) and the SAME public surface (`start(spec)`, `cancel()`,
`running`, `finished`/`failed`/`canceled` signals) -- StudyController's
existing per-row dispatch loop (M30 Phase 5) does not need to know
which kind of runner it holds.

Where JobRunner drives ONE local subprocess, this drives a small
sequence of them: mkdir (ensure the remote scratch dir exists) -> push
(scp the DeviceSpec JSON out) -> run (ssh the SAME
`python -m gui.services.solver_runner <job> <out>` entry point local
jobs use) -> pull (scp the result back), chained through each
QProcess's own `finished` signal so nothing blocks the event loop
mid-transfer. Mirrors `workbench.remote_executor.SSHTransport`'s
command shape exactly (that module's own docstring: "no credential
storage or new auth surface" -- same BatchMode=yes convention here),
just re-expressed as chained QProcess stages instead of one blocking
`subprocess.run` per step, since a GUI row cannot afford to block on
network I/O the way a headless batch call can.

`ssh_cmd`/`scp_cmd` are overridable (default `("ssh",)`/`("scp",)`)
purely so a test can point them at a local stand-in instead of a real
`ssh`/`scp` binary -- see gui/tests/fixtures/fake_ssh.py.
"""
import os
import sys
import tempfile
import uuid

from PySide6.QtCore import QObject, QProcess, QTimer, Signal, Property

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_KILL_GRACE_MS = 3000
_STAGES = ("mkdir", "push", "run", "pull")


class RemoteJobRunner(QObject):
    started = Signal()
    finished = Signal(str)          # result path
    failed = Signal(str, str)       # concise summary, expandable details
    canceled = Signal()

    def __init__(self, host, work_dir=None, parent=None,
                 ssh_cmd=("ssh",), scp_cmd=("scp",)):
        super().__init__(parent)
        self._host = host  # workbench.remote_executor.RemoteHost
        self._ssh_cmd = list(ssh_cmd)
        self._scp_cmd = list(scp_cmd)
        self._work_dir = work_dir or tempfile.mkdtemp(prefix="pytcad-gui-remote-")
        os.makedirs(self._work_dir, exist_ok=True)
        self._proc = None
        self._stage = None
        self._canceling = False
        self._stderr = ""
        self.result_path = ""
        self._job_path = ""
        self._remote_job = ""
        self._remote_out = ""

    # -- state --------------------------------------------------------
    @Property(bool, notify=started)
    def running(self):
        return self._proc is not None and self._proc.state() != QProcess.NotRunning

    # -- control ------------------------------------------------------
    def start(self, spec):
        if self.running:
            raise RuntimeError("a job is already running")
        run_id = uuid.uuid4().hex[:12]
        self._job_path = os.path.join(self._work_dir, f"job-{run_id}.json")
        self.result_path = os.path.join(self._work_dir, f"result-{run_id}.npz")
        spec.to_json(self._job_path)
        self._remote_job = f"{self._host.remote_workdir}/job-{run_id}.json"
        self._remote_out = f"{self._host.remote_workdir}/result-{run_id}.npz"

        self._canceling = False
        self._stderr = ""
        self._run_stage("mkdir")
        self.started.emit()

    def cancel(self):
        if not self.running:
            return
        self._canceling = True
        proc = self._proc
        self._proc.terminate()
        # Same grace-kill pattern as JobRunner.cancel(): the timer must
        # target THIS stage's process, and must tolerate this
        # RemoteJobRunner (or its owning Study row pool) being torn
        # down before it fires.
        def _kill_canceled():
            import shiboken6
            if proc is not None and shiboken6.isValid(proc) and \
                    proc.state() != QProcess.NotRunning:
                proc.kill()
        QTimer.singleShot(_KILL_GRACE_MS, _kill_canceled)

    # -- ssh/scp argv -----------------------------------------------------
    def _target(self):
        h = self._host
        return f"{h.user}@{h.host}" if h.user else h.host

    def _ssh_opts(self):
        h = self._host
        argv = ["-p", str(h.port), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        if h.identity_file:
            argv += ["-i", h.identity_file]
        return argv

    def _scp_opts(self):
        h = self._host
        argv = ["-P", str(h.port), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        if h.identity_file:
            argv += ["-i", h.identity_file]
        return argv

    def _argv_for_stage(self, stage):
        h = self._host
        if stage == "mkdir":
            return (self._ssh_cmd + self._ssh_opts() +
                   [self._target(), f"mkdir -p {h.remote_workdir}"])
        if stage == "push":
            return (self._scp_cmd + self._scp_opts() +
                   [self._job_path, f"{self._target()}:{self._remote_job}"])
        if stage == "run":
            cmd = f"{h.python} -m gui.services.solver_runner " \
                  f"{self._remote_job} {self._remote_out}"
            return self._ssh_cmd + self._ssh_opts() + [self._target(), cmd]
        if stage == "pull":
            return (self._scp_cmd + self._scp_opts() +
                   [f"{self._target()}:{self._remote_out}", self.result_path])
        raise ValueError(stage)

    # -- subprocess plumbing ------------------------------------------
    def _run_stage(self, stage):
        self._stage = stage
        self._stderr = ""
        argv = self._argv_for_stage(stage)
        self._proc = QProcess(self)
        self._proc.setWorkingDirectory(PROJECT_ROOT)
        self._proc.readyReadStandardError.connect(self._on_stderr)
        self._proc.finished.connect(self._on_stage_finished)
        self._proc.start(argv[0], argv[1:])

    def _on_stderr(self):
        self._stderr += bytes(self._proc.readAllStandardError()).decode("utf-8", "replace")

    def _on_stage_finished(self, exit_code, exit_status):
        proc, self._proc = self._proc, None
        proc.deleteLater()

        if self._canceling:
            self._cleanup_job_file()
            self.canceled.emit()
            return

        if exit_code != 0:
            self._cleanup_job_file()
            self.failed.emit(
                f"Remote {self._stage} failed on {self._host.host} "
                f"(exit {exit_code})", self._stderr or "no output")
            return

        idx = _STAGES.index(self._stage)
        if idx + 1 < len(_STAGES):
            self._run_stage(_STAGES[idx + 1])
            return

        # "pull" just finished.
        self._cleanup_job_file()
        if os.path.exists(self.result_path):
            self.finished.emit(self.result_path)
        else:
            self.failed.emit(
                f"Remote result missing after pull from {self._host.host}",
                self._stderr or "no output")

    def _cleanup_job_file(self):
        if self._job_path and os.path.exists(self._job_path):
            try:
                os.remove(self._job_path)
            except OSError:
                pass
