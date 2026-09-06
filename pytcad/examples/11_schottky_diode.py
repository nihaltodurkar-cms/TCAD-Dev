"""Example 11 -- Schottky diode I-V (thermionic emission + image-force
lowering) and the ohmic-limit / tunnel-contact regime crossover.

This is the M28 acceptance demo: a PtSi/n-Si-like Schottky contact's
I-V curve from ideal thermionic-emission theory, the image-force
barrier-lowering correction, and the Padovani-Stratton E00 regime
classification showing how heavily-doped contacts cross over from
thermionic emission into the field-emission ("tunnel", effectively
ohmic) regime -- see pytcad/schottky.py's honesty clause for exactly
what is simplified.

    python examples/11_schottky_diode.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pytcad.materials import SILICON
from pytcad.schottky import (
    richardson_constant_A0, richardson_a_star,
    schottky_barrier_height_n, schottky_iv,
    characteristic_tunneling_energy_E00_eV, contact_regime,
)

T = 300.0
A_star = richardson_a_star("Si", "n")
print(f"Free-electron Richardson constant A0 = {richardson_constant_A0():.3f} A/(cm^2 K^2) "
      f"(published: 120.173)")
print(f"Effective A*_n for Si = {A_star} A/(cm^2 K^2) (Sze & Ng)")

# PtSi/n-Si: published phi_Bn ~= 0.85 eV. Back out an effective metal
# work function against Si's electron affinity just to show the
# Schottky-Mott bookkeeping; the I-V below uses the published barrier
# directly (Fermi-level pinning makes the naive phi_m - chi rule
# unreliable for real interfaces -- see the module honesty clause).
phi_B = 0.85
phi_m_effective = phi_B + SILICON.chi
print(f"\nphi_Bn (PtSi/n-Si, published) = {phi_B} eV "
      f"(implies phi_m ~= {phi_m_effective:.2f} eV via Schottky-Mott)")

V = np.linspace(-0.2, 0.4, 200)
Nd = 1e16
J_ideal = schottky_iv(phi_B, T, V, A_star, image_force=False)
J_img = schottky_iv(phi_B, T, V, A_star, Nd_cm3=Nd, eps_r=SILICON.eps_r)

fig, ax = plt.subplots(figsize=(7, 5))
ax.semilogy(V, np.abs(J_ideal), label="ideal thermionic emission")
ax.semilogy(V, np.abs(J_img), "--", label=f"+ image-force lowering (Nd={Nd:.0e} cm^-3)")
ax.set_xlabel("V [V]"); ax.set_ylabel("|J| [A/cm^2]")
ax.set_title(f"Schottky diode I-V, phi_B={phi_B} eV, T={T:.0f} K")
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig("schottky_iv.png", dpi=140)
print("\nWrote schottky_iv.png")

# ------------------------------------------------------- regime sweep
print(f"\n{'Nd [cm^-3]':>12}  {'E00 [meV]':>10}  {'regime':>7}")
for Nd_scan in (1e15, 1e17, 1e19, 5e19, 5e20):
    E00 = characteristic_tunneling_energy_E00_eV(Nd_scan, SILICON.m_n_star, SILICON.eps_r)
    print(f"{Nd_scan:12.1e}  {E00 * 1000:10.2f}  {contact_regime(E00, T):>7}")

print("\nAs doping rises past ~1e19-1e20 cm^-3 the contact crosses from "
      "thermionic emission (TE) through the mixed TFE regime into field "
      "emission (FE) -- the physical basis for why degenerately-doped "
      "'ohmic' contacts conduct well despite a nonzero barrier.")
