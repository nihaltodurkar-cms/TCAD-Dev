"""MplCanvasItem gains structure/mesh draw modes without breaking the
v0.1 doping/results modes it already had."""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtGui import QGuiApplication

from gui.services import examples
from gui.visualization.mpl_canvas_item import MplCanvasItem


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def _canvas(gapp):
    item = MplCanvasItem()
    item.setWidth(480)
    item.setHeight(320)
    structure, mesh = examples.mosfet_example_structure()
    item.setStructureSource(structure, mesh)
    return item


def test_structure_mode_renders_a_nonblank_image(gapp):
    item = _canvas(gapp)
    item.setMode("structure")
    img = item.renderToImage()
    assert not img.isNull()
    colours = {img.pixel(x, y) for x in range(0, img.width(), 41)
              for y in range(0, img.height(), 41)}
    assert len(colours) > 1


def test_mesh_mode_renders_grid_lines(gapp):
    item = _canvas(gapp)
    item.setMode("mesh")
    img = item.renderToImage()
    assert not img.isNull()
    colours = {img.pixel(x, y) for x in range(0, img.width(), 23)
              for y in range(0, img.height(), 23)}
    assert len(colours) > 1


def test_default_mode_is_backward_compatible(gapp):
    """Regression: v0.1 always used the doping/field mode with setStore --
    that path must still work with no mode set."""
    item = MplCanvasItem()
    item.setWidth(200); item.setHeight(200)
    from gui.services.result_store import SpecResultStore
    item.setStore(SpecResultStore(examples.mosfet_example_spec()), "doping")
    img = item.renderToImage()
    assert not img.isNull()
