"""Checks the v2.1-corrected dock sizing and surface toning in
Main.qml: the workbench dock is wider than the pre-reskin 310/240
default, and the workbench/properties/console docks are flat panel
surfaces (Theme.panel) while the viewport is the app's darkest,
flush-against-chrome canvas (Theme.background) -- not floating
cardBg/cardBorder cards (DESIGN.md section 2/7/10 -- the v2 reskin's
card treatment on docked surfaces is reversed; cardBg/cardBorder
remain defined in Theme.qml but are now reserved for the transient
overlay layer only, see test_theme_tokens.py).

Loads the real Main.qml through gui.app.create_engine(), like
test_shell_icons.py's predecessor did.
"""
from PySide6.QtCore import QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from gui.app import close_engine, create_engine

# Theme.qml's dark-mode values (see test_theme_tokens.py) -- Main.qml's
# create_engine() starts with Theme.dark == true, its documented default.
PANEL_BG = "#0d0e12"
VIEWPORT_BG = "#0a0b0e"


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


def test_docks_are_flat_panels_and_viewport_is_the_darkest_surface():
    app = QApplication.instance() or QApplication([])
    engine, controller = create_engine(app)
    try:
        root = engine.rootObjects()[0]
        for name in ("workbenchDock", "propertiesDock", "consoleDock"):
            dock = root.findChild(QObject, name)
            assert dock is not None, name
            color = QColor(dock.property("color")).name()
            assert color == PANEL_BG, f"{name}: expected {PANEL_BG}, got {color}"

        viewport = root.findChild(QObject, "viewportPanel")
        assert viewport is not None
        v_color = QColor(viewport.property("color")).name()
        assert v_color == VIEWPORT_BG, f"viewportPanel: expected {VIEWPORT_BG}, got {v_color}"
    finally:
        close_engine(engine)
