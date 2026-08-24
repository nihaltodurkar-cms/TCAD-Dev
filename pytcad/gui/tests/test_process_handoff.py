"""Integration test: a real process flow, run through process_runner.py,
handed off to a real Device1D solve through the existing solver_runner
path -- design section 17's required integration test.

This exercises TWO real subprocesses (a process flow run and a device
solve) plus real numerical solves -- it takes real wall-clock time.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication

from gui.controllers.app_controller import AppController


@pytest.fixture(scope="module")
def qapp():
    yield QGuiApplication.instance() or QGuiApplication([])


def test_full_process_flow_solves_through_device1d(qapp, tmp_path):
    app = AppController()
    app.addProcessStep("substrate", "Substrate",
                       {"length_cm": 3e-4, "background_doping_cm3": -1e16,
                        "mesh": {"h_min_cm": 2e-8, "h_max_cm": 1e-6, "ratio": 1.12}})
    app.addProcessStep("implant", "Implant P",
                       {"species": "P", "energy_keV": 50.0, "dose_cm2": 3e14})
    app.addProcessStep("anneal", "Anneal",
                       {"temperature_C": 950.0, "time_s": 600.0})
    assert app.runProcessValidation() is True, app.processValidationErrors

    loop = QEventLoop()
    app.processResultChanged.connect(loop.quit)
    app.errorRaised.connect(lambda s, d: (print("ERROR", s, d), loop.quit()))
    QTimer.singleShot(60000, loop.quit)
    app.runProcess()
    loop.exec()

    assert app.hasProcessResult is True, app.status

    # Read the final checkpoint directly from the ProcessResultStore, the
    # same way buildDeviceFromProcess() itself does, so we have an
    # independent x array to check ntotal/values against below.
    final_id = app._process_result.step_ids()[-1]
    state = app._process_result.state_for(final_id)
    x = state["x"]

    app.leftContactV = 0.0
    app.rightContactV = 0.3
    ok = app.buildDeviceFromProcess()
    assert ok is True, app.status

    # Binding correction 1 (design review): ntotal must actually be
    # populated on the built DeviceSpec, with the right length -- this is
    # the whole point of Task 8's doping handoff, and it is worthless if
    # nothing ever asserts it.
    assert app.spec.doping.ntotal is not None
    assert len(app.spec.doping.values) == len(x)
    assert len(app.spec.doping.ntotal) == len(x)

    solve_loop = QEventLoop()
    app.resultChanged.connect(solve_loop.quit)
    app.errorRaised.connect(lambda s, d: (print("SOLVE ERROR", s, d), solve_loop.quit()))
    QTimer.singleShot(60000, solve_loop.quit)
    app.run()
    solve_loop.exec()

    assert app.hasResult is True, app.status
    assert "potential" in app.fieldNames
