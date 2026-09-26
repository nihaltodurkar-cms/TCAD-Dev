"""Checks the v3.0-glassmorphism dock sizing and surface toning in
Main.qml: the workbench dock is wider than the pre-reskin 310/240
default, and the workbench/properties/console docks are TRANSLUCENT
glass panel surfaces (Theme.panel, alpha < 1) while the viewport
stays the app's darkest, fully OPAQUE canvas (Theme.background,
alpha == 1 -- it's a rendering surface, not something content should
show through). v3.0 supersedes the earlier v2.1 correction, which had
made docked panels flat and fully opaque; RGB channels are unchanged
across that reversal (only alpha moved), which is why the hex-name
assertions below still hold -- see Theme.qml's own header comment and
test_theme_tokens.py.

Loads the real Main.qml through gui.app.create_engine(), like
test_shell_icons.py's predecessor did.
"""
from PySide6.QtCore import QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from gui.app import close_engine, create_engine

# Theme.qml's values (one black-and-white scheme since 2026-09-26; see
# test_theme_tokens.py): Theme.panel and Theme.background.
PANEL_BG = "#ffffff"
VIEWPORT_BG = "#ffffff"


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


def test_docks_and_viewport_are_opaque_white_surfaces():
    """One black-and-white scheme (2026-09-26): the glass docks are gone --
    nothing is painted behind them any more, so they are opaque."""
    app = QApplication.instance() or QApplication([])
    engine, controller = create_engine(app)
    try:
        root = engine.rootObjects()[0]
        for name in ("workbenchDock", "propertiesDock", "consoleDock"):
            dock = root.findChild(QObject, name)
            assert dock is not None, name
            color = QColor(dock.property("color"))
            assert color.name() == PANEL_BG, f"{name}: expected {PANEL_BG}, got {color.name()}"
            assert color.alphaF() == 1.0, f"{name}: expected an opaque panel, got alpha={color.alphaF()}"

        viewport = root.findChild(QObject, "viewportPanel")
        assert viewport is not None
        v_color = QColor(viewport.property("color"))
        assert v_color.name() == VIEWPORT_BG, f"viewportPanel: expected {VIEWPORT_BG}, got {v_color.name()}"
        assert v_color.alphaF() == 1.0, (
            "viewportPanel: expected a fully opaque rendering surface, "
            f"got alpha={v_color.alphaF()}")
    finally:
        close_engine(engine)


def test_window_palette_is_black_and_white_even_under_a_dark_os():
    """Qt's own controls (menu bar, split handles, check boxes) paint from
    the palette, which follows the OS unless pinned: a dark Windows setting
    drew white menu titles on the white bar and black split handles
    (2026-09-26, found in the running app). Main.qml pins it to Theme."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlEngine, QQmlExpression

    app = QApplication.instance() or QApplication([])
    hints = QGuiApplication.styleHints()
    hints.setColorScheme(Qt.ColorScheme.Dark)
    engine, controller = create_engine(app)
    try:
        root = engine.rootObjects()[0]

        def colour(expr):
            value, error = QQmlExpression(QQmlEngine.contextForObject(root), root, expr).evaluate()
            assert not error, expr
            return QColor(value).name()

        for role, token in (("windowText", "text"), ("buttonText", "text"), ("text", "text"),
                            ("window", "chromeBg"), ("base", "panel"), ("highlight", "accent"),
                            ("highlightedText", "textOnAccent"), ("mid", "border"), ("dark", "borderStrong")):
            assert colour(f"palette.{role}") == colour(f"Theme.{token}"), role
        assert colour("palette.windowText") == "#000000"
        assert colour("palette.window") == "#f2f2f2"
    finally:
        close_engine(engine)
        hints.unsetColorScheme()

