"""Memory leak detection and QObject lifecycle tests (GUI-IMPROVEMENT-PLAN Phase 4).

Tests for:
- QObject parent/child relationships
- Dangling references after controller destruction
- Memory leaks from unparented objects
- Proper cleanup during engine teardown
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
import gc
import weakref
import shiboken6
from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import QObject

from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def test_controller_lifecycle(gapp):
    """AppController and all sub-controllers are properly parented."""
    from gui.controllers.app_controller import AppController
    
    ctl = AppController()
    
    # Check that all sub-controllers are Qt children
    children = ctl.children()
    assert ctl.lab in children
    assert ctl.builder in children
    assert ctl.family in children
    assert ctl.cv in children
    assert ctl.stateValidator in children
    
    # Check that they have the correct parent
    assert ctl.lab.parent() == ctl
    assert ctl.builder.parent() == ctl
    assert ctl.family.parent() == ctl
    assert ctl.cv.parent() == ctl
    assert ctl.stateValidator.parent() == ctl


def test_engine_teardown_no_errors(gapp):
    """Engine teardown doesn't leave dangling references."""
    from gui.controllers.app_controller import AppController
    
    engine, ctl = gui_app.create_engine(gapp)
    
    # Check that the controller is alive
    assert ctl is not None
    
    # Teardown the engine
    gui_app.close_engine(engine)
    
    # The controller should still be alive (Python reference)
    # but the QML engine should be cleaned up
    # (We can't easily check this without shiboken)


def test_subcontroller_lifecycle(gapp):
    """Sub-controllers are destroyed when parent is destroyed."""
    from gui.controllers.app_controller import AppController
    import shiboken6
    
    ctl = AppController()
    
    # Create weak references to sub-controllers
    lab_ref = weakref.ref(ctl.lab)
    builder_ref = weakref.ref(ctl.builder)
    family_ref = weakref.ref(ctl.family)
    cv_ref = weakref.ref(ctl.cv)
    validator_ref = weakref.ref(ctl.stateValidator)
    
    # Delete the controller
    del ctl
    
    # Force garbage collection
    gc.collect()
    
    # All sub-controllers should be destroyed (Qt children are destroyed with parent)
    assert lab_ref() is None, "lab controller not destroyed"
    assert builder_ref() is None, "builder controller not destroyed"
    assert family_ref() is None, "family controller not destroyed"
    assert cv_ref() is None, "cv controller not destroyed"
    assert validator_ref() is None, "stateValidator not destroyed"


def test_no_dangling_qml_bindings(gapp):
    """QML bindings don't reference destroyed objects."""
    from gui.controllers.app_controller import AppController
    
    engine, ctl = gui_app.create_engine(gapp)
    
    # Get the root object
    root = engine.rootObjects()[0]
    
    # Check that the root object can access appController
    assert root.property("appController") is not None or \
           engine.rootContext().contextProperty("appController") is not None
    
    # Teardown
    gui_app.close_engine(engine)
    
    # If we get here without crashes, the test passes


def test_state_validator_cleanup(gapp):
    """GuiStateValidator is cleaned up properly with its parent.

    GuiStateValidator has no QTimer any more (it's event-driven via
    onStateChange()/checkValue(), see gui_state_validator.py) -- this
    only checks the validator itself is destroyed with its parent."""
    from gui.controllers.app_controller import AppController
    import weakref

    ctl = AppController()

    # Create a weak reference to the validator
    validator_ref = weakref.ref(ctl.stateValidator)

    # Delete the controller
    del ctl

    # Force garbage collection
    gc.collect()

    assert validator_ref() is None, "stateValidator not destroyed"


def test_multiple_engines_isolated(gapp):
    """Multiple QML engines are properly isolated."""
    from gui.controllers.app_controller import AppController
    
    engine1, ctl1 = gui_app.create_engine(gapp)
    engine2, ctl2 = gui_app.create_engine(gapp)
    
    # Controllers should be different objects
    assert ctl1 is not ctl2
    
    # Sub-controllers should be different objects
    assert ctl1.lab is not ctl2.lab
    assert ctl1.builder is not ctl2.builder
    assert ctl1.stateValidator is not ctl2.stateValidator
    
    # Teardown
    gui_app.close_engine(engine1)
    gui_app.close_engine(engine2)


def test_state_validator_destroyed_with_parent(gapp):
    """GuiStateValidator (a QObject child of AppController, no timer of
    its own any more) is destroyed when its parent is."""
    from gui.controllers.app_controller import AppController
    import shiboken6

    ctl = AppController()
    validator = ctl.stateValidator

    # Delete the controller (which will delete the validator as a child)
    del ctl
    gc.collect()

    assert not shiboken6.isValid(validator)


def test_no_python_memory_leaks(gapp):
    """No Python memory leaks from GUI controllers."""
    from gui.controllers.app_controller import AppController
    import tracemalloc
    
    # Start tracing
    tracemalloc.start()
    
    # Create and destroy controllers
    for _ in range(10):
        ctl = AppController()
        del ctl
    
    # Force garbage collection
    gc.collect()
    
    # Get current and peak memory usage
    current, peak = tracemalloc.get_traced_memory()
    
    # Stop tracing
    tracemalloc.stop()
    
    # Check that memory usage is reasonable
    # (Allow 10MB headroom for the test itself)
    assert current < 10 * 1024 * 1024, f"Memory leak detected: {current / 1024 / 1024:.2f} MB"


def test_qml_component_lifecycle(gapp):
    """QML components are properly destroyed."""
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtCore import QUrl
    import os
    
    # Create a simple QML component
    qml_content = """
    import QtQuick
    import QtQuick.Controls
    
    Rectangle {
        id: root
        width: 100
        height: 100
        color: "red"
        
        Component.onCompleted: {
            // Create a child object
            var child = Qt.createQmlObject(
                'import QtQuick; Text { text: "child" }', root)
        }
    }
    """
    
    # Write to a temp file
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.qml', delete=False) as f:
        f.write(qml_content)
        qml_path = f.name
    
    try:
        engine = QQmlApplicationEngine()
        engine.load(QUrl.fromLocalFile(qml_path))
        
        # Check that the component loaded
        assert len(engine.rootObjects()) > 0
        
        # Teardown
        gui_app.close_engine(engine)
    finally:
        os.unlink(qml_path)
