# Semiconductor Workbench - v0.5.0 Major Architecture Plan
==========================================================
Date: 2026-08-24. Status: M1 IMPLEMENTED (domain core + model catalog,
15 tests, both-example equivalence proven); M2-M8 still planning.
Supersedes the earlier Step-1 plan.txt (small-boundary scope); keeps its
findings as the audit baseline.

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
4. MILESTONE ROADMAP
------------------------------------------------------------------------
Every milestone ships green tests and preserves all existing tests.
Dependency order: M1 -> M2 -> M3 -> {M4, M5} -> M6 -> M7; M8 after M1.

M1 - DOMAIN CORE + MODEL CATALOG (Architecture) [SHIPPED]
  Purpose: foundational objects everything else consumes.
  Files: new pytcad/workbench/core/{device,region,materials,catalog}.py;
         pytcad/workbench/adapters/spec.py.
  Interfaces: DomainDevice, Region, MaterialLibrary.get(name),
         ModelCatalog.list()/describe(name)/validate(config).
  Migration: none forced - DeviceSpec stays wire/project format; becomes
         strictly a derived view of DomainDevice.
  Tests: round-trip equivalence (domain->spec->current builder ==
         current direct path for both shipped examples); catalog
         metadata completeness.
  Risks: representation duplication (mitigated by derived-view rule).
  Compat: 100% behavioral.

M2 - RUNRECORD + RESULT SCHEMA v2 (Architecture/Results)
  Purpose: runs become first-class. Capture Newton iteration/residual
         history (keep warnings for compat), stamp enabled-model config,
         emit schema-v2 files (flat node coords + per-node fields +
         structured-shape hint) alongside v1 shaped keys.
  Files: solver_backend (v2 grammar + RunRecord), solver_runner (capture
         + dual write), result_store (prefer v2 when present).
  Tests: conformance 1D/2D/3D on v2 keys; convergence-trace assertions;
         old-file acceptance.
  Risks: file size growth (traces behind a flag); solver_runner is the
         most delicate non-numerical file.
  Compat: v1 readers/writers untouched; backward-readable.

M3 - SOLVERBACKEND INTERFACE (Solver Backends)
  Purpose: real protocol prepare(DomainDevice, ModelConfig, numerics)
         -> SolveHandle; run() -> RunResult+RunRecord. Generic subprocess
         runner keyed by backend id (JobRunner already module-
         parameterized - formalize, don't replace).
  Files: workbench/solvers/base.py, workbench/solvers/pytcad_backend.py
         (thin wrap of today's runner internals), job_runner adaptation.
  Tests: backend-conformance battery (from M2) against pytcad backend;
         golden-file equality with current outputs.
  Risks: behavior drift (guarded by golden tests).
  Compat: default backend id "pytcad"; CLI unchanged.

M4 - PHYSICS LAB PHASE 1 (Educational UI)
  Purpose: first real educational surface: panel listing ModelCatalog
         entries with enable/disable + validated parameter edits;
         equation/reference text; convergence-history plot from
         RunRecord; "what produced this quantity" provenance view.
         Everything backed by the real pipeline - nothing faked.
  Files: qml/panels/PhysicsLabPanel.qml, controllers/lab_controller.py
         (keeps the god controller from growing), analysis hook.
  Tests: headless QML driver checks (catalog reflection, toggles reach
         ModelConfig + change RunRecord, convergence plot data).
  Risks: controller growth (mitigated by dedicated lab_controller).
  Compat: purely additive UI.

M5 - OBSERVABLES LAYER (Analysis)
  Purpose: promote sweep_derived into workbench/analysis with uniform
         Observable.compute(RunResult) interface; add gm(Vg) curve,
         band-diagram extraction, recombination/mobility diagnostic
         fields (core already computes these mid-iteration - expose,
         never recompute); route C-V through the pipeline using the
         validated moscap.cv_sweep behind the Observable interface.
  Tests: numerical parity goldens vs existing sweep_derived values.
  Risks: C-V generality (quasi-static vs small-signal) - scope to the
         validated moscap path first.
  Compat: existing GUI readouts unchanged in wording/values.

M6 - DEVICE TEMPLATES (Device Builder phase 1)
  Purpose: parametric templates (pn diode, NMOS like today's example,
         MOS-C) expressed in domain core; Builder UI lists templates
         with editable parameters. BJT/HEMT/solar deferred until
         heterostructure Regions exist (post-M7 learning).
  Tests: each template builds, solves, matches current benchmarks.
  Risks: low.

M7 - DEVSIM BACKEND SPIKE (Solver Backends)
  Purpose: GENUINE backend proof: optional dependency; 1D diode
         implemented natively in DEVSIM (its own mesh), emitting
         RunResult v2 + RunRecord. Verified against the shared analytic
         benchmark set BEFORE any UI exposure. Unstructured output fits
         schema v2 point clouds; visualization gains a triangulated
         scatter path.
  Tests: cross-backend agreement within stated tolerances; conformance
         battery.
  Risks: highest-risk milestone; isolated by the interface, opt-in,
         off by default.

M8 - PROCESS BUILDER EVOLUTION
  Purpose: process ops map onto domain-core Regions (per-region
         implants); checkpoints become DomainDevices; 2D profiles later.
  Compat: existing 1D flow files load unchanged.

------------------------------------------------------------------------
5. RECOMMENDED FIRST IMPLEMENTATION MILESTONE
------------------------------------------------------------------------
M1 - Domain Core + Model Catalog. It is the one component every other
milestone imports (backends consume Devices+ModelConfig; Physics Lab
renders the Catalog; Builder edits Devices; Analysis annotates Results),
it forces zero behavioral change, and it converts materials.py /
Models-flag reality into documented, citable metadata - the first
tangible educational value.

Deliverable sketch: pytcad/workbench/core/{device,region,materials,
catalog}.py + adapters/spec.py + equivalence tests against both shipped
examples.

------------------------------------------------------------------------
6. EXPLICITLY NOT IMPLEMENTED YET
------------------------------------------------------------------------
- Any DEVSIM code, install, or adapter (that is M7, after M1-M3).
- Quantum/tunneling/thermionic/impact-ionization models; any new
  semiconductor physics.
- Rewriting Device classes into compositional equation assembly
  (deferred until a SECOND concrete model need justifies it - no
  speculative abstraction).
- Custom FEM/FVM; new mesh generators.
- BJT/HEMT/solar-cell device templates (need heterostructure Regions).
- Generic-engine C-V beyond the validated moscap path.
- GUI redesign, theme/layout churn, Matplotlib replacement.
- ANY change to numerical defaults, scalings, or tolerances; no deletion
  of DeviceSpec or the subprocess contract.
