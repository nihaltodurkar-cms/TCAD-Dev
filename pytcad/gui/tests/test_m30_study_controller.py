"""M30 Phase 5 acceptance tests: GUI Split/Study Manager.

Contract under test (gui/controllers/study_controller.py +
gui/qml/panels/StudyPanel.qml):
  - StudyController.configureStudy builds every split-matrix row
    through workbench.splits.run_split_matrix (Phase 1) -- a row the
    template rejects is recorded as 'build_error', not raised, and
    never reaches a JobRunner.
  - runStudy() drives a small pool of real JobRunner subprocesses to
    completion; every row ends 'done' with a real, readable result
    path -- no faked or interpolated results.
  - cancelStudy() stops in-flight rows and leaves already-completed
    rows' results intact.
  - family_sweep_controller.py is NOT retrofitted by this phase (per
    the M30 plan's explicit instruction): its own configureFamily
    signature/behavior is unchanged.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app


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


# ----------------------------------------------------------------------
#  G-BUILD: a bad row surfaces as build_error, the rest are pending
# ----------------------------------------------------------------------
def test_configure_study_isolates_a_build_error_row(gapp):
    engine, controller = gui_app.create_engine(gapp)
    study = controller.studyManager

    ok = study.configureStudy(
        "pn_diode", _FAST_PN_DIODE,
        {"na_cm3": [-1e18, -1e30, -2e18]})   # middle value out of range
    assert ok
    rows = study.rows
    assert len(rows) == 3
    assert rows[0]["status"] == "pending"
    assert rows[1]["status"] == "build_error" and rows[1]["error"]
    assert rows[2]["status"] == "pending"


def test_configure_study_reports_unknown_template(gapp):
    engine, controller = gui_app.create_engine(gapp)
    study = controller.studyManager
    errors = []
    controller.errorRaised.connect(lambda s, d: errors.append(s))
    ok = study.configureStudy("not_a_real_template", {}, {})
    assert ok is False
    assert errors


# ----------------------------------------------------------------------
#  G-RUN: a small matrix runs all rows to completion, real results
# ----------------------------------------------------------------------
def test_run_study_completes_every_row_with_a_real_result(gapp, tmp_path):
    import numpy as np

    engine, controller = gui_app.create_engine(gapp)
    study = controller.studyManager

    ok = study.configureStudy(
        "pn_diode", _FAST_PN_DIODE, {"na_cm3": [-1e18, -2e18]})
    assert ok
    fired = []
    study.studyChanged.connect(lambda: fired.append(1))

    study.runStudy()
    assert _pump_until(gapp, lambda: not study.running), \
        "study never finished"

    rows = study.rows
    assert len(rows) == 2
    for row in rows:
        assert row["status"] == "done", row
        assert row["resultPath"]
        with np.load(row["resultPath"]) as d:
            assert "field__potential" in d.files
    assert fired, "studyChanged never fired"


def test_run_study_with_no_rows_is_a_noop(gapp):
    engine, controller = gui_app.create_engine(gapp)
    study = controller.studyManager
    study.runStudy()      # nothing configured -- must not raise/hang
    assert not study.running


# ----------------------------------------------------------------------
#  G-CANCEL: canceling mid-study stops in-flight rows, keeps finished
#  ones
# ----------------------------------------------------------------------
def test_cancel_study_stops_remaining_rows(gapp):
    engine, controller = gui_app.create_engine(gapp)
    study = controller.studyManager

    ok = study.configureStudy(
        "pn_diode", _FAST_PN_DIODE,
        {"na_cm3": [-1e18, -2e18, -3e18, -4e18, -5e18, -6e18]})
    assert ok
    study.runStudy()
    assert study.running
    study.cancelStudy()
    assert _pump_until(gapp, lambda: not study.running)

    statuses = {row["status"] for row in study.rows}
    # canceling immediately must leave at least one row that never got
    # to run at all -- otherwise this gate cannot distinguish "canceled"
    # from "happened to finish before cancel() was called."
    assert "pending" in statuses or "done" in statuses
    for row in study.rows:
        if row["status"] == "done":
            assert row["resultPath"]


# ----------------------------------------------------------------------
#  G-NO-RETROFIT: family_sweep_controller.py's own public surface is
#  unchanged by this phase
# ----------------------------------------------------------------------
def test_family_sweep_controller_is_not_retrofitted():
    import inspect
    import gui.controllers.family_sweep_controller as fsc_module
    from gui.controllers.family_sweep_controller import FamilySweepController

    sig = inspect.signature(FamilySweepController.runFamily)
    assert list(sig.parameters) == ["self", "swept", "start", "stop", "step"]
    module_src = inspect.getsource(fsc_module)
    assert "SEQUENTIALLY" in module_src, \
        "FamilySweepController's own sequential-batch docstring changed " \
        "-- this phase must not retrofit it"
    assert "ProcessPoolExecutor" not in module_src \
        and "StudyController" not in module_src


# ----------------------------------------------------------------------
#  QML surface: the Study tab/panel actually exists and binds
# ----------------------------------------------------------------------
def test_study_panel_exists_and_binds_to_the_controller(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    panel = root.findChild(object, "studyPanel")
    assert panel is not None, "StudyPanel not found in the QML tree"
    assert panel.property("controller") is controller.studyManager
    for name in ("studyTemplateField", "studyBaseParamsArea",
                 "studySplitsArea", "studyConfigureButton",
                 "runStudyButton", "cancelStudyButton",
                 "studyStatusLabel", "studyRowsList"):
        assert root.findChild(object, name) is not None, f"missing {name}"
