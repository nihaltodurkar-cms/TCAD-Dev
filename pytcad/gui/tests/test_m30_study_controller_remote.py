"""M30 Phase 12 acceptance tests: GUI wiring for remote execution.

Contract under test (gui/controllers/study_controller.py's
setRemoteHosts/remoteHosts + gui/services/remote_job_runner.py +
gui/qml/panels/StudyPanel.qml's remote-hosts field):
  - StudyController.setRemoteHosts([...]) switches runStudy() from its
    local JobRunner pool to a RemoteJobRunner pool, round-robin over
    the configured hosts; empty/unset stays local-only (unchanged
    behavior from Phase 5).
  - A remote row runs to a real, readable result -- same "no faked or
    interpolated results" rule Phase 5's own G-RUN gate holds to.
  - A bad remote host's row is reported failed (never a hang), and
    does not lose a good host's rows (G-PARTIAL-FAILURE, restated at
    the GUI layer).
  - The QML panel actually exposes the remote-hosts field.

No real SSH/network: `RemoteJobRunner` is constructed (via a
monkeypatched factory at the exact seam StudyController.runStudy()
uses) with its `ssh_cmd`/`scp_cmd` pointed at the local
gui/tests/fixtures/fake_ssh*.py stand-ins instead of the real `ssh`/
`scp` binaries -- same "a second local process pretending to be
remote" strategy the library-level Phase 12 gates
(tests/test_m30_remote_executor.py) already use, just injected at the
GUI's own construction seam instead of workbench.remote_executor's
Transport protocol.
"""
import dataclasses
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app
from gui.services.remote_job_runner import RemoteJobRunner

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
_FAKE_SSH = (sys.executable, os.path.join(FIXTURES_DIR, "fake_ssh.py"))
_FAKE_SSH_ALWAYS_FAIL = (sys.executable, os.path.join(FIXTURES_DIR, "fake_ssh_always_fail.py"))
_FAKE_SCP = (sys.executable, os.path.join(FIXTURES_DIR, "fake_scp.py"))


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def _pump_until(gapp, condition, timeout_s=60):
    for _ in range(timeout_s * 10):
        gapp.processEvents()
        gapp.thread().msleep(100)
        if condition():
            return True
    return False


_FAST_PN_DIODE = dict(length_cm=1e-4, height_cm=2e-5, nx=16, ny=6,
                      nd_cm3=1e18)


def _install_fake_remote_runner(monkeypatch, tmp_path, bad_hosts=()):
    """Monkeypatch the exact name study_controller.py imports
    (`RemoteJobRunner`) with a factory that builds a real
    RemoteJobRunner, just pointed at a local scratch `remote_workdir`
    and the fake ssh/scp stand-ins -- `bad_hosts` names get the
    always-fails ssh stand-in, simulating a dropped worker."""
    remote_wd = str(tmp_path / "remote-wd")

    def factory(host, parent=None, work_dir=None):
        fake_host = dataclasses.replace(host, remote_workdir=remote_wd)
        ssh_cmd = _FAKE_SSH_ALWAYS_FAIL if host.host in bad_hosts else _FAKE_SSH
        return RemoteJobRunner(fake_host, parent=parent, work_dir=work_dir,
                               ssh_cmd=ssh_cmd, scp_cmd=_FAKE_SCP)

    monkeypatch.setattr("gui.controllers.study_controller.RemoteJobRunner", factory)


# ----------------------------------------------------------------------
#  setRemoteHosts/remoteHosts round trip
# ----------------------------------------------------------------------
def test_set_remote_hosts_updates_property(gapp):
    engine, controller = gui_app.create_engine(gapp)
    study = controller.studyManager

    assert study.remoteHosts == []
    study.setRemoteHosts(["lab-1", " lab-2 ", "", "  "])
    assert study.remoteHosts == ["lab-1", "lab-2"]
    study.setRemoteHosts([])
    assert study.remoteHosts == []
    study.setRemoteHosts(None)
    assert study.remoteHosts == []


# ----------------------------------------------------------------------
#  G-REMOTE-RUN: a remote-configured study runs every row to a real
#  result, through a real (local stand-in) ssh/scp dispatch
# ----------------------------------------------------------------------
def test_run_study_remote_completes_every_row_with_a_real_result(
        gapp, tmp_path, monkeypatch):
    import numpy as np

    _install_fake_remote_runner(monkeypatch, tmp_path)

    engine, controller = gui_app.create_engine(gapp)
    study = controller.studyManager
    study.setRemoteHosts(["loopback-worker"])

    ok = study.configureStudy(
        "pn_diode", _FAST_PN_DIODE, {"na_cm3": [-1e18, -2e18]})
    assert ok

    study.runStudy()
    assert _pump_until(gapp, lambda: not study.running), \
        "remote study never finished"

    rows = study.rows
    assert len(rows) == 2
    for row in rows:
        assert row["status"] == "done", row
        assert row["resultPath"]
        with np.load(row["resultPath"]) as d:
            assert "field__potential" in d.files


# ----------------------------------------------------------------------
#  G-PARTIAL-FAILURE (GUI): one bad host's rows fail without hanging or
#  losing a good host's rows
# ----------------------------------------------------------------------
def test_bad_remote_host_fails_its_rows_without_losing_the_good_host(
        gapp, tmp_path, monkeypatch):
    _install_fake_remote_runner(monkeypatch, tmp_path, bad_hosts={"bad-worker"})

    engine, controller = gui_app.create_engine(gapp)
    study = controller.studyManager
    study.setRemoteHosts(["good-worker", "bad-worker"])

    ok = study.configureStudy(
        "pn_diode", _FAST_PN_DIODE,
        {"na_cm3": [-1e18, -2e18, -3e18, -4e18]})
    assert ok

    study.runStudy()
    assert _pump_until(gapp, lambda: not study.running), \
        "study with a bad remote host hung instead of finishing"

    statuses = [row["status"] for row in study.rows]
    assert "done" in statuses, "the good host's rows must still complete"
    assert "failed" in statuses, "the bad host's rows must be reported failed"
    for row in study.rows:
        if row["status"] == "failed":
            assert row["error"]


# ----------------------------------------------------------------------
#  QML surface: the remote-hosts field actually exists and binds
# ----------------------------------------------------------------------
def test_study_panel_exposes_remote_hosts_field(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    panel = root.findChild(object, "studyPanel")
    assert panel is not None
    for name in ("studyRemoteHostsArea", "studyRemoteHostsStatusLabel"):
        assert root.findChild(object, name) is not None, f"missing {name}"
