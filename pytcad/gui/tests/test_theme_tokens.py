"""Headless checks for Theme.qml v2's design-system tokens.

Loads the Theme singleton through a standalone QQmlComponent (not the
full Main.qml window) so this stays a cheap, independent regression
gate: if a future edit drops a token or breaks dark/light retuning,
this fails on its own, without booting the whole app.
"""
import os

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor
from PySide6.QtQml import QQmlComponent, QQmlEngine

QML_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "qml"
)

PROBE_QML = """
import QtQuick
QtObject {
    property bool setDark: true
    onSetDarkChanged: Theme.dark = setDark
    property color background: Theme.background
    property color panel: Theme.panel
    property color cardBg: Theme.cardBg
    property color cardBorder: Theme.cardBorder
    property color accent: Theme.accent
    property color accentGradientStart: Theme.accentGradientStart
    property color accentGradientEnd: Theme.accentGradientEnd
    property int radiusCard: Theme.radiusCard
}
"""


def _make_probe(qml_engine):
    component = QQmlComponent(qml_engine)
    component.setData(
        PROBE_QML.encode("utf-8"),
        QUrl.fromLocalFile(os.path.join(QML_DIR, "_theme_probe.qml")),
    )
    obj = component.create()
    assert obj is not None, component.errorString()
    assert component.errorString() == ""
    # The QQmlComponent must outlive the object it created -- letting
    # `component` (a local variable) get garbage-collected when this
    # function returns takes the created object's underlying C++
    # object down with it (confirmed directly: a bare `return obj`
    # here reproduces "libshiboken: Internal C++ object already
    # deleted" on the very next property access, even though `obj`
    # itself is still referenced). Anchoring `component` as an
    # attribute of the object it created keeps it alive exactly as
    # long as the object is.
    obj._keepalive_component = component
    return obj


def test_theme_v2_tokens_dark_and_light():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    probe = _make_probe(engine)

    probe.setProperty("setDark", True)
    dark_bg = QColor(probe.property("background")).name()
    dark_card = QColor(probe.property("cardBg")).name()
    dark_accent = QColor(probe.property("accent")).name()
    grad_start_dark = QColor(probe.property("accentGradientStart")).name()
    grad_end_dark = QColor(probe.property("accentGradientEnd")).name()
    assert dark_bg == "#0a0b0e"
    assert dark_card == "#16171d"
    assert dark_accent == "#8b5cf6"
    assert probe.property("radiusCard") == 10

    probe.setProperty("setDark", False)
    light_bg = QColor(probe.property("background")).name()
    light_card = QColor(probe.property("cardBg")).name()
    light_accent = QColor(probe.property("accent")).name()
    grad_start_light = QColor(probe.property("accentGradientStart")).name()
    grad_end_light = QColor(probe.property("accentGradientEnd")).name()
    assert light_bg != dark_bg
    assert light_card == "#ffffff"
    assert light_accent == "#7c3aed"

    # The brand gradient is identical in both themes by design (spec
    # section 4/5) -- this is the regression gate for that requirement.
    assert grad_start_dark == grad_start_light == "#8b5cf6"
    assert grad_end_dark == grad_end_light == "#3b82f6"
