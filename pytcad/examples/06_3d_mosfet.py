"""Example 6 -- a realistic 3D n-channel MOSFET: Id-Vg transfer
characteristic, checked two independent ways.

Structure (an older-generation, long-channel bulk NMOS -- realistic and
well documented, not a scaled-down toy): Lg=600 nm gate, Lsd=300 nm
source/drain regions, 200 nm deep substrate, W=1 um channel width,
Na=1e17 cm^-3 p-type channel/substrate, Nsd_peak=1e19 cm^-3 n+
source/drain, tox=5 nm gate oxide, n+ poly gate. This is exactly the
2D cross-section already validated in examples/04_mosfet_idvg.py and
tests/test_validation_2d.py (same Lg/Lsd/depth/doping/tox/sigma_y/
sigma_lat -- see that test file for why this specific geometry was
chosen: it keeps the source/drain doping tails from merging under the
gate, so the device shows a genuine off state and a real subthreshold
knee), now extruded across a finite width W with the gate as a true
3D Robin boundary condition on the y=0 (top-surface) face
(GateBC(normal_axis='y'); the '3D-VISUALIZATION-PLAN.md'/device3d.py
design note says this axis is implemented but -- unlike normal_axis='z'
-- had never actually been exercised by this sub-project's own tests
before this example. Side walls at z=0 and z=W get no explicit
boundary condition, which Device3D treats as an implicit zero-flux
Neumann face (an idealized long, straight gate stripe with no
STI/fringing at the width edges -- out of scope, stated honestly, same
class of limitation the 2D solver already has for its width direction).

Two independent checks, not one:

  1. DIMENSIONAL CONSISTENCY (internal, source-independent): because
     doping and every boundary condition are uniform along z, the true
     physics has NO z-gradient anywhere -- the 3D solution must reduce
     to the (already-validated) 2D cross-section's solution exactly,
     the same reduction identity examples/05_3d_reduces_to_2d.py
     checks for a p-n junction. Id_3D [A] should equal Id_2D [A/cm] * W
     [cm] to numerical precision, not just approximately.

  2. PUBLISHED-VALUE CHECK (external): threshold voltage against the
     textbook long-channel depletion-approximation formula (Sze & Ng,
     *Physics of Semiconductor Devices*, 3rd ed., Ch. 6; Taur & Ning,
     *Fundamentals of Modern VLSI Devices*, 2nd ed., Ch. 2):

         V_th = V_FB + 2*phi_F + sqrt(4*eps_s*q*N_a*phi_F) / C_ox

     -- literally the same formula this codebase already validates the
     MOS-C module against (MOSCapacitor.analytic_landmarks(), gated in
     tests/test_validation.py) -- and the subthreshold swing against
     the 300 K thermal floor S_min = ln(10)*kT/q ~ 59.6 mV/decade
     (Sze & Ng Ch. 6; Taur & Ning Ch. 3): any real device's swing must
     be >= this floor, with the excess set by the depletion-capacitance
     body factor (1 + C_dep/C_ox) -- this solver has no traps/interface
     states, so it should sit close to the floor, not far above it.

     Vth is extracted from the drift-diffusion solve with the SAME
     max-transconductance linear-extrapolation method already validated
     in tests/test_validation_2d.py (promoted to
     gui/services/sweep_derived.threshold_voltage_max_gm) -- not a new
     extraction method invented for this example.

Honest limits, stated up front: this is drift-diffusion only (no
velocity saturation/Canali in 2D or 3D -- see device3d.py's explicit
NotImplementedError for Models(field_mobility=True)), so it is a
LONG-CHANNEL comparison -- Lg=600 nm is intentionally well above the
regime (~<250 nm) where 2D short-channel charge-sharing effects would
make the simple long-channel V_th formula a poor reference. No
short-channel-effect modeling, no LOCOS/STI, no unstructured mesh --
same honest limits as the rest of the 3D core (see README.md section 6).

    python examples/06_3d_mosfet.py   -> 3d_mosfet.png
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pytcad.mesh import graded_mesh, uniform_mesh
from pytcad.mesh2d import Mesh2D
from pytcad.mesh3d import Mesh3D, check_mesh3d
from pytcad.device2d import Device2D
from pytcad.device3d import Device3D
from pytcad.moscap import MOSCapacitor, flatband_voltage
from pytcad.mosfet import mosfet_doping
from pytcad.materials import SILICON
from pytcad.constants import thermal_voltage
from pytcad import adapt

from gui.services.sweep_derived import threshold_voltage_max_gm

# ---------------------------------------------------------------------
# Structure: identical cross-section to examples/04_mosfet_idvg.py /
# tests/test_validation_2d.py's validated MOSFET, extruded across a
# real device width.
# ---------------------------------------------------------------------
Lg, Lsd, depth = 6e-5, 3e-5, 2e-5      # 600 nm gate, 300 nm S/D, 200 nm deep [cm]
W = 1e-4                                # 1 um channel width [cm]
Na, Nsd_peak = 1e17, 1e19               # p-substrate, n+ source/drain [cm^-3]
tox_cm = 5e-7                           # 5 nm gate oxide [cm]
sigma_y, sigma_lat = 5e-6, 1e-6         # 50 nm / 10 nm junction grading [cm]
T = 300.0
Vds = 0.05                              # linear-region Vth extraction bias [V]

Vfb = flatband_voltage(-Na, tox_cm, "n+poly", 0.0, T, SILICON)


def _face(i_x, kk_all):
    ii, kk = np.meshgrid(i_x, kk_all, indexing="ij")
    return ii.ravel(), kk.ravel()


def build_device3d(mesh):
    """build_device(mesh) closure for adapt.adapt_solve_3d: doping and
    every contact/gate node-index array must be recomputed from
    whatever mesh the driver hands in -- they change every refinement
    pass, so nothing here may be captured from an outer, now-stale
    mesh."""
    mesh2_local = Mesh2D(mesh.x, mesh.y)
    dop2d_local, Ntot2d_local = mosfet_doping(
        mesh2_local, Lsd, Lg, Na, Nsd_peak, sigma_y, sigma_lat)
    dop3d_local = np.tile(dop2d_local, (mesh.Nz, 1, 1))
    Ntot3d_local = np.tile(Ntot2d_local, (mesh.Nz, 1, 1))

    dev = Device3D(mesh, dop3d_local, Ntotal=Ntot3d_local, T=T, material=SILICON)
    i_src = np.where(mesh.x <= Lsd)[0]
    i_drn = np.where(mesh.x >= Lsd + Lg)[0]
    i_gate = np.where((mesh.x > Lsd) & (mesh.x < Lsd + Lg))[0]
    kk_all = np.arange(mesh.Nz)

    ii, kk = _face(i_src, kk_all)
    dev.add_contact("source", i=ii, j=np.zeros_like(ii), k=kk, V=0.0)
    ii, kk = _face(i_drn, kk_all)
    dev.add_contact("drain", i=ii, j=np.zeros_like(ii), k=kk, V=0.0)
    ii, kk = _face(i_gate, kk_all)
    dev.add_gate("gate", i=ii, j=np.zeros_like(ii), k=kk, tox_cm=tox_cm, Vfb=Vfb, Vg=0.0,
                 normal_axis="y")
    ii, kk = np.meshgrid(np.arange(mesh.Nx), kk_all, indexing="ij")
    ii, kk = ii.ravel(), kk.ravel()
    dev.add_contact("body", i=ii, j=np.full_like(ii, mesh.Ny - 1), k=kk, V=0.0)
    return dev


# ---------------------------------------------------------------------
# Mesh quality: solution-driven adaptive refinement (M21, already
# shipped -- pytcad/adapt.py::adapt_solve_3d), not a hand-picked mesh.
# Refines x/y/z independently from potential curvature + carrier
# log-gradients AND an explicit per-axis Debye-length adequacy check.
# Start deliberately coarse (12 x 6 x 4) and let the driver find where
# resolution is actually needed -- in particular, whether the width
# (z) axis genuinely needs refining near the heavily-doped n+
# source/drain surface, the exact spot the hand-picked mesh's
# check_mesh3d call flagged (worst h/L_D=96) before this change.
# max_nodes caps well under the 3D solver's measured usable range
# (README.md "3D Solver": ~27,000 nodes before direct-solve LU fill-in
# becomes impractical) -- this sweep needs ~20 further re-solves after
# adaptation, not just the one equilibrium solve adapt_solve_3d itself
# runs, so headroom matters.
# ---------------------------------------------------------------------
L = 2 * Lsd + Lg
x0 = uniform_mesh(L, 12)
y0 = uniform_mesh(depth, 6)
z0 = uniform_mesh(W, 4)
mesh0 = Mesh3D(x0, y0, z0)

print(f"Starting mesh: {mesh0.N} nodes ({x0.size} x {y0.size} x {z0.size})")
print("Adaptive refinement (M21 adapt_solve_3d)...")
dev3, mesh3, hist = adapt.adapt_solve_3d(
    build_device3d, mesh0, tol=1e-2, max_passes=6, max_nodes=27000)
for h in hist:
    print(f"  pass {h['pass']}: {h['nodes']} nodes, qoi={h['qoi']:.4e}, "
          f"delta={h['delta']:.3e}, debye viol (x,y,z)="
          f"({h['debye_violations_x']},{h['debye_violations_y']},{h['debye_violations_z']}), "
          f"cause={h['cause']}")

x, y, z = mesh3.x, mesh3.y, mesh3.z
mesh2 = Mesh2D(x, y)
dop2d, Ntot2d = mosfet_doping(mesh2, Lsd, Lg, Na, Nsd_peak, sigma_y, sigma_lat)
dop3d = np.tile(dop2d, (mesh3.Nz, 1, 1))

print(f"\nAdapted 3D mesh: {mesh3.N} nodes ({mesh3.Nx} x {mesh3.Ny} x {mesh3.Nz})")
check_mesh3d(mesh3, dop3d, eps_r=SILICON.eps_r, T=T)

# --- 2D reference device on the SAME (x, y) the adapted 3D mesh
# settled on, so the dimensional-consistency check below compares like
# with like -- same requirement examples/05_3d_reduces_to_2d.py states.
dev2 = Device2D(mesh2, dop2d, Ntotal=Ntot2d, T=T, material=SILICON)
i_src2 = np.where(mesh2.x <= Lsd)[0]
i_drn2 = np.where(mesh2.x >= Lsd + Lg)[0]
i_gate2 = np.where((mesh2.x > Lsd) & (mesh2.x < Lsd + Lg))[0]
dev2.add_contact("source", i=i_src2, j=np.zeros_like(i_src2), V=0.0)
dev2.add_contact("drain", i=i_drn2, j=np.zeros_like(i_drn2), V=0.0)
dev2.add_contact("body", i=np.arange(mesh2.Nx), j=np.full(mesh2.Nx, mesh2.Ny - 1), V=0.0)
dev2.add_gate("gate", i=i_gate2, j=np.zeros_like(i_gate2), tox_cm=tox_cm, Vfb=Vfb, Vg=0.0)

# dev3 is already built AND solved at equilibrium by adapt_solve_3d
# (its default `solve` is solve_equilibrium()) -- reused directly, not
# rebuilt, so the Id-Vg sweep below warm-starts from that same state.

# ---------------------------------------------------------------------
# Id-Vg sweeps, both devices, same bias points, warm-started.
# ---------------------------------------------------------------------
Vg_list = np.linspace(-0.2, 1.2, 22)

print("\nSolving 2D reference (per-unit-width) sweep...")
dev2.solve_equilibrium()
Id2 = []
for Vg in Vg_list:
    dev2.solve_bias({"drain": Vds, "gate": Vg})
    Id2.append(dev2.terminal_current("drain"))
Id2 = np.array(Id2)

print("\nSolving 3D sweep (equilibrium already solved by adapt_solve_3d)...")
Id3 = []
for Vg in Vg_list:
    dev3.solve_bias({"drain": Vds, "gate": Vg})
    I = dev3.terminal_current("drain")
    Id3.append(I)
    print(f"  Vg = {Vg:+.3f} V   Id_3D = {I:+.6e} A   Id_2D*W = {Id2[len(Id3)-1]*W:+.6e} A")
Id3 = np.array(Id3)

# ---------------------------------------------------------------------
# Check 1 -- dimensional consistency: Id_3D should equal Id_2D * W.
# ---------------------------------------------------------------------
Id2_scaled = Id2 * W
# Compare only where both currents are numerically meaningful (above
# the linear-solve/roundoff noise floor) -- a ratio of two near-zero
# deep-off-state currents is not a meaningful check.
mask = np.abs(Id2_scaled) > 1e-16
rel_err = np.abs(Id3[mask] - Id2_scaled[mask]) / np.abs(Id2_scaled[mask])
print(f"\n[Check 1] Dimensional consistency (Id_3D vs Id_2D * W):")
print(f"  max relative error = {rel_err.max():.3e} over {mask.sum()} bias points")

# ---------------------------------------------------------------------
# Check 2 -- published-value comparison.
# ---------------------------------------------------------------------
mosc = MOSCapacitor(Nsub=-Na, tox_cm=tox_cm, gate="n+poly", T=T, material=SILICON)
landmarks = mosc.analytic_landmarks()
Vth_analytic = landmarks["V_th"]

Vth_3d = threshold_voltage_max_gm(Vg_list, Id3, vds=Vds)
Vth_2d = threshold_voltage_max_gm(Vg_list, Id2, vds=Vds)

print(f"\n[Check 2] Threshold voltage (Sze & Ng Ch. 6 / Taur & Ning Ch. 2 formula):")
print(f"  V_th, analytic (long-channel depletion approx.) = {Vth_analytic:+.4f} V")
print(f"  V_th, 3D solver (max-gm extraction)              = {Vth_3d:+.4f} V"
      f"  (delta = {(Vth_3d - Vth_analytic)*1e3:+.1f} mV)")
print(f"  V_th, 2D solver (max-gm extraction)              = {Vth_2d:+.4f} V"
      f"  (delta = {(Vth_2d - Vth_analytic)*1e3:+.1f} mV)")

VT = thermal_voltage(T)
S_min = np.log(10.0) * VT * 1e3   # mV/decade, 300 K thermal floor

sub_mask = (Vg_list < Vth_3d - 0.05) & (Id3 > 0)
if sub_mask.sum() >= 3:
    slope, _ = np.polyfit(Vg_list[sub_mask], np.log10(Id3[sub_mask]), 1)
    S_3d = 1e3 / slope   # mV/decade
else:
    S_3d = float("nan")

print(f"\n[Check 2b] Subthreshold swing (Sze & Ng / Taur & Ning 300 K thermal floor):")
print(f"  S_min (theoretical floor, ln(10)*kT/q) = {S_min:.1f} mV/decade")
print(f"  S, 3D solver (fit over Vg < Vth-50mV)  = {S_3d:.1f} mV/decade")

Ion = float(np.abs(Id3[Vg_list >= Vth_analytic + 0.3]).max()) if np.any(
    Vg_list >= Vth_analytic + 0.3) else float(np.abs(Id3).max())
Ioff = float(np.abs(Id3[np.argmin(np.abs(Vg_list - 0.0))]))
print(f"\n  I_on (approx, Vg ~ Vth+0.3V) = {Ion:.3e} A,  I_off (Vg=0) = {Ioff:.3e} A,"
      f"  Ion/Ioff ~ {Ion/max(Ioff,1e-30):.3e}")

# ---------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
ax1.semilogy(Vg_list, np.abs(Id3) + 1e-30, "o-", label="3D (real A)")
ax1.semilogy(Vg_list, np.abs(Id2_scaled) + 1e-30, "x--", label="2D x W (A)")
ax1.axvline(Vth_analytic, color="k", ls=":", label=f"V_th analytic = {Vth_analytic:.3f} V")
ax1.set_xlabel("Vg [V]"); ax1.set_ylabel("|Id| [A]")
ax1.set_title(f"Subthreshold (Vds={Vds} V, W={W*1e4:.2f} um)")
ax1.grid(True, which="both", alpha=0.3); ax1.legend(fontsize=8)

ax2.plot(Vg_list, Id3 * 1e6, "o-", label="3D")
ax2.plot(Vg_list, Id2_scaled * 1e6, "x--", label="2D x W")
ax2.axvline(Vth_analytic, color="k", ls=":")
ax2.set_xlabel("Vg [V]"); ax2.set_ylabel("Id [uA]"); ax2.set_title("Linear region")
ax2.grid(True, alpha=0.3); ax2.legend(fontsize=8)

fig.tight_layout()
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "3d_mosfet.png")
fig.savefig(out, dpi=140)
print(f"\nWrote {out}")
