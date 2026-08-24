"""Application bootstrap.

    cd pytcad && python -m gui.app

create_engine() is kept separate from main() so the smoke test can load
the QML headlessly without entering an event loop.
"""
import os
import sys

# Make the project root importable so both `pytcad` and `gui` resolve
# however the app is launched -- matching what tests/ and examples/ do.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType

from gui.controllers.app_controller import AppController
from gui.visualization.mpl_canvas_item import MplCanvasItem

QML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qml")


def create_engine(app):
    """Build the QML engine and controller.  Returns (engine, controller).

    The caller keeps both alive -- letting the controller be garbage
    collected would tear down the models QML is bound to.
    """
    qmlRegisterType(MplCanvasItem, "PyTCAD", 1, 0, "MplCanvas")

    engine = QQmlApplicationEngine()
    engine.addImportPath(QML_DIR)

    controller = AppController()
    # Parent the controller to the engine (both QObjects): without this,
    # Python GC can destroy the controller while QML bindings still
    # evaluate during engine teardown, and every binding sees a null
    # appController -- the source of the noisy "Cannot read property
    # '<x>' of null" TypeErrors on exit.  The engine now destroys the
    # controller only AFTER the QML tree is gone.
    controller.setParent(engine)
    engine.rootContext().setContextProperty("appController", controller)
    engine.rootContext().setContextProperty("physicsLab", controller.lab)
    engine.rootContext().setContextProperty("deviceBuilder",
                                            controller.builder)
    engine.load(QUrl.fromLocalFile(os.path.join(QML_DIR, "Main.qml")))

    # hold references on the engine so they outlive this function
    engine._controller = controller
    return engine, controller


def main():
    app = QGuiApplication(sys.argv)
    app.setApplicationName("PyTCAD")
    engine, controller = create_engine(app)
    if not engine.rootObjects():
        print("failed to load QML", file=sys.stderr)
        return 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
