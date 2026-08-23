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


def test_setmode_before_setstructuresource_is_not_clobbered(gapp):
    """QML calls setMode(mode) then setStructureSource(...), in that order
    (tests here call the reverse) -- setStructureSource must not force the
    mode back to "structure", or every non-structure mode silently renders
    the structure diagram instead (this was a real, previously-shipped bug:
    the Mesh viewport rendered the structure diagram, not a mesh grid)."""
    item = MplCanvasItem()
    item.setWidth(480); item.setHeight(320)
    structure, mesh = examples.mosfet_example_structure()
    item.setMode("mesh")
    item.setStructureSource(structure, mesh)
    assert item._mode == "mesh"


def test_doping_mode_renders_structure_preview_before_a_solve(gapp):
    """Loading a structure and switching to doping mode, with no solve and
    no ResultStore, must rasterize the structure's own regions rather than
    showing the "No project loaded" placeholder."""
    item = MplCanvasItem()
    item.setWidth(480); item.setHeight(320)
    structure, mesh = examples.mosfet_example_structure()
    item.setMode("doping")
    item.setStructureSource(structure, mesh)
    assert item._store is None
    img = item.renderToImage()
    assert not img.isNull()
    colours = {img.pixel(x, y) for x in range(0, img.width(), 41)
              for y in range(0, img.height(), 41)}
    assert len(colours) > 1


def test_doping_mode_prefers_resultstore_once_a_solve_exists(gapp):
    """After a solve, doping mode must keep using the ResultStore, not fall
    back to the pre-solve structure-rasterizing preview."""
    from gui.services.result_store import SpecResultStore
    item = MplCanvasItem()
    item.setWidth(480); item.setHeight(320)
    structure, mesh = examples.mosfet_example_structure()
    item.setMode("doping")
    item.setStructureSource(structure, mesh)
    item.setStore(SpecResultStore(examples.mosfet_example_spec()), "doping")
    assert item._store is not None
    img = item.renderToImage()
    assert not img.isNull()
