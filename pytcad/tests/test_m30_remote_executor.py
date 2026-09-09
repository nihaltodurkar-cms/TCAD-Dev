"""M30 Phase 12 acceptance tests: remote execution.

Contract under test (workbench/remote_executor.py,
workbench/executor.py):
  - G-PROTOCOL-PARITY: `RemoteExecutor` and `LocalExecutor` implement
    the identical `Executor` protocol -- `workbench.batch.
    solve_split_matrix` works unmodified against either, producing
    bit-identical solver results.
  - G-PARTIAL-FAILURE: a remote worker that fails mid-job is reported
    as that job's own BatchOutcome.error, never a hang and never a
    lost/silently-dropped row.
  - G-NO-TRANSPORT-IN-DEVICESPEC: the job JSON a remote host receives
    is byte-identical to the one written locally -- no
    transport-specific field is added.

No real SSH/network is used: `_LoopbackTransport` below is the plan
doc's own suggested stand-in ("a second local process pretending to be
remote"; a real remote worker fleet is outside this repo's test
environment) -- it runs the SAME
`python -m gui.services.solver_runner <job> <out>` subprocess entry
point a real remote worker would run, just against a local scratch
directory instead of over ssh, so dispatch/concurrency/BatchOutcome
plumbing is exercised for real rather than mocked out.
"""
import os
import shutil
import subprocess
import sys

PYTCAD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PYTCAD_ROOT)

import numpy as np
import pytest

from workbench.batch import solve_split_matrix
from workbench.executor import LocalExecutor
from workbench.remote_executor import CommandResult, RemoteExecutor, RemoteHost
from workbench.workflow import run_deck_full

_MOS_DECK = """
go
template mos_capacitor
na_cm3 = -1e16
nx = 20
ny = 8
split tox_cm = 7e-7, 8e-7, 9e-7
end
"""


class _LoopbackTransport:
    """Stand-in for a real Transport: 'remote' paths are just another
    local directory, and `run` shells out to the real solver_runner
    subprocess against that directory -- a genuine subprocess dispatch,
    not a mock."""

    def __init__(self, root):
        self.root = root
        self.pushed_bytes = {}   # remote_path -> bytes actually written

    def _local(self, remote_path, host):
        rel = remote_path[len(host.remote_workdir):].lstrip("/")
        p = os.path.join(self.root, host.host, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p

    def push(self, local_path, remote_path, host):
        dest = self._local(remote_path, host)
        shutil.copy(local_path, dest)
        with open(dest, "rb") as f:
            self.pushed_bytes[remote_path] = f.read()

    def run(self, argv, host, timeout=None):
        if argv[:2] == ["mkdir", "-p"]:
            return CommandResult(0, "", "")
        remote_job, remote_out = argv[-2], argv[-1]
        job_local = self._local(remote_job, host)
        out_local = self._local(remote_out, host)
        proc = subprocess.run(
            [sys.executable, "-m", "gui.services.solver_runner",
             job_local, out_local],
            cwd=PYTCAD_ROOT, capture_output=True, text=True, timeout=timeout)
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)

    def pull(self, remote_path, local_path, host):
        shutil.copy(self._local(remote_path, host), local_path)


class _AlwaysFailsTransport(_LoopbackTransport):
    """A host whose remote solve always fails -- simulates a worker
    that drops mid-job, per G-PARTIAL-FAILURE."""

    def run(self, argv, host, timeout=None):
        if argv[:2] == ["mkdir", "-p"]:
            return CommandResult(0, "", "")
        return CommandResult(1, "", "simulated remote worker crash")


class _PerHostTransport:
    """Routes to a good or bad transport depending on which host a
    call targets, so a multi-host study can isolate one bad host from
    a good one."""

    def __init__(self, good, bad, bad_host_name):
        self.good, self.bad, self.bad_host_name = good, bad, bad_host_name

    def _pick(self, host):
        return self.bad if host.host == self.bad_host_name else self.good

    def push(self, local_path, remote_path, host):
        return self._pick(host).push(local_path, remote_path, host)

    def run(self, argv, host, timeout=None):
        return self._pick(host).run(argv, host, timeout=timeout)

    def pull(self, remote_path, local_path, host):
        return self._pick(host).pull(remote_path, local_path, host)


# ----------------------------------------------------------------------
#  G-PROTOCOL-PARITY
# ----------------------------------------------------------------------
def test_remote_executor_matches_local_results(tmp_path):
    run = run_deck_full(_MOS_DECK)

    local_dir = tmp_path / "local"; local_dir.mkdir()
    local_paired = solve_split_matrix(
        run, work_dir=str(local_dir), executor=LocalExecutor())

    host = RemoteHost(host="loopback-worker", python=sys.executable,
                      remote_workdir=str(tmp_path / "fake-remote-wd"))
    transport = _LoopbackTransport(str(tmp_path / "fake-remote-fs"))
    remote = RemoteExecutor([host], transport=transport)
    remote_dir = tmp_path / "remote"; remote_dir.mkdir()
    remote_paired = solve_split_matrix(
        run, work_dir=str(remote_dir), executor=remote)

    assert len(local_paired) == len(remote_paired) == 3
    for (lrow, lout), (rrow, rout) in zip(local_paired, remote_paired):
        assert lrow.params == rrow.params
        assert lout.error is None and rout.error is None
        with np.load(lout.out_path) as lp, np.load(rout.out_path) as rp:
            assert np.array_equal(lp["field__potential"],
                                  rp["field__potential"]), \
                "remote executor result differs from local -- must not " \
                "change answers"


def test_remote_executor_satisfies_executor_protocol():
    from workbench.executor import Executor
    host = RemoteHost(host="h")
    assert isinstance(RemoteExecutor([host], transport=_LoopbackTransport("/tmp")),
                      Executor)
    assert isinstance(LocalExecutor(), Executor)


# ----------------------------------------------------------------------
#  G-PARTIAL-FAILURE
# ----------------------------------------------------------------------
def test_bad_remote_host_reports_row_failure_not_hang(tmp_path):
    host = RemoteHost(host="dead-worker",
                      remote_workdir=str(tmp_path / "fake-remote-wd"))
    transport = _AlwaysFailsTransport(str(tmp_path / "fake-remote-fs"))
    remote = RemoteExecutor([host], transport=transport, job_timeout=30)

    run = run_deck_full(_MOS_DECK)
    work_dir = tmp_path / "work"; work_dir.mkdir()
    paired = solve_split_matrix(run, work_dir=str(work_dir),
                               executor=remote)

    assert len(paired) == 3
    for row, outcome in paired:
        assert row.error is None and row.device is not None  # built fine
        assert outcome.out_path is None
        assert "dead-worker" in outcome.error
        assert "simulated remote worker crash" in outcome.error


def test_one_bad_host_does_not_lose_a_good_hosts_results(tmp_path):
    good_host = RemoteHost(host="good-worker",
                           remote_workdir=str(tmp_path / "good-wd"))
    bad_host = RemoteHost(host="bad-worker",
                          remote_workdir=str(tmp_path / "bad-wd"))
    good_t = _LoopbackTransport(str(tmp_path / "good-fs"))
    bad_t = _AlwaysFailsTransport(str(tmp_path / "bad-fs"))
    transport = _PerHostTransport(good_t, bad_t, bad_host_name="bad-worker")

    remote = RemoteExecutor([good_host, bad_host], transport=transport)
    run = run_deck_full(_MOS_DECK)
    work_dir = tmp_path / "work"; work_dir.mkdir()
    paired = solve_split_matrix(run, work_dir=str(work_dir),
                               executor=remote)

    outcomes = [o for _, o in paired]
    # round-robin over 2 hosts across 3 rows -> good, bad, good
    assert outcomes[0].error is None and outcomes[0].out_path is not None
    assert outcomes[1].error is not None and outcomes[1].out_path is None
    assert outcomes[2].error is None and outcomes[2].out_path is not None


# ----------------------------------------------------------------------
#  G-NO-TRANSPORT-IN-DEVICESPEC
# ----------------------------------------------------------------------
def test_pushed_job_json_is_byte_identical_to_local(tmp_path):
    from workbench.adapters.spec import spec_from_domain
    from workbench.core.templates import get_template

    device = get_template("pn_diode").build(
        {"length_cm": 1e-4, "height_cm": 2e-5, "nx": 20, "ny": 6,
         "na_cm3": -1e18, "nd_cm3": 1e18})
    spec = spec_from_domain(device)
    spec.bias = None
    spec.sweep = None
    job_path = str(tmp_path / "job.json")
    out_path = str(tmp_path / "out.npz")
    spec.to_json(job_path)
    with open(job_path, "rb") as f:
        original_bytes = f.read()

    host = RemoteHost(host="loopback-worker", python=sys.executable,
                      remote_workdir=str(tmp_path / "fake-remote-wd"))
    transport = _LoopbackTransport(str(tmp_path / "fake-remote-fs"))
    remote = RemoteExecutor([host], transport=transport)

    outcomes = remote.run_jobs([(job_path, out_path)])
    assert outcomes[0].error is None

    pushed = next(iter(transport.pushed_bytes.values()))
    assert pushed == original_bytes, \
        "DeviceSpec JSON must be pushed byte-identical -- no " \
        "transport-specific field may be added to the job payload"


# ----------------------------------------------------------------------
#  misc
# ----------------------------------------------------------------------
def test_remote_executor_rejects_empty_hosts():
    with pytest.raises(ValueError):
        RemoteExecutor([])


def test_remote_executor_with_no_jobs_returns_empty():
    host = RemoteHost(host="h")
    remote = RemoteExecutor([host], transport=_LoopbackTransport("/tmp"))
    assert remote.run_jobs([]) == []
