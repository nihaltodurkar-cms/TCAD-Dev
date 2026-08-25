"""M10 growth UI: the deck file-open entry point and the controller
slot behind it."""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def test_controller_rundeck_adopts_structure_and_arms_sweep(gapp):
    """The full front door: a deck text becomes an editable Structure
    workbench session with the sweep armed -- exactly what a user gets
    from the file-open dialog."""
    engine, controller = gui_app.create_engine(gapp)
    controller.runDeck("""
        go
        template pn_diode
        sweep n start=0.0 stop=0.5 step=0.1
        end
    """)
    assert controller.structure is not None
    cfg = controller.sweepConfig()
    assert cfg is not None and cfg["contact"] == "n"


def test_main_qml_has_a_deck_open_entry_point(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    assert root.findChild(object, "openDeckAction") is not None, \
        "Main.qml has no file-open entry point for decks"
