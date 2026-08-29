"""v0.4 "series" viewport mode: sweep curves rendered through the same
Agg-into-QImage path as every other mode.

The data source is the ResultStore layer's SweepResult (Task 3), which
already guarantees non-converged points arrive as NaN -- this file pins
that those NaNs survive into the rendered artist (visible line gap,
never fabricated data) and that log scaling, channel switching, and fit()
behave without crashing on awkward real-world inputs (zero current at
V=0, negative currents, all-invalid curves).
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtGui import QGuiApplication

from gui.services.result_store import SweepResult
from gui.visualization.mpl_canvas_item import MplCanvasItem


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def _sweep_result(converged=None, currents=None):
    v = np.array([0.0, 0.2, 0.4, 0.6])
    if currents is None:
        # diode-like exponential growth, includes exact zero at V=0
        currents = {"drain": np.array([0.0, 1e-7, 2e-5, 1e-3])}
    if converged is None:
        converged = [True] * len(v)
    chans = {k: np.array(vals, dtype=float) for k, vals in currents.items()}
    for vals in chans.values():
        vals = None          # noqa -- clarity only; NaN handled by caller
    return SweepResult(
        contact="drain",
        meta={"contact": "drain", "start": 0.0, "stop": 0.6,
              "step": 0.2, "dimensionality": 2},
        voltages=v,
        converged=np.asarray(converged, dtype=bool),
        channels=chans,
        unit="A/cm",
    )


def _canvas(gapp, sweep, mode="series"):
    item = MplCanvasItem()
    item.setWidth(480)
    item.setHeight(320)
    item.setMode(mode)
    item.setSweepSource(sweep)
    return item


def _colour_count(img):
    return len({img.pixel(x, y)
                for x in range(0, img.width(), 31)
                for y in range(0, img.height(), 31)})


# ----------------------------------------------------------------------
#  basic rendering
# ----------------------------------------------------------------------
def test_series_mode_renders_nonblank_image(gapp):
    item = _canvas(gapp, _sweep_result())
    img = item.renderToImage()
    assert not img.isNull()
    assert _colour_count(img) > 1


def test_fit_spans_the_voltage_range(gapp):
    item = _canvas(gapp, _sweep_result())
    (x0, x1), ylim = item.axisLimits()
    assert (x0, x1) == pytest.approx((0.0, 0.6))
    assert ylim is None            # y autoscales to the data


def test_log_scale_renders_with_zero_and_negative_currents(gapp):
    """Real devices read 0 A at V=0 and reverse sign depending on the
    contact convention.  Log mode must drop such points honestly
    (semilogy shows positives only) rather than crash or fabricate."""
    sw = _sweep_result(currents={"drain": [0.0, -1e-9, 2e-5, 1e-3]})
    item = _canvas(gapp, sw)
    item.logScale = True
    img = item.renderToImage()
    assert not img.isNull()
    assert _colour_count(img) > 1


# ----------------------------------------------------------------------
#  non-converged points stay visibly broken, never fabricated
# ----------------------------------------------------------------------
def test_nan_points_survive_into_the_rendered_artist(gapp):
    """Point 2 did not converge: its value must reach the plot as NaN
    (a gap in the line), not as an interpolated or substituted number."""
    conv = [True, True, False, True]
    sw = _sweep_result(
        converged=conv,
        currents={"drain": [1e-7, 1e-5, np.nan, 1e-3]})
    item = _canvas(gapp, sw)

    fig = item._build_figure(480, 320)
    lines = fig.axes[0].get_lines()
    assert lines, "series mode drew no curve"
    ydata = np.asarray(lines[0].get_ydata(), dtype=float)
    assert np.isnan(ydata).sum() == 1


def test_all_invalid_curve_still_renders_safely(gapp):
    sw = _sweep_result(converged=[False] * 4,
                       currents={"drain": [np.nan] * 4})
    item = _canvas(gapp, sw)
    img = item.renderToImage()
    assert not img.isNull()


# ----------------------------------------------------------------------
#  channel selection
# ----------------------------------------------------------------------
def test_available_channels_and_switching(gapp):
    sw = _sweep_result(currents={
        "drain": [1e-7, 1e-5, 1e-3, 1e-1],
        "source": [-1e-7, -1e-5, -1e-3, -1e-1]})
    item = _canvas(gapp, sw)
    assert item.availableSweepChannels() == ["drain", "source"]
    item.setSweepChannel("source")
    fig = item._build_figure(480, 320)
    label = fig.axes[0].get_ylabel()
    assert "source" in label


def test_unknown_channel_is_safe(gapp):
    item = _canvas(gapp, _sweep_result())
    item.setSweepChannel("base")       # not a channel
    img = item.renderToImage()
    assert not img.isNull()            # message frame, no crash


def test_no_sweep_source_falls_back_without_crash(gapp):
    item = MplCanvasItem()
    item.setWidth(320)
    item.setHeight(240)
    item.setMode("series")
    img = item.renderToImage()
    assert not img.isNull()
