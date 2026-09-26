"""Viewport quick fixes (2026-09-25), found by measuring MplCanvasItem:

1. Hover readout: the QML overlay Label bound to `canvas.readout` never
   refreshed on hover (the property's NOTIFY was viewChanged, which
   hover never emits), while every hover that changed the text called
   update() -- a full matplotlib rebuild (37-105 ms per mouse move) for
   pixels identical to what was already on screen.
2. The pan/zoom fast path re-applied self._ylim as (lo, hi), dropping
   the inverted y-axis every 2D map draws with -- the map flipped
   upside down on the first pan or zoom.
3. The fast-path flag was never cleared by a fast-path paint or by a
   content change, so pan -> setField()/setMode()/theme kept showing
   the OLD figure.

Headless, same run_job -> NpzResultStore -> renderToImage() pattern as
test_mpl_canvas_hover_m51.py.
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtQml import QQmlComponent, QQmlEngine, qmlRegisterType
from PySide6.QtWidgets import QApplication

from gui.services import examples
from gui.services.result_store import NpzResultStore
from gui.services.solver_runner import run_job
from gui.visualization.mpl_canvas_item import MplCanvasItem


@pytest.fixture(scope="module")
def gapp():
    yield QApplication.instance() or QApplication([])


def _solve(tmp_path_factory, name, spec):
    d = tmp_path_factory.mktemp(name)
    job, out = str(d / "job.json"), str(d / "out.npz")
    with open(job, "w") as fh:
        json.dump(spec.to_dict(), fh)
    run_job(job, out)
    return NpzResultStore(out)


@pytest.fixture(scope="module")
def store_1d(tmp_path_factory):
    return _solve(tmp_path_factory, "d1", examples.diode_1d_example_spec())


@pytest.fixture(scope="module")
def store_2d(tmp_path_factory):
    return _solve(tmp_path_factory, "r2", examples.resistor_2d_example_spec())


def _canvas(store, field="doping", mode="doping"):
    item = MplCanvasItem()
    item.setWidth(600)
    item.setHeight(400)
    item.setMode(mode)
    item.setStore(store, field)
    item.renderToImage()
    return item


def _hover_px_on_curve(item):
    """Pixel coords of a real plotted 1D sample (hoverAt snaps within 8%
    of the span, so an arbitrary pixel can legitimately miss)."""
    xs, ys, _ = item._series[0]
    k = len(xs) // 3
    dx, dy = item._ax.transData.transform((float(xs[k]), float(ys[k])))
    fig_h = item._fig.get_figheight() * item._fig.dpi
    return float(dx), float(fig_h - dy)


def _colorbar_label(item):
    return item._fig.axes[-1].get_ylabel()


def _other_field(store, field):
    return next(n for n in store.available_scalars() if n != field)


# -- 1. hover readout ---------------------------------------------------

def test_hover_readout_reaches_a_qml_binding(gapp, store_1d):
    """The real contract: ViewportPanel.qml's Label is bound to
    canvas.readout, so the binding itself must refresh on hover."""
    qmlRegisterType(MplCanvasItem, "PyTCAD", 1, 0, "MplCanvas")
    engine = QQmlEngine()
    comp = QQmlComponent(engine)
    comp.setData(b"import QtQuick\nimport PyTCAD 1.0\n"
                 b"Item { width: 600; height: 400\n"
                 b"  property string shown: c.readout\n"
                 b"  MplCanvas { id: c; anchors.fill: parent } }",
                 "probe.qml")
    root = comp.create()
    assert root is not None, comp.errorString()
    item = root.findChildren(MplCanvasItem)[0]
    item.setMode("doping")
    item.setStore(store_1d, "doping")
    item.renderToImage()

    item.hoverAt(*_hover_px_on_curve(item))
    gapp.processEvents()
    assert item.readout != ""
    assert root.property("shown") == item.readout

    item.clearReadout()
    gapp.processEvents()
    assert root.property("shown") == ""
    del root, comp, engine


def test_hover_and_clear_never_repaint(gapp, store_2d):
    item = _canvas(store_2d)
    repaints, notes = [], []
    item.update = lambda *a: repaints.append(a)
    item.readoutChanged.connect(lambda: notes.append(1))
    w, h = item.width(), item.height()
    for f in (0.3, 0.4, 0.5, 0.6, 0.7):
        item.hoverAt(f * w, 0.5 * h)
    item.clearReadout()
    item.hoverAt(-50.0, -50.0)          # off the plot: clears again
    assert notes, "hovering over the 2D map must change the readout"
    assert repaints == [], "a readout change is QML's job, never a repaint"


def test_unchanged_readout_does_not_notify(gapp, store_2d):
    item = _canvas(store_2d)
    item.hoverAt(0.5 * item.width(), 0.5 * item.height())
    notes = []
    item.readoutChanged.connect(lambda: notes.append(1))
    item.hoverAt(0.5 * item.width(), 0.5 * item.height())
    assert notes == []


# -- 2. 2D orientation across the fast path -----------------------------

def test_2d_map_keeps_its_inverted_y_axis_across_pan_and_zoom(gapp, store_2d):
    item = _canvas(store_2d)
    assert item._ax.yaxis_inverted(), "2D maps draw y=0 (surface) at top"
    full_ylim = item._ax.get_ylim()

    fig = item._fig
    item.pan(0.0, 0.0)
    item.renderToImage()
    assert item._fig is fig, "precondition: the fast path actually ran"
    assert item._ax.yaxis_inverted()
    assert item._ax.get_ylim() == pytest.approx(full_ylim)

    item.zoom(0.8)
    item.renderToImage()
    assert item._fig is fig
    assert item._ax.yaxis_inverted()
    fast = item._ax.get_ylim()
    item.setField("doping")             # force a full rebuild, same limits
    item.renderToImage()
    assert item._fig is not fig
    assert item._ax.get_ylim() == pytest.approx(fast), (
        "the fast path must show exactly what a full rebuild would")


# -- 3. content changes after a pan/zoom --------------------------------

def test_set_field_after_a_pan_shows_the_new_field(gapp, store_2d):
    item = _canvas(store_2d)
    item.pan(0.02, 0.0)
    item.renderToImage()
    other = _other_field(store_2d, "doping")
    item.setField(other)
    item.renderToImage()
    assert other in _colorbar_label(item)


def test_content_change_between_pan_and_paint_rebuilds(gapp, store_2d):
    """pan() and setField() in the same frame (one coalesced paint)."""
    item = _canvas(store_2d)
    fig = item._fig
    item.pan(0.02, 0.0)
    other = _other_field(store_2d, "doping")
    item.setField(other)
    item.renderToImage()
    assert item._fig is not fig
    assert other in _colorbar_label(item)


@pytest.mark.parametrize("change", [
    lambda it: it.setMode("bands"),
    lambda it: setattr(it, "logScale", True),
    lambda it: setattr(it, "contours", True),
    lambda it: setattr(it, "meshOverlay", True),
    lambda it: it.resetView(),
], ids=["mode", "log", "contours", "mesh", "reset"])  # "theme": no theme switch since 2026-09-26
def test_every_content_setter_invalidates_the_fast_path(gapp, store_2d, change):
    item = _canvas(store_2d)
    item.pan(0.02, 0.0)
    assert item._skip_rebuild is True
    change(item)
    assert item._skip_rebuild is False


def test_fast_path_flag_is_one_shot(gapp, store_2d):
    item = _canvas(store_2d)
    fig = item._fig
    item.pan(0.02, 0.0)
    item.renderToImage()
    assert item._fig is fig
    assert item._skip_rebuild is False
    item.renderToImage()                # e.g. a Qt expose repaint
    assert item._fig is not fig
