"""Workflow-friction pass: AppController.hasDeviceToRun, Main.qml's Run
button gating on it, and ViewportPanel.qml's empty-state overlay.

Before this change, run() with nothing loaded raised a dead-end
"Nothing to run" / "Load an example first." error dialog -- the Run
button was always enabled regardless of whether there was anything to
run, and a fresh launch showed only the bare "No project loaded"
matplotlib placeholder with no indication of what to do next.
hasDeviceToRun mirrors run()'s own early-return check so both are
fixed off the same single source of truth.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from gui.app import close_engine, create_engine
from gui.controllers.app_controller import AppController


def test_has_device_to_run_false_on_a_fresh_controller():
    ctl = AppController()
    assert ctl.hasDeviceToRun is False


def test_has_device_to_run_true_after_load_example():
    ctl = AppController()
    ctl.loadExample("diode_1d")
    assert ctl.hasDeviceToRun is True


def test_has_device_to_run_true_when_structure_is_set_directly():
    ctl = AppController()
    ctl.structure = object()  # any non-None sentinel; run() only checks identity
    assert ctl.hasDeviceToRun is True


def test_has_device_to_run_matches_runs_own_nothing_to_run_condition():
    # A real run() call with nothing loaded emits errorRaised("Nothing
    # to run", ...) -- the exact condition hasDeviceToRun mirrors.
    ctl = AppController()
    received = []
    ctl.errorRaised.connect(lambda summary, details: received.append(summary))
    assert ctl.hasDeviceToRun is False
    ctl.run()
    assert received == ["Nothing to run"]


def test_run_button_disabled_with_nothing_loaded_enabled_after_load_example():
    app = QApplication.instance() or QApplication([])
    engine, controller = create_engine(app)
    try:
        root = engine.rootObjects()[0]
        run_button = root.findChild(QObject, "runButton")
        assert run_button is not None
        assert run_button.property("enabled") is False

        controller.loadExample("diode_1d")
        for _ in range(5):
            app.processEvents()
        assert run_button.property("enabled") is True
    finally:
        close_engine(engine)


def test_viewport_empty_state_visible_on_fresh_launch_hidden_after_load():
    app = QApplication.instance() or QApplication([])
    engine, controller = create_engine(app)
    try:
        root = engine.rootObjects()[0]
        empty_state = root.findChild(QObject, "viewportEmptyState")
        assert empty_state is not None
        assert empty_state.property("visible") is True

        controller.loadExample("diode_1d")
        for _ in range(5):
            app.processEvents()
        assert empty_state.property("visible") is False
    finally:
        close_engine(engine)


def test_viewport_empty_state_buttons_load_the_expected_examples():
    app = QApplication.instance() or QApplication([])
    engine, controller = create_engine(app)
    try:
        root = engine.rootObjects()[0]
        diode_button = root.findChild(QObject, "emptyStateLoadDiodeButton")
        mosfet_button = root.findChild(QObject, "emptyStateLoadMosfetButton")
        assert diode_button is not None and mosfet_button is not None

        from PySide6.QtCore import QMetaObject
        QMetaObject.invokeMethod(diode_button, "clicked")
        for _ in range(5):
            app.processEvents()
        assert controller.hasDeviceToRun is True
        assert "diode_1d" in controller.status
    finally:
        close_engine(engine)
