"""Example 08: adaptive mesh refinement (AMR) on a 3D trench-gate power
MOSFET (UMOS).

This is a demonstration of the REAL AMR pipeline that already exists in
this repo (pytcad.adapt's structured tensor-product 3D driver, the same
machinery examples/07_3d_sic_power_mosfet.py uses via
adapt.adapt_solve_3d), driven manually pass-by-pass here only so each
cycle's mesh/solution can be exported and reported individually --
adapt_solve_3d itself runs its whole loop internally and only returns
the FINAL state. Every building block below (default_indicator_3d,
mark_dorfler, reduce_x/y/z, refine_3d, the Debye-adequacy check) is
imported unchanged from pytcad.adapt; nothing here re-implements or
mocks the estimator/marking/refinement math -- see adapt.adapt_solve_3d
for the reference loop this mirrors.

Device: pytcad.umos3d's trench-gate half-cell (see that module's
docstring for the geometry). The gate sits on the silicon's own x=0
face, restricted to y <= Dtrench -- a genuinely 3D feature this repo's
existing planar sic_vmosfet.py device does not have, and exactly the
feature that produces real, physically meaningful field crowding at
the two trench corners (x=0,y=0) and (x=0,y=Dtrench).

PIPELINE PER CYCLE (identical to adapt_solve_3d's own loop body):
    build_umos(mesh) -> Device3D  (real doping + real BCs, no mocks)
    dev.solve_equilibrium()        (real nonlinear Poisson/DD solve)
    default_indicator_3d(dev)      (real curvature + log-density error
                                    indicator, reduced onto each axis)
    Debye-length mesh-adequacy check (same as adapt_solve_3d)
    mark_dorfler + refine_3d       (real adaptive marking + refinement)

HONEST SCALE NOTE: this uses the STRUCTURED tensor-product 3D AMR path
(adapt.py), not the unstructured tetrahedral one (adapt_unstructured3d.
py). That module's own docstring says it is pure-Python O(N_tets) and
validated only up to a few thousand tets -- not a realistic route to
the several-hundred-thousand-element scale this example targets.
Structured refine_3d instead inserts whole grid LINES (a marked cell
refines its entire row/column/slab across the third dimension) -- so
refinement here concentrates STRONGLY along each axis near a marked
feature (trench corners, the body/drift junction, the source/body
junction) but is not fully unstructured-local in 3D the way a tet mesh
would be. That tradeoff was discussed and accepted before writing this
example: it is the only one of the two existing pipelines that can
reach hundreds of thousands of elements in practical time.

Outputs (this directory): two headless PNG previews per AMR pass
(8_umos_amr_pass{N}_overview.png, _trench_corner.png), drawn from a
grid carrying potential, log10(n), net doping and electric-field
magnitude -- a non-interactive view (fixed camera/colormap,
off_screen=True pyvista, same pattern examples/07 uses for its own
screenshot) of the refined regions concentrating at the trench corners
and junctions across passes.

MEASURED RUN (5 passes, THETA=0.7, TOL=2e-4, not projected): 31,581 ->
850,218 elements (26.9x), 15.8%->48.7% of per-axis cells flagged each
pass (never saturating to 100% -- confirms the growth is feature-
driven, not uniform doubling), stopped on the MAX_NODES budget at pass
4 with the QoI still tightening (rel. change 5.1e-3, not yet under
TOL) -- this is a budget-limited stop, not a converged one; say so if
using this run's numbers anywhere.
"""
import os
import time
import warnings

import numpy as np
import pyvista as pv

from pytcad.mesh3d import Mesh3D
from pytcad.umos3d import UMOSParams, build_umos
from pytcad.adapt import (
    default_indicator_3d, refine_3d, mark_dorfler,
    reduce_x, reduce_y, reduce_z,
)
from pytcad.mesh import debye_length

HERE = os.path.dirname(os.path.abspath(__file__))

# ----------------------------------------------------------------------
# 1. Device parameters and an initial COARSE, UNIFORM mesh (~20-50k
#    elements). No manual grading here -- AMR is what is being
#    demonstrated, so the starting mesh is deliberately naive.
# ----------------------------------------------------------------------
p = UMOSParams()

Nx0, Ny0, Nz0 = 34, 34, 30
mesh0 = Mesh3D(
    np.linspace(0.0, p.Lcell, Nx0),
    np.linspace(0.0, p.depth, Ny0),
    np.linspace(0.0, p.W, Nz0),
)
elements0 = (Nx0 - 1) * (Ny0 - 1) * (Nz0 - 1)
print(f"Initial mesh: {mesh0.N} nodes, {elements0} hexahedral elements")

# ----------------------------------------------------------------------
# 2. Manual AMR loop -- same algorithm as adapt.adapt_solve_3d, run
#    pass-by-pass so each cycle can be exported/reported individually.
# ----------------------------------------------------------------------
MAX_PASSES = 5
THETA = 0.7
TOL = 2e-4
MAX_NODES = 1_200_000
DEBYE_TARGET = 1.0

# NOTE on the Debye-adequacy check adapt_solve_3d also applies: this
# device's lightly-doped drift region (Nd_drift=2e16 cm^-3) has a Debye
# length of ~29 nm, so an h<=L_D floor is violated almost EVERYWHERE at
# a 20-50k-element starting resolution (measured directly: 33/33, 33/33
# and 29/29 cells on a first 34x34x30 mesh) -- folding that into the
# marked set the way adapt_solve_3d does would make the first 1-2
# passes an almost-uniform doubling, not the feature-concentrated
# refinement this example exists to demonstrate. So here the Debye
# ratios are computed and REPORTED every cycle (the honest numerical-
# adequacy caveat a real quantitative run would still need to resolve
# before trusting the result), but only the physically-motivated
# curvature/log-density indicator (default_indicator_3d) drives what
# actually gets refined -- see the loop body below.

mesh = mesh0
prev_q = None
history = []


def _qoi(dev):
    rho = dev.n - dev.p - dev.C
    return float(np.sum(np.abs(rho).ravel() * dev.mesh.dV))


def _preview_grid(dev, mesh):
    """Plain pyvista, headless: a RectilinearGrid built from the mesh
    axes, cast to an UnstructuredGrid, carrying the fields the PNG
    previews draw."""
    grid = pv.RectilinearGrid(mesh.x * 1e4, mesh.y * 1e4, mesh.z * 1e4)
    grid.point_data["potential_V"] = dev.psi_V.ravel(order="C")
    grid.point_data["log10_n_cm3"] = np.log10(
        np.maximum(dev.n_cm3, 1.0)).ravel(order="C")
    grid.point_data["net_doping_cm3"] = dev.doping.ravel(order="C")

    dpsi_dz, dpsi_dy, dpsi_dx = np.gradient(dev.psi_V, mesh.z, mesh.y, mesh.x)
    # mesh axes are in cm; psi_V is in volts -> E in V/cm.
    Emag = np.sqrt(dpsi_dx ** 2 + dpsi_dy ** 2 + dpsi_dz ** 2)
    grid.point_data["E_field_Vcm"] = Emag.ravel(order="C")

    return grid.cast_to_unstructured_grid()


def _export_screenshots(ugrid, cycle):
    """Static, headless PNG previews (off_screen=True, same pyvista
    path examples/07 already uses for its own screenshot; no
    interactivity, fixed camera/colormap). Two views per pass: (1) the whole
    half-cell mesh with edges shown, colored by field magnitude, so
    the growing element density is visible frame to frame; (2) a
    zoomed-in view of the trench corner region (x<0.35um, y<1.4um in
    the exported coordinates) where refinement is expected to
    concentrate. E_field_Vcm is plotted log-scaled (its dynamic range
    spans several orders of magnitude, from ~0 in the bulk to the
    trench-corner peak) with an explicit clim floor -- log_scale=True
    on data whose true minimum is exactly 0.0 otherwise renders with
    "-nan" colorbar tick labels (confirmed directly: VTK clamps the
    plotted colors fine but can't log-format a tick at 0)."""
    paths = []
    Emax = float(ugrid.point_data["E_field_Vcm"].max())
    clim = (max(Emax * 1e-4, 1.0), max(Emax, 1.0))

    plotter = pv.Plotter(off_screen=True, window_size=[900, 700])
    plotter.add_mesh(ugrid, scalars="E_field_Vcm", cmap="inferno",
                     log_scale=True, clim=clim, show_edges=True,
                     edge_color="gray", line_width=0.3, show_scalar_bar=True)
    plotter.add_axes()
    plotter.camera_position = "iso"
    plotter.enable_parallel_projection()
    out_overview = os.path.join(HERE, f"8_umos_amr_pass{cycle}_overview.png")
    plotter.screenshot(out_overview)
    plotter.close()
    paths.append(out_overview)

    corner = ugrid.clip_box(
        [0.0, 0.35, 0.0, 1.4, ugrid.bounds[4], ugrid.bounds[5]], invert=False)
    plotter = pv.Plotter(off_screen=True, window_size=[900, 700])
    if corner.n_points > 0:
        plotter.add_mesh(corner, scalars="E_field_Vcm", cmap="inferno",
                         log_scale=True, clim=clim, show_edges=True,
                         edge_color="gray", line_width=0.5,
                         show_scalar_bar=True)
    else:
        plotter.add_mesh(ugrid, scalars="E_field_Vcm", cmap="inferno",
                         show_edges=True, show_scalar_bar=True)
    plotter.add_axes()
    plotter.camera_position = "xy"
    out_corner = os.path.join(HERE, f"8_umos_amr_pass{cycle}_trench_corner.png")
    plotter.screenshot(out_corner)
    plotter.close()
    paths.append(out_corner)

    return paths


cause = "max_passes"
for cycle in range(MAX_PASSES):
    Nx, Ny, Nz = mesh.Nx, mesh.Ny, mesh.Nz
    nodes = mesh.N
    elements = (Nx - 1) * (Ny - 1) * (Nz - 1)

    t0 = time.perf_counter()
    dev = build_umos(mesh, p)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=UserWarning)
        dev.solve_equilibrium()
    solve_time = time.perf_counter() - t0

    q = _qoi(dev)
    if not np.isfinite(q):
        raise ValueError(
            f"quantity of interest is {q} after pass {cycle} on "
            f"{nodes} nodes -- refusing to refine on a non-finite solve")
    delta = np.inf if prev_q is None else abs(q - prev_q) / max(abs(q), 1e-30)

    # --- Debye mesh-adequacy check (identical to adapt_solve_3d) ---
    dop = np.abs(dev.doping)
    LD = debye_length(dop, T=dev.T)
    debye_x = np.diff(mesh.x) / np.minimum(LD[:, :, :-1], LD[:, :, 1:])
    debye_y = np.diff(mesh.y)[None, :, None] / np.minimum(LD[:, :-1, :], LD[:, 1:, :])
    debye_z = np.diff(mesh.z)[:, None, None] / np.minimum(LD[:-1, :, :], LD[1:, :, :])
    viol_x = np.flatnonzero(debye_x.mean(axis=(0, 1)) > DEBYE_TARGET)
    viol_y = np.flatnonzero(debye_y.mean(axis=(0, 2)) > DEBYE_TARGET)
    viol_z = np.flatnonzero(debye_z.mean(axis=(1, 2)) > DEBYE_TARGET)

    # --- real error indicator: potential curvature + carrier log- ---
    # --- density gradients, reduced per axis (pytcad.adapt) --------
    eta_x, eta_y, eta_z = default_indicator_3d(dev)
    max_eta = max(float(np.max(eta_x)) if eta_x.size else 0.0,
                  float(np.max(eta_y)) if eta_y.size else 0.0,
                  float(np.max(eta_z)) if eta_z.size else 0.0)

    marked_x = mark_dorfler(reduce_x(eta_x), THETA)
    marked_y = mark_dorfler(reduce_y(eta_y), THETA)
    marked_z = mark_dorfler(reduce_z(eta_z), THETA)
    n_marked = int(marked_x.size + marked_y.size + marked_z.size)
    n_cells_total = (Nx - 1) + (Ny - 1) + (Nz - 1)
    refine_pct = 100.0 * n_marked / max(n_cells_total, 1)

    ugrid = _preview_grid(dev, mesh)
    png_paths = _export_screenshots(ugrid, cycle)

    print(
        f"\n=== AMR cycle {cycle} ===\n"
        f"  nodes            : {nodes}\n"
        f"  elements         : {elements}\n"
        f"  DOFs (psi)       : {nodes}\n"
        f"  solver time      : {solve_time:.2f} s\n"
        f"  QoI (int|rho|dV) : {q:.6e}\n"
        f"  rel. QoI change  : {delta:.3e}\n"
        f"  max error ind.   : {max_eta:.3e}\n"
        f"  marked cells     : {n_marked} / {n_cells_total} "
        f"({refine_pct:.1f}% of per-axis cells flagged)\n"
        f"  Debye violations : x={viol_x.size} y={viol_y.size} z={viol_z.size}\n"
        f"  exported         : "
        f"{', '.join(os.path.basename(pp) for pp in png_paths)}"
    )

    history.append({
        "pass": cycle, "nodes": nodes, "elements": elements,
        "solve_time_s": solve_time, "qoi": q, "delta": delta,
        "max_indicator": max_eta, "marked_cells": n_marked,
        "refine_pct": refine_pct,
        "debye_violations": int(viol_x.size + viol_y.size + viol_z.size),
    })

    if prev_q is not None and delta <= TOL:
        cause = "converged"
        break
    prev_q = q

    if n_marked == 0:
        cause = "converged"
        break

    new_mesh = refine_3d(mesh, marked_x, marked_y, marked_z,
                         ratio=2.0, max_nodes=MAX_NODES)
    if new_mesh.N == mesh.N:
        cause = "max_nodes"
        break
    mesh = new_mesh
else:
    cause = "max_passes"

# ----------------------------------------------------------------------
# 3. Summary
# ----------------------------------------------------------------------
print(f"\nAMR loop stopped: {cause}")
print(f"{'pass':>4} {'nodes':>10} {'elements':>10} {'solve_s':>9} "
      f"{'delta':>10} {'max_ind':>10} {'refine%':>8}")
for h in history:
    print(f"{h['pass']:>4} {h['nodes']:>10} {h['elements']:>10} "
          f"{h['solve_time_s']:>9.2f} {h['delta']:>10.3e} "
          f"{h['max_indicator']:>10.3e} {h['refine_pct']:>7.1f}%")

growth = history[-1]["elements"] / history[0]["elements"]
print(f"\nElement growth over {len(history)} cycles: "
      f"{history[0]['elements']} -> {history[-1]['elements']} "
      f"({growth:.1f}x)")
print(f"PNG previews written to {HERE} (8_umos_amr_pass*_*.png).")
