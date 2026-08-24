"""v0.4 QML surface: SweepPanel + "series" viewport mode.

Same headless pattern as test_structure_panels.py / test_process_handoff.py:
the real engine is created via create_engine(), panels are found by
objectName, and QML objects are driven through their own properties and
QMetaObject -- no reimplementation of panel logic in Python.

The last test runs a REAL subprocess sweep end-to-end through the QML
panel wiring (config fields -> apply button -> controller.run() ->
JobRunner -> solver_runner -> ResultStore -> viewport series render),
because a Python-only test cannot prove the QML handlers are wired.
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from PySide6.QtCore import QEventLoop, QTimer, QMetaObject, Q_ARG
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def _fresh(gapp):
    # keep the engine alive for the whole test -- returning only the root
    # lets Python GC the QQmlEngine and delete the C++ objects under us
    engine, controller = gui_app.create_engine(gapp)
    return engine, engine.rootObjects()[0], controller


# ----------------------------------------------------------------------
#  panel presence and bindings
# ----------------------------------------------------------------------
def test_engine_loads_with_sweep_panel(gapp):
    engine, root, _ = _fresh(gapp)
    assert root.findChild(object, "sweepPanel") is not None, \
        "missing sweepPanel"


def test_sweep_panel_children_present(gapp):
    engine, root, _ = _fresh(gapp)
    for name in ("sweepContactBox", "sweepStartField", "sweepStopField",
                 "sweepStepField", "applySweepButton", "clearSweepButton",
                 "sweepStatusLabel"):
        assert root.findChild(object, name) is not None, f"missing {name}"


def test_contact_box_populates_from_controller(gapp):
    engine, root, controller = _fresh(gapp)
    controller.loadStructureExample("mosfet_2d_structure")
    box = root.findChild(object, "sweepContactBox")
    model = list(box.property("model"))
    for expected in ("source", "drain", "body", "gate"):
        assert expected in model


def test_apply_button_wires_to_controller(gapp):
    engine, root, controller = _fresh(gapp)
    controller.loadStructureExample("mosfet_2d_structure")

    box = root.findChild(object, "sweepContactBox")
    idx = list(box.property("model")).index("drain")
    box.setProperty("currentIndex", idx)
    for name, value in (("sweepStartField", "0.0"), ("sweepStopField", "0.6"),
                        ("sweepStepField", "0.2")):
        root.findChild(object, name).setProperty("text", value)

    assert controller.hasSweepConfig is False
    btn = root.findChild(object, "applySweepButton")
    QMetaObject.invokeMethod(btn, "clicked")
    assert controller.hasSweepConfig is True
    cfg = controller._sweep_config
    assert (cfg.contact, cfg.start, cfg.stop, cfg.step) == ("drain", 0.0, 0.6, 0.2)


def test_clear_button_and_status_label_reflect_state(gapp):
    engine, root, controller = _fresh(gapp)
    controller.loadStructureExample("mosfet_2d_structure")
    label = root.findChild(object, "sweepStatusLabel")
    clear_btn = root.findChild(object, "clearSweepButton")

    controller.setSweepConfig("drain", 0.0, 0.6, 0.2)
    # the label binds to hasSweepConfig; force its binding to re-evaluate
    root.findChild(object, "sweepPanel").setProperty("visible", False)
    root.findChild(object, "sweepPanel").setProperty("visible", True)
    assert str(label.property("text")) == "sweep armed"

    clear_btn.setProperty("enabled", True)
    QMetaObject.invokeMethod(clear_btn, "clicked")
    assert controller.hasSweepConfig is False


# ----------------------------------------------------------------------
#  viewport series mode
# ----------------------------------------------------------------------
def test_view_mode_selector_offers_curves(gapp):
    engine, root, _ = _fresh(gapp)
    selector = root.findChild(object, "viewModeSelector")
    model = list(selector.property("model"))
    assert "Curves" in model


def test_series_mode_hands_sweep_to_canvas(gapp):
    """With no result yet this must still route cleanly: the mode switch
    itself works and leaves nothing broken (regression guard for the
    ViewportPanel.setViewMode('series') branch existing at all)."""
    engine, root, controller = _fresh(gapp)
    viewport = root.findChild(object, "viewportPanel")
    QMetaObject.invokeMethod(viewport, "setViewMode", Q_ARG("QVariant", "series"))
    channel_box = root.findChild(object, "sweepChannelSelector")
    assert channel_box is not None


# ----------------------------------------------------------------------
#  full path: QML config -> real subprocess sweep -> curve rendered
# ----------------------------------------------------------------------
def test_qml_sweep_end_to_end(gapp):
    engine, root, controller = _fresh(gapp)
    controller.loadStructureExample("mosfet_2d_structure")

    # configure the sweep through the REAL panel controls
    box = root.findChild(object, "sweepContactBox")
    box.setProperty("currentIndex", list(box.property("model")).index("drain"))
    for name, value in (("sweepStartField", "0.0"), ("sweepStopField", "0.4"),
                        ("sweepStepField", "0.1")):
        root.findChild(object, name).setProperty("text", value)
    QMetaObject.invokeMethod(root.findChild(object, "applySweepButton"), "clicked")
    assert controller.hasSweepConfig is True

    loop = QEventLoop()
    controller.resultChanged.connect(loop.quit)
    errors = []
    controller.errorRaised.connect(lambda s, d: (errors.append(s), loop.quit()))
    QTimer.singleShot(240000, loop.quit)     # generous; several 2D solves
    controller.run()
    loop.exec()

    assert not errors, f"sweep run raised: {errors}"
    assert controller.hasResult is True, controller.status
    assert controller.hasSweep is True, "finished result carries no sweep"

    sw = controller.sweepResultForQml
    assert sw.contact == "drain"
    assert sw.voltages.size == 5
    assert bool(sw.converged.all()), "all points should converge on this ramp"

    # the viewport must actually receive it and draw a real curve
    viewport = root.findChild(object, "viewportPanel")
    viewport.setProperty("currentMode", "")   # force re-apply
    QMetaObject.invokeMethod(viewport, "setViewMode", Q_ARG("QVariant", "series"))

    canvas = root.findChild(object, "mplCanvas")
    assert canvas._sweep is not None, (
        "ViewportPanel never handed sweepResultForQml to MplCanvasItem -- "
        "'Curves' mode would render the placeholder forever")
    assert canvas._sweep_channel != ""

    img = canvas.renderToImage()
    assert not img.isNull()
    colours = {img.pixel(x, y) for x in range(0, img.width(), 41)
               for y in range(0, img.height(), 41)}
    assert len(colours) > 1, "series viewport rendered a blank/flat image"

    # the channel selector must be populated from the real result
    channel_model = list(root.findChild(object, "sweepChannelSelector")
                         .property("model"))
    assert "source" in channel_model and "drain" in channel_model
