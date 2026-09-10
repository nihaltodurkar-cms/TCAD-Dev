"""M38 Phase 4: compact-model extraction controller.

Runs `gui.services.compact_runner` through its own JobRunner subprocess
(same ownership/isolation pattern as CVController) and exposes the JSON
manifest it writes as QML properties. Deliberately a separate
controller -- no god-controller growth.

Layering rule: this controller never imports pytcad or workbench.compact
directly; it only starts the subprocess and reads back the JSON file it
wrote. Plan: `M38-PHASE4-PLAN.md`.
"""
import json
import tempfile

from PySide6.QtCore import Property, QObject, Signal, Slot

from ..services.job_runner import JobRunner


class _CompactJob:
    """Adapts a plain dict to the `to_json(path)` contract JobRunner.start()
    expects, same shape as cv_controller.py's `_CVJob`."""

    def __init__(self, params):
        self.params = dict(params)

    def to_json(self, path):
        with open(path, "w") as fh:
            json.dump(self.params, fh)


class CompactModelController(QObject):
    # One notify signal for both `resultForQml` and `lastError`: either
    # property can change on EITHER outcome (a fresh success clears the
    # stale error text; a failure leaves the previous result in place
    # but must still notify lastError's binding).
    changed = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._work_dir = tempfile.mkdtemp(prefix="pytcad-compact-")
        self._runner = JobRunner(parent=self,
                                 module="gui.services.compact_runner",
                                 work_dir=self._work_dir)
        self._runner.started.connect(self.changed)
        self._runner.finished.connect(self._on_finished)
        self._runner.failed.connect(self._on_failed)
        self._result = None
        self._lastError = ""

    @Property(bool, notify=changed)
    def running(self):
        return self._runner.running

    @Slot(float, float, float, float, float, float, float, float, float,
         float, float)
    def runDiode(self, scale, L_um, xj_um, Na, Nd, v_start, v_stop, v_step,
                v_fit_min, v_fit_max, unused=0.0):
        job = _CompactJob({
            "kind": "diode", "scale": float(scale), "L_um": float(L_um),
            "xj_um": float(xj_um), "Na": float(Na), "Nd": float(Nd),
            "v_start": float(v_start), "v_stop": float(v_stop),
            "v_step": abs(float(v_step)) or 0.025,
            "v_fit_min": float(v_fit_min), "v_fit_max": float(v_fit_max),
        })
        self._start(job)

    @Slot(float, float, float, float, float, float, float, float, float,
         float, float, float, float)
    def runMosfet(self, scale, Lg_um, Lsd_um, depth_um, Na, Nsd_peak, tox_nm,
                  vg_start, vg_stop, vg_step, vds_lin,
                  vd_start=1.6, vd_stop=3.0):
        job = _CompactJob({
            "kind": "mosfet1", "scale": float(scale), "Lg_um": float(Lg_um),
            "Lsd_um": float(Lsd_um), "depth_um": float(depth_um),
            "Na": float(Na), "Nsd_peak": float(Nsd_peak),
            "tox_nm": float(tox_nm),
            "vg_start": float(vg_start), "vg_stop": float(vg_stop),
            "vg_step": abs(float(vg_step)) or 0.25,
            "vds_lin": float(vds_lin),
            "vd_start": float(vd_start), "vd_stop": float(vd_stop),
            "vd_step": 0.2, "vgs_sat": float(vg_stop) * 0.5,
        })
        self._start(job)

    def _start(self, job):
        try:
            self._runner.start(job)
        except Exception as exc:
            self._app.errorRaised.emit(
                "Could not start the compact-model extraction", str(exc))

    def _on_finished(self, result_path):
        self._lastError = ""
        try:
            with open(result_path) as fh:
                self._result = json.load(fh)
        except Exception as exc:
            self._app.errorRaised.emit(
                "Could not read the compact-model result", str(exc))
            self._result = None
            self._lastError = str(exc)
            self.changed.emit()
            return
        self.changed.emit()

    def _on_failed(self, summary, details):
        self._lastError = summary
        self._app.errorRaised.emit(f"Extraction failed: {summary}", details)
        self.changed.emit()

    @Property(str, notify=changed)
    def resultJson(self):
        """The finished manifest (kind/converged/scale/params/netlist/
        curve), JSON-encoded, or "" before the first run/after a
        failure. A plain str property rather than Property(object):
        PySide's QVariant marshalling of a Python dict/None through an
        `object`-typed property was measured to hand QML a stale/empty
        object on every read here, not the current value -- a JSON
        string + QML-side JSON.parse sidesteps it entirely."""
        return json.dumps(self._result) if self._result is not None else ""

    @Property(str, notify=changed)
    def lastError(self):
        return self._lastError
