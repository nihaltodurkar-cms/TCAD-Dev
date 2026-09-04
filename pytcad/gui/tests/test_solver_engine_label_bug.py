"""Regression test for a real, pre-existing bug found during the QML
architecture cleanup pass (2026-09-04) and confirmed unrelated to that
work (byte-identical diff on app_controller.py/result_store.py at the
time): AppController.solverEngineLabel crashed with

    AttributeError: 'SpecResultStore' object has no attribute 'has_record'

whenever a device was loaded (via loadExample()) but not yet solved --
i.e. whenever self._store is a SpecResultStore (a structure preview),
not an NpzResultStore (an actual solve output).

Root cause: has_record()/run_record() were added directly to
NpzResultStore (gui/services/result_store.py) without also adding them
to the ResultStore ABC as protocol members with honest defaults --
unlike every sibling capability (has_sweep/sweep_result, has_transient/
transient_result, has_band_diagram/band_diagram), which the ABC's own
docstring says is exactly the intended pattern: "Sweep and solved-
result support are protocol members with honest defaults rather than
abstractmethods: most stores legitimately carry neither." has_record/
run_record simply never got that treatment. SpecResultStore (and any
other non-Npz store) inherited no default and crashed instead of
answering honestly.
"""
import time

from PySide6.QtWidgets import QApplication

from gui.controllers.app_controller import AppController
from gui.services.result_store import SpecResultStore


def test_spec_result_store_answers_has_record_honestly_instead_of_crashing():
    # ResultStore's own ABC docstring: "most stores legitimately carry
    # neither" -- a structure preview is exactly such a store.
    from gui.services.device_spec import DeviceSpec, MeshSpec, DopingSpec, ContactSpec
    spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": [0.0, 1e-4]}),
        doping=DopingSpec(kind="array", values=[-1e16, -1e16]),
        contacts=[ContactSpec(name="a", kind="ohmic", nodes={"i": [0]}, V=0.0),
                  ContactSpec(name="b", kind="ohmic", nodes={"i": [1]}, V=0.0)],
        bias={"a": 0.0, "b": 0.0})
    store = SpecResultStore(spec)
    assert store.has_record() is False
    assert store.run_record() is None


def test_solver_engine_label_does_not_crash_before_any_solve():
    app = QApplication.instance() or QApplication([])
    ctl = AppController()
    ctl.loadExample("diode_1d")  # sets self._store to a SpecResultStore
    # This is the exact call that raised AttributeError before the fix.
    assert ctl.solverEngineLabel == ""


def test_solver_engine_label_reports_the_real_engine_after_a_solve():
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
    # A real diode_1d solve uses the direct sparse solver by default.
    assert ctl.solverEngineLabel == "Direct"
