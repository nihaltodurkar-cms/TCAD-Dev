"""JobRunner owns the QProcess lifecycle.  These tests drive a real Qt
event loop headlessly -- no GUI is shown, but the async behavior is the
whole point, so it must be exercised for real rather than mocked."""
import json
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


def test_job_runner_accepts_a_custom_module(qapp, tmp_path):
    runner = JobRunner(work_dir=str(tmp_path), module="gui.services.process_runner")
    assert runner._module == "gui.services.process_runner"


def test_job_runner_default_module_is_unchanged(qapp, tmp_path):
    runner = JobRunner(work_dir=str(tmp_path))
    assert runner._module == "gui.services.solver_runner"


class _ProcessFlowJson:
    """Minimal to_json(path) adapter, mirroring app_controller.py's own
    _ProcessFlowJob -- JobRunner.start() just needs `spec.to_json(path)`
    to write the flow.json a process run reads."""
    def __init__(self, flow):
        self._flow = flow

    def to_json(self, path):
        with open(path, "w") as fh:
            json.dump(self._flow.to_dict(), fh)


def _small_process_flow():
    from gui.services.process_model import ProcessFlow, ProcessStep
    return ProcessFlow(steps=[
        ProcessStep(id="sub", name="Substrate", operation="substrate",
                   parameters={"length_cm": 2e-4, "background_doping_cm3": -1e16,
                               "mesh": {"h_min_cm": 2e-8, "h_max_cm": 2e-6, "ratio": 1.15}}),
        ProcessStep(id="i1", name="Implant", operation="implant",
                   parameters={"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14}),
    ])


def test_process_run_success_keeps_its_state_dir(qapp, tmp_path):
    """Final-review finding: a canceled/failed process run must not leave
    a stale per-run checkpoint directory or partial .tmp files behind
    (JobRunner._cleanup_stale_state_dir/_cleanup_tmp), but a SUCCESSFUL
    run's own state_dir is the ProcessResultStore's actual backing data
    and must survive -- confirm the happy path is unaffected."""
    runner = JobRunner(work_dir=str(tmp_path), module="gui.services.process_runner")
    outcome = _run_to_completion(runner, _ProcessFlowJson(_small_process_flow()))
    assert outcome.get("kind") == "finished", outcome

    manifest_path = outcome["path"]
    with open(manifest_path) as fh:
        manifest = json.load(fh)
    state_dir = os.path.dirname(next(iter(manifest["state_paths"].values())))
    assert os.path.isdir(state_dir), "a successful run's state_dir must survive"
    assert not os.path.exists(manifest_path + ".tmp.json"), (
        "the manifest's own .tmp.json must be renamed away on success")


def test_process_run_cancel_removes_the_state_dir_and_tmp_files(qapp, tmp_path):
    """The actual regression: canceling a process run used to leave its
    per-step .tmp.npz files (inside the old shared checkpoint directory)
    and the manifest's own .tmp.json behind forever -- and, worse, left
    the OLD ProcessResultStore from any previous successful run pointing
    at a directory a later run could still write into. Isolating each
    run into its own "<result-stem>-state/" directory (process_runner.py)
    means a cancel now has a single directory it can safely delete
    outright."""
    from gui.services.process_model import ProcessFlow, ProcessStep
    # The flow must still be RUNNING when the cancel timer fires at
    # 500 ms, or there is nothing to cancel and the runner reports
    # "finished".  Four anneal steps used to take ~15 s, which was
    # ample; fixing mesh.graded_mesh's stub final cell (it was 2.5-5.5x
    # SMALLER than the requested h_min, and an explicit diffusion step
    # is limited by h^2) made process runs ~78x faster, so four steps
    # now complete in ~0.2 s.  120 steps take ~4.9 s -- a ~10x margin
    # over the timer.
    steps = _small_process_flow().steps + [
        ProcessStep(id=f"a{k}", name="Anneal", operation="anneal",
                   parameters={"temperature_C": 950.0, "time_s": 600.0})
        for k in range(120)
    ]
    flow = ProcessFlow(steps=steps)
    runner = JobRunner(work_dir=str(tmp_path), module="gui.services.process_runner")

    loop = QEventLoop()
    outcome = {}
    runner.finished.connect(lambda p: (outcome.update(kind="finished", path=p), loop.quit()))
    runner.failed.connect(lambda s, d: (outcome.update(kind="failed"), loop.quit()))
    runner.canceled.connect(lambda: (outcome.update(kind="canceled"), loop.quit()))
    runner.start(_ProcessFlowJson(flow))
    result_path = runner.result_path
    QTimer.singleShot(500, runner.cancel)
    QTimer.singleShot(60000, loop.quit)
    loop.exec()

    assert outcome.get("kind") == "canceled", outcome
    state_dir = os.path.splitext(result_path)[0] + "-state"
    assert not os.path.isdir(state_dir), "canceled run left a stale state_dir behind"
    assert not os.path.exists(result_path + ".tmp.json"), (
        "canceled run left the manifest's .tmp.json behind")
