"""Tests for gui.services.characterization -- solver-independent DC/RF
device-characterization extraction used by the Virtual Probe Station panel.
Pure Python/NumPy: no Qt, no QT_QPA_PLATFORM needed."""
import math

import numpy as np
import pytest

from gui.services import characterization as ch


def _mosfet_transfer(vth=0.4, ss_mv_dec=90.0, beta=1.0e-3, vg_max=1.5, n=400):
    """Synthetic long-channel MOSFET transfer curve in the LINEAR (triode)
    region at small Vds -- the regime the linear-extrapolation Vth method is
    meant for: Id ~ beta*(Vg-Vth) above threshold (constant gm, so the
    extrapolated x-intercept of the strong-inversion slope IS Vth), joined
    to an exponential subthreshold region below Vth, continuous in current
    at the boundary."""
    vg = np.linspace(-0.2, vg_max, n)
    ss_v_dec = ss_mv_dec / 1000.0
    ioff = 1.0e-12
    id_sub = ioff * 10.0 ** ((vg - 0.0) / ss_v_dec)
    idx_vth = np.searchsorted(vg, vth)
    id_at_vth = id_sub[idx_vth]
    id_strong = np.where(vg > vth, id_at_vth + beta * (vg - vth), 0.0)
    ids = np.where(vg <= vth, id_sub, id_strong)
    ids = np.clip(ids, 1e-15, None)
    return vg, ids


def _output_curve(vd_max=1.5, gds_target=1.0e-5, id_sat=5.0e-4, n=200):
    """Synthetic output curve (Id vs Vd) with a knee then a gently sloped
    saturation tail of slope gds_target."""
    vd = np.linspace(0.0, vd_max, n)
    knee = 0.3
    lin = id_sat * np.clip(vd / knee, 0.0, 1.0)
    tail = np.where(vd > knee, gds_target * (vd - knee), 0.0)
    ids = lin + tail
    return vd, ids


def _breakdown_curve(bv=12.0, n=300):
    """Synthetic reverse-bias avalanche curve: negligible leakage, then a
    sharp current rise at bv."""
    vd = np.linspace(0.0, 20.0, n)
    ids = 1.0e-10 + 1.0e-3 / (1.0 + np.exp(-(vd - bv) * 8.0))
    return vd, ids


def _single_pole_h21(ft=5.0e9, n=100):
    """|H21(f)| for a single-pole current-gain roll-off with unity-gain
    frequency ft: |H21(f)| = ft / f above the pole."""
    f = np.logspace(6, 11, n)
    h21 = ft / f
    return f, h21


class TestEngineering:
    def test_basic(self):
        assert ch.engineering(1.5e-9, "A") == "1.5 nA"
        assert ch.engineering(0.0, "V") == "0 V"

    def test_nonfinite(self):
        assert ch.engineering(float("nan")) == "n/a"
        assert ch.engineering(float("inf")) == "n/a"


class TestTransferExtraction:
    def test_vth_linear_reasonable(self):
        vg, ids = _mosfet_transfer(vth=0.4)
        vth = ch.extract_vth_linear(vg, ids)
        assert math.isfinite(vth)
        assert 0.2 < vth < 0.7

    def test_vth_constant_current(self):
        vg, ids = _mosfet_transfer(vth=0.4)
        vth = ch.extract_vth_constant_current(vg, ids, target=1.0e-7)
        assert math.isfinite(vth)
        assert 0.0 < vth < 1.0

    def test_subthreshold_swing_sane_range(self):
        vg, ids = _mosfet_transfer(vth=0.4, ss_mv_dec=90.0)
        ss = ch.extract_subthreshold_swing(vg, ids)
        assert math.isfinite(ss)
        assert 40.0 < ss < 180.0

    def test_on_off_ratio_large(self):
        vg, ids = _mosfet_transfer(vth=0.4)
        ratio = ch.extract_on_off_ratio(vg, ids)
        assert math.isfinite(ratio)
        assert ratio > 1.0e6

    def test_report_transfer(self):
        vg, ids = _mosfet_transfer(vth=0.4)
        rows = ch.build_extraction_report("transfer", vg, ids)
        names = [r["name"] for r in rows]
        assert "Vth (linear extrapolation)" in names
        assert "Subthreshold swing" in names
        assert all(math.isfinite(r["value"]) for r in rows)


class TestOutputExtraction:
    def test_gds_ro_finite_positive(self):
        vd, ids = _output_curve(gds_target=1.0e-5)
        gds, ro = ch.extract_output_conductance(vd, ids)
        assert math.isfinite(gds) and gds > 0.0
        assert math.isfinite(ro) and ro > 0.0
        assert ro == pytest.approx(1.0 / gds, rel=1e-9)

    def test_gds_close_to_injected(self):
        vd, ids = _output_curve(gds_target=1.0e-5)
        gds, _ = ch.extract_output_conductance(vd, ids)
        assert gds == pytest.approx(1.0e-5, rel=0.15)

    def test_report_output(self):
        vd, ids = _output_curve()
        rows = ch.build_extraction_report("output", vd, ids)
        assert any(r["name"] == "Output conductance" for r in rows)


class TestBreakdown:
    def test_bv_in_expected_range(self):
        vd, ids = _breakdown_curve(bv=12.0)
        bv = ch.extract_breakdown_voltage(vd, ids, current_limit=1.0e-6)
        assert math.isfinite(bv)
        assert 10.0 < bv < 14.0

    def test_report_breakdown(self):
        vd, ids = _breakdown_curve(bv=12.0)
        rows = ch.build_extraction_report("breakdown", vd, ids,
                                          meta={"current_limit": 1.0e-6})
        bv_row = next(r for r in rows if r["name"] == "Breakdown voltage")
        assert 10.0 < bv_row["value"] < 14.0


class TestFtEstimate:
    def test_ft_from_h21_within_tolerance(self):
        f, h21 = _single_pole_h21(ft=5.0e9)
        ft = ch.estimate_ft(f, h21=h21)
        assert math.isfinite(ft)
        assert ft == pytest.approx(5.0e9, rel=0.15)

    def test_ft_from_y21_y11_approx(self):
        f, h21 = _single_pole_h21(ft=3.0e9)
        # |Y21/Y11| approximation: fabricate y11=1, y21=h21 so the ratio
        # reduces to the same single-pole magnitude curve.
        y11 = np.ones_like(h21)
        ft = ch.estimate_ft(f, y21=h21, y11=y11)
        assert math.isfinite(ft)
        assert ft == pytest.approx(3.0e9, rel=0.15)

    def test_ft_missing_data_is_nan(self):
        f, _ = _single_pole_h21()
        assert math.isnan(ch.estimate_ft(f))


class TestDegenerate:
    def test_empty_input(self):
        assert math.isnan(ch.extract_vth_linear([], []))
        assert math.isnan(ch.extract_subthreshold_swing([], []))
        assert ch.build_extraction_report("transfer", [], []) == []

    def test_unsupported_sweep_type(self):
        rows = ch.build_extraction_report("nonsense", [0, 1], [0, 1])
        assert rows[0]["name"] == "Unsupported sweep type"
