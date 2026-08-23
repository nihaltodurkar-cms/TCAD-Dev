"""JobRunner owns the QProcess lifecycle.  These tests drive a real Qt
event loop headlessly -- no GUI is shown, but the async behavior is the
whole point, so it must be exercised for real rather than mocked."""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from gui.services.device_spec import MeshSpec, DopingSpec, ContactSpec, DeviceSpec
from gui.services.job_runner import JobRunner
from gui.services.result_store import NpzResultStore
from gui.services import examples


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def _tiny_1d_spec():
    x = np.linspace(0.0, 2e-4, 30)
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array",
                          values=np.where(x < 1e-4, -1e17, 1e17).tolist()),
        contacts=[ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}),
                  ContactSpec(name="right", kind="ohmic", nodes={"i": [29]})],
        bias={"left": 0.3, "right": 0.0},
    )


def _run_to_completion(runner, spec, timeout_ms=120000):
    """Start the job and spin a real event loop until it settles."""
    loop = QEventLoop()
    outcome = {}
    runner.finished.connect(lambda p: (outcome.update(kind="finished", path=p), loop.quit()))
    runner.failed.connect(lambda s, d: (outcome.update(kind="failed", summary=s, details=d), loop.quit()))
    runner.canceled.connect(lambda: (outcome.update(kind="canceled"), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    runner.start(spec)
    loop.exec()
    return outcome


def test_successful_run_emits_finished_with_loadable_result(qapp, tmp_path):
    runner = JobRunner(work_dir=str(tmp_path))
    lines = []
    runner.progressLine.connect(lines.append)

    outcome = _run_to_completion(runner, _tiny_1d_spec())

    assert outcome.get("kind") == "finished", outcome
    store = NpzResultStore(outcome["path"])
    assert store.scalar_field("potential").values.shape == (30,)
    assert lines, "no progress lines were streamed from the subprocess"
    assert not runner.running


def test_failure_is_reported_not_crashed(qapp, tmp_path):
    spec = _tiny_1d_spec()
    spec.doping.values = "not an array"        # provokes a backend exception
    runner = JobRunner(work_dir=str(tmp_path))

    outcome = _run_to_completion(runner, spec)

    assert outcome.get("kind") == "failed", outcome
    assert outcome["summary"]                   # concise line for the user
    assert "Traceback" in outcome["details"]    # expandable technical detail
    assert not runner.running


def test_cancel_emits_canceled_and_yields_no_result(qapp, tmp_path):
    """A canceled run must never surface a result path, and must leave no
    file at the canonical output path."""
    spec = examples.mosfet_example_spec()       # big enough to still be running
    runner = JobRunner(work_dir=str(tmp_path))

    loop = QEventLoop()
    outcome = {}
    runner.finished.connect(lambda p: (outcome.update(kind="finished", path=p), loop.quit()))
    runner.failed.connect(lambda s, d: (outcome.update(kind="failed"), loop.quit()))
    runner.canceled.connect(lambda: (outcome.update(kind="canceled"), loop.quit()))
    runner.start(spec)
    QTimer.singleShot(400, runner.cancel)       # cancel while it is solving
    QTimer.singleShot(60000, loop.quit)
    loop.exec()

    assert outcome.get("kind") == "canceled", outcome
    assert not runner.running
    assert not os.path.exists(runner.result_path), \
        "cancellation must not leave a result at the canonical path"


def test_example_spec_is_a_valid_2d_mosfet():
    spec = examples.mosfet_example_spec()
    assert spec.mesh.dimensionality == 2
    Ny, Nx = spec.mesh.shape()
    assert np.asarray(spec.doping.values).shape == (Ny, Nx)
    names = {c.name for c in spec.contacts}
    assert {"source", "drain", "body", "gate"} <= names
    gate = [c for c in spec.contacts if c.kind == "gate"][0]
    assert gate.tox_cm is not None and gate.Vfb is not None
    assert "mosfet_2d" in examples.EXAMPLES
