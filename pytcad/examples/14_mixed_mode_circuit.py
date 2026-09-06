"""Example 14 -- mixed-mode device + circuit (M27).

Three acceptance demos in one script:

  1. A resistor voltage divider, checked against the textbook analytic
     result.
  2. A real pytcad Device1D p-n junction embedded via
     pytcad.circuit.DeviceStamp in a resistor-loaded circuit, checked
     against solving the SAME device standalone at the circuit-
     computed terminal voltage.
  3. A 3-stage CMOS (level-1 MOSFET) ring oscillator transient run,
     started from a symmetry-broken initial condition -- see
     pytcad/circuit.py's own module docstring for the full honesty
     clause (finite-difference device conductance, no MOSFET body
     effect/subthreshold conduction, backward-Euler only).

    python examples/14_mixed_mode_circuit.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pytcad.circuit import (
    Circuit, VSource, Resistor, Capacitor, Diode, MOSFET1, DeviceStamp, GND,
)
from pytcad.mesh import graded_mesh
from pytcad.device import Device1D

print("--- 1. Resistor divider ---")
c1 = Circuit()
c1.add(VSource("V1", "in", GND, 5.0))
c1.add(Resistor("R1", "in", "mid", 1000.0))
c1.add(Resistor("R2", "mid", GND, 2000.0))
x, mna = c1.dc_operating_point()
v_mid = Circuit.node_voltage(x, mna, "mid")
print(f"  V(mid) = {v_mid:.4f} V  (analytic: {5.0 * 2000 / 3000:.4f} V)")

print("\n--- 2. Device-in-circuit vs device-only ---")
xg = graded_mesh(2e-4, [1e-4], 5e-7, 6e-6, 1.2)
doping = np.where(xg < 1e-4, -1e17, 1e17)
dev = Device1D(xg, doping)
c2 = Circuit()
c2.add(VSource("V1", "in", GND, 0.5))
c2.add(Resistor("R1", "in", "a", 500.0))
stamp = c2.add(DeviceStamp("D1", "a", GND, dev, area_cm2=1e-4))
x2, mna2 = c2.dc_operating_point(max_iter=40)
va = Circuit.node_voltage(x2, mna2, "a")
dev_only = Device1D(xg, doping)
dev_only.solve_bias([va, 0.0])
J, _ = dev_only.current_density()
print(f"  V(a) = {va:.4f} V")
print(f"  I from circuit stamp   = {stamp.last_current:.6e} A")
print(f"  I from standalone solve = {J * 1e-4:.6e} A")

print("\n--- 3. 3-stage CMOS ring oscillator (transient) ---")
c3 = Circuit()
VDD = 5.0
c3.add(VSource("VDD", "vdd", GND, VDD))
nodes = [f"n{i}" for i in range(3)]
for i in range(3):
    out, inp = nodes[i], nodes[(i - 1) % 3]
    c3.add(MOSFET1(f"MP{i}", "vdd", inp, out, kind="p", Vt0=-0.7,
                  kp=4e-4, W_L=10.0, lam=0.02))
    c3.add(MOSFET1(f"MN{i}", out, inp, GND, kind="n", Vt0=0.7,
                  kp=2e-4, W_L=10.0, lam=0.02))
    c3.add(Capacitor(f"C{i}", out, GND, 1e-12))

times, hist, mna3 = c3.transient(
    t_stop=4e-8, dt=2e-11,
    initial_conditions={"n0": 4.5, "n1": 0.5, "n2": 2.5})
v0 = hist[:, mna3.idx("n0")]
crossings = int(np.sum(np.diff(np.sign(v0 - VDD / 2.0)) != 0))
print(f"  n0 swing: [{v0.min():.3f}, {v0.max():.3f}] V, "
      f"{crossings} threshold crossings over {times[-1] * 1e9:.1f} ns")

fig, ax = plt.subplots(figsize=(8, 4))
for i, name in enumerate(nodes):
    ax.plot(times * 1e9, hist[:, mna3.idx(name)], label=name)
ax.set_xlabel("t [ns]"); ax.set_ylabel("V [V]")
ax.set_title("3-stage CMOS ring oscillator (M27 mixed-mode circuit)")
ax.legend()
fig.tight_layout()
fig.savefig("ring_oscillator.png", dpi=140)
print("  Wrote ring_oscillator.png")
