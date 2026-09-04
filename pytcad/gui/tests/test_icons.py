"""Headless checks for the v2 reskin's icon set: gui/qml/Icons.qml's
URL-building svg(name, color) and gui/services/icon_provider.py's
actual SVG-to-pixel rasterization.

Split into two halves matching the two-layer design (see
icon_provider.py's module docstring for why a Python-side provider
exists at all, not a plain data:image/svg+xml,... QML binding): the
QML half only needs to prove it builds the right URL string, and the
Python half proves the provider actually produces non-blank pixels --
the exact thing that silently failed before this design was adopted.
"""
import os
from urllib.parse import unquote

from PySide6.QtCore import QByteArray, QSize, QUrl
from PySide6.QtGui import QImage
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtSvg import QSvgRenderer

from gui.services.icon_provider import ICON_PATHS, IconImageProvider, build_svg

QML_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "qml"
)

EXPECTED_NAMES = [
    "project", "structure", "mesh", "process", "sweeps", "probeStation",
    "telemetry", "bands", "transient", "physicsLab", "builder",
    "run", "stop", "undo", "redo", "sun", "moon",
]

PROBE_QML = """
import QtQuick
QtObject {
    readonly property string urlProject: Icons.svg("project", "#8b5cf6")
    readonly property string urlRunFromString: Icons.svg("run", "#8b5cf6")
    readonly property string urlRunFromColorObject: Icons.svg("run", Theme.accent)
    readonly property string urlUnknown: Icons.svg("doesNotExist", "#8b5cf6")
    property var iconNames: Icons.names
}
"""


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


def test_qml_svg_builds_the_expected_image_provider_url():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    probe = _make_probe(engine)
    assert probe.property("urlProject") == "image://icons/project/8b5cf6"
    assert probe.property("urlRunFromString") == "image://icons/run/8b5cf6"


def test_qml_svg_accepts_a_real_color_object_not_just_a_string():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    probe = _make_probe(engine)
    # Theme.accent (dark, default) is "#8b5cf6" -- same hex either way.
    assert probe.property("urlRunFromColorObject") == "image://icons/run/8b5cf6"


def test_qml_svg_unknown_name_returns_empty_string():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    probe = _make_probe(engine)
    assert probe.property("urlUnknown") == ""


def test_qml_names_list_covers_every_expected_icon():
    engine = QQmlEngine()
    engine.addImportPath(QML_DIR)
    probe = _make_probe(engine)
    raw = probe.property("iconNames")
    names = raw.toVariant() if hasattr(raw, "toVariant") else list(raw)
    assert set(EXPECTED_NAMES) <= set(names)


def test_icon_provider_paths_cover_every_expected_icon():
    assert set(EXPECTED_NAMES) <= set(ICON_PATHS.keys())


def test_build_svg_produces_valid_markup_with_the_requested_color():
    doc = build_svg("run", "8b5cf6")
    assert doc is not None
    assert doc.count("<svg") == 1
    assert "#8b5cf6" in doc
    renderer = QSvgRenderer(QByteArray(doc.encode("utf-8")))
    assert renderer.isValid()


def test_build_svg_unknown_name_returns_none():
    assert build_svg("doesNotExist", "8b5cf6") is None


def test_icon_provider_renders_non_blank_pixels_for_every_expected_icon():
    # This is the actual regression gate for the bug that motivated this
    # whole design: a provider that reports success but paints nothing
    # would previously have looked "correct" (right size, right status)
    # while being visually blank. Check real pixel content instead.
    provider = IconImageProvider()
    for name in EXPECTED_NAMES:
        image = provider.requestImage(f"{name}/8b5cf6", QSize(), QSize(24, 24))
        assert isinstance(image, QImage)
        assert not image.isNull()
        assert image.width() == 24 and image.height() == 24
        nonzero_alpha = 0
        for y in range(image.height()):
            for x in range(image.width()):
                if image.pixelColor(x, y).alpha() > 0:
                    nonzero_alpha += 1
        assert nonzero_alpha > 0, f"icon '{name}' rendered fully transparent"


def test_icon_provider_unknown_name_returns_blank_but_valid_image():
    provider = IconImageProvider()
    image = provider.requestImage("doesNotExist/8b5cf6", QSize(), QSize(24, 24))
    assert isinstance(image, QImage)
    assert not image.isNull()
