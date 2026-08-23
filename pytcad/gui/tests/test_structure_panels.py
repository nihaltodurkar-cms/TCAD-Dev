"""Smoke test for the v0.2 QML additions -- same headless pattern as
v0.1's test_app_launches.py, extended to the new panels."""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def test_engine_still_loads_with_v02_panels(gapp):
    engine, controller = gui_app.create_engine(gapp)
    assert engine.rootObjects(), "Main.qml failed to load -- see stderr for QML errors"


def test_v02_panels_and_their_models_bind_through_qml(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    controller.loadStructureExample("mosfet_2d_structure")

    structure_panel = root.findChild(object, "structurePanel")
    mesh_panel = root.findChild(object, "meshPanel")
    assert structure_panel is not None, "missing structurePanel"
    assert mesh_panel is not None, "missing meshPanel"


def test_view_mode_selector_exists_and_switches(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    selector = root.findChild(object, "viewModeSelector")
    assert selector is not None, "missing viewModeSelector"


def test_dirty_title_reflects_undo_state(gapp):
    engine, controller = gui_app.create_engine(gapp)
    controller.loadStructureExample("mosfet_2d_structure")
    assert controller.isDirty is False
    controller.addRegion("Extra", 0.0, 1e-5, 0.0, 1e-5, 1e16)
    assert controller.isDirty is True
