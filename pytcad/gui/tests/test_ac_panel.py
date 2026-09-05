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


# ----------------------------------------------------------------------
#  rejected arm attempt must revert the fields to the LIVE armed config
#  (mirrors test_sweep_panels.py's own
#  test_rejected_arm_reverts_fields_to_armed_config)
# ----------------------------------------------------------------------
def test_rejected_arm_reverts_fields_to_armed_config(gapp):
    engine, root, controller = _fresh(gapp)
    controller.loadExample("diode_1d")

    contact_box = root.findChild(object, "acContactBox")
    f_start = root.findChild(object, "acFStartField")
    f_stop = root.findChild(object, "acFStopField")
    n_points = root.findChild(object, "acNPointsField")
    apply_btn = root.findChild(object, "applyAcButton")

    # arm a valid AC sweep through the panel
    contact_box.setProperty("currentIndex", 0)
    f_start.setProperty("text", "1.0")
    f_stop.setProperty("text", "1e9")
    n_points.setProperty("text", "30")
    QMetaObject.invokeMethod(apply_btn, "clicked")
    assert controller.hasACConfig is True

    # type garbage over it (f_stop <= f_start) and hit Arm again
    f_stop.setProperty("text", "0.5")
    errors = []
    controller.errorRaised.connect(lambda s, d: errors.append(s))
    QMetaObject.invokeMethod(apply_btn, "clicked")

    assert "Invalid AC configuration" in errors
    assert controller.hasACConfig is True, "rejection dropped the armed AC config"
    note = root.findChild(object, "acRejectNote")
    assert note is not None and note.property("visible") is True, \
        "panel gave no hint that the armed values differ from the typed ones"
    # the fields were reverted to the LIVE config -- screen == what Run uses
    assert float(f_start.property("text")) == 1.0
    assert float(f_stop.property("text")) == 1e9
    assert int(n_points.property("text")) == 30

    # a subsequent successful arm clears the rejection note
    f_stop.setProperty("text", "2e9")
    QMetaObject.invokeMethod(apply_btn, "clicked")
    assert controller.acConfig()["f_stop"] == 2e9
    assert note.property("visible") is False
