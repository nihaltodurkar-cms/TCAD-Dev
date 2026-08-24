# Semiconductor Workbench - v0.5.0 Major Architecture Plan
==========================================================
Date: 2026-08-24. Status: M1 + M2 + M3 + M4 SHIPPED (M4: Physics Lab
foundation -- CatalogModel over the real registry, validated toggles
reaching the executed RunRecord, convergence viewport mode). M3 delivered the
store/analysis boundary (ABC sweep+solved-result protocol, no more
isinstance checks, public selected_step_id, service-layer junction
depth), the observables layer (workbench/analysis, parity-golden vs GUI
readouts, gm(Vg), band diagram matching the core exactly), and the
SolverBackend protocol with golden-equality transparency proof.
M4-M10 still planning. Supersedes the earlier Step-1 plan.txt
(small-boundary scope); keeps its findings as the audit baseline.

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

M5 - DEVICE BUILDER EXPANSION (Device Builder)
  Purpose: parametric templates (pn diode, NMOS like today's example,
          MOS-C) expressed in domain core; Builder UI lists templates
          with editable parameters. BJT/HEMT/solar deferred until
          heterostructure Regions exist.
  Tests: each template builds, solves, matches current benchmarks.

M6 - PROCESS BUILDER (Process side)
  Purpose: process ops map onto domain-core Regions (per-region
          implants); checkpoints become DomainDevices. Scope stays 1D:
          multi-material regions are explicitly OUT until the
          heterostructure question is settled.
  Compat: existing 1D flow files load unchanged.

M7 - DEVSIM BACKEND (Solver Backends)
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

------------------------------------------------------------------------
5. NEXT IMPLEMENTATION MILESTONE
------------------------------------------------------------------------
M1 and M2 are shipped. Next: M3 - ResultStore / analysis boundary +
SolverBackend protocol. It pays down every store-layer leak found in the
audit, promotes analysis into backend-agnostic observables, and defines
the backend door that M4-M10 walk through - still with zero behavioral
change, guarded by parity goldens.

------------------------------------------------------------------------
6. EXPLICITLY NOT IMPLEMENTED YET
------------------------------------------------------------------------
- Any DEVSIM code, install, or adapter (that is M7, behind the M3
  protocol).
- Quantum/tunneling/thermionic/impact-ionization models; any new
  semiconductor physics (M8, gated on benchmarks + catalog metadata).
- Rewriting Device classes into compositional equation assembly
  (deferred until a SECOND concrete model need justifies it - decided
  at M8).
- Custom FEM/FVM; new mesh generators.
- BJT/HEMT/solar-cell device templates (need heterostructure Regions).
- Generic-engine C-V beyond the validated moscap path.
- GUI redesign, theme/layout churn, Matplotlib replacement.
- ANY change to numerical defaults, scalings, or tolerances; no deletion
  of DeviceSpec or the subprocess contract.
