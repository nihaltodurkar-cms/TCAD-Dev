"""C-V analysis controller: runs MOSCapacitor C-V sweeps through its own
JobRunner subprocess and exposes the result store.  Deliberately a
separate controller (no god-controller growth); same ownership pattern
as FamilySweepController."""
import json
import os
import tempfile
import uuid

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..services.job_runner import JobRunner
from ..services.result_store import NpzResultStore


class _CVJob:
    """Adapts plain C-V parameters to the `to_json(path)` contract
    JobRunner.start() expects (the same generic contract ProcessFlow
    now satisfies directly via its own to_json/from_json -- see
    gui/services/process_model.py -- but a bare dict of C-V params has
    no dataclass of its own to grow that method on)."""

    def __init__(self, params):
        self.params = dict(params)

    def to_json(self, path):
        with open(path, "w") as fh:
            json.dump(self.params, fh)


class CVController(QObject):
    cvFinished = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._work_dir = tempfile.mkdtemp(prefix="pytcad-cv-")
        self._runner = JobRunner(parent=self, module="gui.services.moscap_runner",
                                 work_dir=self._work_dir)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)
        self._store = None

    @Slot(float, float, float, float, float)
    def runCV(self, nsub_cm3, tox_nm, vstart, vstop, vstep):
        job = _CVJob({
            "nsub_cm3": float(nsub_cm3),
            "tox_nm": float(tox_nm),
            "vstart": float(vstart),
            "vstop": float(vstop),
            "vstep": abs(float(vstep)) or 0.05,
        })
        try:
            self._runner.start(job)
        except Exception as exc:
            self._app.errorRaised.emit("Could not start the C-V run", str(exc))

    def _on_finished(self, result_path):
        try:
            self._store = NpzResultStore(result_path)
        except Exception as exc:
            self._app.errorRaised.emit("Could not read the C-V result",
                                       str(exc))
            return
        self.cvFinished.emit()

    def _on_failed(self, summary, details):
        self._app.errorRaised.emit(f"C-V failed: {summary}", details)

    def cvStore(self):
        """The finished C-V result store, or None before the first run."""
        return self._store

    # Same opaque-handoff rationale as AppController.sweepResultForQml:
    # handed to MplCanvasItem.setCvSource() by ViewportPanel, never
    # attribute-read from QML.
    @Property(object, notify=cvFinished)
    def cvResultForQml(self):
        if self._store is None or not self._store.has_sweep():
            return None
        try:
            return self._store.sweep_result()
        except Exception:
            return None
