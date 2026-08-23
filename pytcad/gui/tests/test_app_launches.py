"""Smoke test: the QML actually loads, with no QML errors, headlessly.
This is the test that catches a typo'd property binding or a missing
import before a human ever launches the app."""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def test_engine_loads_qml_without_errors(gapp):
    engine, controller = gui_app.create_engine(gapp)
    assert engine.rootObjects(), "Main.qml failed to load -- see stderr for QML errors"
    assert controller is not None


def test_window_has_the_v01_furniture(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    assert root.property("visible") is not None
    # objectName-tagged pieces required by the v0.1 definition of done
    for name in ("projectTreePanel", "viewportPanel", "propertiesPanel",
                 "consolePanel", "statusBarLabel", "mainToolBar"):
        assert root.findChild(object, name) is not None, f"missing {name}"


def test_controller_is_reachable_and_can_load_the_example(gapp):
    engine, controller = gui_app.create_engine(gapp)
    controller.loadExample("mosfet_2d")
    assert controller.spec is not None
    assert "doping" in controller.fieldNames


def test_panels_actually_receive_their_models_through_qml_bindings(gapp):
    """Regression test for a real bug: propertiesModel/consoleModel were
    plain Python attributes, invisible to QML's meta-object property
    lookup, so `appController.propertiesModel` silently resolved to
    undefined and both panels rendered empty -- with every other test
    passing, because they all read the Python objects directly instead
    of going through the QML binding path. This test reads the QML
    property values themselves, the way a human eye caught it."""
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]

    properties_panel = root.findChild(object, "propertiesPanel")
    console_panel = root.findChild(object, "consolePanel")

    bound_properties_model = properties_panel.property("propertiesModel")
    bound_console_model = console_panel.property("consoleModel")
    assert bound_properties_model is not None, \
        "propertiesPanel.propertiesModel resolved to undefined/null in QML"
    assert bound_console_model is not None, \
        "consolePanel.consoleModel resolved to undefined/null in QML"

    controller.loadExample("mosfet_2d")

    # the QML-bound model must be the SAME object the controller mutates
    assert bound_properties_model.rowCount() == len(controller.propertiesModel.rows())
    assert bound_properties_model.rowCount() > 0
    assert bound_console_model.rowCount() == controller.consoleModel.rowCount()
    assert bound_console_model.rowCount() > 0
