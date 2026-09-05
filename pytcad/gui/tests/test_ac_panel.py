"""M18 Phase 4: ACPanel.qml -- QML object tree + AppController wiring.

Same headless pattern as test_sweep_panels.py: the real engine is
created via create_engine(), panels are found by objectName, and QML
objects are driven through their own properties and QMetaObject -- no
reimplementation of panel logic in Python.

(TransientPanel.qml has no QML-object-tree test of its own in this
suite -- it is only exercised at the AppController level, in
test_transient_gui.py -- so this mirrors SweepPanel's own
QML-object-tree convention instead, per this task's brief Step 1.)
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtCore import QMetaObject
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def _fresh(gapp):
    # keep the engine alive for the whole test -- returning only the root
    # lets Python GC the QQmlEngine and delete the C++ objects under us
    engine, controller = gui_app.create_engine(gapp)
    return engine, engine.rootObjects()[0], controller


def test_ac_panel_present_in_qml(gapp):
    engine, root, _ = _fresh(gapp)
    assert root.findChild(object, "acPanel") is not None, "missing acPanel"
    for name in ("acContactBox", "acFStartField", "acFStopField",
                 "acNPointsField", "applyAcButton", "clearAcButton"):
        assert root.findChild(object, name) is not None, f"missing {name}"


def test_ac_panel_arm_and_clear_end_to_end(gapp):
    engine, root, controller = _fresh(gapp)
    controller.loadExample("diode_1d")

    contact_box = root.findChild(object, "acContactBox")
    f_start = root.findChild(object, "acFStartField")
    f_stop = root.findChild(object, "acFStopField")
    n_points = root.findChild(object, "acNPointsField")
    apply_btn = root.findChild(object, "applyAcButton")
    clear_btn = root.findChild(object, "clearAcButton")

    contact_box.setProperty("currentIndex", 0)
    f_start.setProperty("text", "1.0")
    f_stop.setProperty("text", "1e9")
    n_points.setProperty("text", "30")
    QMetaObject.invokeMethod(apply_btn, "clicked")
    assert controller.hasACConfig

    QMetaObject.invokeMethod(clear_btn, "clicked")
    assert not controller.hasACConfig
