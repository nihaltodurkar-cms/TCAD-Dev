"""M38 Phase 4: CompactModelPanel.qml -- QML object tree + controller
wiring. Same headless pattern as test_ac_panel.py: a real engine via
create_engine(), panels found by objectName, driven through their own
properties and QMetaObject.

Plan: `M38-PHASE4-PLAN.md`.
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

import pytest
from PySide6.QtCore import QMetaObject
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app

COMPACT_TAB_INDEX = 13


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def _fresh(gapp):
    engine, controller = gui_app.create_engine(gapp)
    return engine, engine.rootObjects()[0], controller


def _select_compact_tab(root):
    root.findChild(object, "workbenchTabs").setProperty(
        "currentIndex", COMPACT_TAB_INDEX)


def test_compact_model_panel_present_in_qml(gapp):
    engine, root, _ = _fresh(gapp)
    assert root.findChild(object, "compactModelPanel") is not None
    for name in ("compactKindBox", "runExtractionButton",
                 "compactDiodeL", "compactMosfetLg"):
        assert root.findChild(object, name) is not None, f"missing {name}"


def test_diode_extraction_end_to_end_through_the_panel(gapp):
    engine, root, controller = _fresh(gapp)
    _select_compact_tab(root)

    kind_box = root.findChild(object, "compactKindBox")
    run_btn = root.findChild(object, "runExtractionButton")
    kind_box.setProperty("currentIndex", 0)

    done = []
    controller.compact_model.changed.connect(lambda: done.append(1))

    QMetaObject.invokeMethod(run_btn, "clicked")
    for _ in range(600):
        gapp.processEvents()
        gapp.thread().msleep(100)
        if not controller.compact_model.running and done:
            break
    assert not controller.compact_model.running, \
        "extraction did not finish in time"

    result_json = controller.compact_model.resultJson
    assert result_json, controller.compact_model.lastError
    result = json.loads(result_json)
    assert result["kind"] == "diode"
    assert result["converged"]
    summary = root.findChild(object, "compactResultSummary")
    assert "Diode" in summary.property("text")
    netlist_area = root.findChild(object, "compactNetlistArea")
    assert netlist_area.property("text").startswith("* PyTCAD")


def test_kind_toggle_shows_the_right_field_group(gapp):
    engine, root, controller = _fresh(gapp)
    _select_compact_tab(root)
    gapp.processEvents()
    kind_box = root.findChild(object, "compactKindBox")
    diode_field = root.findChild(object, "compactDiodeL")
    mosfet_field = root.findChild(object, "compactMosfetLg")

    kind_box.setProperty("currentIndex", 0)
    gapp.processEvents()
    assert diode_field.parent().property("visible") is True
    assert mosfet_field.parent().property("visible") is False

    kind_box.setProperty("currentIndex", 1)
    gapp.processEvents()
    assert diode_field.parent().property("visible") is False
    assert mosfet_field.parent().property("visible") is True
