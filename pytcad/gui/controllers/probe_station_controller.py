"""Virtual Probe Station: DC/RF device-characterization sweeps and the
post-processing extraction (Vth, SS, gds/ro, breakdown voltage, fT) that
turns a raw sweep into device figures of merit.

Same ownership pattern as CVController/FamilySweepController (deliberately
its own controller -- the god controller must not grow): it receives the
AppController reference, owns no JobRunner of its own yet (demo data is
generated synchronously, in-process -- there is no subprocess to run), and
is exposed to QML through a `@Property(QObject, constant=True)` getter on
AppController (see `probeStation` there), the same route as `cv`/`family`.

Backend contract, matching the original proposal:
  DC sweep payload  -> {"x": [...], "y": [...]}
  RF sweep payload   -> {"f": [...], "h21": [...]}  or
                        {"f": [...], "y21": [...], "y11": [...]}

`run_probe_station_sweep`/`run_probe_station_rf` in this module are the
real-solver dispatch point. This repo's other per-feature controllers
(CVController -> gui.services.moscap_runner, FamilySweepController's own
JobRunner) each drive a dedicated subprocess runner module rather than a
shared job-kind registry in solver_runner.py -- there is no existing
"kind"-routed dispatcher to hook into. Wiring the Virtual Probe Station to
a real solver would follow that same pattern (a gui.services.probe_runner
module driven through its own JobRunner) but is out of scope for this
pass: the functions below are honest, clearly-marked stubs (see
ARCHITECTURE.md's "honestly labeled/flagged" convention for known gaps),
and the demo-data path is fully implemented and working.
"""
import math

import numpy as np

from PySide6.QtCore import QObject, Property, Signal, Slot

from ..services import characterization as ch


def run_probe_station_sweep(payload):
    """Real-solver DC sweep dispatch. NOT YET IMPLEMENTED: wiring this to
    an actual device solve (via a dedicated gui.services.probe_runner
    subprocess, following the CVController/moscap_runner precedent) is a
    follow-up pass. Demo data (loadDemo/runSweep with demo=True) does not
    call this."""
    raise NotImplementedError(
        "Virtual Probe Station DC sweeps are not yet wired to a real "
        "solver backend -- only demo data is available in this build. "
        "payload=" + repr(payload))


def run_probe_station_rf(payload):
    """Real-solver RF (small-signal) sweep dispatch. Same not-yet-wired
    status as run_probe_station_sweep above."""
    raise NotImplementedError(
        "Virtual Probe Station RF sweeps are not yet wired to a real "
        "solver backend -- only demo data is available in this build. "
        "payload=" + repr(payload))


def _demo_transfer(vth=0.42, ss_mv_dec=85.0, beta=1.0e-3, vg_max=1.5, n=200):
    vg = np.linspace(-0.2, vg_max, n)
    ss_v_dec = ss_mv_dec / 1000.0
    ioff = 1.0e-12
    id_sub = ioff * 10.0 ** (vg / ss_v_dec)
    idx_vth = int(np.searchsorted(vg, vth))
    id_at_vth = id_sub[idx_vth]
    id_strong = np.where(vg > vth, id_at_vth + beta * (vg - vth), 0.0)
    ids = np.clip(np.where(vg <= vth, id_sub, id_strong), 1e-15, None)
    return vg.tolist(), ids.tolist()


def _demo_output(vd_max=1.5, gds=1.2e-5, id_sat=4.0e-4, n=150):
    vd = np.linspace(0.0, vd_max, n)
    knee = 0.3
    lin = id_sat * np.clip(vd / knee, 0.0, 1.0)
    tail = np.where(vd > knee, gds * (vd - knee), 0.0)
    return vd.tolist(), (lin + tail).tolist()


def _demo_breakdown(bv=14.0, n=200):
    vd = np.linspace(0.0, 22.0, n)
    ids = 1.0e-10 + 1.0e-3 / (1.0 + np.exp(-(vd - bv) * 8.0))
    return vd.tolist(), ids.tolist()


def _demo_rf(ft=8.0e9, n=100):
    f = np.logspace(6, 11, n)
    h21 = ft / f
    return f.tolist(), h21.tolist()


_DEMO_SWEEPS = {
    "transfer": _demo_transfer,
    "output": _demo_output,
    "breakdown": _demo_breakdown,
}


class ProbeStationController(QObject):
    probeChanged = Signal()
    rfChanged = Signal()
    statusChanged = Signal()
    busyChanged = Signal()

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._sweep_type = "transfer"
        self._x = []
        self._y = []
        self._extraction = []
        self._rf_f = []
        self._rf_h21 = []
        self._rf_extraction = []
        self._status = "No sweep yet"
        self._busy = False

    # -- DC sweep ---------------------------------------------------------
    @Slot(str)
    def loadDemo(self, sweep_type):
        """Populate the panel with a synthetic curve for `sweep_type`
        ("transfer"/"output"/"breakdown") -- no solver involved."""
        sweep_type = str(sweep_type)
        gen = _DEMO_SWEEPS.get(sweep_type)
        if gen is None:
            self._app.errorRaised.emit(
                "Unknown sweep type",
                f"'{sweep_type}' is not one of {list(_DEMO_SWEEPS)}.")
            return
        x, y = gen()
        self._apply_sweep(sweep_type, x, y, {})
        self._set_status(f"Demo {sweep_type} curve loaded")

    @Slot(str, "QVariantMap")
    def runSweep(self, sweep_type, params):
        """Real-backend DC sweep. Not yet wired -- see
        run_probe_station_sweep()'s docstring; surfaces the honest
        NotImplementedError through errorRaised rather than pretending to
        solve anything."""
        sweep_type = str(sweep_type)
        payload = dict(params or {})
        payload["sweep_type"] = sweep_type
        self._set_busy(True)
        try:
            result = run_probe_station_sweep(payload)
        except NotImplementedError as exc:
            self._set_busy(False)
            self._set_status("Real-solver sweep not available")
            self._app.errorRaised.emit("Probe Station: no solver backend yet",
                                       str(exc))
            return
        except Exception as exc:
            self._set_busy(False)
            self._set_status("Sweep failed")
            self._app.errorRaised.emit("Probe Station sweep failed", str(exc))
            return
        self._set_busy(False)
        self._apply_sweep(sweep_type, result.get("x", []), result.get("y", []),
                          payload)
        self._set_status(f"{sweep_type} sweep complete")

    def _apply_sweep(self, sweep_type, x, y, meta):
        self._sweep_type = sweep_type
        self._x = [float(v) for v in x]
        self._y = [float(v) for v in y]
        try:
            self._extraction = ch.build_extraction_report(sweep_type, self._x,
                                                           self._y, meta=meta)
        except Exception:
            self._extraction = []
        self.probeChanged.emit()

    # -- RF sweep -----------------------------------------------------------
    @Slot()
    def loadDemoRF(self):
        f, h21 = _demo_rf()
        self._apply_rf(f, h21=h21)
        self._set_status("Demo RF (H21) curve loaded")

    @Slot("QVariantMap")
    def runRF(self, params):
        """Real-backend RF sweep. Not yet wired -- see
        run_probe_station_rf()'s docstring."""
        payload = dict(params or {})
        self._set_busy(True)
        try:
            result = run_probe_station_rf(payload)
        except NotImplementedError as exc:
            self._set_busy(False)
            self._set_status("Real-solver RF sweep not available")
            self._app.errorRaised.emit("Probe Station: no solver backend yet",
                                       str(exc))
            return
        except Exception as exc:
            self._set_busy(False)
            self._set_status("RF sweep failed")
            self._app.errorRaised.emit("Probe Station RF sweep failed", str(exc))
            return
        self._set_busy(False)
        self._apply_rf(result.get("f", []), h21=result.get("h21"),
                       y21=result.get("y21"), y11=result.get("y11"))
        self._set_status("RF sweep complete")

    def _apply_rf(self, f, h21=None, y21=None, y11=None):
        self._rf_f = [float(v) for v in f]
        self._rf_h21 = [float(v) for v in h21] if h21 is not None else []
        try:
            ft = ch.estimate_ft(self._rf_f, h21=h21, y21=y21, y11=y11)
        except Exception:
            ft = float("nan")
        self._rf_extraction = [{
            "name": "fT (unity current-gain frequency)",
            "value": ft if math.isfinite(ft) else float("nan"),
            "unit": "Hz",
            "display": ch.engineering(ft, "Hz"),
            "note": "",
        }]
        self.rfChanged.emit()

    # -- status / busy ------------------------------------------------------
    def _set_status(self, text):
        self._status = text
        self.statusChanged.emit()

    def _set_busy(self, value):
        self._busy = value
        self.busyChanged.emit()

    @Property(str, notify=statusChanged)
    def status(self):
        return self._status

    @Property(bool, notify=busyChanged)
    def isBusy(self):
        return self._busy

    # -- QML-facing data -----------------------------------------------------
    @Property(str, notify=probeChanged)
    def sweepType(self):
        return self._sweep_type

    @Property(list, notify=probeChanged)
    def sweepX(self):
        return list(self._x)

    @Property(list, notify=probeChanged)
    def sweepY(self):
        return list(self._y)

    @Property(list, notify=probeChanged)
    def extractionModel(self):
        return list(self._extraction)

    @Property(list, notify=rfChanged)
    def rfFreq(self):
        return list(self._rf_f)

    @Property(list, notify=rfChanged)
    def rfH21(self):
        return list(self._rf_h21)

    @Property(list, notify=rfChanged)
    def rfModel(self):
        return list(self._rf_extraction)
