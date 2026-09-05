"""Rasterizes PyTCAD's vector icon set (see gui/qml/Icons.qml) to pixmaps
via QSvgRenderer, served to QML through the standard image:// provider
mechanism (registered as "icons" in gui/app.py's create_engine()).

Why this exists, not a plain `Image { source: "data:image/svg+xml,..." }`
binding built entirely in QML: confirmed directly (2026-09-04, GUI visual
reskin Task 4) that under this machine's QtQuick rendering backend (no
working GPU/EGL driver -- "libEGL warning: ... driver (null)", "failed to
create dri2 screen" at startup), an `Image` sourced from a
`data:image/svg+xml,...` URI reports `status: Ready` and a correct
`paintedWidth`/`paintedHeight`, yet paints NOTHING -- pixel-sampled the
live window and found the background color unchanged across the icon's
entire bounding box. A `data:image/png;base64,...` source in the exact
same delegate position DID paint correctly, and `QSvgRenderer` driven
directly from Python (bypassing QML's Image/QtSvg-image-plugin path
entirely) also renders the same SVG markup correctly. So the SVG content,
the data-URI encoding, and the Image element's own state tracking are
all fine -- only the QtSvg *image plugin*'s texture upload inside this
specific QtQuick scene graph is broken. Rasterizing to a QImage/QPixmap
in Python via the same QSvgRenderer that's proven to work, and handing
QML a real QImage through this provider, sidesteps that broken code path
entirely while keeping Icons.qml's `Icons.svg(name, color)` call
signature unchanged for every consumer (Main.qml's sidebar tabs and
toolbar buttons).
"""
from PySide6.QtCore import QByteArray, QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer

# Mirrors gui/qml/Icons.qml's `_paths` -- kept in sync manually (QML and
# Python don't share source at runtime); gui/tests/test_icon_provider.py
# cross-checks both against the same expected name list so a future drift
# is caught as a test failure, not a silent missing icon.
ICON_PATHS = {
    "project":      "<path d='M4 10 L12 4 L20 10 L20 20 L4 20 Z'/><path d='M9 20 V14 H15 V20'/>",
    "structure":    "<rect x='4' y='4' width='7' height='7'/><rect x='13' y='4' width='7' height='7'/><rect x='4' y='13' width='7' height='7'/><rect x='13' y='13' width='7' height='7'/>",
    "mesh":         "<path d='M3 6 H21 M3 12 H21 M3 18 H21 M7 3 V21 M12 3 V21 M17 3 V21'/>",
    "process":      "<path d='M9 3 H15 V7 L18 12 V20 H6 V12 L9 7 Z'/>",
    "sweeps":       "<path d='M3 15 Q7 6 11 15 T19 15'/>",
    "probeStation": "<circle cx='12' cy='9' r='4'/><path d='M6 21 C6 16 18 16 18 21'/>",
    "telemetry":    "<path d='M3 17 L8 10 L12 14 L21 5'/><path d='M15 5 H21 V11'/>",
    "bands":        "<path d='M3 8 H21 M3 16 H21 M7 8 V16 M17 8 V16'/>",
    "transient":    "<circle cx='12' cy='12' r='8'/><path d='M12 7 V12 L16 14'/>",
    "ac":           "<path d='M3 12 Q6 4 9 12 T15 12 T21 12'/>",
    "physicsLab":   "<circle cx='12' cy='12' r='1.6' fill='currentColor' stroke='none'/><ellipse cx='12' cy='12' rx='9' ry='3.6'/><ellipse cx='12' cy='12' rx='9' ry='3.6' transform='rotate(60 12 12)'/><ellipse cx='12' cy='12' rx='9' ry='3.6' transform='rotate(120 12 12)'/>",
    "builder":      "<path d='M14 3 L21 10 L10 21 L3 21 L3 14 Z'/>",
    "run":          "<path d='M6 4 L20 12 L6 20 Z' fill='currentColor' stroke='none'/>",
    "stop":         "<rect x='6' y='6' width='12' height='12' fill='currentColor' stroke='none'/>",
    "undo":         "<path d='M8 8 H15 A5 5 0 1 1 11 18'/><path d='M8 8 L12 4 M8 8 L12 12'/>",
    "redo":         "<path d='M16 8 H9 A5 5 0 1 0 13 18'/><path d='M16 8 L12 4 M16 8 L12 12'/>",
    "sun":          "<circle cx='12' cy='12' r='4'/><path d='M12 2 V5 M12 19 V22 M2 12 H5 M19 12 H22 M4.9 4.9 L7 7 M17 17 L19.1 19.1 M19.1 4.9 L17 7 M7 17 L4.9 19.1'/>",
    "moon":         "<path d='M20 14.5 A8 8 0 1 1 9.5 4 A6.2 6.2 0 0 0 20 14.5 Z' fill='currentColor' stroke='none'/>",
}

DEFAULT_SIZE = 24


def build_svg(name: str, hex_color: str) -> str | None:
    """Returns the SVG document for `name` colored `hex_color` ("RRGGBB",
    no '#'), or None if `name` isn't registered."""
    inner = ICON_PATHS.get(name)
    if inner is None:
        return None
    css = "#" + hex_color
    colored = inner.replace("currentColor", css)
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
        f"fill='none' stroke='{css}' stroke-width='1.8' "
        "stroke-linecap='round' stroke-linejoin='round'>"
        f"{colored}</svg>"
    )


class IconImageProvider(QQuickImageProvider):
    """Registered as engine.addImageProvider("icons", ...) -- reached
    from QML as image://icons/<id>, where <id> is "<name>/<rrggbb>"
    (built by Icons.qml's svg() function)."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, id: str, size: QSize, requestedSize: QSize) -> QImage:
        name, _, hex_color = id.partition("/")
        svg_doc = build_svg(name, hex_color or "000000")
        target = DEFAULT_SIZE
        if requestedSize.width() > 0 and requestedSize.height() > 0:
            target = max(requestedSize.width(), requestedSize.height())

        image = QImage(target, target, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0)
        if svg_doc is not None:
            renderer = QSvgRenderer(QByteArray(svg_doc.encode("utf-8")))
            if renderer.isValid():
                painter = QPainter(image)
                renderer.render(painter)
                painter.end()
        size.setWidth(target)
        size.setHeight(target)
        return image
