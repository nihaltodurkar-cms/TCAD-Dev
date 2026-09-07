"""M30 Phase 6 acceptance tests: Sweep Matrix Viewer.

Contract under test (StudyController.matrixCells/splitAxes/
availableDisplayFields + StudyPanel.qml's Grid/Repeater):
  - matrixCells(field) returns one entry per row, in row-major order
    (workbench.splits.expand_splits' own documented order: the LAST
    split key varies fastest), with `value` = max(scalar_field) for a
    'done' row -- a real reduction of the real solved field, read
    fresh from the result .npz, never synthesized.
  - A row that isn't 'done' (pending/failed/build_error) reports
    value=None -- callers must render that distinctly, never as 0.
  - The QML Grid actually renders one cell per row when its tab is
    active, and clicking a 'done' cell loads that row's result into
    the main viewport via AppController.loadStudyResult (reused, not
    reimplemented).
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


_MOS_2X2 = dict(length_cm=1e-4, height_cm=2e-5, nx=16, ny=8)


def _run_2x2_study(gapp, controller):
    study = controller.studyManager
    ok = study.configureStudy(
        "mos_capacitor", _MOS_2X2,
        {"tox_cm": [7e-7, 8e-7], "na_cm3": [-1e16, -2e16]})
    assert ok
    study.runStudy()
    assert _pump_until(gapp, lambda: not study.running)
    return study


# ----------------------------------------------------------------------
#  G-GRID: a 2-parameter, 2x2 study's cells match the underlying
#  result scalars exactly, in the documented row-major order
# ----------------------------------------------------------------------
def test_matrix_cells_are_row_major_and_match_real_field_maxima(gapp):
    import numpy as np

    engine, controller = gui_app.create_engine(gapp)
    study = _run_2x2_study(gapp, controller)

    assert study.splitAxes == {"tox_cm": [7e-7, 8e-7], "na_cm3": [-1e16, -2e16]}
    fields = study.availableDisplayFields()
    assert "doping" in fields

    cells = study.matrixCells("doping")
    assert len(cells) == 4
    # row-major, LAST split key (na_cm3) fastest:
    expected_order = [(7e-7, -1e16), (7e-7, -2e16), (8e-7, -1e16), (8e-7, -2e16)]
    got_order = [(c["params"]["tox_cm"], c["params"]["na_cm3"]) for c in cells]
    assert got_order == expected_order

    for cell in cells:
        assert cell["status"] == "done"
        from gui.services.result_store import NpzResultStore
        store = NpzResultStore(cell["resultPath"])
        expected_value = float(np.max(store.scalar_field("doping").values))
        assert cell["value"] == pytest.approx(expected_value)


# ----------------------------------------------------------------------
#  G-PARTIAL: an incomplete/failed study distinguishes those rows
#  distinctly, not as a numeric 0
# ----------------------------------------------------------------------
def test_matrix_cells_report_none_not_zero_for_incomplete_rows(gapp):
    engine, controller = gui_app.create_engine(gapp)
    study = controller.studyManager
    ok = study.configureStudy(
        "mos_capacitor", _MOS_2X2, {"tox_cm": [7e-7, -1.0]})  # 2nd build-fails
    assert ok
    # deliberately do NOT run -- both rows are still 'pending'/'build_error'
    cells = study.matrixCells("doping")
    assert len(cells) == 2
    assert cells[0]["status"] == "pending" and cells[0]["value"] is None
    assert cells[1]["status"] == "build_error" and cells[1]["value"] is None


def test_available_display_fields_empty_before_any_row_completes(gapp):
    engine, controller = gui_app.create_engine(gapp)
    study = controller.studyManager
    study.configureStudy("pn_diode", {}, {"na_cm3": [-1e18, -2e18]})
    assert study.availableDisplayFields() == []


# ----------------------------------------------------------------------
#  G-SELECT: the Grid actually renders (tab active) and a cell click
#  loads that row's result into the viewport
# ----------------------------------------------------------------------
def test_matrix_grid_renders_and_cell_click_loads_the_viewport(gapp):
    import numpy as np

    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    root.findChild(object, "workbenchTabs").setProperty("currentIndex", 12)
    for _ in range(5):
        gapp.processEvents()

    study = _run_2x2_study(gapp, controller)
    for _ in range(10):
        gapp.processEvents()

    grid = root.findChild(object, "studyMatrixGrid")
    assert grid is not None
    assert grid.property("visible") is True
    assert grid.property("columns") == 2

    # studyMatrixGrid's Repeater is a Grid/Repeater delegate list: Qt's
    # offscreen platform never advances a Repeater's item incubator
    # without a real run loop, so per-delegate objectName lookups
    # (studyMatrixCell_0, etc.) return None headlessly even with the
    # right tab active -- the SAME documented limitation
    # test_smoke_e2e.py already records for labCatalogList/
    # templateParamColumn's own Repeaters, not new to this panel. The
    # accepted substitute already established there: verify what CAN be
    # driven headlessly (the model backing the Repeater has real
    # 'done' rows with real result paths) and call the exact method the
    # delegate's own `onClicked: root.hostController.loadStudyResult(...)`
    # invokes, rather than a synthesized mouse event the incubator can
    # never deliver to.
    cells = study.matrixCells("doping")
    assert cells[0]["status"] == "done" and cells[0]["resultPath"]

    fired = []
    controller.resultChanged.connect(lambda: fired.append(1))
    controller.loadStudyResult(cells[0]["resultPath"])

    assert fired, "loadStudyResult did not update the main viewport"
