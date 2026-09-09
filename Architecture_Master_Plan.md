# TCAD-Dev 2.0 — Architecture & Execution Master Plan

> **Project:** TCAD-Dev  
> **Target:** 10/10 open-source semiconductor multiphysics platform  
> **Date:** September 6, 2026  
> **Purpose:** Define the architecture, implementation order, acceptance criteria, and technical governance for scaling TCAD-Dev from its current validated semiconductor solver into a modular, high-performance 3D TCAD platform.

---

## 0. Executive Summary

The existing plan has the correct central idea:

> **Separate physics, discretization, and compute backend.**

However, the plan needs one important correction: **the architecture should not be optimized around becoming a generic PDE framework for its own sake.**

That would create a large amount of infrastructure with no guaranteed TCAD payoff.

The better target is:

```text
                         TCAD-Dev 2.0
                              │
              ┌───────────────┴────────────────┐
              │                                │
       Semiconductor Physics            Numerical Platform
              │                                │
     Si / SiC / GaN / MOSFET          PDE / Mesh / Solvers
              │                                │
       Process + Device                 CPU / GPU / MPI
              │                                │
              └───────────────┬────────────────┘
                              ↓
                    Large-scale 3D TCAD
                              ↓
                  Verification + Calibration
                              ↓
                       Workbench / API
```

The project should therefore pursue **architecture generality only where it directly improves one or more of:**

- new physics development
- numerical robustness
- 3D geometry support
- DOF reduction
- convergence
- runtime
- memory consumption
- parallel scalability
- reproducibility
- verification

Anything that does not materially improve these should be secondary.

---

# 0.1 Reconciliation With the Existing Roadmap (ARCHITECTURE.md, M1–M30)

**This section is the single most important addition to the plan, because without it the rest of this document reads as if TCAD-Dev were starting from zero.**

TCAD-Dev already has a live, milestone-numbered roadmap in `ARCHITECTURE.md` (§4b), covering `M1`–`M30`, with a "STATUS BY MILESTONE" section that is updated as work lands (last verified 2026-08-31). That roadmap is **not superseded by this document** — it is the ground truth for what exists. This document is the *generic-architecture target* those milestones should converge toward. Concretely:

## What is already done (removed from this document's active roadmap)

**M1–M13 and M15–M22 are shipped/complete; M14 is partial (blocked only on a paywalled source, not a defect).** Full per-milestone detail lives in `ARCHITECTURE.md`'s "STATUS BY MILESTONE" section (§4b.5) — that is the live source of truth and is not duplicated here. Notably, M22 already shipped this document's original Phase 5 (continuation/robust Newton) and Phase 8 (AMG/scalable CPU) content years ahead of the order this document once proposed — those phases have been removed from §38 below accordingly.

**Consequence:** Sections 38/39 of this document (Implementation Roadmap, Priority Matrix) must be read as "what remains," not "what's next from scratch." Anywhere this document says "Phase N — Priority P0," check the M-number mapping in §0.2 below first.

## What is genuinely still ahead (M23–M30 — this is the real backlog)

- **M23** — 2D process geometry engine (mask-driven deposit/etch, oxidation, 2D implants) — **STRUCTURED-MESH SLICE COMPLETE** (`pytcad/process2d.py`, gates G1-G4 green in `tests/test_m23_process2d.py`/`test_model_benchmarks.py`, LOCOS demo in `examples/08_locos_flow.py`). General-mesh version remains future work per the milestone's own spec (structured-mesh first, general mesh after M21 was the plan; only the structured slice has been built).
- **M24** — pair diffusion / segregation / clustering (TED) — **LUMPED-MODEL SLICE COMPLETE** (`pytcad/ted.py`: Fair extrinsic enhancement, "+1" TED supersaturation, OED boost, equilibrium segregation partition, solubility-limited clustering; gates in `tests/test_m24_ted.py`/`test_model_benchmarks.py`; demo in `examples/09_ted_anneal.py`). This is a lumped-scalar engineering model, not a coupled point-defect PDE — see the module's honesty clause; composing it with `process2d.oxidize_2d`'s moving boundary (rather than a fixed interface slab) remains future work.
- **M25** — Monte-Carlo implantation (BCA) — **SIMPLIFIED-BCA SLICE COMPLETE** (`pytcad/mc_implant.py`: screened-Rutherford nuclear scattering with a calibrated LSS electronic-stopping prefactor, not the literal ZBL magic-formula fit — see the module's honesty clause and measured-accuracy note; gates in `tests/test_m25_mc_implant.py`/`test_model_benchmarks.py`; demo in `examples/10_mc_implant.py`). Amorphous-target range matches the existing SRIM-derived table to roughly ±35% over a few-x energy window around calibration; channeling is a disclosed phenomenological knob giving a qualitatively deeper tail, not a lattice simulation.
- **M26** — 3D generalization (unstructured tets on M21/M22, FinFET-class templates) — **STRUCTURED-MESH SLICE + UNSTRUCTURED-TET GATE BC + EXTRUSION PIPELINE, ALL COMPLETE** (to the disclosed simplification level below). Two passes:
  - Pass 1 (structured): `pytcad/finfet3d.py` builds a tri-gate FinFET directly on the existing structured (tensor-product) `Device3D`/`Mesh3D` core (same "structured first, general mesh later" pattern as M23), with `pytcad/characterization.py` (Vth/SS/DIBL extraction) and a literature-trend gate in `tests/test_model_benchmarks.py` showing DIBL and subthreshold swing both worsen as gate length shrinks (Colinge-consistent qualitative trend, not a curve fit); demo in `examples/12_finfet3d_dibl.py`.
  - Pass 2 (unstructured tets, closing the milestone's literal spec): `pytcad/unstructured_dd3d.py` gained a `gates` Robin/oxide-coupling BC (re-derived from first principles, not copied from device3d.py's structured convention — see that module's docstring), backed by `unstructured_assembly3d.boundary_face_node_weights3d` (per-node boundary-triangle area). Building this surfaced and FIXED a genuine pre-existing scaling bug in that module's interior Poisson-flux coefficient (`trans_geom*eps` → the dimensionally-correct `trans_geom/LD`; see the module docstring's "SCALING FIX" section for the full derivation and empirical confirmation) — the bug silently collapsed equilibrium depletion profiles to a near-discontinuous step without visibly failing the existing (tolerance-based, current/bulk-value-only) test suite, all of which still passes after the fix. `pytcad/gmsh_finfet3d.py` extrudes an actual `pytcad.process2d` etch profile into a 3D tri-gate tet mesh (source/gate/drain regions + contacts, tri-gate wrap combined into one face group to avoid double-counting the shared top-corner edge). A new general-mesh "3D reduces to 2D" identity gate (`tests/test_m26_finfet3d.py::test_unstructured_gate_bc_reduces_to_2d`) validates the gate BC against the already-validated `Device2D` solver — the literal general-mesh sibling of `test_validation_3d.py`'s structured-only version of that same acceptance clause. Demo: `examples/13_finfet3d_from_process2d.py`.
  - **Disclosed remaining gaps**: doping extrusion is per-region-constant (reuses `evaluate_doping_at_nodes3d`'s existing convention), not a true 2D process2d implant-array extrusion; the extruded FinFET's fully COUPLED drift-diffusion bias solve was measured to converge slowly/not at all in a single large-voltage-jump Newton call on a first-pass tet mesh (current conservation held throughout, so the trajectory was physically sensible — this needs voltage ramping/continuation, which the structured path's `id_vg_sweep_3d` already does successfully but the tet path's own bias driver does not yet); tet AMR (`adapt_unstructured3d.py`) at FinFET-relevant scale remains only lightly validated (2-3 passes, small meshes).
- **M27** — mixed-mode device + circuit (MNA + device stamps) — **DONE** (2026-09-06): `pytcad/circuit.py` — a Modified Nodal Analysis solver (VSource/ISource/Resistor/Capacitor/Diode/level-1 Shichman-Hodges MOSFET) plus `DeviceStamp`, embedding a real `Device1D` as a nonlinear two-terminal element via a FINITE-DIFFERENCE terminal conductance (not literally "the existing analytic Jacobian" — see that module's own honesty clause for why). Gates: resistor-divider-vs-analytic, device-in-circuit-vs-device-only-solve, and a 3-stage CMOS ring-oscillator transient smoke test (qualitative, as the milestone spec itself calls for), all in `tests/test_model_benchmarks.py`; structural tests in `tests/test_m27_circuit.py`; demo `examples/14_mixed_mode_circuit.py`. `transient()` is backward-Euler only, and a `DeviceStamp` inside a transient circuit is solved quasi-statically each step (no device-internal capacitive coupling) — disclosed, not silently glossed over.
- **M28** — Schottky/tunnel contacts + gate stacks — **STANDALONE-MODULE SLICE COMPLETE** (`pytcad/schottky.py`: thermionic emission + Richardson constants, image-force barrier lowering, Padovani-Stratton field-emission/tunnel-contact regime; gates in `tests/test_m28_schottky.py`/`test_model_benchmarks.py`; demo in `examples/11_schottky_diode.py`). Not yet wired into a live Device1D/Device2D Jacobian as a boundary condition — standalone contact-physics module only, same pattern as M23-M25.
- **M29** — hydrodynamic/energy-balance transport (velocity overshoot) — **DONE** (2026-09-06) as a disclosed-simplification slice, NOT the full self-consistent hydrodynamic transport the spec's own "genuinely stretch" framing anticipated: `pytcad/hydrodynamic.py` is a standalone LOCAL (no spatial energy-flux) steady energy-balance closure — carrier temperature from a published energy relaxation time, a genuinely computable "why overshoot matters in short devices" length scale (l_w = v_sat*tau_w, ~0.04 um for Si, the correct submicron order of magnitude), a qualitative field-driven heating trend, and carrier-temperature-driven impact ionization reached by mapping back to an effective field and reusing the existing (M15) published field-driven van Overstraeten-de Man coefficients. It is NOT wired into Device1D's residual/Jacobian at all (a pure post-processing module), so the milestone's "DD limit recovery (bit-identity when off)" criterion is satisfied by construction — gated explicitly anyway as a regression guard. The genuine limitation, disclosed in the module's own docstring: a purely LOCAL closure cannot reproduce the actual SPATIAL shape of a Monte Carlo overshoot profile (which needs the div(S) energy-flux term this module omits), so the "overshoot" acceptance criterion is satisfied via the heating-trend/length-scale facts above, not a spatial-profile match. Gates in `tests/test_model_benchmarks.py`/`tests/test_m29_hydrodynamic.py`; demo `examples/15_hydrodynamic_overshoot.py`.
- **M30** — workbench system features (parameter sweeps/splits, calibration/optimization loop, DeckBuild-dialect import, batch parallelism) — **this is where this document's Sections 46 (Sweep Engine) and Phase 15 (Calibration/DOE) land.** Do last, incrementally, per its own spec.

Critical path per ARCHITECTURE.md §4b.3: `M13 → M15 → M17 → M18 → M21 → M23 → M27` (statistics → II → transient → AC → meshing → process → mixed-mode). As of the last status update, everything up to and including M21(phase 3) is landed; **M23 and M27 are the actual next milestones.**

## Where this document's architecture vision genuinely adds value

The M-numbered roadmap is a *feature* roadmap (what physics/numerics ship next); it is largely silent on the *generic PDE IR / physics-discretization separation* this document argues for. That gap is real:

- Current physics (`device.py`, `device2d.py`, `device3d.py`) computes residual **and** Jacobian **inline per equation**, hand-deriving sparse structure per model — i.e. physics currently *does* own matrix assembly, which is exactly the situation **Invariant 1** and **Invariant 3** (§49) argue against.
- There is no PDE IR, no generic FVM operator layer, no AD path — Jacobians are hand-derived and gated by finite-difference checks (see §0.3 below), not generated.
- The module layout is `pytcad/` (numerical core) + `workbench/` (domain layer: `ModelCatalog`, `SolverBackend` protocol, backends) + `gui/` (QML) — a real two/three-way separation that already achieves *some* of what the target `tcad/` layout in §5 wants (registry-based model composition, backend protocol), but not the full physics/discretization/backend boundary.

**Recommendation:** treat the PDE-IR/generic-FVM work (this document's Phases 1–4) as a *parallel refactor track*, run alongside the M23/M27 feature track, not a blocking prerequisite. The M-roadmap's own engineering rules (§0.3) already require wrap-don't-rewrite and FD-Jacobian gates for any core change, which is compatible with this document's Principle 1 ("preserve the validated solver") — follow that principle literally: extract the PDE-IR layer *underneath* M23/M27 rather than pausing feature work for it. Do **not** treat generic-FVM/PDE-IR as blocking M23–M30; they are complementary, and M23–M30 have paying users (process/circuit capability) that the IR work does not yet have.

## 0.2 Phase-to-Milestone Cross-Reference (remaining phases only)

Phases fully covered by shipped milestones — the original "Baseline/Inventory," "Solver Robustness," and "Scalable CPU" phases — have been removed from §38 and are omitted here; see §0.1 above for what they were replaced by.

| This document's phase (§38) | Status against M-roadmap |
|---|---|
| Phase 1 — Stable Core Interfaces | Partially exists (`SolverBackend` protocol, `ModelCatalog`); genuine gap is `ResidualProvider`/`JacobianProvider`/`Problem`/`Field` abstractions — still open |
| Phase 2 — PDE IR + Expressions | Not started anywhere in the M-roadmap — this is this document's real net-new contribution |
| Phase 3 — Generic FVM | Not started; M21 built a *concrete* (non-generic) unstructured FVM assembler — reuse its geometry/flux code as the reference implementation when generalizing, per Principle 1 |
| Phase 4 — Jacobian Infrastructure (AD) | Not started; current Jacobians are hand-derived + FD-gated (§0.3) — AD would be additive, not a replacement for the gate |
| Phase 6 — Unstructured 3D | 2D already done (M21) and not repeated in §38; remaining scope is 3D, i.e. **M26** — structured-mesh FinFET slice AND unstructured-tet gate BC + process2d extrusion pipeline + tet-mesh reduces-to-2D identity ALL done; coupled-bias convergence on the extruded tet FinFET (needs voltage ramping) remains open |
| Phase 7 — AMR | 2D h-refinement already done (M21 phase 1) and not repeated in §38; remaining scope is 3D generalization, part of **M26** — `adapt_unstructured3d.py` exists but only lightly validated (2-3 passes, small mesh) |
| Phase 9 — MPI | Partially exists (MPI-Schwarz opt-in in current code); remaining scope is unifying it behind one backend abstraction |
| Phase 10 — GPU | Not started |
| Phase 11 — Electrothermal | Self-heating steady-state 1D already done (**M19 phase 1**) and not repeated in §38; remaining scope is the generic monolithic/staggered coupling layer |
| Phase 12 — SiC/GaN Depth | Most of the list already shipped across M13–M20 and not repeated in §38; remaining scope is M14 gate G-A, avalanche/high-field depth, and a documented benchmark suite |
| Phase 13 — GPU + MPI | Not started |
| Phase 14 — Process Integration | **M23–M25 — done** (structured-mesh/lumped-model/simplified-BCA slices; see §0.1) |
| Phase 15 — Calibration/DOE | **M30**, not started, explicitly "do last, incrementally" |
| Phase 16 — FEM/DG | Not started, correctly deprioritized (P3) in both documents |
| Phase 17 — Mixed-Mode/Contacts/Hydrodynamic | **M27 done** (MNA circuit solver + DeviceStamp); **M28 done** (standalone-module slice); **M29 done** (local energy-balance closure, disclosed slice) |

## 0.3 Standing Engineering Rules (from ARCHITECTURE.md §4b.4 — binding, not aspirational)

These are already-enforced house rules and must be treated as **hard governance**, folded into §40/§41 below rather than duplicated as new ADRs:

1. Any milestone touching a device core reuses the M11-S3 amendment mechanism: **explicit user sign-off, FD-Jacobian-first, bit-identity with the model off, acceptance tests before merge.**
2. Every new model lands in `tests/test_model_benchmarks.py` **first**, with published constants; the benchmark error is quoted in the commit.
3. **Gate blocking is real**: "mostly green" is not green; a skipped or weakened gate is a hidden failure. (M15 was once wrongly declared complete this way — see M15-IONIZATION-PLAN.md's debug-pass record. Do not repeat this.)
4. New meshes/linear solvers ship with golden-parity tests against existing validated paths (tensor-product mesh, `spsolve`) before anything switches to them.
5. Optional dependencies (triangle/gmsh/pyamg/MC helpers) stay optional: auto-detected, graceful refusal with a precise message.
6. Result-schema changes are additive + versioned (schema v3 for transients, etc.).
7. **Honesty clauses are mandatory** in every milestone: state what is NOT modeled, where the model breaks, and which acceptance gates are only qualitative.
8. GUI grows only along validated data paths — no plot without a store a test validates.

---

# 1. Strategic Objective

## Primary objective

Build an open-source TCAD platform capable of solving **large, realistic 3D semiconductor multiphysics problems** while retaining a clean Python-facing development environment.

> **Amendment (2026-09-09).** This document predates M31 and never mentions
> C++. That is now out of date, but the objective above is *unchanged* and
> M31 does not contradict it: Python remains the API, scripting, workflow
> and post-processing surface -- the "clean Python-facing development
> environment" this sentence commits to -- while a C++ engine (`pytcad/core/`)
> takes the numerically intensive layer underneath it. The engine is
> *optional at every step*: `pytcad/_accel.py` soft-imports it and falls back
> to the pure-Python reference, which is also the oracle the compiled path is
> diffed against with `np.array_equal`. Section 37's "do not rewrite the
> project -- progressive extraction" is the rule M31 is executing, not an
> exception to it.
>
> Two things in this document have since been overtaken by measurement and
> should be read with that in mind:
>
> - Section 21's "do not CUDA-port the entire project, profile first" was
>   followed, and the profile says the assembly is **not** the bottleneck
>   (98% of a 3D solve is in `_superlu.gssv`; assembly is 0.011s of 0.494s).
>   The real blocker was unstructured mesh geometry at ~3.5k tets/s, now
>   1.99M tets/s. See `ARCHITECTURE.md` 4c.1.
> - Sections 34/35 (benchmark suite B1-B7, performance dashboard) are still
>   **not implemented**, and section 36 forbids performance claims without
>   them. That gap is now scheduled as M32 and deliberately placed *inside*
>   M31 rather than after it, for the reason section 36 exists.

> **Ambition amendment (2026-09-09).** The stated goal is now to be *better*
> than Sentaurus/Atlas, not level with them. `ARCHITECTURE.md` section 4e
> sets out how that is meant to be true without fighting 30 person-decades
> on their own axis -- principally differentiable simulation / adjoint
> sensitivities (M47-M50), which neither incumbent can offer
> architecturally, plus modern parallel numerics, provenance, and
> inspectable physics. Section 42's API-stability list should be read
> alongside 4e.5's requirement that the residual assembler be
> *parameterized*, since `dR/dp` is part of the public surface if adjoints
> are.

## Strategic specialization

The strongest initial differentiation should be:

> **High-performance 3D TCAD for SiC/GaN and other advanced power/compound semiconductor devices.**

Priority physics:

- drift-diffusion
- Fermi-Dirac statistics
- incomplete ionization
- heterojunctions
- interface traps
- SRH/Auger/radiative recombination
- tunneling / BTBT
- trap-assisted tunneling
- impact ionization / avalanche
- high-field mobility
- electrothermal coupling
- self-heating
- quantum corrections where justified

Do not attempt to reproduce every feature of commercial TCAD before the numerical foundation is strong.

---

# 2. Architectural North Star

The system should have six conceptual layers:

```text
┌──────────────────────────────────────────────────────┐
│  WORKFLOW                                            │
│  GUI / CLI / Python / Batch / DOE                   │
└─────────────────────────┬────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────┐
│  SIMULATION                                           │
│  Device / Process / Sweep / Coupling / Results       │
└─────────────────────────┬────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────┐
│  PHYSICS                                              │
│  Equations / Constitutive Models / Materials         │
└─────────────────────────┬────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────┐
│  NUMERICAL IR                                         │
│  PDE / Residual / Jacobian / Operators               │
└─────────────────────────┬────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────┐
│  NUMERICAL ENGINE                                     │
│  Mesh / FVM / AMR / Nonlinear / Linear Algebra       │
└─────────────────────────┬────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────┐
│  COMPUTE BACKENDS                                     │
│  CPU / CUDA / MPI / GPU+MPI                          │
└──────────────────────────────────────────────────────┘
```

### Fundamental rule

Physics describes **mathematical meaning**.

Numerical infrastructure describes **discretization and solution**.

Backends describe **execution**.

Workflow describes **how users operate the simulator**.

No layer should silently absorb responsibilities belonging to another layer.

---

# 3. What the Current Plan Gets Right

The uploaded plan correctly identifies the following foundations:

- generic PDE IR
- physics/discretization separation
- backend abstraction
- AD for Jacobians
- generic nonlinear solver interface
- unstructured 3D
- AMR
- MPI
- GPU
- multiphysics coupling
- process/device integration
- calibration/DOE
- verification
- unified Simulation API

These should remain.

The major improvement is to **change the implementation order and acceptance criteria** so that each architectural step produces a useful, measurable TCAD capability rather than only a cleaner codebase.

---

# 4. Architecture Principles

## Principle 1 — Preserve the validated solver

The current solver is an asset.

Do not throw it away.

Use it as:

```text
Reference implementation
        +
Regression oracle
        +
Physics validation baseline
```

The new architecture should initially wrap and extract functionality from the existing implementation.

---

## Principle 2 — Physics must be discretization-independent

A physics model should not contain:

```text
CSR matrix construction
finite-volume geometry calculations
CUDA kernels
MPI communication
PETSc calls
GUI state
```

Instead:

```text
Physics model
      ↓
Equation / constitutive description
      ↓
Discretization
```

---

## Principle 3 — Discretization must be physics-independent

The FVM engine should not contain:

```text
if equation == poisson
if equation == electron_continuity
if material == sic
```

It should operate on generic equations, fields, coefficients, fluxes, and source terms.

---

## Principle 4 — Backend independence

The same numerical problem should conceptually support:

```text
CPU
GPU
MPI
GPU + MPI
```

without changing the physics definition.

---

## Principle 5 — Optimize the dominant cost, not the most interesting code

For large 3D TCAD, performance should be investigated using measured profiles of:

```text
mesh
assembly
residual
Jacobian
preconditioner
linear solve
Newton iterations
communication
memory
I/O
```

Do not assume GPU is automatically the largest optimization.

---

# 5. Target Module Architecture

```text
tcad/
│
├── api/
│   ├── simulation.py
│   ├── problem.py
│   ├── sweep.py
│   └── results.py
│
├── pde/
│   ├── ir/
│   ├── expressions/
│   ├── variables/
│   ├── equations/
│   ├── operators/
│   └── boundary_conditions/
│
├── physics/
│   ├── semiconductor/
│   ├── thermal/
│   ├── quantum/
│   ├── optical/
│   ├── mechanical/
│   └── process/
│
├── materials/
│
├── mesh/
│   ├── geometry/
│   ├── topology/
│   ├── structured/
│   ├── unstructured/
│   ├── refinement/
│   ├── partition/
│   └── transfer/
│
├── discretization/
│   ├── fvm/
│   ├── fem/
│   └── dg/
│
├── assembly/
│
├── nonlinear/
│
├── linear_algebra/
│
├── backends/
│   ├── cpu/
│   ├── cuda/
│   └── mpi/
│
├── multiphysics/
│
├── verification/
│
├── calibration/
│
├── workflow/
│
├── io/
│
├── visualization/
│
└── cli/
```

This is the **target architecture**, not a requirement to move the current repository into this layout immediately.

## 5.1 Actual Current Layout (do not confuse with the target above)

The repository is currently split as:

```text
pytcad/      numerical core (device.py, device2d.py, device3d.py, meshing, linear solvers — M1-M22 content)
workbench/   domain layer: ModelCatalog, RunRecord/result schema, SolverBackend protocol, process/device builders
gui/         QML-based GUI (physics lab, device/process builders)
```

This already achieves a partial separation the target `tcad/` layout wants — a model registry (`ModelCatalog`) and a backend protocol (`SolverBackend`) exist today. What it does **not** yet have is the PDE-IR/physics/discretization boundary: `pytcad/device*.py` still hand-assembles residuals and Jacobians per equation (see §0.1). Treat `workbench/` as the seed of the future `api/` + `workflow/` layers, and `pytcad/` as the seed of `physics/` + `discretization/` + `assembly/` once those are pulled apart. Do not create a parallel `tcad/` tree — extract into the existing packages incrementally, per Principle 1.

## 5.2 Workflow-Layer Plans Already in the Repo

Two existing plan documents belong entirely to the **Workflow** layer of the six-layer stack (§2) and to **M30** (Workbench System Features) in the M-roadmap — they are not superseded by this document, just filed here for cross-reference:

- `pytcad/GUI-IMPROVEMENT-PLAN.md` — QML GUI improvements (physics lab / device builder UX).
- `pytcad/3D-VISUALIZATION-PLAN.md` — 3D field/mesh visualization, which will matter once M26 (3D generalization) lands and needs a rendering path.

Both should keep evolving independently of the numerical-architecture phases above; neither blocks nor is blocked by Phases 1–13. `pytcad/DESIGN.md` documents the current GUI/domain design and should remain the reference for workflow-layer decisions until `workbench/` is formally promoted to the `api/`+`workflow/` split in §5.

---

# 6. PDE / Model IR

The PDE IR is the most important architectural investment.

It should describe:

```text
Fields
Equations
Parameters
Expressions
Sources
Fluxes
Constitutive relations
Boundary conditions
Interface conditions
Material dependencies
Time operators
Coupling relationships
```

Conceptually:

```python
problem = PDEProblem()

phi = problem.variable("phi")
n   = problem.variable("n")
p   = problem.variable("p")
T   = problem.variable("T")

problem.add_equation(poisson_equation)
problem.add_equation(electron_continuity)
problem.add_equation(hole_continuity)
problem.add_equation(heat_equation)
```

The IR should not know whether the equations are solved by:

```text
FVM
FEM
DG
CPU
CUDA
MPI
```

---

# 7. Expression System

A generic PDE IR needs a robust expression representation.

Example:

```text
div(eps * grad(phi))
+
q * (p - n + Nd - Na)
```

The expression system should support:

- arithmetic
- gradients
- divergence
- time derivatives
- material properties
- nonlinear functions
- field dependencies
- piecewise/interface behavior
- parameters

This becomes the foundation for:

```text
residual generation
+
automatic differentiation
+
symbolic simplification
+
code generation
```

---

# 8. Residual/Jacobian Contract

All nonlinear physics should reduce to:

```text
F(x) = 0
```

with:

```text
x = global unknown vector
F = global residual
J = dF/dx
```

Define stable interfaces such as:

```text
ResidualProvider
JacobianProvider
```

The important point is that **the nonlinear solver consumes these interfaces without knowing the physical meaning of the equations.**

---

# 9. Jacobian Strategy

Use a three-level strategy:

```text
Level 1 — AD
    ↓
default correctness/development path

Level 2 — symbolic differentiation
    ↓
simplification / generated derivatives

Level 3 — analytic optimized kernels
    ↓
performance-critical models
```

This avoids the false choice between:

> "Everything must be AD"

and

> "Everything must be manually differentiated."

Both are useful.

---

# 10. Physics Plugin Architecture

Physics should be composable.

Example:

```text
DriftDiffusion
    +
SRH
    +
Hurkx BTBT
    +
Impact Ionization
    +
Interface Traps
    +
Electrothermal
```

Each model contributes equations, coefficients, source terms, or constitutive relations.

This allows the simulator to construct a problem from components instead of maintaining hundreds of specialized solver paths.

---

# 11. Materials Architecture

Material properties must become first-class data.

Each material should expose versioned properties such as:

```text
Permittivity
Bandgap
Electron affinity
Effective mass
Density of states
Mobility parameters
Thermal conductivity
Heat capacity
Recombination parameters
Impact-ionization parameters
Tunneling parameters
Trap parameters
```

Requirements:

- unit-aware
- temperature-dependent
- reference/source metadata
- versioned
- testable
- user-overridable

---

# 12. Interfaces and Heterojunctions

Interfaces must be first-class.

```text
Region A
   │
Interface
   │
Region B
```

Support:

- discontinuous material properties
- band offsets
- interface charge
- interface traps
- recombination
- thermionic emission
- tunneling
- thermal boundary conditions

This is a high-priority requirement for SiC/GaN development.

---

# 13. Mesh Architecture

The mesh subsystem should eventually support:

```text
1D structured
2D structured
3D structured
2D unstructured
3D unstructured
adaptive refinement
partitioning
solution transfer
```

The mesh should expose topology and geometry independently.

```text
Mesh
├── geometry
├── topology
├── regions
├── boundaries
└── interfaces
```

This is critical for imported industrial geometries.

---

# 14. Unstructured 3D

Unstructured 3D should be prioritized before FEM/DG.

Why?

Because the immediate TCAD bottleneck is not lack of discretization methods.

It is:

```text
realistic geometry
+
local resolution
+
DOF count
+
memory
+
solver scaling
```

A good 3D unstructured FVM implementation provides much more immediate value.

---

# 15. AMR

AMR should be a generic numerical capability with TCAD-specific indicators.

Loop:

```text
Mesh
 ↓
Solve
 ↓
Estimate error
 ↓
Mark
 ↓
Refine / Coarsen
 ↓
Transfer solution
 ↓
Solve
```

Indicators should eventually include:

- residual-based error
- field gradients
- carrier gradients
- depletion transitions
- heterointerfaces
- tunneling regions
- avalanche regions
- thermal hotspots

### Required benchmark

For a defined accuracy target:

```text
AMR DOF << Uniform-mesh DOF
```

while maintaining equivalent physical accuracy.

---

# 16. Nonlinear Solver Architecture

Create one generic nonlinear framework:

```text
NonlinearSolver
├── Newton
├── Damped Newton
├── Line Search
├── Gummel
├── Continuation
├── Pseudo-Transient Continuation
└── Trust Region
```

Recommended implementation order:

1. Newton
2. Damped Newton
3. Gummel
4. Continuation
5. PTC
6. Trust-region methods

The solver should support difficult device regimes without requiring physics-specific solver classes.

---

# 17. Continuation Is a First-Class Feature

For TCAD, continuation deserves higher priority than the original plan suggests.

Examples:

```text
Voltage continuation
Temperature continuation
Doping continuation
Material-parameter continuation
Trap-density continuation
```

This can be essential for reaching difficult operating points such as:

- breakdown
- strong inversion
- high injection
- severe thermal feedback
- tunneling-dominated regimes

---

# 18. Linear Algebra Architecture

Target:

```text
LinearSystem
├── Vector
├── Matrix
├── Preconditioner
└── LinearSolver
```

Solvers:

```text
Direct
Iterative
Multigrid
```

Initial priority:

```text
GMRES
FGMRES
BiCGSTAB
AMG
```

Direct solvers remain useful for small/medium verification problems and reference solutions.

---

# 19. Preconditioning Strategy

Do not treat AMG as merely another solver option.

For large 3D drift-diffusion, preconditioning is one of the main scalability mechanisms.

Investigate:

```text
AMG
Block preconditioning
Field-split methods
Schur complements
Domain decomposition
Physics-based preconditioners
```

For coupled systems:

```text
Poisson
electron
hole
thermal
```

a field/block-aware preconditioner may eventually outperform a generic black-box AMG approach.

---

# 20. Backend Architecture

```text
Backend
├── CPU
├── CUDA
├── MPI
└── GPU + MPI
```

The backend owns:

- memory placement
- vector operations
- sparse operations
- kernels
- communication
- execution scheduling

Physics does not.

---

# 21. GPU Strategy

Do not CUDA-port the entire project.

Profile first.

Likely candidates:

```text
Residual evaluation
Jacobian evaluation
Flux calculations
Vector operations
SpMV
Selected preconditioner operations
```

Target architecture:

```text
Physics
   ↓
backend-neutral numerical operation
   ↓
┌─────────────┬─────────────┐
CPU           CUDA
```

Maintain a CPU reference path for correctness.

---

# 22. MPI Strategy

Distributed execution requires:

```text
Partitioned mesh
+
ghost cells/elements
+
distributed vectors
+
distributed sparse operators
+
communication
```

Architecture:

```text
Global Mesh
     ↓
Partition
     ↓
Local domain + ghosts
     ↓
Local residual/Jacobian
     ↓
Communication
     ↓
Distributed solve
```

PETSc/Trilinos can be integrated behind the linear-algebra abstraction rather than exposed throughout the codebase.

---

# 23. GPU + MPI

This is a late-stage target.

Required:

```text
distributed mesh
+
GPU-local kernels
+
GPU-aware communication
+
distributed preconditioning
+
multi-GPU scaling
```

Do not make GPU+MPI a prerequisite for proving the architecture.

First prove:

```text
single CPU
→ multi-core CPU
→ single GPU
→ multi-process CPU
→ multi-GPU
```

---

# 24. Multiphysics Architecture

Use a generic coupling layer.

Example:

```text
Electrical
   ↓ Joule heating
Thermal
   ↓ temperature
Material / Mobility / Generation
   ↓
Electrical
```

Support:

### Staggered

```text
electrical → thermal → electrical
```

### Monolithic

```text
[Electrical + Thermal]
       ↓
single nonlinear system
```

### Operator splitting

For suitable time-dependent multiphysics problems.

The coupling mechanism should not be hard-coded specifically for electrothermal simulation.

---

# 25. Process → Device

Target pipeline:

```text
Process recipe
      ↓
Process simulation
      ↓
Geometry/material structure
      ↓
Mesh
      ↓
Device physics
      ↓
Electrical / thermal results
```

The shared infrastructure should include:

```text
geometry
materials
regions
interfaces
mesh
configuration
provenance
```

---

# 26. Workflow Architecture

One public Simulation API:

```text
                Simulation API
              /       |       \
            GUI      CLI     Python
              \       |       /
                    HPC
```

No separate GUI solver.

No separate batch solver.

No separate Python solver.

They all invoke the same simulation engine.

---

# 27. Declarative Simulation Specification

Support a versioned configuration format.

Example:

```yaml
device: sic_mosfet

mesh:
  file: device.msh
  adaptive: true

physics:
  poisson: true
  electron_transport: true
  hole_transport: true
  traps: true
  btbt: hurkx
  avalanche: okuto_crowell
  thermal: true

solver:
  nonlinear: newton
  continuation: true
  linear: gmres
  preconditioner: amg

backend:
  type: cpu

sweep:
  gate_voltage:
    start: 0
    stop: 10
    step: 0.1
```

Configuration should include enough information to reproduce the simulation.

---

# 28. Provenance

Every result should record:

```text
TCAD-Dev version
Git commit
configuration
mesh identifier
material database version
physics models
solver
tolerances
backend
hardware
timestamp
```

This is more important than simply storing a YAML file.

---

# 29. Verification Architecture

Create:

```text
verification/
├── unit
├── analytic
├── manufactured
├── jacobian
├── conservation
├── convergence
├── literature
├── cross_solver
└── experimental
```

Every new physics model should have a verification path before being considered complete.

---

# 30. Jacobian Verification

Every nonlinear model should support:

```text
analytic/AD Jacobian
        vs
finite-difference directional derivative
```

Test:

```text
Jv ≈ [F(x + εv) - F(x)] / ε
```

across multiple:

- states
- mesh sizes
- operating regimes
- parameter ranges

This should become an automated regression test.

---

# 31. Manufactured Solutions

Use manufactured-solution tests to verify the numerical machinery independently of semiconductor-specific physics.

This is one of the strongest ways to test:

```text
PDE IR
+
FVM
+
boundary conditions
+
Jacobian
+
mesh convergence
```

---

# 32. Conservation Tests

Automate:

```text
charge conservation
current continuity
mass balance
energy balance
```

A simulation that converges numerically but violates conservation should not be considered correct.

---

# 33. Cross-Solver Validation

Use independent references where practical:

```text
TCAD-Dev
   ↕
DEVSIM / analytical model / literature
   ↕
experimental data
```

Record discrepancies rather than hiding them.

---

# 34. Benchmark Suite

Create permanent benchmark cases.

### B1 — 1D Poisson

Tests:

- PDE IR
- BCs
- Jacobian

### B2 — 1D diode

Tests:

- DD
- convergence
- conservation

### B3 — 2D MOSFET

Tests:

- device physics
- Newton
- current continuity

### B4 — 3D MOSFET

Tests:

- 3D mesh
- memory
- solver scaling

### B5 — 3D SiC MOSFET

Tests:

- traps
- high field
- avalanche
- thermal coupling

### B6 — 3D GaN HEMT

Tests:

- heterojunctions
- interface charge
- high-field transport

### B7 — Large synthetic 3D

Tests:

- DOF scaling
- AMR
- AMG
- MPI
- GPU

---

# 35. Performance Dashboard

Every benchmark should report:

```text
DOF
NNZ
Memory
Assembly time
Residual time
Jacobian time
Linear solve time
Preconditioner setup
Newton iterations
Total runtime
```

For parallel runs:

```text
speedup
parallel efficiency
communication time
strong scaling
weak scaling
```

For GPU:

```text
CPU runtime
GPU runtime
speedup
GPU memory
kernel breakdown
```

---

# 36. Performance Rule

Never use:

> "The solver is HPC-ready."

unless the benchmark proves:

```text
correctness
+
scaling
+
memory behavior
+
reproducibility
```

Performance claims belong in benchmark tables, not marketing language.

---

# 37. Migration Strategy

## Do not rewrite the project.

Use progressive extraction.

```text
Current implementation
        ↓
Define interfaces
        ↓
Wrap current solver
        ↓
Extract generic components
        ↓
Route one physics subsystem
        ↓
Validate
        ↓
Repeat
```

At each step:

```text
existing tests
+
new architectural tests
+
benchmark comparison
```

must remain green.

---

# 38. Implementation Roadmap

**Removed from this roadmap because already complete:** the baseline/dependency inventory (superseded by `ARCHITECTURE.md` §4b, kept live there instead of frozen here), solver-robustness (damping/line search/continuation/PTC — shipped in M22), and scalable-CPU linear algebra (GMRES/AMG/block preconditioners — shipped in M22). See §0.1–0.3 for what landed and where. What remains below is the actual open roadmap.

## Phase 1 — Stable Core Interfaces (remaining gap only)

**Priority: P0**

`SolverBackend` protocol and `ModelCatalog` already exist (see §5.1). The genuine remaining gap is:

```text
Problem
Field
Equation
BoundaryCondition
ResidualProvider
JacobianProvider
```

Do not build a giant framework. Keep interfaces small.

### Exit criterion

Existing solver executes through the new interfaces.

---

## Phase 2 — PDE IR + Expression System

**Priority: P0**

Implement:

```text
variables
parameters
expressions
equations
sources
BCs
interfaces
```

### Exit criterion

At minimum:

```text
Poisson
+
one nonlinear transport PDE
```

can be expressed through the IR and solved.

---

## Phase 3 — Generic FVM

**Priority: P0**

Refactor:

```text
Poisson
→ electron continuity
→ hole continuity
→ recombination
→ generation
```

through:

```text
Physics
 ↓
PDE IR
 ↓
FVM
 ↓
Residual/Jacobian
 ↓
Existing nonlinear solver
```

### Exit criterion

Validated existing device results remain within predefined numerical tolerances.

Do not require bit-for-bit equality when floating-point operation ordering legitimately changes.

---

## Phase 4 — Jacobian Infrastructure

**Priority: P0/P1**

Implement:

```text
expression graph
AD
Jacobian verification
analytic-kernel escape hatch
```

### Exit criterion

A new nonlinear PDE can be added without manually deriving every Jacobian term.

---

## Phase 6 — Unstructured 3D

**Priority: P0**

**= M26 in the existing roadmap.** 2D unstructured meshing/FVM is already done (M21, all phases) — not repeated here. Remaining scope is the 3D lift on top of M21/M22, per ARCHITECTURE.md's own M26 spec (unstructured tets, 3D-reduces-to-2D bit-identity gate, FinFET/GAA templates via extruded 2D process output). Depends on M21, M22, M23.

Implement:

- tetrahedral mesh
- region topology
- contacts
- interfaces
- imported meshes
- unstructured FVM

### Exit criterion

A realistic 3D device runs and passes conservation/verification tests.

---

## Phase 7 — AMR (3D generalization only)

**Priority: P0**

2D h-refinement (error estimation/marking/refinement/coarsening/solution transfer) is already done (M21 phase 1) — not repeated here. Remaining scope is generalizing the same loop to 3D as part of M26.

### Exit criterion

Equivalent accuracy is achieved with materially fewer DOFs than a uniform 3D mesh on at least two realistic devices.

---

## Phase 9 — MPI (unification remaining)

**Priority: P1**

An opt-in MPI-Schwarz path already exists in the current code — not repeated here. Remaining scope is unifying it behind one backend abstraction (§20) rather than a standalone opt-in:

```text
partitioning
ghost exchange
distributed vectors
distributed matrices
distributed solver — unified with the CPU/GPU backend interface
```

### Exit criterion

A realistic 3D device executes correctly on multiple processes through the same `Backend` interface used by CPU/GPU.

---

## Phase 10 — GPU

**Priority: P1**

Port only profiled hotspots.

### Exit criterion

Demonstrated acceleration for sufficiently large problems without numerical regression.

---

## Phase 11 — Electrothermal (generic coupling remaining)

**Priority: P1**

Steady-state 1D self-heating already ships (M19 phase 1) — not repeated here. Remaining scope is the **generic** multiphysics coupling layer (§24: staggered/monolithic/operator-splitting) using electrical+thermal as the first serious application, rather than a one-off coupling specific to self-heating.

### Exit criterion

Electrothermal simulations converge and conserve energy within defined tolerances, through the generic coupling layer (not a hard-coded electrothermal path).

---

## Phase 12 — SiC/GaN Depth (remaining gaps only)

**Priority: P1**

Most of this list already ships across M13/M15/M16/M20 (traps, heterojunctions, BTBT, incomplete ionization) — not repeated here. Remaining gaps:

```text
M14 gate G-A (surface mobility) — blocked on a paywalled primary source, not a bug; leave open
avalanche / high-field mobility depth beyond what M15 covers
documented, versioned SiC/GaN benchmark suite tying the above together
```

### Exit criterion

A documented SiC and GaN benchmark suite exists covering the remaining gaps above.

---

## Phase 13 — GPU + MPI

**Priority: P2**

Target multi-GPU distributed execution.

### Exit criterion

Published strong/weak scaling benchmark.

---

## Phase 14 — Process Integration

**Priority: P2**

**= M23 (2D process geometry: mask-driven deposit/etch, oxidation, 2D implants) → M24 (pair diffusion/segregation/TED) → M25 (Monte-Carlo implantation).** M23's structured-mesh slice, M24's lumped-model slice, and M25's simplified-BCA slice are all complete (`pytcad/process2d.py`, `pytcad/ted.py`, `pytcad/mc_implant.py`). **Phase 14 / M23-M25 is now functionally done** (to the disclosed simplification level in each module's honesty clause); **M26 (3D generalization) or M27 (mixed-mode circuit) are the next items on the critical path** — see §0.1/§0.2.

Connect process-generated structures directly to the device pipeline.

---

## Phase 15 — Calibration / DOE

**Priority: P2**

**= M30 (Workbench System Features)**: parameter sweeps/splits, calibration/optimization loop (goal function vs. reference curves, Nelder-Mead), DeckBuild-dialect import, batch parallelism. Per its own spec, do this **last, incrementally** — it depends on most other milestones being in place to have something to sweep/calibrate over.

Implement:

```text
parameter extraction
DOE
sensitivity
optimization
uncertainty analysis
```

---

## Phase 16 — FEM / DG

**Priority: P3**

Implement only when there is a concrete physics or numerical requirement.

Do not implement them merely to increase the feature list.

---

## Phase 17 — Mixed-Mode Circuit, Contacts, Hydrodynamic Transport

**Priority: P1 (M27/M28) / P2-stretch (M29)**

Three M-roadmap milestones with no home in the original phase list:

- **M27 — mixed-mode device + circuit**: MNA solver with device stamps (DD device as nonlinear stamp via terminal currents + conductance from the existing analytic Jacobian). Depends on M17 (transient) and M14 (MOSFET mobility credible) — both landed or near-landed, so this is realistically unblocked once M23 frees up roadmap bandwidth.
- **M28 — Schottky/tunnel contacts + gate stacks**: **DONE** (standalone-module slice) — thermionic-emission Schottky BC (`pytcad/schottky.py`), image-force lowering, Padovani-Stratton tunnel-contact/field-emission regime classification. Work-function/fixed-charge engineering in MOS gate stacks was already covered by `pytcad.moscap.flatband_voltage` from earlier work. Remaining future work: wiring the Schottky BC into a live Device1D/Device2D Newton solve (currently standalone I-V/regime physics, not solver-coupled).
- **M29 — hydrodynamic/energy-balance transport**: carrier-temperature moments, velocity overshoot, couples to impact-ionization and mobility driving forces. Depends on M15, M17; explicitly a stretch goal — do not let it block anything on the critical path.

### Exit criterion

Per each milestone's own acceptance gates (ARCHITECTURE.md §4b.2): resistor-divider/device-in-circuit agreement for M27; Schottky I-V vs. thermionic theory + Richardson-constant benchmark for M28; DD-limit bit-identity recovery plus literature-trend overshoot gates for M29.

---

# 39. Priority Matrix

**Rows already fully complete have been removed** (Robust Newton/continuation and AMG — both shipped in M22; see §0.1). Remaining/partial capabilities only:

| Capability | Priority | Strategic reason | Status (see §0.1–0.2) |
|---|---:|---|---|
| PDE IR | P0 | Core abstraction | Not started — genuine gap |
| Expression system | P0 | Enables generic equations/AD | Not started — genuine gap |
| Generic FVM | P0 | Main TCAD discretization | Not started (concrete 2D unstructured FVM exists via M21, not generic) |
| Unstructured 3D | P0 | Real geometry | 2D done (M21); M26's FinFET/DIBL-SSE gate done on the structured path (`pytcad/finfet3d.py`) AND the unstructured-tet path now has a gate BC, a process2d extrusion pipeline (`pytcad/gmsh_finfet3d.py`), and a tet-mesh reduces-to-2D identity test |
| AMR | P0 | DOF reduction | 2D h-refinement done (M21 phase 1); 3D tet AMR exists (`adapt_unstructured3d.py`) but lightly validated only (2-3 passes, small mesh) |
| Residual/Jacobian API | P0 | Generic nonlinear solving | Not started — physics hand-assembles inline today |
| Linear algebra abstraction | P0 | Backend independence | Partial — Krylov/AMG exist (M22), not yet backend-unified |
| AD | P1 | Development speed/correctness | Not started — Jacobians hand-derived + FD-gated |
| MPI | P1 | Distributed memory | Partial — MPI-Schwarz opt-in exists, not unified |
| CUDA | P1 | Accelerator performance | Not started |
| Electrothermal | P1 | High-value multiphysics | Steady-state 1D done (M19 phase 1); remaining scope is generic coupling layer |
| SiC/GaN physics | P1 | Strategic differentiation | Most landed (M13/M15/M16/M20); remaining gaps are M14 gate G-A, avalanche/high-field depth, documented benchmark suite |
| Calibration | P2 | Engineering workflow | Not started — = M30, do last |
| Process expansion | P2 | Integrated TCAD | **Done — M23/M24/M25** (disclosed-simplification slices; general-mesh/coupled-point-defect/full-ZBL fidelity remain future work) |
| GPU + MPI | P2 | Advanced HPC | Not started |
| FEM | P3 | Secondary discretization | Not started, correctly deprioritized |
| DG | P3 | Specialized | Not started, correctly deprioritized |
| Tcl | P3 | Low strategic value | Not started, correctly deprioritized |
| Mixed-mode circuit (M27) | P1 | Unblocks system-level validation | **Done** — `pytcad/circuit.py` (finite-difference DeviceStamp conductance, not the literal analytic-Jacobian mechanism) |
| Schottky/tunnel contacts (M28) | P1 | Contact physics completeness | **Done — standalone-module slice** (Jacobian-coupled BC remains future work) |
| Hydrodynamic transport (M29) | P2-stretch | Overshoot-regime accuracy | **Done** — local energy-balance closure (`pytcad/hydrodynamic.py`), not the full self-consistent transport solve the stretch framing anticipated |

---

# 40. Architecture Governance

**These rules are already in force (ARCHITECTURE.md §4b.4 / §0.3 above) and take precedence over anything below that would relax them:** FD-Jacobian-first + bit-identity-off-path + explicit sign-off for any device-core change; benchmark-first model landing; gate-blocking with no "mostly green"; golden-parity tests for new meshes/solvers before switchover; optional deps stay optional; additive+versioned result schema; mandatory honesty clauses per milestone; GUI only grows along validated data paths. New ADRs below are additive to this list, not a replacement for it.

Create ADRs for decisions that are expensive to reverse.

Minimum:

```text
ADR-001 — PDE IR
ADR-002 — Expression representation
ADR-003 — Physics/discretization boundary
ADR-004 — FVM architecture
ADR-005 — Mesh abstraction
ADR-006 — AMR strategy
ADR-007 — Jacobian/AD strategy
ADR-008 — Nonlinear solver API
ADR-009 — Linear algebra API
ADR-010 — MPI architecture
ADR-011 — GPU architecture
ADR-012 — Material database
ADR-013 — Configuration format
ADR-014 — Verification policy
ADR-015 — Result/provenance format
```

---

# 41. Architectural Tests

Do not rely only on unit tests.

Add tests that enforce architecture.

Examples:

```text
physics package cannot import backend package
physics package cannot import GUI
FVM cannot depend on semiconductor-specific classes
backend cannot depend on physics
GUI cannot instantiate solver internals directly
```

Use automated import/dependency checks in CI.

This prevents architectural erosion six months after the refactor.

---

# 42. API Stability

Separate:

```text
Public API
```

from:

```text
Internal implementation
```

Only a small set should be stable initially:

```text
Simulation
Problem
Field
Mesh
PhysicsModel
Solver
Results
Configuration
```

Everything else can evolve.

This prevents premature API lock-in.

---

# 43. Data and I/O Strategy

Avoid allowing every module to invent its own file format.

Define a result model containing:

```text
mesh
regions
fields
contacts
materials
metadata
provenance
solver diagnostics
```

Support:

```text
checkpoint
restart
field export
simulation metadata
```

A large 3D simulation must be restartable.

---

# 44. Checkpoint / Restart

This should be elevated from a convenience feature to a core HPC requirement.

Support:

```text
save nonlinear state
save mesh
save material/model configuration
save solver state where practical
restart on another run
```

For distributed execution:

```text
checkpoint
    ↓
restart
    ↓
possibly different process count
```

should eventually be supported.

---

# 45. Fault Tolerance

For long HPC jobs, design for failure.

At minimum:

```text
periodic checkpoints
restartable sweeps
failed-point isolation
per-step logging
```

A 48-hour simulation that loses all progress because one operating point failed is poor workflow architecture.

---

# 46. Sweep Engine

The Workbench should eventually support:

```text
parameter sweeps
voltage sweeps
temperature sweeps
material sweeps
geometry sweeps
DOE
```

Continuation should allow previous converged solutions to seed subsequent points.

This is both a numerical optimization and a workflow feature.

---

# 47. Results and Diagnostics

Every solve should expose:

```text
converged?
Newton iterations
linear iterations
residual norm
step norm
minimum/maximum fields
conservation error
runtime
memory
```

This is essential for debugging and scientific reproducibility.

---

# 48. What NOT to Build Yet

Do not prioritize:

```text
FEM
DG
optics
mechanics
complex quantum transport
massive process feature expansion
Tcl compatibility
large plugin marketplace
```

until:

```text
PDE IR
+
generic FVM
+
unstructured 3D
+
AMR
+
robust nonlinear solving
+
scalable linear algebra
```

are mature.

---

# 49. What Must NOT Be Compromised

The following are architectural invariants:

### Invariant 1

Physics never directly owns sparse matrix assembly.

### Invariant 2

Physics never calls CUDA/MPI/PETSc directly.

### Invariant 3

FVM never contains semiconductor-specific branching.

### Invariant 4

GUI never contains numerical algorithms.

### Invariant 5

Backends never contain device-specific physics.

### Invariant 6

Verification is part of feature development, not an afterthought.

### Invariant 7

Performance claims require benchmarks.

---

# 50. Definition of Done — Architecture

The architecture is mature when:

## Physics

- [ ] New physics can be composed from reusable models.
- [ ] Physics does not depend on hardware.
- [ ] Physics does not depend on discretization.
- [ ] Material/interface models are modular.

## PDE

- [ ] Generic PDEs can be represented.
- [ ] Expressions support nonlinear coupled equations.
- [ ] Residual/Jacobian contracts are stable.
- [ ] AD is available.

## Numerics

- [ ] Generic FVM exists.
- [ ] Unstructured 3D exists.
- [ ] AMR exists.
- [ ] Newton/Gummel/continuation use common infrastructure.
- [ ] AMG/block preconditioning is available.

## HPC

- [ ] CPU backend is stable.
- [ ] MPI backend is stable.
- [ ] GPU backend is stable.
- [ ] GPU+MPI has been demonstrated.
- [ ] Scaling benchmarks are reproducible.

## TCAD

- [ ] SiC benchmark suite exists.
- [ ] GaN benchmark suite exists.
- [ ] Electrothermal coupling is validated.
- [ ] Process-to-device pipeline works.

## Verification

- [ ] Jacobian tests are automated.
- [ ] Manufactured solutions exist.
- [ ] Mesh convergence is tested.
- [ ] Conservation is tested.
- [ ] Cross-simulator/literature validation exists.

## Workflow

- [ ] GUI, CLI, Python and HPC use one Simulation API.
- [ ] Configurations are versioned.
- [ ] Results contain provenance.
- [ ] Checkpoint/restart exists.
- [ ] Sweeps are reproducible.

---

# 51. The Real 10/10 Test

Ignore the architecture diagram for a moment.

Ask seven practical questions.

### 1. Can I add a new nonlinear PDE without rewriting the solver?

If yes, the PDE abstraction works.

### 2. Can I use the same physics model on structured and unstructured meshes?

If yes, the discretization boundary works.

### 3. Can I move from CPU to GPU without changing physics code?

If yes, the backend boundary works.

### 4. Can a 3D device be locally refined without rewriting physics?

If yes, AMR is properly separated.

### 5. Can a difficult breakdown point be reached through generic continuation rather than device-specific hacks?

If yes, the nonlinear infrastructure is becoming mature.

### 6. Can the same simulation run through GUI, Python, CLI and HPC?

If yes, the workflow architecture works.

### 7. Can every performance/accuracy claim be reproduced from a versioned benchmark?

If yes, the project is becoming an engineering-grade simulator rather than a research codebase.

---

# 52. Final Target Architecture

The final system should conceptually look like:

```text
                         USER
                          │
          ┌───────────────┼────────────────┐
          ↓               ↓                ↓
         GUI             CLI             Python
          └───────────────┼────────────────┘
                          ↓
                  ┌───────────────┐
                  │ Simulation API│
                  └───────┬───────┘
                          ↓
             ┌────────────────────────┐
             │ Problem / Workflow     │
             └───────────┬────────────┘
                         ↓
             ┌────────────────────────┐
             │ Physics + Materials    │
             └───────────┬────────────┘
                         ↓
             ┌────────────────────────┐
             │ PDE / Model IR         │
             └───────────┬────────────┘
                         ↓
             ┌────────────────────────┐
             │ Discretization          │
             │ FVM → FEM → DG          │
             └───────────┬────────────┘
                         ↓
             ┌────────────────────────┐
             │ Mesh + AMR + Partition  │
             └───────────┬────────────┘
                         ↓
             ┌────────────────────────┐
             │ Residual + Jacobian     │
             │ AD + Analytic Kernels   │
             └───────────┬────────────┘
                         ↓
             ┌────────────────────────┐
             │ Nonlinear Solver        │
             │ Newton / Gummel / PTC   │
             └───────────┬────────────┘
                         ↓
             ┌────────────────────────┐
             │ Linear Algebra          │
             │ GMRES / AMG / Blocks    │
             └───────────┬────────────┘
                         ↓
             ┌────────────────────────┐
             │ Backend                 │
             │ CPU / CUDA / MPI        │
             └───────────┬────────────┘
                         ↓
                  LARGE 3D TCAD
                         ↓
             ┌────────────────────────┐
             │ Verification           │
             │ Calibration             │
             │ Benchmarks              │
             │ Provenance              │
             └────────────────────────┘
```

---

# 53. Bottom Line

The original plan's direction is strong, but the improved strategy is more disciplined:

```text
Do NOT build a generic PDE framework first
and hope it becomes useful for TCAD.

Build the minimum generic PDE infrastructure
required to solve increasingly difficult TCAD problems.
```

**Robust Newton + continuation and AMG/block preconditioning are already shipped (M22) and removed from this progression** — see §0.1. The remaining progression is:

```text
CURRENT VALIDATED TCAD  (M1-M22 shipped, incl. continuation + AMG)
        ↓
ARCHITECTURAL INTERFACES  (remaining gap only, §38 Phase 1)
        ↓
PDE IR + EXPRESSIONS
        ↓
GENERIC FVM
        ↓
UNSTRUCTURED 3D  (3D lift only, 2D already done — M26)
        ↓
AMR  (3D generalization only, 2D already done — M26)
        ↓
MPI  (unify existing opt-in path behind one backend)
        ↓
GPU
        ↓
ELECTROTHERMAL  (generic coupling layer, 1D steady-state already done)
        ↓
SiC / GaN DEPTH  (remaining gaps only — see §0.1/§39)
        ↓
GPU + MPI
        ↓
PROCESS INTEGRATION  (M23-M25 — done, disclosed-simplification slices)
        ↓
MIXED-MODE / CONTACTS / HYDRODYNAMIC  (M27-M29)
        ↓
CALIBRATION / DOE  (M30)
        ↓
MATURE OPEN-SOURCE TCAD PLATFORM
```

The first serious milestone is **not CUDA**.

It is:

```text
Poisson + Drift-Diffusion
        ↓
Generic PDE IR
        ↓
Generic FVM
        ↓
Generic Residual/Jacobian
        ↓
Existing validated nonlinear solver
        ↓
All existing tests still pass
```

Once that boundary is real, the rest of the roadmap becomes technically credible.

Until that boundary exists, adding more physics or hardware backends mostly increases architectural debt.

---

# 54. Immediate Action Plan

**Revised in light of §0.1: the baseline and dependency inventory this section originally asked for already exists in `ARCHITECTURE.md` §4b (status-by-milestone, critical path, standing rules). Do not redo that work — keep it updated as milestones land. The action plan below starts from that ground truth.**

### Next 1 — Keep the baseline current, don't refreeze it

`ARCHITECTURE.md`'s "STATUS BY MILESTONE" section is the baseline. When a milestone's status changes, update it there (and cross-check §0.1/§0.2 above), rather than maintaining a second competing status table in this document.

### Next 2 — The dependency graph already exists

`ARCHITECTURE.md` §4b.3 (critical path: `M13 → M15 → M17 → M18 → M21 → M23 → M27`, plus the four parallel tracks: physics/numerics/process/system) **is** the real current code dependency graph at the milestone level. Use it directly; do not re-derive it.

### Next 3 — Define five minimal interfaces

Start with:

```text
PDE
Mesh
Residual
Jacobian
NonlinearSolver
```

### Next 4 — Wrap, don't rewrite

Put the existing solver behind those interfaces.

### Next 5 — Migrate Poisson first

Poisson is the cleanest proof that:

```text
Physics
≠
Discretization
≠
Solver
```

### Next 6 — Migrate one transport equation

Then prove the abstraction works for nonlinear semiconductor transport.

### Next 7 — Add architectural CI

Fail CI if forbidden dependencies appear.

### Next 8 — Run the PDE-IR/generic-FVM extraction as a track parallel to M23/M27, not a gate in front of them

Per §0.1: since 2D unstructured meshing/AMR (M21) and robust continuation (M22) are already done, and M23 (process geometry) and M27 (mixed-mode circuit) are the actual next milestones on the critical path with real user-facing payoff, do not block them on the PDE-IR extraction. Run the interface/PDE-IR work (Next 3–7) as a background track against the existing Poisson/transport code, and only require it as load-bearing once M26 (3D generalization) needs the generality — that is the point where the architecture starts paying for itself.

---

# 55. Final Principle

> **The goal is not to make TCAD-Dev abstract. The goal is to make TCAD-Dev extensible, scalable, verifiable, and fast without allowing abstraction to become the product.**

The product remains:

**a serious open-source TCAD simulator.**

The architecture is the mechanism that allows it to become one.
