"""M30 Phase 7 acceptance tests: Run Comparison.

Contract under test:
  - gui/services/provenance_diff.py's provenance_diff(records, labels)
    is a pure, Qt-free function: it flags every field that genuinely
    differs between RunRecords and marks identical fields as such.
  - StudyController.compareRows(indices, field_name, ...) reuses
    gui.services.result_store.extract_line_cut VERBATIM (no new
    extraction code) to build a per-row overlay curve, plus a
    provenance diff table from each row's own RunRecord.
  - A row that is out of range, not 'done', or whose field isn't 2D is
    reported in `skipped` with a reason rather than aborting the
    comparison or producing garbage for the other rows.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app
from gui.services.provenance_diff import provenance_diff
from gui.services.solver_backend import RunRecord


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


def _record(**overrides):
    base = dict(backend="pytcad", created_utc="2026-01-01T00:00:00",
               dimensionality=2, material="Silicon", T=300.0,
               models={"srh": True, "auger": False}, numerics={})
    base.update(overrides)
    return RunRecord(**base)


# ----------------------------------------------------------------------
#  G-PROVDIFF: every genuine difference is flagged; identical fields
#  are not
# ----------------------------------------------------------------------
def test_provenance_diff_flags_real_differences_only():
    a = _record()
    b = _record(T=350.0, models={"srh": True, "auger": True})
    rows = provenance_diff([a, b], labels=["A", "B"])

    by_field = {r["field"]: r for r in rows}
    assert by_field["T"]["differs"] is True
    assert by_field["T"]["values"] == [300.0, 350.0]
    assert by_field["models"]["differs"] is True
    assert by_field["backend"]["differs"] is False
    assert by_field["dimensionality"]["differs"] is False
    assert by_field["material"]["differs"] is False


def test_provenance_diff_identical_records_flags_nothing():
    a, b = _record(), _record()
    rows = provenance_diff([a, b])
    assert not any(r["differs"] for r in rows)


def test_provenance_diff_handles_a_missing_record():
    rows = provenance_diff([_record(), None])
    by_field = {r["field"]: r for r in rows}
    assert by_field["backend"]["differs"] is True
    assert by_field["backend"]["values"] == ["pytcad", None]


# ----------------------------------------------------------------------
#  G-OVERLAY: two runs of the same device at different split values
#  overlay correctly with correct per-curve labels
# ----------------------------------------------------------------------
_MOS = dict(length_cm=1e-4, height_cm=2e-5, nx=16, ny=8)


def test_compare_rows_overlay_has_correct_labels_and_real_data(gapp):
    engine, controller = gui_app.create_engine(gapp)
    study = controller.studyManager
    study.configureStudy("mos_capacitor", _MOS, {"na_cm3": [-1e16, -2e16]})
    study.runStudy()
    assert _pump_until(gapp, lambda: not study.running)

    result = study.compareRows([0, 1], "doping", "horizontal", 1e-5)
    assert not result["skipped"]
    assert len(result["curves"]) == 2
    assert result["curves"][0]["label"] != result["curves"][1]["label"]
    for curve in result["curves"]:
        assert len(curve["x"]) == len(curve["y"]) > 0

    prov_by_field = {r["field"]: r for r in result["provenance"]}
    assert prov_by_field["dimensionality"]["differs"] is False
    assert all(v == 2 for v in prov_by_field["dimensionality"]["values"])


def test_compare_rows_skips_a_non_done_index_with_a_reason(gapp):
    engine, controller = gui_app.create_engine(gapp)
    study = controller.studyManager
    study.configureStudy("mos_capacitor", _MOS, {"na_cm3": [-1e16]})
    # deliberately do not run -- row 0 is 'pending'
    result = study.compareRows([0, 99], "doping", "horizontal", 1e-5)
    assert result["curves"] == []
    reasons = {s["index"]: s["reason"] for s in result["skipped"]}
    assert 0 in reasons and 99 in reasons


# ----------------------------------------------------------------------
#  G-MISMATCHED-DIM: comparing a 1D and a 2D result fails clearly for
#  that row, without corrupting the rest of the comparison
# ----------------------------------------------------------------------
def test_compare_rows_reports_dimension_mismatch_not_garbage(gapp, tmp_path):
    import numpy as np

    from gui.services.device_spec import ContactSpec, DeviceSpec, DopingSpec, MeshSpec
    from gui.services.solver_runner import run_job

    engine, controller = gui_app.create_engine(gapp)
    study = controller.studyManager
    study.configureStudy("mos_capacitor", _MOS, {"na_cm3": [-1e16]})
    study.runStudy()
    assert _pump_until(gapp, lambda: not study.running)

    # Inject a real, independently-solved 1D result as a second "row"
    # -- exercising extract_line_cut's own dimensionality guard, not a
    # fabricated failure.
    x = np.linspace(0.0, 2e-4, 30)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    spec_1d = DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
                  ContactSpec(name="right", kind="ohmic",
                              nodes={"i": [x.size - 1]}, V=0.0)],
        bias=None)
    job_path, out_path = str(tmp_path / "job1d.json"), str(tmp_path / "r1d.npz")
    spec_1d.to_json(job_path)
    run_job(job_path, out_path)
    study._rows.append({"params": {"na_cm3": -3e16}, "status": "done",
                        "resultPath": out_path, "error": "", "_device": None})

    result = study.compareRows([0, 1], "doping", "horizontal", 1e-5)
    assert len(result["curves"]) == 1          # only the real 2D row
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["index"] == 1
    assert "2D" in result["skipped"][0]["reason"] or \
        "dimensionality" in result["skipped"][0]["reason"]


# ----------------------------------------------------------------------
#  QML surface: the comparison controls actually exist and bind
# ----------------------------------------------------------------------
def test_comparison_controls_exist_in_the_study_panel(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    for name in ("compareIndicesField", "compareRunButton",
                 "compareSkippedLabel", "comparisonCurvesList",
                 "provenanceDiffList"):
        assert root.findChild(object, name) is not None, f"missing {name}"
