"""Example 9 -- transient-enhanced diffusion (TED) after an implant.

This is the M24 acceptance demo: a boron implant is annealed twice, once
with the ordinary constant-D model (pytcad.process.diffuse_numeric) and
once with the "+1" lumped TED model (pytcad.ted.diffuse_with_defects),
showing the extra near-term spread TED produces and that it saturates
rather than growing like sqrt(Dt) forever -- see pytcad/ted.py's honesty
clause for exactly what this lumped model does and does not capture.

    python examples/09_ted_anneal.py
"""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pytcad import process
from pytcad.ted import diffuse_with_defects, ted_plus_one_S0

# ------------------------------------------------------------ implant
# A light threshold-adjust-style implant, deliberately low-dose: the "+1"
# model's supersaturation scales as dose/damage_depth/C_I_eq, and real
# moderate-to-high-dose implants (>=1e13 cm^-2 over a few tens of nm) push
# S0 into the 1e3-1e6 range per the TED literature (Jain/Chakravarthi
# et al.) -- physically real, but that regime also involves {311}
# extended-defect formation and interstitial clustering that this lumped
# single-scalar model does NOT capture (see pytcad/ted.py's honesty
# clause), so a naive multiplicative D-boost there is not credible. This
# example deliberately stays in the dilute regime where the lumped model
# is a reasonable qualitative illustration.
x = np.linspace(0.0, 3e-4, 601)
dose = 1e12
C0 = process.implant(x, "B", 30, dose)

# ------------------------------------------------------------ "+1" TED IC
damage_depth = 5e-6           # roughly the implant range, order-of-magnitude
C_I_eq = 1e15                 # equilibrium interstitial conc. placeholder [cm^-3]
S0 = ted_plus_one_S0(dose, damage_depth, C_I_eq)
tau = 15.0                    # s, engineering-level TED decay time
print(f"'+1' initial supersaturation S0 = {S0:.2e}, decay tau = {tau:.0f} s")

def width(x, C):
    """RMS profile width (second moment) -- a robust spread metric that
    doesn't depend on an arbitrary background-crossing threshold, unlike
    junction_depth() against a flat substrate that this light implant
    doesn't really have."""
    return float(np.sqrt(np.trapezoid(C * x**2, x) / np.trapezoid(C, x)))

T_C, anneal_times = 950.0, [30.0, 300.0, 1800.0]
fig, ax = plt.subplots(figsize=(7, 5))
w_bare_prev = None
for t in anneal_times:
    bare = process.diffuse_numeric(x, C0, "B", T_C, t)
    ted = diffuse_with_defects(x, C0, "B", T_C, t, ted_S0=S0, ted_tau_s=tau)
    w_bare, w_ted = width(x, bare), width(x, ted)
    extra = w_ted - w_bare
    print(f"t={t:7.0f}s   width(no TED)={w_bare*1e7:6.1f} nm   "
          f"width(TED)={w_ted*1e7:6.1f} nm   extra={extra*1e7:6.1f} nm")
    ax.semilogy(x * 1e4, ted, label=f"TED, t={t:.0f}s")
    ax.semilogy(x * 1e4, bare, "--", lw=0.8, label=f"no TED, t={t:.0f}s")

ax.set_xlim(0, 1.0); ax.set_ylim(1e14, 1e21)
ax.set_xlabel("depth [$\\mu$m]"); ax.set_ylabel("B concentration [cm$^{-3}$]")
ax.set_title("TED vs. constant-D anneal (M24 demo)")
ax.legend(fontsize=7); ax.grid(alpha=.3)
fig.tight_layout()
fig.savefig("ted_anneal.png", dpi=140)
print("\nWrote ted_anneal.png")
print("\nThe 'extra' spread from TED should grow quickly while the "
      "supersaturation is still large, then level off (plateau) once it "
      "has decayed -- the qualitative TED signature, not a fit to a "
      "specific published SIMS profile (see pytcad/ted.py honesty clause).")
