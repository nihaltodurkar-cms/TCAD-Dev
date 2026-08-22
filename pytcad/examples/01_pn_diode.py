"""Example 1 -- abrupt silicon p-n junction diode.

Runs a forward + reverse I-V sweep, checks the result against the analytic
short-base ideal-diode current, and plots bands and carrier profiles.

    python examples/01_pn_diode.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pytcad import Device1D, Models, NewtonOptions, SILICON
from pytcad.mesh import graded_mesh, check_mesh
from pytcad.materials import mobility_caughey_thomas, lifetime_scharfetter
from pytcad.constants import Q

# ----------------------------------------------------------------- geometry
L = 2.0e-4          # 2 um total [cm]
xj = 1.0e-4         # junction at 1 um
Na, Nd = 1e17, 1e17

x = graded_mesh(L, [xj], h_min=1.0e-8, h_max=1.0e-6, ratio=1.12)
doping = np.where(x < xj, -Na, Nd)          # p on the left, n on the right

print("Mesh:")
check_mesh(x, doping)

dev = Device1D(x, doping, T=300.0, models=Models(bgn=False, auger=True))
print(f"  scaling: L_D = {dev.LD*1e7:.2f} nm, N_scale = {dev.Ns:.2e} cm^-3")

# ----------------------------------------------------------------- built-in
dev.solve_equilibrium()
Vbi_sim = (dev.psi[-1] - dev.psi[0]) * dev.VT
Vbi_ana = dev.VT * np.log(Na * Nd / dev.ni**2)
print(f"\nBuilt-in potential: simulated {Vbi_sim:.4f} V, "
      f"analytic {Vbi_ana:.4f} V")

W_ana = np.sqrt(2 * dev.eps * Vbi_ana / Q * (1 / Na + 1 / Nd))
print(f"Depletion width (depletion approx.): {W_ana*1e7:.1f} nm")

# ----------------------------------------------------------------- I-V
V_fwd = np.arange(0.0, 0.76, 0.025)
print("\nForward sweep:")
J_fwd = dev.iv_sweep(V_fwd, verbose=False)

V_rev = -np.arange(0.0, 5.01, 0.25)
print("Reverse sweep:")
J_rev = dev.iv_sweep(V_rev, verbose=False)

# analytic short-base saturation current
Wp, Wn = xj - W_ana / 2, (L - xj) - W_ana / 2
Dn = mobility_caughey_thomas(Na, SILICON, 300.0, "n") * dev.VT
Dp = mobility_caughey_thomas(Nd, SILICON, 300.0, "p") * dev.VT
J0 = Q * dev.ni**2 * (Dp / (Wn * Nd) + Dn / (Wp * Na))
print(f"\nAnalytic short-base J0 = {J0:.3e} A/cm^2")
k = np.argmin(np.abs(V_fwd - 0.5))
print(f"At V = 0.5 V:  simulated {J_fwd[k]:.4e},  "
      f"ideal-diode {J0*np.exp(0.5/dev.VT):.4e} A/cm^2")

ideality = np.diff(V_fwd[8:]) / (dev.VT * np.diff(np.log(J_fwd[8:])))
print(f"Ideality factor over 0.2-0.75 V: {ideality.mean():.4f}")

# ----------------------------------------------------------------- profiles
dev.solve_bias([0.6, 0.0], NewtonOptions())
n_fwd, p_fwd = dev.n_cm3.copy(), dev.p_cm3.copy()
Ec, Ev, EFn, EFp = dev.band_diagram()

fig, ax = plt.subplots(2, 2, figsize=(11, 8))

ax[0, 0].semilogy(V_fwd, np.abs(J_fwd), "o-", ms=3, label="simulated")
ax[0, 0].semilogy(V_fwd, J0 * np.expm1(V_fwd / dev.VT), "--",
                  label="ideal diode")
ax[0, 0].set_xlabel("V [V]"); ax[0, 0].set_ylabel("|J| [A/cm$^2$]")
ax[0, 0].set_title("Forward I-V"); ax[0, 0].legend(); ax[0, 0].grid(alpha=.3)

ax[0, 1].plot(V_rev, J_rev * 1e9, "o-", ms=3)
ax[0, 1].set_xlabel("V [V]"); ax[0, 1].set_ylabel("J [nA/cm$^2$]")
ax[0, 1].set_title("Reverse leakage"); ax[0, 1].grid(alpha=.3)

xu = x * 1e4
ax[1, 0].plot(xu, Ec, label="$E_c$")
ax[1, 0].plot(xu, Ev, label="$E_v$")
ax[1, 0].plot(xu, EFn, "--", label="$E_{Fn}$")
ax[1, 0].plot(xu, EFp, ":", label="$E_{Fp}$")
ax[1, 0].set_xlabel("x [$\\mu$m]"); ax[1, 0].set_ylabel("Energy [eV]")
ax[1, 0].set_title("Band diagram at 0.6 V"); ax[1, 0].legend(fontsize=8)
ax[1, 0].grid(alpha=.3)

ax[1, 1].semilogy(xu, n_fwd, label="n")
ax[1, 1].semilogy(xu, p_fwd, label="p")
ax[1, 1].semilogy(xu, np.abs(doping), "k--", lw=.8, label="|N|")
ax[1, 1].set_ylim(1e4, 1e19)
ax[1, 1].set_xlabel("x [$\\mu$m]"); ax[1, 1].set_ylabel("cm$^{-3}$")
ax[1, 1].set_title("Carriers at 0.6 V"); ax[1, 1].legend(fontsize=8)
ax[1, 1].grid(alpha=.3)

fig.tight_layout()
fig.savefig("pn_diode.png", dpi=140)
print("\nWrote pn_diode.png")
