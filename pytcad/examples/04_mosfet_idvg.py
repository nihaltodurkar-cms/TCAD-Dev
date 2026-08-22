"""Example 4 -- 2D n-channel MOSFET: Id-Vg transfer characteristic at fixed Vds.

Structure: Lg=600nm gate, Lsd=300nm source/drain regions, 200nm deep
substrate, Na=1e17 channel doping, Nsd_peak=1e19 source/drain, 5nm oxide,
sigma_y=50nm/sigma_lat=10nm junction grading. This geometry (wider gate,
tighter lateral doping spread than a naive first guess) keeps the
source/drain doping tails from merging under the gate, so the device shows
a genuine off state and a real subthreshold knee -- see
tests/test_validation_2d.py::_build_test_mosfet for the validated
parameters and the failure mode of the original 200nm/30nm geometry.
Long-channel enough that field-dependent mobility (not implemented in
Device2D -- see the design spec) isn't needed for a qualitatively correct
linear-region curve.

    python examples/04_mosfet_idvg.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pytcad.mosfet import build_mosfet, id_vg_sweep

dev = build_mosfet(Lg=6e-5, Lsd=3e-5, depth=2e-5, Na=1e17, Nsd_peak=1e19,
                   tox_cm=5e-7, gate="n+poly", sigma_y=5e-6, sigma_lat=1e-6,
                   nx=150, ny=80)

Vds = 0.05
Vg_list = np.linspace(-0.5, 1.5, 41)
Id = id_vg_sweep(dev, Vg_list, Vds)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
ax1.semilogy(Vg_list, np.abs(Id) + 1e-20)
ax1.set_xlabel("Vg [V]"); ax1.set_ylabel("|Id| [A/cm]"); ax1.set_title(f"Subthreshold (Vds={Vds} V)")
ax1.grid(True, which="both", alpha=0.3)

ax2.plot(Vg_list, Id * 1e6)
ax2.set_xlabel("Vg [V]"); ax2.set_ylabel("Id [uA/cm]"); ax2.set_title("Linear")
ax2.grid(True, alpha=0.3)

fig.tight_layout()
fig.savefig("mosfet_idvg.png", dpi=140)
print("Wrote mosfet_idvg.png")
