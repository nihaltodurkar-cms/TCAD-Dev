"""The viewport renders through Matplotlib's Agg backend into a QImage.
Tested headlessly by rendering and inspecting the resulting image and the
axis limits -- no window is ever shown."""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtGui import QGuiApplication

from gui.services import examples
from gui.services.result_store import SpecResultStore
from gui.visualization.mpl_canvas_item import MplCanvasItem


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def _canvas_with_structure(gapp):
    item = MplCanvasItem()
    item.setWidth(480)
    item.setHeight(320)
    item.setStore(SpecResultStore(examples.mosfet_example_spec()), "doping")
    return item


def test_renders_a_nonblank_image(gapp):
    item = _canvas_with_structure(gapp)
    img = item.renderToImage()
    assert not img.isNull()
    assert img.width() > 0 and img.height() > 0
    # a real plot is not one flat colour
    colours = {img.pixel(x, y)
               for x in range(0, img.width(), 37)
               for y in range(0, img.height(), 37)}
    assert len(colours) > 1


def test_fit_then_zoom_changes_limits(gapp):
    item = _canvas_with_structure(gapp)
    item.fit()
    x0, x1 = item.axisLimits()[0]
    item.zoom(0.5)                      # zoom in
    zx0, zx1 = item.axisLimits()[0]
    assert (zx1 - zx0) < (x1 - x0)
    item.resetView()
    rx0, rx1 = item.axisLimits()[0]
    assert abs((rx1 - rx0) - (x1 - x0)) < 1e-12 * max(1.0, abs(x1 - x0))


def test_pan_shifts_limits_without_resizing(gapp):
    item = _canvas_with_structure(gapp)
    item.fit()
    (x0, x1), (y0, y1) = item.axisLimits()
    item.pan(0.25, 0.0)
    (nx0, nx1), _ = item.axisLimits()
    assert abs((nx1 - nx0) - (x1 - x0)) < 1e-9 * (x1 - x0)   # same width
    assert abs(nx0 - x0) > 0                                  # but moved


def test_switching_field_is_safe_when_absent(gapp):
    item = _canvas_with_structure(gapp)
    item.setField("potential")          # not in a structure preview
    img = item.renderToImage()
    assert not img.isNull()             # renders a message, does not crash
