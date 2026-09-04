"""Checks the v2 reskin's dock sizing and card-surface retoning in
Main.qml: the workbench dock is wider than the pre-reskin 310/240
default, and the workbench/properties/console docks plus the viewport
all use the new cardBg/cardBorder tokens instead of the old
panel/panelAlt/border ones.

Loads the real Main.qml through gui.app.create_engine(), like
test_shell_icons.py's predecessor did.
"""
from PySide6.QtCore import QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from gui.app import close_engine, create_engine

# Theme.qml v2's dark-mode values (see test_theme_tokens.py) -- Main.qml's
# create_engine() starts with Theme.dark == true, its documented default.
CARD_BG = "#16171d"


def _pump(app, rounds=20):
    for _ in range(rounds):
        app.processEvents()


def test_workbench_dock_is_wider_than_the_pre_reskin_default():
    app = QApplication.instance() or QApplication([])
    engine, controller = create_engine(app)
    try:
        root = engine.rootObjects()[0]
        dock = root.findChild(QObject, "workbenchDock")
        assert dock is not None
        # QQmlProperty can't resolve the "SplitView.preferredWidth"
        # attached property from Python in this PySide6 build (confirmed
        # directly: isValid() is False regardless of whether an engine
        # context is supplied) -- check the actual RENDERED width
        # instead, after letting the SplitView's layout settle. This
        # tests the observable outcome (the dock really is wider) rather
        # than a specific binding's internal value.
        _pump(app)
        width = dock.property("width")
        assert width > 310, f"expected rendered width > 310, got {width}"
    finally:
        close_engine(engine)


def test_docks_and_viewport_use_card_surface_tokens():
    app = QApplication.instance() or QApplication([])
    engine, controller = create_engine(app)
    try:
        root = engine.rootObjects()[0]
        for name in ("workbenchDock", "propertiesDock", "consoleDock"):
            dock = root.findChild(QObject, name)
            assert dock is not None, name
            color = QColor(dock.property("color")).name()
            assert color == CARD_BG, f"{name}: expected {CARD_BG}, got {color}"

        viewport = root.findChild(QObject, "viewportPanel")
        assert viewport is not None
        v_color = QColor(viewport.property("color")).name()
        assert v_color == CARD_BG, f"viewportPanel: expected {CARD_BG}, got {v_color}"
    finally:
        close_engine(engine)
