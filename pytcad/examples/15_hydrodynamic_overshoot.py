"""Example 15 -- hydrodynamic / energy-balance local carrier-
temperature closure (M29).

This is the M29 acceptance demo: a local (no spatial energy-flux)
steady energy-balance closure computes carrier temperature Tn(E) from
a published energy relaxation time, from which (a) a "why overshoot
matters in short devices" length scale, (b) a qualitative field-driven
heating trend, and (c) a carrier-temperature-mediated route to the
existing (M15) published field-driven impact-ionization coefficients
are all derived. See pytcad/hydrodynamic.py's own module docstring for
the full honesty clause on what a LOCAL closure like this one cannot
capture (the actual spatial shape of a Monte Carlo overshoot profile).

    python examples/15_hydrodynamic_overshoot.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pytcad.hydrodynamic import (
    carrier_temperature, hot_carrier_heating_ratio, energy_relaxation_length,
    impact_ionization_rate_carrierT, TAU_W_N,
)
from pytcad.ionization import alpha_n, alpha_p
from pytcad.materials import SILICON

l_w = energy_relaxation_length(SILICON.vsat_n, TAU_W_N)
print(f"Energy relaxation length l_w = v_sat*tau_w = {l_w * 1e4:.4f} um")
print("(Sze & Ng: velocity overshoot matters once a device's own "
      "characteristic length is comparable to or below this scale --  "
      "the textbook reason overshoot is a submicron-device effect.)")

fields = np.logspace(2, 5.5, 60)
Tn = carrier_temperature(fields, SILICON.mu_n_max)
heating = hot_carrier_heating_ratio(fields, SILICON.mu_n_max)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
ax1.loglog(fields, Tn)
ax1.set_xlabel("E [V/cm]"); ax1.set_ylabel("Tn [K]")
ax1.set_title("Local carrier temperature vs field")
ax1.axhline(300.0, color="gray", ls="--", lw=1, label="lattice T")
ax1.legend()

ax2.loglog(fields, heating)
ax2.axhline(1.0, color="gray", ls="--", lw=1, label="equilibrium (no heating)")
ax2.set_xlabel("E [V/cm]"); ax2.set_ylabel("hot-carrier heating ratio")
ax2.set_title("Field-driven heating trend")
ax2.legend()
fig.tight_layout()
fig.savefig("hydrodynamic_overshoot.png", dpi=140)
print("\nWrote hydrodynamic_overshoot.png")

print(f"\nHeating ratio at E=1e2 V/cm (near-equilibrium): "
      f"{hot_carrier_heating_ratio(1e2, SILICON.mu_n_max):.4f}")
print(f"Heating ratio at E=2e5 V/cm (avalanche-relevant field): "
      f"{hot_carrier_heating_ratio(2e5, SILICON.mu_n_max):.4f}")

print("\n--- Carrier-temperature-driven impact ionization vs the "
      "published field model ---")
n, p, E = 1e15, 1e10, 3.5e5
Tn_e = carrier_temperature(E, SILICON.mu_n_max)
Tp_e = carrier_temperature(E, SILICON.mu_p_max)
G_carrierT = impact_ionization_rate_carrierT(
    n, p, Tn_e, Tp_e, SILICON.mu_n_max, SILICON.mu_p_max)
G_field = (alpha_n(E) * SILICON.mu_n_max * E * n
          + alpha_p(E) * SILICON.mu_p_max * E * p)
print(f"E = {E:.1e} V/cm   Tn = {Tn_e:.1f} K")
print(f"G (carrier-temperature route) = {G_carrierT:.6e} cm^-3 s^-1")
print(f"G (published M15 field model) = {G_field:.6e} cm^-3 s^-1")
print("(These match exactly by construction -- the carrier-temperature "
      "path reduces back to the same published coefficients, see "
      "hydrodynamic.py's own honesty clause for what this does and "
      "does not independently validate.)")
