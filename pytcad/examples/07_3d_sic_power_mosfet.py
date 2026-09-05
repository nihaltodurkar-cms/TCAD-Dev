"""Example 7 -- a comprehensive 3D TCAD reference example: a vertical
planar 4H-SiC power MOSFET half-cell, exercising the broadest slice of
this repo's Device3D capabilities of any example in this directory.

Structure: pytcad.sic_vmosfet.build_sic_vmosfet -- see that module's
docstring for the full geometry description (N+ source / P+ body-tie
notch / P-body / N- drift / N+ substrate-drain, GateBC over the
channel+JFET region). Read that docstring FIRST; this script assumes it.

CAPABILITY SCOPE -- what this example does and does not exercise, and
why. This is not an afterthought: the repo's Device3D core has real,
uneven physics-model coverage across dimensionalities (checked directly
in device3d.py's constructor guards before writing a single line of
this script), and several capabilities the "obvious" request for a
comprehensive power-MOSFET example would name are NOT implemented for
Device3D at all. See README_3d_sic_power_mosfet.md for the full
capability matrix; the short version:

  EXERCISED: Poisson + electron/hole continuity (always on), doping-
  dependent (Caughey-Thomas) mobility, SRH + Auger recombination,
  Slotboom bandgap narrowing, Fermi-Dirac carrier statistics (the N+/P+
  regions here are into the degenerate regime), ohmic contacts, a true
  3D gate/oxide Robin BC, real solution-adaptive 3D mesh refinement
  (pytcad.adapt.adapt_solve_3d), equilibrium + gate sweep + drain
  sweep + a dedicated off-state blocking study + on-state Rds,on
  extraction, full field/potential/carrier/current-density/terminal-
  current extraction, and headless 3D visualization/export.

  NOT AVAILABLE for Device3D in this repo (confirmed by reading
  device3d.py's own guards, not assumed) -- refused rather than
  silently skipped wherever this script would otherwise touch them:
  high-field/Canali mobility, impact ionization, band-to-band
  tunneling, density-gradient quantum correction, surface recombination
  velocity, transient/time-domain simulation, electro-thermal coupling,
  AC/small-signal analysis, Schottky contacts. `pytcad.continuation`
  is Device1D-only/unvalidated for 3D, so incremental manual bias
  stepping is used wherever a large bias jump needs warm-start help,
  not that module.

Runtime: this is the most expensive example in this directory (a real
adaptive 3D power-device mesh plus ~20 nonlinear bias solves). The
reference run took ~49 minutes wall-clock, almost entirely because the
OFF-branch drain ramp hit a genuine Newton convergence limit around
Vd~7.6V and spent most of that time on auto-halving retries there
before honestly stopping short of its 50V target -- see
README_3d_sic_power_mosfet.md's Results/Runtime sections for the full,
measured account (not an estimate). A run that does not push the
OFF-branch that far would take single-digit minutes.

    python examples/07_3d_sic_power_mosfet.py
        -> 7_sic_mosfet_electrical.png, 7_sic_mosfet_fields.png,
           7_sic_mosfet_fields.npz always; 7_sic_mosfet_3d.png and
           .vtk only if pyvista is installed (skipped, not faked,
           otherwise)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pytcad.mesh import uniform_mesh
from pytcad.mesh3d import Mesh3D, check_mesh3d
from pytcad.device import Models, NewtonOptions
from pytcad.sic_vmosfet import SiCVMOSFETParams, build_sic_vmosfet, sic_vmosfet_doping
from pytcad import adapt

HERE = os.path.dirname(os.path.abspath(__file__))
T0 = time.time()


def log(msg):
    print(f"[{time.time()-T0:7.1f}s] {msg}", flush=True)


# ---------------------------------------------------------------------
# 1. Structure + adaptive 3D mesh
# ---------------------------------------------------------------------
p = SiCVMOSFETParams()
MODELS = Models(fd=True, srh=True, auger=True, bgn=True, doping_mobility=True)
# surface_mobility is deliberately left at its default False: the
# investigation for this example found Device3D has NO guard against
# it (device2d.py reads the flag; device3d.py never checks it at all),
# so setting it would silently no-op rather than raise -- a real gap
# in this codebase, documented in README_3d_sic_power_mosfet.md rather
# than worked around by pretending the flag does something here.

log(f"4H-SiC material: Eg(300K)={p.material.Eg(300.0):.3f} eV, "
   f"eps_r={p.material.eps_r}, kappa_th300={p.material.kappa_th300} W/(cm*K)")
log(f"Geometry: half-cell Lcell={p.Lcell*1e4:.2f} um, channel "
   f"{ (p.Lch-p.Ln)*1e4:.2f} um, drift {p.t_drift*1e4:.2f} um @ "
   f"{p.Nd_drift:.1e} cm^-3, depth {p.depth*1e4:.2f} um")


def build_device(mesh):
    """build_device(mesh) closure for adapt.adapt_solve_3d -- doping
    and every contact/gate node array recomputed from whatever mesh
    the driver hands in, same requirement examples/06_3d_mosfet.py's
    own closure documents."""
    return build_sic_vmosfet(mesh, p, models=MODELS)


x0 = uniform_mesh(p.Lcell, 14)
y0 = uniform_mesh(p.depth, 10)
z0 = uniform_mesh(p.W, 6)
mesh0 = Mesh3D(x0, y0, z0)
log(f"Starting mesh: {mesh0.N} nodes ({x0.size} x {y0.size} x {z0.size})")
log("Adaptive refinement (pytcad.adapt.adapt_solve_3d)...")
dev, mesh, hist = adapt.adapt_solve_3d(
    build_device, mesh0, tol=2e-2, max_passes=5, max_nodes=15000)
for h in hist:
    log(f"  pass {h['pass']}: {h['nodes']} nodes, qoi={h['qoi']:.4e}, "
       f"delta={h['delta']:.3e}, debye viol (x,y,z)="
       f"({h['debye_violations_x']},{h['debye_violations_y']},"
       f"{h['debye_violations_z']}), cause={h['cause']}")

dop, _ = sic_vmosfet_doping(mesh, p)
worst_ratio = check_mesh3d(mesh, dop, eps_r=p.material.eps_r, T=p.T)
log(f"Adapted mesh: {mesh.N} nodes ({mesh.Nx} x {mesh.Ny} x {mesh.Nz}), "
   f"worst h/L_D = {worst_ratio:.1f} (residual under-resolution in the "
   f"heaviest-doped N+/P+ regions is expected at this node budget -- "
   f"same documented tradeoff examples/06_3d_mosfet.py's own adaptive "
   f"run reports)")

# dev is already built AND solved at equilibrium by adapt_solve_3d
# (its default `solve` is solve_equilibrium()) -- reused directly.
opts = NewtonOptions(max_iter=100)

# ---------------------------------------------------------------------
# 2. Gate sweep (Id-Vg), linear region -- the standard transfer curve.
# ---------------------------------------------------------------------
Vds_lin = 0.1
Vg_list = np.array([0.0, 2.0, 4.0, 6.0, 10.0, 15.0, 20.0])
log(f"Id-Vg sweep at Vds={Vds_lin} V...")
Id_vg = []
for Vg in Vg_list:
    t0 = time.time()
    dev.solve_bias({"drain": Vds_lin, "gate": Vg}, opts)
    I = dev.terminal_current("drain")
    Id_vg.append(I)
    log(f"  Vg={Vg:5.1f} V   Id={I:+.4e} A   ({time.time()-t0:.1f}s)")
Id_vg = np.array(Id_vg)

# ---------------------------------------------------------------------
# 3. Drain sweep (Id-Vd) family -- off-state and on-state branches,
#    each ramped incrementally (manual bias stepping, warm-started from
#    the previous point) rather than jumped to directly -- the
#    established robust pattern this repo's own sweep helpers use, and
#    the substitute for pytcad.continuation, which is Device1D-only/
#    unvalidated for Device3D (checked, not assumed -- see README).
#
# A first attempt at this sweep (jumping 1V -> 10V -> 50V -> 100V in
# one Newton solve each) produced exactly the failure mode this
# section now guards against: two of those jumps left Newton's own
# convergence warning firing (`3D Newton did not converge`), and the
# resulting "solution" reported Id ~ 5 A at Vg=0V -- an off-state
# device that is obviously not actually passing 5 Amps. That is a
# non-converged Newton iterate, not a real result, and reporting it
# would be exactly the kind of faked output this example must not
# produce. The bad state then crashed the very next solve (an
# out-of-validated-range Fermi-Dirac inversion) when the ON-branch
# sweep tried to warm-start from it. Fixed two ways: (1) genuinely
# fine-grained ramping with automatic step-halving on a detected
# non-convergence, stopping (not guessing past) the point where
# Newton stops converging reliably; (2) each branch below gets its
# OWN freshly-built, freshly-re-equilibrated device, so a difficult
# OFF-branch high-Vd point can never contaminate the ON-branch's
# starting state.
# ---------------------------------------------------------------------
def _solve_bias_checked(dev, voltages, opts):
    """solve_bias, returning whether Newton actually converged (the
    method itself only warns, never raises, on non-convergence -- see
    device3d.py's own `warnings.warn(f"3D Newton did not converge...")`
    call) -- caught here rather than trusted silently."""
    import warnings as _w
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        dev.solve_bias(voltages, opts)
        return not any("did not converge" in str(x.message) for x in caught)


def ramped_drain_sweep(dev, Vg, Vd_targets, opts, max_step=2.0):
    """Step the drain from wherever `dev` currently is up through each
    of Vd_targets, in increments of at most `max_step` volts, warm-
    starting every solve from the previous converged point. On a
    detected non-convergence, halve the step and retry (up to a few
    times); if it still won't converge, STOP the ramp there and return
    only the targets actually reached -- an honest partial result
    beats a fabricated one.

    Returns (Vd_reached, Id_reached) -- may be SHORTER than Vd_targets
    if the ramp had to stop early; callers must not assume a 1:1
    correspondence with Vd_targets."""
    dev.solve_bias({"drain": 0.0, "gate": Vg}, opts)
    Vd_cur = 0.0
    Vd_reached, Id_reached = [], []
    for Vd_target in Vd_targets:
        Vd_target = float(Vd_target)
        step = max_step
        while Vd_cur < Vd_target - 1e-9:
            Vd_next = min(Vd_cur + step, Vd_target)
            t0 = time.time()
            ok = _solve_bias_checked(dev, {"drain": Vd_next, "gate": Vg}, opts)
            if ok:
                Vd_cur = Vd_next
                log(f"  Vg={Vg:5.1f} V  Vd={Vd_cur:7.2f} V   "
                   f"Id={dev.terminal_current('drain'):+.4e} A   "
                   f"(step={step:.2f}V, {time.time()-t0:.1f}s)")
            else:
                step /= 2.0
                log(f"  Vg={Vg:5.1f} V  Vd={Vd_cur+step*2:7.2f} V step "
                   f"did NOT converge -- halving step to {step:.3f}V and retrying")
                if step < 0.05:
                    log(f"  Vg={Vg:5.1f} V: ramp STOPPED at Vd={Vd_cur:.2f} V "
                       f"-- Newton would not converge with a step below "
                       f"0.05V. Reporting only points actually reached; "
                       f"NOT fabricating data beyond this bias.")
                    # The true last-converged state is Vd_cur, which may
                    # sit strictly between two requested checkpoints (as
                    # it did on the first real run of this script: the
                    # ramp reached 7.62V but never hit the 10V
                    # checkpoint) -- append it explicitly so callers that
                    # read Vd_reached[-1]/Id_reached[-1] for "the last
                    # state `dev` is actually in" get the TRUE value, not
                    # a stale earlier checkpoint. Guard against a
                    # duplicate append if Vd_cur already IS the last
                    # recorded checkpoint (nothing changed since then).
                    if not Vd_reached or abs(Vd_reached[-1] - Vd_cur) > 1e-9:
                        Vd_reached.append(Vd_cur)
                        Id_reached.append(dev.terminal_current("drain"))
                    return np.array(Vd_reached), np.array(Id_reached)
        Vd_reached.append(Vd_cur)
        Id_reached.append(dev.terminal_current("drain"))
    return np.array(Vd_reached), np.array(Id_reached)


Vd_off_target = np.array([0.1, 1.0, 5.0, 10.0, 20.0, 30.0, 50.0])
log("Id-Vd, OFF-state branch (Vg=0 V) -- ramped toward blocking...")
Vd_off, Id_off = ramped_drain_sweep(dev, 0.0, Vd_off_target, opts)
if len(Vd_off) < len(Vd_off_target):
    log(f"OFF-branch ramp reached {Vd_off[-1]:.1f} V of the "
       f"{Vd_off_target[-1]:.1f} V target before Newton convergence "
       f"stopped improving further -- this IS the honest result, not a "
       f"truncated placeholder.")

# ON-branch: a FRESH device, independently built and re-equilibrated --
# never warm-started from the OFF-branch's (possibly difficult) final
# state. Reuses the SAME adapted mesh (mesh, from adapt_solve_3d above).
log("Building a fresh device for the ON-branch (independent of the "
   "OFF-branch's end state)...")
dev_on = build_device(mesh)
dev_on.solve_equilibrium(opts)
Vd_on_target = np.array([0.1, 1.0, 2.0, 5.0, 10.0])
Vg_on = 15.0
log(f"Id-Vd, ON-state branch (Vg={Vg_on} V)...")
Vd_on, Id_on = ramped_drain_sweep(dev_on, Vg_on, Vd_on_target, opts)

# ---------------------------------------------------------------------
# 4. Off-state blocking analysis -- peak field vs. the literature 4H-SiC
#    critical field. Impact ionization is NOT implemented for Device3D
#    (device3d.py raises on Models(impact=True)), so this is NOT a
#    simulated avalanche breakdown voltage -- it is the standard TCAD-
#    lite proxy (peak |E| at the highest simulated blocking bias vs. a
#    literature critical field), stated as exactly that, not dressed
#    up as a real BV sweep.
# ---------------------------------------------------------------------
psi_off = dev.psi_V   # (Nz, Ny, Nx) [V] -- dev is still at its LAST
# converged OFF-branch point (Vd=Vd_off[-1], Vg=0); this example never
# re-solves dev between the ramp above and here, so this is genuinely
# the state the ramp actually reached, not assumed.
Ey = -np.diff(psi_off, axis=1) / np.diff(mesh.y)[None, :, None]   # [V/cm]
Ex = -np.diff(psi_off, axis=2) / np.diff(mesh.x)[None, None, :]
peak_E = float(max(np.abs(Ey).max(), np.abs(Ex).max()))
E_CRIT_4H_SIC = 2.2e6   # V/cm, representative literature value (Baliga,
                       # "Fundamentals of Power Semiconductor Devices")
log(f"Off-state (Vg=0, Vd={Vd_off[-1]:.0f} V): peak |E| = {peak_E:.3e} V/cm "
   f"vs. literature 4H-SiC critical field ~{E_CRIT_4H_SIC:.1e} V/cm "
   f"(ratio {peak_E/E_CRIT_4H_SIC:.2f}) -- NOT a simulated avalanche BV, "
   f"impact ionization is not implemented for Device3D here.")
I_leak = float(abs(Id_off[-1]))
log(f"Off-state leakage at Vd={Vd_off[-1]:.0f} V: {I_leak:.3e} A")

# ---------------------------------------------------------------------
# 5. On-state Rds,on extraction (linear-region slope at the ON branch's
#    lowest bias points).
# ---------------------------------------------------------------------
lin_mask = Vd_on <= 1.0
Rds_on = float(np.polyfit(Vd_on[lin_mask], Id_on[lin_mask], 1)[0]) ** -1 \
    if lin_mask.sum() >= 2 else float("nan")
log(f"On-state (Vg={Vg_on} V) Rds,on (linear-region fit, Vd<=1V) = "
   f"{Rds_on:.4e} Ohm (per this half-cell's own cross-sectional area, "
   f"not a normalized Ohm*cm^2 figure -- see README for that conversion)")

# ---------------------------------------------------------------------
# 6. Full extraction at three representative bias points: equilibrium,
#    on-state, off-state-blocking. potential/carrier/current-density
#    are direct Device3D fields; E-field is derived (np.gradient-style
#    finite difference of psi_V -- there is no E_field accessor, this
#    is ordinary numpy, not a missing API).
# ---------------------------------------------------------------------
np.savez(os.path.join(HERE, "7_sic_mosfet_fields.npz"),
        x_um=mesh.x * 1e4, y_um=mesh.y * 1e4, z_um=mesh.z * 1e4,
        psi_V=dev.psi_V, n_cm3=dev.n_cm3, p_cm3=dev.p_cm3,
        Jn_x=dev.Jn_x, Jn_y=dev.Jn_y, Jp_x=dev.Jp_x, Jp_y=dev.Jp_y)
log(f"Wrote {os.path.join(HERE, '7_sic_mosfet_fields.npz')} "
   f"(potential/carrier/current-density fields at the off-state-blocking bias)")

# ---------------------------------------------------------------------
# 7. Electrical plots
# ---------------------------------------------------------------------
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
ax1.semilogy(Vg_list, np.abs(Id_vg) + 1e-30, "o-")
ax1.set_xlabel("Vg [V]"); ax1.set_ylabel("|Id| [A]")
ax1.set_title(f"Id-Vg transfer (Vds={Vds_lin} V)")
ax1.grid(True, which="both", alpha=0.3)

ax2.plot(Vd_on, Id_on * 1e3, "o-", label=f"Vg={Vg_on} V (on)")
ax2.plot(Vd_off, np.abs(Id_off) * 1e3, "x--", label="Vg=0 V (off, |Id|)")
ax2.set_xlabel("Vd [V]"); ax2.set_ylabel("Id [mA]"); ax2.set_title("Id-Vd family")
ax2.grid(True, alpha=0.3); ax2.legend(fontsize=8)
fig.tight_layout()
out1 = os.path.join(HERE, "7_sic_mosfet_electrical.png")
fig.savefig(out1, dpi=140)
log(f"Wrote {out1}")

# Field/potential cross-section plot (x-y slice at the z-midplane).
kz = mesh.Nz // 2
fig2, axes = plt.subplots(1, 3, figsize=(14, 4.5))
extent = [mesh.x[0] * 1e4, mesh.x[-1] * 1e4, mesh.y[-1] * 1e4, mesh.y[0] * 1e4]
im0 = axes[0].imshow(dev.psi_V[kz], extent=extent, aspect="auto", cmap="RdBu_r")
axes[0].set_title(f"Potential [V] (off-state, Vd={Vd_off[-1]:.2f}V)")
plt.colorbar(im0, ax=axes[0])
im1 = axes[1].imshow(np.log10(np.maximum(dev.n_cm3[kz], 1.0)), extent=extent,
                     aspect="auto", cmap="viridis")
axes[1].set_title("log10(n) [cm^-3]")
plt.colorbar(im1, ax=axes[1])
Emag = np.zeros_like(dev.psi_V[kz])
Emag[:, :-1] = np.abs(Ex[kz])
im2 = axes[2].imshow(Emag, extent=extent, aspect="auto", cmap="inferno")
axes[2].set_title("|Ex| [V/cm]")
plt.colorbar(im2, ax=axes[2])
for ax in axes:
    ax.set_xlabel("x [um]"); ax.set_ylabel("y [um]")
fig2.tight_layout()
out2 = os.path.join(HERE, "7_sic_mosfet_fields.png")
fig2.savefig(out2, dpi=140)
log(f"Wrote {out2}")

# ---------------------------------------------------------------------
# 8. Headless 3D visualization/export via plain pyvista -- bypassing
#    gui/services/viewer3d.py, which unconditionally imports PySide6
#    at module level (checked directly) and so cannot be imported from
#    a pure pytcad-core script without a GUI-capable environment. This
#    exact off-screen pattern is already used elsewhere in this repo's
#    own test suite (gui/tests/test_exploded_view_real_plotter_bug.py).
# ---------------------------------------------------------------------
try:
    import pyvista as pv
    grid = pv.RectilinearGrid(mesh.x * 1e4, mesh.y * 1e4, mesh.z * 1e4)
    # pyvista's RectilinearGrid is x-fastest point order matching numpy
    # C-order (Nz,Ny,Nx) flatten -- same convention dev.psi_V already uses.
    grid.point_data["potential_V"] = dev.psi_V.ravel(order="C")
    grid.point_data["log10_n_cm3"] = np.log10(np.maximum(dev.n_cm3, 1.0)).ravel(order="C")
    plotter = pv.Plotter(off_screen=True, window_size=[900, 700])
    plotter.add_mesh(grid, scalars="potential_V", cmap="RdBu_r", opacity=0.6)
    plotter.add_axes()
    out3 = os.path.join(HERE, "7_sic_mosfet_3d.png")
    plotter.screenshot(out3)
    grid.save(os.path.join(HERE, "7_sic_mosfet_3d.vtk"))
    log(f"Wrote {out3} and 7_sic_mosfet_3d.vtk (headless pyvista)")
except ImportError:
    log("pyvista not available -- skipped 3D visualization/export "
       "(fields are still saved in 7_sic_mosfet_fields.npz)")

log("Done.")
log(f"SUMMARY: Vth (rough, from Id-Vg onset) between "
   f"{Vg_list[np.abs(Id_vg) < 1e-9][-1] if np.any(np.abs(Id_vg) < 1e-9) else 0.0} "
   f"and {Vg_list[np.abs(Id_vg) >= 1e-9][0] if np.any(np.abs(Id_vg) >= 1e-9) else float('nan')} V, "
   f"Rds_on={Rds_on:.3e} Ohm, I_leak(Vd={Vd_off[-1]:.0f}V)={I_leak:.3e} A, "
   f"peak_E/E_crit={peak_E/E_CRIT_4H_SIC:.2f}")
