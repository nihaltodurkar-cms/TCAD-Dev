"""M30 Phase 12: remote execution over SSH.

`RemoteExecutor` implements the same `Executor` protocol
(`workbench/executor.py`) as the local `ProcessPoolExecutor` path
(`workbench.batch.run_jobs_parallel`) -- "replace/augment the executor's
worker pool with remote workers," per the plan doc, not a new runner
concept. A caller (e.g. `workbench.batch.solve_split_matrix`) can swap
this in for `LocalExecutor` unmodified (G-PROTOCOL-PARITY).

Transport is the one seam that actually talks to a remote host
(`push`/`run`/`pull`). `SSHTransport` is the production implementation
(plain `ssh`/`scp` subprocesses -- no new dependency, and it reuses the
SAME entry point local jobs already use,
`python -m gui.services.solver_runner <job.json> <out.npz>`, over the
user's own SSH keys via `BatchMode=yes`; no credential storage or new
auth surface is introduced here). Tests inject a fake `Transport`
standing in for "a second local process pretending to be remote over
loopback" (plan doc section 16), since a real remote worker fleet is
outside this repo's test environment.

The job payload itself (the `DeviceSpec` JSON written by
`workbench.batch.solve_split_matrix`/`workbench.calibration`) is pushed
and pulled byte-for-byte unchanged -- no remote-transport-specific
field is added to it (G-NO-TRANSPORT-IN-DEVICESPEC): this module only
decides WHERE that same file runs, never what is in it.
"""
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from .batch import BatchOutcome

DEFAULT_JOB_TIMEOUT = 600  # seconds; a hung remote job must not hang the study forever


@dataclass(frozen=True)
class RemoteHost:
    """One remote worker. `identity_file`/`user` are passed straight
    to ssh/scp -- auth itself stays whatever the user's own SSH setup
    (keys, agent, ssh config Host aliases) already provides; this repo
    stores no credentials."""
    host: str
    user: Optional[str] = None
    port: int = 22
    identity_file: Optional[str] = None
    python: str = "python"
    remote_workdir: str = "/tmp/pytcad-remote"


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@runtime_checkable
class Transport(Protocol):
    def push(self, local_path: str, remote_path: str, host: RemoteHost) -> None: ...

    def run(self, argv: Sequence[str], host: RemoteHost,
            timeout: Optional[float] = None) -> CommandResult: ...

    def pull(self, remote_path: str, local_path: str, host: RemoteHost) -> None: ...


def _target(host: RemoteHost) -> str:
    return f"{host.user}@{host.host}" if host.user else host.host


class SSHTransport:
    """Real transport: shells out to the system `ssh`/`scp`.
    `BatchMode=yes` makes a missing/unusable credential fail fast
    (as a job error) instead of hanging on an interactive password
    prompt -- there is no such prompt available to a batch job."""

    def _ssh_prefix(self, host: RemoteHost) -> List[str]:
        argv = ["ssh", "-p", str(host.port),
                "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        if host.identity_file:
            argv += ["-i", host.identity_file]
        return argv

    def _scp_prefix(self, host: RemoteHost) -> List[str]:
        argv = ["scp", "-P", str(host.port),
                "-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]
        if host.identity_file:
            argv += ["-i", host.identity_file]
        return argv

    def push(self, local_path, remote_path, host):
        subprocess.run(self._scp_prefix(host) +
                       [local_path, f"{_target(host)}:{remote_path}"],
                       check=True, capture_output=True, text=True, timeout=60)

    def run(self, argv, host, timeout=None):
        proc = subprocess.run(
            self._ssh_prefix(host) + [_target(host), " ".join(argv)],
            capture_output=True, text=True, timeout=timeout)
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)

    def pull(self, remote_path, local_path, host):
        subprocess.run(self._scp_prefix(host) +
                       [f"{_target(host)}:{remote_path}", local_path],
                       check=True, capture_output=True, text=True, timeout=60)


class RemoteExecutor:
    """Executor backend: dispatches jobs round-robin across `hosts`
    over `transport`. Same `[(job_json_path, out_npz_path), ...]` in,
    `list[BatchOutcome]` out contract as
    `workbench.batch.run_jobs_parallel` (G-PROTOCOL-PARITY).

    Dispatch is I/O-bound (ssh/scp subprocesses waiting on the
    network), not CPU-bound, so a `ThreadPoolExecutor` is the right
    concurrency primitive here -- unlike Phase 4's local
    `ProcessPoolExecutor`, which exists specifically to get real
    parallel CPU work past the GIL."""

    id = "remote-ssh"

    def __init__(self, hosts: Sequence[RemoteHost],
                 transport: Optional[Transport] = None,
                 job_timeout: Optional[float] = DEFAULT_JOB_TIMEOUT):
        hosts = list(hosts)
        if not hosts:
            raise ValueError("RemoteExecutor needs at least one RemoteHost")
        self.hosts = hosts
        self.transport = transport or SSHTransport()
        self.job_timeout = job_timeout

    def _dispatch_one(self, job_json_path: str, out_npz_path: str,
                       host: RemoteHost) -> BatchOutcome:
        run_id = uuid.uuid4().hex[:12]
        remote_job = f"{host.remote_workdir}/job-{run_id}.json"
        remote_out = f"{host.remote_workdir}/result-{run_id}.npz"
        try:
            self.transport.run(["mkdir", "-p", host.remote_workdir], host,
                               timeout=self.job_timeout)
            self.transport.push(job_json_path, remote_job, host)
            result = self.transport.run(
                [host.python, "-m", "gui.services.solver_runner",
                 remote_job, remote_out], host, timeout=self.job_timeout)
            if result.returncode != 0:
                # A remote worker that dropped mid-job, crashed, or
                # simply never had the job -- always surfaced as THIS
                # row's failure, never a hang and never lost silently
                # (G-PARTIAL-FAILURE).
                detail = (result.stderr or result.stdout or "").strip()
                return BatchOutcome(
                    out_path=None,
                    error=f"remote solve failed on {host.host} "
                          f"(exit {result.returncode}): {detail}")
            self.transport.pull(remote_out, out_npz_path, host)
            return BatchOutcome(out_path=out_npz_path, error=None)
        except Exception as exc:
            return BatchOutcome(
                out_path=None,
                error=f"{type(exc).__name__} dispatching to "
                      f"{host.host}: {exc}")

    def run_jobs(self, jobs: Sequence[Tuple[str, str]],
                 max_workers: Optional[int] = None) -> List[BatchOutcome]:
        jobs = list(jobs)
        if not jobs:
            return []
        max_workers = max_workers or min(len(jobs), max(1, len(self.hosts)) * 4)
        outcomes: List[Optional[BatchOutcome]] = [None] * len(jobs)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(self._dispatch_one, job_path, out_path,
                           self.hosts[i % len(self.hosts)]): i
                for i, (job_path, out_path) in enumerate(jobs)
            }
            for fut in as_completed(futures):
                outcomes[futures[fut]] = fut.result()
        return outcomes
