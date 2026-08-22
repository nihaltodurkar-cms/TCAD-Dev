"""Example 2 -- a small process flow, then the device it produces.

Flow:
    1. p-type substrate, N_A = 1e16 cm^-3
    2. Boron channel-stop check (skipped)
    3. Phosphorus implant, 50 keV, 3e14 cm^-2
    4. Drive-in / activation anneal, 950 C for 30 min
    5. Dry gate oxidation, 900 C for 1 h (bookkeeping only)
    6. Extract the junction depth and sheet resistance
    7. Hand the profile to the drift-diffusion solver and get the I-V

This is exactly the Sentaurus Process -> Sentaurus Device handoff, in ~60
lines.  Note step 4: the analytic erfc/Gaussian solutions do NOT apply after
an implant, because the starting profile is a Gaussian of finite width, not
a delta function -- so we diffuse numerically.

    python examples/02_process_flow.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pytcad import process, Device1D, Models, SILICON
from pytcad.mesh import graded_mesh
from pytcad.materials import mobility_caughey_thomas
from pytcad.constants import Q

# ------------------------------------------------------------ 1. substrate
L = 3.0e-4                       # 3 um [cm]
x = graded_mesh(L, [0.0, 3e-5], h_min=2e-8, h_max=1e-6, ratio=1.12)
Nsub = 1e16                      # p-type

# ------------------------------------------------------------ 2. implant
Rp, dRp = process.implant_moments("P", 50)
print(f"P, 50 keV:  Rp = {Rp*1e7:.1f} nm, dRp = {dRp*1e7:.1f} nm")
dose = 3e14                      # cm^-2
C_imp = process.implant(x, "P", 50, dose)
print(f"As-implanted peak = {C_imp.max():.3e} cm^-3")

# ------------------------------------------------------------ 3. anneal
T_anneal, t_anneal = 950.0, 30 * 60.0
D = process.diffusivity("P", T_anneal)
print(f"D(P, {T_anneal:.0f} C) = {D:.3e} cm^2/s,  "
      f"sqrt(4Dt) = {np.sqrt(4*D*t_anneal)*1e7:.1f} nm")
C_ann = process.diffuse_numeric(x, C_imp, "P", T_anneal, t_anneal)
print(f"Post-anneal surface conc. = {C_ann[0]:.3e} cm^-3")

net = C_ann - Nsub
xj = process.junction_depth(x, net)
print(f"Junction depth xj = {xj[0]*1e7:.1f} nm")

# ------------------------------------------------------------ 4. oxidation
tox = process.oxide_thickness(900.0, 1.0, ambient="dry")
print(f"Dry oxide, 900 C, 1 h: {tox*1e3:.1f} nm "
      f"(consumes {process.silicon_consumed(tox)*1e3:.1f} nm Si)")

# ------------------------------------------------------------ 5. Rs
mask = x <= xj[0]
mu_n = mobility_caughey_thomas(C_ann[mask] + Nsub, SILICON, 300.0, "n")
sigma = Q * mu_n * np.maximum(net[mask], 1.0)
Rs = 1.0 / np.trapezoid(sigma, x[mask])
print(f"Sheet resistance of the n-layer = {Rs:.1f} ohm/sq")

# ------------------------------------------------------------ 6. device
doping = net                                   # n on top, p below
Ntot = C_ann + Nsub                            # total ionised impurities
dev = Device1D(x, doping, Ntotal=Ntot, models=Models(bgn=True))
V = np.arange(0.0, 0.71, 0.05)
# forward-bias the p-side (right contact) relative to the n-side
J = dev.iv_sweep(-V, terminal=0, verbose=False)
print("\nDiode I-V (p-side positive):")
for v, j in zip(V, J):
    print(f"  V = {v:.2f} V   J = {abs(j):.4e} A/cm^2")

# ------------------------------------------------------------ plots
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
xu = x * 1e4
ax[0].semilogy(xu, C_imp, "--", label="as-implanted")
ax[0].semilogy(xu, C_ann, "-", label=f"after {T_anneal:.0f} C / 30 min")
ax[0].axhline(Nsub, color="k", lw=.8, label="substrate $N_A$")
ax[0].axvline(xj[0] * 1e4, color="r", lw=.8, ls=":", label="$x_j$")
ax[0].set_xlim(0, 0.6); ax[0].set_ylim(1e15, 1e21)
ax[0].set_xlabel("depth [$\\mu$m]"); ax[0].set_ylabel("cm$^{-3}$")
ax[0].set_title("Doping profile"); ax[0].legend(fontsize=8); ax[0].grid(alpha=.3)

ax[1].semilogy(V, np.abs(J), "o-", ms=3)
ax[1].set_xlabel("forward bias [V]"); ax[1].set_ylabel("|J| [A/cm$^2$]")
ax[1].set_title("Resulting diode I-V"); ax[1].grid(alpha=.3)
fig.tight_layout()
fig.savefig("process_flow.png", dpi=140)
print("\nWrote process_flow.png")
