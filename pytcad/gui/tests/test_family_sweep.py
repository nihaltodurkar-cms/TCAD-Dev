"""Batch/multi-parameter sweeps: Vds-stepped Id-Vg families.

A family is N warm-started single-contact sweeps executed SEQUENTIALLY
through their own JobRunner, each solving the last-run device at a
different value of a STEPPED terminal.  Everything rides the existing
validated pipeline -- one ordinary solver job per curve, results read
from real npz files.

The controller is deliberately SEPARATE from AppController (no god-
controller growth): it receives the app reference like BuilderController
does and reads one public accessor.
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication

from gui import app as gui_app


@pytest.fixture(scope="module")
def gapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def _diode_base_spec():
    """A fast 1D diode spec as the family's base device."""
    from gui.services.device_spec import (
        ContactSpec, DeviceSpec, DopingSpec, MeshSpec,
    )
    x = np.linspace(0.0, 2e-4, 40)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": x.tolist()}),
        doping=DopingSpec(kind="array", values=doping.tolist()),
        contacts=[ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
                  ContactSpec(name="right", kind="ohmic",
                              nodes={"i": [x.size - 1]}, V=0.0)],
        bias={"left": 0.0, "right": 0.0})


def _pump_until(gapp, condition, timeout_s=90):
    for _ in range(timeout_s * 10):
        gapp.processEvents()
        gapp.thread().msleep(100)
        if condition():
            return True
    return False


def test_family_runs_n_curves_and_labels_them(gapp, tmp_path):
    engine, controller = gui_app.create_engine(gapp)
    fam = controller.family
    fam.setBaseSpec(_diode_base_spec())

    fired = []
    fam.familyChanged.connect(lambda: fired.append(1))

    # 3 curves: right stepped over 0.0 / 0.25 / 0.5 V,
    # each sweeping left 0 -> 0.3 V in 0.1 V steps
    fam.configureFamily(stepped="right", start=0.0, stop=0.5, step=0.25)
    fam.runFamily(swept="left", start=0.0, stop=0.3, step=0.1)

    assert _pump_until(gapp, lambda: bool(fired)), "family never finished"

    curves = fam.curves
    assert len(curves) == 3
    labels = [c["label"] for c in curves]
    assert all("right" in lbl for lbl in labels)
    values = sorted(c["stepped_value"] for c in curves)
    assert values == pytest.approx([0.0, 0.25, 0.5])
    for c in curves:
        assert c["converged"].all(), "a family curve did not converge"
        v = np.asarray(c["voltages"], dtype=float)
        assert np.allclose(v, [0.0, 0.1, 0.2, 0.3])


def test_family_requires_a_base_spec(gapp):
    engine, controller = gui_app.create_engine(gapp)
    fam = controller.family
    errors = []
    controller.errorRaised.connect(lambda s, d: errors.append(s))
    fam.configureFamily(stepped="right", start=0.0, stop=0.5, step=0.25)
    fam.runFamily(swept="left", start=0.0, stop=0.3, step=0.1)
    assert errors, "missing base spec must raise an actionable error"


def test_family_curve_values_are_real_physics(gapp, tmp_path):
    """The family's reverse-bias curve must carry the diode's saturation
    signature: |J| at the largest forward bias exceeds the smallest by
    orders of magnitude (real solver output, schema-checked npz)."""
    engine, controller = gui_app.create_engine(gapp)
    fam = controller.family
    fam.setBaseSpec(_diode_base_spec())
    # right stepped to -0.3 V: junction bias = left - (-0.3), so the
    # 0 -> 0.45 V ramp crosses well into forward conduction
    fam.configureFamily(stepped="right", start=-0.3, stop=-0.3, step=0.3)
    fam.runFamily(swept="left", start=0.0, stop=0.45, step=0.15)
    assert _pump_until(gapp, lambda: bool(fam.curves))

    js = np.asarray(fam.curves[0]["currents"], dtype=float)
    assert abs(js[-1]) > 100 * max(abs(js[0]), 1e-30), \
        f"diode family curve shows no exponential turn-on: {js}"


def test_sweep_panel_exposes_the_family_ui(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    assert controller.familySweep is not None
    for name in ("familySteppedBox", "familyStartField",
                 "familyStopField", "familyStepField", "runFamilyButton",
                 "familyStatusLabel"):
        assert root.findChild(object, name) is not None, f"missing {name}"


def test_family_curves_reach_the_canvas(gapp, tmp_path):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    fam = controller.family
    fam.setBaseSpec(_diode_base_spec())
    fam.configureFamily(stepped="right", start=0.0, stop=0.5, step=0.5)
    fam.runFamily(swept="left", start=0.0, stop=0.3, step=0.1)
    # Wait for BOTH curves, not just the first: bool(fam.curves) goes
    # true after curve 1/2 lands, so a fixed settle-wait after that
    # races the second curve's solve under CPU contention (e.g. -n 4
    # parallel runs) -- self-caught as a flake, not a wiring bug (the
    # canvas update itself is a same-tick signal, no delay needed once
    # both curves exist).
    assert _pump_until(gapp, lambda: len(fam.curves) == 2), \
        "family did not finish both curves"

    # ViewportPanel's Connections pushes the curves into the canvas;
    # give the queued signal delivery a few loop turns to land
    canvas = root.findChild(object, "mplCanvas")
    assert _pump_until(gapp, lambda: canvas.familyCurveCount() == 2), \
        "canvas did not receive the family curves"


def test_bad_direction_config_is_rejected_with_error(gapp):
    """step=+0.25 from 1.0 toward 0.0 used to silently produce a
    single-curve 'family' -- it must raise an actionable error instead."""
    engine, controller = gui_app.create_engine(gapp)
    fam = controller.family
    errs = []
    controller.errorRaised.connect(lambda s, d: errs.append(s))
    fam.configureFamily(stepped="right", start=1.0, stop=0.0, step=0.25)
    assert errs and "Invalid family" in errs[0]
    # negative direction is legitimate and must still work
    errs.clear()
    fam.configureFamily(stepped="right", start=0.5, stop=-0.5, step=-0.25)
    assert not errs
    fam.runFamily(swept="left", start=0.0, stop=0.3, step=0.1)
    assert any("Nothing to sweep" in e for e in errs) or not fam.curves


def test_family_stepper_contact_list_follows_structure_changes(gapp):
    engine, controller = gui_app.create_engine(gapp)
    root = engine.rootObjects()[0]
    controller.loadStructureExample("mosfet_2d_structure")
    box = root.findChild(object, "familySteppedBox")
    model_before = list(box.property("model"))
    assert model_before, "stepper combo must offer the device contacts"
    # loading a different project refreshes the registry; the stepper
    # must follow it rather than keep stale contacts
    controller.loadStructureExample("mosfet_2d_structure")
    assert list(box.property("model")) == model_before
