"""M51 (ARCHITECTURE.md sec 8 "STANDING OPEN ITEMS"): hover-to-inspect
for 2D field maps / Structure / Mesh modes, and the mesh-overlay toggle
-- the concrete gap identified there (pan/zoom already existed via
ViewportPanel.qml's MouseArea; hoverAt() only ever populated a readout
for 1D curve modes before this).

Headless, same Agg-render-then-inspect pattern as test_mpl_canvas_item.py:
call _build_figure() directly (its side effects populate the same
self._ax/self._fig/self._field_grid/etc. state a real paint() would),
then derive the exact pixel coordinates hoverAt() expects by round-
tripping a known DATA point through the live Axes transform -- the same
transform hoverAt() itself inverts -- rather than guessing pixel values.
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtGui import QGuiApplication

from gui.services import examples
from gui.services.result_store import NpzResultStore, SpecResultStore
from gui.services.solver_runner import run_job
from gui.visualization.mpl_canvas_item import MplCanvasItem


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


@pytest.fixture()
def resistor_2d_store(tmp_path):
    """A uniformly-doped 2D bar (80x20 nodes, doping == 1e17 cm^-3
    EVERYWHERE) -- deterministic hover-value checks that don't depend on
    which exact node the cursor snaps to."""
    spec = examples.resistor_2d_example_spec()
    job_path = str(tmp_path / "job.json")
    out_path = str(tmp_path / "out.npz")
    with open(job_path, "w") as fh:
        json.dump(spec.to_dict(), fh)
    run_job(job_path, out_path)
    return NpzResultStore(out_path)


def _px_for_data_point(item, data_x, data_y):
    """The exact (x_px, y_px) hoverAt() would need to land on this DATA
    point -- built by round-tripping through the SAME ax.transData
    forward transform hoverAt() itself inverts, and the same
    figure-height flip its own docstring documents (Qt top-left origin
    vs. matplotlib bottom-left display space)."""
    ax = item._ax
    fig = item._fig
    disp_x, disp_y = ax.transData.transform((data_x, data_y))
    fig_h_px = fig.get_figheight() * fig.dpi
    return float(disp_x), float(fig_h_px - disp_y)


# -- 2D field-map hover (doping/bands/recombination) ---------------------

def test_hover_on_2d_field_map_reports_nearest_node_value(gapp, resistor_2d_store):
    item = MplCanvasItem()
    item.setWidth(480)
    item.setHeight(320)
    item.setStore(resistor_2d_store, "doping")
    item.setMode("doping")
    item._build_figure(480, 320)
    assert item._field_grid is not None

    x, y, values, label, unit = item._field_grid
    mid_x, mid_y = float(x[len(x) // 2]), float(y[len(y) // 2])
    px, py = _px_for_data_point(item, mid_x, mid_y)
    item.hoverAt(px, py)

    assert item.readout != ""
    assert label in item.readout
    # Uniformly doped: 1e17 cm^-3 everywhere, so the reported value is
    # exact regardless of which node the cursor actually snapped to.
    assert "1.000e+17" in item.readout or "1.00e+17" in item.readout.replace("+017", "+17")


def test_hover_on_2d_field_map_reports_raw_value_even_with_log_scale_on(
        gapp, resistor_2d_store):
    """The log-scale toggle changes what the COLORMAP shows, never what
    a reader is told the physical value at that node actually is (see
    _hover_field_grid's own docstring)."""
    item = MplCanvasItem()
    item.setWidth(480)
    item.setHeight(320)
    item.setStore(resistor_2d_store, "doping")
    item.setMode("doping")
    item.logScale = True
    item._build_figure(480, 320)

    x, y, values, label, unit = item._field_grid
    # values must be the RAW field, not log10 -- a log10 of 1e17 (~17)
    # would be wildly different from the raw value and instantly wrong.
    assert np.allclose(values, 1e17)

    px, py = _px_for_data_point(item, float(x[0]), float(y[0]))
    item.hoverAt(px, py)
    assert "1.00" in item.readout and "e+17" in item.readout.lower()


def test_hover_outside_field_bounds_clears_readout(gapp, resistor_2d_store):
    item = MplCanvasItem()
    item.setWidth(480)
    item.setHeight(320)
    item.setStore(resistor_2d_store, "doping")
    item.setMode("doping")
    item._build_figure(480, 320)
    x, y, *_ = item._field_grid

    # Well inside first, to prove the readout actually gets set at all...
    px_in, py_in = _px_for_data_point(item, float(x[len(x) // 2]), float(y[len(y) // 2]))
    item.hoverAt(px_in, py_in)
    assert item.readout != ""

    # ...then a point far outside the data bounds must clear it.
    px_out, py_out = _px_for_data_point(item, float(x.max()) + 1000.0, float(y.max()) + 1000.0)
    item.hoverAt(px_out, py_out)
    assert item.readout == ""


# -- Structure mode hover -------------------------------------------------

def test_hover_on_structure_mode_reports_the_region_under_the_cursor(gapp):
    structure, mesh_model = examples.STRUCTURE_EXAMPLES["mosfet_2d_structure"]()
    item = MplCanvasItem()
    item.setWidth(480)
    item.setHeight(320)
    item.setMode("structure")
    item.setStructureSource(structure, mesh_model)
    item._build_figure(480, 320)
    assert item._ax is not None

    region = structure.regions[0]
    mid_x = (region.x_min + region.x_max) / 2 * 1e4
    mid_y = (region.y_min + region.y_max) / 2 * 1e4
    px, py = _px_for_data_point(item, mid_x, mid_y)
    item.hoverAt(px, py)

    assert region.name in item.readout
    assert ("n-type" in item.readout) or ("p-type" in item.readout)


def test_hover_on_structure_mode_outside_any_region_clears_readout(gapp):
    structure, mesh_model = examples.STRUCTURE_EXAMPLES["mosfet_2d_structure"]()
    item = MplCanvasItem()
    item.setWidth(480)
    item.setHeight(320)
    item.setMode("structure")
    item.setStructureSource(structure, mesh_model)
    item._build_figure(480, 320)

    # Just past the device's own far edge -- guaranteed outside every region.
    far_x = structure.width_cm * 1e4 + 1000.0
    far_y = structure.height_cm * 1e4 + 1000.0
    px, py = _px_for_data_point(item, far_x, far_y)
    item.hoverAt(px, py)
    assert item.readout == ""


# -- Mesh mode hover --------------------------------------------------------

def test_hover_on_mesh_mode_reports_node_index_and_local_spacing(gapp):
    structure, mesh_model = examples.STRUCTURE_EXAMPLES["mosfet_2d_structure"]()
    item = MplCanvasItem()
    item.setWidth(480)
    item.setHeight(320)
    item.setMode("mesh")
    item.setStructureSource(structure, mesh_model)
    item._build_figure(480, 320)
    assert item._mesh_axes_um is not None

    x, y = item._mesh_axes_um
    px, py = _px_for_data_point(item, float(x[2]), float(y[2]))
    item.hoverAt(px, py)

    assert "node (" in item.readout
    assert "spacing" in item.readout


# -- Mesh-overlay toggle -----------------------------------------------------

def test_mesh_overlay_toggle_adds_grid_lines_on_a_2d_field_map(gapp, resistor_2d_store):
    item = MplCanvasItem()
    item.setWidth(480)
    item.setHeight(320)
    item.setStore(resistor_2d_store, "doping")
    item.setMode("doping")

    fig_off = item._build_figure(480, 320)
    n_lines_off = len(fig_off.axes[0].lines)

    item.meshOverlay = True
    fig_on = item._build_figure(480, 320)
    n_lines_on = len(fig_on.axes[0].lines)

    assert n_lines_on > n_lines_off


def test_mesh_overlay_default_is_off(gapp):
    item = MplCanvasItem()
    assert item.meshOverlay is False
