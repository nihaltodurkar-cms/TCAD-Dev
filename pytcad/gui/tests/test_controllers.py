"""Controllers hold all UI-facing state, so they are testable without any
QML.  That is the point of the split: if these pass headlessly, the QML
layer is only bindings."""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer, Qt

from gui.controllers.app_controller import AppController
from gui.controllers.console_model import ConsoleModel
from gui.controllers.project_tree_model import ProjectTreeModel
from gui.controllers.properties_model import PropertiesModel


@pytest.fixture(scope="module")
def qapp():
    yield QCoreApplication.instance() or QCoreApplication([])


def test_project_tree_has_the_standard_workflow_nodes(qapp):
    m = ProjectTreeModel()
    root = m.index(0, 0)
    assert m.data(root, Qt.DisplayRole) == "Project"
    labels = [m.data(m.index(r, 0, root), Qt.DisplayRole)
              for r in range(m.rowCount(root))]
    assert labels == ["Process", "Structure", "Mesh", "Device", "Results"]


def test_console_model_appends_and_clears(qapp):
    c = ConsoleModel()
    c.append("hello")
    c.append("world")
    assert c.rowCount() == 2
    assert c.data(c.index(0, 0), ConsoleModel.LineRole) == "hello"
    c.clear()
    assert c.rowCount() == 0


def test_properties_model_exposes_key_value_rows(qapp):
    p = PropertiesModel()
    p.setRows([("Nodes", "7752"), ("Dimensionality", "2D")])
    assert p.rowCount() == 2
    assert p.data(p.index(0, 0), PropertiesModel.KeyRole) == "Nodes"
    assert p.data(p.index(0, 0), PropertiesModel.ValueRole) == "7752"


def test_loading_example_populates_structure_and_allows_preview(qapp):
    app = AppController()
    app.loadExample("mosfet_2d")

    assert app.spec is not None
    assert app.hasResult is False
    # doping is visualizable immediately, before any solve
    store = app.currentStore()
    assert store is not None
    assert "doping" in store.available_scalars()
    assert "doping" in app.fieldNames

    app.selectNode("structure")
    keys = [k for k, _ in app.propertiesModel.rows()]
    assert "Dimensionality" in keys and "Nodes" in keys


def test_run_completes_and_exposes_solved_fields(qapp):
    app = AppController()
    app.loadExample("mosfet_2d")

    loop = QEventLoop()
    app.resultChanged.connect(loop.quit)
    app.errorRaised.connect(lambda s, d: loop.quit())
    QTimer.singleShot(180000, loop.quit)
    app.run()
    assert app.busy is True
    loop.exec()

    assert app.hasResult is True, app.status
    assert app.busy is False
    assert "potential" in app.fieldNames
    assert "electron_density" in app.fieldNames
    assert app.consoleModel.rowCount() > 0

    app.selectNode("results")
    rows = dict(app.propertiesModel.rows())
    # terminal currents must always carry their unit
    assert any("A/cm" in v for v in rows.values())


def test_backend_error_surfaces_without_crashing(qapp):
    app = AppController()
    app.loadExample("mosfet_2d")
    app.spec.doping.values = "not an array"

    loop = QEventLoop()
    seen = {}
    app.errorRaised.connect(lambda s, d: (seen.update(summary=s, details=d), loop.quit()))
    app.resultChanged.connect(loop.quit)
    QTimer.singleShot(120000, loop.quit)
    app.run()
    loop.exec()

    assert seen.get("summary"), "an error should have been reported"
    assert app.busy is False
    assert app.hasResult is False
