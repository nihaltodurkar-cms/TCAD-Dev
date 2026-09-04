"""Checks that Main.qml's sidebar tab model only references icon names
that actually exist in the icon registry.

This does NOT introspect the rendered tab bar: confirmed directly
(2026-09-04) that `TabBar { Repeater { delegate: TabButton {...} } }`
delegate items are unreachable via QObject.findChildren() and even via
TabBar.itemAt() in this PySide6/Qt build, for the PRE-EXISTING
Text-only delegate as much as the new Image-bearing one (reproduced by
diffing against the pre-reskin Main.qml directly) -- so tree
introspection cannot be the regression gate here regardless of how the
delegate is implemented. A typo in one of Main.qml's icon names is
instead caught statically, by parsing the tab model out of the QML
source and cross-checking every name against the same registry
gui/services/icon_provider.py actually rasterizes from (see
test_icons.py for the pixel-level rendering gate, and
Main.qml's own live-app verification in the reskin plan for the
one visual check this test can't provide).
"""
import os
import re

from gui.services.icon_provider import ICON_PATHS

MAIN_QML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "qml", "Main.qml",
)
# QML architecture cleanup: the toolbar (and its Icons.svg(...) calls)
# moved from Main.qml into its own component -- see
# components/MainToolBar.qml's header comment for why.
TOOLBAR_QML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "qml", "components", "MainToolBar.qml",
)

EXPECTED_TAB_COUNT = 11


def _sidebar_tab_icon_names():
    text = open(MAIN_QML, encoding="utf-8").read()
    # The workbenchTabs Repeater's model is a JS array literal of
    # { "label": ..., "icon": "<name>" } objects -- pull out every
    # "icon" value between the TabBar's own id and its closing
    # Repeater block, not just anywhere in the file (toolbar buttons
    # pass icon names as plain Icons.svg("run", ...) call arguments,
    # a different shape, deliberately not matched by this pattern).
    start = text.index('id: workbenchTabs')
    repeater_start = text.index('Repeater {', start)
    repeater_end = text.index(']', repeater_start)
    block = text[repeater_start:repeater_end]
    return re.findall(r'"icon"\s*:\s*"([^"]+)"', block)


def test_every_sidebar_tab_icon_name_is_registered():
    names = _sidebar_tab_icon_names()
    assert len(names) == EXPECTED_TAB_COUNT, (
        f"expected {EXPECTED_TAB_COUNT} sidebar tabs, found {len(names)}: {names}"
    )
    unknown = [n for n in names if n not in ICON_PATHS]
    assert not unknown, f"sidebar tab icon name(s) not in ICON_PATHS: {unknown}"


def test_toolbar_icon_calls_reference_registered_names():
    text = open(TOOLBAR_QML, encoding="utf-8").read()
    # Icons.svg(<name-expr>, <color-expr>) calls for the toolbar buttons
    # (run/stop/undo/redo/sun/moon). The name argument is either a plain
    # string literal ("run") or a ternary between two literals
    # (Theme.dark ? "sun" : "moon", the theme-toggle button) -- so this
    # collects every quoted string appearing before the first top-level
    # comma inside each Icons.svg(...) call, not just a single literal
    # first argument.
    names_found = set()
    for call_start in [m.start() for m in re.finditer(r'Icons\.svg\(', text)]:
        arg_start = call_start + len('Icons.svg(')
        comma = text.index(',', arg_start)
        name_expr = text[arg_start:comma]
        names_found.update(re.findall(r'"([^"]+)"', name_expr))

    assert names_found, "expected at least one Icons.svg(...) call in MainToolBar.qml"
    unknown = [n for n in names_found if n not in ICON_PATHS]
    assert not unknown, f"Icons.svg() call(s) with unregistered name(s): {unknown}"
    expected_toolbar = {"run", "stop", "undo", "redo", "sun", "moon"}
    assert expected_toolbar <= names_found, (
        f"expected toolbar icon names {expected_toolbar} to all appear in "
        f"Icons.svg(...) calls, found: {names_found}"
    )
