"""Smoke test: the QML actually loads, with no QML errors, headlessly.
This is the test that catches a typo'd property binding or a missing
import before a human ever launches the app."""
import gc, os, sys

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


def test_shutdown_stderr_has_no_null_binding_typeerrors(gapp):
    """Regression test for the teardown noise class b381124 only half-
    fixed: AppController got a Qt parent (the engine), but the OTHER two
    context-property controllers -- physicsLab and deviceBuilder -- were
    constructed with no QObject parent at all, surviving purely on
    Python references. During engine destruction QML bindings could then
    outlive or race those unparented QObjects, printing 'TypeError:
    Cannot read property ... of null' to stderr on exit.

    This test captures file-descriptor 2 around full engine teardown
    (multiple engines torn down together + gc.collect(), so Python GC
    destroys context-property objects while other engines' QML bindings
    still evaluate) and demands zero such lines -- the same way a human
    watching the console would see them."""
    import gc
    from PySide6.QtCore import qInstallMessageHandler, QtMsgType

    # Qt emits QML warnings through its own message machinery, NOT
    # through Python's sys.stderr (and it caches the C-level stream, so
    # even fd-2 redirection misses them) -- intercept at the source.
    captured = []

    def handler(msg_type, context, message):
        if msg_type == QtMsgType.QtCriticalMsg or \
                msg_type == QtMsgType.QtWarningMsg:
            captured.append(message)

    prev = qInstallMessageHandler(handler)
    try:
        engines = []
        for _ in range(4):
            engine, controller = gui_app.create_engine(gapp)
            assert engine.rootObjects()
            engines.append(engine)
        del engines
        gc.collect()
        gapp.processEvents()
    finally:
        qInstallMessageHandler(prev)

    offenders = [ln for ln in captured
                 if "Cannot read property" in ln or "TypeError" in ln]
    assert offenders == [], \
        f"{len(offenders)} null-binding error(s) during shutdown:\n" \
        + "\n".join(offenders[:10])


def test_context_property_controllers_are_qt_owned(gapp):
    """physicsLab and deviceBuilder are exposed to QML as context
    properties, so their lifetime must be governed by the QObject
    parent chain -- not by Python attribute references, whose
    collection order at shutdown is arbitrary (the source of the
    exit-time 'Cannot call method ... of null' TypeErrors).

    Invariant: both are Qt children of AppController, and destroying
    the engine destroys them with it (no orphaned C++ objects left
    dangling behind dead QML contexts)."""
    import shiboken6

    engine, controller = gui_app.create_engine(gapp)
    assert engine.rootObjects()

    # 1) real Qt ownership, not bare Python references
    assert controller.lab.parent() is controller, \
        "PhysicsLabController must be a Qt child of AppController"
    assert controller.builder.parent() is controller, \
        "BuilderController must be a Qt child of AppController"

    # 2) the whole chain dies together when the engine goes away
    lab, builder = controller.lab, controller.builder
    engine.deleteLater()
    gapp.sendPostedEvents(None, 52)   # QEvent::DeferredDelete
    gapp.processEvents()
    gc.collect()

    def destroyed(obj):
        if not shiboken6.isValid(obj):
            return True
        try:
            obj.objectName()
        except RuntimeError:
            return True
        return False

    assert destroyed(controller), "AppController survived engine teardown"
    assert destroyed(lab), \
        "PhysicsLabController outlived its engine -- unparented QObject"
    assert destroyed(builder), \
        "BuilderController outlived its engine -- unparented QObject"
