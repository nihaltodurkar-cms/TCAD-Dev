"""Example 8 -- a LOCOS (LOCal Oxidation of Silicon) process flow.

This is the M23 "STI/LOCOS flow" acceptance demo: pad oxide -> nitride
mask -> field oxidation (with bird's-beak encroachment at the mask edge)
-> nitride/pad strip (bookkeeping only) -> a masked well implant that
respects the same mask edge.

Flow:
    1. Bare silicon wafer, flat.
    2. Thin pad oxide grown everywhere (unmasked -- this columns' oxide
       thickness must match 1D Deal-Grove exactly, which is exactly what
       pytcad.process2d.oxidize_2d's gate G1 guarantees).
    3. Nitride mask deposited and patterned: open in the "active" region
       (moat), masked over what will become the field/STI region.
    4. Long, hot field oxidation under the mask -- the moat grows a thick
       field oxide, the active region under nitride grows only a thin
       "field-suppressed" oxide, and the boundary between them tapers
       (bird's beak) rather than stepping discontinuously.
    5. A masked well implant into the still-open active region, showing
       the dose is blocked under the nitride/field-oxide stack and shows
       lateral straggle at the same mask edge.

Honesty note: the bird's-beak shape here comes from process2d's lateral
suppression-kernel model, not a solved 2D oxidant-diffusion or stress
PDE -- see pytcad/process2d.py's module docstring. Treat the geometry as
qualitatively LOCOS-shaped, not a quantitative match to a published
cross-section.

    python examples/08_locos_flow.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pytcad.process2d import (
    ProcessGeometry2D, deposit, oxidize_2d, implant_2d, mask_from_intervals,
)

# ------------------------------------------------------------ 1. wafer
L = 40e-4                                  # 40 um wide field of view [cm]
x = np.linspace(0.0, L, 401)
geom = ProcessGeometry2D(x)

# ------------------------------------------------------------ 2. pad oxide
geom = oxidize_2d(geom, T_C=900.0, t_hours=0.15, ambient="dry")   # ~thin pad ox
print(f"Pad oxide (uniform, unmasked): {geom.ox_thick_um.mean()*1000:.1f} nm "
      f"-- must match 1D Deal-Grove exactly (M23 gate G1).")

# ------------------------------------------------------------ 3. nitride mask
active = mask_from_intervals(x, [(12e-4, 28e-4)])       # active/moat region open
geom = deposit(geom, thickness_um=0.15, mask=~active)   # nitride only over field

# ------------------------------------------------------------ 4. field oxidation
before = geom.copy()
geom = oxidize_2d(geom, T_C=1000.0, t_hours=2.0, ambient="wet", mask=active,
                   masked_rate_fraction=0.03)
si_grown_check = geom.si_consumed_um - before.si_consumed_um
ox_grown_check = geom.ox_thick_um - before.ox_thick_um
assert np.allclose(si_grown_check, 0.44 * ox_grown_check, atol=1e-12), \
    "mass conservation (M23 gate G2) violated"

field_ox = geom.ox_thick_um[active].max()
under_nitride = geom.ox_thick_um[~active][0]     # far from any edge
print(f"Field oxide (moat, open):     {field_ox:.3f} um")
print(f"Under nitride (far-field):    {under_nitride*1000:.1f} nm "
      f"({under_nitride/field_ox*100:.1f}% of field rate)")

# ------------------------------------------------------------ 5. well implant
y = np.linspace(0.0, 1.5e-4, 301)      # 1.5 um depth
C = implant_2d(x, y, geom, species="B", energy_keV=50, dose=2e13,
               mask=active, lateral_straggle_ratio=0.8)
print(f"Peak boron conc. in the open moat: {C.max():.3e} cm^-3")
print(f"Peak boron conc. 2 um under the nitride (should be ~0): "
      f"{C[:, np.argmin(np.abs(x - 30e-4))].max():.3e} cm^-3")

# ------------------------------------------------------------ plots
fig, ax = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
xu = x * 1e4
ax[0].plot(xu, geom.ox_thick_um, "b-", label="oxide thickness")
ax[0].plot(xu, geom.surface_um, "k--", lw=0.8, label="surface height")
ax[0].axvspan(12, 28, color="orange", alpha=0.15, label="active (moat)")
ax[0].set_ylabel("thickness [$\\mu$m]")
ax[0].set_title("LOCOS field-oxidation cross-section (bird's beak at the mask edges)")
ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)

im = ax[1].pcolormesh(xu, y * 1e4, np.log10(np.maximum(C, 1e10)),
                       shading="auto", cmap="viridis")
ax[1].invert_yaxis()
ax[1].set_xlabel("lateral position [$\\mu$m]"); ax[1].set_ylabel("depth [$\\mu$m]")
ax[1].set_title("Masked boron well implant (log$_{10}$ cm$^{-3}$)")
fig.colorbar(im, ax=ax[1], label="log10(C)")
fig.tight_layout()
fig.savefig("locos_flow.png", dpi=140)
print("\nWrote locos_flow.png")
