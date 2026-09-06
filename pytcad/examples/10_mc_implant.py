"""Example 10 -- Monte-Carlo (BCA) implantation vs. the analytic table,
and the channeling-tail signature on a "crystalline" target.

This is the M25 acceptance demo: calibrate the BCA model's electronic-
stopping prefactor against pytcad.process's existing SRIM-derived range
table at one energy, then show it tracks the table reasonably over a
few-x energy window (amorphous target), and show that turning on the
channeling knob produces a qualitatively deeper tail (crystalline-target
signature) -- see pytcad/mc_implant.py's honesty clause and "MEASURED
ACCURACY" note for exactly what this simplified model does and does not
capture.

    python examples/10_mc_implant.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pytcad import process
from pytcad.mc_implant import calibrate_electronic_stopping, mc_implant_bca

species, ref_E = "P", 50
k_e = calibrate_electronic_stopping(species, ref_E, n_ions=500, seed=1, n_refine=3)
print(f"Calibrated k_e for {species} against the table at {ref_E} keV: {k_e:.3e}")

print(f"\n{'E [keV]':>8}  {'Rp_tab [nm]':>12}  {'Rp_mc [nm]':>11}  {'ratio':>6}")
for E in (20, 30, 50, 70, 100):
    Rp_tab, _ = process.implant_moments(species, E)
    out = mc_implant_bca(species, E, k_e, n_ions=800, seed=2)
    print(f"{E:8d}  {Rp_tab*1e7:12.1f}  {out['Rp_cm']*1e7:11.1f}  "
          f"{out['Rp_cm']/Rp_tab:6.2f}")

# ------------------------------------------------------------ channeling
amorphous = mc_implant_bca(species, 50, k_e, n_ions=3000, seed=7)
crystalline = mc_implant_bca(species, 50, k_e, n_ions=3000, seed=7,
                              channeling_fraction=0.12,
                              channeling_length_mean_cm=2.5e-5)
print(f"\nAmorphous target:   Rp={amorphous['Rp_cm']*1e7:.1f} nm, "
      f"max depth={amorphous['depth_cm'].max()*1e7:.1f} nm")
print(f"'Crystalline' target: Rp={crystalline['Rp_cm']*1e7:.1f} nm, "
      f"max depth={crystalline['depth_cm'].max()*1e7:.1f} nm, "
      f"{crystalline['channeled_ever'].sum()} of "
      f"{len(crystalline['channeled_ever'])} ions channeled at some point")

fig, ax = plt.subplots(figsize=(7, 5))
bins = np.linspace(0, crystalline["depth_cm"].max() * 1e7, 80)
ax.hist(amorphous["depth_cm"][~amorphous["backscattered"]] * 1e7, bins=bins,
        density=True, alpha=0.6, label="amorphous")
ax.hist(crystalline["depth_cm"][~crystalline["backscattered"]] * 1e7, bins=bins,
        density=True, alpha=0.6, label="with channeling (qualitative)")
ax.set_yscale("log")
ax.set_xlabel("depth [nm]"); ax.set_ylabel("probability density")
ax.set_title(f"MC (BCA) {species} implant depth distribution, {50} keV")
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig("mc_implant.png", dpi=140)
print("\nWrote mc_implant.png")
