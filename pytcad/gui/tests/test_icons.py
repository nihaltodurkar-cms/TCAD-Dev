"""Headless checks for Icons.qml's vector icon set (v2 reskin).

Same standalone-QQmlComponent technique as test_theme_tokens.py,
including the same component-lifetime fix (see that file's
_make_probe docstring for why it's needed).
"""
import os
from urllib.parse import unquote

from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine

QML_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "qml"
)

# Every icon name Main.qml's sidebar tabs and toolbar buttons use (Task
# 4/5 of the reskin plan) -- listed explicitly here, not read back from
# Icons.qml's own `names` property, so a future typo in Main.qml is
# caught by THIS list even before Main.qml is edited to use it.
EXPECTED_NAMES = [
    "project", "structure", "mesh", "process", "sweeps", "probeStation",
    "telemetry", "bands", "transient", "physicsLab", "builder",
    "run", "stop", "undo", "redo", "sun", "moon",
]

PROBE_QML = """
import QtQuick
QtObject {
    readonly property string uriProject: Icons.svg("project", "#8b5cf6")
    readonly property string uriStructure: Icons.svg("structure", "#8b5cf6")
    readonly property string uriMesh: Icons.svg("mesh", "#8b5cf6")
    readonly property string uriProcess: Icons.svg("process", "#8b5cf6")
    readonly property string uriSweeps: Icons.svg("sweeps", "#8b5cf6")
    readonly property string uriProbeStation: Icons.svg("probeStation", "#8b5cf6")
    readonly property string uriTelemetry: Icons.svg("telemetry", "#8b5cf6")
    readonly property string uriBands: Icons.svg("bands", "#8b5cf6")
    readonly property string uriTransient: Icons.svg("transient", "#8b5cf6")
    readonly property string uriPhysicsLab: Icons.svg("physicsLab", "#8b5cf6")
    readonly property string uriBuilder: Icons.svg("builder", "#8b5cf6")
    readonly property string uriRun: Icons.svg("run", "#8b5cf6")
    readonly property string uriStop: Icons.svg("stop", "#8b5cf6")
    readonly property string uriUndo: Icons.svg("undo", "#8b5cf6")
    readonly property string uriRedo: Icons.svg("redo", "#8b5cf6")
    readonly property string uriSun: Icons.svg("sun", "#8b5cf6")
    readonly property string uriMoon: Icons.svg("moon", "#8b5cf6")
    readonly property string uriUnknown: Icons.svg("doesNotExist", "#8b5cf6")
    // A real QML `color` value, not a string -- exercises the
    // object-vs-string branch inside Icons.svg().
    readonly property string uriFromColorObject: Icons.svg("run", Theme.accent)
    property var iconNames: Icons.names
}
"""

NAME_TO_PROPERTY = {
    "project": "uriProject", "structure": "uriStructure", "mesh": "uriMesh",
    "process": "uriProcess", "sweeps": "uriSweeps",
    "probeStation": "uriProbeStation", "telemetry": "uriTelemetry",
    "bands": "uriBands", "transient": "uriTransient",
    "physicsLab": "uriPhysicsLab", "builder": "uriBuilder",
    "run": "uriRun", "stop": "uriStop", "undo": "uriUndo",
    "redo": "uriRedo", "sun": "uriSun", "moon": "uriMoon",
}


def _make_probe(qml_engine):
    component = QQmlComponent(qml_engine)
    component.setData(
        PROBE_QML.encode("utf-8"),
        QUrl.fromLocalFile(os.path.join(QML_DIR, "_icons_probe.qml")),
    )
    obj = component.create()
    assert obj is not None, component.errorString()
    assert component.errorString() == ""
    # See test_theme_tokens.py's _make_probe: the component must
    # outlive the object it created.
    obj._keepalive_component = component
    return obj


def test_every_expected_icon_resolves_to_a_valid_svg_data_uri():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    probe = _make_probe(engine)

    for name in EXPECTED_NAMES:
        prop = NAME_TO_PROPERTY[name]
        uri = probe.property(prop)
        assert uri.startswith("data:image/svg+xml,"), (name, uri)
        payload = unquote(uri[len("data:image/svg+xml,"):])
        assert payload.count("<svg") == 1, (name, payload)
        # The '#' in "#8b5cf6" must survive the encoding round-trip --
        # an unescaped '#' inside a data: URI is a URL fragment
        # delimiter and would silently truncate the SVG.
        assert "#8b5cf6" in payload, (name, payload)


def test_unknown_icon_name_returns_empty_string():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    probe = _make_probe(engine)
    assert probe.property("uriUnknown") == ""


def test_color_object_argument_produces_valid_css_not_raw_argb_hex():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    probe = _make_probe(engine)
    uri = probe.property("uriFromColorObject")
    payload = unquote(uri[len("data:image/svg+xml,"):])
    # Qt's QML `color.toString()` yields "#AARRGGBB" (8 hex digits),
    # which is NOT valid SVG/CSS color syntax (CSS 8-digit hex is
    # RRGGBBAA, a different byte order) -- Icons.svg() must convert a
    # color OBJECT to an rgba(...) string instead of stringifying it
    # directly, or every icon colored from a Theme.* binding (not a
    # literal hex string) would silently render blank.
    assert "rgba(" in payload
    assert "#ff" not in payload.lower()


def test_names_list_covers_every_expected_icon():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    probe = _make_probe(engine)
    # `property var iconNames: Icons.names` crosses into Python as a
    # QJSValue wrapping the JS array, not a Python list directly --
    # .toVariant() does that conversion explicitly.
    raw = probe.property("iconNames")
    names = raw.toVariant() if hasattr(raw, "toVariant") else list(raw)
    assert set(EXPECTED_NAMES) <= set(names)
