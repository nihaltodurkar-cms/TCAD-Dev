"""Example 3 -- MOS capacitor: quasi-static C-V and surface potential.

Shows accumulation -> depletion -> inversion for an n+ poly gate on p-type
silicon, and compares C_min and V_th against the depletion approximation.
Also sweeps the fixed oxide charge Q_f to show the flatband shift, which is
how C-V is actually used in a fab for oxide-quality monitoring.

    python examples/03_mos_cv.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pytcad import MOSCapacitor

tox = 5e-7          # 5 nm [cm]
Nsub = -1e17        # p-type, 1e17 cm^-3

mos = MOSCapacitor(Nsub, tox, gate="n+poly")
lm = mos.analytic_landmarks()
print("Depletion-approximation landmarks:")
print(f"  phi_F  = {lm['phi_F']*1e3:.1f} mV")
print(f"  W_max  = {lm['W_max']*1e7:.1f} nm")
print(f"  V_FB   = {lm['V_FB']:.3f} V")
print(f"  V_th   = {lm['V_th']:.3f} V")
print(f"  C_ox   = {lm['C_ox']*1e6:.3f} uF/cm^2")
print(f"  C_min  = {lm['C_min']*1e6:.3f} uF/cm^2")

Vg = np.linspace(-2.0, 2.0, 201)
phis, Qg, C = mos.cv_sweep(Vg)
print(f"\nNumerical: C_max = {C.max()*1e6:.3f} uF/cm^2, "
      f"C_min = {C.min()*1e6:.3f} uF/cm^2 at Vg = {Vg[np.argmin(C)]:.2f} V")

fig, ax = plt.subplots(1, 3, figsize=(14, 4))

for Qf in (0.0, 5e11, 1e12):
    m = MOSCapacitor(Nsub, tox, gate="n+poly", Qf=Qf)
    _, _, Cq = m.cv_sweep(Vg)
    ax[0].plot(Vg, Cq * 1e6, label=f"$Q_f$ = {Qf:.0e} cm$^{{-2}}$")
ax[0].axhline(lm["C_ox"] * 1e6, color="k", lw=.8, ls="--", label="$C_{ox}$")
ax[0].axhline(lm["C_min"] * 1e6, color="gray", lw=.8, ls=":",
              label="$C_{min}$ (depl. approx.)")
ax[0].set_xlabel("$V_G$ [V]"); ax[0].set_ylabel("C [$\\mu$F/cm$^2$]")
ax[0].set_title("Quasi-static C-V"); ax[0].legend(fontsize=7); ax[0].grid(alpha=.3)

ax[1].plot(Vg, phis)
ax[1].axhline(2 * lm["phi_F"], color="r", lw=.8, ls="--", label="$2\\phi_F$")
ax[1].set_xlabel("$V_G$ [V]"); ax[1].set_ylabel("$\\phi_s$ [V]")
ax[1].set_title("Surface potential"); ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)

for Vg_show in (-1.5, 0.0, 1.5):
    psi = mos.solve_psi(Vg_show)
    n = mos.nie_s * np.exp(np.clip(psi, -700, 700)) * mos.Ns
    p = mos.nie_s * np.exp(np.clip(-psi, -700, 700)) * mos.Ns
    ax[2].semilogy(mos.x * 1e7, n, label=f"n, $V_G$={Vg_show:+.1f} V")
ax[2].set_xlim(0, 100); ax[2].set_ylim(1e2, 1e20)
ax[2].set_xlabel("depth [nm]"); ax[2].set_ylabel("n [cm$^{-3}$]")
ax[2].set_title("Electron density"); ax[2].legend(fontsize=7); ax[2].grid(alpha=.3)

fig.tight_layout()
fig.savefig("mos_cv.png", dpi=140)
print("Wrote mos_cv.png")
