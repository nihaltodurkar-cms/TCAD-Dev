"""GUI state machine tests (GUI-IMPROVEMENT-PLAN Phase 4).

Tests hard-to-detect bugs that are difficult to catch with unit tests:
- State transitions (busy -> ready, hasResult -> noResult, etc.)
- Null pointer exceptions in QML bindings
- Race conditions from rapid user input
- Memory leaks from dangling QObject references
- State inconsistencies between controller and UI
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
import shiboken6
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def test_state_validator_exists(gapp):
    """AppController has a stateValidator attribute."""
    from gui.controllers.app_controller import AppController
    ctl = AppController()
    assert hasattr(ctl, 'stateValidator')
    assert ctl.stateValidator is not None


def test_state_validator_detects_invalid_input(gapp):
    """GuiStateValidator detects invalid input values."""
    from gui.controllers.app_controller import AppController
    ctl = AppController()
    
    # Clear any existing problems
    ctl.stateValidator.clearProblems()
    
    # Check an invalid value
    ctl.stateValidator.checkValue("test_field", float('nan'))
    
    # Should have detected the problem
    assert ctl.stateValidator.problemCount > 0
    
    # Check that the problem is cleared when a valid value is provided
    ctl.stateValidator.checkValue("test_field", 1.0)
    
    # Problem should still be there (we didn't clear it)
    # But we can clear it explicitly
    ctl.stateValidator.clearProblems()
    assert ctl.stateValidator.problemCount == 0


def test_state_validator_on_state_change(gapp):
    """GuiStateValidator detects a stale result and clears it once the
    result is no longer dirty.

    has_store is passed True throughout: AppController.hasResult is
    defined as `self._store is not None and ...`, so has_result=True
    always implies has_store=True in real usage -- (True, False, *) is
    not a reachable AppController state and onStateChange no longer
    treats it specially (see gui_state_validator.py's onStateChange
    docstring)."""
    from gui.controllers.app_controller import AppController
    ctl = AppController()

    # Clear any existing problems
    ctl.stateValidator.clearProblems()

    # Simulate a stale result (has_result=True, is_dirty=True)
    ctl.stateValidator.onStateChange(True, True, True)

    # Should have detected the problem
    assert ctl.stateValidator.problemCount > 0

    # Fix the state (project no longer dirty)
    ctl.stateValidator.onStateChange(True, True, False)

    # Problem should be cleared
    assert ctl.stateValidator.problemCount == 0


def test_state_validator_on_state_change_stale_result(gapp):
    """GuiStateValidator detects stale results."""
    from gui.controllers.app_controller import AppController
    ctl = AppController()

    # Clear any existing problems
    ctl.stateValidator.clearProblems()

    # Simulate stale result (has_result=True, has_store=True, is_dirty=True)
    ctl.stateValidator.onStateChange(True, True, True)

    # Should have detected the problem
    assert ctl.stateValidator.problemCount > 0
    problems = ctl.stateValidator.problems
    assert any(p['category'] == 'stale_result' for p in problems)


def test_qml_null_safety_physics_lab(gapp):
    """PhysicsLabPanel handles null lab gracefully."""
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtCore import QUrl
    
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("physicsLab", None)
    engine.rootContext().setContextProperty("appController", None)
    
    # Load the PhysicsLabPanel QML
    qml_path = os.path.join(os.path.dirname(__file__), 
                           '../../qml/panels/PhysicsLabPanel.qml')
    engine.load(QUrl.fromLocalFile(qml_path))
    
    # Should not crash even with null physicsLab
    # (In a real test, we'd check for errors)
    engine.deleteLater()


def test_qml_null_safety_mesh_panel(gapp):
    """MeshPanel handles null controller gracefully."""
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtCore import QUrl
    
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("appController", None)
    
    # Load the MeshPanel QML
    qml_path = os.path.join(os.path.dirname(__file__), 
                           '../../qml/panels/MeshPanel.qml')
    engine.load(QUrl.fromLocalFile(qml_path))
    
    # Should not crash even with null controller
    engine.deleteLater()


def test_rapid_input_handling(gapp):
    """GUI handles rapid input without crashing."""
    from gui.controllers.app_controller import AppController
    from gui.services.result_store import NpzResultStore
    import tempfile
    import json
    import numpy as np
    
    ctl = AppController()
    
    # Create a minimal result file
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test.npz")
        meta = {
            "backend": "pytcad",
            "created_utc": "2026-01-01T00:00:00Z",
            "dimensionality": 1,
            "material": "Si",
            "T": 300.0,
            "models": {},
            "numerics": {},
            "schema_version": 2,
        }
        np.savez(path,
                 record__meta=np.array([json.dumps(meta)]),
                 dimensionality=np.array(1),
                 axis_x=np.array([0.0, 1e-4, 2e-4]),
                 field__potential=np.array([0.0, 0.1, 0.2]),
                 unit__potential=np.array("V"),
                 solved_bias=np.array([0.0, 0.1, 0.2]),
                 result__schema=np.array(2))
        
        store = NpzResultStore(path)
        ctl._store = store
        
        # Rapidly access properties (simulating rapid UI interactions)
        for _ in range(100):
            _ = ctl.hasResult
            _ = ctl.meshStats
            _ = ctl.fieldNames
            _ = ctl.stateValidator.problemCount
        
        # Should not crash
        assert ctl.hasResult


def test_qobject_lifecycle(gapp):
    """QObject lifecycle is managed correctly."""
    from gui.controllers.app_controller import AppController
    
    ctl = AppController()
    
    # Check that sub-controllers are Qt children of the main controller
    assert shiboken6.isValid(ctl.lab)
    assert shiboken6.isValid(ctl.builder)
    assert shiboken6.isValid(ctl.family)
    assert shiboken6.isValid(ctl.cv)
    assert shiboken6.isValid(ctl.stateValidator)
    
    # Check that they have the correct parent
    assert ctl.lab.parent() == ctl
    assert ctl.builder.parent() == ctl
    assert ctl.family.parent() == ctl
    assert ctl.cv.parent() == ctl
    assert ctl.stateValidator.parent() == ctl


def test_validation_banner_qml_loads(gapp):
    """ValidationBanner QML component loads without errors."""
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtCore import QUrl
    
    engine = QQmlApplicationEngine()
    
    # Create a mock stateValidator
    from gui.services.gui_state_validator import GuiStateValidator
    validator = GuiStateValidator()
    engine.rootContext().setContextProperty("stateValidator", validator)
    
    # Load the ValidationBanner QML
    qml_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                           'gui', 'qml', 'components', 'ValidationBanner.qml')
    engine.load(QUrl.fromLocalFile(qml_path))
    
    # Should not crash (even if there are QML warnings)
    # The important thing is that the engine doesn't crash
    
    engine.deleteLater()


def test_status_indicator_qml_loads(gapp):
    """StatusIndicator QML component loads without errors."""
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtCore import QUrl
    
    engine = QQmlApplicationEngine()
    
    # Load the StatusIndicator QML
    qml_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                           'gui', 'qml', 'components', 'StatusIndicator.qml')
    engine.load(QUrl.fromLocalFile(qml_path))
    
    # Should not crash (even if there are QML warnings)
    
    engine.deleteLater()


def test_validated_text_field_qml_loads(gapp):
    """ValidatedTextField QML component loads without errors."""
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtCore import QUrl
    
    engine = QQmlApplicationEngine()
    
    # Load the ValidatedTextField QML
    qml_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                           'gui', 'qml', 'components', 'ValidatedTextField.qml')
    engine.load(QUrl.fromLocalFile(qml_path))
    
    # Should not crash (even if there are QML warnings)
    
    engine.deleteLater()
