"""M9 plots slice (ARCHITECTURE.md roadmap): viewport observables fed
from workbench/analysis -- band diagrams, recombination maps, and the
first model on/off comparison runs.

Physics gates here are analytic, not cosmetic:
  - band_diagram() must match Device1D.band_diagram() on a REAL solved
    device (the parity contract the observables layer was founded on);
  - net recombination must vanish at equilibrium (np = nie^2) and be
    positive somewhere under forward bias in a solved diode.
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtCore import QMetaObject
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


@pytest.fixture(scope="module")
def solved_1d(tmp_path_factory):
    """A real solved 1D diode through the pytcad backend, as an npz."""
    from gui.services.device_spec import (
        ContactSpec, DeviceSpec, DopingSpec, MeshSpec,
    )
    from workbench.solvers.base import SolveRequest, get_backend
    x = np.linspace(0.0, 2e-4, 80)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
                  ContactSpec(name="right", kind="ohmic",
                              nodes={"i": [x.size - 1]}, V=0.0)],
        bias={"left": 0.3, "right": 0.0})
    job = str(tmp_path_factory.mktemp("m9") / "diode.json")
    out = str(tmp_path_factory.mktemp("m9") / "diode.npz")
    spec.to_json(job)
    get_backend("pytcad").run(SolveRequest(job_json_path=job,
                                           out_npz_path=out))
    return out


# -- observables -----------------------------------------------------------
def test_band_diagram_matches_the_core_bit_for_bit(solved_1d):
    from gui.services.result_store import NpzResultStore
    from workbench.analysis.observables import band_diagram
    store = NpzResultStore(solved_1d)
    psi = store.scalar_field("potential").values
    n = store.scalar_field("electron_density").values
    p = store.scalar_field("hole_density").values

    # the core reference: solve the same device natively and read its
    # own band diagram
    from pytcad import Device1D, Models
    spec_mesh_x = np.asarray(store.mesh_axes().axes["x"], dtype=float)
    doping = np.asarray(store.scalar_field("doping").values, dtype=float)
    dev = Device1D(spec_mesh_x, doping, T=300.0,
                   models=Models(bgn=True, auger=True, srh=True))
    dev.solve_equilibrium()
    dev.solve_bias([0.3, 0.0])
    Ec, Ev, EFn, EFp = dev.band_diagram()

    got = band_diagram(psi, n, p)
    for a, b in zip(got, (Ec, Ev, EFn, EFp)):
        assert np.allclose(a, b, atol=1e-9), \
            f"max |diff| = {np.max(np.abs(a - b)):.3g} eV"


def test_recombination_vanishes_at_equilibrium(solved_1d):
    from gui.services.result_store import NpzResultStore
    from workbench.analysis.observables import recombination_rate
    store = NpzResultStore(solved_1d)
    x = np.asarray(store.mesh_axes().axes["x"], dtype=float)
    doping = np.asarray(store.scalar_field("doping").values, dtype=float)
    psi_eq = None
    # equilibrium R == 0 is exact physics (np = nie^2): probe with the
    # equilibrium carrier densities reconstructed from psi at V=0 via a
    # fresh equilibrium solve
    from pytcad import Device1D, Models
    dev = Device1D(x, doping, T=300.0, models=Models(bgn=True))
    dev.solve_equilibrium()
    from workbench.analysis.observables import recombination_rate as rr
    R = rr(dev.n_cm3, dev.p_cm3, doping)
    # Scaled gate: under bias R reaches 1e15..1e25 cm^-3 s^-1, so the
    # Newton-convergence-level leakage (~1e-2 here) is numerical zero --
    # but only when measured against the SRH denominator scale, not an
    # arbitrary absolute.
    nie = dev.nie
    den_scale = np.max(nie**2 / (dev.tau_n + dev.tau_p))
    assert np.max(np.abs(R)) < 1e-10 * den_scale, \
        f"equilibrium R leaked beyond Newton noise: {np.max(np.abs(R))}"


def test_recombination_positive_under_forward_bias(solved_1d):
    from gui.services.result_store import NpzResultStore
    from workbench.analysis.observables import recombination_rate
    store = NpzResultStore(solved_1d)
    n = store.scalar_field("electron_density").values
    p = store.scalar_field("hole_density").values
    doping = np.asarray(store.scalar_field("doping").values, dtype=float)
    R = recombination_rate(n, p, doping)
    assert np.nanmax(R) > 0.0, "forward-biased diode must recombine somewhere"


# -- viewport modes ---------------------------------------------------------
def _canvas_with_store(gapp, solved):
    from gui.services.result_store import NpzResultStore
    from gui.visualization.mpl_canvas_item import MplCanvasItem
    item = MplCanvasItem()
    item.setWidth(480)
    item.setHeight(320)
    item.setStore(NpzResultStore(solved))
    return item


def test_bands_mode_renders_curves(gapp, solved_1d):
    item = _canvas_with_store(gapp, solved_1d)
    item.setMode("bands")
    img = item.renderToImage()
    assert not img.isNull()
    colours = {img.pixel(x, y) for x in range(0, img.width(), 23)
               for y in range(0, img.height(), 23)}
    assert len(colours) > 2, "band diagram rendered blank"


def test_recombination_mode_renders(gapp, solved_1d):
    item = _canvas_with_store(gapp, solved_1d)
    item.setMode("recombination")
    img = item.renderToImage()
    assert not img.isNull()
    colours = {img.pixel(x, y) for x in range(0, img.width(), 23)
               for y in range(0, img.height(), 23)}
    assert len(colours) > 2, "recombination plot rendered blank"


def test_mode_selector_offers_the_new_modes(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    selector = root.findChild(object, "viewModeSelector")
    model = [str(selector.property("model").value(i))
             if hasattr(selector.property("model"), "value")
             else str(list(selector.property("model"))[i])
             for i in range(len(list(selector.property("model"))))]
    assert "Bands" in model and "Recombination" in model


# -- model on/off comparison runs ------------------------------------------
def test_comparison_run_produces_an_overlay_source(gapp, tmp_path):
    """Arm a sweep, run the device normally, then fire the comparison:
    the controller must execute a SECOND solve with every catalog model
    disabled -- without touching the primary store -- and expose its
    sweep as the overlay source."""
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]

    controller.loadExample("pn_diode") if "pn_diode" in \
        __import__("gui.services.examples", fromlist=["EXAMPLES"]).EXAMPLES \
        else None
    if controller.spec is None:
        controller.loadStructureExample("mosfet_2d_structure")
    controller.setSweepConfig(_sweep_contact(controller), 0.0, 0.5, 0.25)

    controller.run()
    # run() emits resultChanged at START too (clear-on-start), so the
    # honest completion signal is busy going False again.
    deadline = 600   # ~60 s of event-loop pumping, generous
    while controller.busy and deadline:
        gapp.processEvents()
        gapp.thread().msleep(100)
        deadline -= 1
    assert not controller.busy, "primary run never finished"

    done = []
    controller.comparisonChanged.connect(lambda: done.append(1))
    controller.runModelComparison()
    deadline = 400
    while not done and deadline:
        gapp.processEvents()
        gapp.thread().msleep(100)
        deadline -= 1
    assert done, "comparison run never finished"

    overlay = controller.comparisonSweepForQml
    assert overlay is not None, "comparison produced no overlay sweep"
    assert list(overlay.channels)


def _sweep_contact(controller):
    names = controller.sweepContactNames
    return names[0] if names else ""


# -- 2D maps: Bands/Recombination must render real 2D fields ---------------
@pytest.fixture(scope="module")
def solved_2d(tmp_path_factory):
    """A small solved 2D MOSFET through the pytcad backend."""
    from gui.services import examples
    from gui.services.solver_backend import validate_result
    from workbench.solvers.base import SolveRequest, get_backend
    spec = examples.mosfet_example_spec()
    d = tmp_path_factory.mktemp("m9_2d")
    job, out = str(d / "m.json"), str(d / "m.npz")
    spec.to_json(job)
    get_backend("pytcad").run(SolveRequest(job_json_path=job,
                                           out_npz_path=out))
    validate_result(out)
    return out


def test_bands_mode_renders_2d_map(solved_2d):
    from gui.services.result_store import NpzResultStore
    from gui.visualization.mpl_canvas_item import MplCanvasItem
    item = MplCanvasItem()
    item.setWidth(480); item.setHeight(320)
    item.setStore(NpzResultStore(solved_2d))
    item.setMode("bands")
    img = item.renderToImage()
    assert not img.isNull()
    colours = {img.pixel(x, y) for x in range(0, img.width(), 17)
               for y in range(0, img.height(), 17)}
    assert len(colours) > 4, "2D band map rendered blank"


def test_recombination_mode_renders_2d_map(solved_2d):
    from gui.services.result_store import NpzResultStore
    from gui.visualization.mpl_canvas_item import MplCanvasItem
    item = MplCanvasItem()
    item.setWidth(480); item.setHeight(320)
    item.setStore(NpzResultStore(solved_2d))
    item.setMode("recombination")
    img = item.renderToImage()
    assert not img.isNull()
    colours = {img.pixel(x, y) for x in range(0, img.width(), 17)
               for y in range(0, img.height(), 17)}
    assert len(colours) > 4, "2D recombination map rendered blank"
