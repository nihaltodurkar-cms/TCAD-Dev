# M34 — Nonlocal Tunneling & Impact Ionization: Milestone Plan

## Status, 2026-09-11 -- all five slices landed

Read this first; sections 0-7 below are the plan as written before
execution, and this section records where the work departed from it and
why. Every number here was measured in this session.

| slice | result | gates |
|---|---|---|
| S1 1D nonlocal BTBT | landed | `tests/test_m34_s1_nonlocal_btbt.py`; G2/G7 in `test_model_benchmarks.py` |
| S2 1D nonlocal impact ionization | landed | `tests/test_m34_s2_nonlocal_ii.py`; 4 benchmarks in `test_model_benchmarks.py` |
| S3 structured 2D/3D nonlocal BTBT | landed | `tests/test_m34_s3_nonlocal_btbt_2d3d.py` |
| S4 compiled path tracer | landed | `tests/test_m34_s4_trace_parity.py`; benchmark B10 |
| S5 catalog / wire format / GUI | landed | `tests/test_m34_s5_catalog.py` |

### S1 -- what was built, beyond section 2's design

- Exact per-segment WKB quadrature (`btbt.segment_integrals`, closed
  antiderivatives in theta = asin(alpha)). The uniform-field reduction
  to the published eq (8) now holds to rounding at ANY resolution (rel
  1e-12, a single edge included), where the midpoint rule converged as
  N^-1/2.
- kappa is computed WITHOUT cancellation at the band edges
  (`btbt._kane_alpha_c`: 1 +- alpha from S^2 - S0^2 = u*delta). The
  direct form returned kappa = 0 below delta ~ 1e-16, making 1/kappa a
  divide-by-zero at a positive delta; `segment_integrals` is gated finite
  on adversarial inputs.
- Live prefactor and band extrema, interpolated electron deposit at the
  delta = 1 crossing, span margin to delta = 1.5 -- as designed.
- Refresh after convergence re-solves with PLAIN full-step Newton: at
  round-off the stiff-generation backtracking rejected a physical step
  (a new path dominating a deep-minority node, dp/p = 0.38 at p ~ 3e-22)
  and never closed.
- Interior nodes only: the first-principles current is large enough to
  put > 1e3 V/cm on the contact edge, and a path starting on a Dirichlet
  node lost its holes to the row overwrite.
- Measured: G4 FD Jacobian < 5e-5 on every column at -2/-4/-6 V; G5 pair
  conservation to rel 1e-12; G6 converges on 0.5 V and 0.25 V ramps;
  G6b the two ramps agree to 7e-15 in psi, 1e-15 of n+p in densities,
  current exactly; G3 transmission bracketing and G7 tunnel length hold
  as theorems of the exact quadrature.

### S2 -- departures from section 3

- Transport direction: the field sign on STRONG edges (>= 100 V/cm,
  below which alpha underflows to exactly 0), inherited from the nearest
  strong edge otherwise. Neither the field sign nor the carrier's own SG
  current is usable in a quasi-neutral region under reverse bias: the
  field is round-off (|dpsi| ~ 1e-14 on an n+ side) and the majority
  current changes sign 8 times across the n+ edge of a junction (a
  difference of two huge, nearly equal SG terms).
- Convergence: with an M34 flag on, `Device1D.solve_bias` measures
  density updates against the M11-S5 floor Device2D/3D already use
  (1e-10 scaled). Full Newton steps at |F| ~ 1e-13 move deep-minority
  densities by ~1e-4 relative every iteration, so the raw test never
  closed. M15/M16 alone keep the raw test -- bit-identical by choice.
- Measured: lambda -> 0 differs from the local model by an upwind-vs-
  centred O(h) term, 3.45e-2 -> 1.13e-2 for h_max 4e-6 -> 1e-6 cm; at an
  abrupt 1e18/1e18 junction at -3 V the peak effective field is 0.445 of
  the peak field and generation 0.296 of the local model's (Slotboom's
  narrow-peak claim); in a p-i-n plateau E_eff/E - 1 <= 9.9e-5; the FD
  gate follows M15's G-B method, with density-column steps floored at
  1e-7*max(|u|, 1e-4) (M15's absolute 1e-7 is central-difference
  truncation where n ~ 2e-6 sits beside a zero-crossing |Jn|: 1.1e-3 ->
  3e-10 as the step shrinks).

### S3 -- the tracer, and what the dimensional-reduction gate found

`nonlocal_path.build_structured` traces field lines (Esseni 2017 sec 2.4
"dynamic path"). The 2D/3D -> 1D reduction gate found four tracer
defects, each fixed at its cause:
1. steps landing one ulp short of a face ended paths early (42 of 52
   per row lost) -- every reached face is now landed on exactly;
2. the central-gradient start screen disagreed with Device1D's forward-
   edge test at the depletion edges -- the screen is now the field along
   the path's first segment;
3. round-off gave boundary-row paths an outward normal component that
   pushed them out of the domain -- an insulating boundary now drops the
   outward component (exact for Neumann boundaries; an approximation at
   a gate/Robin boundary, stated in the catalog);
4. on a noisy field a path wandered 100,000 steps -- a path now stops
   after 64 steps without a new psi maximum or beyond margin*Eg/(q*1e3
   V/cm), where transmission is negligible.
Measured: transverse-uniform 2D and 3D devices reproduce Device1D at
-6 V to 1.4e-13 in psi, 4e-14 of n+p in densities, 1.3e-14 in current;
FD Jacobian 6e-8 (2D, every psi column) and 1.6e-8 (3D, 80 columns);
exact pair conservation; straight paths along a uniform diagonal field
match Eg/(qF) to 4.2e-12 (2D) and 1.1e-10 (3D); an L-shaped 2D corner
junction with curved paths converges, conserves and passes the FD gate.

### S4 -- compiled tracer

`pytcad._core.trace_paths` (`core/src/nonlocal/paths.cpp`, bindings in
`core/bindings/nonlocal_bindings.cpp`) mirrors `_trace_paths_py`
operation for operation; that translation unit is built with
`-ffp-contract=off`. Parity: 7 gates, `np.array_equal` on every output
array (diagonal fields in 2D/3D, a curved junction, a noisy field, an
empty case, a real Device2D state, malformed-input refusal). Only the
stepping loop is compiled -- `evaluate` stays numpy. Benchmark B10 is a
2D nonlocal-BTBT bias solve on a corner junction (equilibrium -> -0.5 V;
7,110 DOF, 171,948 NNZ, 17 assembly calls, 16 linear solves). Quick
size, best of 3: 4.64 s total with the Python tracer, 2.08 s compiled;
the linear solves are unchanged (1.28 s vs 1.31 s), the difference is
the two path builds per solve (one inside the first assembly call).
A tracer-only B10 was tried first and refused by the harness contract
(`test_case_runs_and_reports_a_real_measurement` requires an observed
solve), so no tracer-only figure is quoted. No other speed claim is made.

### S5 -- exposure

`btbt_nonlocal` and `impact_nonlocal` are ModelCatalog entries (default
off, citations, limitations) and `_default_models()` keys, so the
Physics Lab shows them and `Models(**spec.models)` carries them into a
job. `ModelCatalog.validate` refuses `impact_nonlocal` without `impact`.
One pre-existing test changed by necessity: `test_workbench_m1.py`'s
literal set of catalog keys.

### Found along the way, outside M34 proper (fixed)

- Unstructured `Device2D` silently ignored `impact` and `btbt` (the
  structured refusals run after the unstructured branch returns); both
  are now refused there, with the two M34 flags.
- ARCHITECTURE.md 4d.1 claimed coupled local impact ionization and local
  BTBT in 2D/3D; Device2D/Device3D refuse both. Corrected.

### Still open (recorded, not fixed)

- A direct 0 -> -5 V solve stalls in the strength ladder's 0.0 stage on
  the 5e19 tunnel diode for M15, M16 and M34 alike (backtracking at a
  non-round-off residual); ramps avoid it.
- The fast suite carried 39 warnings before M34 (mesh.py, adapt.py,
  scipy/numpy), so the zero-warnings invariant was already broken.

### Suites (final code, 2026-09-11)

Fast suite (`-m "not slow"`, `-n 6`): `PYTCAD_ACCEL=1` 1731 passed, 5
skipped, 1 xfailed; `PYTCAD_ACCEL=0` 1723 passed, 13 skipped, 1 xfailed;
39 warnings each, the pre-M34 count and sources. Slow battery:
`PYTCAD_ACCEL=1` 26 passed; `PYTCAD_ACCEL=0` 20 passed, 6 skipped. The
xfail is M14 G-A. Golden md5s unchanged (section 1). Three pre-existing
tests changed, each because it pins a list M34 grows: the catalog key
sets in `test_workbench_m1.py` and `gui/tests/test_physics_lab.py`, and
the benchmark case list in `test_m32_benchmarks.py`.

### Honest limits (by design)

Single dominant zero-transverse-momentum channel with (fc - fv) = 1, so
nonlocal BTBT generates at zero bias too; first-principles Kane, not
calibrated; homojunctions only; structured meshes only in 2D/3D;
nonlocal impact ionization in 1D only, lambda_p = lambda_n, and its
source was the Slotboom 1991 abstract, not the paper's body.

Written 2026-09-11, after M34-S1's second pass (`M34-S1-PLAN.md` section
9). The user's instruction was "Fully implement M34, make plans and
execute", so this plan is executed in the same session. That instruction
is the explicit sign-off CLAUDE.md requires for each core amendment
below (`device.py`, `device2d.py`, `device3d.py`, `btbt.py`,
`ionization.py`). Every amendment still carries the house gates:
default-off bit-identity, FD-Jacobian first, and published-value
benchmarks in `tests/test_model_benchmarks.py`.

## 0. What "fully" means here, and why

The roadmap line (ARCHITECTURE.md 4c, M34) is "nonlocal tunneling and
ionization ... path integration along field lines". The 4d.1 coverage
matrix gives M34 one row: **BTBT, nonlocal — 1D, 2D, 3D**.

One correction was found while scoping: the matrix marks local impact
ionization and local Kane BTBT as working in 1D/2D/3D, but
`Device2D.__init__` and `Device3D.__init__` both RAISE on
`Models(impact=True)` and `Models(btbt=True)` ("Device1D only"). Both
local models are 1D-only. That determines the scope:

| piece | 1D | 2D | 3D | slice |
|---|---|---|---|---|
| nonlocal BTBT (Kane WKB path, Esseni 2017 eq 11) | yes | yes | yes | S1, S3 |
| nonlocal impact ionization (effective field) | yes | — | — | S2 |
| compiled path kernel (M31 P4 pattern) | — | yes | yes | S4 |
| catalog / DeviceSpec / GUI exposure, docs | yes | — | — | S5 |

Nonlocal impact ionization in 2D/3D is **out of scope**: it modifies
the ionization coefficient of a coupled local II model, and 2D/3D have
none (the M15 2D/3D port is its own follow-up). Nonlocal BTBT in 2D/3D
does NOT depend on local BTBT there -- it needs only the generation
deposit, so it is in scope.

Also out of scope (named, not silently dropped): phonon-assisted BTBT;
eq (11)'s full integral over tunneling energies (S1's single dominant
channel stays); quantization corrections; nonlocal BTBT on unstructured
2D/3D meshes (refused loudly); nonlocal BTBT across heterointerfaces
(refused loudly, as S1 already does).

## 1. Golden baseline (reconstruct-and-compare protocol, step 1)

Every change below is behind a default-off flag. md5s before any M34
work (re-verified 2026-09-11, this session):

    diode1d_eq.npz      f78dd28dbd24b39f6995e423d59e24cc
    diode1d_fwd.npz     36662794eb2f849ac6263f23921ebb86
    diode2d_eq.npz      f31b42c7b4cded7d10ff0831d92f8174
    frozen_meshes.npz   ce5850ecaf56ee0db5e05be4d9b17a80
    hetero1d_eq.npz     a2791e63f070ae749ae5bc11fde99ed1
    resistor3d_eq.npz   7b2e8ad51672c9fd66ec26b30d88446e

No golden is expected to move. One that moves is a defect.

## 2. S1 completion — 1D nonlocal BTBT

Open item from `M34-S1-PLAN.md` section 9: G6 (ramp convergence) fails
because the edge-midpoint quadrature is nearly discontinuous when a
node crosses a turning point. Scoping S1's completion found three more
places where a per-call FROZEN value makes the converged answer depend
on the solve path (warm start), which is a correctness defect, not
just a convergence one:

- `|dEv/dx|_xi` (eq 11's prefactor) is frozen at the warm-start state:
  a -6V solve reached from -5.5V uses the -5.5V field.
- `Emin/Emax` (km^2, eq 12) likewise.
- The electron deposit node j is the first node past delta = 1 at the
  warm start, not at the converged state.

Design (only the node span stays frozen within a Newton solve):

1. **Exact per-edge quadrature.** delta is linear in x along each edge
   (psi is piecewise linear). With theta = asin(alpha), eq (9) gives
   closed antiderivatives in delta:
       G(delta) = hbar/(2u sqrt(mr Eg)) * (u*theta - cos(theta))
       K(delta) = sqrt(mr Eg)/(2u hbar) *
                  (u*(theta + sin(theta)cos(theta))/2 - cos(theta)^3/3)
   with dG/ddelta = 1/kappa and dK/ddelta = kappa (checked by hand). An
   edge contributes h/|d_delta| * [F(hi) - F(lo)] over the part of its
   delta range inside (0, 1); edges outside contribute exactly 0. This
   is continuous in psi (no kappa floor), exact for a uniform field
   (G2 becomes a rounding-level gate), and its derivative is the chain
   rule through the clamped endpoints. Near-flat edges (|d_delta| <
   1e-10) use h*f(delta_mid) to avoid cancellation.
2. **Live prefactor and band extrema.** `|dEv/dx|_xi` from the start
   edge's live psi difference; Emin/Emax from live psi extrema (their
   argmin/argmax columns).
3. **Interpolated electron deposit.** The live delta = 1 crossing on
   edge (m, m+1) is at t = (1 - delta_m)/(delta_m+1 - delta_m); the
   electron count is split (1-t, t) between the two nodes. It sums to
   the hole count exactly (G5 holds by construction) and is continuous
   as the crossing moves.
4. **Span margin.** The frozen span runs past the delta = 1 node until
   delta >= 1.5 (or the device end), so a Newton-time relaxation of psi
   does not truncate the path. Edges past the crossing contribute
   exactly 0.
5. **Window refresh.** After Newton converges, `solve_bias` re-locates
   windows at the converged psi. If the window set changed, it re-solves
   (at most 4 refreshes; failure to stabilize is reported, not hidden).
   The converged state is then consistent with its own windows.

Gates (test_m34_s1_nonlocal_btbt.py unless noted):
- G1 off bit-identity (exists).
- G2 uniform-field reduction to published eq (8): now EXACT to
  rounding -- tighten test_model_benchmarks.py to rel 1e-12 at every N
  instead of the N^-1/2 order check.
- G3 (new) transmission bracketing: for every window on a real diode,
  exp(-2 int kappa) lies between the uniform-field transmissions at the
  path's max and min edge fields. This follows from the quadrature being
  exact for piecewise-linear psi -- a theorem, not a calibration.
- G4 FD Jacobian at 5e-5, every column, -2/-4/-6V (exists).
- G4b sparsity: entries only in rows {hole row of i, electron rows of
  the crossing edge's two nodes} and psi columns in the span or at the
  global psi extrema.
- G5 conservation (exists).
- G6 ramp 0 -> -6V converges in 0.5V AND 0.25V steps (the second
  failed earlier than the first before).
- G6b path independence: the 0.5V and 0.25V ramps give the same -6V
  state (tolerance from measurement, recorded).
- G7 (test_model_benchmarks.py) structural: every window's tunnel
  length x_f - x_i lies within [Eg/(q Fmax), Eg/(q Fmin)] over its own
  path, x_f != x_i (Esseni 2017: holes generated at x_i, electrons at
  x_f; x_f = eEg/|F| in a uniform field).

## 3. S2 — nonlocal (effective-field) impact ionization, Device1D

**Model.** The M15 generation G = Kgen*(alpha_n(E)*Sn + alpha_p(E)*Sp)
with the local node field replaced by a per-carrier EFFECTIVE field
obtained from the relaxation equation along the carrier's drift
direction s:

    lambda_c * dE_eff,c/ds + E_eff,c = |E|

This is the drift-dominated form of the simplified energy balance of
Slotboom, Streutker, van Dort, Woerlee, Pruijmboom, Gravesteijn,
"Non-local impact ionization in silicon devices", IEDM 1991 (IEEE
Xplore 235484). Its abstract, the only part of the paper accessible
this session, states the key claims: the simplified energy balance with
an energy relaxation length gives the carrier temperature for a given
field distribution; lambda_e = 650 A was extracted from MBE bipolar and
submicron MOS devices; and electrons gain much less energy than the
maximum field implies when the field peak is narrow. The exact
equation in the paper's body was NOT read. Mapping temperature back to
field through the uniform-field relation cancels the energy-balance
constant (2q/5k), so E_eff depends on lambda alone and reduces EXACTLY
to |E| in a uniform field. Stated as such in the code.

- lambda_n = 6.5e-6 cm (650 A, Slotboom 1991). lambda_p = lambda_n is
  a NAMED simplification (no accessible hole value), the same pattern
  hydrodynamic.py's TAU_W_P already uses.
- Drift direction: electrons toward higher psi, holes toward lower,
  decided per edge from the live psi difference. Inflow boundaries are
  cold (E_eff = 0). Where an edge's direction flips (a psi extremum)
  the recursion's structure changes. That is a documented kink,
  irrelevant in a reverse-biased junction, where psi is monotonic.
- Discretization: exact exponential integrator per edge,
  E_eff(k+1) = a_k*E_eff(k) + (1 - a_k)*|E_k|, a_k = exp(-h_k/lambda),
  processed in psi order. With several inflows, E_eff is their mean.
- Jacobian: E_eff = W |E_edge| with W built alongside the recursion
  (weights below 1e-18 of the row pruned); dG/dpsi gains a dense block
  through W and d|E|/dpsi. The |J| terms keep M15's tridiagonal form.
- Flags: `Models(impact_nonlocal=True)` (requires `impact=True`),
  `impact_lambda_n`, `impact_lambda_p` [cm]. Device2D/3D keep refusing
  `impact` and so refuse this too.

Gates:
- test_model_benchmarks.py, FIRST: lambda_e pinned to 650 A;
  step-field response E_eff = E0(1 - exp(-x/lambda)) to rounding on a
  graded mesh; a pulse of width w peaks at E0(1 - exp(-w/lambda));
  uniform field gives E_eff = E exactly.
- off bit-identity (impact_nonlocal=False, impact=True == M15 as-is).
- FD Jacobian at 5e-5, every column, at a bias with real multiplication.
- lambda -> 0 recovers the local model within the upwind/centered field
  difference (measured, recorded).
- Slotboom's published claim as a direction gate: at an abrupt p+n+
  junction (narrow field peak) the nonlocal II generation is BELOW the
  local model's; in a long p-i-n (field plateau >> lambda) the two
  agree in the plateau interior.
- convergence of a reverse ramp with impact_nonlocal=True.

## 4. S3 — nonlocal BTBT in structured Device2D and Device3D

Esseni 2017 section 2.4: commercial TCAD's "dynamic path" takes the
tunneling direction at each point from the gradient of the valence-band
energy -- a path along field lines. Design:

- One path engine (`pytcad/nonlocal_path.py`) shared by 1D/2D/3D: a
  path is a list of samples, each with an interpolation stencil (node
  indices + weights) and arc-length coordinates. psi at a sample is
  linear in nodal psi, so S1's exact per-segment quadrature, live
  prefactor, interpolated deposit and Jacobian carry over unchanged. 1D
  is the special case where samples are nodes with unit weights. S1's
  Device1D code is refactored onto it, with 1D results required to be
  unchanged.
- Tracing (frozen per solve_bias call, refreshed as in S1): from each
  candidate start node (field above the screen, band can reach Ec),
  step along +grad(psi) (bilinear/trilinear interpolation of the
  cell-wise gradient) with ds = 0.5*min(h) until delta >= 1.5, the
  domain boundary, or a length cap. Sample points and stencils are
  stored.
- Deposit: holes at the start node (its dual volume), electrons at the
  delta = 1 crossing spread over that sample's stencil weights x the
  crossing's segment interpolation -- count-conserving.
- Device2D (structured only; unstructured=True refuses) and Device3D
  get `Models(btbt_nonlocal=True)`, a homojunction guard, the residual/
  Jacobian block after both continuity assignments and before the
  Dirichlet stamping, and the same per-call window reset + refresh.

Gates: off bit-identity (2D and 3D goldens untouched); FD Jacobian at
5e-5 on every psi column of a small 2D and 3D diode; conservation;
**dimensional reduction**: a 2D/3D device uniform in y (and z)
reproduces the 1D result per unit area (the repo's standing
3D -> 2D -> 1D reduction discipline); tracing: on a uniform-field 2D
device paths are straight lines along the field; convergence of a
reverse ramp in 2D.

## 5. S4 — compiled path tracer (M31 P4 pattern)

`_trace_paths_py` (the oracle) and `_core.trace_paths` (C++, nanobind,
`core/src/nonlocal/paths.cpp`), dispatched through `_accel.use_accel()`.
Tracing is pure arithmetic plus sqrt (correctly rounded in both
libraries) and floor, so the parity gate is `np.array_equal` on sample
coordinates, stencils and weights, following test_accel_parity.py. No
transcendental crosses the boundary. A benchmark entry goes in
`benchmarks/`. No speed claim is made anywhere without its table (M32
rule).

## 6. S5 — exposure and documentation

- `workbench/core/catalog.py`: ModelInfo entries for `btbt_nonlocal`
  and `impact_nonlocal`, with citations and the stated scope.
- `gui/services/device_spec.py` models dict, Physics Lab toggles, and
  persistence (SCHEMA_VERSION bump only if the models key set requires
  it -- check project_store's own rule first).
- ARCHITECTURE.md: M34 entry, 4d.1 matrix (nonlocal BTBT 1D/2D/3D; and
  the correction of the local II/BTBT rows to 1D-only), history.md,
  CLAUDE.md milestone state (CRLF file: binary-safe edit).

## 7. Order and stopping rule

S1 -> S2 -> S3 -> S4 -> S5, each: red tests first, implement, FD and
adversarial probes, fast suite both ways (`PYTCAD_ACCEL=0/1`). The slow
battery runs before the completion claim. If a slice hits a blocker
that needs a model decision (as G6 did), it is recorded here and in
history.md with its evidence, and the next slice proceeds only if it
does not depend on it.
