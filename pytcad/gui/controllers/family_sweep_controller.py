"""Family sweeps (batch): N warm-started single-contact solves of the
same device at N bias values of a STEPPED terminal -- the classic
Id-Vg-at-several-Vds workflow.

Deliberately its own controller (the god controller must not grow):
it receives the AppController reference like BuilderController does,
owns ONE JobRunner of its own, and runs its jobs strictly SEQUENTIALLY
-- each curve is an ordinary solver job writing an ordinary schema-v2
npz, read back through the ordinary ResultStore.  Nothing here fakes or
interpolates a curve.
"""
import copy
import tempfile

import numpy as np

from PySide6.QtCore import QObject, Property, Signal, Slot

from ..services.job_runner import JobRunner
from ..services.result_store import NpzResultStore


class FamilySweepController(QObject):
    familyChanged = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._runner = JobRunner(parent=self,
                                 work_dir=tempfile.mkdtemp(
                                     prefix="pytcad-family-"))
        self._runner.finished.connect(self._on_curve_finished)
        self._runner.failed.connect(self._on_curve_failed)
        self._stepped = ""
        self._values = []
        self._swept = ""
        self._ramp = None            # (start, stop, step)
        self._base_spec = None
        self._queue = []             # pending (value, spec) pairs
        self._curves = []            # finished curve dicts
        self._error = ""

    # -- configuration --------------------------------------------------
    @Slot(str, float, float, float)
    def configureFamily(self, stepped, start, stop, step):
        """Which terminal is STEPPED and over which values.  A single
        value (start == stop) is allowed and yields a one-curve family;
        the per-point validation happens against the base spec at run."""
        # reject a step that moves AWAY from the target -- the old code
        # silently produced a single-curve "family" for that typo
        if step != 0 and (stop - start) * step < 0:
            self._app.errorRaised.emit(
                "Invalid family configuration",
                f"step {step:g} does not move from start {start:g} "
                f"toward stop {stop:g}")
            return
        self._stepped = str(stepped)
        vals = []
        if step != 0:
            span = abs(stop - start)
            n = int(round(span / abs(step)))
            if abs(span - n * abs(step)) < 1e-9:
                n += 1
            else:
                n = int(span / abs(step)) + 1
            direction = 1.0 if stop >= start else -1.0
            vals = [start + i * abs(step) * direction
                    for i in range(max(n, 1))]
        else:
            vals = [float(start)]
        self._values = vals

    def setBaseSpec(self, spec):
        """Python-side injection for tests/scripts.  The GUI path leaves
        this unset and uses the last solved device."""
        self._base_spec = spec

    @Slot(str, float, float, float)
    def runFamily(self, swept, start, stop, step):
        base = self._base_spec or self._app.lastRunSpec()
        if base is None:
            self._app.errorRaised.emit(
                "Nothing to sweep",
                "Run the device once first; every family curve re-solves "
                "that exact device.")
            return
        if self._runner.running:
            return          # a click during a running family is ignored
        names = [c.name for c in base.contacts]
        for label, contact in ((self._stepped, self._stepped),
                               ("swept", swept)):
            if contact not in names:
                self._app.errorRaised.emit(
                    "Family cannot run",
                    f"Contact {contact!r} is not registered on this "
                    f"device (have: {', '.join(names)}).")
                return
        self._swept = swept
        self._ramp = (float(start), float(stop), float(step))
        from ..services.device_spec import SweepSpec
        try:
            SweepSpec(contact=swept, start=start, stop=stop,
                      step=step).validate(names)
        except ValueError as exc:
            self._app.errorRaised.emit("Invalid family sweep", str(exc))
            return

        self._queue = []
        self._curves = []
        for v in self._values:
            spec = copy.deepcopy(base)
            spec.sweep = SweepSpec(contact=swept, start=start, stop=stop,
                                   step=step)
            spec.bias = dict(base.bias or {})
            spec.bias[self._stepped] = v
            self._queue.append((v, spec))
        self._start_next()

    def _start_next(self):
        if not self._queue:
            self.familyChanged.emit()
            return
        v, spec = self._queue[0]
        self._app.consoleModel.append(
            f"Family curve {len(self._curves) + 1}/"
            f"{len(self._curves) + len(self._queue)}: "
            f"{self._stepped}={v:g} V")
        try:
            self._runner.start(spec)
        except Exception as exc:
            self._queue = []
            self._app.errorRaised.emit("Could not start the family", str(exc))

    def _on_curve_finished(self, result_path):
        if not self._queue:
            return
        v, _spec = self._queue.pop(0)
        store = NpzResultStore(result_path)
        sw = store.sweep_result() if store.has_sweep() else None
        flags = np.asarray(sw.converged, dtype=bool) if sw is not None \
            else np.array([], dtype=bool)
        # 1D sweeps record a single "device" channel, not per-contact names
        if sw is not None:
            channel = sw.contact if sw.contact in sw.channels \
                else (list(sw.channels)[0] if sw.channels else "")
            currents = np.asarray(sw.channels.get(channel, []),
                                  dtype=float)
        else:
            currents = np.asarray([], dtype=float)
        self._curves.append({
            "label": f"{self._stepped}={v:g} V",
            "stepped_value": float(v),
            "voltages": np.asarray(sw.voltages, dtype=float)
                        if sw is not None else [],
            "currents": currents,
            "converged": flags,
        })
        self._start_next()

    def _on_curve_failed(self, summary, details):
        self._queue = []
        # partial curves stay visible; the UI must hear about it either way
        self.familyChanged.emit()
        self._app.errorRaised.emit(f"Family failed: {summary}", details)

    # -- QML surface ----------------------------------------------------
    @Property(list, notify=familyChanged)
    def curves(self):
        return list(self._curves)

    @Property(bool, notify=familyChanged)
    def hasCurves(self):
        return bool(self._curves)
