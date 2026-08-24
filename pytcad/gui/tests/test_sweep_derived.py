"""v0.4 derived readouts computed FROM CURVE DATA ONLY.

No new semiconductor physics: every quantity here is a geometric readout
of an already-computed sweep.  The Vth extraction is deliberately the
SAME max-transconductance tangent method validated in
pytcad/tests/test_validation_2d.py (_extract_vth_max_gm, 0.1 V tolerance
against the MOSCapacitor analytic landmark) -- promoted into the Qt-free
service layer, not reinvented.  Non-converged points are excluded from
every statistic before anything is reported.
"""
import json
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.result_store import NpzResultStore, SweepResult
from gui.services.sweep_derived import (
    current_extremes, on_off_ratio, summarize, threshold_voltage_max_gm,
)


# ----------------------------------------------------------------------
#  pure-function behaviour on synthetic curves
# ----------------------------------------------------------------------
def test_on_off_ratio_basic():
    I = np.array([1e-9, 1e-7, 1e-5, 1e-3])
    assert on_off_ratio(I) == pytest.approx(1e6)


def test_on_off_ratio_uses_magnitudes_and_drops_nonpositive():
    # reverse-sign convention / exact zero must not break the ratio
    I = np.array([0.0, -1e-9, 1e-3])
    assert on_off_ratio(I) == pytest.approx(1e-3 / 1e-9)


def test_on_off_ratio_returns_none_when_not_meaningful():
    assert on_off_ratio(np.array([0.0, 0.0])) is None          # nothing on
    assert on_off_ratio(np.array([1e-3])) is None              # single point
    assert on_off_ratio(np.array([np.nan, 1e-3])) is None      # one valid


def test_current_extremes_signed_over_valid_points():
    lo, hi = current_extremes(np.array([1e-12, -1e-4, 1e-3]))
    assert lo == pytest.approx(-1e-4)
    assert hi == pytest.approx(1e-3)
    assert np.isnan(current_extremes(np.array([np.nan, np.nan]))[0])

def test_threshold_on_ideal_linear_curve():
    """For I = g*(Vg - Vth) the tangent method must recover Vth exactly."""
    Vg = np.linspace(0.0, 1.0, 21)
    g, vth_true = 1e-3, 0.4
    Id = g * (Vg - vth_true)
    got = threshold_voltage_max_gm(Vg, Id, vds=0.0)
    assert got == pytest.approx(vth_true, abs=1e-12)


def test_threshold_applies_the_vds_correction():
    Vg = np.linspace(0.0, 1.0, 21)
    Id = 1e-3 * (Vg - 0.4)
    no_corr = threshold_voltage_max_gm(Vg, Id, vds=0.0)
    with_corr = threshold_voltage_max_gm(Vg, Id, vds=0.05)
    assert no_corr - with_corr == pytest.approx(0.025)


def test_threshold_ignores_non_converged_points():
    """A NaN hole in the curve must change nothing versus the clean
    curve built from the same valid points -- never poison the fit."""
    Vg = np.linspace(0.0, 1.0, 21)
    Id = 1e-3 * (Vg - 0.4)
    holed = Id.copy(); holed[7] = np.nan; holed[8] = np.nan
    clean_v = np.delete(Vg, [7, 8]); clean_i = np.delete(Id, [7, 8])
    assert threshold_voltage_max_gm(Vg, holed) == \
        pytest.approx(threshold_voltage_max_gm(clean_v, clean_i))


def test_threshold_returns_none_without_enough_valid_points():
    assert threshold_voltage_max_gm(np.array([0.0]), np.array([1e-6])) is None
    assert threshold_voltage_max_gm(
        np.array([0.0, 0.5]), np.array([np.nan, 1e-6])) is None
    assert threshold_voltage_max_gm(
        np.array([0.0, 0.5, 1.0]), np.array([0.0, 0.0, 0.0])) is None  # gm == 0


# ----------------------------------------------------------------------
#  summarize(): NaN-safe aggregate over a SweepResult
# ----------------------------------------------------------------------
def _sweep_result(converged, currents, unit="A/cm"):
    n = len(currents)
    return SweepResult(
        contact="gate", meta={"contact": "gate"},
        voltages=np.linspace(-1, 1, n),
        converged=np.asarray(converged, dtype=bool),
        channels={"drain": np.asarray(currents, dtype=float)}, unit=unit)


def test_summarize_reports_counts_and_extremes():
    sw = _sweep_result([True] * 11, np.concatenate([[1e-12], np.logspace(-9, -3, 10)]))
    s = summarize(sw)
    assert s["points_total"] == 11
    assert s["points_converged"] == 11
    assert s["current_max"] == pytest.approx(1e-3)
    assert s["current_min"] == pytest.approx(1e-12)
    assert s["on_off_ratio"] == pytest.approx(1e9)


def test_summarize_excludes_non_converged_points():
    conv = [True] * 11
    I = np.concatenate([[1e-12], np.logspace(-9, -3, 10)])
    # invalidate everything but the last point: a single valid magnitude
    # defines no ratio, and the extremes must come only from valid data
    conv[:10] = [False] * 10
    I[:10] = np.nan
    s = summarize(_sweep_result(conv, I))
    assert s["points_converged"] == 1
    assert s["current_max"] == s["current_min"] == pytest.approx(1e-3)
    assert "on_off_ratio" not in s, \
        "one valid point must not produce an on/off ratio"


def test_summarize_all_invalid_curve_is_safe():
    s = summarize(_sweep_result([False] * 4, [np.nan] * 4))
    assert s["points_total"] == 4
    assert s["points_converged"] == 0
    assert "current_max" not in s and "on_off_ratio" not in s


# ----------------------------------------------------------------------
#  physics validation: the promoted method stays faithful to the backend
# ----------------------------------------------------------------------
def test_extracted_vth_matches_backend_landmark():
    """Same device, sweep, method and tolerance as the backend's own
    validated MOSFET Vth test -- proving the service-layer promotion did
    not alter the extraction.  Runs the real pytcad solver (~seconds)."""
    from pytcad.mosfet import build_mosfet, id_vg_sweep
    from pytcad.moscap import MOSCapacitor

    Na, tox_cm = 1e17, 5e-7
    dev = build_mosfet(Lg=6e-5, Lsd=3e-5, depth=2e-5, Na=Na, Nsd_peak=1e19,
                       tox_cm=tox_cm, gate="n+poly", sigma_y=5e-6,
                       sigma_lat=1e-6, nx=90, ny=50)
    Vg_list = np.linspace(-1.0, 1.0, 21)
    Id = id_vg_sweep(dev, Vg_list, Vds=0.05, verbose=False)

    mos = MOSCapacitor(Nsub=-Na, tox_cm=tox_cm, gate="n+poly")
    landmark = mos.analytic_landmarks()["V_th"]

    extracted = threshold_voltage_max_gm(Vg_list, Id, vds=0.05)
    assert extracted is not None
    assert abs(extracted - landmark) < 0.1, \
        f"Vth={extracted:.4f} V vs landmark={landmark:.4f} V"

    ratio = on_off_ratio(Id)
    assert ratio is not None and ratio > 1e6


# ----------------------------------------------------------------------
#  controller reachability: rows appear in the Results tree node
# ----------------------------------------------------------------------
def test_results_node_shows_sweep_derived_rows(qapp=None, tmp_path=None):
    from PySide6.QtCore import QCoreApplication
    qapp = QCoreApplication.instance() or QCoreApplication([])
    from gui.controllers.app_controller import AppController

    app = AppController()
    d = {
        "dimensionality": np.array(1),
        "axis_x": np.array([0.0, 1e-4]),
        "field__potential": np.array([0.0, 1.0]),
        "unit__potential": np.array("V"),
        "field__doping": np.array([1e17, 1e17]),
        "unit__doping": np.array("cm^-3"),
        "solved_bias": np.array(True),
        "sweep__voltage": np.array([-1.0, -0.5, 0.0, 0.5]),
        "sweep__converged": np.array([True, True, True, True]),
        "unit__sweep_current": np.array("A/cm^2"),
        "sweep__meta": np.array(json.dumps(
            {"contact": "left", "start": -1.0, "stop": 0.5,
             "step": 0.5, "dimensionality": 1})),
        "sweep__current__device": np.array([1e-12, 1e-9, 1e-6, 1e-3]),
    }
    path = "/tmp/opencode/sweep_derived_test.npz"
    os.makedirs("/tmp/opencode", exist_ok=True)
    np.savez(path + ".tmp.npz", **d)
    os.replace(path + ".tmp.npz", path)

    # a result only ever exists after a run, and a run requires a spec --
    # mirror that real state instead of poking at internals' order
    from gui.services.device_spec import ContactSpec, DeviceSpec, DopingSpec, MeshSpec
    app.spec = DeviceSpec(
        mesh=MeshSpec(dimensionality=1, axes={"x": [0.0, 1e-4]}),
        doping=DopingSpec(kind="array", values=[1e17, 1e17]),
        contacts=[
            ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
            ContactSpec(name="right", kind="ohmic", nodes={"i": [1]}, V=0.0),
        ])
    app._on_finished(path)

    rows = dict(app._properties_for("results"))
    assert any("Sweep" in k for k in rows), rows
    assert rows["Sweep points"] == "4 of 4 converged"
    assert "A/cm^2" in rows["Sweep Imax (left)"], rows["Sweep Imax (left)"]
    # Final review M-2: 'left' is an ohmic contact here, so Ion/Ioff and
    # a threshold are not meaningful for this output-characteristic
    # sweep and must be absent (gate-swept rows are covered in
    # test_v04_review_fixes.py).
    assert "Sweep Ion/Ioff" not in rows
    assert "Sweep Vth (max-gm est.)" not in rows
