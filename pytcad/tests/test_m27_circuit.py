"""M27 structural/consistency gates: the MNA circuit solver
(pytcad/circuit.py).

The three headline acceptance gates (resistor divider vs analytic,
device-in-circuit vs device-only, ring-oscillator transient smoke
test) live in test_model_benchmarks.py per house rule. This file
covers cheaper structural/unit checks on each element and on the MNA
machinery itself.

See circuit.py's own module docstring for the honesty clause on what
is simplified (finite-difference, not analytic-Jacobian, device
conductance; no MOSFET body effect or subthreshold conduction;
backward-Euler only; DeviceStamp is quasi-static per transient step).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from pytcad.circuit import (
    Circuit, VSource, ISource, Resistor, Capacitor, Diode, MOSFET1, GND,
)


def test_isource_drives_a_resistor_to_ohms_law():
    c = Circuit()
    c.add(ISource("I1", "a", GND, 1.0e-3))
    c.add(Resistor("R1", "a", GND, 1000.0))
    x, mna = c.dc_operating_point()
    va = Circuit.node_voltage(x, mna, "a")
    assert va == pytest.approx(1.0e-3 * 1000.0, rel=1e-6)


def test_two_resistors_in_series_share_current():
    c = Circuit()
    c.add(VSource("V1", "in", GND, 10.0))
    c.add(Resistor("R1", "in", "mid", 100.0))
    c.add(Resistor("R2", "mid", GND, 100.0))
    x, mna = c.dc_operating_point()
    assert Circuit.node_voltage(x, mna, "mid") == pytest.approx(5.0, rel=1e-6)


def test_diode_forward_current_matches_shockley_equation():
    c = Circuit()
    c.add(VSource("V1", "in", GND, 1.0))
    c.add(Resistor("R1", "in", "a", 200.0))
    c.add(Diode("D1", "a", GND, Is=1e-13, N=1.0, VT=0.025852))
    x, mna = c.dc_operating_point()
    va = Circuit.node_voltage(x, mna, "a")
    I_diode = 1e-13 * (np.exp(va / 0.025852) - 1.0)
    I_kirchhoff = (1.0 - va) / 200.0
    assert I_diode == pytest.approx(I_kirchhoff, rel=1e-4)


def test_diode_reverse_bias_current_is_essentially_saturation_current():
    c = Circuit()
    c.add(VSource("V1", "in", GND, -2.0))
    c.add(Resistor("R1", "in", "a", 1000.0))
    c.add(Diode("D1", "a", GND, Is=1e-13, N=1.0))
    x, mna = c.dc_operating_point()
    va = Circuit.node_voltage(x, mna, "a")
    assert va == pytest.approx(-2.0, abs=1e-6)   # negligible drop across R1


def test_mosfet1_off_state_carries_zero_current():
    c = Circuit()
    c.add(VSource("VDD", "vdd", GND, 5.0))
    c.add(VSource("VG", "g", GND, 0.0))
    c.add(Resistor("RD", "vdd", "d", 1000.0))
    c.add(MOSFET1("M1", "d", "g", GND, kind="n", Vt0=0.7))
    x, mna = c.dc_operating_point()
    vd = Circuit.node_voltage(x, mna, "d")
    assert vd == pytest.approx(5.0, abs=1e-6)   # no drop: Id ~= 0


def test_mosfet1_saturation_current_matches_square_law_by_hand():
    c = Circuit()
    VDD, VG = 5.0, 2.0
    c.add(VSource("VDD", "vdd", GND, VDD))
    c.add(VSource("VG", "g", GND, VG))
    c.add(Resistor("RD", "vdd", "d", 1000.0))
    c.add(MOSFET1("M1", "d", "g", GND, kind="n", Vt0=0.7, kp=2e-4,
                 W_L=10.0, lam=0.02))
    x, mna = c.dc_operating_point()
    vd = Circuit.node_voltage(x, mna, "d")
    beta, Vt, lam = 2e-4 * 10.0, 0.7, 0.02
    vov = VG - Vt
    if vd < vov:
        Id_hand = beta * (vov * vd - 0.5 * vd ** 2) * (1 + lam * vd)
    else:
        Id_hand = 0.5 * beta * vov ** 2 * (1 + lam * vd)
    Id_via_R = (VDD - vd) / 1000.0
    assert Id_via_R == pytest.approx(Id_hand, rel=1e-4)


def test_mosfet1_rejects_unknown_kind():
    with pytest.raises(ValueError):
        MOSFET1("M1", "d", "g", "s", kind="x")


def test_capacitor_is_open_circuit_at_dc():
    """A capacitor in series with nothing else conducting must leave
    its far node floating at 0 (the floating-node guard's tiny
    conductance to ground), not force any particular voltage."""
    c = Circuit()
    c.add(VSource("V1", "in", GND, 3.0))
    c.add(Resistor("R1", "in", "a", 1000.0))
    c.add(Capacitor("C1", "a", GND, 1e-9))
    x, mna = c.dc_operating_point()
    va = Circuit.node_voltage(x, mna, "a")
    assert va == pytest.approx(3.0, abs=1e-6)   # no DC current through C1


def test_transient_rc_charging_matches_analytic_exponential():
    """A series R-C charging from an uncharged capacitor must follow
    v(t) = V*(1 - exp(-t/RC)) under backward-Euler to within its own
    first-order truncation error at a modest dt/RC ratio. The source
    has been at V forever (no switch in this netlist), so the true DC
    operating point is already the FULLY CHARGED capacitor -- an
    explicit `initial_conditions` override is what actually models a
    step turned on at t=0 (see circuit.py's own `transient()`
    docstring for why that parameter exists)."""
    R, C, V = 1000.0, 1e-9, 1.0
    tau = R * C
    c = Circuit()
    c.add(VSource("V1", "in", GND, V))
    c.add(Resistor("R1", "in", "a", R))
    c.add(Capacitor("C1", "a", GND, C))
    dt = tau / 50.0
    times, hist, mna = c.transient(t_stop=3 * tau, dt=dt,
                                   initial_conditions={"a": 0.0})
    va = hist[:, mna.idx("a")]
    expected = V * (1.0 - np.exp(-times / tau))
    assert np.max(np.abs(va - expected)) < 0.02 * V


def test_device_stamp_conductance_is_positive_for_a_forward_biased_diode():
    from pytcad.mesh import graded_mesh
    from pytcad.device import Device1D
    from pytcad.circuit import DeviceStamp

    x = graded_mesh(2e-4, [1e-4], 5e-7, 6e-6, 1.2)
    doping = np.where(x < 1e-4, -1e17, 1e17)
    dev = Device1D(x, doping)
    stamp = DeviceStamp("D1", "a", GND, dev, area_cm2=1e-4)
    mna_size = 1
    class _FakeMNA:
        def idx(self, name):
            return 0 if name == "a" else None
    G = np.zeros((mna_size, mna_size))
    z = np.zeros(mna_size)
    stamp.stamp(_FakeMNA(), np.array([0.5]), G, z)
    assert G[0, 0] > 0.0   # forward conduction: dI/dV > 0
