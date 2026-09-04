"""Performance pass (2026-09-04): regression tests for MplCanvasItem's
pan()/zoom() fast path.

cProfile on _build_figure() showed tight_layout() alone is ~69% of a
full render's cost (0.525s of 0.756s across 20 calls). pan()/zoom() no
longer trigger a full rebuild when reusable Axes exist from a prior
render (self._ax is not None, true only for the line-plot modes --
series/cv/cut/bands/recombination/1D-field -- via _remember_series();
2D colormap modes never set self._ax and are unaffected) at the same
pixel size: they re-window the existing Axes and redraw directly,
skipping _build_figure() (and its tight_layout() call) entirely.

These tests are the regression gate: the fast path must actually
engage when eligible, must be measurably faster, must fall back to a
full rebuild when NOT eligible (no prior render, or a resize since the
last one), and must still produce a correctly non-blank, correctly
re-windowed image either way.
"""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from gui.controllers.app_controller import AppController
from gui.visualization.mpl_canvas_item import MplCanvasItem


def _approx_tuple(t):
    return (pytest.approx(t[0]), pytest.approx(t[1]))


def _solved_1d_canvas():
    app = QApplication.instance() or QApplication([])
    ctl = AppController()
    ctl.loadExample("diode_1d")
    ctl.run()
    for _ in range(300):
        app.processEvents()
        time.sleep(0.01)
        if not ctl.busy:
            break
    assert ctl.hasResult, "solve did not complete in time for this test"

    item = MplCanvasItem()
    item.setWidth(900)
    item.setHeight(600)
    item.setMode("doping")
    item.setStore(ctl._store, ctl.currentField)
    return app, item


def test_fast_path_is_eligible_only_after_a_full_render_of_a_series_mode():
    app, item = _solved_1d_canvas()
    assert item._ax is None, "no render yet -- nothing to reuse"
    item.renderToImage()
    assert item._ax is not None, (
        "a solved 1D field view calls _remember_series() and must leave "
        "reusable Axes for the pan/zoom fast path"
    )


def test_pan_sets_the_fast_path_flag_and_skips_the_rebuild():
    app, item = _solved_1d_canvas()
    item.renderToImage()  # full build, populates self._ax
    fig_before = item._fig

    item.pan(0.05, 0.0)
    assert item._skip_rebuild is True
    item.renderToImage()

    assert item._fig is fig_before, (
        "the fast path must reuse the SAME Figure object, not rebuild one"
    )


def test_pan_fast_path_is_measurably_faster_than_a_full_rebuild():
    app, item = _solved_1d_canvas()
    item.renderToImage()

    t0 = time.perf_counter()
    for _ in range(10):
        item._skip_rebuild = False  # force the slow path each time
        item.renderToImage()
    full_ms = (time.perf_counter() - t0) / 10 * 1000

    t0 = time.perf_counter()
    for _ in range(10):
        item.pan(0.01, 0.0)
        item.renderToImage()
    fast_ms = (time.perf_counter() - t0) / 10 * 1000

    assert fast_ms < full_ms * 0.75, (
        f"expected the fast path to be meaningfully faster: "
        f"full={full_ms:.2f}ms fast={fast_ms:.2f}ms"
    )


def test_pan_fast_path_actually_shifts_the_visible_window():
    app, item = _solved_1d_canvas()
    item.renderToImage()
    xlim_before = item.axisLimits()[0]

    item.pan(0.1, 0.0)
    item.renderToImage()
    xlim_after = item.axisLimits()[0]

    assert xlim_after != xlim_before
    assert item._ax.get_xlim() == _approx_tuple(xlim_after)


def test_resize_between_renders_forces_a_full_rebuild_not_a_stale_fast_path():
    app, item = _solved_1d_canvas()
    item.renderToImage()
    fig_before = item._fig

    item.pan(0.01, 0.0)
    item.setWidth(700)  # resize before the next paint
    item.renderToImage()

    assert item._fig is not fig_before, (
        "a resize since the last full build must force a real rebuild, "
        "not reuse a Figure sized for the old width"
    )
    assert item._last_build_size == (700, 600)


def test_rendered_image_is_non_blank_after_a_fast_path_pan():
    app, item = _solved_1d_canvas()
    item.renderToImage()
    item.pan(0.02, 0.0)
    img = item.renderToImage()
    assert not img.isNull()
    assert img.width() > 0 and img.height() > 0
