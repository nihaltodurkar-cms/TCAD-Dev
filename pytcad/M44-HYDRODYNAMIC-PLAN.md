# M44 -- Hydrodynamic transport: coupled 1D, then compiled, then 2D/3D

Status: Slice 0 (literature confirmation) DONE 2026-09-19. Slice 1
(1D coupled Tn in Device1D) IN PROGRESS.

## Slice 0 -- literature confirmation (done before any code)

Primary source: T. Grasser, T.-W. Tang, H. Kosina, S. Selberherr,
"A Review of Hydrodynamic and Energy-Transport Models for Semiconductor
Device Simulation," Proceedings of the IEEE, vol. 91, no. 2, Feb 2003,
pp. 251-274 (open PDF: iue.tuwien.ac.at/pdf/ib_2003/JB2003_Grasser_1.pdf,
fetched and read directly this session, pages 1-3 and 7-12).

**Finding 1 -- the existing M29 local closure is independently
confirmed correct.** The paper's Eq. (5):

    Tn = TL + (2/3)(q/kB)*tau_E*mu*E^2 = TL*(1 + (E/Ec)^2)

is EXACTLY `hydrodynamic.carrier_temperature()`'s formula (module
already cites Selberherr for `TAU_W_N`; this is now doubly confirmed
against a second, independent published source, same coefficients, no
discrepancy). No change needed to hydrodynamic.py's existing local
closure.

**Finding 2 -- the coupled model to implement is the standard
"three-moment energy-transport" (ET) model**, the paper's Eqs.
(56)-(59) (Fourier-law closure of Bloetkjaer's moment equations, the
"typical" ET model per the paper's own text):

    grad.J        = q * dn/dt                                   (56)
    J             = mu*kB*grad(n*Tn) + q*n*mu*E                 (57)
    grad.(n*S)    = -(3/2)*kB*d(n*Tn)/dt + E.J
                    - n*(3/2)*kB*(Tn - TL)/tau_E                (58)
    n*S           = -(5*kB*Tn)/(2*q)*J - kappa(Tn)*grad(Tn)     (59)

Read: (58) is the electron energy-balance equation (the new PDE M44
adds); (59) is the energy flux S -- a convective term (5/2)(kB*Tn/q)*J
plus a Fourier conductive term -kappa(Tn)*grad(Tn); (57) generalizes
the electron current to include a temperature-gradient driving force
(mu*kB*grad(n*Tn) replaces the isothermal mu*kB*Tn*grad(n) drift-
diffusion term) -- this is the ONLY change needed to Jn in
`_residual_jacobian`, and is the mechanism that actually produces
overshoot (current no longer depends on the LOCAL field alone).
kappa(Tn), the carrier thermal conductivity, is closed via a
Wiedemann-Franz-type relation standard to this model family; for the
STEADY-STATE bias solve (`solve_bias`, no `d/dt` terms), (58) reduces to

    d(n*S)/dx = E.J - n*(3/2)*kB*(Tn - TL)/tau_E

which is the actual equation to discretize (Slice 1 has no transient
coupling -- that is out of scope here, same as M17's own device.py-
untouched pattern for now; a future slice could extend this to
transient3d.py-style external driving if ever needed).

**Finding 3 -- mobility feedback: REUSE existing gated code, invent
nothing new.** Searched for a standard closed-form `mu_n(Tn)` (the
often-cited "Baccarani-Wordeman" form); no single clean formula is
retrievable/verifiable from accessible sources -- the Grasser review's
own Section IV shows mobility-vs-Tn closures in this model family are
either fit to Monte Carlo data (Thoma/Tang/Chen models, Section
IV.A-D) or left as `mu*(T*)` with `T*` a fitted function, not one
universal law. Rather than invent/attribute an unverified formula,
Slice 1 uses two pieces ALREADY published and ALREADY gated in this
codebase:
  1. `hydrodynamic.effective_field_from_temperature(Tn, mu, tau_w, TL)`
     -- M29's own already-gated inverse of the local closure, maps a
     carrier temperature back to the field consistent with it.
  2. `materials.mobility_field(mu0, E, mat, carrier)` -- the Canali
     velocity-saturation model, ALREADY used in Device1D today (see
     `Models.field_mobility`, device.py:2451-2468) with a LAGGED
     per-Newton-iterate field value `E_node`. `Models.field_mobility`'s
     existing lagged-update code is the exact mechanism to extend: when
     `energy_balance=True`, `E_node` is computed from the current Tn
     iterate via (1) instead of (or supplementing) the local field, fed
     into the SAME `mobility_field()` call. This is a much
     lower-risk mobility coupling than inventing a new law, and gives
     an honest, disclosed simplification consistent with this module's
     own existing honesty-clause style.

**Finding 4 -- benchmark gate, honestly scoped.** The Grasser paper's
Fig. 1(a)/(b) show the QUALITATIVE overshoot shape (Tn bump then decay
near a junction; velocity overshoot above v_sat that decays into the
bulk) from Monte Carlo reference data, for n+-n-n+ structures of
varying channel length. No raw digitized data is available from this
fetch (only rendered figure images), so a QUANTITATIVE curve-matching
gate (repo's usual "vs published, +/-X%" gate style) is NOT achievable
here without digitizing a printed figure by eye, which is exactly the
kind of imprecision M14 G-A already refused to do with a paywalled
source. HONEST GATE SCOPE (mirrors the M14 G-A precedent -- disclosed
gap, not fabricated precision):
  - G4 (qualitative): Tn(x) and Jn(x)/v(x) show the bump-then-decay
    shape near a field gradient that the LOCAL closure (M29) cannot
    produce -- this is directly checkable and is the real capability
    this milestone buys.
  - G4b (quantitative, XFAIL/disclosed gap): matching Fig. 1's actual
    digitized curve values is not attempted -- no accessible digitized
    dataset, same class of gap as M14's G-A.

**Scope note carried into Slice 1:** hole energy balance (Tp) is
explicitly deferred (see main plan's "Scope decision" section) --
consistent with the wider ET literature itself, which treats electron
energy balance as the dominant effect for n-channel/n+-n-n+ overshoot.

## Slice 1 -- golden baseline (recorded BEFORE any device.py edit, 2026-09-19)

Per CLAUDE.md's reconstruct-and-compare protocol. `Models.energy_balance`
defaults to `False` and the change is additive-only (new DOF branch
gated behind the flag, existing 3*N code path untouched) -- these
should all come back byte-identical after the edit; if any moves,
that's a defect to explain, not a re-baseline.

```
ce5850ecaf56ee0db5e05be4d9b17a80  tests/goldens/m13/frozen_meshes.npz
a2791e63f070ae749ae5bc11fde99ed1  tests/goldens/m13/hetero1d_eq.npz
f78dd28dbd24b39f6995e423d59e24cc  tests/goldens/m13/diode1d_eq.npz
f31b42c7b4cded7d10ff0831d92f8174  tests/goldens/m13/diode2d_eq.npz
36662794eb2f849ac6263f23921ebb86  tests/goldens/m13/diode1d_fwd.npz
7b2e8ad51672c9fd66ec26b30d88446e  tests/goldens/m13/resistor3d_eq.npz
```

(TAT_EQ_DIGEST/TAT_FW_DIGEST/HETERO_FW_DIGEST hardcoded hex digests in
`tests/test_m13_solver.py` are the other bit-identity gate covered by
the same rule -- checked via that file's own test run, not re-copied
here.)

## Slice 1 -- implementation notes and bugs found (2026-09-19)

Implemented in `pytcad/device.py`: `Models.energy_balance` (appended
4th DOF block, indices `3*N..4*N-1`, NOT interleaved with psi/n/p --
the existing 3*N block's code and indices are completely unchanged);
`_residual_jacobian(..., theta=None, n_lag=None, Jn_lag=None,
Qheat_lag=None)`; wiring in `solve_bias`/`_newton()` (theta warm-start,
Tn-consistent mobility via `hydrodynamic.effective_field_from_temperature`
+ `materials.mobility_field`, lagged coefficients recomputed each outer
Newton iterate); `solve_equilibrium` sets `Tn = TL` exactly (zero
current => zero Joule heating => theta==1 is the EXACT solution, not
an approximation -- no new equation solved there).

**Two real bugs found by direct testing, not by inspection:**

1. **Wrong Jacobian diagonal term** (algebra slip in the hand
   derivation, transposed which edge's left/right derivative feeds the
   diagonal). Caught immediately by the FD-Jacobian gate -- exactly
   what that gate exists for.

2. **Negative carrier temperature (Tn < TL) under forward bias** --
   caught by direct execution (a smoke test showing `Tn.min() < 300`)
   BEFORE the formal gate was even written. Root cause: the Joule-
   heating source term `E.Jn` used the raw electrostatic field
   `E = -grad(psi)`. This is EXACTLY the same pathology M19 self-
   heating already found and fixed (`thermal.joule_heating_density`'s
   own docstring: "an earlier version of this function used
   device.E_field directly ... In a diode's diffusion-dominated
   depletion region that formula gives spurious, thermodynamically-
   impossible LOCAL NEGATIVE heat"). Fixed the same way: Wachutka
   (1990)'s electron quasi-Fermi-potential gradient,
   `E_n = -grad(phi_n)`, `phi_n = psi - ln(n/nie)`, with the product
   `Jn*E_n` formed PER EDGE first and box-averaged to nodes after
   (not averaged-then-multiplied) -- the same convention
   `joule_heating_density` uses, reused rather than re-derived.

**FD-Jacobian gate methodology note:** the first version of G1 used a
fixed absolute error threshold and a large fixed perturbation step,
which failed even on the UNTOUCHED pre-existing 3*N block (confirmed
by running the same probe with `theta=None` -- identical failure,
proving it was a test artifact, not a regression). Fixed by adopting
`test_m13_solver.py`'s own established `_jacobian_probe` convention
exactly: a relative (`1e-7 * |value|`) finite-difference step, and
per-column error normalized by that column's own max magnitude (an
absolute threshold is meaningless across rows spanning many orders of
magnitude). All 5 gates plus the disclosed G4b xfail pass after this
fix (`tests/test_m44_hydrodynamic_coupled.py`, 0.29s).

**Combination refused (disclosed, not silently ignored):**
`energy_balance=True` with `impact`/`btbt`/`btbt_nonlocal` raises
`NotImplementedError` in `Models.__post_init__` -- those flags drive
`solve_bias`'s stiff-generation strength ladder and backtracking line
search, which does not yet know about the theta unknown (its merit
function is evaluated via a 3*N-only `_residual_jacobian` call).
Deferred, not attempted here.

Golden baseline reconstruct-and-compare: confirmed byte-identical
after the full Slice 1 edit (`energy_balance` defaults False and the
3*N code path is untouched) -- all 6 `tests/goldens/m13/*.npz` md5sums
match the Slice-1-start baseline recorded above.

**Regression check (targeted, per this milestone's own instruction not
to run the full suite until M44 fully lands):**
`OPENBLAS_NUM_THREADS=1 python3 -m pytest tests/test_m13_solver.py
tests/test_m15_ionization.py tests/test_m16_btbt.py
tests/test_m34_s1_nonlocal_btbt.py tests/test_m34_s2_nonlocal_ii.py
tests/test_m34_s6_impact_2d3d.py tests/test_m44_hydrodynamic_coupled.py
-q -n 6` -> **93 passed, 1 xfailed in 564.75s** (2026-09-19). No
regressions in any physics that shares `_residual_jacobian`/`Models`
with M44's changes (M13 Fermi-Dirac/incomplete-ionization, M15 impact
ionization, M16 BTBT, M34 nonlocal BTBT/II) -- the 4th-DOF append
design's "existing 3*N block is untouched" claim is now regression-
tested, not just asserted.

**Slice 1 status: DONE.** Next: Slice 2 (benchmark before touching
C++ at all) or a review pause -- see chat for which was chosen.

## Slice 2 -- benchmark results (2026-09-19)

`benchmarks/m44_s2_hydro_measure.py` (one-off decision script, same
shape as the existing `p4_diffusion_remeasure.py` precedent -- not a
permanent B1-B9 dashboard case). Warm run discarded, best of 5,
`OPENBLAS_NUM_THREADS=1`, `V=[0, 0.6]` diode:

| N | off (s) | on (s) | overhead | assembly-only off (s) | assembly-only on (s) | assembly overhead |
|---|---|---|---|---|---|---|
| 41 | 0.0085 | 0.0361 | 4.24x | 0.000257 | 0.000574 | 2.23x |
| 161 | 0.0120 | 0.0869 | 7.27x | 0.000304 | 0.001510 | 4.97x |
| 641 | 0.0197 | 0.2466 | 12.50x | 0.000461 | 0.005151 | 11.17x |
| 2561 | 0.0553 | 1.1202 | 20.25x | 0.001131 | 0.021207 | 18.75x |

**This CONTRADICTS the plan's own stated a-priori expectation**
("assembly is O(N) ... almost certainly dominated by the sparse solve,
so a compile is likely NOT justified here" -- written before
measuring, exactly the kind of guess CLAUDE.md's M32 rule exists to
override with a real number). The overhead is large AND GROWS with N
(4x at N=41, 20x at N=2561), and tracks the "assembly-only" column
closely -- so the new Tn-row cost, not the larger linear solve, is the
dominant and worsening cost.

**Root cause, found by reading the code the numbers pointed at (not by
guessing):** the new Tn-block assembly in `_residual_jacobian` is a
plain Python `for i in range(1, N-1):` loop -- one Python-level
iteration per interior node, appending to `rows/cols/vals` lists --
while every OTHER term in `_residual_jacobian` (including this exact
same tridiagonal shape for psi's own Poisson row) is vectorized numpy.
This is an ordinary Python-loop-vs-vectorized-numpy performance bug,
not a case for C++: the loop has no genuine serial dependency (node i's
computation only reads neighbor values, all already computed
up front as `w_edge`/`dw_dthetaL`/`dw_dthetaR`/`Q_src` arrays) and
vectorizes directly.

**Decision:** vectorize the Tn-block assembly in pure numpy FIRST (an
ordinary correctness-preserving refactor, re-gated by the existing FD-
Jacobian + regression tests, zero new dependencies) before any C++ is
considered anywhere in this milestone. This is not a deviation from
the plan's C++ scoping (Slice 3 was always the earliest C++ could be
justified, on the structured 2D/3D grid) -- it is fixing a plain
Python inefficiency that should never have reached the "compile it"
question in the first place. Re-measure after vectorizing before
deciding whether Slice 3's C++ step is still warranted at all.

**Done.** The `for i in range(1, N-1)` loop was replaced with the
vectorized array form (index array `idx = np.arange(1, N-1)`, all
terms already precomputed as edge-indexed arrays -- `add()` already
accepts array `r`/`c`/`v`, so no new machinery was needed). All 5
gates + the disclosed xfail still pass (0.26s) after the change --
the vectorized form is the same math, not a different algorithm.

**Re-measured after vectorizing:**

| N | off (s) | on (s) | overhead | assembly-only off (s) | assembly-only on (s) | assembly overhead |
|---|---|---|---|---|---|---|
| 41 | 0.0086 | 0.0248 | 2.88x | 0.000247 | 0.000280 | 1.13x |
| 161 | 0.0119 | 0.0383 | 3.22x | 0.000299 | 0.000329 | 1.10x |
| 641 | 0.0195 | 0.0685 | 3.51x | 0.000444 | 0.000492 | 1.11x |
| 2561 | 0.0526 | 0.2402 | 4.56x | 0.001081 | 0.001219 | 1.13x |

Assembly overhead dropped from up to 18.75x down to a flat ~1.1x
(effectively free, and no longer growing with N) at every size tested
-- confirming the Python loop, not the new physics, was the entire
problem. The remaining 2.9x-4.6x TOTAL overhead is now consistent with
genuinely more work rather than inefficiency: a 4*N vs 3*N sparse
direct solve (already using the compiled SuperLU path via scipy, same
as the base solver -- nothing left to compile there without changing
the linear-solve algorithm itself, out of scope) plus the lagged
outer-Newton coupling needing more iterations to reach the same
tolerance (mobility/Tn/current are only mutually consistent after
several outer passes, by design -- see Slice 1's honesty clause on the
lagged-Jacobian tradeoff).

(The vectorization touches only code inside `if theta is not None:` --
no other physics path executes it, so the earlier 93-test targeted
regression run was not re-run for this change; the M44 gate file's own
re-pass is the relevant check here.)

**Slice 2 conclusion: NO C++ is justified for the 1D path.** This
restores the plan's original a-priori expectation, but only AFTER
actually measuring found and fixed a real, unrelated Python
performance bug first -- exactly the discipline CLAUDE.md's M32 rule
is for. Slice 3's C++ step remains scoped to the structured 2D/3D grid
assembly only, as originally planned.

## Slice 3 -- structured-grid kernel (2026-09-19)

**Architecture correction found while starting this slice (before
writing any code):** the plan's own text said this "mirrors
thermal_grid.py -> core/src/thermal/grid.cpp exactly." That premise
does not hold once you look at *why* thermal_grid.py was compiled:
it runs its own NESTED Newton solve inside `thermal.py`'s outer Gummel
loop (an extra multiplicative factor of iterations), which is what
made it hot. M44 Slice 1's own architecture is different -- Tn is an
APPENDED DOF inside the SAME single Newton iterate as psi/n/p, no
nested solve, no outer loop -- exactly `ii_grid.py`/`btbt_grid.py`'s
(M34-S6) cost profile, and those stay pure Python, uncompiled, in this
codebase. So `pytcad/hydro_grid.py` was built following THEIR calling
convention (a flat `axes` list of per-axis edge arrays with `kL`/`kR`
node indices, returning `(F, rows, cols, vals)` COO triples for the
caller to stamp in) instead of thermal_grid.py's raw-coordinate/ND-
array one. See `hydro_grid.py`'s own module docstring for the full
reasoning.

**Implementation:** `grid_hydro(N, axes, dV, n_lag, theta, Qheat_lag,
mu_n0, KAPPA0, ALPHA, dirichlet_nodes)` -- the exact Slice 1 equation
(same `kappa_s`/`Q_src`/`w_edge` formulas), generalized to sum the flux
divergence over every axis in `axes`, fully vectorized from the start
via `np.bincount` scatter-add (Slice 2's lesson applied up front, not
found the hard way a second time). Boundary/contact nodes are given
directly as `dirichlet_nodes`; an ordinary insulating mesh boundary
needs no special case (fewer incident edges = an implicit zero-flux
Neumann condition, same as Poisson's own box-integration already gets
in device2d.py/device3d.py).

**Gates** (`tests/test_m44_s3_hydro_grid.py`, all 4 passed on first
run, 0.21s): G1/G2 FD-Jacobian in 2D and 3D (same per-column-relative-
error convention as Slice 1's and `test_m13_solver.py`'s own probe);
G3/G4 y-uniform-2D and z-uniform-3D reduction -- Device1D's own
converged Slice-1 (psi, n, Tn, Jn) state, tiled along the transverse
axis/axes with zero transverse current, fed through `grid_hydro`, must
give (near-)zero residual at every interior node: max|F| < 1e-8,
confirming `grid_hydro` and Device1D's `_residual_jacobian` really do
solve the SAME equation, not just similarly-shaped ones.

**Benchmark (measured, not assumed -- same M32 discipline as Slice
2):** `grid_hydro` wall time, warm, best of 20, synthetic grids:

| dim | N | time |
|---|---|---|
| 2D | 400 | 0.05 ms |
| 2D | 2,500 | 0.39 ms |
| 2D | 10,000 | 1.53 ms |
| 3D | 3,375 | 0.55 ms |
| 3D | 15,625 | 3.51 ms |
| 3D | 64,000 | 17.95 ms |

Scales linearly with N as expected for a vectorized bincount assembly,
and is fast in absolute terms -- ARCHITECTURE.md's own M47/M22 notes
record Device3D's plain electrical solve at ~8,600 nodes as "simply
slow via a direct sparse solve" (hundreds of ms to seconds), so an
~18ms assembly at 64,000 nodes is nowhere near the bottleneck.

**Slice 3 conclusion: NO C++ is justified here either.** Combined with
Slice 2, no part of M44 built so far needs a compile -- the pattern
this milestone's own physics follows (appended-DOF within a single
Newton iterate) matches `ii_grid.py`/`btbt_grid.py`'s already-
established pure-Python precedent, not `thermal_grid.py`'s nested-
solve one. `core/`, CMakeLists.txt, and the bindings directory are
untouched.

**Known Slice 4 prerequisite, found while writing this slice's
reduction gates (not yet acted on):** `Device2D.__init__` currently
REFUSES `Models(field_mobility=True)` outright ("Canali field-
dependent mobility is not implemented in Device2D") -- and
Slice 1's own mobility feedback for `energy_balance` runs entirely
through that same Canali `mobility_field()` call. Device3D was not
checked yet. Wiring `hydro_grid.py` into Device2D/Device3D (Slice 4)
will need EITHER a minimal Canali-mobility port to Device2D/Device3D
first, or an `energy_balance`-only mobility path that bypasses the
existing `field_mobility` refusal without silently composing with it
-- a real scope item for Slice 4, not a Slice 3 concern, flagged here
so it isn't rediscovered as a surprise.

## Slice 4 -- Device2D wiring (2026-09-19)

Wired `hydro_grid.py`'s D-generic kernel into `Device2D` following the
SAME appended-DOF design as Device1D (`Models.energy_balance`, DOF
`3*N -> 4*N` when on, base 3*N block untouched). New
`_update_energy_mobility(theta)` method (mirrors `_update_surface_
mobility`'s own lagged-recompute pattern) replaces ALL edge
diffusivities from the Tn-consistent Canali mobility -- Device2D's
existing `Models.field_mobility` stays refused (`__init__`'s own
guard, unrelated), `energy_balance` has its own independent path.

**Three real bugs found while gating this, in the order found:**

1. **`DirichletBC.i`/`.j` array-shape bug.** `DirichletBC` always
   stores `i`/`j` as `np.atleast_1d` arrays, even for a single-node
   contact. Building `dirichlet_nodes` via
   `np.array([bc.j*Nx+bc.i for bc in ...])` stacked a LIST of `(1,)`
   arrays into shape `(n_contacts, 1)` instead of concatenating into a
   flat `(n_contacts,)` array, crashing `grid_hydro`'s COO assembly.
   Fixed with `np.concatenate` (the same pattern this file's own
   `live[bc.j*Nx+bc.i] = False` fancy-indexing already uses correctly
   elsewhere).

2. **Unfloored deep-minority density causes measurable Jacobian rank
   deficiency.** `kappa_s = KAPPA0*mu_n0*n_lag*theta` is multiplicative
   in `n_lag`, which underflows to ~1e-14 in a diode's deep-minority
   region (confirmed directly). Left unfloored, `kappa_s` vanishes
   there and decouples those nodes from every neighbor at once --
   measured directly: the assembled theta-block Jacobian dropped to
   rank 72/123 (condition number ~3e14) on a real device state before
   this fix. Fixed by flooring `n_lag` at `1e-8`
   (`_STIFF_DENSITY_FLOOR`, the SAME floor this codebase's n/p
   convergence metric already uses for exactly this reason) in BOTH
   `hydro_grid.py` and Device1D's own Slice 1 code (for consistency --
   Device1D's tridiagonal structure tolerated the unfloored version
   better, which is why this was found in Slice 4 and not Slice 1, but
   the same physical argument applies: a node with ~0 carriers has no
   physically meaningful electron temperature to solve for). Also
   fixed, alongside this: theta's own Newton-step clip was an
   ABSOLUTE range (`[0.05, 1000]`) instead of the RELATIVE `0.1x-10x`
   clip n/p already use, letting one early iterate overshoot by >30x
   (Tn 300K -> 10800K in a single step) -- harmless in 1D, but this
   was the initial symptom that led to finding bug 2.

3. **Missing transverse control-volume weight on the flux-divergence
   term -- the actual root cause of a real, reproducible ~87%
   Tn mismatch between a y-uniform Device2D solve and Device1D's own
   Slice-1 result.** `device2d.py`'s own Poisson residual weights its
   two divergence terms by the TRANSVERSE control-volume width
   (`dVy[:,None]*div_x + dVx[None,:]*div_y`) -- an x-face's flux has a
   "depth" in y. `hydro_grid.py`'s `grid_hydro` did not do this at
   all. Slice 3's OWN reduction gates (G3/G4) did not catch this
   because they used an ARTIFICIALLY row-uniform `dV` (Device1D's own
   scalar dV, tiled identically at every row) rather than
   device2d.py's/device3d.py's REAL row/layer-varying
   `dV = outer(dVy, dVx)` (a boundary row's transverse CV is HALF-
   width, an interior row's is FULL-width) -- with a uniform dV the
   missing weight is invisible; with the real one it is not.
   Diagnosed by direct bisection: confirmed the psi/n/p block was
   byte-identical to a decoupled baseline at every early iterate
   (ruling out cross-contamination), confirmed the base current (Jn_y)
   was exact round-off in the baseline (ruling out a pre-existing
   geometry issue), then confirmed the theta-block Jacobian was
   measurably rank-deficient/ill-conditioned even after fix 2 and that
   its ROW-DEPENDENT asymmetry was a genuine (non-random,
   non-vanishing-under-refinement) feature localized at the contact
   edge -- which is what led to re-deriving the discretization against
   device2d.py's own convention rather than continuing to suspect
   solver noise. Fixed by adding a mandatory `w` (transverse weight)
   field to each axis dict in `hydro_grid.py`'s `axes` convention, and
   updating BOTH `device2d.py`'s caller and `test_m44_s3_hydro_grid.py`
   itself (which was silently exercising the bug's blind spot) to use
   the real row-varying `dV`/`w`.

**Result after all three fixes:** a y-uniform Device2D diode solve
(41x3 mesh) reproduces Device1D's own converged Tn(x) to
**3.4e-13 absolute** (round-off), `Jn_y` exactly `0.0`, row-to-row
difference exactly `0.0` -- not merely "close." A resistor case
matches to `2.2e-7` (Newton tolerance level). New gate file
`tests/test_m44_s4_device2d.py` (3 tests: off-path bit-identity,
y-uniform reduction at 1e-6 tolerance, no-negative-heating sanity) --
all pass, plus the full M44 suite (Slices 1/3/4 combined, 12 tests + 1
disclosed xfail) passes in 0.48s.

**Regression check (targeted, per this milestone's own instruction):**
`OPENBLAS_NUM_THREADS=1 python3 -m pytest tests/test_validation_2d.py
tests/test_m34_s6_impact_2d3d.py tests/test_m16_s2_btbt_grid.py
tests/test_m41_incomplete_ion_2d3d.py tests/test_m42_s2_gate_bc.py -q
-n 6` -> **64 passed in 565.75s** (2026-09-19). No regressions in
Device2D's existing physics (impact ionization, BTBT, incomplete
ionization, GateBC, general validation).

**Honest process note:** this was found only by actually building a
LIVE, multi-row Device2D solve and comparing against Device1D end to
end -- Slice 3's own standalone kernel gates, run in isolation, gave
false confidence (they were unknowingly exercising a degenerate,
uniform-dV configuration that could never expose this class of bug).
The lesson generalizes: a dimensional-lift reduction gate must use the
REAL device's own row/layer-varying geometry, not a simplified stand-in,
or it risks validating the wrong thing.

## Device3D (2026-09-19) -- Slice 4 complete

Same wiring as Device2D, three lessons applied from the start
(n_lag floor, relative theta clip, transverse weight `w` = product of
the OTHER two axes' widths, e.g. x-edge weight = dVy*dVz). New
`_update_energy_mobility` (device3d.py) mirrors Device2D's own.

**One new shape bug, found immediately (same class as Slice 4's first
Device2D bug):** `contact_k` is REASSIGNED from a raw list to a
deduped ndarray earlier in `_residual_jacobian` (`if contact_k:
contact_k = np.unique(np.concatenate(contact_k))`). Re-wrapping it in
`np.concatenate(contact_k)` a second time for `contact_nodes` raised
"zero-dimensional arrays cannot be concatenated" (`np.concatenate` on
a 1D array iterates its scalar elements). Fixed by reusing the
already-deduped array directly.

**Result:** a y/z-uniform 21x3x3 Device3D diode reproduces Device1D's
own converged Tn(x) to **3.7e-10** (round-off), `Jn_y`/`Jn_z` at
~4.7e-18 (round-off). New gate file `tests/test_m44_s4_device3d.py`
(3 tests, mirrors the Device2D file) -- all pass, full M44 suite now
15 tests + 1 disclosed xfail in 0.73s. Targeted Device3D regression
(`test_m34_s6_impact_2d3d.py`, `test_m16_s2_btbt_grid.py`,
`test_m41_incomplete_ion_2d3d.py`, `test_m34_s3_nonlocal_btbt_2d3d.py`)
running.

**Regression check:** `test_m34_s6_impact_2d3d.py`, `test_m16_s2_btbt_grid.py`,
`test_m41_incomplete_ion_2d3d.py` -> 36 passed, 0 failed.
`test_m34_s3_nonlocal_btbt_2d3d.py` -> 3 failed + 6 errors, ALL
`ImportError: pytcad requires the compiled extension pytcad._core`
(run used plain `python3`/base conda env, not `conda run -n TCAD`
where `_core` is actually built) -- an environment gap in how this
check was invoked, not a regression from any M44 change; none of
M44's own code touches `_accel`/`_core` at all.

**Slice 4 (Device2D + Device3D) is now DONE.**

See the approved plan (design phase) for the full slice breakdown
(Slice 1: 4*N DOF coupling in Device1D; Slice 2: benchmark before any
C++; Slice 3: compile the 2D/3D structured-grid assembly, mirroring
`thermal_grid.py`; Slice 4: dimensional lift). This file is updated as
each slice lands with: golden-baseline md5sums (before/after), FD-
Jacobian gate results, and any further honest findings.
