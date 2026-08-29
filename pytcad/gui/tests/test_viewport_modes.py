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


def test_process_mode_renders_a_nonblank_multi_species_plot(gapp):
    """setMode("process") then setProcessSource(...) -- the real QML order --
    must render net doping plus each species' profile, not the "No project
    loaded" placeholder and not a single flat line."""
    import json
    import os
    import tempfile

    from gui.services.process_model import ProcessFlow, ProcessStep
    from gui.services.process_result_store import ProcessResultStore
    from gui.services.process_runner import run_flow

    flow = ProcessFlow(steps=[
        ProcessStep(id="sub", name="Substrate", operation="substrate",
                    parameters={"length_cm": 2e-4, "background_doping_cm3": -1e16,
                                "mesh": {"h_min_cm": 2e-8, "h_max_cm": 2e-6, "ratio": 1.15}}),
        ProcessStep(id="i1", name="Implant", operation="implant",
                    parameters={"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14}),
    ])
    tmp = tempfile.mkdtemp()
    flow_path = os.path.join(tmp, "f.json")
    manifest_path = os.path.join(tmp, "m.json")
    with open(flow_path, "w") as fh:
        json.dump(flow.to_dict(), fh)
    run_flow(flow_path, manifest_path)
    with open(manifest_path) as fh:
        manifest = json.load(fh)
    store = ProcessResultStore(manifest)

    item = MplCanvasItem()
    item.setWidth(480); item.setHeight(320)
    item.setMode("process")
    item.setProcessSource(store, "i1")
    assert item._mode == "process"
    img = item.renderToImage()
    assert not img.isNull()
    colours = {img.pixel(x, y) for x in range(0, img.width(), 41)
              for y in range(0, img.height(), 41)}
    assert len(colours) > 1


def test_setmode_before_setprocesssource_is_not_clobbered(gapp):
    """setProcessSource must not force self._mode to "process" -- mirrors
    the setStructureSource regression test above, guarding against the same
    class of bug (a setXSource() call silently overriding whatever mode
    setMode() had just set) recurring for the new process mode."""
    import json
    import os
    import tempfile

    from gui.services.process_model import ProcessFlow, ProcessStep
    from gui.services.process_result_store import ProcessResultStore
    from gui.services.process_runner import run_flow

    flow = ProcessFlow(steps=[
        ProcessStep(id="sub", name="Substrate", operation="substrate",
                    parameters={"length_cm": 2e-4, "background_doping_cm3": -1e16,
                                "mesh": {"h_min_cm": 2e-8, "h_max_cm": 2e-6, "ratio": 1.15}}),
        ProcessStep(id="i1", name="Implant", operation="implant",
                    parameters={"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14}),
    ])
    tmp = tempfile.mkdtemp()
    flow_path = os.path.join(tmp, "f.json")
    manifest_path = os.path.join(tmp, "m.json")
    with open(flow_path, "w") as fh:
        json.dump(flow.to_dict(), fh)
    run_flow(flow_path, manifest_path)
    with open(manifest_path) as fh:
        manifest = json.load(fh)
    store = ProcessResultStore(manifest)

    item = MplCanvasItem()
    item.setWidth(480); item.setHeight(320)
    item.setMode("mesh")
    item.setProcessSource(store, "i1")
    assert item._mode == "mesh"


def test_process_mode_y_axis_is_floored_against_gaussian_underflow(gapp):
    """Regression test for a Task 15 real-display finding: a Gaussian
    implant tail underflows to a subnormal float (~1e-312) far from its
    peak -- not a real concentration, just floating-point noise -- and
    _draw_process() had no y-axis floor, so matplotlib's semilogy
    autoscale stretched the axis down to include it. A real screenshot
    showed the axis running from ~1e33 to ~1e-311, squashing the
    physically meaningful 1e15-1e20 cm^-3 range into an unreadable sliver.
    This drives the same real flow and checks the rendered y-limits stay
    within a sane physical window."""
    import json
    import os
    import tempfile

    from gui.services.process_model import ProcessFlow, ProcessStep
    from gui.services.process_result_store import ProcessResultStore
    from gui.services.process_runner import run_flow

    flow = ProcessFlow(steps=[
        ProcessStep(id="sub", name="Substrate", operation="substrate",
                    parameters={"length_cm": 1e-3, "background_doping_cm3": 1e15,
                                "mesh": {"h_min_cm": 1e-7, "h_max_cm": 1e-5, "ratio": 1.2}}),
        ProcessStep(id="i1", name="Implant", operation="implant",
                    parameters={"species": "P", "energy_keV": 40.0, "dose_cm2": 2e14,
                                "tilt_deg": 7}),
        ProcessStep(id="a1", name="Anneal", operation="anneal",
                    parameters={"temperature_C": 1000.0, "time_s": 45.0}),
    ])
    tmp = tempfile.mkdtemp()
    flow_path = os.path.join(tmp, "f.json")
    manifest_path = os.path.join(tmp, "m.json")
    with open(flow_path, "w") as fh:
        json.dump(flow.to_dict(), fh)
    run_flow(flow_path, manifest_path)
    with open(manifest_path) as fh:
        manifest = json.load(fh)
    store = ProcessResultStore(manifest)

    item = MplCanvasItem()
    item.setWidth(480); item.setHeight(320)
    item.setMode("process")
    item.setProcessSource(store, "a1")
    img = item.renderToImage()
    assert not img.isNull()

    fig = item._build_figure(480, 320)
    ax = fig.axes[0]
    ymin, ymax = ax.get_ylim()
    # Real doping concentrations in this codebase never approach 1e25
    # cm^-3 (well above any physical dopant density) or fall below 1e0 --
    # anything outside that band is underflow noise, not signal.
    assert ymin >= 1.0, f"y-axis floor {ymin} lets underflow noise through"
    assert ymax <= 1e25, f"y-axis ceiling {ymax} is not physically sane"


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
