"""Headless checks for Theme.qml's design-system tokens: ONE scheme,
black and white (the user's decision, 2026-09-26: "no modes, just black
and white"; data keeps its colours).

Loads the Theme singleton through a standalone QQmlComponent (not the
full Main.qml window) so this stays a cheap, independent regression gate.
Every colour token Theme.qml declares is read back from the running QML
engine, so a new token cannot slip past the greyscale rule.
"""
import os
import re

from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor
from PySide6.QtQml import QQmlComponent, QQmlEngine

QML_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "qml"
)
THEME_QML = os.path.join(QML_DIR, "Theme.qml")

# The only tokens allowed a hue: they carry meaning (state), not decoration.
STATUS = {"running", "runningBg", "warning", "warningBg", "error", "errorBg", "ok", "okBg"}


def _colour_token_names():
    text = open(THEME_QML, encoding="utf-8").read()
    return re.findall(r"^\s*(?:readonly\s+)?property\s+color\s+(\w+)\s*:", text, re.M)


def _probe(engine, names):
    body = "\n".join(f"    property color {n}: Theme.{n}" for n in names)
    component = QQmlComponent(engine)
    component.setData(f"import QtQuick\nQtObject {{\n{body}\n}}\n".encode("utf-8"),
                      QUrl.fromLocalFile(os.path.join(QML_DIR, "_theme_probe.qml")))
    obj = component.create()
    assert obj is not None, component.errorString()
    assert component.errorString() == ""
    # The QQmlComponent must outlive the object it created (its C++ object
    # is otherwise deleted with the component: "Internal C++ object already
    # deleted" on the next property access).
    obj._keepalive_component = component
    return obj


def _colours():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    names = _colour_token_names()
    probe = _probe(engine, names)
    out = {n: QColor(probe.property(n)) for n in names}
    out["_engine"] = engine  # keep alive
    return out


def test_theme_has_no_modes():
    text = open(THEME_QML, encoding="utf-8").read()
    assert not re.search(r"property\s+bool\s+dark\b", text), "Theme.qml has a dark/light switch again"
    assert "function toggle" not in text
    assert not re.search(r"\bdark\s*\?", text), "a token still depends on a dark flag"


def test_every_chrome_token_is_a_grey():
    colours = _colours()
    names = [n for n in colours if n != "_engine"]
    assert len(names) >= 30, f"the token parser found too little ({len(names)}): fix it, not the gate"
    assert STATUS <= set(names), f"status tokens missing: {STATUS - set(names)}"
    coloured = [f"{n}={c.name()}" for n in names if n not in STATUS
                for c in [colours[n]] if not (c.red() == c.green() == c.blue())]
    assert not coloured, f"chrome tokens with a hue (only status colours may have one): {coloured}"


def test_black_on_white():
    c = _colours()
    for n in ("background", "panel", "cardBg"):
        assert c[n].name() == "#ffffff", f"{n} {c[n].name()}"
        assert c[n].alpha() == 255, f"{n} is translucent: nothing is behind the panels any more"
    for n in ("text", "accent", "focus"):
        assert c[n].name() == "#000000", f"{n} {c[n].name()}"
    assert c["panel"].alpha() == c["panelAlt"].alpha() == c["chromeBg"].alpha() == 255
    assert c["error"].name() == "#c0392b" and c["ok"].name() == "#2e8b44"  # status keeps meaning


def test_card_radius_unchanged():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    component = QQmlComponent(engine)
    component.setData(b"import QtQuick\nQtObject { property int radiusCard: Theme.radiusCard }\n",
                      QUrl.fromLocalFile(os.path.join(QML_DIR, "_theme_probe.qml")))
    obj = component.create()
    assert obj is not None, component.errorString()
    assert obj.property("radiusCard") == 10
