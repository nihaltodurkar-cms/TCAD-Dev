"""Example 12 -- 3D tri-gate FinFET short-channel electrostatics: DIBL
and subthreshold-swing degradation as gate length shrinks.

This is the M26 acceptance demo: two otherwise-identical structured-
mesh tri-gate FinFETs (pytcad.finfet3d.build_finfet3d), one long-
channel and one short-channel, swept in Id-Vg at two drain biases and
compared via pytcad.characterization's Vth/SS/DIBL extractors. See
pytcad/finfet3d.py's module docstring for the full honesty clause on
what this model is (and is not): a structured tensor-product 3D mesh,
not unstructured tets; closed-form analytic doping, not a 2D-process-
extrusion pipeline; a LITERATURE-TREND comparison, not a fit to any
specific published curve.

Runtime: ~2 minutes (4 full 3D Id-Vg sweeps).

    python examples/12_finfet3d_dibl.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.simplefilter("ignore")

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pytcad.finfet3d import build_finfet3d, id_vg_sweep_3d
from pytcad.characterization import extract_subthreshold_swing, extract_dibl

Vg = np.linspace(-0.4, 1.2, 12)
COMMON = dict(Lsd=0.3e-6, Hfin=0.3e-6, Wfin=0.2e-6, tox_cm=2e-7,
              Na=5e17, Nsd_peak=1e19, sigma_y=0.05e-6, sigma_lat=0.05e-6,
              NX=6, NY=4, NZ=4, mesh_ratio=1.3)
VDS_LOW, VDS_HIGH, TARGET = 0.05, 0.3, 4e-7

results = {}
fig, ax = plt.subplots(figsize=(7, 5))
for Lg, label in ((1.5e-6, "long (Lg=1.5 um)"), (0.4e-6, "short (Lg=0.4 um)")):
    print(f"\n--- {label} ---")
    dev_low = build_finfet3d(Lg=Lg, **COMMON)
    Id_low = id_vg_sweep_3d(dev_low, Vg, Vds=VDS_LOW, verbose=False)
    dev_high = build_finfet3d(Lg=Lg, **COMMON)
    Id_high = id_vg_sweep_3d(dev_high, Vg, Vds=VDS_HIGH, verbose=False)

    ss = extract_subthreshold_swing(Vg, Id_low)
    dibl = extract_dibl(Vg, Id_low, Vg, Id_high, VDS_LOW, VDS_HIGH, target=TARGET)
    results[Lg] = (ss, dibl)
    print(f"  SS = {ss:.1f} mV/decade   DIBL = {dibl * 1000:.1f} mV/V")

    ax.semilogy(Vg, np.abs(Id_low), label=f"{label}, Vds={VDS_LOW} V")
    ax.semilogy(Vg, np.abs(Id_high), "--", label=f"{label}, Vds={VDS_HIGH} V")

ax.set_xlabel("Vg [V]"); ax.set_ylabel("|Id| [A]")
ax.set_title("Tri-gate FinFET Id-Vg: short-channel electrostatics")
ax.legend(fontsize=7)
fig.tight_layout()
fig.savefig("finfet3d_idvg.png", dpi=140)
print("\nWrote finfet3d_idvg.png")

ss_long, dibl_long = results[1.5e-6]
ss_short, dibl_short = results[0.4e-6]
print(f"\nSS long={ss_long:.1f}  short={ss_short:.1f} mV/decade "
      f"(literature trend: short >= long)")
print(f"DIBL long={dibl_long*1000:.1f}  short={dibl_short*1000:.1f} mV/V "
      f"(literature trend: short > long)")
