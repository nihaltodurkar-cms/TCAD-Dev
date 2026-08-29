# Semiconductor Workbench - Architecture Plan
==========================================================
Date: 2026-08-28 (updated). Status: M1-M10 SHIPPED (v0.5.0 tagged).
M11 heterostructures COMPLETE through S5 (S1 materials, S2
region_materials wire format, S3 1D heterojunction core: eps(x)
flux-form Poisson, Anderson band offsets via carrier-specific ln(nie)
SG deltas, per-material recombination; S4 2D box-integration
heterojunction core with the full gate battery incl. dimensional
reduction to 1D; S5 structure-model materials lossless end-to-end,
HBT/HEMT parametric templates solve through the pipeline -- COMPLETE
except optional devsim hetero support).
M12 tunneling SHIPPED (S1 FN+WKB analysis module with published-
constant gates; S2 Hurkx trap-assisted tunneling in Device1D, all
acceptance gates green; S3 density-gradient designed, not started --
folded into M20 of the parity plan).
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
full defect ledger.  Phase 3's mesher is DECIDED and its core
conformality claim VALIDATED (gmsh; see section 4b below and
M21-MESHING-PLAN.md sec 12) but phase 3 itself (region-tag resolver,
FV assembly, golden parity) has not started.
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
2026-08-29 LANDED-PENDING-VERIFICATION -- gates written, not yet
executed (same session standing as M16 above).
FUTURE: capability growth is governed by section 4b below (M13
Fermi-Dirac statistics through M30 system-level; three parity tiers).
The M1-M10 roadmap below is retained as the shipped architecture
record; sections 5-7 track the live queue.

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

M11 - HETEROSTRUCTURES [S1-S3 SHIPPED; S4/S5 OPEN]
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

M12 - TUNNELING & QUANTUM CORRECTIONS [S1-S2 SHIPPED; S3 -> M20]
  S1: workbench/physics/tunneling.py -- Fowler-Nordheim constants and
  slope, triangular-barrier WKB kappa/transmission, gated against
  published values. S2: Hurkx trap-assisted tunneling in Device1D
  (Models(tat, trap_et_rel); frozen-field approximation documented;
  WKB factors SI-calibrated -- field in V/m; bulk-Si midgap
  negligibility asserted as honest physics). Acceptance: FD-Jacobian
  with traps < 5e-5; traps-off bit-identity; WKB factor-law gate
  1e7..5e10 V/m; global-charge-balance neutrality. S3 (density
  gradient) was designed in the now-archived M12 tunneling design doc
  and is folded into M20 of the parity plan (not started).

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
  [missing] Quantum corrections (density gradient; Schrodinger-
            Poisson) -- M12-S3 DG designed, not started
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
  Scope: frequency-domain perturbation of the converged DC point
  (complex linear solve with the same analytic Jacobian); Y-
  parameters, C-V(f), admittance for any two-terminal; junction
  and MOS capacitances from the AC solve.
  Acceptance: low-f limit equals quasi-static C-V (existing
  validated path); junction C vs analytic depletion formula;
  3dB roll-off of a diode against the analytic stored-charge
  pole from M17.
  Depends: M17.

M19  SELF-HEATING (THERMODYNAMIC MODEL)                      [L]
  Scope: lattice-temperature equation coupled to DD (Joule term
  + divergence of heat flux), thermal BCs (isothermal, thermal
  resistance to ambient); optional Seebeck term. 1D first, then
  2D. Temperature enters through existing T-dependent material
  calls -- no new material work.
  Acceptance: Joule heating of a uniform resistor vs analytic
  T(x) parabola; electrothermal feedback in a diode I-V vs
  published self-heating roll-off behavior; thermal-off
  bit-identity; FD-Jacobian gate on the coupled block system.
  Depends: M17 (transient machinery for the coupled solve).

M20  DENSITY-GRADIENT QUANTUM CORRECTION (= M12-S3, folded)  [M]
  LANDED-PENDING-VERIFICATION (2026-08-29; same session standing as
  M16/M22-Schur: implemented and gate-written, tests NOT executed).
  Implementation per M20-DENSITY-GRADIENT-PLAN.md:
  - pytcad/dg.py: quantum_potential (Ancona-Stafford Lambda, 3-point
    non-uniform stencil, Lambda=0 at boundary nodes per the Neumann
    literature note below), airy_triangular_well (closed-form Airy
    reference), schrodinger_poisson + schrodinger_poisson_mos (the
    self-consistent published-value reference solver, eigsh + 2D-DOS
    Boltzmann occupations).
  - MOSCapacitor(dg=False, dg_gamma=1.0): lagged-Lambda Newton with an
    outer fixed point; inversion_centroid(Vg) accessor; dg+fd refused.
  - Device1D Models(dg/dg_gamma): solve_equilibrium DG branch (Boltzmann
    only; dg+fd and dg+incomplete_ion refused); solve_bias + Device2D/3D
    raise NotImplementedError. Default off is bit-identical (G-A gate,
    M13 goldens).
  - Catalog "dg" + wire default; the three key-set pin tests updated.
  Acceptance gates G-A..G-F in tests/test_m20_dg.py (NOT YET RUN):
  bit-identity off; S-P vs Airy <=5%; S-P centroid 0.5-4 nm and DG
  within factor 2 of S-P; DG-on direction gates (centroid >0.2 nm,
  surface suppression, Lambda interior peak, C_max drop 3-25%);
  refusals; catalog invariants.
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
  Scope: PHASES 1-2 (1D/2D/3D adaptive h-refinement) SHIPPED (phase 1
  2026-08-27, phase 2 2026-08-28 after a hard-debug pass found and
  fixed six real bugs -- see M21-MESHING-PLAN.md sec 13), see
  pytcad/adapt.py and M21-MESHING-PLAN.md. PHASE 3's mesher choice is
  DECIDED (2026-08-27, see section 4b.6 below and M21-MESHING-PLAN.md
  sec 12): gmsh, not raw OpenCASCADE or FreeCAD -- it is the one open
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
  Track numerics: M22 -> M21 -> M26
  Track process:  M23 -> M24 -> M25
  Track system:   M17 -> M18 -> M27 -> M30
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
4b.5 STATUS BY MILESTONE (2026-08-28, live -- read this one, not 4b.2,
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
  M16 band-to-band tunneling                     IMPLEMENTED 2026-08-29
                                                  (local Kane in
                                                  Device1D, M15-R1b
                                                  live coupling,
                                                  ordering gates
                                                  written first; see
                                                  pytcad/M16-BTBT-
                                                  PLAN.md; suite
                                                  confirmation
                                                  pending)
  M17 transient simulation                       not started
  M18 small-signal AC                            not started
  M19 self-heating                               not started
  M20 density-gradient quantum correction        not started
  M21 general 2D meshing + FV assembly           PHASES 1-2 (1D/2D/3D
                                                  adaptive h-refinement)
                                                  SHIPPED; phase 3 not
                                                  started
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
                                                  M15 R1b
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
section 12.  Not yet done: the region-tag resolver, the FV assembly
itself, the golden parity gate, and a 3D repeat of the conformality
check (a materially harder case, solid-solid rather than curve-curve).

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
3. M16 BAND-TO-BAND TUNNELING -- LANDED-PENDING-VERIFICATION 2026-08-29
   following the M15 R1b pattern (live-coupled generation, shared
   strength ladder), and this time with the residual-ordering and
   live-state invariants written as gates BEFORE the physics gates,
   exactly as this file's M16 note required (see
   pytcad/M16-BTBT-PLAN.md).  The literature-note failure mode
   (local-model plateau at high reverse bias) is gated explicitly by
   the high-bias non-plateau gate.  LANDED-PENDING-VERIFICATION means
   the gates were never executed (the session's shell was blocked);
   the next session MUST run tests/test_m16_btbt.py first (history.md
   Addendum 16).
4. M12-S2 GUI exposure -- Physics Lab entries for TAT (model exists and
   is validated; catalog wiring only).
5. M14 remainder -- LANDED 2026-08-28: G-B (D_it C-V stretch-out), G-C
   (S_n/S_p surface recombination in Device1D), catalog registration
   (surface_mobility). driving_force descoped (no consumer). Only G-A
   (Lombardi phonon-term constants, blocked on a paywalled source) and
   S_n/S_p in Device2D (attempted, found to be a no-op, reverted to an
   explicit raise -- needs a per-contact-adjacency generalization not
   yet built) remain open. See pytcad/M14-SURFACE-MOBILITY-PLAN.md.

------------------------------------------------------------------------
6. EXPLICITLY NOT IMPLEMENTED YET
------------------------------------------------------------------------
- Transient (M17); AC (M18);
  self-heating (M19).  (M15 impact ionization, M22 phase 2's
  continuation driver, and M16 local Kane BTBT are COMPLETE/LANDED --
  see sections 3 and 5 and pytcad/M16-BTBT-PLAN.md; the nonlocal BTBT
  variant remains Tier 3.  M20 density gradient is
  LANDED-PENDING-VERIFICATION -- equilibrium-only DG exists behind
  Models(dg=True)/MOSCapacitor(dg=True), gates unexecuted; DG
  TRANSPORT and 2D/3D DG remain not implemented.)
- Unstructured meshing (M21 phase 3); 2D process geometry engine
  (M23); pair diffusion/TED/segregation (M24); Monte-Carlo implantation
  (M25); general 3D (M26). (M15 impact ionization and M22 phase 2's
  continuation driver are both COMPLETE/LANDED -- see sections 3 and 5
  above; the 3D iterative-solve scaling gate, M22 G6, is likewise
  CLOSED via node-block-Jacobi preconditioning.)
- The interactive GUI itself has no dimensionality or backend selector:
  every Process-Flow-built device is 1D and every Structure/Device-
  Builder-template device is 2D (see the GUI smoke-test entry, section
  5 above); there is no GUI path to a Device3D or the DEVSIM backend.
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
- GPU acceleration (CUDA/CuPy) and MPI/domain-decomposition parallelism.
  M22 phase 1 (Krylov behind spsolve) is the correct PREREQUISITE --
  distributed/accelerated solves need an iterative method, not a
  distributed LU -- but no GPU or MPI code exists anywhere in the tree.
  SYCL has no native Python path (oneAPI dpnp is the nearest binding)
  and was not pursued for that reason.
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
  parametric templates). Blocked on M21 phase 3 (unstructured meshing)
  -- a freeform region needs an unstructured mesh to solve on. The
  mesher for phase 3 is decided and its conformality claim validated
  (see section 4b's Geometry Foundation Decision); the resolver, FV
  assembly, and geometry-authoring UI itself are all still open.
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
5. [DONE 2026-08-28] M14 remainder -- G-B/G-C(1D)/catalog LANDED;
   driving_force descoped, G-C(2D) and G-A remain open (see section 5
   item 5). M11-S4/S5 GUI polish, M12-S2 catalog wiring for TAT --
   small, independent, low-risk, still open.
7. [DONE 2026-08-29, LANDED-PENDING-VERIFICATION] M20 DENSITY-GRADIENT
   -- Ancona-Stafford DG quantum correction (equilibrium-only:
   MOSCapacitor dg flag + Device1D Models.dg) plus the pytcad/dg.py
   analysis layer with the Schrodinger-Poisson reference solver; gates
   G-A..G-F in tests/test_m20_dg.py written but NOT executed (same
   session standing as M16 and the M22 Schur preconditioner; see
   section 4b's M20 entry and history.md Addendum 18).  Verification
   backlog for the next session: py_compile the touched files, then
   test_m16_btbt.py, test_m20_dg.py, test_m22_linsolve.py, and the
   full suite.
8. NEXT on the spine: M17 TRANSIENT (unlocks M18 small-signal/AC and
   M27 self-heating's coupled solve).
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
