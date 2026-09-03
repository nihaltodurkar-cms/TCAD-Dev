"""Tests for the three GUI panels merged in from a parallel branch
(2026-09-04) with no dedicated coverage of their own: Band Diagram
Viewer, Solver Telemetry, and Virtual Probe Station. Each controller
holds all UI-facing state (same split as test_controllers.py's own
docstring), so these are testable headlessly without any QML."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import math

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from gui.controllers.app_controller import AppController


@pytest.fixture(scope="module")
def qapp():
    yield QCoreApplication.instance() or QCoreApplication([])


def _run_and_wait(app, timeout_ms=180000):
    loop = QEventLoop()
    app.resultChanged.connect(loop.quit)
    app.errorRaised.connect(lambda s, d: loop.quit())
    QTimer.singleShot(timeout_ms, loop.quit)
    app.run()
    loop.exec()


# ---------------------------------------------------------------- Band Diagram
class TestBandDiagramController:
    def test_no_result_is_honest_not_fabricated(self, qapp):
        app = AppController()
        bd = app.bandDiagram
        assert bd.available is False
        assert "No result" in bd.unavailableReason
        assert bd.x == [] and bd.ec == []

    def test_1d_solve_populates_band_edges(self, qapp):
        app = AppController()
        app.loadExample("diode_1d")
        _run_and_wait(app)
        assert app.hasResult is True, app.status

        bd = app.bandDiagram
        assert bd.available is True, bd.unavailableReason
        assert len(bd.x) > 0
        assert len(bd.ec) == len(bd.x)
        assert len(bd.ev) == len(bd.x)
        assert len(bd.efn) == len(bd.x)
        assert len(bd.efp) == len(bd.x)
        # valence edge must never sit above conduction edge
        assert all(ev <= ec for ev, ec in zip(bd.ev, bd.ec))
        assert all(math.isfinite(v) for v in bd.ec + bd.ev + bd.efn + bd.efp)

    def test_2d_solve_reports_not_available_honestly(self, qapp):
        app = AppController()
        app.loadExample("mosfet_2d")
        _run_and_wait(app)
        assert app.hasResult is True, app.status

        bd = app.bandDiagram
        assert bd.available is False
        assert "2D" in bd.unavailableReason

    def test_refresh_follows_result_changed_without_manual_call(self, qapp):
        """BandDiagramController wires refresh() to app.resultChanged in
        __init__ -- it must update on its own, not need loadFromResult()
        called directly from the test."""
        app = AppController()
        app.loadExample("diode_1d")
        _run_and_wait(app)
        assert app.bandDiagram.available is True


# ------------------------------------------------------------- Solver Telemetry
class TestSolverTelemetryController:
    def test_demo_mode_populates_a_decaying_trace(self, qapp):
        app = AppController()
        st = app.solverTelemetry
        assert st.state == "idle"
        assert st.currentResidualDisplay == "--"

        st.loadDemo()
        assert st.isDemo is True
        assert st.state == "converged"
        assert len(st.iterationHistory) == 18
        assert len(st.residualHistory) == 18
        assert st.currentIteration == 18
        # geometric decay: monotonically non-increasing
        assert all(a >= b for a, b in
                  zip(st.residualHistory, st.residualHistory[1:]))
        assert st.currentResidualDisplay != "--"

    def test_real_solve_drives_live_telemetry_not_just_demo(self, qapp):
        app = AppController()
        st = app.solverTelemetry
        app.loadExample("diode_1d")

        _run_and_wait(app)
        assert app.hasResult is True, app.status

        assert st.isDemo is False
        assert st.state == "converged"
        assert len(st.iterationHistory) > 0, \
            "no iteration was scraped from the real solver subprocess"
        assert len(st.residualHistory) > 0, \
            "no |dpsi| residual was scraped from the real solver subprocess"
        assert all(math.isfinite(v) for v in st.residualHistory)
        assert all(v >= 0 for v in st.residualHistory)

    def test_started_signal_resets_state_to_running(self, qapp):
        app = AppController()
        st = app.solverTelemetry
        st.loadDemo()
        assert st.state == "converged"

        app._runner.started.emit()
        assert st.state == "running"
        assert st.isDemo is False
        assert st.iterationHistory == []
        assert st.residualHistory == []

    def test_failed_signal_sets_failed_state(self, qapp):
        app = AppController()
        st = app.solverTelemetry
        app._runner.started.emit()
        app._runner.failed.emit("boom", "details")
        assert st.state == "failed"


# ------------------------------------------------------------- Probe Station
class TestProbeStationController:
    @pytest.mark.parametrize("sweep_type", ["transfer", "output", "breakdown"])
    def test_demo_sweep_populates_curve_and_extraction(self, qapp, sweep_type):
        app = AppController()
        ps = app.probeStation
        ps.loadDemo(sweep_type)

        assert ps.sweepType == sweep_type
        assert len(ps.sweepX) > 0
        assert len(ps.sweepY) == len(ps.sweepX)
        assert all(math.isfinite(v) for v in ps.sweepX)
        assert all(math.isfinite(v) for v in ps.sweepY)
        assert "loaded" in ps.status

    def test_demo_transfer_extracts_vth_and_ss(self, qapp):
        app = AppController()
        ps = app.probeStation
        ps.loadDemo("transfer")
        names = [row["name"] for row in ps.extractionModel]
        assert any("Vth" in n for n in names)
        assert any("swing" in n.lower() for n in names)

    def test_unknown_sweep_type_raises_error_not_crash(self, qapp):
        app = AppController()
        ps = app.probeStation
        errors = []
        app.errorRaised.connect(lambda s, d: errors.append((s, d)))
        ps.loadDemo("nonsense")
        assert errors, "unknown sweep type must surface via errorRaised"
        # unchanged state, not a fabricated curve
        assert ps.sweepX == []

    def test_demo_rf_populates_h21_and_ft(self, qapp):
        app = AppController()
        ps = app.probeStation
        ps.loadDemoRF()
        assert len(ps.rfFreq) > 0
        assert len(ps.rfH21) == len(ps.rfFreq)
        assert len(ps.rfModel) == 1
        assert ps.rfModel[0]["unit"] == "Hz"
        assert math.isfinite(ps.rfModel[0]["value"])

    def test_run_sweep_surfaces_not_implemented_honestly(self, qapp):
        """runSweep is the real-backend dispatch path -- not yet wired to
        a solver (see probe_station_controller.py's module docstring).
        It must surface that honestly via errorRaised, not crash and not
        pretend to have solved anything."""
        app = AppController()
        ps = app.probeStation
        errors = []
        app.errorRaised.connect(lambda s, d: errors.append((s, d)))

        ps.runSweep("transfer", {})

        assert ps.isBusy is False
        assert errors, "unimplemented real-solver path must errorRaise"
        assert "no solver backend" in errors[-1][0].lower()
        # no fabricated data got written to the sweep curve
        assert ps.sweepX == []

    def test_run_rf_surfaces_not_implemented_honestly(self, qapp):
        app = AppController()
        ps = app.probeStation
        errors = []
        app.errorRaised.connect(lambda s, d: errors.append((s, d)))

        ps.runRF({})

        assert ps.isBusy is False
        assert errors, "unimplemented real-solver RF path must errorRaise"
        assert ps.rfFreq == []
