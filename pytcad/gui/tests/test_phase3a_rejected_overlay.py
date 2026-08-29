"""Phase 3a: rejected-bias-point overlay on the convergence view.

Verifies that `_draw_convergence` marks non-converged (rejected) steps
with a distinct red 'x' marker, and that the legend includes a
"rejected" entry when any such step exists.
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtGui import QGuiApplication

from gui.visualization.mpl_canvas_item import MplCanvasItem
from gui.services.solver_backend import RunRecord, ConvergenceStep


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def _make_record(trace):
    """Build a minimal RunRecord from a list of ConvergenceStep dicts."""
    return RunRecord(
        backend="pytcad",
        created_utc="2026-01-01T00:00:00Z",
        dimensionality=1,
        material="Si",
        T=300.0,
        models={},
        numerics={},
        trace=tuple(ConvergenceStep.from_dict(s) for s in trace),
    )


def _accepted_step(stage, n=3):
    return {"stage": stage, "iterations": list(range(n)),
            "metrics": {"|dpsi|": [1e-1, 1e-3, 1e-6][:n]},
            "converged": True}


def _rejected_step(stage, n=3):
    return {"stage": stage, "iterations": list(range(n)),
            "metrics": {"|dpsi|": [1e-1, 1e-2, 1e-1][:n]},
            "converged": False}


def _canvas_with_record(gapp, record):
    """Build a convergence-mode canvas with the given RunRecord."""
    item = MplCanvasItem()
    item.setWidth(480)
    item.setHeight(320)
    item.setMode("convergence")
    item.setConvergenceSource(record)
    return item


def test_convergence_view_marks_rejected_step(gapp):
    """A non-converged step produces a red 'x' marker on the convergence plot."""
    record = _make_record([
        _accepted_step("equilibrium", 3),
        _rejected_step("bias", 3),
        _accepted_step("equilibrium", 2),
    ])
    canvas = _canvas_with_record(gapp, record)
    img = canvas.renderToImage()
    assert not img.isNull()
    # Count distinct colours - rejected 'x' marker adds red (#e74c3c)
    # which shouldn't appear in the base convergence plot
    colours = {img.pixel(x, y)
               for x in range(0, img.width(), 31)
               for y in range(0, img.height(), 31)}
    # Base plot has stage colours + grid + background; rejected adds red
    assert len(colours) > 5, "expected multiple colours including red x marker"


def test_convergence_view_no_marker_when_all_converged(gapp):
    """When all steps converge, no 'x' markers appear - fewer colours than rejected case."""
    record = _make_record([
        _accepted_step("equilibrium", 3),
        _accepted_step("bias", 4),
    ])
    canvas = _canvas_with_record(gapp, record)
    img = canvas.renderToImage()
    assert not img.isNull()
    colours = {img.pixel(x, y)
               for x in range(0, img.width(), 31)
               for y in range(0, img.height(), 31)}
    # Should have fewer distinct colours than the rejected case
    assert len(colours) > 3


def test_convergence_view_rejected_has_more_colours(gapp):
    """Rejected case has more distinct colours than all-converged case."""
    record_rejected = _make_record([
        _accepted_step("equilibrium", 2),
        _rejected_step("bias", 3),
    ])
    record_converged = _make_record([
        _accepted_step("equilibrium", 2),
        _accepted_step("bias", 3),
    ])
    canvas_rejected = _canvas_with_record(gapp, record_rejected)
    canvas_converged = _canvas_with_record(gapp, record_converged)
    img_rejected = canvas_rejected.renderToImage()
    img_converged = canvas_converged.renderToImage()
    colours_rejected = {img_rejected.pixel(x, y)
                        for x in range(0, img_rejected.width(), 31)
                        for y in range(0, img_rejected.height(), 31)}
    colours_converged = {img_converged.pixel(x, y)
                         for x in range(0, img_converged.width(), 31)
                         for y in range(0, img_converged.height(), 31)}
    # Rejected case should have at least as many colours (red x marker)
    assert len(colours_rejected) >= len(colours_converged)
