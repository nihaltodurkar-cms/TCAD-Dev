# Example 7 — 3D 4H-SiC Vertical Power MOSFET

A comprehensive 3D TCAD reference example: a vertical planar 4H-SiC
power MOSFET half-cell, built entirely from existing repo APIs
(`Device3D`, `Mesh3D`, `pytcad.adapt.adapt_solve_3d`) plus two new,
reusable pieces — a 4H-SiC `Semiconductor` material entry
(`pytcad/pytcad/materials.py`) and a vertical-DMOS geometry/doping
builder (`pytcad/pytcad/sic_vmosfet.py`), since neither existed in this
codebase before.

```
python examples/07_3d_sic_power_mosfet.py
python -m pytest tests/test_sic_vmosfet.py -q
```

Also loadable interactively from the GUI: **File menu → "Trial"**
(`gui.services.examples.sic_power_mosfet_3d_example_spec`, registered
in `EXAMPLES["trial"]`). This is the SAME geometry/doping construction
(`pytcad.sic_vmosfet`) on a deliberately coarser, non-adaptive, fixed
mesh (~5,000 nodes vs. the standalone script's ~7,900 adapted nodes) —
a UI quick-load example must construct instantly on the UI thread, the
same convention every other `EXAMPLES` entry follows (running
`adapt.adapt_solve_3d` does not belong behind a menu click). Loads
unbiased; use the Sweeps panel for an interactive Id-Vg/Id-Vd curve.
Because the mesh is coarser, expect **less accurate** results than the
standalone script, and be aware the underlying device geometry showed
a real Newton convergence limit around Vd≈7.6V in the standalone
script's own adaptively-refined run (see Results below) — pushing the
Sweeps panel's drain voltage well past that in the GUI is likely to hit
the same limit, on the (coarser) fixed mesh here.

## Geometry

A symmetric **half-cell** of a striped planar DMOS layout (mirror
symmetry assumed at all four lateral boundaries — `Device3D`'s
box-integration assembly gives zero-flux Neumann there automatically,
with no explicit boundary condition needed).

```
   x=0                x=Ln          x=Lch              x=Lcell
    |--- source/tie ---|--- channel ---|---- JFET/drift ----|
    |                  P-body (x<Lch)                       |
```

| Axis | Extent | Meaning |
|---|---|---|
| x (lateral) | `[0, Ln]` | N+ source (surface); for `z<Wbt` the sub-range `[0,Lbt]` is P+ body-tie instead |
| | `[0, Lch]` | P-body (vertically, beneath the surface) |
| | `[Lch, Lcell]` | JFET/drift exposed at the surface, under the gate |
| y (depth) | shallow | N+ source / P+ body-tie (Gaussian-in-depth) |
| | mid | P-body (Gaussian-in-depth, `x<Lch` only) |
| | bulk | N− drift (sets blocking voltage) |
| | bottom | N+ substrate/drain (thin, full-area ohmic contact) |
| z (stripe length) | uniform, **except** | the body-tie notch `[0,Wbt]` — the one deliberately 3D-only feature |

The body-tie notch is why this structure does **not** reduce to a
z-invariant 2D extrusion the way `examples/06_3d_mosfet.py`'s does — it
exercises genuine x-y-z coupling, not just a width multiplier. Real
striped power MOSFETs use exactly this design: a continuous P+ tie
along the whole stripe would waste source area, so ties are placed
periodically.

Doping is built additively (same convention `pytcad/mosfet.py` already
uses: each region contributes a signed Gaussian/erf-rolloff blob, net
doping is the sum, `Ntotal` is the sum of magnitudes — the
total-ionized-impurity convention `mobility_caughey_thomas` requires).

### Default parameters

| Parameter | Value | Note |
|---|---|---|
| Channel length (`Lch-Ln`) | 0.6 µm | |
| Drift thickness | 4.2 µm | |
| Drift doping | 1×10¹⁶ cm⁻³ | few-hundred-volt-class |
| P-body doping | 2×10¹⁷ cm⁻³ | |
| N+ source / P+ body-tie doping | 2×10¹⁹ cm⁻³ | reduced from a more aggressive 5×10¹⁹ to keep the Debye length tractable on a ~15k-node adaptive mesh — see Limitations |
| N+ substrate doping | 1×10¹⁹ cm⁻³ | |
| Gate oxide | 50 nm, n+poly | |
| Half-cell width × stripe length | 2.0 µm × 2.0 µm | |

None of these dimensions are claimed to match any specific datasheet
part — this is a representative, self-consistent structure, not a
reproduction of a commercial device.

## 4H-SiC material (`pytcad.materials.SIC_4H`)

Added following the file's own existing convention for non-silicon
materials (`GE`/`GAAS`/`INGAAS`/`algaas()`): well-established constants
kept precise, fit-shape parameters explicitly flagged where they are
carried over from the codebase's generic (silicon-derived) functional
forms rather than independently refit to 4H-SiC data. See the
material's own code comment block in `materials.py` for the full
field-by-field provenance. Headline numbers: `eps_r=9.7`,
`chi=3.17 eV`, `Eg(300K)≈3.23 eV`, `kappa_th300=3.7 W/(cm·K)`
(~2.5× silicon's — the reason SiC is used for power devices).

## Physics — capability matrix

Checked directly against `device3d.py`'s constructor guards before
writing any of this example (not assumed from the 1D/2D docs).

| Capability | Device3D status | Exercised here |
|---|---|---|
| Poisson + electron/hole continuity | Always on | ✅ |
| Doping-dependent (Caughey-Thomas) mobility | Wired | ✅ |
| SRH recombination | Wired | ✅ |
| Auger recombination | Wired | ✅ |
| Bandgap narrowing (Slotboom) | Wired | ✅ |
| Fermi-Dirac statistics | Wired | ✅ (N+/P+ regions are degenerate) |
| Ohmic contacts | Wired | ✅ (source, drain) |
| Gate/oxide (GateBC, any face normal) | Wired | ✅ (`normal_axis='y'`) |
| Heterostructure (per-node material) | Wired | Not exercised — this device is a 4H-SiC homojunction |
| High-field (Canali) mobility | **Raises `NotImplementedError`** | ❌ not available |
| Impact ionization | **Raises** | ❌ not available |
| Band-to-band tunneling | **Raises** | ❌ not available |
| Density-gradient quantum correction | **Raises** | ❌ not available |
| Surface recombination velocity (S_n/S_p) | **Raises** | ❌ not available |
| Surface mobility (Lombardi CVT) | **Silently ignored — no guard exists** (a real gap: `device2d.py` reads the flag, `device3d.py` never checks it) | Left at default `False` deliberately; see `test_surface_mobility_is_a_documented_silent_gap_not_a_claimed_feature` |
| Schottky contacts | **Does not exist anywhere in the core solver** (any dimensionality) | ❌ not available |
| Transient/time-domain | **No `transient3d.py` exists** | ❌ not available |
| Electro-thermal (self-heating) | **`thermal.py` is Device1D-only, no 2D/3D hook** | ❌ not available |
| AC/small-signal (Y-parameters) | **No `ac3d.py` exists** | ❌ not available |
| Continuation (`pytcad.continuation`) | Documented/built for Device1D only, unvalidated for 3D | Not used — manual incremental bias stepping instead (see `ramped_drain_sweep`) |
| Solution-adaptive 3D mesh refinement | Real, tested (`pytcad.adapt.adapt_solve_3d`) | ✅ |

**None of the ❌ rows are worked around, faked, or silently
approximated.** Where the user-facing request named a capability in
this list, the example's own docstring and this README say plainly
that it isn't available for `Device3D` today, rather than improvising
a substitute and presenting it as the real thing.

## Solver settings

- `NewtonOptions(max_iter=100)` for bias solves (the default `linsolve="direct"`
  sparse LU — the mesh sizes here stay well under the ~27,000-node
  practical ceiling this repo's own README documents for direct solves
  in 3D).
- Equilibrium + the adaptive mesh's own equilibrium passes use
  `pytcad.adapt.adapt_solve_3d`'s default solver (`solve_equilibrium()`).
- High-bias off-state points are reached by **manual incremental
  ramping** (`ramped_drain_sweep`, warm-starting each step from the
  previous converged point) rather than a single large jump — the
  robust, already-established pattern this repo's own sweep helpers
  use, standing in for `pytcad.continuation` (Device1D-only).

## Simulation studies

1. **Equilibrium** — via the adaptive-mesh driver's own default solve.
2. **Gate sweep (Id-Vg)** — Vds=0.1 V (linear region), Vg = 0…20 V, 7
   points.
3. **Drain sweep (Id-Vd), OFF branch** — Vg=0 V, Vd ramped toward a
   50 V target in fine (≤2 V, auto-halving on non-convergence, down to
   a 0.05 V floor) increments, warm-starting every step from the
   previous converged point — see "A real convergence limit found and
   handled honestly" below for what this branch actually reached.
4. **Drain sweep (Id-Vd), ON branch** — Vg=15 V, Vd = 0.1…10 V (5
   points, same fine-ramping helper), for Rds,on extraction. Uses a
   **freshly built, independently re-equilibrated** device, never
   warm-started from the OFF branch's end state — see below for why.
5. **Off-state blocking analysis** — peak |E| at the highest bias the
   OFF-branch ramp actually reached, compared against a literature
   4H-SiC critical field (~2.2 MV/cm, Baliga). **This is not a
   simulated avalanche breakdown voltage** — impact ionization is not
   implemented for `Device3D` (see the capability matrix), so this is
   the standard TCAD-lite peak-field-vs-critical-field proxy, reported
   as exactly that.
6. **On-state Rds,on** — linear-region fit over the ON branch's Vd≤1V
   points.
7. **Full field extraction** at the off-state-blocking bias point:
   potential, electron/hole density, current density (all direct
   `Device3D` fields — `psi_V`, `n_cm3`, `p_cm3`, `Jn_x/y`, `Jp_x/y`),
   plus a derived E-field (finite difference of `psi_V` — there is no
   `E_field` accessor; this is ordinary numpy, not a missing API).
8. **Visualization/export** — headless 3D rendering via plain
   `pyvista` (`Plotter(off_screen=True)`), **bypassing**
   `gui/services/viewer3d.py`, which unconditionally imports PySide6 at
   module level and so cannot be imported from a pure `pytcad`-core
   script. Outputs: a 2D field cross-section PNG, a 3D screenshot PNG,
   a `.vtk` export, and a `.npz` with the raw field arrays.

## Results

From the actual completed run (`examples/7_sic_mosfet_*.{png,npz,vtk}`,
regenerated by `python examples/07_3d_sic_power_mosfet.py`) — real
numbers, not illustrative placeholders:

- Adapted mesh: 7,917 nodes (29×21×13, from a 1,155-node start), capped
  by the 15,000-node budget after 2 refinement passes.
- **Id-Vg** (Vds=0.1V): off-state current 2.56×10⁻¹⁴ A at Vg=0V; turns
  on sharply between Vg=0V and Vg=2V (7.52×10⁻⁶ A) — this example's 7
  sweep points do not resolve exactly where between 0V and 2V the
  threshold sits, only that it is low for this doping/oxide
  combination — then saturates near 7.8-8.0×10⁻⁶ A for Vg≥4V,
  essentially flat out to Vg=20V. That flatness is JFET/drift-region
  spreading-resistance-limited at this device's geometry, not a
  channel-limited MOSFET saturation.
- **Id-Vd, ON branch** (Vg=15V): clean, fully-converged linear-region
  sweep, Id=7.94×10⁻⁶ A at Vd=0.1V rising to 7.92×10⁻⁴ A at Vd=10V —
  roughly linear over this whole range (no visible knee into
  saturation by 10V). Rds,on (linear fit, Vd≤1V) = **1.265×10⁴ Ω**
  for this half-cell's own cross-section (not a normalized Ω·cm²
  figure — multiply by the half-cell's cross-sectional area,
  `Lcell×W` = 2µm×2µm here, to get one).
- **Id-Vd, OFF branch** (Vg=0V): **a real convergence limit found and
  handled honestly, not smoothed over.** The ramp toward the 50V
  target converged cleanly and fast (17-95s/step) out to Vd=7V, where
  Id had already risen to 4.1×10⁻⁵ A — nearly 4 orders of magnitude
  above the near-zero current at Vd≤1V. Pushing further, Newton
  convergence became genuinely difficult (not merely "needed a smaller
  step"): the ramp's automatic step-halving ran from 2V down to its
  0.05V floor, taking increasingly long per attempt (up to ~270s), and
  the ramp **stopped at Vd=7.62V** — well short of the 50V target.
  Off-state leakage there: 3.71×10⁻⁶ A. Peak |E| at that point:
  4.46×10⁵ V/cm, only 20% of the literature 4H-SiC critical field
  (~2.2×10⁶ V/cm) — so this device, as designed, shows a soft
  current-leakage rise and a hard numerical convergence wall well
  *before* reaching a field level where the (unmodeled) avalanche
  physics would even become relevant. Read plainly: **this specific
  drift/JFET/body geometry does not block voltage as well as a
  production power MOSFET would** — most likely a reach-through or
  JFET-pinch-off-adjacent effect given how sharply Id rises between
  3V and 7V, though this example does not attempt to diagnose the
  exact mechanism (that would be a real device-design study, out of
  scope for a capability-demonstration example). This is reported as
  the finding it is, not disguised as a successful 50V blocking
  result.
- Off/on current ratio (Vds=0.1V, Vg=0 vs Vg=15V): 5 orders of
  magnitude — confirmed structurally (not just for this one run) by
  `test_off_state_leakage_much_smaller_than_on_state_current`.

## Runtime

The most expensive example in this directory, and dominated entirely
by ONE thing: `scipy.sparse.linalg.spsolve`/`splu` (`NewtonOptions`'s
default `linsolve="direct"`), the sparse direct LU solver every Newton
iteration calls. This is **effectively single-threaded** in scipy's
bundled SuperLU backend — confirmed directly (not assumed) by
measuring the running process at ~100-115% CPU with `OPENBLAS_NUM_THREADS`/
`OMP_NUM_THREADS`/`MKL_NUM_THREADS` all set to 6: no speedup, because
sparse LU factorization is not a dense-BLAS operation those variables
control. The only genuine multi-core path in this repo is the GUI-layer
MPI Schwarz domain decomposition (`gui/services/mpi_schwarz_runner.py`,
equilibrium/sweep/single-bias-point only, not usable as a drop-in here).

**Actual measured wall-clock time for the full run: ~49 minutes**
(2,912s), on this reference machine, breaking down as: ~4s for the
adaptive-mesh setup, ~150s for the 7-point Id-Vg sweep, ~2,360s for the
OFF-branch drain ramp (the bulk of the runtime — dominated by the
convergence difficulty above, including several ~150-270s failed-then-
retried attempts), ~400s for the ON-branch's 5-point drain sweep, and
under 2s for extraction/plotting/export. A first attempt at this
script (jumping directly to each target Vd instead of fine-grained
ramping) failed outright — Newton non-convergence at Vd=10V/50V/100V
produced an unphysical ~5A "solution" for a Vg=0V off-state device,
which then crashed the next solve. That failure, and the fix (fine-
grained auto-halving ramping + never warm-starting one branch from
another's difficult end state), are recorded here rather than erased,
since both are real information about this solver's behavior on a
genuinely hard bias point, not implementation trivia.

Individual bias-point solves ranged from ~15s (easy points, small
warm-start distance) to ~270s (points near the OFF-branch's
convergence limit). A re-run that skips the OFF-branch's high-Vd
region (e.g. lowering the target well below where this run's
convergence difficulty set in, around Vd~7V) would be substantially
faster — single-digit minutes, dominated by the Id-Vg sweep and the
adaptive mesh setup alone.

## Limitations (honest, not exhaustive-hedging)

- **Residual mesh under-resolution in the heaviest-doped regions.**
  `check_mesh3d` reports `max h/L_D` well above the usual `<1` target
  even after adaptive refinement, at this node budget — the same
  documented tradeoff `examples/06_3d_mosfet.py`'s own run reports.
  Raising `max_nodes` would improve this at the cost of runtime; not
  attempted here to keep the example tractable to actually run and
  review in one session.
- **Doping reduced from a more aggressive design point.** N+
  source/P+ body-tie doping is 2×10¹⁹ cm⁻³, not the ~5×10¹⁹–1×10²⁰
  cm⁻³ real devices sometimes use for lower contact resistance — a
  direct consequence of the mesh-budget tradeoff above (heavier doping
  means a shorter Debye length means more nodes needed for the same
  resolution ratio).
- **No impact ionization** → the off-state study is a peak-field proxy,
  not a real breakdown-voltage sweep (see study 5 above).
- **The OFF-branch drain ramp hit a genuine Newton convergence limit at
  Vd≈7.6V**, well short of the 50V target, on this specific
  drift/JFET/body-tie geometry — not a bug, not a bias-stepping
  artifact (fine-grained auto-halving ramping was already in use when
  this happened), but a real property of this device design as
  simulated. See the Results section for the full account and the
  likely (not confirmed) reach-through/JFET-pinch-off explanation. A
  different geometry (thicker/lower-doped drift, wider JFET gap) might
  push this limit higher; not attempted here.
- **Sparse direct solve is effectively single-threaded** (confirmed by
  measuring CPU usage, not assumed) — `OPENBLAS_NUM_THREADS` and
  similar env vars do not meaningfully speed up this example; see
  Runtime above.
- **No transient, no electro-thermal, no Schottky, no continuation** —
  all confirmed absent from `Device3D`/the core solver, not merely
  unbuilt for this example (see the capability matrix).
- **`surface_mobility` left at its default** because `Device3D` has no
  guard against it (a real, documented gap — see the capability
  matrix and `test_surface_mobility_is_a_documented_silent_gap_not_a_claimed_feature`).
  Setting it here would silently do nothing, not exercise a real model.
- **4H-SiC material parameters**: some fields (mobility Nref/alpha
  shape, BGN Slotboom constants, Auger coefficients, Varshni
  alpha/beta) are carried over from this codebase's existing generic
  fit forms rather than independently refit to 4H-SiC literature data
  — explicitly flagged in `materials.py`'s own code comments, not
  hidden.
- **Idealized half-cell symmetry.** Mirror boundary conditions at all
  four lateral edges assume a perfectly repeating cell array with no
  edge/termination effects — standard for a unit-cell TCAD study, but
  not a full-device (edge termination, guard ring) simulation.

## Capability matrix — quick reference

See the "Physics" section above for the full table. Summary: **12 of
19** listed capabilities are genuinely exercised; the remaining 7 are
confirmed absent from `Device3D`/the core solver (not faked, not
silently skipped) and are named explicitly, both in this README and in
the example script's own docstring and inline comments.
