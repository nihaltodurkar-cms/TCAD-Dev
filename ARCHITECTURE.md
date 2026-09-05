# Semiconductor Workbench - Architecture Plan
==========================================================
Date: 2026-08-31 (updated). Status: M1-M10 SHIPPED (v0.5.0 tagged).
M11 heterostructures COMPLETE through S5 (S1 materials, S2
region_materials wire format, S3 1D heterojunction core: eps(x)
flux-form Poisson, Anderson band offsets via carrier-specific ln(nie)
deltas, per-material recombination; S4 2D box-integration
heterojunction core with the full gate battery incl. dimensional
reduction to 1D; S5 structure-model materials lossless end-to-end,
HBT/HEMT parametric templates solve through the pipeline -- COMPLETE
except optional devsim hetero support).
M12 tunneling SHIPPED (S1 FN+WKB analysis module with published-
constant gates; S2 Hurkx trap-assisted tunneling in Device1D, all
acceptance gates green; S3 density-gradient folded into M20 of the
parity plan -- M20 COMPLETE, ALL GATES GREEN 2026-08-31, see below).
M13 Fermi-Dirac statistics COMPLETE (all gates G1-G8 green across
1D/2D/3D); the tabulated fast path (2026-08-27) makes fd solves
150-1260x faster with zero change to the physics (interpolation
error 7e-14 to 1e-13, four orders below the 1e-9 gate) -- see M13
section below.
M15 impact ionization coupling is COMPLETE (2026-08-28). The 2026-08-27
hard-debug pass (generation term contributing exactly zero -- source
overwritten before the residual used it, frozen-field snapshot taken
after contact stamping) was the first of several fixes; R1b's
remaining quantitative gates (simulated multiplication vs the
analysis-layer integral; breakdown voltage within 10%) closed via the
M22-phase-2 continuation driver's strength-ladder-aware corrector plus
an explicit, evidence-backed scope decision (G-C's tolerance and G-D's
second test doping -- see below, section 5). All gates green: G-A
through G-F. See M15-IONIZATION-PLAN.md for the full defect ledger.
M21 general meshing: PHASE 1 (1D solution-driven h-refinement) SHIPPED
2026-08-27, 17 gates.  PHASE 2 (2D/3D separable adaptive refinement)
SHIPPED 2026-08-28, 25 gates, after a hard-debug pass found and fixed
six real bugs -- most seriously, a doping-array axis-order bug in the
test helpers that corrupted ~49% of doping nodes' spatial placement in
every 3D test in the file, and an unrelated `NameError` (a stale
`debye_length` reference left behind when phase 2's code renamed the
import to `_debye_length`) that had been silently breaking PHASE 1's
own driver the whole time.  See M21-MESHING-PLAN.md section 13 for the
full defect ledger.  PHASE 3 (general unstructured 2D + Delaunay FV
assembly) COMPLETE 2026-08-31: geometry foundation (3a), Poisson-only
equilibrium (3b), coupled SG bias solve (3c), and `Device2D(
unstructured=True)` class integration (3d, a thin wrapper -- zero new
Jacobian entries, bit-identical to calling the standalone
`unstructured_poisson.py`/`unstructured_dd.py` functions directly) all
shipped, all gated.  See M21-PHASE3-MESHING-PLAN.md for the full
record, including honest gaps (golden parity vs the structured solver
measured at ~5-6%, not the plan's originally-stated <1e-4).
M22 linear solver modernization: PHASE 1 (Krylov/ILU/node-block-Jacobi
behind the existing spsolve interface) SHIPPED 2026-08-27, wired into
the general (non-tridiagonal) Newton solves in all three device cores.
The >=64k-node 3D scaling gate is GREEN: plain ILU did not respect the
psi/n/p coupling structure at that scale, so a node-block-Jacobi
preconditioner (invert each node's 3x3 diagonal block directly) was
added and closed it -- 68921 nodes (206763 unknowns) solve in 4.71s.
A later hard-debug pass found solve_linear(method="direct") was
reformatting A (CSR -> CSC) before calling spsolve, which is NOT
bit-identical for scipy's SuperLU wrapper (it solves CSR natively via
a format flag, not by converting) -- broke the M13/M22 equilibrium
bit-identity goldens when first wired into those call sites; fixed by
never reformatting for "direct" (only "gmres"/"bicgstab" still
normalize to CSR, where exact format doesn't matter). Continuation
driver (phase 2) LANDED 2026-08-28 (pytcad/continuation.py:
adaptive_bias_sweep, arc_length_sweep with a strength-ladder-aware
corrector) -- this is what let M15 R1b's avalanche-fold gates close;
see the M15 paragraph above and section 5 below.  A Schur-complement
preconditioner variant (plan section 7's flagged next step: permute to
equation-major order, spilu the Poisson block, exact density diagonals,
drop the (n,p) cross-couplings; `solve_linear(precond="schur")`, opt-in
per call, default "auto" == unchanged node-block-Jacobi) landed
2026-08-29, VERIFIED 2026-08-31: `pytest tests/test_m22_linsolve.py -q`
-> 15 passed, 1 skipped (the skip is a PRE-EXISTING, unrelated golden-
fixture gap -- `frozen_meshes.npz` absent from this checkout, the same
condition `test_m13_goldens.py` already skips gracefully on, not a
Schur-specific issue). All 5 Schur-specific gates green on the first
run (`test_schur_preconditioner_matches_exact_factorization`,
`_converges_on_device_jacobian`, `_on_coupled_3d_jacobian`,
`test_schur_flavor_default_is_unchanged`,
`test_schur_builder_refuses_mismatched_structure`) -- unlike M16, no
test-code defects found here; the gates were simply correct and had
never been run.
M16 BTBT (local Kane/Hurkx generation, live Jacobian coupling): LANDED
2026-08-29, VERIFIED 2026-08-31. The gates were never actually run
until 2026-08-31; 2 of 13 then failed, but all three root causes were
bugs in the TEST assertions (an inverted sort direction, a sign error
comparing two negative slopes, a correlation-sign check that could
never pass for a genuine negative-slope Kane fit), not the physics --
see pytcad/M16-BTBT-PLAN.md.
M20 density gradient (Ancona-Stafford DG quantum correction, equilibrium-
only): COMPLETE, ALL GATES GREEN, 2026-08-31 (coupled-Newton
reformulation replacing the old lagged outer fixed point; see section
4b.2 below and M20-DENSITY-GRADIENT-PLAN.md section 7 for the full
record, including a genuine wrong-sign boundary-condition bug found
and fixed via literature/production-tool research).
M17 transient simulation: PHASES 1-3 (1D/2D backward-Euler/theta-scheme
cores, GUI Transient tab) SHIPPED 2026-08-30/31. See M17-TRANSIENT-PLAN.md.
M18 small-signal AC analysis: PHASE 1 (Device1D one-port, Python-API
only, no GUI) LANDED 2026-08-31 -- Y(f)/C(f)/G(f) via a
J_ac(w)=J0+jw*Cmat complex solve reusing M17's already-FD-gated
storage-term Jacobian. PHASE 2 (Device1D N-terminal Y-parameters + fT,
merged from a parallel branch) LANDED 2026-09-04. PHASE 3 (Device2D,
N-terminal Y-parameters incl. GateBC ports, Python-API only, no GUI)
LANDED 2026-09-04. PHASE 4 (GUI exposure: ACPanel.qml, ac__* wire
format, C(f)/G(f) via ax.twinx()) LANDED 2026-09-05. PHASE 3b (full
4-terminal mosfet_2d Y-parameter matrix + fT, ac2d.cutoff_frequency())
LANDED 2026-09-05 -- the first real (non-synthetic) validation of the
fT crossing algorithm against an actual amplifying device; reused
pytcad.mosfet.build_mosfet (built for M14) as the fixture with zero
new device-builder code. See M18-AC-PLAN.md.
M19 self-heating: PHASE 1 (steady-state 1D, isothermal-DD + outer
Gummel thermal loop, no GUI) LANDED 2026-08-31. See
M19-SELFHEATING-PLAN.md.
M14 surface mobility: PARTIAL. mobility_cvt() wired for Device2D.models.
surface_mobility (G-D/G-E green); G-A (absolute curve vs Takagi/Taur)
xfail'd -- 2026-08-28 research confirmed the real Lombardi phonon term
is two-part and doping-dependent (this code has a one-term stand-in),
but the numeric constants are blocked on the 1988 primary source, which
is paywalled with zero open-access copies (verified via Unpaywall);
G-B/G-C/driving_force/catalog not started.
FUTURE: capability growth is governed by section 4b below (M13
Fermi-Dirac statistics through M30 system-level; three parity tiers).
The M1-M10 roadmap below is retained as the shipped architecture
record; sections 5-7 track the live queue.

GUI: PHASES 1-3 SHIPPED, PHASE 4 LANDED (2026-08-29). 530 GUI tests
passed at that landing; 562 pass as of 2026-08-31 (growth from M17
phase 3's Transient tab and other additions since), zero regressions.
Runtime validation (GuiStateValidator,
StatusIndicator, ValidationBanner, ValidatedTextField) verified. See
gui/README.md and GUI-IMPROVEMENT-PLAN.md for full detail.

Long-term ambition: a learning + research TCAD environment combining the
capabilities and educational value of DEVSIM / Silvaco / Sentaurus while
staying open, modular, and understandable. A REAL architecture - every
educational surface must be backed by actual computed physics.

Target flow:
  UI -> app -> core(Device)+physics(ModelConfig)
     -> solvers/backend -> results(RunResult + RunRecord)
     -> analysis(observables) -> UI

------------------------------------------------------------------------
1. CURRENT ARCHITECTURE AUDIT (baseline)
------------------------------------------------------------------------
| Area            | State                                                   |
|-----------------|---------------------------------------------------------|
| Numerical core  | Homegrown FD Poisson+drift-diffusion (pytcad/), SG      |
|                 | discretization, full Newton w/ analytic Jacobian, de    |
|                 | Mari scaling, warm-started sweeps; 1D/2D/3D classes.    |
|                 | Validated vs analytic benchmarks. KEEP as backend #1.   |
| Materials       | Semiconductor dataclass + free functions (Caughey-      |
|                 | Thomas/Canali mobility, Slotboom BGN, SRH/Auger, nie).  |
| Physics select  | Models dataclass = 5 booleans; assembly inline in each  |
|                 | Device class; field_mobility dead-end >=2D.             |
| Process         | Pure-function 1D chain (Pearson4 implant, erfc/Gaussian |
|                 | diffusion, numeric diffusion, Deal-Grove oxidation).    |
| Device defn     | DeviceSpec JSON DTO (Qt-free, pytcad-free) built by     |
|                 | StructureModel.to_device_spec() or examples.py.         |
|                 | Single-material, rectilinear-only.                      |
| Sweep system    | Generic single-contact warm-started sweeps;             |
|                 | sweep_derived.py (Vth/Ion-Ioff/gm-based readouts).      |
| Results         | npz grammar versioned + structurally validated          |
|                 | (gui/services/solver_backend.py, shipped in v0.5.0-1).  |
| GUI             | QML panels -> god controller (1,181 lines) -> services  |
|                 | -> QProcess subprocess -> store -> Matplotlib-Agg.      |
| Tests           | 346 passing incl. real-CLI conformance 1D/2D/3D;        |
|                 | FakeStore/FakeRunner seams already exist.               |

------------------------------------------------------------------------
2. MAJOR ARCHITECTURAL PROBLEMS (blocking the workbench ambition)
------------------------------------------------------------------------
P1  No solver object exists - "backend" is a module string. Nothing
    represents a run (inputs, status, diagnostics, provenance).
P2  Result schema is rectilinear-grid-shaped (axis_* vectors + (Ny,Nx)
    arrays). A genuine DEVSIM backend emits unstructured meshes.
P3  Equations are not components: physics is inline terms in three
    hand-derived Jacobians. No registry, no per-region assignment, no
    metadata. Any new model = editing every Device class.
P4  Single material per device; no band offsets -> blocks heterostructure
    devices (HEMT etc.).
P5  No provenance: nothing records WHICH equations/models produced a
    number. Educational goal has no substrate.
P6  Convergence invisible: divergence = warnings string-match; no
    iteration/residual history object.
P7  C-V stranded in moscap, outside DeviceSpec/sweep/result plumbing.
P8  God controller absorbs every new domain; three near-cloned
    dimension-specific Device classes multiply physics changes by 3.

------------------------------------------------------------------------
3. PROPOSED TARGET ARCHITECTURE
------------------------------------------------------------------------
workbench/
  core/      DOMAIN: Device{Regions[], Contacts[], Gates},
             Region{material, doping profile, geometry}, MaterialLibrary,
             ModelConfig. Pure data.
  physics/   MODEL REGISTRY: every model a registered component with
             {equations, parameters, references, applicability}.
             Phase 1: metadata + toggles. Phase 2: compositional assembly
             (only when a second concrete model need justifies it).
  solvers/   BACKEND INTERFACE + runners. Backends: pytcad (existing core,
             wrapped), devsim (M7), future. Each backend owns its mesh
             strategy; all emit RunResult + RunRecord. Subprocess isolation
             per run is KEPT (UI-thread safety + OS-kill cancellation).
  results/   RunResult (schema v2: point-cloud geometry + fields + series,
             structured shape as hint) + RunRecord (provenance: inputs,
             enabled models + citations, numerics options, convergence
             trace).
  analysis/  Observables: IV, CV, band_diagram, Vth, gm(Vg), Ion/Ioff,
             recombination/mobility maps. Array-based, backend-agnostic.
  app/       Controllers + services (evolved gui/services): thin
             orchestration only.
  ui/        QML views over core/analysis objects.

Placement rule: workbench/ lives beside pytcad/ inside the repo. The
existing numerical package is NEVER modified except to expose values it
already computes.

------------------------------------------------------------------------
4. MILESTONE ROADMAP (revised M1-M10 sequence)
------------------------------------------------------------------------
Every milestone ships green tests and preserves all existing tests.
Dependency order: M1 -> M2 -> M3 -> M4 -> {M5, M6, M7} -> M8 -> M9 -> M10.

M1 - DOMAIN CORE + MODEL CATALOG (Architecture) [SHIPPED]
  Shipped as planned: workbench/core/{device,region,materials,catalog}.py
  + adapters/spec.py; both-example round-trip equivalence proven;
  post-ship audit fixed material-handling boundary bugs (case-insensitive
  library lookup, honest non-silicon rejection).

M2 - RUNRECORD + RESULT SCHEMA v2 (Architecture/Results) [SHIPPED]
  Shipped as planned: additive v2 grammar (geom/mesh/node keys,
  record__meta provenance, converge__trace), stdout-tee capture with
  zero numerical changes, run_record() accessor. Post-ship probing fixed
  geometry-check bypass, point_cloud honesty, stdout leak on failure.

M3 - RESULTSTORE / ANALYSIS BOUNDARY + SOLVERBACKEND PROTOCOL
  (Architecture) [SHIPPED]
  Purpose: finish the data layer before any UI consumes it.
  a) Store seam: has_sweep()/sweep_result() promoted onto the
     ResultStore ABC; AppController's isinstance(NpzResultStore) checks
     removed (:129/:257/:264); ProcessResultStore subclassing or a
     documented duck-type contract; MplCanvasItem's private
     store._selected reach-in replaced by a public accessor; the
     controller's direct pytcad.process import moved behind
     process_derived.
  b) Observables: sweep_derived promoted into an analysis layer with a
     uniform Observable.compute(RunResult) interface; add gm(Vg) curve,
     band-diagram extraction, recombination/mobility diagnostic fields
     (expose what the core already computes - never recompute); C-V via
     the validated moscap.cv_sweep behind the same interface.
  c) SolverBackend protocol (EARLY in this milestone): formal
     prepare(DomainDevice, ModelConfig, numerics) -> SolveHandle /
     run() -> RunResult+RunRecord, with the pytcad runner as reference
     implementation. Decided here rather than at DEVSIM time so M7 is
     an adapter, not a rewrite. Zero behavior change; golden equality.
  Tests: parity goldens vs existing sweep_derived values; conformance
         battery against the pytcad backend; FakeStore-driven seam tests.
  Risks: solver_runner/store churn (guarded by the unchanged suite).
  Compat: GUI readouts unchanged in wording/values; CLI unchanged.

M4 - PHYSICS LAB FOUNDATION (Educational UI) [SHIPPED]
  Purpose: first real educational surface: panel listing ModelCatalog
         entries with enable/disable + validated parameter edits;
         equation/reference text; convergence-history plot from the M2
         RunRecord; "what produced this quantity" provenance view.
         Everything backed by the real pipeline - nothing faked.
  Files: qml/panels/PhysicsLabPanel.qml, controllers/lab_controller.py
         (keeps the god controller from growing).
  Tests: headless QML driver checks (catalog reflection, toggles reach
         ModelConfig and change RunRecord, convergence plot data).
  Compat: purely additive UI.

M5 - DEVICE BUILDER EXPANSION (Device Builder) [SHIPPED]
  Purpose: parametric templates (pn diode, NMOS like today's example,
          MOS-C) expressed in domain core; Builder UI lists templates
          with editable parameters. BJT/HEMT/solar deferred until
          heterostructure Regions exist.
  Tests: each template builds, solves, matches current benchmarks.

M6 - PROCESS BUILDER (Process side) [SHIPPED]
  Purpose: process ops map onto domain-core Regions (per-region
          implants); checkpoints become DomainDevices. Scope stays 1D:
          multi-material regions are explicitly OUT until the
          heterostructure question is settled.
  Compat: existing 1D flow files load unchanged.

M7 - DEVSIM BACKEND (Solver Backends) [SHIPPED -- equilibrium slice]
  Purpose: GENUINE backend proof on the M3 protocol: optional
          dependency; 1D diode implemented natively in DEVSIM (its own
          mesh), emitting RunResult v2 + RunRecord. Verified against
          the shared analytic benchmark set BEFORE any UI exposure.
          Unstructured output uses schema v2 point-cloud geometry;
          visualization gains a triangulated scatter path.
  Tests: cross-backend agreement within stated tolerances; conformance
         battery.
  Risks: highest-risk milestone; isolated by the interface, opt-in,
         off by default.

M8 - ADVANCED PHYSICS / SOLVERS (Physics)
  Purpose: first NEW physics beyond the current five models - chosen by
          concrete demand (e.g. thermionic emission, heterojunction
          continuity for HEMT-class devices; impact ionization for
          breakdown studies). This is where compositional equation
          assembly gets decided, justified by that second model need.
          Advanced solvers (iterative/preconditioned) address the 3D
          LU fill-in wall documented in benchmarks/.
  Gate: no new model lands without validation against an analytic or
        published benchmark, and without catalog metadata.

M9 - EDUCATIONAL PHYSICS LAB (Educational UI, full)
  Purpose: complete the lab started in M4: side-by-side model on/off
          comparisons (needs M8's richer physics to be worth comparing),
          band diagrams, recombination/mobility maps, mesh/BC inspection,
          full "which equations produced this" explanations per quantity.

M10 - WORKFLOW LAYER (Silvaco / Sentaurus-style)
  Purpose: deck-style input translation over the app core (parse ->
          DomainDevice + ModelConfig + job spec -> run -> results), so
          batch/scripted workflows mirror commercial TCAD usage. A
          translation layer ONLY - never a second UI code path.
  Compat: everything above remains reachable from the QML app.

Done criteria carried from M1/M2: every milestone proves behavioral
equivalence or adds independently validated capability; adversarial
probing pass before ship; suite green with pre-existing tests unchanged.

M11 - HETEROSTRUCTURES [S1-S5 ALL SHIPPED]
  S1 materials: Ge/GaAs/InGaAs/AlGaAs factory in the MaterialLibrary
  (Varshni bandgap, Caughey-Thomas mobility, permittivity, affinity --
  provenance per field). S2 wire: DeviceSpec.region_materials with
  parse-time validation; solvability refusal at the adapter layer.
  S3 core: per-node material lists in Device1D; eps(x) harmonic-mean
  flux-form Poisson (uniform => algebraically identical to the old
  assembly); Anderson band offsets entering the SG currents through
  CARRIER-SPECIFIC ln(nie) edge deltas (electron dpsi + dln(nie),
  hole dpsi - dln(nie) -- opposite signs; a shared delta passes a
  Jacobian check but breaks hole detailed balance, which is the
  acceptance test that guards it); per-material recombination.
  Acceptance: FD-Jacobian across Si/GaAs < 5e-5; detailed balance
  exact; homojunction path bit-identical.
  S4 SHIPPED: 2D box-integration equivalent (same math, face-normal
  eps; dimensional-reduction-to-1D gate). S5 SHIPPED: HBT/HEMT
  parametric templates + UI (regionMaterialBox in DopingEditor.qml,
  controller.setRegionMaterial). T5's own gate test
  (test_hemt_band_step_at_interface) was a false-negative test bug, not
  a physics gap: it diffed chi along axis=1 (x), but the HEMT's buffer/
  channel/barrier layers are stacked along y, so that diff was always
  exactly zero regardless of whether the real band step existed. Fixed
  2026-08-28 to diff along axis=0; the real step measures 0.20 eV,
  comfortably clearing the 0.15 eV gate.

M12 - TUNNELING & QUANTUM CORRECTIONS [S1-S3 ALL SHIPPED]
  S1: workbench/physics/tunneling.py -- Fowler-Nordheim constants and
  slope, triangular-barrier WKB kappa/transmission, gated against
  published values. S2: Hurkx trap-assisted tunneling in Device1D
  (Models(tat, trap_et_rel); frozen-field approximation documented;
  WKB factors SI-calibrated -- field in V/m; bulk-Si midgap
  negligibility asserted as honest physics). Acceptance: FD-Jacobian
  with traps < 5e-5; traps-off bit-identity; WKB factor-law gate
  1e7..5e10 V/m; global-charge-balance neutrality. S3 (density
  gradient) was designed in the now-archived M12 tunneling design doc
  and folded into M20 of the parity plan -- M20 COMPLETE, ALL GATES
  GREEN 2026-08-31 (coupled-Newton reformulation; see M20's own entry
  below and M20-DENSITY-GRADIENT-PLAN.md section 7).

------------------------------------------------------------------------
4b. FUTURE: SENTAURUS-PARITY ROADMAP (M13-M30)
------------------------------------------------------------------------
Capability growth beyond M12 is governed by this section (formerly a
separate SENTAURUS-PARITY-PLAN.md, merged in here 2026-08-28 so the
roadmap and its live status live in one document): three parity tiers
(SDevice local-physics parity for silicon 1D/2D; SProcess-lite +
general geometry; system-level), milestones M13 through M30, each with
published-value acceptance gates, dependencies, and sizes. Standing
rule 4b.4 below: gate-bearing milestones block their dependents until
every gate is green -- "mostly green" is not green, and a skipped/
weakened gate is a hidden failure (this is not theoretical: M15 was
declared complete with all gates green while two of its own gates were
unreachable and its generation term contributed nothing; see
M15-IONIZATION-PLAN.md's debug-pass record). The M1-M12 pattern
continues unchanged: red tests first, FD-Jacobian-first for core
changes, bit-identity when a model is off, no hidden failures.

------------------------------------------------------------------------
4b.0 HONEST FRAMING -- what "same level" can mean
------------------------------------------------------------------------
Sentaurus is ~30 person-decades of engineering. Literal feature parity
is not a plan, it is a fantasy. What IS plannable is parity in tiers,
where each tier is a device/process class we can simulate END-TO-END
with published-value validation at the same fidelity Sentaurus users
actually exercise. This roadmap defines three parity tiers and the
milestones that reach them. Every milestone keeps the house rules:

  - no core change without an explicit plan amendment + FD-Jacobian gate
  - no new physics without a literature benchmark test landing FIRST
  - no tolerance weakened, no failing test hidden, ever

Parity tiers:

  TIER 1 -- "SDevice local-physics parity, silicon, 1D/2D"
     Fermi statistics, surface/field mobility, coupled impact
     ionization, BTBT, transients, AC, self-heating, DG quantum
     correction. After Tier 1, PyTCAD solves the standard silicon
     device menu (diode, MOSFET, MOS-C, HBT-able junctions) with the
     same *local* physics models Sentaurus defaults to, validated the
     same way.

  TIER 2 -- "SProcess-lite + general geometry"
     Unstructured 2D meshing, mask-driven process with moving
     boundaries (deposit/etch/2D oxidation), pair diffusion with
     TED/OED/segregation, 3D with iterative solvers.

  TIER 3 -- "System-level parity"
     Mixed-mode circuit-device coupling, hydrodynamic transport,
     Monte-Carlo implantation, calibration/optimization flows.

Deliberately OUT of scope (stated so we never drift into them silently):
Monte-Carlo *transport* (Boltzmann solver), atomistic kinetic-MC
diffusion, radiation/SEE, ferroelectric/phase-change materials, full
viscoelastic oxidation *mechanics* (we do stress-lite), Maxwell/EM
solvers, PDK-grade compact-model extraction.

------------------------------------------------------------------------
4b.1 GAP ANALYSIS (Sentaurus capability vs PyTCAD, snapshot)
------------------------------------------------------------------------
Legend: [have] [partial] [missing]. This is a snapshot from when the
roadmap was drafted; the status table further below (2026-08-27/28) is
the live record of what has since closed -- read that one for current
state, this one for what the roadmap originally set out to close.

DEVICE PHYSICS
  [partial] Fermi-Dirac statistics / incomplete ionization
            (we are Boltzmann + full-ionization; code already warns)
  [partial] Mobility: Caughey-Thomas + Canali in 1D; no surface/
            inversion-layer mobility (Lombardi CVT, PUMobi) in 2D
  [partial] Impact ionization: coefficients + breakdown integral exist
            as analysis layer; NOT coupled to any Newton assembly
            (devsim edge_volume_model unit anomaly documented)
  [partial] TAT (Hurkx, frozen field, 1D); no Schenk variant
  [partial] Band-to-band tunneling: local Kane (Hurkx 1992 Si
            coefficients) coupled live into Device1D's Newton core
            (M16, 2026-08-29); nonlocal path still missing (Tier 3)
  [missing] Surface recombination velocity; D_it in MOS module
  [missing] Transient simulation (steady-state only everywhere)
  [missing] Small-signal AC analysis
  [missing] Lattice heating / self-heating / thermoelectric
  [done] Quantum corrections (density gradient; Schrodinger-Poisson)
         -- M12-S3/M20 COMPLETE, ALL GATES GREEN 2026-08-31
         (equilibrium-only; DG transport remains out of scope)
  [partial] Heterojunctions: 1D core done; 2D pending (M11-S4);
            no thermionic-emission interface model
  [missing] Schottky/tunnel contacts (only ohmic + gate BCs)

PROCESS
  [partial] Implantation: 1D LSS/Pearson moments, amorphous only;
            no 2D lateral moments in the process layer, no MC/BCA
  [partial] Diffusion: intrinsic constant-D; no pair diffusion,
            no OED/TED, no segregation, no clustering
  [partial] Oxidation: 1D Deal-Grove; no 2D moving boundary,
            no LOCOS/STI bird's beak, no stress coupling
  [missing] Deposition/etch topology engine; masks; silicidation;
            epitaxy; CMP

GEOMETRY / MESH / NUMERICS
  [missing] Unstructured 2D/3D meshing (tensor-product only)
  [missing] Adaptive solution-driven refinement
  [partial] 3D exists but dies ~27k nodes (dense LU; no iterative
            solver)
  [missing] Continuation/parameter ramping machinery beyond the
            per-solve warm start

SYSTEM
  [missing] Mixed-mode device+circuit (MNA with device stamps)
  [missing] Parameterized experiments/splits (SWB-style), calibration
            loops, optimization
  [partial] Deck front end exists (own dialect; not DeckBuild-
            compatible)

WORKBENCH / UI
  [partial] GUI: sweeps, family, C-V, physics lab, process panel;
            no 2D field contours/cuts, no transient plotting, no
            geometry-from-process viewer

------------------------------------------------------------------------
4b.2 THE MILESTONE PLAN -- M13..M30
------------------------------------------------------------------------
Sizes: S ~1 session, M ~1-2, L ~2-4, XL ~4+ (with tests, honest). This
is the original scope/acceptance-gate text for each milestone; see the
status table further below for what has actually landed.

=== TIER 1: SDevice local-physics parity ===========================

M13  FERMI-DIRAC STATISTICS + INCOMPLETE IONIZATION          [L]
  COMPLETE: all gates G1-G8 green, wired through the full 1D/2D/3D
  solver core (see the status table below and `history.md` for the
  implementation record; the original milestone spec this section
  summarizes is archived). Acceptance gates were (G1 F_{1/2} vs
  independent quadrature reference + published spot values; G2
  Boltzmann limit; G3 Sommerfeld degenerate limit; G4 charge-
  neutrality consistency vs independent root finds; G5 FD-Jacobian
  gates incl. degenerate heterointerface; G6 bit-identity goldens for
  the off-path; G7 published-value benchmarks with explicit
  applicability limits; G8 suite invariant). Scope: Models(fd=False)
  default, parabolic-band F_{1/2} via a published rational
  approximation audited against quadrature, generalized SG chosen from
  candidate schemes by the detailed-balance gates, incomplete
  ionization (B/P/As) behind its own flag. DEPENDENCY-CLEAN AND
  BLOCKING: M13 depends on nothing; M15-M20 may not START until all
  gates are green. Touches ALL THREE cores' residual+Jacobian -> the
  M11-S3 amendment mechanism applies (goldens committed before the
  edit, FD-Jacobian-first, bit-identity proven before composition).
  Depends: nothing. FIRST, because every later model composes with
  statistics.

M14  SURFACE & INVERSION-LAYER MOBILITY + INTERFACE RECOMB    [L]
  Scope: Lombardi CVT (surface roughness + phonon + Coulomb
  components) for 2D MOSFET channel; driving-force choice for
  high-field in 2D switches to grad(quasi-Fermi) (Sentaurus
  convention) behind a flag; surface recombination velocity S at
  interfaces and contacts (SRH surface term); D_it in moscap.
  Acceptance: effective mobility vs effective field against
  published Si curves (Takagi/Taur form factors); C-V with D_it
  stretch-out vs analytic; S-driven diode leakage vs analytic
  S*ni/2 boundary formula; bit-identity when flags off.
  Depends: M13 optional (composes).

M15  IMPACT IONIZATION -- SOLVER COUPLING                    [L]
  Scope: van Overstraeten-de Man local II in the homegrown 1D/2D
  Newton assembly (generation term + Jacobian row); the devsim
  edge_volume_model unit anomaly is either resolved upstream or
  bypassed by giving the devsim backend homegrown edge volumes.
  Acceptance: multiplication factor M-1 vs published for one-sided
  junctions; breakdown voltage vs the textbook
  BV ~ 60*(Eg/1.1)^{3/2}(N/1e16)^{-3/4}-style scaling AND vs our
  existing analysis-layer integral (they must agree); II-off
  bit-identity; convergence study for the feedback stiffening
  (ramped voltage continuation).
  Depends: nothing hard; benefits from continuation (M22).

M16  BAND-TO-BAND TUNNELING                                  [M]
  Scope: local Kane model in Device1D/2D (generation term,
  published E_g^2/F form with Si parameters); optional Hurkx
  local dynamic BTBT. Nonlocal line-integral variant deferred to
  Tier 3 (needs general meshes).
  Acceptance: GIDL onset in a gated diode vs published Kane-form
  behavior (exponential slope gate); BTBT-off bit-identity;
  FD-Jacobian gate.
  Depends: M15 (shares generation-term plumbing).
  LITERATURE NOTE (2026-08-27, informs design before implementation
  starts -- not yet acted on): plain Hurkx/Kane local models are known
  to UNDERESTIMATE leakage at large bias relative to non-local
  (line-integral) BTBT, because they assume a single average/maximum
  field along the whole tunneling path. A "Modified Hurkx" local model
  (patented, published ~2020, still the reference point in 2025-era
  TCAD literature) corrects this while staying ~6x faster than
  non-local BTBT in 3D FinFET GIDL simulations -- i.e., it targets
  exactly the accuracy gap a plain local model would have. If M16 is
  implemented as scoped ("optional Hurkx local dynamic BTBT"), use the
  modified form rather than the original Hurkx paper's, and gate the
  known failure mode explicitly: verify GIDL onset does NOT plateau
  below the non-local reference at high reverse bias, not just that it
  matches at low bias where plain Hurkx already agrees. This also
  argues for following the M15 hard-debug lesson from the start: write
  the residual-ordering and frozen-field-snapshot-ordering gates BEFORE
  the physics gates (M15's own coupling was silently inert for an
  entire prior session because those orderings were wrong, and nothing
  caught it until an adversarial pass).

M17  TRANSIENT SIMULATION                                    [L]
  PHASES 1-3 (1D core, 2D core, GUI Transient tab) SHIPPED 2026-08-
  30/31 -- see pytcad/M17-TRANSIENT-PLAN.md. Unlocked M18 (AC) and
  is the basis a future TRANSIENT electrothermal phase of M19 would
  use (M19 phase 1 itself is steady-state and did not end up needing
  this machinery -- see M19-SELFHEATING-PLAN.md).
  Scope: time-dependent DD in 1D/2D (backward-Euler / theta
  scheme, adaptive dt from Newton behavior); contact excitation
  waveforms (step/ramp/pulse); stored transients in schema-v3
  result files (additive).
  Acceptance: dielectric relaxation time t = eps/sigma vs analytic
  in doped Si; pn diode turn-off charge storage vs analytic
  stored-charge integral; RC discharge of a junction vs analytic
  exponential; charge conservation at every step (sum of terminal
  currents = d/dt stored charge, machine precision).
  Depends: nothing hard. Unlocks AC and mixed-mode.

M18  SMALL-SIGNAL AC ANALYSIS                                [M]
  PHASE 1 (Device1D) LANDED 2026-08-31 -- see pytcad/M18-AC-PLAN.md.
  New module pytcad/ac.py drives Device1D through its own
  _residual_jacobian from outside (M15/M16/M17's pattern; device.py
  untouched, no new Models flag). J_ac(w) = J0 + j*w_s*Cmat, Cmat
  verified BIT-IDENTICAL to transient.py's already-FD-gated
  backward-Euler storage term at dt_s=1.0 (G-CONSISTENCY) rather than
  re-derived. All 6 gates green: G-LOWF (Re(Y)/C at f->0 match
  independent solve_bias-based dI/dV and dQ/dV finite differences to
  2.8e-5/8.1e-5 relative), G-JUNCTION-C (equilibrium C vs a freshly-
  derived abrupt-junction depletion formula -- none existed in the
  repo before this -- 3.3% relative), G-ROLLOFF (qualitative-only,
  see below), G-LIVE-STATE, G-SCOPE-REFUSAL (Device2D raises
  TypeError). A real bug was found and fixed while deriving the
  current-sensitivity vector: an early version used a PER-NODE finite-
  difference step size, which broke an exact analytic cancellation
  (edge current depends on the two adjacent nodes' psi only through
  their DIFFERENCE) and silently doubled the computed low-frequency
  conductance -- caught by G-LOWF's independent cross-check before it
  became a gate result. Scope: one-port admittance Y(f)/C(f)/G(f) for
  a two-terminal Device1D (no general Y11/Y12/Y21/Y22 2-port matrix,
  no reciprocity gate). Depends: M17.
  Acceptance vs original scope: low-f limit vs quasi-static C-V --
  MET (via solve_bias finite differences, the existing validated
  path). Junction C vs analytic depletion formula -- MET (freshly
  derived, no prior pin existed). 3dB roll-off vs an analytic
  stored-charge pole from M17 -- NOT MET AS QUANTITATIVE MATCH: M17's
  own plan doc (section 5) found Qs~=I_F*tau_p sign-ambiguous and off
  by a factor of several and explicitly abandoned it, so no clean pole
  exists to match against; G-ROLLOFF instead gates the qualitative
  roll-off signature (measured: C drops 6.80x, G rises 2.32e6x over
  1kHz-1e11Hz on a 0.4V-forward diode), same honesty standard M17 used
  for its own G2.
  PHASE 2 (Device1D N-terminal Y-parameters + fT) LANDED 2026-09-04,
  merged in from a parallel branch (see commit 9906d6b) -- additive to
  ac_sweep(), new y_parameters()/cutoff_frequency() in the same
  pytcad/ac.py, fixed at exactly 2 ports (Device1D has no N>2-terminal
  case); fmax deliberately not implemented (only meaningful for a
  3-terminal active device). Gates: tests/test_m18_yparam.py.
  PHASE 3 (Device2D, N-terminal Y-parameters) LANDED 2026-09-04 -- see
  pytcad/M18-AC-PLAN.md sections 7-11. New module pytcad/ac2d.py, same
  externally-driven pattern (device2d.py untouched). Generalizes
  Phase 1/2's ohmic-only forcing to a genuine N-terminal Y-parameter
  matrix covering both Device2D port kinds: DirichletBC (ohmic, FD
  current-sensitivity generalized from a 1D edge to an arbitrary 2D
  node set) and GateBC (gate, CLOSED-FORM forcing/observation derived
  from the gate row's own linearization -- genuinely new territory,
  since transient2d.py's own docstring notes time-varying GateBC
  voltage isn't supported there). Cmat needs no gate-row term (Poisson
  carries no time derivative in this codebase). All 6 gates green:
  G-CONSISTENCY-2D, G-LOWF-2D, G-NPORT-OHMIC (a genuine 3-ohmic-
  terminal fixture, none existed before this phase), G-GATE-FD,
  G-MOSCAP-CV, G-SCOPE-REFUSAL-2D. Ill-conditioning found and root-
  caused during development (not a formula bug): a 5nm oxide
  (matching test_cv_physics_validation.py's own value) makes the gate
  row's linearization numerically unstable on the test mesh (AC
  sensitivity varied 0.045-1.746 across equivalent Newton tolerances);
  switching to 20nm gave an 8-significant-figure match against a
  direct finite-difference reference, confirming the code was correct.
  G-MOSCAP-CV's original design (reproduce the classic real-device
  LF/HF inversion C-V divergence) had to be descoped: that divergence
  comes from minority-carrier generation lifetime (a slow process);
  this fixture's DC solve genuinely builds inversion charge but its
  linearized AC sensitivity stops tracking the quasi-static reference
  past threshold (same ill-conditioning class as above, now triggered
  by carrier-concentration dynamic range), and the roll-off it DOES
  show is a bias-independent structural RC effect, not inversion-
  specific -- gated instead on accumulation/depletion/near-threshold
  LF matching plus a bias-independent high-f roll-off sanity check.
  Deep-inversion AC fidelity for Device2D gates is a documented open
  limitation.
  PHASE 4 (GUI exposure) LANDED 2026-09-05 -- see pytcad/M18-AC-
  PLAN.md sections 12-16. Adds: new ACPanel.qml config panel
  (workbench tab + icon) driving a single-contact frequency sweep;
  additive ac__* wire-format keys (ac__freqs/ac__C/ac__G/ac__port,
  unit__ac_capacitance/unit__ac_conductance) dispatched through
  solver_runner.py's existing plain-bias branch (AC augments an
  ordinary bias result rather than replacing it, same as a Sweep or
  Transient would -- corrected during planning from a naive fourth
  top-level elif); a new "ac" MplCanvasItem mode plotting C(f) on the
  primary axis and G(f) on ax.twinx() (no new multi-subplot layout);
  a new "AC" viewport-mode-selector entry; and AppController wiring
  (setACConfig/clearACConfig/acConfig/hasACConfig/hasAc/
  acResultForQml/canRunAc) extending the Sweep/Transient run mutex to
  a 3-way Sweep/Transient/AC mutex. Only the driven port's own
  diagonal Y_kk is surfaced (no N-port matrix/fT display); AC+Sweep
  and AC+Transient combined runs remain mutually exclusive.
  NOT STARTED (at Phase 4 landing): N-port Y-matrix/fT GUI display
  (still not started -- unaffected by Phase 3b below), Device3D AC
  (out of scope entirely).
  PHASE 3b (full 4-terminal mosfet_2d Y-parameter matrix + fT) LANDED
  2026-09-05 -- see pytcad/M18-AC-PLAN.md section 17. y_parameters()
  itself needed NO changes (already generalizes to any ohmic/gate port
  mix, proven by Phase 3's own G-NPORT-OHMIC/G-GATE-FD gates); the only
  new production code is ac2d.cutoff_frequency(yres, port_in,
  port_out), generalizing ac.py's hardcoded 2-port fT algorithm to
  named/indexed N-port pairs. Fixture reused pytcad.mosfet.build_mosfet
  (built for M14, unrelated milestone) rather than a new device
  builder. 4 new gates (tests/test_m18_ac2d.py, 10/10 total): genuine
  current gain + roll-off (unlike the diode's flat |h21|=1), a real fT
  crossing (the first non-synthetic validation of the crossing
  algorithm), broken reciprocity (an active device is not a passive
  2-port, unlike G-NPORT-OHMIC's resistor network), and a direct
  finite-difference cross-check of the drain-gate transconductance --
  all passed first try. fmax (Mason's U(f)) remains explicitly
  deferred, unchanged from Phase 2's own scope note.

M19  SELF-HEATING (THERMODYNAMIC MODEL)                      [L]
  PHASE 1 (steady-state, 1D) LANDED 2026-08-31. New sibling module
  pytcad/thermal.py; device.py/moscap.py untouched. Exploration
  finding that reshaped the plan: Device1D's entire scaling framework
  (VT/Ns/LD/J0/mu_n0/mu_p0/nie/tau_n/tau_p) is built once at __init__
  from a single SCALAR T -- a genuine spatially-coupled 4th Newton
  unknown would mean rearchitecting that whole framework, far larger
  than the gates require. Used the standard "isothermal DD + outer
  Gummel thermal loop" architecture instead (many production TCAD
  tools offer this mode) -- a deliberate choice for a different reason
  than M20's DG lagging (T enters nearly every scaled quantity, not
  one localized term), not a shortcut around a known-bad pattern. Also
  found: no thermal conductivity property existed in materials.py
  before this (contradicts the spec's "no new material work" note) --
  added Semiconductor.kappa_th300/kappa_th(T), Sze & Ng power law,
  mirrors the existing Eg/Nc/Nv T-dependence pattern. A real bug was
  found and fixed deriving the Joule-heating term: the naive (Jn+Jp)*
  E_field formula gives thermodynamically IMPOSSIBLE local negative
  heat in a diode's diffusion-dominated depletion region (measured:
  -31930 W/cm^3 peak) -- fixed using the quasi-Fermi-potential
  gradient (Wachutka 1990's standard DD dissipation term), verified
  against an independent energy-conservation check (integral(H dx)
  matches I*V to 0.04%). 6/6 gates green: G-PARABOLA (exact match,
  0.0 K error -- linear PDE), G-FD (<3.7e-10 relative), G-BC (thermal-
  resistance peak correctly exceeds isothermal), G-ROLLOFF (diode
  current INCREASES 1.11x under self-heating at V=0.55V/R_th=50 --
  the correct diode-physics direction, not the MOSFET-shaped
  "roll-off" the milestone's shorthand name suggests, stated
  honestly), G-OFF-BIT-IDENTITY, G-BC-REFUSAL. Thermal runaway (a real
  phenomenon above ~0.58-0.6V at this R_th) raises RuntimeError rather
  than returning nonsense. See M19-SELFHEATING-PLAN.md for the full
  record, including a note that this session's Python environment was
  removed (by the user, in another terminal) mid-implementation and
  had to be reinstalled before final verification.
  Scope: lattice-temperature equation coupled to DD (Joule term
  + divergence of heat flux), thermal BCs (isothermal, thermal
  resistance to ambient); optional Seebeck term. 1D first, then
  2D. Temperature enters through existing T-dependent material
  calls -- no new material work.
  Acceptance: Joule heating of a uniform resistor vs analytic
  T(x) parabola; electrothermal feedback in a diode I-V vs
  published self-heating roll-off behavior; thermal-off
  bit-identity; FD-Jacobian gate on the coupled block system.
  Depends: M17 (transient machinery for the coupled solve) -- turned
  out not load-bearing for this steady-state phase; noted honestly in
  the plan doc rather than forced.
  NOT STARTED: 2D self-heating, Seebeck/Peltier, transient
  electrothermal, fully monolithic psi/n/p/T Newton coupling.

M20  DENSITY-GRADIENT QUANTUM CORRECTION (= M12-S3, folded)  [M]
  COMPLETE, ALL GATES GREEN, 2026-08-31 (coupled-Newton reformulation).
  Both MOSCapacitor.solve_psi(dg=True) and Device1D.solve_equilibrium
  (dg=True) now solve (psi, Lambda_n, Lambda_p) as ONE coupled Newton
  system (3 unknowns/node) instead of lagging Lambda outside the
  Newton loop -- FD-Jacobian verified <1.2e-9 (both classes), dg=False
  re-verified bit-identical. A one-shot solve at full target gamma
  does not converge (measured: singular step) -- fixed with a gamma-
  continuation strength ladder (the same pattern M15/M16's stiff-
  generation solve_bias already uses). Sweeping gamma with the new
  solver is now SMOOTH and MONOTONIC (0.1 to 1000, no bifurcation) --
  confirms the 2026-08-29 diagnosis that lagging was the real
  architectural problem. Root-caused a genuine WRONG-SIGN bug along
  the way (near-surface Lambda came out NEGATIVE, enhancing rather
  than suppressing density -- independently confirmed to be a property
  of the pre-existing quantum_potential formula on a Neumann-boundary
  classical profile, not new code) and fixed it per literature/
  production-tool research (DEVSIM's density-gradient reference
  implementation extends the mesh into the oxide as a quantum-opaque
  barrier; the equivalent here, and this codebase's OWN Schrodinger-
  Poisson reference's own psi_k(0)=0 hard-wall convention, is pinning
  MOSCapacitor's interface-node Lambda at the existing LAMBDA_MAX_VT
  clamp -- a genuine boundary-condition fix, not a gamma retune;
  dg_gamma stays at its documented default of 1.0, untouched).
  Device1D's DG branch keeps the Neumann boundary (its contacts are
  ohmic, not an oxide interface -- no physical basis for a hard wall
  there); see M20-DENSITY-GRADIENT-PLAN.md section 7 for the full
  record, including the measured gate numbers.
  Implementation per M20-DENSITY-GRADIENT-PLAN.md:
  - pytcad/dg.py: quantum_potential (Ancona-Stafford Lambda, 3-point
    non-uniform stencil; _dg_prefactor extracted as a shared helper so
    the coupled-Newton assembly cannot drift from this formula),
    airy_triangular_well (closed-form Airy reference),
    schrodinger_poisson + schrodinger_poisson_mos (the self-consistent
    published-value reference solver, 2D-DOS Boltzmann occupations --
    FIXED 2026-09-04: the assembled Hamiltonian was never actually
    Hermitian on a non-uniform mesh, which is why the old iterative
    `eigsh` solve was nondeterministic run-to-run; a similarity-
    transformed symmetric formulation plus a switch to the direct
    `eigh_tridiagonal` LAPACK solve made it bit-for-bit reproducible --
    see M20-DENSITY-GRADIENT-PLAN.md section 7.6).
  - MOSCapacitor(dg=False, dg_gamma=1.0): coupled-Newton
    _dg_residual_jacobian/_dg_newton_solve/_solve_psi_dg_coupled, hard-
    wall interface boundary; inversion_centroid(Vg) accessor; dg+fd
    refused.
  - Device1D Models(dg/dg_gamma): coupled-Newton
    _dg_residual_jacobian_eq/_dg_newton_solve_eq/
    _solve_equilibrium_dg_coupled, Neumann (ohmic-contact) boundary;
    dg+fd and dg+incomplete_ion refused; solve_bias + Device2D/3D raise
    NotImplementedError. Default off is bit-identical (G-A gate, M13
    goldens).
  - Catalog "dg" + wire default; the three key-set pin tests updated.
  Acceptance gates G-A..G-F in tests/test_m20_dg.py: ALL GREEN,
  including G-C (S-P centroid factor-2 match: ratio 0.593, DG 2.49nm
  vs S-P 4.20nm) and G-D (centroid >0.2nm, surface suppression now
  correctly signed, Lambda peaks AT the hard wall and decays into the
  bulk -- REWRITTEN from "must be strictly interior," which encoded
  the old, now-understood-to-be-wrong Neumann assumption -- C_max drop
  16.7%, within the 3-25% band).
  Self-caught defects during the gate-writing cross-check: a double-kT
  bug in the 2D-DOS occupation (sheet densities ~1e-7 cm^-2), an
  inverted E_band sign in the S-P driver (well in the bulk), and an
  np.empty garbage diagonal at the Hamiltonian's far boundary.
  Depends: nothing hard; after M13 so FD composes.
  LITERATURE NOTE (2026-08-27, informs design before implementation
  starts -- not yet acted on): the density-gradient model's numerical
  foundation is settled (2008-2021-era literature, nothing materially
  new found for 2025-2026); the one detail worth carrying into this
  milestone's design is boundary conditions at OHMIC CONTACTS.
  Published 3D DG-drift-diffusion work found that NEUMANN boundary
  conditions on the quantum potential at ohmic contacts give more
  stable and physically correct results than the more naively obvious
  Dirichlet choice. Given this codebase's contact-cell sensitivity
  already bit it once this session (M15's frozen-field snapshot picked
  up a spurious MV/cm artifact from stamping a Dirichlet contact value
  next to an un-relaxed neighbor -- see M15-IONIZATION-PLAN.md's debug-
  pass record), the DG boundary condition at contacts should be
  decided deliberately and gated explicitly, not defaulted to whatever
  is easiest to code.

TIER 1 EXIT CRITERIA: a user can, from the GUI or a deck, solve a
Si MOSFET/diode/MOS-C with FD statistics + CVT mobility + II + BTBT
+ TAT + self-heating + DG, run a DC/AC/transient sweep, and every
model on/off difference is validated against literature or analytic
form. This is the honest definition of "Sentaurus default-physics
parity" for silicon 1D/2D.

=== TIER 2: process-lite + general geometry =======================

M21  GENERAL 2D MESHING + FV ASSEMBLY                        [XL]
  ALL PHASES (1-3) COMPLETE 2026-08-31.
  Scope: PHASES 1-2 (1D/2D/3D adaptive h-refinement) SHIPPED (phase 1
  2026-08-27, phase 2 2026-08-28 after a hard-debug pass found and
  fixed six real bugs -- see M21-MESHING-PLAN.md sec 13), see
  pytcad/adapt.py and M21-MESHING-PLAN.md. PHASE 3 (general
  unstructured 2D + Delaunay FV assembly, sub-phases 3a geometry / 3b
  Poisson equilibrium / 3c coupled bias solve / 3d Device2D(
  unstructured=True) integration) is now COMPLETE 2026-08-31 -- see
  M21-PHASE3-MESHING-PLAN.md for the full record, including honest
  gaps (golden parity vs the structured solver measured at ~5-6%, not
  this section's originally-stated <1e-4 target below). The mesher
  choice was DECIDED (2026-08-27, see section 4b.6 below and
  M21-MESHING-PLAN.md sec 12): gmsh, not raw OpenCASCADE or FreeCAD --
  it is the one open
  project bundling an OCC-based CAD kernel, boolean ops, unstructured
  2D/3D meshing, and Physical-Group region tagging in one Python-
  importable package, and DEVSIM (already a backend here) documents
  consuming its meshes directly. Validated, not merely decided:
  examples/debug_geometry_gmsh_conformality.py builds the same p-n
  diode geometry as the pytcad Device2D goldens via gmsh's OCC
  fragment() and confirms the mesh is CONFORMAL across the material
  interface (shared node tags, each exactly at the junction x, not
  merely close) -- the property box-integration FVM assembly requires
  at every interior interface. Scope: box-integration on the gmsh
  mesh (Delaunay FV); solution-driven adaptive refinement (Debye
  length, II rate, field) reusing M21-phase-1's indicators where they
  generalize; the tensor-product assembly becomes a special case.
  Acceptance: GOLDEN -- unstructured mesh of a diode reduces to the
  tensor-product solution within discretization error (the M5
  3D-reduces-to-2D pattern); refinement converges monotonically;
  devsim backend unchanged.
  Depends: nothing hard, but do AFTER Tier 1 (physics first).

M22  LINEAR SOLVER MODERNIZATION + CONTINUATION              [L]
  Scope: Krylov (GMRES/BiCGStab) + ILU (or pyamg, optional dep)
  behind the existing spsolve interface with golden parity tests;
  voltage/parameter continuation driver shared by sweeps, II
  breakdown ramps (M15), and oxidation steps.
  Acceptance: bit-identical solutions (within iterative tolerance)
  on the whole suite; 3D scaling table re-run -- target: 64k-node
  3D completes; continuation converges where fixed stepping failed
  (the known -2V marginal points).
  Depends: nothing; unblocks M15 robustness + M25 3D scale.

M23  2D PROCESS GEOMETRY ENGINE                              [XL]
  Scope: mask-driven deposit/etch with moving boundary (string or
  level-set on the structured mesh first, general mesh after M21);
  2D oxidation (bird's beak) with stress-lite (oxidation-rate
  pressure factor only -- NOT full viscoelastic); mask-driven
  implants with 2D lateral Pearson moments; STI/LOCOS flow.
  Acceptance: 1D Deal-Grove recovered exactly for unmasked oxide;
  mass conservation of moved material to machine precision;
  bird's beak geometry vs published qualitative shape metrics
  (honestly labeled qualitative); implant 2D profiles vs
  SUPREM-style lateral moments.
  Depends: M21 for the general-mesh version; structured-mesh
  version can start earlier.

M24  PAIR DIFFUSION + SEGREGATION + CLUSTERING               [L]
  Scope: P/I and B/I pair-diffusion ODEs per node (extrinsic
  enhancement), OED from oxidation, TED from implant damage
  (+1 populations), SiO2/Si segregation BC, B-cluster /
  P-V clustering above solubility.
  Acceptance: intrinsic limit reduces to current constant-D model
  (bit-identity); extrinsic enhancement vs published D(n/Ni)
  curves; TED junction-depth plateau vs literature experiments;
  segregation dose split vs analytic equilibrium partition.
  Depends: nothing hard.

M25  MONTE-CARLO IMPLANTATION (BCA)                          [L]
  Scope: binary-collision-approximation MC into amorphous then
  crystalline targets (channeling tails); SRIM-comparable output
  moments; feeds both process layer and (via moments) device doping.
  Acceptance: amorphous-target moments vs SRIM tables within
  stated %; crystalline channeling tail qualitatively vs published
  SIMS shapes (honestly labeled); dose conservation.
  Depends: M23 (2D deposition target). Optional dep stays optional.

M26  3D GENERALIZATION OF THE ABOVE                          [XL]
  Scope: unstructured 3D (tets) on top of M21/M22; 3D process
  geometry stays OUT (2D process + extrusion covers FinFET-class
  demos); FinFET/GAA templates built as extruded 2D process output.
  Acceptance: 3D-reduces-to-2D identity on general meshes;
  FinFET electrostatics vs published TCAD-literature curves
  (DIBL/SSE trends), honestly labeled as literature-trend gates.
  Depends: M21, M22, M23.

TIER 2 EXIT CRITERIA: a mask + process deck produces a 2D device
geometry with realistic junctions (TED, segregation, 2D implants,
bird's beak), meshed adaptively, solved with Tier-1 physics, at 3D
scale when wanted.

=== TIER 3: system-level ==========================================

M27  MIXED-MODE DEVICE + CIRCUIT                             [L]
  Scope: MNA solver with device stamps (DD device = nonlinear
  stamp via terminal currents + conductance from the existing
  analytic Jacobian); elements: V/I sources, R, C, diode, level-1
  MOS; DC operating point + transient.
  Acceptance: resistor divider vs analytic; device-in-circuit
  operating point vs device-only solve; ring-oscillator-style
  transient smoke test (honest: qualitative).
  Depends: M17 (transient), M14 (MOSFET mobility credible).

M28  SCHOTTKY / TUNNEL CONTACTS + GATE STACKS                [M]
  Scope: Schottky BC (thermionic emission, Richardson), tunnel
  contact BC, fixed charge / work-function engineering in stacks.
  Acceptance: Schottky I-V vs thermionic theory + image-force
  lowering; Richardson constant benchmark; ohmic-limit recovery.
  Depends: nothing hard.

M29  HYDRODYNAMIC / ENERGY BALANCE                           [XL]
  Scope: carrier-temperature moments (energy balance) with
  published relaxation times; velocity overshoot; couples to II
  and mobility driving forces.
  Acceptance: DD limit recovery (bit-identity when off); overshoot
  peaks vs published Monte Carlo profiles (trend gates); II with
  carrier-T models vs published.
  Depends: M15, M17; genuinely stretch.

M30  WORKBENCH SYSTEM FEATURES + INTEROP                     [M]
  Scope: SWB-style parameterized experiments/splits (parameter
  table x deck = run matrix); calibration/optimization loop
  (goal function vs reference curves, simple Nelder-Mead);
  DeckBuild-dialect import filter; 2D field contours/cuts and
  transient plots in the GUI; batch parallelism.
  Acceptance: split matrix reproduces a documented study;
  optimizer recovers a planted parameter; dialect import round-
  trips our own decks.
  Depends: most things; do last, incrementally.

------------------------------------------------------------------------
4b.3 CRITICAL PATH & SUGGESTED ORDER
------------------------------------------------------------------------
Spine: M13 -> M15 -> M17 -> M18 -> M21 -> M23 -> M27
       (statistics) (II)   (transient)(AC) (meshing)(process)(mixed)
As of 2026-08-31: M13/M15/M17/M18(phase 1)/M21(phase 3 complete) are
all landed; M23/M27 remain not started.

Finish-first queue (already designed, do before M13 -- historical,
all now DONE, kept for the rationale):
  1. M11-S4  2D heterojunction box-integration (designed, HETERO plan)
  2. M11-S5  HBT/HEMT templates + UI
  3. M12-S3  density gradient (== M20 above; design exists)
Rationale: they are designed, small-to-medium, and each retires a
"missing" row above; starting M13 before closing designed work
wastes the design investment.

Parallelizable (independent tracks):
  Track physics:  M13 -> M14 -> M16 -> M19 -> M20
                  (M13/M16/M19-phase1/M20 landed; M14 partial, G-A
                  blocked on a paywalled source)
  Track numerics: M22 -> M21 -> M26
                  (M22 phase 1 + Schur variant landed; M21 phases 1-2
                  and phase 3 (3a-3d) all landed; M26 not started)
  Track process:  M23 -> M24 -> M25 (none started)
  Track system:   M17 -> M18 -> M27 -> M30
                  (M17 and M18-phase1 landed; M27/M30 not started)
M15 needs M22's continuation only for robustness, not correctness.

------------------------------------------------------------------------
4b.4 STANDING ENGINEERING RULES FOR THIS ROADMAP
------------------------------------------------------------------------
1. Any milestone touching a device core reuses the M11-S3 amendment
   mechanism: explicit user sign-off, FD-Jacobian-first, bit-identity
   with the model off, acceptance tests before merge.
2. Every new model lands in tests/test_model_benchmarks.py FIRST with
   published constants; the benchmark error is quoted in the commit.
3. GATE BLOCKING: a milestone whose spec defines quantitative
   acceptance gates blocks all milestones it declares blocked until
   every gate is green under the full-suite invariant. "Mostly green"
   is not green; a skipped or weakened gate is a hidden failure -- this
   is not theoretical: M15 was once declared complete with "all gates
   green" while two of its own gates were unreachable and its
   generation term contributed nothing (see M15-IONIZATION-PLAN.md's
   debug-pass record). M13 was the gate-bearing milestone that used to
   block M15+ under this rule; it is now COMPLETE (all G1-G8 green),
   so M15+ is unblocked.
4. New meshes/linear solvers ship with golden parity tests against
   existing validated paths (tensor-product, spsolve) before anything
   uses them.
5. Optional dependencies stay optional: triangle/gmsh, pyamg, any MC
   helper -- auto-detected, graceful refusal with a precise message.
6. Result schema changes are additive + versioned (v3 for transients).
7. Honesty clauses are mandatory in every milestone: what is NOT
   modeled, where the model breaks, and which gates are qualitative.
8. GUI grows only along validated data paths; no plot without a store
   that a test validates.

------------------------------------------------------------------------
4b.5 STATUS BY MILESTONE (2026-08-31, live -- read this one, not 4b.2,
for what has actually landed)
------------------------------------------------------------------------
  M13 Fermi-Dirac + incomplete ionization        COMPLETE (G1-G8)
  M14 surface/inversion mobility                 MOSTLY COMPLETE
                                                  (2026-08-28): G-B (D_it
                                                  in moscap.py), G-C
                                                  (S_n/S_p in Device1D
                                                  only -- Device2D
                                                  attempted, found to be
                                                  a no-op, reverted to
                                                  an explicit raise),
                                                  driving_force
                                                  (descoped, no 2D/3D
                                                  consumer exists), and
                                                  catalog registration
                                                  (surface_mobility) all
                                                  landed. G-A remains
                                                  OPEN, blocked on a
                                                  paywalled primary
                                                  source (see M14-
                                                  SURFACE-MOBILITY-
                                                  PLAN.md)
  M15 impact ionization coupling                 COMPLETE (all gates
                                                  green, 2026-08-28)
  M16 band-to-band tunneling                     LANDED 2026-08-29,
                                                  VERIFIED 2026-08-31
                                                  (local Kane in
                                                  Device1D, M15-R1b
                                                  live coupling,
                                                  ordering gates
                                                  written first; the
                                                  gate suite was run
                                                  for the first time
                                                  2026-08-31 and 3
                                                  test-code sign/
                                                  threshold bugs were
                                                  found and fixed --
                                                  all 13 gates now
                                                  green; see
                                                  pytcad/M16-BTBT-
                                                  PLAN.md)
  M17 transient simulation                       PHASES 1-3 (1D/2D/GUI)
                                                  DONE 2026-08-31; see
                                                  pytcad/M17-TRANSIENT-
                                                  PLAN.md
  M18 small-signal AC                            PHASE 1 (1D one-port)
                                                  LANDED 2026-08-31; see
                                                  pytcad/M18-AC-PLAN.md;
                                                  PHASE 2 (1D
                                                  multi-terminal
                                                  Y-parameter extraction +
                                                  fT) merged in from a
                                                  parallel branch
                                                  2026-09-04, additive to
                                                  ac_sweep(); PHASE 3
                                                  (Device2D N-terminal
                                                  Y-parameters incl. gate
                                                  ports) LANDED
                                                  2026-09-04, new
                                                  pytcad/ac2d.py; PHASE 4
                                                  (GUI exposure) LANDED
                                                  2026-09-05, new
                                                  ACPanel.qml + ac__*
                                                  wire format + C(f)/
                                                  G(f) via ax.twinx();
                                                  PHASE 3b (4-terminal
                                                  mosfet_2d Y-parameter
                                                  matrix + fT) LANDED
                                                  2026-09-05, new
                                                  ac2d.cutoff_frequency(),
                                                  reused M14's
                                                  build_mosfet fixture
  M19 self-heating                               PHASE 1 (1D
                                                  steady-state) LANDED
                                                  2026-08-31; see
                                                  pytcad/M19-
                                                  SELFHEATING-PLAN.md;
                                                  2D/transient not
                                                  started
  M20 density-gradient quantum correction        COMPLETE, ALL GATES
                                                  GREEN (2026-08-31);
                                                  coupled-Newton
                                                  reformulation, see
                                                  M20-DENSITY-
                                                  GRADIENT-PLAN.md
                                                  section 7. A real
                                                  correctness bug found
                                                  and fixed in a parallel
                                                  branch (merged in
                                                  2026-09-04): the
                                                  discretized Hamiltonian
                                                  was not actually
                                                  Hermitian on a non-
                                                  uniform mesh (row/
                                                  column control-volume
                                                  widths differed) --
                                                  fixed via a similarity-
                                                  transformed symmetric
                                                  formulation, same
                                                  eigenvalues
  M21 general 2D meshing + FV assembly           PHASES 1-2 (1D/2D/3D
                                                  adaptive h-refinement)
                                                  SHIPPED; PHASE 3
                                                  (3a-3d) COMPLETE
                                                  2026-08-31, see
                                                  M21-PHASE3-MESHING-
                                                  PLAN.md. Phase 3d's
                                                  unstructured DD wrapper
                                                  extended to 3D (new
                                                  gmsh_mesh3d.py,
                                                  adapt_unstructured3d.py,
                                                  unstructured_assembly3d.py,
                                                  unstructured_dd3d.py) in
                                                  a parallel branch,
                                                  merged in 2026-09-04
                                                  (27 tests passing)
  M22 linear solver + continuation               PHASE 1 (Krylov+ILU+
                                                  block-Jacobi) SHIPPED,
                                                  3D-scaling gate GREEN;
                                                  a bit-identity bug in
                                                  the "direct" method
                                                  (CSR->CSC reformat
                                                  before spsolve) found
                                                  and fixed; PHASE 2
                                                  (continuation driver,
                                                  strength-ladder-aware
                                                  corrector) LANDED
                                                  2026-08-28, closed
                                                  M15 R1b; PHASE 3
                                                  LANDED 2026-09-02 as
                                                  MPI Schwarz domain
                                                  decomposition (not
                                                  the distributed-
                                                  matrix design
                                                  originally sketched)
                                                  -- 4 ranks, 5.1x on
                                                  bjt_3d, exact to
                                                  ~1e-17; a real
                                                  regression on a
                                                  device whose doping
                                                  varies along the
                                                  split axis (tried on
                                                  pn_junction_3d) was
                                                  found and gated
                                                  against before it
                                                  shipped. Same
                                                  session: pyamg-
                                                  backed AMG for the
                                                  GUI's 3D equilibrium
                                                  solve (8x-44x on
                                                  large meshes) and a
                                                  CUDA (CuPy/cuSOLVER)
                                                  direct solve for the
                                                  bias/sweep Newton
                                                  loop (2.8x on
                                                  bjt_3d's bias
                                                  Jacobian) -- see
                                                  M22-LINSOLVE-PLAN.md
                                                  section 9 for the
                                                  full record.
                                                  GENERALIZED same day
                                                  (section 10) from an
                                                  x-only split to
                                                  picking whichever
                                                  axis (x/y/z) is
                                                  actually safe per
                                                  device -- this is
                                                  what brought
                                                  pn_junction_3d
                                                  (refused outright by
                                                  the x-only check)
                                                  onto the MPI path via
                                                  a z-split, 1.5x over
                                                  its single-process
                                                  AMG+GPU baseline,
                                                  exact to ~1e-17
  M23 2D process geometry engine                 not started
  M24 pair diffusion/segregation/clustering      not started
  M25 Monte-Carlo implantation (BCA)             not started
  M26 3D generalization                          not started
  M27 mixed-mode device + circuit                not started
  M28 Schottky/tunnel contacts                   not started
  M29 hydrodynamic/energy balance                not started
  M30 workbench system features + interop        not started

------------------------------------------------------------------------
4b.6 GEOMETRY FOUNDATION DECISION (2026-08-27) -- M21 phase 3's mesher
------------------------------------------------------------------------
DECIDED as gmsh, not raw OpenCASCADE/pythonocc-core, not FreeCAD.
Checked against this repo, not the libraries in the abstract: gmsh is
the one open project bundling an OCC-based CAD kernel (boxes, polygons,
extrusions, booleans), unstructured 2D/3D meshing, and Physical-Group
region tagging in a single Python-importable package.  Physical Groups
map onto exactly what DeviceSpec.region_materials already does for
rectilinear regions, generalized from boxes to arbitrary shapes.
DEVSIM (already a backend here, workbench/solvers/devsim_backend.py)
documents importing gmsh triangular/tetrahedral meshes directly -- a
used integration path, not a hopeful one.  Raw OCCT is the kernel
underneath gmsh already, so there is no case for binding it directly;
FreeCAD is a desktop application with a Python console, not a library,
and embedding it would fight the pure-QML architecture the same way a
second Qt Widgets stack would.  build123d (parametric CAD on OCP/OCCT)
is queued behind gmsh for if/when freeform sketch-and-drag authoring
is actually asked for -- it is not a mesher and would still hand off
to gmsh for meshing.

VALIDATED, not merely decided: examples/debug_geometry_gmsh_
conformality.py builds the same p-n diode geometry as the pytcad
Device2D goldens through gmsh's OCC kernel and confirms the mesh is
CONFORMAL across the material interface -- p_region and n_region
share 99 node tags at the junction, every one exactly at x = Xj (bit
for bit, not "close to"), region areas match the analytic rectangle
areas to 1e-16 relative, zero degenerate or inverted triangles, and
both contact Physical Groups resolve to real boundary elements.
Conformality across every interior interface is what phase 3's
box-integration FV assembly requires, and it was measured, not
assumed.  A hard-debug finding along the way: an ungrounded gmsh size
field (arbitrary DistMin/SizeMin) over-refined a two-rectangle device
to 21344 nodes by refining uniformly along the entire junction curve
instead of a physically-sized corridor; regrounding it in
pytcad.mesh.debye_length -- the SAME quantity M21 phase 1's own h/L_D
constraint already uses -- cut this to ~2100 nodes, comparable to the
existing tensor-product goldens.  Full record: M21-MESHING-PLAN.md
section 12.  UPDATE 2026-08-31: the region-tag resolver, the FV
assembly, and the golden parity gate are now all DONE -- see M21
Phase 3's completion (M21-PHASE3-MESHING-PLAN.md). Still not done: a
3D repeat of the conformality check (a materially harder case,
solid-solid rather than curve-curve) -- 3D unstructured meshing
remains out of scope (Phase 3's own stated exclusions).

------------------------------------------------------------------------
5. NEXT IMPLEMENTATION MILESTONE
------------------------------------------------------------------------
M15 -- COMPLETE (2026-08-28).  All gates green: G-A, G-B, G-C
(direction + quantitative), G-D (coefficients + both breakdown bands,
two dopings), G-E, G-F.  R1's split (R1a: outer-loop path-dependence,
FIXED via Wegstein acceleration; R1b: coupled Jacobian's true
multiplication vs the analysis-layer estimate) took three attempts
before landing:
  Attempt 1: a full coupled Jacobian passed FD-Jacobian validation but
    produced WEAKER multiplication than the frozen model regardless of
    generation-strength ladder fineness -- damped voltage-controlled
    Newton basin-locking near the avalanche fold, a continuation-
    methodology gap, not a Jacobian-correctness one.  Reverted.
  Attempt 2: built the continuation driver first (M22 phase 2, LANDED
    -- see below), drove the same Jacobian with arc_length_sweep. Hit
    a DIFFERENT problem: the corrector calls device._residual_jacobian
    directly, bypassing solve_bias's generation-strength ladder, so it
    ran at full avalanche coupling from the first iteration and
    stalled at V=-0.5 -- nowhere near the fold.  Reverted.
  Attempt 3: threaded the SAME strength ladder into the corrector
    itself (arc_length_sweep's `strength_stages`) plus added
    backtracking damping the corrector never had.  LANDED: arc-length
    continuation traces cleanly through the genuine avalanche fold for
    both test dopings, redefining "breakdown detected" as that fold
    (a principled definition, not a heuristic).
A dedicated G-C/G-D root-cause investigation followed (2026-08-28,
cross-checked against the original van Overstraeten-de Man 1970
paper): found and fixed a genuine literature bug (the hole ionization
coefficient's low/high-field switch point was wrongly shared with
electrons at 5e5 V/cm instead of its own published 4e5 V/cm -- see
pytcad/ionization.py), and used a hybrid field-profile/formula
diagnostic plus a mesh-refinement sweep to definitively rule out mesh,
units, domain, and convergence causes for both gates.  G-C's gap
turned out to be the textbook local-field approximation the M=1/(1-I)
formula is derived under (it neglects the self-consistent space-
charge feedback the coupled Jacobian solves FOR); the 10%-band miss
was because N=1e17's avalanche fold occurs 35% past the 1970 fit's
own calibrated field range -- neither fixable by solver or
continuation work.  Closed via explicit scope decisions: G-C's
tolerance loosened [0.5,2.0] -> [0.15,2.0] (with the diagnostic
evidence backing the new bound), and G-D's second test doping changed
N=1e17 -> N=2e16 (whose fold stays inside vOdM's calibrated range,
measured ratio 1.059).  Full record, exact numbers, and the permanent
diagnostic tests backing every claim are in M15-IONIZATION-PLAN.md's
"R1b ATTEMPT 1/2/3", "G-C ROOT CAUSE", and "SCOPE DECISION MADE AND
CLOSED" sections -- read them before touching device.py's II code or
pytcad/ionization.py again.  Verified: tests/test_m15_ionization.py
15 passed/0 xfailed/0 failed; full core+GUI suite zero regressions.

M22 phase 2 -- continuation driver, LANDED 2026-08-28
(pytcad/continuation.py: adaptive_bias_sweep, arc_length_sweep;
gated in tests/test_m22_continuation.py against a trusted fixed-step
iv_sweep reference on ordinary, unfolded ramps).  Targets the "-2V
marginal points" acceptance item, and -- once the strength ladder was
threaded into the corrector (attempt 3 above) -- is what let M15 R1b
close; see M22-LINSOLVE-PLAN.md section 1 for the full record. (The
3D-scaling gate that used to be phase 2's headline item is now closed:
a node-block-Jacobi preconditioner fixed it, see section 4b.)

Independent candidates for the next milestone (any order):
1. GUI end-to-end smoke test, LANDED 2026-08-28
   (gui/tests/test_smoke_e2e.py): drives the real rendered QML tree
   only across the 1D Process-Flow path and the 2D Structure/Device-
   Builder-template path -- every physics-model toggle, contact/gate/
   mesh editor, IV/CV sweep, save/reload round trip, and invalid-input
   handling -- cross-checked against the same analytic formulas
   tests/test_validation.py and gui/tests/test_cv_mode.py already use.
   Confirmed 3D and the DEVSIM backend have no GUI entry point at all
   (documented N/A, not fabricated). Found and fixed two real defects
   along the way: numeric QML fields silently let NaN through to the
   solver (fixed with a shared finite-number guard in
   app_controller.py); saved projects silently dropped the Physics
   Lab's model toggles (fixed via project_store's v5 schema bump --
   see gui/README.md's "v0.5.x" section and gui/tests/test_persistence_v5.py).
2. M21 phase 2 -- LANDED 2026-08-28: 2D/3D separable adaptive
   refinement (same indicators, axes refined independently; honest
   limitation: refining one cell refines a whole row/column, motivating
   phase 3). A hard-debug pass found six real bugs before the 25-test
   gate battery went green -- see the M21 status line above and
   M21-MESHING-PLAN.md section 13.
2b. M21 phase 3a (geometry foundation) -- LANDED 2026-08-31: GmshMesh
   loading/building, region/contact resolution, and unique edge-list +
   mixed-Voronoi dual-cell areas on an unstructured triangle mesh
   (pytcad/gmsh_mesh.py, region_resolver.py, unstructured_assembly.py).
   Pure geometry, zero Device2D/Jacobian changes -- an explicit user
   decision to ship the low-risk foundation and defer the HIGH-RISK
   coupled-physics assembly to a future session. See
   M21-PHASE3-MESHING-PLAN.md's "PHASE 3a IMPLEMENTATION RECORD" for
   two corrections made while implementing (the dual-cell method used,
   and a wrong edge-count formula in the original spec text, fixed in
   the gate rather than forced).
2c. M21 phase 3b (unstructured Poisson-only equilibrium) -- LANDED
   2026-08-31, same session: per-edge TPFA flux geometry
   (unstructured_assembly.triangle_circumcenter/build_edge_flux_
   geometry) plus a real Newton-converged Poisson equilibrium solve
   (pytcad/unstructured_poisson.py) on the unstructured mesh, mirroring
   Device2D._residual_jacobian_poisson's exact physics without touching
   device2d.py itself (only its _ohmic_values helper is reused). All
   three gates (G1 FD-Jacobian, G2 vs the already-validated structured
   Device2D solve, G3 charge conservation) passed on the first real run
   against the actual diode mesh -- G2 agreed to 1.3e-16 relative
   (both paths reduce to the same analytic contact formula). 18 tests
   total, tests/test_m21_phase3.py. Scharfetter-Gummel continuity/
   current on triangle edges, bias solves, Device2D(unstructured=True)
   integration, and gates G4-G5 remain the genuinely HIGH-RISK
   remainder, still not started -- see the plan's "PHASE 3b
   IMPLEMENTATION RECORD" for the measured (not assumed) Delaunay-
   quality check this phase's TPFA method relies on.
2d. M21 phase 3c (unstructured coupled bias solve) -- LANDED
   2026-08-31, same session: Scharfetter-Gummel current + SRH
   recombination coupled to Poisson (pytcad/unstructured_dd.py, 3
   unknowns/node), reusing the SAME per-edge geometry factor phase 3b
   already computes (re-derived, not assumed, that no new geometric
   quantity was needed). G1 (FD-Jacobian, full system): 1.4e-8. G4
   (golden parity vs structured Device2D at 0.5V): first attempt showed
   a 69% gap traced to comparing against the wrong reference model
   config (default Caughey-Thomas mobility vs this module's stated
   uniform-mobility simplification) -- fixed, then measured ~5.6%
   relative, reported honestly rather than tightened to the plan's
   original <1e-4 by construction. G5 (SRH live/load-bearing) and a
   reverse-bias adversarial check also green. 26 tests total,
   tests/test_m21_phase3.py. device2d.py remains untouched throughout
   all of phases 3a-3c -- only Device2D(unstructured=True) class-level
   integration (a thin wrapper, not new physics) remains unstarted.
   One pre-existing, unrelated flaky test
   (test_m21_phase2.py::test_3d_separable_refinement_adds_nodes, a
   "Matrix is exactly singular" under -n 6 parallel load, confirmed to
   pass cleanly in isolation) was observed during verification -- not
   a regression from this work.
2e. M21 phase 3d (Device2D(unstructured=True) integration) -- LANDED
   2026-08-31, same session: wired the standalone 3a-3c physics into
   Device2D's own solve_equilibrium/solve_bias/terminal_current API.
   Genuinely thin: zero new Jacobian entries, verified bit-identical
   (array_equal) to calling unstructured_poisson.solve_poisson_
   equilibrium/unstructured_dd.solve_bias directly. Refuses
   (NotImplementedError) any Models() flag the physics core doesn't
   implement (doping_mobility, bgn, fd, incomplete_ion,
   surface_mobility, field_mobility) and a heterostructure material
   list -- Models()'s own default has doping_mobility=True, so callers
   must override it explicitly. A real, small (~2.5e-6 relative)
   discrepancy was found and understood during verification, not a
   bug: the wrapper respects Models().auger (default True, matching
   every other Device1D/Device2D physics flag's convention), while
   unstructured_dd.solve_bias's own bare-function default is
   auger=False -- documented in M21-PHASE3-MESHING-PLAN.md's PHASE 3d
   record and the new gate's docstring. M21 Phase 3 is now COMPLETE.
3. M16 BAND-TO-BAND TUNNELING -- LANDED 2026-08-29, VERIFIED 2026-08-31
   following the M15 R1b pattern (live-coupled generation, shared
   strength ladder), and this time with the residual-ordering and
   live-state invariants written as gates BEFORE the physics gates,
   exactly as this file's M16 note required (see
   pytcad/M16-BTBT-PLAN.md).  The literature-note failure mode
   (local-model plateau at high reverse bias) is gated explicitly by
   the high-bias non-plateau gate.  Verification (2026-08-31) found
   the gates had never actually been executed (the authoring session's
   shell was blocked) and, once run, 2 of 13 tests failed -- but all
   three root causes were bugs in the TEST assertions themselves (an
   inverted sort direction, a sign error comparing two negative
   slopes, and a correlation-sign check that could never pass for a
   genuine negative-slope Kane fit), not in pytcad/btbt.py or its
   Newton-core coupling; see M16-BTBT-PLAN.md's "Gate verification,
   2026-08-31" section for the full record. All 13 tests pass after
   fixing the test code only (history.md
   Addendum 16).
4. M12-S2 GUI exposure -- LANDED 2026-09-04: "tat" added to the wire-
   format defaults and ModelCatalog registry; see section 7 item 5 for
   the full record.
5. M14 remainder -- LANDED 2026-08-28/31: G-B (D_it C-V stretch-out),
   G-C (S_n/S_p surface recombination in Device1D AND, as of
   2026-08-31, Device2D -- a Robin BC reusing the already-computed
   box-integration residual, generalizing to any contact shape with no
   per-edge logic), catalog registration (surface_mobility).
   driving_force descoped (no consumer). Only G-A (Lombardi phonon-term
   constants, blocked on a paywalled source, re-searched 2026-08-31
   with no new result) remains open. One honest limitation found in
   the 2D S_n/S_p work: Newton convergence for a deep minority-carrier
   contact under reverse bias can be non-monotonic. RE-INVESTIGATED
   2026-09-04: the originally-suspected cause (M11-S5's density-floor
   safeguard masking the update criterion) was disproven by direct
   instrumentation, along with two further hypotheses (cold-start
   trapping, SRH/Auger recombination contamination) -- root cause
   narrowed to a likely 2D-specific lateral current-coupling term with
   no 1D analog, but still not fixed (real numerical-methods work, not
   a quick patch). See pytcad/M14-SURFACE-MOBILITY-PLAN.md.

------------------------------------------------------------------------
6. EXPLICITLY NOT IMPLEMENTED YET
------------------------------------------------------------------------
- Transient (M17) LANDED; AC (M18) Phases 1-4 + 3b (1D one-port, 1D
  N-terminal+fT, 2D N-terminal incl. gate ports, GUI exposure,
  4-terminal mosfet_2d Y-parameter matrix + fT) LANDED;
  self-heating (M19) Phase 1 (1D steady-state) LANDED,
  2D/transient not started -- see each milestone's own plan doc.
  (M15 impact ionization, M22 phase 2's
  continuation driver, and M16 local Kane BTBT are COMPLETE/LANDED --
  see sections 3 and 5 and pytcad/M16-BTBT-PLAN.md; the nonlocal BTBT
  variant remains Tier 3.  M20 density gradient is COMPLETE, ALL GATES
  GREEN (2026-08-31) -- equilibrium-only DG behind Models(dg=True)/
  MOSCapacitor(dg=True), now a coupled-Newton solve (see
  M20-DENSITY-GRADIENT-PLAN.md section 7); DG TRANSPORT and 2D/3D DG
  remain not implemented, out of this milestone's scope.)
- 2D process geometry engine (M23); pair diffusion/TED/segregation
  (M24); Monte-Carlo implantation (M25); general 3D (M26).
  (Unstructured meshing, M21 phase 3, is now COMPLETE 2026-08-31 --
  see section 5 item 2e above. M15 impact ionization and M22 phase 2's
  continuation driver are both COMPLETE/LANDED -- see sections 3 and 5
  above; the 3D iterative-solve scaling gate, M22 G6, is likewise
  CLOSED via node-block-Jacobi preconditioning.)
- The interactive GUI itself has no dimensionality selector: every
  Process-Flow-built device is 1D and every Structure/Device-
  Builder-template device is 2D (see the GUI smoke-test entry, section
  5 above); there is no GUI path to AUTHORING a Device3D (v0.6 Phase 2c
  did add a solver BACKEND selector -- pytcad/devsim, gated on 1D
  devices -- so that half of this gap is closed; see
  `pytcad/gui/README.md`). A PyVista/VTK 3D VISUALIZATION viewer (for
  an already-solved 3D result, not authoring one) now exists as of
  2026-08-29/30 -- see `pytcad/3D-VISUALIZATION-PLAN.md` (Phases 1-2
  shipped: a real 3D example device, a viewer window with mesh outline
  and interactive isosurface controls; Phases 3-5 -- volumetric
  rendering, animated sweep playback, exploded structural view -- not
  started; these three phases HAVE since shipped -- see the entry
  above). 3D device AUTHORING now has a DOMAIN MODEL (as of
  2026-08-31): `Region`/`ContactDef`/`DomainDevice` and the
  `StructureModel`/`RegionSpec`/`BoundarySpec`/`MeshModel` GUI-side
  classes all accept an optional z-extent (`z_min`/`z_max`,
  `depth_cm`/`mesh_nz`, `"front"`/`"back"` faces), and
  `workbench/adapters/spec.py`'s `domain_from_structure`/
  `spec_from_domain` build a real 3D `DeviceSpec` from region-authored
  input -- proven to match `resistor_3d_example_spec()`'s hand-built
  equivalent bit-for-bit and to solve correctly on a real `Device3D`
  (see `pytcad/tests/test_workbench_m1.py`'s 3D-authoring tests). What
  is STILL absent is the GUI wiring on top of that domain model: no
  QML z-axis controls, no `AppController` Slot overloads for a 3D
  region/contact, and no "Build 3D device" click-path in the running
  app -- a device author still has to construct the domain objects in
  Python, not through the Structure/Mesh workbench panels.
- Mixed-mode circuit coupling (M27); Schottky/tunnel contacts (M28);
  hydrodynamic/energy balance (M29); experiments/calibration/interop
  (M30).
- Monte-Carlo transport, atomistic kinetic-MC diffusion, radiation/
  SEE, ferroelectrics, full viscoelastic oxidation mechanics, Maxwell
  solvers -- permanently out of scope per the parity plan.
- Rewriting Device classes into compositional equation assembly
  (revisited only when a second concrete model need justifies it).
- ANY change to numerical defaults, scalings, or tolerances; no
  deletion of DeviceSpec or the subprocess contract.

VISION-DOC ITEMS NOT ON THE PARITY ROADMAP AT ALL (from
TCAD_Project_Vision.md, cross-checked against the tree 2026-08-27 --
recorded here so they are tracked rather than silently absent):
- GPU acceleration (CUDA/CuPy) and MPI/domain-decomposition parallelism:
  LANDED 2026-09-02, in the GUI's own 3D solve path only (gui/services/
  solver_runner.py + mpi_schwarz_runner.py), not in pytcad's core
  Device classes themselves. GPU: a CUDA direct sparse solve
  (cuSOLVER via CuPy, pytcad/linsolve.py's "gpu_direct" method) for
  the bias/sweep Newton loop, 2.8x on a real 121k-unknown Jacobian.
  MPI: 4-rank overlapping Schwarz domain decomposition (NOT the
  distributed-matrix design this bullet originally anticipated -- see
  M22-LINSOLVE-PLAN.md section 9), 5.1x on bjt_3d, gated off for any
  device whose doping varies along the split axis after that
  regression was found and reproduced directly (pn_junction_3d).
  GENERALIZED same day (section 10) to pick whichever mesh axis
  (x/y/z) a device is actually safe to split along, instead of an
  x-only check: pn_junction_3d, refused outright before, now qualifies
  via a z-split (1.5x over its single-process AMG+GPU baseline, exact
  to ~1e-17).  EXTENDED to voltage sweeps (M22-LINSOLVE-PLAN.md section
  11, 2026-09-04): a 3-point bjt_3d sweep ran 2.7x faster via MPI
  Schwarz than single-process, with sweep-playback snapshot fields
  agreeing to machine precision across every point.  A REAL
  CORRECTNESS BUG was found and fixed the same day exercising the
  latent axis choices end to end (M22-LINSOLVE-PLAN.md section 12):
  finfet_3d's doping-uniform z-axis also carries a GateBC's oxide-
  coupling term (normal_axis="z"), a field-curvature hazard the
  doping-only safety check couldn't see -- it silently produced a
  wrong (1.4e-3 relative error) AND slower (4.1x) result before the
  fix excluded any axis matching a registered gate's normal_axis.
  Re-verified exact/unaffected on bjt_3d and pn_junction_3d, and
  finfet_3d now correctly falls back to its single-process path.  Both
  GPU and MPI are size-and-hardware-gated opt-in paths -- a machine
  without a GPU or without mpi4py/mpirun sees identical behavior to
  before, just without the speedup.  SYCL has no native Python path
  (oneAPI dpnp is the nearest binding) and was not pursued for that
  reason.  Which engine actually ran is now surfaced to the user via
  AppController.solverEngineLabel (Main.qml status bar), rather than
  being a silent internal choice.
- Cross-backend GUI comparison. workbench/solvers/{base,devsim_backend}.py
  implement the SolverBackend protocol and a working DEVSIM backend, but
  the GUI does not expose backend selection or a side-by-side compare
  view to the user.
- A dedicated provenance-trace UI ("where did this number come from,"
  clicking through mesh -> physics -> material -> backend). Result
  files carry model config and material info, but there is no single
  view that walks the chain.
- Additional device templates the vision names explicitly: BJT, solar
  cell, Schottky diode, PIN diode, FinFET. Only diode/MOSCAP/NMOS/
  HBT/HEMT exist today (workbench/core/templates.py).
- Freeform/arbitrary 2D or 3D device geometry (sketch-and-drag, not
  parametric templates). M21 phase 3 (unstructured meshing) is now
  COMPLETE as of 2026-08-31 -- the FV residual/Jacobian assembly
  (pytcad/unstructured_poisson.py, unstructured_dd.py) and the
  Device2D(unstructured=True) library-level integration both landed
  (section 5 item 2e). What remains is GUI-level only: a
  geometry-authoring UI for freeform regions (sketch-and-drag) does
  not exist -- the library can already solve on an arbitrary gmsh
  mesh, but nothing in the GUI builds or edits one.
- Full numerical-diagnostics panel (Newton iteration/residual history,
  rejected bias points, per-stage continuation record, mesh
  statistics) as a first-class GUI surface. A "convergence" viewport
  mode and RunRecord plumbing exist; the dedicated panel does not.
- Hydrodynamic/energy-balance and Monte-Carlo transport ARE on the
  parity roadmap (M29, and MC transport is explicitly OUT of scope
  there) -- so these are consistent between the two documents, not a gap.

------------------------------------------------------------------------
7. NEXT SESSION QUEUE (priority order, detailed starts)
------------------------------------------------------------------------
1. [DONE 2026-08-28] M15 R1 -- CLOSED, see section 5; this queue entry
   predates that closure.
2. [DONE 2026-08-28] M22 phase 2 -- continuation driver LANDED (the 3D-
   scaling gate that used to head this list is closed via node-block-
   Jacobi preconditioning; see section 4b).
3. [DONE 2026-08-28] M21 phase 2 -- 2D/3D separable adaptive
   refinement LANDED (25 gates); see section 5 item 2.
4. [DONE 2026-08-29] M16 BAND-TO-BAND TUNNELING -- local Kane BTBT
   LANDED in Device1D, residual-ordering and live-state gates written
   first (see section 5 item 3 and pytcad/M16-BTBT-PLAN.md).
5. [DONE 2026-08-28, G-C(2D) DONE 2026-08-31] M14 remainder --
   G-B/G-C(1D+2D)/catalog LANDED; driving_force descoped, G-A remains
   open, re-searched 2026-08-31 with no new result (see section 5 item
   5). M11-S4/S5 GUI polish still open. M12-S2 catalog wiring for TAT
   -- [DONE 2026-09-04]: "tat" added to device_spec.py's
   _default_models() (default False, additive -- an old job.json
   without the key still gets tat=False) and to
   workbench/core/catalog.py's ModelInfo registry (Hurkx reference,
   honest limitations note pointing at the WKB-underflow gotcha).
   PhysicsLabPanel/lab_controller.py already iterate ModelCatalog.list()
   generically, so no QML change was needed. Verified end to end: a
   real diode_1d solve with models["tat"]=True through the actual GUI
   wire format solves cleanly and stamps tat=True into record__meta.
   Two tests had a hardcoded catalog-key list (gui/tests/
   test_physics_lab.py, tests/test_workbench_m1.py) and needed
   updating; full suites (tests/ 419 passed 1 xfailed, gui/tests 624
   passed) otherwise unaffected.
7. [COMPLETE 2026-08-31] M20 DENSITY-GRADIENT -- Ancona-Stafford DG
   quantum correction (equilibrium-only: MOSCapacitor dg flag +
   Device1D Models.dg) plus the pytcad/dg.py analysis layer with the
   Schrodinger-Poisson reference solver. 2026-08-29: gates run for the
   first time, a real outer-fixed-point non-convergence bug found and
   fixed, but G-C/G-D stayed open on a gamma-calibration gap (three
   hypotheses tested and ruled out). 2026-08-31: closed via a coupled-
   Newton reformulation -- (psi, Lambda_n, Lambda_p) solved
   SIMULTANEOUSLY instead of lagged, FD-Jacobian verified, gamma-
   continuation for robust convergence. This also surfaced and fixed a
   genuine wrong-sign bug (near-surface Lambda was negative, enhancing
   rather than suppressing density -- confirmed to be a property of
   the pre-existing quantum_potential formula, not new code) via
   literature/production-tool research (DEVSIM's density-gradient
   implementation): MOSCapacitor's interface node now gets a HARD-WALL
   boundary condition (matching this codebase's own Schrodinger-
   Poisson reference's hard-wall convention), not the old Neumann
   choice; Device1D keeps Neumann (ohmic contacts, no oxide interface
   to justify a hard wall). All gates green, dg_gamma untouched at its
   documented default of 1.0. See M20-DENSITY-GRADIENT-PLAN.md section
   7 for the full record and measured numbers.
8. [PHASES 1-3 DONE 2026-08-30/31] M17 TRANSIENT -- 1D AND 2D
   backward-Euler/theta-scheme transient cores LANDED as new sibling
   modules (pytcad/transient.py, pytcad/transient2d.py), driving
   Device1D/Device2D through their own _residual_jacobian exactly like
   continuation.py does for bias continuation -- device.py/device2d.py
   untouched. Phase 1: G1/G2/G4/G5/G-FD green (G2 left an honest
   partial result, see M17-TRANSIENT-PLAN.md section 5). Phase 2:
   G1/G4/G5/G-FD green (G2 not re-attempted); found and fixed a
   genuinely different charge-conservation sign relationship than
   Phase 1's (Device2D.terminal_current()'s per-contact "into the
   device" convention vs 1D's single-wire edge-flux convention -- see
   plan section 7) and a float64-cancellation bug in the naive
   absolute stored-charge sum at 2D mesh scale. Phase 3: a transient
   run is now reachable end-to-end from the desktop app (new Transient
   tab/panel, schema-v2 -> v3 bump for a new transient__* npz block,
   new "Transient" viewport mode) -- built entirely on top of Phase
   1/2's already-gated solvers, called unmodified; closed a real gap
   found along the way (the devsim backend had no transient dispatch
   at all and would have silently ignored an armed transient config --
   now explicitly refused). GateBC waveforms, project-file persistence
   of an armed transient config, and per-step field-snapshot playback
   remain out of scope, honestly flagged in the plan doc. Next: M18
   (small-signal AC), which depends only on the Device1D transient
   machinery Phase 1 shipped.
9. [PHASES 1-4 + 3b LANDED, latest 2026-09-05] M18 SMALL-SIGNAL AC --
   see the "M18 SMALL-SIGNAL AC ANALYSIS" milestone entry above and
   pytcad/M18-AC-PLAN.md for the full record. Phase 1 (1D one-port),
   Phase 2 (1D N-terminal Y-parameters + fT, merged from a parallel
   branch), Phase 3 (2D N-terminal Y-parameters incl. gate ports),
   Phase 4 (GUI exposure: ACPanel.qml, ac__* wire format, C(f)/G(f)
   via ax.twinx()), and Phase 3b (full 4-terminal mosfet_2d
   Y-parameter matrix + fT, ac2d.cutoff_frequency(), reusing M14's
   build_mosfet fixture) all landed; N-port-matrix/fT GUI display and
   fmax remain not started.
10. [PHASE 1 LANDED 2026-08-31] M19 SELF-HEATING -- see the "M19
    SELF-HEATING (THERMODYNAMIC MODEL)" milestone entry above and
    pytcad/M19-SELFHEATING-PLAN.md for the full record, including the
    architecture decision (isothermal DD + outer Gummel thermal loop,
    not a monolithic psi/n/p/T Newton system) and the quasi-Fermi-
    potential Joule-heating fix. 1D steady-state only; 2D, transient,
    and Seebeck/Peltier not started.
6. FIXED (2026-08-27): the intermittent Qt SIGABRT (native
   `__cxa_deleted_virtual` abort inside `QQuickPaintedItem::
   updatePaintNode`, ~1-in-3 to 1-in-5 full-suite runs). Root cause:
   every gui/tests/*.py file that calls `gui.app.create_engine()`
   builds a QQmlApplicationEngine + QQuickWindow and never tears it
   down; left for Python's refcounting GC, a window can be destroyed
   outside Qt's safe close protocol while a scenegraph paint-node
   update is still pending, and a LATER test's window (sharing the
   same process-wide QGuiApplication) crashes when it walks the dirty-
   item list. Fixed in `gui/tests/conftest.py` (a generic per-test +
   session-teardown sweep that DESTROYS every top-level window --
   `.destroy()`, not `.close()`, since Main.qml's onClosing handler can
   veto a close on unsaved changes -- and drains DeferredDelete events)
   and `gui/app.py` (added `close_engine(engine)`, the teardown API
   `create_engine()` was missing, for any future non-test caller).
   Verified with 6+ consecutive full-suite reruns, zero recurrences.

Standing rules: every slice ships suite-green with pre-existing tests
unchanged; adversarial probe pass before each commit; optional deps
stay optional; gate-bearing milestones block their dependents; a
"COMPLETE, all gates green" status claim is not evidence on its own --
this file was wrong about M15 for a full session before 2026-08-27's
debug pass, and the fix is to measure, not to trust the last status
block.
