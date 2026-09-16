# Semiconductor Workbench - Architecture Plan
==========================================================
Date: 2026-09-14 (compacted). Status summary: M1-M12 SHIPPED. Tier-1
parity (M13-M20) COMPLETE except M14's G-A (paywalled source). Tier-2
(M21-M26) COMPLETE to disclosed slice levels. Tier-3 (M27-M30 Part I)
LANDED; M30 Part II (GUI/product layer) LANDED 2026-09-09. M31 (C++/
PETSc engine) IN PROGRESS. M32-M50 (proposed post-M31 map) mostly
landed per the status table in 4c below. M41 (dimensional-lift track)
IN PROGRESS, M41/M16-S2 landed, M43 next.

This file is the LIVE roadmap + status record. For blow-by-blow
debugging narratives behind any "LANDED"/"COMPLETE" line, see that
milestone's own `pytcad/M*-PLAN.md` and `history.md` -- this file
states outcomes and open items, not session transcripts.

Long-term ambition: a learning + research TCAD environment matching,
and on select axes (see section 4e) beating, DEVSIM/Silvaco/Sentaurus
while staying open, modular, and understandable. Every educational
surface must be backed by actual computed physics.

Target flow:
  UI -> app -> core(Device)+physics(ModelConfig)
     -> solvers/backend -> results(RunResult + RunRecord)
     -> analysis(observables) -> UI

------------------------------------------------------------------------
1. ARCHITECTURE AUDIT (baseline, still accurate)
------------------------------------------------------------------------
| Area            | State                                                   |
|-----------------|---------------------------------------------------------|
| Numerical core  | Homegrown FD Poisson+drift-diffusion (pytcad/), SG      |
|                 | discretization, full Newton w/ analytic Jacobian, de    |
|                 | Mari scaling, warm-started sweeps; 1D/2D/3D classes.    |
|                 | Validated vs analytic benchmarks. Backend #1.           |
| Materials       | Semiconductor dataclass + free functions (Caughey-      |
|                 | Thomas/Canali mobility, Slotboom BGN, SRH/Auger, nie).  |
| Physics select  | Models dataclass = booleans; assembly inline in each    |
|                 | Device class.                                           |
| Process         | Pure-function 1D/2D chain (implant, diffusion, oxide,   |
|                 | TED, MC-implant) -- see M23-M26.                        |
| Device defn     | DeviceSpec JSON DTO (Qt-free, pytcad-free) built by     |
|                 | StructureModel.to_device_spec() or examples.py.         |
| Sweep system    | Generic warm-started sweeps; sweep_derived.py; M30's    |
|                 | splits/batch/study layer on top.                        |
| Results         | npz grammar v2/v3, structurally validated               |
|                 | (gui/services/solver_backend.py).                       |
| GUI             | QML panels -> controllers -> services -> QProcess       |
|                 | subprocess -> store -> Matplotlib-Agg / PyVista 3D.     |
| Tests           | ~1300+ passing incl. real-CLI conformance 1D/2D/3D.     |

------------------------------------------------------------------------
2. TARGET ARCHITECTURE (as realized)
------------------------------------------------------------------------
workbench/
  core/      DOMAIN: Device{Regions[], Contacts[], Gates}, Region,
             MaterialLibrary, ModelConfig, templates.
  physics/   MODEL REGISTRY: analysis-layer physics (tunneling,
             impact_ionization) with metadata/citations.
  solvers/   SolverBackend protocol + pytcad/devsim backends. Each
             backend emits RunResult + RunRecord. Subprocess isolation
             per run (UI-thread safety + OS-kill cancellation).
  results/   RunResult (v2/v3: point-cloud geometry + fields + series)
             + RunRecord (provenance: inputs, models+citations,
             convergence trace).
  analysis/  Observables: IV, CV, band_diagram, Vth, gm(Vg), Ion/Ioff,
             recombination/mobility maps. Backend-agnostic.
  app/       Controllers + services: thin orchestration only.
  ui/        QML views over core/analysis objects.

Placement rule: workbench/ lives beside pytcad/. The numerical core
is NEVER modified except to expose values it already computes, or via
the explicit frozen-core amendment mechanism (CLAUDE.md).

------------------------------------------------------------------------
3. M1-M12 -- SHIPPED FOUNDATION (compact record)
------------------------------------------------------------------------
M1 Domain core + model catalog. M2 RunRecord + result schema v2.
M3 ResultStore/analysis boundary + SolverBackend protocol. M4 Physics
Lab foundation (catalog panel, provenance view). M5 Device Builder
(pn diode/NMOS/MOS-C templates). M6 Process Builder (1D, per-region
implants). M7 DEVSIM backend (equilibrium slice, opt-in). M8 first new
physics beyond the original five models. M9 educational physics lab
(model on/off comparisons). M10 deck/workflow translation layer.
All SHIPPED; each proved behavioral equivalence or added independently
validated capability, adversarial-probed before ship.

M11 HETEROSTRUCTURES -- ALL SHIPPED (S1-S5): Ge/GaAs/InGaAs/AlGaAs
materials; DeviceSpec.region_materials wire format; Device1D eps(x)
flux-form Poisson + Anderson band offsets via CARRIER-SPECIFIC ln(nie)
edge deltas (electron dpsi + dln(nie), hole dpsi - dln(nie) -- a
shared delta passes FD-Jacobian but breaks hole detailed balance);
Device2D box-integration equivalent; HBT/HEMT templates + UI.

M12 TUNNELING & QUANTUM CORRECTIONS -- ALL SHIPPED (S1-S3): FN/WKB
analysis module (workbench/physics/tunneling.py); Hurkx TAT in
Device1D (SI-calibrated fields -- V/cm underflows silently); S3
(density gradient) folded into M20 (COMPLETE, see below).

------------------------------------------------------------------------
4. SENTAURUS-PARITY ROADMAP (M13-M30) -- STATUS
------------------------------------------------------------------------
Three parity tiers: TIER 1 "SDevice local-physics parity, Si 1D/2D"
(statistics, mobility, II, BTBT, transient, AC, self-heating, DG).
TIER 2 "SProcess-lite + general geometry" (unstructured meshing,
mask-driven process, TED/OED, 3D iterative solvers). TIER 3
"System-level" (mixed-mode circuit, hydrodynamic, MC implant,
calibration).

Deliberately OUT OF SCOPE, permanently: Monte-Carlo Boltzmann
transport, atomistic kinetic-MC diffusion, radiation/SEE,
ferroelectric/phase-change materials, full viscoelastic oxidation
mechanics, Maxwell/EM solvers, PDK-grade compact-model extraction,
bit-identity with commercial tools, any performance claim without the
section-36 benchmark table.

STANDING ENGINEERING RULES (unchanged, still binding):
1. Any milestone touching a device core uses the M11-S3 amendment
   mechanism: explicit sign-off, FD-Jacobian-first, bit-identity with
   the model off, acceptance tests before merge.
2. Every new model lands in tests/test_model_benchmarks.py FIRST with
   published constants; the benchmark error is quoted in the commit.
3. GATE BLOCKING: a milestone with quantitative acceptance gates blocks
   its declared dependents until every gate is green under the
   full-suite invariant. "Mostly green" is not green -- M15 was once
   declared complete while two of its own gates were unreachable
   (M15-IONIZATION-PLAN.md's debug-pass record is the cautionary case).
4. New meshes/linear solvers ship with golden parity tests against
   existing validated paths before anything uses them.
5. Optional dependencies stay optional, auto-detected, graceful refusal.
6. Result schema changes are additive + versioned.
7. Honesty clauses are mandatory: what is NOT modeled, where it breaks,
   which gates are qualitative.
8. GUI grows only along validated data paths; no plot without a
   store a test validates.

STATUS BY MILESTONE (live -- supersedes any per-milestone spec text):

  M13 Fermi-Dirac + incomplete ionization   COMPLETE (G1-G8 green,
      1D/2D/3D). Incomplete ionization lifted to structured 2D/3D by
      M41 (2026-09-12).
  M14 Surface/inversion mobility            MOSTLY COMPLETE: CVT
      mobility, D_it (moscap C-V stretch-out), S_n/S_p surface
      recombination (Device1D + Device2D, Robin BC), catalog entry all
      landed. G-A (absolute mobility vs Takagi/Taur, needs the 1988
      Lombardi paper's two-part doping-dependent phonon term) remains
      OPEN -- blocked on a paywalled primary source with no
      open-access copy found (re-searched 2026-08-31, no new result).
      driving_force descoped (no 2D/3D consumer). Known limitation:
      Newton convergence for a deep minority-carrier contact under
      reverse bias in 2D can be non-monotonic (root cause narrowed to
      a 2D-specific lateral-coupling term, not fixed). See
      pytcad/M14-SURFACE-MOBILITY-PLAN.md.
  M15 Impact ionization coupling            COMPLETE, all gates green.
      Coupled generation term in the Newton Jacobian; arc-length
      continuation with a strength-ladder-aware corrector traces
      through the avalanche fold. Found and fixed a real literature
      bug (hole/electron field switch point wrongly shared at
      5e5 V/cm vs hole's own 4e5 V/cm, pytcad/ionization.py). G-C's
      tolerance was explicitly loosened ([0.5,2.0]->[0.15,2.0]) and
      G-D's second test doping changed (1e17->2e16 cm^-3) with
      evidence that the local-field approximation's own calibrated
      range, not a code defect, explains the residual gap -- see
      M15-IONIZATION-PLAN.md.
  M16 Band-to-band tunneling (local Kane)   LANDED, VERIFIED. Live
      Jacobian coupling in Device1D; gates were unrun for two days and
      2/13 failed on verification -- all three were TEST bugs (sort
      direction, sign error, an unwinnable correlation-sign check),
      not physics; all 13 pass now. M16-S2 (2026-09-13) ported the
      same model to structured Device2D/Device3D (pytcad/btbt_grid.py),
      closing the last local-BTBT dimensional gap.
  M17 Transient simulation                  PHASES 1-3 COMPLETE:
      1D/2D backward-Euler/theta-scheme cores (pytcad/transient.py,
      transient2d.py) as sibling modules (device.py/device2d.py
      untouched); GUI Transient tab, schema v2->v3. GateBC waveforms,
      transient-config persistence, per-step field snapshots remain
      out of scope.
  M18 Small-signal AC                       PHASES 1-4 + 3b COMPLETE:
      pytcad/ac.py (Device1D one-port, then N-terminal Y-params + fT),
      pytcad/ac2d.py (Device2D N-terminal incl. gate ports, then
      4-terminal mosfet_2d fT crossing), ACPanel.qml GUI exposure.
      Device3D AC and fmax (Mason's U(f)) not started -- see 4c.4 on
      revisiting the "permanently out of scope" call on Device3D AC.
  M19 Self-heating                          PHASE 1 (1D steady-state)
      LANDED: outer isothermal-DD + Gummel thermal loop (not a
      monolithic psi/n/p/T Newton system -- Device1D's whole scaling
      is built from one scalar T). Correct Joule term is the
      quasi-Fermi-potential-gradient dissipation (Wachutka 1990), not
      naive J*E (which gives thermodynamically impossible negative
      heat in a diffusion-dominated depletion region). Added
      Semiconductor.kappa_th300/kappa_th(T). 2D, transient,
      Seebeck/Peltier not started.
  M20 Density-gradient quantum correction   COMPLETE, all gates green.
      Coupled-Newton (psi, Lambda_n, Lambda_p) solve (replaced an
      earlier lagged fixed point that converged to the wrong physics).
      MOSCapacitor gets a hard-wall interface BC at the oxide (fixed a
      genuine wrong-sign near-surface Lambda bug); Device1D keeps
      Neumann (ohmic contacts, no oxide interface). Equilibrium-only;
      DG transport and 2D/3D DG are M42.
  M21 General 2D/3D meshing + FV assembly   ALL PHASES COMPLETE:
      phase 1 (1D h-refinement), phase 2 (2D/3D separable refinement),
      phase 3 (gmsh-based unstructured 2D FV assembly: geometry (3a),
      Poisson equilibrium (3b), coupled SG bias solve (3c),
      Device2D(unstructured=True) thin-wrapper integration (3d)).
      Mesher decision: gmsh (see 4b.6 below). Honest gap: golden
      parity vs the structured solver measured ~5-6%, not the
      original <1e-4 target (different mobility model config, not a
      residual bug). 3D unstructured DD (unstructured_dd3d.py) is
      homojunction-only -- no heterojunction gauge exists there (see
      M47).
  M22 Linear solver + continuation          PHASE 1 (Krylov/ILU/
      node-block-Jacobi) closed the >=64k-node 3D scaling gate (68921
      nodes / 206763 unknowns in 4.71s). Found and fixed a bit-identity
      bug: solve_linear(method="direct") reformatted CSR->CSC before
      spsolve, which is NOT bit-identical for scipy's SuperLU wrapper.
      PHASE 2 continuation driver (adaptive_bias_sweep, arc_length_
      sweep) unblocked M15's avalanche-fold gates. A Schur-complement
      preconditioner variant landed as opt-in (default unchanged).
      PHASE 3 landed as MPI Schwarz domain decomposition (not the
      originally-scoped distributed-matrix design) -- picks whichever
      mesh axis (x/y/z) is safe to split along per device (doping
      gradient AND any registered GateBC's normal_axis both checked,
      after a real silent-wrong-answer regression on a gated 3D device
      was found and fixed). Also: pyamg AMG for GUI 3D equilibrium
      (8x-44x) and CUDA/cuSOLVER direct solve for bias/sweep (2.8x),
      both opt-in and size-gated.
  M23 2D process geometry engine            STRUCTURED-MESH SLICE
      COMPLETE: pytcad/process2d.py -- mask-driven deposit/etch, 2D
      Deal-Grove oxidation with qualitative (not quantitatively
      validated) bird's-beak encroachment, mask-driven 2D implants.
      General-mesh (post-M21) version is future work.
  M24 Pair diffusion/segregation/clustering  LUMPED-MODEL SLICE
      COMPLETE: pytcad/ted.py -- Fair extrinsic enhancement, "+1" TED
      supersaturation, OED boost, equilibrium segregation partition,
      solubility-limited clustering. A lumped-scalar engineering
      model, NOT a coupled point-defect PDE.
  M25 Monte-Carlo implantation (BCA)         SIMPLIFIED-BCA SLICE
      COMPLETE: pytcad/mc_implant.py -- screened-Rutherford nuclear
      scattering + a calibrated (not literal ZBL) LSS electronic-
      stopping prefactor. Amorphous-target range matches the existing
      SRIM table to ~+-35%; channeling is a disclosed phenomenological
      knob, not a lattice simulation.
  M26 3D generalization                      TWO PASSES LANDED:
      (1) structured-mesh tri-gate FinFET (pytcad/finfet3d.py) +
      characterization.py (Vth/SS/DIBL) with a literature-trend gate;
      (2) unstructured tet path gained a Robin/oxide-coupling gate BC
      and a process2d-to-3D-tet extrusion pipeline
      (pytcad/gmsh_finfet3d.py) -- building the gate BC found and
      fixed a pre-existing interior-flux scaling bug. Disclosed gaps:
      doping extrusion is per-region-constant (no true 2D-implant-
      array extrusion); extruded-tet bias solve needs continuation not
      yet implemented there; tet AMR at FinFET scale lightly validated
      only.
  M27 Mixed-mode device + circuit            DONE: pytcad/circuit.py --
      MNA solver (V/I sources, R, C, diode, level-1 Shichman-Hodges
      MOSFET) + DeviceStamp embedding a real Device1D via a
      FINITE-DIFFERENCE terminal conductance (not literally reusing
      the analytic Jacobian). transient() is backward-Euler only; a
      DeviceStamp inside a transient circuit is solved quasi-statically
      per step (no device-internal capacitive coupling).
  M28 Schottky/tunnel contacts + gate stacks STANDALONE-MODULE SLICE
      COMPLETE: pytcad/schottky.py -- thermionic emission + Richardson
      constants, image-force lowering, Padovani-Stratton field-
      emission/tunnel-contact classification, ohmic-limit recovery.
      NOT wired into any device Newton core as a BC (see M46).
  M29 Hydrodynamic/energy balance            DONE as a disclosed
      simplification, not the full self-consistent transport solve
      originally scoped: pytcad/hydrodynamic.py is a standalone LOCAL
      (no spatial energy-flux) steady closure -- carrier temperature
      from a published relaxation time, the length scale
      l_w=v_sat*tau_w (~0.04um for Si), a qualitative field-heating
      trend, and carrier-T-driven II via the existing M15 coefficients.
      NOT wired into Device1D's residual/Jacobian (pure post-
      processing) -- a genuine spatial-overshoot-profile match needs
      the div(S) energy-flux term this module omits (see M44).
  M30 Workbench system features + interop    Part I LANDED
      (workbench/splits.py, calibration.py, batch.py,
      deckbuild_import.py -- parameter splits, Nelder-Mead calibration,
      batch parallelism, DeckBuild-dialect import). Part II (GUI/
      product layer: Study Manager, Sweep Matrix Viewer, Run
      Comparison, manifest resume, provenance, parameter constraints,
      adaptive sweep, SSH remote execution + GUI wiring) LANDED
      2026-09-09, all 12 phases -- workbench/study_manifest.py,
      adaptive_sweep.py, constraints.py, remote_executor.py,
      gui/services/remote_job_runner.py, gui/qml/panels/StudyPanel.qml.

4a. GAP ANALYSIS SNAPSHOT (drafted pre-M13; kept for what motivated the
roadmap -- the status table above is the live record, not this list):
Fermi-Dirac/incomplete ionization, surface mobility, coupled II, BTBT,
TAT, self-heating, transient, AC, DG, 2D heterojunctions were all
[partial]/[missing] when drafted; all now landed to the tier-1 scope
above except M14 G-A. Process (implant/diffusion/oxidation/deposition-
etch), unstructured meshing, adaptive refinement, 3D scale, mixed-mode
circuit, calibration/splits were all [partial]/[missing]; all landed to
the tier-2/3 scope above.

4b.6 GEOMETRY FOUNDATION DECISION (M21 phase 3's mesher): gmsh, not raw
OpenCASCADE/pythonocc-core or FreeCAD. gmsh is the one open project
bundling an OCC-based CAD kernel, unstructured 2D/3D meshing, and
Physical-Group region tagging in one Python-importable package;
DEVSIM already documents importing gmsh meshes directly. Validated,
not merely decided: examples/debug_geometry_gmsh_conformality.py
confirms a gmsh-built p-n diode mesh is CONFORMAL across the material
interface (shared node tags exactly at the junction, region areas
match analytic to 1e-16, zero degenerate triangles) -- what box-
integration FV assembly requires. A hard-debug finding: an ungrounded
gmsh size field over-refined a device to 21344 nodes; regrounding it
in pytcad.mesh.debye_length (the same quantity phase 1's own h/L_D
constraint uses) cut this to ~2100 nodes. Full record:
M21-MESHING-PLAN.md section 12. A 3D repeat of the conformality check
remains undone (3D unstructured meshing is out of Phase 3's scope).

------------------------------------------------------------------------
5. POST-M31 ROADMAP (M31-M50)
------------------------------------------------------------------------
STATUS OF THIS SECTION: M31 is REAL (planned, gated, in progress, own
plan doc). M32-M50 is a PROPOSED map grounded in this repo's own
disclosed gaps (4b.1, each M*-PLAN.md's honest-limits section,
Architecture_Master_Plan.md sections 34/35) -- nothing below is
committed until it has its own plan doc and gates.

5.1 M31 -- C++/PYTHON/QT PRODUCTION ARCHITECTURE  [XL, IN PROGRESS]
Full spec: pytcad/M31-CPP-ARCHITECTURE-PLAN.md. Progressive extraction
(Architecture_Master_Plan.md section 37) -- NOT a rewrite.

  P0  build system + CI + C++/Python boundary          LANDED
  P1  de-couple device.py; two latent bugs fixed        LANDED
  P2  mesh/geom kernels -- the measured blocker          LANDED
  P3a linsolve method="petsc" via petsc4py (no C++)     LANDED
  P3b same configuration moved into core/solver/         LANDED
  P4  process/particle kernels (MC implant, TED, AMR)    LANDED
  P5  assembly + Newton in C++                    STOPPED after P5-0
  P5-1 solver-selection tuning (Phase A, A-2)            LANDED
  P6  native QQuickVTKItem 3D viewport                NOT STARTED
  P7  MPI + GPU via PETSc; DMPlex                     NOT STARTED
  P8  Qt shell hardening                              NOT STARTED
  P9  promote pytcad_cpp to default                   N/A (no P5)

THE MEASUREMENT THAT ORDERED THESE PHASES -- do not re-derive it:
structured 3D assembly is NOT the bottleneck (a 24^3 equilibrium solve
spends 98% of wall time in _superlu.gssv; assembly is 0.011s of
0.494s); the pure-Python node-block-Jacobi GMRES already does 68,921
nodes in 4.71s, so the direct-LU wall is ALGORITHMIC, not linguistic.
The genuine blocker was unstructured mesh geometry (~80k tri/s 2D,
~3.5k tets/s 3D -- minutes of Python dict overhead before any physics
ran); P2 closed it to 3.16M tri/s / 1.99M tets/s, bit-identical.

P5 STOPPED after P5-0: P5-1's Phase A-2 measured all 8 solver-
selection cells (the discriminator is COUPLING, not dimension --
largest win: 3D structured coupled bias, 44.56s -> 1.60s, 27.9x, via
petsc/direct auto-selection, no default moved). P5 proper's own exit
criterion then fired: B9's assembly SHARE rose 11x (1.5%->16.3%) but
its ABSOLUTE cost did not move (~109ms) against an ongoing second-
engine maintenance cost -- see M31-P5-ASSEMBLY-NEWTON-PLAN.md section
12. P6/P7 are NOT blocked on a C++ assembler that will not exist --
re-scope against the Python+PETSc stack P5-0/P5-1 actually built.

OPEN DECISION carried out of P2: build_unstructured_stencil is
winding-sensitive (a clockwise-wound triangle contributes NEGATIVE
dual-cell areas); gmsh emits CCW so no real caller hits it, but the
compiled path faithfully reproduces the quirk and it is PINNED by a
test rather than papered over. Fixing it changes physics and must
land on both paths (Python oracle + C++) at once.

ADJOINT NOTE (relevant to M47 below): P5's stopping means the
"expose dR/dp, keep J^T-friendly assembly" gate this section originally
wanted on the C++ assembler never had an assembler to apply to. The
Dirichlet-transpose half of that gate was instead closed on the PYTHON
path (P4b: symmetric row-AND-column elimination in dirichlet.py). M47
should depend on P4b's fix, not on a P5 that stopped.

5.2 PROPOSED M32-M40 (each row names the 4b.1/plan-doc gap it retires)

  M32  Benchmark suite & performance dashboard    [M]   LANDED
       pytcad/benchmarks/ (cases B1-B7), `python -m benchmarks`,
       gated (test_m32_benchmarks.py), checked-in benchmarks/BASELINE.md.
       Satisfies section 36's "no HPC claim without a table" rule.
       Three dashboard columns (residual/Jacobian split, Newton
       iteration count, true memory) are deliberately NOT reported --
       cannot be measured honestly from outside the frozen core.
  M33  Surface/interface physics completion       [L]   FULLY LANDED
       (S1-S5): chi-aware band alignment + thermionic emission in
       Device1D, ported to Device2D, Device3D, and unstructured_dd.py.
       Retires the surface-recombination/D_it/thermionic-interface
       [missing] rows. unstructured_dd.py's non-equilibrium-slaved
       formulation makes an isotype junction's terminal current
       PROVABLY gauge-invariant (an exact identity, confirmed).
  M34  Nonlocal tunneling & ionization (Tier 3)   [L]   LANDED
       Nonlocal path Kane BTBT (Esseni 2017 eq 11 WKB quadrature,
       pytcad/nonlocal_path.py, compiled tracer core/src/nonlocal/
       paths.cpp) in Device1D and structured Device2D/Device3D through
       one engine. Nonlocal effective-field II (pytcad/ii_nonlocal.py,
       Slotboom 1991) in Device1D, then lifted to structured 2D/3D
       (pytcad/ii_nonlocal_grid.py, one sparse-LU factor-solve for
       E_eff + its Jacobian -- replaced two naive-Python performance
       traps: a per-line loop, vectorized; a per-node dict-DP walk,
       recognized as one sparse triangular solve). Local coupled II
       also lifted to structured 2D/3D (pytcad/ii_grid.py), closing
       4d.1's local-II gap. A convergence bug shared by all three
       stiff paths (impact, btbt, btbt_nonlocal) -- judging Newton
       convergence on the line-search-DAMPED update instead of the
       full correction -- was found and fixed in all three devices;
       this was M15's long-open G-C gap (M_sim/M_int measured 0.76,
       inside its tolerance band). Out of scope: unstructured meshes,
       heterojunctions, phonon-assisted BTBT, energy-resolved channels.
  M35  3D process simulation                      [XL]  NOT STARTED
       Still missing: 2D moving-boundary oxidation (LOCOS/STI bird's
       beak proper), deposition/etch topology engine, masks,
       silicidation, epitaxy, CMP, none of it in 3D. The single
       biggest remaining parity gap; needs a real topology/level-set
       engine. Depends: M31 P2 (landed).
  M36  Stress/strain coupling                     [L]   NOT STARTED
       Depends: M31 P5 (stopped -- re-scope against Python+PETSc).
  M37  Reliability & trap dynamics (BTI/HCI/TDDB) [L]   NOT STARTED
       Depends: M33 (landed), M17 (landed).
  M38  TCAD-to-SPICE compact model extraction     [M]   ALL 4 PHASES
       LANDED: workbench/compact.py fits circuit.py's Diode/MOSFET1,
       emits a real SPICE .MODEL card, reads it back, closes the loop
       through circuit.Circuit's MNA solver -- no external SPICE.
       Measured: pn diode N=1.0031; 2D MOSFET fit 2.90% relative RMS,
       Vt0 within 0.91% of closed-form. Phase 4: compact_runner.py +
       "Compact Model" GUI tab + workflow.py's parse-only `EXTRACT`
       deck statement (not yet wired into batch execution). NOT done:
       BSIM-class models, temperature/geometry scaling, AC/C-V
       extraction, PMOS in the GUI panel.
  M39  Quantum transport (NEGF, 1D)                [XL]  NOT STARTED
       DG/Schrodinger-Poisson are equilibrium-only; NEGF is the
       honest way to do quantum TRANSPORT. Depends: M31 P5 (stopped,
       re-scope), M32 (landed).
  M40  Optical generation / photonics              [L]   NOT STARTED
       Opens solar/photodetector/imager devices. No C++ dependency
       beyond meshing.

Suggested order: M31 P3a -> M32 -> P4..P7 -> M35 (spine). Parallel
tracks: physics M33->M37; system M30-Part-II(landed)->M38(landed);
optics M40 standalone. C++-gated: M34 (needs P4, has it), M35 (needs
P2, has it); M36/M39 (needed P5, which stopped -- re-scope first).
M32 sits deliberately inside the M31 track, not after it, because P7's
scaling claims need the dashboard to police them (section 36).

WHAT IS PERMANENTLY OUT OF SCOPE (stated so it is never rediscovered
as a "gap"): p-/r-refinement (node motion, M21's own exclusion);
bit-identity with commercial tools. Device3D AC's "permanently out of
scope" call is DEMOTED to a deferral to re-cost (see M45) -- it was
made when 3D died at ~27k nodes, and M31 removes that constraint.

5.3 THE ROAD TO 3D -- DIMENSIONAL-LIFT MILESTONES (M41-M47)

Organized by DIMENSION rather than capability: the DD spine (drift-
diffusion, Fermi-Dirac, coupled/nonlocal II, local/nonlocal BTBT, TAT,
AMR, mixed-mode) already reaches 3D on both structured and
unstructured meshes -- M31 is about making 3D FAST, not making it
exist. The debt is concentrated in physics added AFTER the DD core
(quantum corrections, self-heating, hydrodynamic, transient, AC),
each of which stopped at 1D/2D under a defensible "1D first" call that
nobody has since revisited. Process simulation is the widest gap
(3D device physics vs. 2D-at-best/1D-for-TED process input).

COVERAGE MATRIX (Y = works, - = absent; verified against imports/
NotImplementedError sites, not inferred from filenames):

  capability                       1D    2D    3D    gap owner
  --------------------------------------------------------------------
  Drift-diffusion, structured       Y     Y     Y    --
  Drift-diffusion, unstructured     -     Y     Y    -- (1D moot)
  Fermi-Dirac / incomplete ion.     Y     Y     Y    --
  Impact ionization (coupled)       Y     Y     Y    --
  Impact ionization, nonlocal       Y     Y     Y    --
  BTBT, local Kane / nonlocal       Y     Y     Y    --
  Trap-assisted tunneling           Y     Y     Y    --
  Density gradient / quantum        Y     S1    -    M42
  Self-heating (lattice T)          Y     -     -    M43
  Hydrodynamic / energy balance     Y*    -     -    M44
  Transient / small-signal AC       Y     Y     -    M45
  Adaptive refinement               Y     Y     Y    --
  Process: implant/diffuse/oxide    Y     Y     -    M35
  Process: TED, MC implant          Y     -     -    M35
  Mixed-mode circuit                Y     Y     Y    --
  Schottky / tunnel contacts        Y*    -     -    M46

  Y* = standalone/analysis module, NOT coupled into any device Newton
       core (hydrodynamic.py, schottky.py -- imported by __init__.py
       and nothing else).

RULE: no dimensional lift lands without its reduction identity as a
gate -- a 3D implementation whose z-uniform case does not reproduce
the validated 2D answer to floating-point noise is a second,
unvalidated code path, not a 3D implementation (the existing
examples/05_3d_reduces_to_2d.py pattern, 1.11e-16 V measured).

  M41  Incomplete ionization -> 2D/3D         [S]   LANDED 2026-09-12
       A port, not new physics: M13's shallow-dopant model factored to
       module level (ionized_doping/ionized_eta_doping/ionized_dE_kt
       in device.py) and reused by all three devices; Device1D's own
       arithmetic unchanged (verified against all six m13 golden md5s).
       Two findings: (a) equilibrium and coupled Poisson blocks need
       DIFFERENT chain rules and separate FD-Jacobian gates -- a
       mutation test confirmed the equilibrium one catches a dropped
       chain (0.52 vs a 5e-5 threshold) that the convergence gates
       alone would miss; (b) band_offset='affinity'+incomplete_ion
       stays refused in 2D/3D as in 1D (same double ln(Nc/nie) offset
       hazard). Unstructured Device2D still refuses the flag (no
       ionization mechanism in unstructured_dd.py at all).
       M16-S2 (local Kane BTBT -> structured 2D/3D, pytcad/
       btbt_grid.py) landed the same week, closing 4d.1's other
       remaining local/nonlocal-BTBT inversion (see M16 above).
  M42  Density gradient / quantum -> 2D/3D    [L]   S1 LANDED 2026-09-17,
       S2/S3/S4 NOT STARTED. Prerequisite for any credible FinFET/GAA
       confinement claim -- S1 alone does NOT satisfy that: it is
       Device2D, OHMIC CONTACTS ONLY, any GateBC refused loudly (the
       plan's own S2, the Lambda boundary condition at a gate/oxide
       interface, is an open physics question S1 deliberately does not
       answer -- M42-DENSITY-GRADIENT-2D3D-PLAN.md section 0.2). Ported
       Device1D's coupled-Newton (psi, Lambda_n, Lambda_p) equilibrium
       formulation one dimension up, reusing Device2D's own box-
       integration flux-divergence pattern (harmonic-mean edges, per-
       node control volumes) for the Lambda Laplacian instead of a bare
       finite-difference stencil -- reduces EXACTLY to Device1D's own
       formula in the 1D limit (a transversely-uniform 2D device
       matches Device1D to floating-point noise: max|dpsi|=1.8e-15).
       10 gates in tests/test_m42_s1_density_gradient_2d.py, all green;
       all six m13 golden md5s unchanged (dg=False path untouched).
       Depends: M31 P5 (stopped -- re-scope) turned out NOT to be
       load-bearing, same correction the plan's own section 0.1 already
       made -- this landed as a pure-Python/numpy assembly job with no
       C++ involvement.
  M43  Self-heating -> 2D/3D                  [L]   PHASES 1+2+3 (2D, 3D,
       C++ ACCEL) LANDED 2026-09-16.
       thermal.py's structured assembly has the one non-vectorized
       scalar Python loop in the tree -- pairs naturally with M31 P4.
       Phase 1 (2D): new sibling module pytcad/thermal2d.py (device2d.py
       untouched, zero frozen-core edits there), same outer-Gummel-loop
       architecture M19 chose in 1D (Device2D shares Device1D's exact
       scalar-T-at-__init__ scaling, so the "monolithic coupling is a
       disproportionate rewrite" reasoning transfers unchanged). One
       small additive amendment to thermal.py itself: ThermalBC.
       adiabatic() (zero-flux BC), needed for the reduction-identity
       gate; all 6 pre-existing M19 gates re-verified green afterward.
       New vectorized (no Python loop, unlike the 1D module) 2D FV
       heat-equation Newton solve + a 2D Joule-heating formula (same
       Wachutka 1990 term as 1D, box-integrated with device2d.py's own
       dVy/dVx flux-divergence convention). 4 gates in
       tests/test_m43_thermal2d.py: FD-Jacobian (caught a real sign-
       convention bug in the edge-to-node Jacobian scatter before any
       other gate ran -- relative error 2.0, i.e. exactly backwards),
       a Robin-vs-Dirichlet BC peak-ordering check, an off-bit-identity
       check, and the load-bearing one per 4d.4's rule ("no dimensional
       lift lands without its reduction identity as a gate"): a
       y-uniform 2D diode with adiabatic transverse boundaries
       reproduces thermal.py's own 1D solve_electrothermal end to end
       (temperature profile and current roll-off ratio both match).
       Phase 2 (3D, same session, on request to "generalize it to 3D"):
       rather than hand-duplicating phase 1's per-axis stencil a third
       time, the residual/Jacobian assembly was factored into a
       genuinely dimension-generic core, pytcad/thermal_grid.py's
       _residual_jacobian_grid(coords, T, H, material, T_ambient, bcs)
       (D=2 or 3, one axis loop) -- mirrors ii_grid.py/btbt_grid.py's
       "one kernel for Device2D and Device3D" pattern (M34-S6).
       thermal2d.py's own assembly functions became thin wrappers over
       this core (phase 1's 4 gates re-run green, unchanged, immediately
       after that refactor -- before any 3D code was written); new
       pytcad/thermal3d.py wraps the same core for Device3D, with only
       joule_heating_density_3d genuinely new (reads Jn_x/Jn_y/Jn_z,
       device3d.py's own dVy*dVz/dVx*dVz/dVx*dVy cross-section
       convention, device3d.py:993-998). 4 more gates in
       tests/test_m43_thermal3d.py, mirroring phase 1's set at D=3 --
       G-FD-3D passed on the FIRST run (no repeat of phase 1's sign
       bug; parameterizing one axis loop instead of hand-writing a
       third block is what avoided it), and G-REDUCTION-3D is a genuine
       two-level chain (a z-uniform 3D diode with adiabatic front/back
       reproduces thermal2d.py's own 2D solve, which itself already
       reduces to 1D). Phase 3 (same session, on request to "use cpp
       not python"): no C++ compiler existed on this machine (only
       cmake/ninja were present) -- confirmed directly (a trivial
       <optional> compile failed), not assumed, and surfaced to the
       user before writing anything, per the house rule against
       claiming a compiled-kernel gate without running it. User chose
       to install one; a conda-forge GCC 16.2 toolchain (gxx) was
       installed into the tcad-dev env (a durable environment change --
       a `cxx-compiler` meta-package was tried first but activates
       MSVC via a Visual Studio install with no C++ workload, so it was
       removed in favor of plain gxx as a real MinGW-w64 compiler).
       The PRE-EXISTING C++ engine was rebuilt and its own accel-parity
       suite re-confirmed green FIRST (69 passed/8 skipped), before
       trusting the new toolchain with anything new. Ported: thermal_
       grid.py's _residual_jacobian_grid (the D=2-or-3-generic assembly
       phase 2 built) -> core/src/thermal/grid.cpp, following M31 P4's
       exact pattern (Python body kept as the oracle, renamed _py; the
       one transcendental -- kappa_th's power law -- evaluated once in
       Python and its result crosses as plain arrays, so the kernel
       itself is pure arithmetic). The genuinely hard part was NOT the
       arithmetic but floating-point ASSOCIATION ORDER: the reference
       builds each axis's contribution in two separate passes (lo
       scatter, then hi scatter, then add to F once) and appends the
       Jacobian's 4 COO groups per axis as 4 SEPARATE full passes (not
       interleaved per-edge), because scipy.sparse.csr_matrix sums
       duplicate (row,col) entries in insertion order and an interior
       diagonal is touched by two different edges of the same axis --
       an interleaved single-pass version would have been mathematically
       equivalent but NOT bit-identical ((a-b)+c != a+(c-b) in IEEE
       754), caught by reasoning before ever compiling, not by a
       failing gate. Result: bit-identical on the first successful
       build+test cycle -- direct kernel-level F/Jacobian parity (2D
       and 3D, mixing all 3 BC kinds at one corner) plus two full
       end-to-end solve_electrothermal_{2,3}d runs (ACCEL=0 vs 1,
       comparing the converged T after the whole outer Gummel loop),
       tests/test_m43_thermal_grid_accel_parity.py, 4/4 green. **Stale
       as a description of the test file's CURRENT form, corrected
       2026-09-17**: M43 phase 4 (same day, later in this same entry
       below) removed the pure-Python oracle this ACCEL=0-vs-1 parity
       check compared against -- the test file's own docstring now
       says it checks reproducibility (same input twice, bit-identical
       output) on the sole remaining compiled path, not cross-path
       parity. Left in place as the historical record of what phase 3
       itself verified at landing time, not edited to pretend it always
       read this way. Only the
       per-iteration assembly is compiled -- both Newton loops and the
       outer Gummel loop stay in Python, matching diffuse_numeric's own
       precedent of dispatching the repeated inner operation only. No
       performance number is claimed (correctness, not speed, is this
       phase's claim; no benchmarks/ run was done). See
       M43-SELFHEATING-2D3D-PLAN.md for the full record. Deferred,
       all three phases: GUI wiring (library-only, matching M18 AC
       phase 1's scope note), monolithic coupling, recombination/
       generation heat, Seebeck/Peltier, and any 3D performance claim
       at scale -- a larger-grid (~8600 node) sanity run was attempted
       but did not finish within the session (Device3D's own
       unmodified electrical solve, not this milestone's code, is
       simply slow there via a direct sparse solve); the small-grid
       gates are the confirmed 3D evidence, no larger-scale number is
       claimed.
  M44  Hydrodynamic -> coupled, then 2D/3D    [XL]  NOT STARTED
       Two steps: hydrodynamic.py must first become a coupled 1D
       model (it is pure post-processing today) before any
       dimensional lift is meaningful -- overshoot is a 3D
       short-channel effect that a 1D-only closure cannot show.
  M45  Transient and AC -> 3D                 [XL]  NOT STARTED
       transient2d.py/ac2d.py exist, no 3D form of either. Device3D
       AC's "permanently out of scope" call should be REVISITED, not
       inherited -- it predates M31's 3D-scale fix; a 3D AC solve is a
       factorize-once-per-frequency op on a Jacobian PETSc already
       factorizes. Depends: M31 P3b/P7.
  M46  Schottky/tunnel contacts -> coupled, then 2D/3D  [L]  NOT STARTED
       Same shape as M44: couple schottky.py into a device core first,
       then lift dimensionally.
  M47  3D numerical engine completion         [XL]  PROPOSED, NOT
       SCOPED, NOT SIGNED OFF. Distinct from M41-M46: this is the
       ENGINE work underneath all of them. Two concrete gaps found by
       direct inspection: (a) M31's C++ coverage stops short of 3D
       residual/Jacobian assembly (device3d.py/unstructured_dd3d.py
       assembly is still pure Python/numpy -- see CLAUDE.md "What is
       compiled so far"); (b) unstructured_dd3d.py is explicitly
       homojunction-only (no materials_per_node/dlnnie mechanism) --
       adding one is genuine new-feature work needing its own plan,
       not a port. Expected difficulties: the frozen-core amendment
       protocol applies to every touch of device3d.py/
       unstructured_dd3d.py; 3D's edge/GateBC normal_axis combinatorics
       are a real step up from 2D; 3D test batteries are already the
       suite's slowest part. Depends on/overlaps M31 P4 (landed) and
       M35 (its own track). Needs a proper plan doc before any code.

ORDERING: M41[S](done) -> M43[L](done) -> M42[L](S1 done, S2 next) ->
M46[L] -> M45[XL] -> M44[XL], with M35 (3D process) and M47 (engine
completion, last deliberately -- more to learn by landing a few of
M41-M46 first) as separate tracks.

------------------------------------------------------------------------
6. COMPETITIVE STRATEGY -- BEATING SENTAURUS/ATLAS, NOT JUST MATCHING
------------------------------------------------------------------------
4b.0's framing: literal feature parity with a 30-person-decade
incumbent is a fantasy; beat it on axes where its ARCHITECTURE, not
its effort, prevents it from competing.

WHERE WE CAN GENUINELY WIN (structural, not effort-based):
  W1  Differentiable simulation / adjoint sensitivities -- THE
      differentiator. Neither incumbent can give dJ/dp without a
      rewrite. Enables gradient-based device optimization,
      O(1)-per-iteration calibration instead of O(n_params) FD solves,
      UQ/sensitivity ranking, and gradients for ML surrogates.
  W2  Modern parallel numerics -- PETSc gives MPI+CUDA+AMG as
      configuration, not a project; mostly already scheduled (M31 P7).
  W3  Reproducibility/provenance -- study manifests + RunRecord
      already stamp git commits; "any published figure regenerates
      bit-identically" is cheap because most of it is built.
  W4  Inspectable, cited physics -- every model carries its published
      reference + honest-limits statement; incumbents are black boxes.
  W5  Python-native extensibility -- a new model is a Python function
      (+ optional C++ kernel with a bit-identity gate), not a C-ABI
      PMI recompile.
  W6  Cost and access -- zero licence cost, no seat limits, runs in CI
      (enables adoption of W1-W5, not itself a technical edge).

WHERE PARITY IS THE HONEST CEILING: core device physics breadth (aim
to match, achievable via 4b's tiers); process simulation (M35 is XL
because 30 years of implant/diffusion calibration data live there).

WHERE TO CONCEDE, EXPLICITLY: foundry-calibrated model libraries (the
calibration data is proprietary -- offer a calibration FRAMEWORK,
never a pre-calibrated 5nm deck); industrial qualification/support/
training/ecosystem; specialized vertical modules (power, memory,
imagers, photonics).

STRUCTURAL CONSEQUENCE: adjoint capability must be DESIGNED IN, not
retrofitted. M31 P5 (the intended host) stopped after P5-0, so M47/
M48 below re-anchor to the Python-path fix (P4b's transpose-friendly
Dirichlet elimination) rather than a C++ assembler that will not
exist -- a smaller, still-real claim, to be re-scoped before M47
starts (see 5.1's ADJOINT NOTE; note this is a different "M47" number
than section 5.3's dimensional-engine M47 -- resolve the numbering
collision before either is scoped in detail).

  M47/48  Adjoint sensitivity engine          [L]  dQoI/dp via one
          forward + one adjoint solve, gated against FD gradients to
          the same 5e-5 tolerance test_m13_solver.py already uses.
  M48/49  Gradient-based calibration/optimization [M]  Replace M30's
          Nelder-Mead with L-BFGS driven by the adjoint engine; gate:
          same fit, >=5x fewer forward solves.
  M49/50  Uncertainty quantification & sensitivity ranking [M]
  M50/51  ML surrogate / differentiable coupling [L]

FALSIFIABLE CRITERIA (per section 36, no claim without a benchmark
table; C1/C4 are the ones to chase first -- fully in our control,
no Sentaurus licence needed):
  C1  Same device/targets: calibration converges in >=5x fewer forward
      solves than Nelder-Mead (W1/adjoint-calibration milestone).
  C2  On B7 (large synthetic 3D), one-GPU-workstation time-to-solution
      beats a documented Sentaurus multi-core result at equal DOF/
      accuracy (W2/M31 P7).
  C3  Any published figure regenerates bit-identically from its study
      manifest on a clean checkout (W3).
  C4  Time-to-add-a-new-physics-model, including its validation gate,
      is under one working session (W5).

------------------------------------------------------------------------
7. STANDING OPEN ITEMS (not covered by a numbered milestone above)
------------------------------------------------------------------------
- GUI has no freeform/arbitrary geometry authoring (sketch-and-drag).
  The library already solves on an arbitrary gmsh mesh
  (unstructured_poisson.py/unstructured_dd.py); nothing in the GUI
  builds or edits one. 3D device AUTHORING has a domain model
  (Region/ContactDef/DomainDevice with optional z-extent) and, as of
  2026-09-13, Structure-panel GUI wiring (AppController.setDomainDepth/
  setRegionZBounds, StructurePanel "3D DOMAIN" control, DopingEditor
  per-region z-bounds row) -- a device author can go 2D-region-
  authored -> 3D through the Structure panel for a simple ohmic-
  contact device. Template-driven 3D examples and a freeform "Build 3D
  device" wizard remain future work. Phase-1 scope: ohmic contacts
  only (no gates), no range-restricted 3D contact faces, uniform
  doping only in 3D -- all three already refused loudly, not silently
  ignored.
- No dedicated provenance-trace UI (click through mesh -> physics ->
  material -> backend); result files carry the data, no single view
  walks the chain.
- M52 MULTI-METRIC CONVERGENCE + MESH STATS -- LANDED 2026-09-16.
  This item used to read "No full numerical-diagnostics panel ... a
  'convergence' viewport mode and RunRecord plumbing exist, not the
  dedicated panel" -- investigating before building a new panel found
  that claim stale: the GUI already has THREE diagnostics surfaces
  reading the M2 RunRecord/ConvergenceStep substrate (SolverTelemetryPanel,
  live/scrape-fed; the "convergence" viewport mode, post-hoc; and
  PhysicsLabPanel's provenance/continuation tables) -- a fourth panel
  would have duplicated them. The real, shared defect: both
  `_draw_convergence` (mpl_canvas_item.py) and `PhysicsLabController.
  convergenceData()` independently only ever read the FIRST tracked
  Newton metric (`next(iter(step.metrics.values()))`), silently
  dropping the rest -- confirmed a real bias-solve verbose line prints
  3 (`|F|`/`|dpsi|`/`|dn/n|`, device.py:2451-2453). Fixed in place: the
  convergence plot now draws every tracked metric per stage (distinct
  linestyle, shared stage color), `convergenceData()` gained a
  `"metrics"` dict alongside the unchanged `"residuals"` key, and
  `provenanceRows()` gained per-axis mesh-extent rows (`AppController.
  meshStats`' axis breakdown was already computed and thrown away).
  A real bug was caught by real-app verification and fixed before
  landing: the new mesh rows initially mislabeled raw cm values "um"
  with no conversion (`[0, 0.00012] um` for a 1.2 um channel) --
  fixed with the same *1e4 conversion every other mesh-coordinate
  readout in the GUI uses. See `M52-DIAGNOSTICS-MULTIMETRIC-PLAN.md`.
  Deliberately out of scope: a new panel/tab, unifying
  SolverTelemetryPanel's live scrape pipeline with the post-hoc
  RunRecord path (two independent pipelines for the same conceptual
  chart), and rejected-bias-POINT-level data (continuation.py's
  drivers still never persist individual backoff attempts, only the
  coarse per-stage converged=False flag).
- Additional device templates the original vision named: BJT, solar
  cell, PIN diode explicitly (Schottky now has a standalone physics
  module, M28, but no template). Only diode/MOSCAP/NMOS/HBT/HEMT/
  FinFET exist as templates today.
- No cross-backend GUI comparison (pytcad vs devsim side-by-side),
  though both implement the SolverBackend protocol.
- GPU (CUDA/CuPy) and MPI domain decomposition: LANDED but only in the
  GUI's 3D solve path (gui/services/solver_runner.py +
  mpi_schwarz_runner.py), not in pytcad's core Device classes
  themselves. Which engine actually ran is surfaced via
  AppController.solverEngineLabel. SYCL was not pursued (no native
  Python binding).
- M51 GEOMETRY/MESH HOVER + OVERLAY -- LANDED 2026-09-16 (identified
  2026-09-14, scoped and implemented same session). Investigating the
  "NO INTERACTIVE 1D/2D GEOMETRY/MESH VIEWER" gap before implementing
  found it narrower than first flagged: `ViewportPanel.qml` already had
  real pan/zoom (`MouseArea` + `canvas.pan()`/`zoom()`/`fit()`/
  `resetView()`), and `MplCanvasItem.hoverAt()` already drove a live
  readout for 1D curve modes -- what was actually missing was hover for
  2D field maps (doping/bands/recombination)/Structure/Mesh modes (all
  silent no-ops, `hoverAt` bailed whenever `self._series` was empty,
  which it always was there) and a mesh-overlay toggle for 2D field
  maps. `hoverAt()` is now a dispatcher over four hover sources
  (`_hover_series` unchanged, plus new `_hover_field_grid`/
  `_hover_structure`/`_hover_mesh`), and a `meshOverlay` property mirrors
  the existing `contours` property exactly, drawing the field map's own
  true (non-uniform) mesh axis coordinates as an overlay. See
  `M51-GEOMETRY-MESH-HOVER-PLAN.md` for the full writeup and honest
  limits (no 3D hover here -- viewer3d.py already covers 3D; no
  edge-level Structure inspection, only regions). Gated in
  `gui/tests/test_mpl_canvas_hover_m51.py` (8/8); the pre-existing
  `test_mpl_canvas_item.py`/`test_mpl_canvas_series.py`/
  `test_viewport_pan_zoom_fast_path.py` suites re-run green, unchanged.
  Verified against the real running app: a real solve, the actual
  `mplCanvas` QML object in the live tree, a real hover producing
  `"doping: 1.000e+17 cm^-3 @ x=2.03, y=0.53 um"`, and the real
  mesh-overlay toggle adding/removing 100 grid lines on the actual
  rendered figure.
- 3D VIEWER PHASE 6 -- VECTOR FIELD VISUALIZATION -- LANDED 2026-09-14.
  `gui/services/viewer3d.py`'s isosurface/volume/exploded-view viewer
  had no vector-field rendering despite `ResultStore.vector_field()`/
  `VectorField` already existing in the store protocol and
  `solver_runner.extract_result()` already writing a real
  `vector__current_density__{x,y,z}` (node-averaged Jn+Jp) for every
  solved-bias 3D result -- the data existed, nothing visualized it.
  Added `attach_vector_field()` (the vector analogue of
  `attach_scalar_field()`) plus a new "Vector Field" sidebar dock:
  arrow glyphs (`grid.glyph(orient=name, scale=name, tolerance=...)`,
  arrow length/color both following the vector's own magnitude) and
  streamlines (`grid.streamlines(...)` seeded from the grid's own
  center/radius, rendered as tubes), both real VTK filters over the
  actual solved data -- verified directly on the resistor_3d fixture
  (125 streamline points, a 3280-point tube mesh, not a synthetic
  check). `ResultStore.available_vectors()` added as a new protocol
  member (default `[]`, same honest-default pattern as
  `region_materials()`) so the vector dock disables itself outright
  for an equilibrium-only or pre-solve store rather than showing a
  live-looking control with nothing behind it. A real bug was caught
  before shipping: this pyvista version's `streamlines(max_time=...)`
  raises `pyvista.core.errors.DeprecationError`, which subclasses
  RuntimeError -- an initial broad `except (ValueError, RuntimeError)`
  around the streamline call silently swallowed it, which would have
  made "Show streamlines" a permanent no-op for every user; fixed by
  using the current `max_length` parameter and narrowing the except to
  `ValueError` only (VTK's genuine "no valid seed" case), confirmed by
  re-running the real pipeline and seeing actual streamline points.
  A SECOND real bug reached the user before it was caught: `grid.glyph()`
  does NOT carry the source vector array through under its own name --
  its output only ever has PyVista's own fixed "GlyphVector"/
  "GlyphScale" arrays -- so the first landing's `add_mesh(glyphs,
  scalars="current_density")` raised `KeyError: 'Data array
  (current_density) not present in this dataset'` the instant a real
  user checked "Show arrows" in the actual running app. The mocked
  `FakeInteractor` test suite could not catch this (its `add_mesh`
  never inspects the `scalars=` kwarg against the mesh it was called
  on) -- fixed by coloring glyphs by "GlyphScale" instead (verified
  equal to the real vector magnitude), and closed the test gap itself
  by adding `test_add_glyphs_and_add_streamlines_render_on_a_real_
  pyvista_plotter` (a genuine off-screen `pv.Plotter`, no Qt/X11
  needed, no FakeInteractor) that reproduces the exact KeyError when
  run against the pre-fix code -- confirmed directly, not assumed.
  A THIRD real bug reached the user before it was caught, again only
  on a real (non-uniform) device rather than the uniform resistor-bar
  fixture the original test coverage used: `vtkTubeFilter` can
  silently DROP the source vector array entirely when a streamline
  segment has few points -- confirmed directly on
  `pn_junction_3d_example_spec` (a 16-point streamline kept
  "current_density" before tubing, lost it after; a 150-point one on
  the same device kept it both times) -- so the "Show streamlines"
  checkbox raised the same `KeyError` class as the glyph bug, just on
  a different device/code path. This is genuine, data-dependent VTK
  behavior, not fixable upstream: fixed by checking
  `name in tube.point_data` AFTER tubing and falling back to a solid-
  colored tube rather than assuming the array survived. Gated by
  `test_add_streamlines_falls_back_to_a_solid_tube_when_tube_drops_
  the_field` (monkeypatches `PolyData.tube` to reproduce the exact
  observed drop deterministically, since VTK's internal streamline
  seeding is randomized and a synthetic 2-point polyline built by hand
  did NOT reproduce the drop when tried directly). Stress-tested
  afterward: 15 trials each of resistor_3d/pn_junction_3d/mosfet_3d/
  bjt_3d_example_spec through the exact production glyph+streamline
  code path, zero crashes. Gated in `gui/tests/test_viewer3d.py`/
  `test_result_store.py`; full `gui/tests/` suite re-run green (795
  passed) after all three fixes. Honest limit: Phase 4's sweep-playback snapshots
  (`result_store.SweepSnapshots`) are scalar-only, so glyphs/
  streamlines are NOT recomputed per playback frame -- toggle them off
  before scrubbing a sweep. NOT done: a user-positioned streamline
  seed plane (uses the grid center by default), E-field as a second
  vector quantity (only current_density is exported today), and the
  same feature for 2D (M51 above is the 1D/2D analogue, unscoped).
- PARAVIEW EXPORT -- LANDED 2026-09-16. `gui/services/paraview_export.py`
  (pure) writes a genuine ParaView-native `.vtu` for the current result
  and, once sweep-snapshot playback data exists, a real `.pvd` time series
  keyed by each step's bias voltage -- reusing `viewer3d.py`'s own
  grid-building functions rather than a from-source ParaView build (both
  `pq*` widgets and `paraview.simple` need one; investigated and rejected
  as out of proportion given PyVista/VTK already covers the in-app
  viewer). `Viewer3DWindow` gained a "ParaView Export" dock: export
  actions plus "Open in ParaView" (`QProcess.startDetached` against a
  `QSettings`-persisted executable path). See
  `PARAVIEW-EXPORT-PLAN.md` for the full writeup and honest limits
  (scalar-only `.pvd`, no real-ParaView visual verification available on
  this machine). A real bug shipped past the first green test run and was
  caught only by opening the actual app and clicking the real button: the
  export handlers referenced `paraview_export` with no import of it in
  scope (a claimed "lazy import" that was never actually written) --
  every existing test called the underlying pure functions directly or a
  different handler, none of them the two that were actually broken.
  Fixed (the lazy import, inside each handler, to dodge the real
  circular-import risk with `viewer3d.py`); closed the test gap with two
  new handler-level tests. Gated in `gui/tests/test_paraview_export.py`
  (10/10); `test_viewer3d.py`'s pre-existing 48 tests re-run green,
  unchanged.

------------------------------------------------------------------------
8. NEXT SESSION QUEUE
------------------------------------------------------------------------
Live front of the queue, updated 2026-09-17: M43 (self-heating -> 2D/3D,
all 3 phases) and M51/M52/the ParaView export item (section 7) have
since LANDED -- this paragraph is left dated so a reader can see what
changed rather than silently rewriting history. M42-S1 (density-gradient
-> Device2D, ohmic contacts only) LANDED 2026-09-17; the front of the
dimensional-lift track (5.3) is now **M42-S2** (the GateBC Lambda
boundary condition -- an open physics question, not an implementation
task; M42-DENSITY-GRADIENT-2D3D-PLAN.md section 0.2/8 says to decide
whether it is answerable before starting it). M35 (3D process) and M47
(3D engine completion) remain the two largest unscoped items. See
`history.md` for session-by-session detail and open handoff notes --
note `history.md` itself has NOT been updated with entries for M43,
M51, M52, or the ParaView export item as of this writing (verified by
grep 2026-09-17); those milestones' only in-tree record is this file
and their own plan docs.

Standing rules: every slice ships suite-green with pre-existing tests
unchanged; adversarial probe pass before each commit; optional deps
stay optional; gate-bearing milestones block their dependents; a
"COMPLETE, all gates green" status claim is not evidence on its own --
measure it, don't trust the last status block (this file was wrong
about M15 for a full session once, per M15-IONIZATION-PLAN.md).
