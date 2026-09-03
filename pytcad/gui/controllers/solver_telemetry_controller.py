"""Solver Telemetry panel: a live Newton-convergence readout for the
solve currently driven by AppController's real JobRunner (self._runner,
gui/services/job_runner.py), NOT a second independent solver connection.

Architecture note (why this is a signal listener, not a same-process
registry): every solve runs in a genuinely separate OS process via
QProcess -- see job_runner.py's own module docstring for why (a hung or
slow Newton loop must never be able to block or unsafely kill the GUI).
A same-process Python object cannot be called into from that subprocess.
What DOES cross the process boundary is job_runner.py's stdout-scraped
telemetry: iterationChanged(int) and the new residualChanged(float),
emitted from JobRunner._on_stdout as the subprocess's own
NewtonOptions(verbose=True) print lines arrive. This controller only
ever listens to that JobRunner instance's Qt signals and accumulates
what it hears -- exactly the same event-driven ownership shape as
CVController/ProbeStationController being handed the app and reading
from it, not the same-process solver registry an earlier (rejected)
proposal assumed.

Same ownership pattern as ProbeStationController: a plain sub-controller
receiving the AppController reference, exposed to QML through a
`@Property(QObject, constant=True)` getter (see `solverTelemetry` on
AppController).
"""
import math

from PySide6.QtCore import QObject, Property, Signal, Slot


class SolverTelemetryController(QObject):
    telemetryChanged = Signal()
    statusChanged = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._iterations = []
        self._residuals = []
        self._current_iteration = 0
        self._current_residual = None
        self._stage = ""
        self._state = "idle"        # idle | running | converged | failed | canceled
        self._demo = False

        runner = getattr(app, "_runner", None)
        if runner is not None:
            runner.started.connect(self._on_started)
            runner.stageChanged.connect(self._on_stage)
            runner.iterationChanged.connect(self._on_iteration)
            runner.residualChanged.connect(self._on_residual)
            runner.finished.connect(self._on_finished)
            runner.failed.connect(self._on_failed)
            runner.canceled.connect(self._on_canceled)

    # -- real-solve wiring ---------------------------------------------
    def _on_started(self):
        self._demo = False
        self._iterations = []
        self._residuals = []
        self._current_iteration = 0
        self._current_residual = None
        self._stage = ""
        self._state = "running"
        self.telemetryChanged.emit()
        self.statusChanged.emit()

    def _on_stage(self, stage):
        self._stage = str(stage)
        self.statusChanged.emit()

    def _on_iteration(self, it):
        self._current_iteration = int(it)
        self.telemetryChanged.emit()

    def _on_residual(self, value):
        self._current_residual = float(value)
        self._iterations.append(self._current_iteration)
        self._residuals.append(self._current_residual)
        self.telemetryChanged.emit()

    def _on_finished(self, path):
        self._state = "converged"
        self.statusChanged.emit()

    def _on_failed(self, summary, details):
        self._state = "failed"
        self.statusChanged.emit()

    def _on_canceled(self):
        self._state = "idle"
        self.statusChanged.emit()

    # -- demo mode (UI testing without a real solve) --------------------
    @Slot()
    def loadDemo(self):
        """Synthetic Newton-convergence trace (geometric residual decay
        over 18 iterations) for exercising the panel's plot/readout
        without running a real solve -- same spirit as
        ProbeStationController.loadDemo()."""
        self._demo = True
        n = 18
        self._iterations = list(range(1, n + 1))
        self._residuals = [1.0e-1 * (0.55 ** i) for i in range(n)]
        self._current_iteration = n
        self._current_residual = self._residuals[-1]
        self._stage = "bias"
        self._state = "converged"
        self.telemetryChanged.emit()
        self.statusChanged.emit()

    # -- QML-facing data --------------------------------------------------
    @Property(list, notify=telemetryChanged)
    def iterationHistory(self):
        return list(self._iterations)

    @Property(list, notify=telemetryChanged)
    def residualHistory(self):
        return list(self._residuals)

    @Property(int, notify=telemetryChanged)
    def currentIteration(self):
        return self._current_iteration

    @Property(str, notify=telemetryChanged)
    def currentResidualDisplay(self):
        if self._current_residual is None:
            return "--"
        r = self._current_residual
        if not math.isfinite(r):
            return str(r)
        return f"{r:.3e}"

    @Property(str, notify=statusChanged)
    def stage(self):
        return self._stage

    @Property(str, notify=statusChanged)
    def state(self):
        return self._state

    @Property(bool, notify=statusChanged)
    def isDemo(self):
        return self._demo
