"""Phase 3b: per-stage continuation record view.

Verifies that LabController.continuationData() returns the correct
stage history from RunRecord.continuation_records, and that the
Physics Lab panel renders it.
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtGui import QGuiApplication
from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def test_continuation_data_from_record(gapp):
    """LabController.continuationData() returns stage history from RunRecord."""
    from gui.controllers.app_controller import AppController
    from gui.services.solver_backend import RunRecord
    from gui.services.result_store import NpzResultStore
    import tempfile
    import json
    import numpy as np

    # Create a minimal result file with continuation_records
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test.npz")
        meta = {
            "backend": "pytcad",
            "created_utc": "2026-01-01T00:00:00Z",
            "dimensionality": 1,
            "material": "Si",
            "T": 300.0,
            "models": {},
            "numerics": {},
            "schema_version": 2,
        }
        records = [
            {"index": 0, "parameter": 0.0, "nodes": 40, "accepted": True},
            {"index": 1, "parameter": 0.3, "nodes": 40, "accepted": True},
            {"index": 2, "parameter": 0.6, "nodes": "", "accepted": False},
        ]
        np.savez(path,
                 record__meta=np.array([json.dumps(meta)]),
                 continuation__records=np.array([json.dumps(records)]),
                 dimensionality=np.array(1),
                 axis_x=np.array([0.0, 1e-4, 2e-4]),
                 field__potential=np.array([0.0, 0.1, 0.2]),
                 unit__potential=np.array("V"),
                 solved_bias=np.array([0.0, 0.1, 0.2]),
                 result__schema=np.array(2))

        store = NpzResultStore(path)
        record = store.run_record()
        assert record is not None
        assert len(record.continuation_records) == 3

        # Verify LabController can read it
        ctl = AppController()
        ctl._store = store
        lab = ctl.lab
        data = lab.continuationData()
        assert len(data) == 3
        assert data[0]["index"] == 0
        assert data[0]["accepted"] is True
        assert data[2]["accepted"] is False


def test_continuation_data_empty_when_no_record(gapp):
    """When there's no run record, continuationData returns empty list."""
    from gui.controllers.app_controller import AppController
    ctl = AppController()
    ctl._store = None
    data = ctl.lab.continuationData()
    assert data == []


def test_continuation_data_from_a_real_sweep_run(gapp, tmp_path):
    """continuation__records must have a real producer, not just the
    hand-crafted-npz consumer test above: run an actual 1D diode sweep
    through solver_runner.run_job() and check the GUI table gets real
    per-point (voltage, converged) data out of it, matching the sweep
    series solver_runner already computes independently."""
    from gui.controllers.app_controller import AppController
    from gui.services.device_spec import (
        ContactSpec, DeviceSpec, DopingSpec, MeshSpec, SweepSpec,
    )
    from gui.services.result_store import NpzResultStore
    from gui.services.solver_runner import run_job
    import numpy as np

    x = np.linspace(0.0, 2e-4, 40)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
                  ContactSpec(name="right", kind="ohmic",
                              nodes={"i": [x.size - 1]}, V=0.0)],
        sweep=SweepSpec(contact="left", start=0.0, stop=0.2, step=0.1))
    job_path = str(tmp_path / "job.json")
    out_path = str(tmp_path / "out.npz")
    spec.to_json(job_path)
    run_job(job_path, out_path)

    store = NpzResultStore(out_path)
    sweep = store.sweep_result()
    ctl = AppController()
    ctl._store = store
    data = ctl.lab.continuationData()

    assert len(data) == sweep.n_points() > 0
    assert [row["index"] for row in data] == list(range(sweep.n_points()))
    assert np.allclose([row["parameter"] for row in data], sweep.voltages)
    assert [row["accepted"] for row in data] == list(map(bool, sweep.converged))
