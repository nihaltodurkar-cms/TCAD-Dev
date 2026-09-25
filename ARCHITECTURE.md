# Semiconductor Workbench - Architecture Plan
==========================================================
Date: 2026-09-14 (compacted). Status: M1-M12 SHIPPED. Tier-1 parity (M13-M20) COMPLETE except M14's G-A (paywalled source). Tier-2 (M21-M26) COMPLETE to disclosed slice levels. Tier-3 (M27-M30 Part I) LANDED; M30 Part II (GUI/product layer) LANDED 2026-09-09. M31 (C++/PETSc engine) IN PROGRESS. M32-M50 (proposed post-M31 map) mostly landed per status table in 4c below. M41 (dimensional-lift track) IN PROGRESS, M41/M16-S2 landed, M43 next.

This file = LIVE roadmap + status record. Debugging narratives behind any "LANDED"/"COMPLETE" line: see milestone's own `pytcad/M*-PLAN.md` and `history.md` -- this file states outcomes + open items, not session transcripts.

Long-term ambition: learning + research TCAD env matching, and on select axes (see section 4e) beating, DEVSIM/Silvaco/Sentaurus while staying open, modular, understandable. Every educational surface backed by actual computed physics.

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

Placement rule: workbench/ lives beside pytcad/. Numerical core NEVER modified except to expose values it already computes, or via explicit frozen-core amendment mechanism (CLAUDE.md).

------------------------------------------------------------------------
3. M1-M12 -- SHIPPED FOUNDATION (compact record)
------------------------------------------------------------------------
M1 Domain core + model catalog. M2 RunRecord + result schema v2. M3 ResultStore/analysis boundary + SolverBackend protocol. M4 Physics Lab foundation (catalog panel, provenance view). M5 Device Builder (pn diode/NMOS/MOS-C templates). M6 Process Builder (1D, per-region implants). M7 DEVSIM backend (equilibrium slice, opt-in). M8 first new physics beyond original five models. M9 educational physics lab (model on/off comparisons). M10 deck/workflow translation layer. All SHIPPED; each proved behavioral equivalence or added independently validated capability, adversarial-probed before ship.

M11 HETEROSTRUCTURES -- ALL SHIPPED (S1-S5): Ge/GaAs/InGaAs/AlGaAs materials; DeviceSpec.region_materials wire format; Device1D eps(x) flux-form Poisson + Anderson band offsets via CARRIER-SPECIFIC ln(nie) edge deltas (electron dpsi + dln(nie), hole dpsi - dln(nie) -- shared delta passes FD-Jacobian but breaks hole detailed balance); Device2D box-integration equivalent; HBT/HEMT templates + UI.

M12 TUNNELING & QUANTUM CORRECTIONS -- ALL SHIPPED (S1-S3): FN/WKB analysis module (workbench/physics/tunneling.py); Hurkx TAT in Device1D (SI-calibrated fields -- V/cm underflows silently); S3 (density gradient) folded into M20 (COMPLETE, see below).

------------------------------------------------------------------------
4. SENTAURUS-PARITY ROADMAP (M13-M30) -- STATUS
------------------------------------------------------------------------
Three parity tiers: TIER 1 "SDevice local-physics parity, Si 1D/2D" (statistics, mobility, II, BTBT, transient, AC, self-heating, DG). TIER 2 "SProcess-lite + general geometry" (unstructured meshing, mask-driven process, TED/OED, 3D iterative solvers). TIER 3 "System-level" (mixed-mode circuit, hydrodynamic, MC implant, calibration).

Permanently OUT OF SCOPE: Monte-Carlo Boltzmann transport, atomistic kinetic-MC diffusion, radiation/SEE, ferroelectric/phase-change materials, full viscoelastic oxidation mechanics, Maxwell/EM solvers, PDK-grade compact-model extraction, bit-identity w/ commercial tools, any performance claim w/o section-36 benchmark table.

STANDING ENGINEERING RULES (unchanged, binding):
1. Milestone touching device core uses M11-S3 amendment mechanism: explicit sign-off, FD-Jacobian-first, bit-identity w/ model off, acceptance tests before merge.
2. Every new model lands in tests/test_model_benchmarks.py FIRST w/ published constants; benchmark error quoted in commit.
3. GATE BLOCKING: milestone w/ quantitative acceptance gates blocks declared dependents until every gate green under full-suite invariant. "Mostly green" ≠ green -- M15 once declared complete while two own gates unreachable (M15-IONIZATION-PLAN.md's debug-pass record = cautionary case).
4. New meshes/linear solvers ship w/ golden parity tests vs existing validated paths before anything uses them.
5. Optional deps stay optional, auto-detected, graceful refusal.
6. Result schema changes additive + versioned.
7. Honesty clauses mandatory: what NOT modeled, where it breaks, which gates qualitative.
8. GUI grows only along validated data paths; no plot w/o store a test validates.

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
Fermi-Dirac/incomplete ionization, surface mobility, coupled II, BTBT, TAT, self-heating, transient, AC, DG, 2D heterojunctions all [partial]/[missing] when drafted; all now landed to tier-1 scope above except M14 G-A. Process (implant/diffusion/oxidation/deposition-etch), unstructured meshing, adaptive refinement, 3D scale, mixed-mode circuit, calibration/splits all [partial]/[missing]; all landed to tier-2/3 scope above.

4b.6 GEOMETRY FOUNDATION DECISION (M21 phase 3's mesher): gmsh, not raw
OpenCASCADE/pythonocc-core or FreeCAD. gmsh = one open project bundling OCC-based CAD kernel, unstructured 2D/3D meshing, Physical-Group region tagging in one Python-importable package; DEVSIM already documents importing gmsh meshes directly. Validated, not merely decided: examples/debug_geometry_gmsh_conformality.py confirms gmsh-built p-n diode mesh CONFORMAL across material interface (shared node tags exactly at junction, region areas match analytic to 1e-16, zero degenerate triangles) -- what box-integration FV assembly requires. Hard-debug finding: ungrounded gmsh size field over-refined device to 21344 nodes; regrounding in pytcad.mesh.debye_length (same quantity phase 1's h/L_D constraint uses) cut to ~2100 nodes. Full record: M21-MESHING-PLAN.md section 12. 3D repeat of conformality check undone (3D unstructured meshing out of Phase 3 scope).

------------------------------------------------------------------------
5. POST-M31 ROADMAP (M31-M50)
------------------------------------------------------------------------
STATUS OF THIS SECTION: M31 REAL (planned, gated, in progress, own plan doc). M32-M50 = PROPOSED map grounded in repo's own disclosed gaps (4b.1, each M*-PLAN.md's honest-limits section, Architecture_Master_Plan.md sections 34/35) -- nothing below committed until own plan doc + gates.

5.1 M31 -- C++/PYTHON/QT PRODUCTION ARCHITECTURE  [XL, IN PROGRESS]
Full spec: pytcad/M31-CPP-ARCHITECTURE-PLAN.md. Progressive extraction (Architecture_Master_Plan.md section 37) -- NOT rewrite.

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

THE MEASUREMENT THAT ORDERED THESE PHASES -- do not re-derive:
structured 3D assembly NOT bottleneck (24^3 equilibrium solve spends 98% wall time in _superlu.gssv; assembly 0.011s of 0.494s); pure-Python node-block-Jacobi GMRES already does 68,921 nodes in 4.71s, so direct-LU wall is ALGORITHMIC, not linguistic. Genuine blocker was unstructured mesh geometry (~80k tri/s 2D, ~3.5k tets/s 3D -- minutes of Python dict overhead before any physics); P2 closed it to 3.16M tri/s / 1.99M tets/s, bit-identical.

P5 STOPPED after P5-0: P5-1's Phase A-2 measured all 8 solver-selection cells (discriminator = COUPLING, not dimension -- largest win: 3D structured coupled bias, 44.56s -> 1.60s, 27.9x, via petsc/direct auto-selection, no default moved). P5 proper's own exit criterion then fired: B9's assembly SHARE rose 11x (1.5%->16.3%) but ABSOLUTE cost unchanged (~109ms) vs ongoing second-engine maintenance cost -- see M31-P5-ASSEMBLY-NEWTON-PLAN.md section 12. P6/P7 NOT blocked on C++ assembler that won't exist -- re-scope vs Python+PETSc stack P5-0/P5-1 actually built.

OPEN DECISION from P2: build_unstructured_stencil winding-sensitive (clockwise triangle contributes NEGATIVE dual-cell areas); gmsh emits CCW so no real caller hits it, but compiled path faithfully reproduces quirk, PINNED by test not papered over. Fix changes physics, must land on both paths (Python oracle + C++) at once.

ADJOINT NOTE (relevant to M47 below): P5 stopping means "expose dR/dp, keep J^T-friendly assembly" gate originally wanted on C++ assembler never had assembler to apply to. Dirichlet-transpose half closed on PYTHON path instead (P4b: symmetric row-AND-column elimination in dirichlet.py). M47 should depend on P4b's fix, not stopped P5.

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
  M35  3D process simulation                      [XL]  S1+S2+S3+S3b+S4+S5+S6 LANDED 2026-09-18
       S1 (level-set representation, replacing process2d's
       single-valued height field), S2 (deposit/etch as real
       topology on it -- conformal coverage, trench pinch-off, genuine
       isotropic undercut, directional etch), S3 (oxidation as a
       real embedded 2D oxidant-diffusion moving-boundary solve --
       pytcad/oxidize_levelset.py, replacing the old column-independent
       Deal-Grove + lateral-suppression kernel), S3b (dopant
       transport across that moving boundary, reusing ted.py's own
       segregation_partition applied incrementally per swept cell), and
       S4 (masks as first-class 2D objects via deposit_conformal's
       x_windows param, silicidation -- pytcad/silicide_levelset.py, a
       structural port of S3's architecture with NO built-in named
       silicide, since a literature search for verifiable (B,A)
       constants hit the same class of blocker as M14's G-A --,
       epitaxy via facet-dependent deposit_epitaxial, and CMP via
       planarize, trivial as the plan predicted) are landed and gated;
       see M35-3D-PROCESS-PLAN.md sections 11-15. S3, S3b, and S4's
       full fast-suite regression runs were all skipped per explicit
       user instruction (an honest gap vs S1/S2's own verification
       record -- targeted regression files were run directly instead
       each time). S4 also surfaced (did not introduce) a latent
       numerical limitation in S2's advance_front: its masked-erosion
       exposure test can over-propagate lateral undercut at fine grids
       (one grid cell per CFL substep regardless of substep size) --
       see plan section 15. Per the plan's own section 9, S4 completed
       the "stop and re-evaluate whether S5/S6 (3D) are wanted"
       checkpoint; the user then asked to proceed, with reduced token/
       agent usage. S5 (pytcad/levelset3d.py) ports the level-set CORE
       to 3D only (representation/advection/reinit + S2's deposit/etch
       topology), gated by the 4d.4 rule (z-invariant 3D reproduces 2D
       to <1e-10). A follow-up same-day pass then closed both remaining
       gaps at the user's explicit request ("no gaps"): S5 now has full
       S1-S4 parity in 3D -- etch_directional3d/deposit_epitaxial3d/
       planarize3d added to levelset3d.py, plus two new modules,
       pytcad/oxidize_levelset3d.py (6-neighbor 3D finite-volume
       oxidant-diffusion solve, same persistent-phi architecture as the
       2D module, includes 3D dopant transport) and
       pytcad/silicide_levelset3d.py (per-(x,z)-line linear-parabolic
       solve, same no-built-in-silicide honesty clause as 2D). S6 is
       now COMPLETE: gmsh_finfet3d.py's geometry was rebuilt on a real
       per-column staircase surface (_staircase_face) from
       geom.surface_um instead of 3-region median flattening, on top of
       the doping-field fix (sample_doping_3d_from_process2d) already
       landed. See plan sections 16-17 for the full record, including a
       latent advance_front3d over-propagation finding (same known
       class as S4's, not new) and a real downstream face-classification
       bug the staircase geometry surfaced and fixed (gate_top/gate_side
       tagging assumed one flat top y-value per region). A third same-
       day pass then added a SECOND, independent geometry pipeline
       alongside (not replacing) the staircase path: real smooth 3D
       geometry (levelset3d.marching_cubes_surface, via the new optional
       scikit-image dependency -- a genuine triangulated isosurface,
       including a union-of-materials CSG option) and direct level-set
       tet meshing (new pytcad/levelset3d_mesh.py, via the new optional
       tetgen dependency -- gmsh's own STL-remeshing path was tried
       first and confirmed unsuitable for smooth marching-cubes
       surfaces, see plan section 18 for why). Region tags come from
       per-tet-centroid lookup into the level set's own material_map()
       (not conformal to element faces, a disclosed approximation);
       domain-boundary caps carry a bounded sub-grid-cell placement
       error (also disclosed, measured 0.95% on a flat slab). Both
       pipelines' output was rendered via pyvista's offscreen path and
       visually inspected (the real Viewer3DWindow's known segfault on
       this machine was not re-attempted) -- correct block shape, a
       genuinely curved/diagonal undercut cross-section distinct from
       the staircase path's sharp right-angle steps, no defects found.
       See plan section 18 for the full record. Depends: M31 P2
       (landed).
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

Suggested order: M31 P3a -> M32 -> P4..P7 -> M35 (spine). Parallel tracks: physics M33->M37; system M30-Part-II(landed)->M38(landed); optics M40 standalone. C++-gated: M34 (needs P4, has it), M35 (needs P2, has it); M36/M39 (needed P5, stopped -- re-scope first). M32 deliberately inside M31 track, not after, since P7's scaling claims need dashboard to police them (section 36).

PERMANENTLY OUT OF SCOPE (stated so never rediscovered as "gap"): p-/r-refinement (node motion, M21's own exclusion); bit-identity w/ commercial tools. Device3D AC's "permanently out of scope" call DEMOTED to deferral to re-cost (see M45) -- made when 3D died at ~27k nodes; M31 removes that constraint.

5.3 THE ROAD TO 3D -- DIMENSIONAL-LIFT MILESTONES (M41-M47)

Organized by DIMENSION not capability: DD spine (drift-diffusion, Fermi-Dirac, coupled/nonlocal II, local/nonlocal BTBT, TAT, AMR, mixed-mode) already reaches 3D on structured + unstructured meshes -- M31 about making 3D FAST, not making it exist. Debt concentrated in physics added AFTER DD core (quantum corrections, self-heating, hydrodynamic, transient, AC), each stopped at 1D/2D under defensible "1D first" call nobody revisited. Process simulation = widest gap (3D device physics vs 2D-at-best/1D-for-TED process input).

COVERAGE MATRIX (Y = works, - = absent; verified vs imports/NotImplementedError sites, not inferred from filenames):

  capability                       1D    2D    3D    gap owner
  --------------------------------------------------------------------
  Drift-diffusion, structured       Y     Y     Y    --
  Drift-diffusion, unstructured     -     Y     Y    -- (1D moot)
  Fermi-Dirac / incomplete ion.     Y     Y     Y    --
  Impact ionization (coupled)       Y     Y     Y    --
  Impact ionization, nonlocal       Y     Y     Y    --
  BTBT, local Kane / nonlocal       Y     Y     Y    --
  Trap-assisted tunneling           Y     Y     Y    --
  Density gradient / quantum        Y     Y     Y    -- (M42 S1-S4 done)
  Self-heating (lattice T)          Y     -     -    M43
  Hydrodynamic / energy balance     Y     Y     Y    -- (electron-only)
  Transient / small-signal AC       Y     Y     Y    --
  Adaptive refinement               Y     Y     Y    --
  Process: implant/diffuse/oxide    Y     Y     -    M35
  Process: TED, MC implant          Y     -     -    M35
  Mixed-mode circuit                Y     Y     Y    --
  Schottky / tunnel contacts        S1+S2 S1+S2 S1   M46

  Y* = standalone/analysis module, NOT coupled into any device Newton
       core (hydrodynamic.py, schottky.py -- imported by __init__.py
       and nothing else).

RULE: no dimensional lift lands w/o reduction identity as gate -- 3D impl whose z-uniform case doesn't reproduce validated 2D answer to floating-point noise = second, unvalidated code path, not 3D impl (existing examples/05_3d_reduces_to_2d.py pattern, 1.11e-16 V measured).

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
  M42  Density gradient / quantum -> 2D/3D    [L]   S1+S2+S3+S4 LANDED,
       MILESTONE CLOSED (S1+S2 2026-09-17, S3+S4 2026-09-18 --
       M42-DENSITY-GRADIENT-2D3D-PLAN.md sections 9/11/12/13; this line
       went stale for one session between S2 and S3 landing, per
       section 8's own standing rule that a status claim here is not
       evidence on its own). S1 alone did NOT satisfy the FinFET/GAA confinement
       prerequisite -- Device2D, ohmic contacts only, any GateBC
       refused loudly. S2 closed that gap: the GateBC Lambda boundary
       condition (a two-part hard wall at the gate/oxide interface,
       ported from moscap.py's own M20 fix) landed in device2d.py
       only, 17/17 gates green, all six m13 golden md5s unchanged. S3
       ported the same coupled-Newton solve to Device3D (a direct
       lift, no new physics): the shared Lambda-row assembly was
       factored into pytcad/dg_grid.py (mirrors ii_grid.py/btbt_grid.py's
       "one kernel for Device2D and Device3D" pattern) and, on request
       mid-slice, compiled into pytcad._core (core/src/dg/grid.cpp) as
       an OPTIONAL kernel (unlike M31's required kernels, nothing
       retired the pure-Python fallback here) -- bit-identical between
       both paths, 15/15 new gates green, all 27 pre-existing S1/S2
       gates unchanged after the extraction. Ported
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
       S4 (2026-09-18, LANDED, closing M42 as a track): the FinFET/GAA
       fin-corner confinement demonstration section 10.8 called for.
       build_finfet3d gained an additive dg/dg_gamma passthrough
       (bit-identical when dg=False, by construction); a new
       build_fin_corner_slab (same file) isolates the corner-
       confinement question with uniform doping and a directly
       parameterized Vfb, the same way S2's own _build_gated_device
       isolates the single-gate case -- the full production
       mosfet_doping profile was tried first and found to overdrive
       the electrostatics at a naive bias shift (psi past 40 V,
       corner/flat suppression both saturating to an identical value)
       before falling back to the controlled slab. The load-bearing
       result: the density-suppression ratio (classical n / DG n) at a
       node one step in from BOTH a top and a side gate face at once
       (the corner) exceeds the ratio at a node one step from the top
       face alone (a flat face far from either sidewall) by more than
       2x at every bias tried (9.5x/7.75x/4.06x measured across three
       biases), and the gap survives mesh refinement. 10 gates in
       tests/test_m42_s4_finfet_confinement.py, all green; the
       production tri-gate template also solves dg=True cleanly
       (a smoke gate, not the quantitative comparison). Reported as a
       QUALITATIVE TREND per section 10.8 -- no published FinFET
       quantum-correction curve was sought or found (M14-G-A's
       standing lesson). See M42-DENSITY-GRADIENT-2D3D-PLAN.md section
       13 for the full record, including why the production doping
       profile was rejected for the quantitative gates.
       Same day, section 14: `build_fin_corner_slab` gained `gaa=True`
       (a fourth gate face, genuine gate-all-around), closing S4's own
       "no GAA geometry" limit -- the corner effect holds under it
       (671.4 vs 49.0, ~13.7x). The rest of M42's honest-limits list
       (DG transport, a penetration-aware interface, the refused
       compositions, corner rounding, a published curve) was reviewed
       and deliberately left alone -- each needs its own physics
       derivation or unstructured meshing this repo does not have, not
       a quick follow-on.
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
  M44  Hydrodynamic -> coupled, then 2D/3D    [XL]  LANDED 2026-09-19
       Electron-only (hole energy balance deferred, disclosed).
       Slice 1: Tn appended as a 4th Device1D DOF (rows 3N..4N-1, base
       3N block untouched), three-moment energy-transport model
       (Grasser/Tang/Kosina/Selberherr 2003), Tn-consistent Canali
       mobility feedback via hydrodynamic.py's own
       effective_field_from_temperature. Slice 2: benchmarked before
       compiling anything (M32 discipline) -- found and fixed an
       unvectorized Python assembly loop instead (18x -> 1.1x
       overhead), concluding NO C++ is needed for the 1D path. Slice 3:
       pytcad/hydro_grid.py, a D-generic (2D/3D) standalone kernel
       following ii_grid.py/btbt_grid.py's pure-Python convention (NOT
       thermal_grid.py's compiled one -- this physics has no nested
       Newton solve, so it never gets hot enough to justify a
       compile, confirmed by measurement). Slice 4: wired into
       Device2D/Device3D, same appended-DOF design. Three real bugs
       found while gating Slice 4: a DirichletBC/PinnedBC array-shape
       bug, an unfloored deep-minority density causing measurable
       Jacobian rank deficiency, and a missing transverse control-
       volume weight on the flux-divergence term (the actual cause of
       an 87% y-uniform Tn mismatch -- Slice 3's own gates had used an
       artificially uniform dV that couldn't expose it). After all
       fixes, y/z-uniform Device2D/Device3D reproduce Device1D's own
       Tn(x) to round-off (3e-13 / 4e-10). No C++ anywhere in this
       milestone despite the original scope note's expectation -- see
       pytcad/M44-HYDRODYNAMIC-PLAN.md for the full record, every
       gate, and the quantitative-benchmark gap (disclosed, same class
       as M14's G-A: no accessible digitized published overshoot
       curve).
  M45  Transient and AC -> 3D                 [XL]  LANDED 2026-09-18
       transient3d.py and ac3d.py, direct lifts of transient2d.py's/
       ac2d.py's own already-gated pattern one axis further (device.py/
       device2d.py/device3d.py untouched, same externally-driven
       pattern). Device3D AC's old "permanently out of scope" call was
       REVISITED as this milestone's own scope note said to -- a full
       N-port Y-parameter solve (ohmic AND GateBC ports, any
       normal_axis) works cleanly at the mesh sizes tested here.
       Two findings during the slice: (1) a missing bc.kappa factor in
       ac3d.py's gate forcing/weight, caught by inspection before any
       gate ran; (2) G1's first reduction fixture (a lone-body MOSCap+
       gate, no complete DC circuit through the one ohmic port) gave a
       poorly-conditioned Y[body,body] that mismatched Device2D's
       reduction by up to 56% -- not a code bug, confirmed by checking
       an ohmic-only diode3d fixture (no gate) separately, which
       matched a direct FD to 0.1% with no code change; fixed by using
       a two-ohmic-contact ("resistor + gate") fixture instead, which
       reduces to 1e-6 matrix-relative error. See
       M45-TRANSIENT-AC-3D-PLAN.md for full detail. Time-varying GateBC
       voltage remains unsupported in transient3d.py, same descope
       transient2d.py's own docstring already carries -- not lifted
       here, not this milestone's scope.
  M46  Schottky/tunnel contacts -> coupled, then 2D/3D  [L]  S1+S2+S3
       LANDED 2026-09-18, essentially complete for its own stated
       scope. Same shape as M44: couple schottky.py into a
       device core first, then lift dimensionally. S1 couples it into
       Device1D via a DIRICHLET approximation -- the contact node's
       majority-carrier density is pinned at its barrier-limited
       equilibrium value (reusing schottky.py's own
       schottky_barrier_height_n, not re-derived) through the SAME
       psi0 formula the ohmic contact already used. New SchottkyContact
       dataclass + Device1D(schottky_left=..., schottky_right=...)
       (additive, None on both sides is bit-identical to before).
       Confirmed directly: the resulting device RECTIFIES (forward/
       reverse current ratio ~53,000x at phi_m=4.8 eV), depletion
       grows monotonically with the metal work function, and forward
       current is barrier-limited below the equivalent ohmic device's.
       4 gates in tests/test_m46_s1_schottky_device1d.py, all green.
       S2 (same day) replaced the Dirichlet approximation with the
       full thermionic-emission ROBIN BC when SchottkyContact.A_star
       is given (A_star=None keeps S1's Dirichlet path bit-identical):
       found that device.py ALREADY had the exact equation shape
       needed -- M14's own Models(S_n=..., S_p=...) surface-
       recombination Robin BC is thermionic emission with a different
       velocity/target density, so S2 needed ZERO new Jacobian
       derivation, only per-node selection feeding the already-gated
       formula. Confirmed directly: equilibrium is IDENTICAL between
       Robin and Dirichlet (Jn=0 forces n=n0 regardless of v_R, the
       same invariant M14's own gate documents); under bias, Robin
       current is within ~10-15% of schottky.py's own analytic
       thermionic_current_density formula (numeric always slightly
       below, the expected direction from bulk series resistance the
       pure analytic formula omits) and smaller than S1's Dirichlet
       approximation's (0.536 vs 3.75 A/cm^2 at 0.3V). 6 gates in
       tests/test_m46_s2_schottky_robin.py including an FD-Jacobian
       check, all green. S3 (same day) lifted to Device2D (full S1+S2
       parity, via a SchottkyBC subclassing DirichletBC so every
       existing isinstance(bc, DirichletBC) site needs zero changes;
       the M14 G-C S_n/S_p Robin block was generalized from a global
       velocity to a per-node one) and Device3D (S1 Dirichlet
       approximation only -- Device3D has no M14 S_n/S_p machinery to
       generalize for S2 and refuses it outright already; the Robin
       mode is refused by add_schottky_contact there, a disclosed
       scope limit). A hard-debug finding kept in the record: the
       first draft of Device2D's per-node row splitting dropped the
       +1/+2 column offsets (n/p rows marked as the psi row); caught
       immediately by the FD-Jacobian gate (worst error exactly 1.0)
       before any physics gate was trusted, fixed, re-verified at
       1.7e-9. Confirmed directly: a transversely-uniform Device2D/
       Device3D reduces to Device1D's own SchottkyContact result at
       equilibrium (a genuine 3D->2D->1D chain); both dimensions
       rectify under bias. 10 gates in
       tests/test_m46_s3_schottky_2d3d.py, all green. See
       M46-SCHOTTKY-PLAN.md for the full record.
  M47  3D numerical engine completion         [XL]  LANDED
       2026-09-24 (pytcad/M47-3D-ENGINE-PLAN.md is the record). Both
       gaps closed: (a) 3D assembly compiled -- unstructured_dd3d.py
       (Slice 1, core/src/unstructured3d/) and Device3D's base coupled
       assembly (Slice 2a, core/src/device3d/), each parity-gated
       np.array_equal against its retained Python oracle; optional-
       physics composition stays in Python by design. Neither port is a
       clear wall-clock win (recorded honestly in the plan; a zero-copy
       binding follow-up measured no change and was reverted). (b)
       unstructured_dd3d.py heterojunctions (Slice 3): materials_per_node
       + band_offset ("nie"/"affinity"), a port of unstructured_dd.py's
       2D mechanism into both solve_bias3d and solve_poisson_
       equilibrium3d, gated in tests/test_m47_s3_unstructured3d_
       hetero.py (per-carrier detailed balance to 4e-14, Anderson
       built-in potential to 1.4e-9, structured-Device3D current
       comparison, mutation-checked against the shared-sign hole bug).
       Same stated limits as 2D: eps and SRH lifetimes per reference
       material, not per node.

ORDERING: M41[S](done) -> M43[L](done) -> M42[L](done, S1-S4) -> M46[L](done) -> M45[XL](done) -> M44[XL](done), w/ M35 (3D process, LANDED separately). M47 (3D engine completion) LANDED 2026-09-24, closing dimensional-lift track.
and M47 (engine completion, last deliberately -- more to learn by landing a few of M41-M46 first) as separate tracks.

------------------------------------------------------------------------
6. COMPETITIVE STRATEGY -- BEATING SENTAURUS/ATLAS, NOT JUST MATCHING
------------------------------------------------------------------------
4b.0's framing: literal feature parity w/ 30-person-decade incumbent = fantasy; beat it on axes where its ARCHITECTURE, not effort, prevents competing.

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

WHERE PARITY = HONEST CEILING: core device physics breadth (aim to match, achievable via 4b's tiers); process simulation (M35 XL since 30 years of implant/diffusion calibration data live there).

WHERE TO CONCEDE, EXPLICITLY: foundry-calibrated model libraries (calibration data proprietary -- offer calibration FRAMEWORK, never pre-calibrated 5nm deck); industrial qualification/support/training/ecosystem; specialized vertical modules (power, memory, imagers, photonics).

STRUCTURAL CONSEQUENCE: adjoint capability must be DESIGNED IN, not retrofitted. M31 P5 (intended host) stopped after P5-0, so M47/M48 below re-anchor to Python-path fix (P4b's transpose-friendly Dirichlet elimination) not C++ assembler that won't exist -- smaller, still-real claim, re-scope before M47 starts (see 5.1's ADJOINT NOTE; this "M47" differs from section 5.3's dimensional-engine M47 -- resolve numbering collision before either scoped in detail).

  M47/48  Adjoint sensitivity engine          [L]  dQoI/dp via one
          forward + one adjoint solve, gated against FD gradients to
          the same 5e-5 tolerance test_m13_solver.py already uses.
  M48/49  Gradient-based calibration/optimization [M]  Replace M30's
          Nelder-Mead with L-BFGS driven by the adjoint engine; gate:
          same fit, >=5x fewer forward solves.
  M49/50  Uncertainty quantification & sensitivity ranking [M]
  M50/51  ML surrogate / differentiable coupling [L]

FALSIFIABLE CRITERIA (per section 36, no claim w/o benchmark table; chase C1/C4 first -- fully in our control, no Sentaurus licence needed):
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
  Library already solves on arbitrary gmsh mesh
  (unstructured_poisson.py/unstructured_dd.py); nothing in GUI builds/edits one. 3D device AUTHORING has domain model (Region/ContactDef/DomainDevice w/ optional z-extent) and, as of 2026-09-13, Structure-panel GUI wiring (AppController.setDomainDepth/setRegionZBounds, StructurePanel "3D DOMAIN" control, DopingEditor per-region z-bounds row) -- author can go 2D-region-authored -> 3D via Structure panel for simple ohmic-contact device. Template-driven 3D examples + freeform "Build 3D device" wizard = future work. Phase-1 scope: ohmic contacts only (no gates), no range-restricted 3D contact faces, uniform doping only in 3D -- all three refused loudly, not silently ignored.
- No dedicated provenance-trace UI (click through mesh -> physics -> material -> backend); result files carry data, no single view walks chain.
- M52 MULTI-METRIC CONVERGENCE + MESH STATS -- LANDED 2026-09-16.
  Item formerly read "No full numerical-diagnostics panel ... a 'convergence' viewport mode and RunRecord plumbing exist, not the dedicated panel" -- investigation before building found claim stale: GUI already has THREE diagnostics surfaces reading M2 RunRecord/ConvergenceStep substrate (SolverTelemetryPanel, live/scrape-fed; "convergence" viewport mode, post-hoc; PhysicsLabPanel's provenance/continuation tables) -- fourth panel would duplicate. Real shared defect: both `_draw_convergence` (mpl_canvas_item.py) and `PhysicsLabController.
  convergenceData()` independently read only FIRST tracked Newton metric (`next(iter(step.metrics.values()))`), silently dropping rest -- confirmed real bias-solve verbose line prints 3 (`|F|`/`|dpsi|`/`|dn/n|`, device.py:2451-2453). Fixed in place: convergence plot draws every tracked metric per stage (distinct linestyle, shared stage color), `convergenceData()` gained `"metrics"` dict beside unchanged `"residuals"` key, `provenanceRows()` gained per-axis mesh-extent rows (`AppController.
  meshStats`' axis breakdown was already computed + thrown away). Real bug caught by real-app verification, fixed pre-landing: new mesh rows mislabeled raw cm values "um" w/o conversion (`[0, 0.00012] um` for 1.2 um channel) -- fixed w/ same *1e4 conversion every other GUI mesh-coordinate readout uses. See `M52-DIAGNOSTICS-MULTIMETRIC-PLAN.md`. Deliberately out of scope: new panel/tab, unifying SolverTelemetryPanel's live scrape pipeline w/ post-hoc RunRecord path (two independent pipelines, same conceptual chart), rejected-bias-POINT-level data (continuation.py drivers still never persist individual backoff attempts, only coarse per-stage converged=False flag).
- More device templates original vision named: BJT, solar cell, PIN diode explicitly (Schottky has standalone physics module, M28, but no template). Only diode/MOSCAP/NMOS/HBT/HEMT/FinFET templates exist today.
- No cross-backend GUI comparison (pytcad vs devsim side-by-side), though both implement SolverBackend protocol.
- GPU (CUDA/CuPy) + MPI domain decomposition: LANDED but only in GUI's 3D solve path (gui/services/solver_runner.py + mpi_schwarz_runner.py), not pytcad core Device classes. Engine that ran surfaced via AppController.solverEngineLabel. SYCL not pursued (no native Python binding).
- M51 GEOMETRY/MESH HOVER + OVERLAY -- LANDED 2026-09-16 (identified
  2026-09-14, scoped + implemented same session). Investigating "NO INTERACTIVE 1D/2D GEOMETRY/MESH VIEWER" gap found it narrower than flagged: `ViewportPanel.qml` already had real pan/zoom (`MouseArea` + `canvas.pan()`/`zoom()`/`fit()`/`resetView()`), and `MplCanvasItem.hoverAt()` already drove live readout for 1D curve modes -- actually missing: hover for 2D field maps (doping/bands/recombination)/Structure/Mesh modes (all silent no-ops, `hoverAt` bailed whenever `self._series` empty, which it always was there) + mesh-overlay toggle for 2D field maps. `hoverAt()` now dispatcher over four hover sources (`_hover_series` unchanged, plus new `_hover_field_grid`/
  `_hover_structure`/`_hover_mesh`), and `meshOverlay` property mirrors existing `contours` property exactly, drawing field map's own true (non-uniform) mesh axis coords as overlay. See `M51-GEOMETRY-MESH-HOVER-PLAN.md` for full writeup + honest limits (no 3D hover -- viewer3d.py covers 3D; no edge-level Structure inspection, only regions). Gated in `gui/tests/test_mpl_canvas_hover_m51.py` (8/8); pre-existing `test_mpl_canvas_item.py`/`test_mpl_canvas_series.py`/`test_viewport_pan_zoom_fast_path.py` suites re-run green, unchanged. Verified vs real running app: real solve, actual `mplCanvas` QML object in live tree, real hover producing `"doping: 1.000e+17 cm^-3 @ x=2.03, y=0.53 um"`, real mesh-overlay toggle adding/removing 100 grid lines on actual rendered figure.
- 3D VIEWER PHASE 6 -- VECTOR FIELD VISUALIZATION -- LANDED 2026-09-14.
  `gui/services/viewer3d.py`'s isosurface/volume/exploded-view viewer had no vector-field rendering despite `ResultStore.vector_field()`/`VectorField` already in store protocol and `solver_runner.extract_result()` already writing real `vector__current_density__{x,y,z}` (node-averaged Jn+Jp) for every solved-bias 3D result -- data existed, nothing visualized it. Added `attach_vector_field()` (vector analogue of `attach_scalar_field()`) + new "Vector Field" sidebar dock: arrow glyphs (`grid.glyph(orient=name, scale=name, tolerance=...)`, arrow length/color follow vector magnitude) and streamlines (`grid.streamlines(...)` seeded from grid's center/radius, rendered as tubes), both real VTK filters over actual solved data -- verified directly on resistor_3d fixture (125 streamline points, 3280-point tube mesh, not synthetic). `ResultStore.available_vectors()` added as new protocol member (default `[]`, same honest-default pattern as `region_materials()`) so vector dock disables itself for equilibrium-only or pre-solve store rather than showing live-looking control w/ nothing behind it.
  Bug 1 (caught pre-ship): this pyvista version's `streamlines(max_time=...)` raises `pyvista.core.errors.DeprecationError`, subclass of RuntimeError -- initial broad `except (ValueError, RuntimeError)` silently swallowed it, making "Show streamlines" permanent no-op; fixed w/ current `max_length` param + except narrowed to `ValueError` only (VTK's genuine "no valid seed" case), confirmed by re-running real pipeline + seeing actual streamline points.
  Bug 2 (reached user): `grid.glyph()` does NOT carry source vector array through under own name -- output only has PyVista's fixed "GlyphVector"/"GlyphScale" arrays -- so first landing's `add_mesh(glyphs,
  scalars="current_density")` raised `KeyError: 'Data array
  (current_density) not present in this dataset'` the instant real user checked "Show arrows" in running app. Mocked `FakeInteractor` suite couldn't catch it (its `add_mesh` never checks `scalars=` kwarg vs mesh) -- fixed by coloring glyphs by "GlyphScale" (verified equal to real vector magnitude); test gap closed by `test_add_glyphs_and_add_streamlines_render_on_a_real_
  pyvista_plotter` (genuine off-screen `pv.Plotter`, no Qt/X11, no FakeInteractor), which reproduces exact KeyError vs pre-fix code -- confirmed directly, not assumed.
  Bug 3 (reached user, only on real non-uniform device, not uniform resistor-bar fixture): `vtkTubeFilter` can silently DROP source vector array when streamline segment has few points -- confirmed directly on `pn_junction_3d_example_spec` (16-point streamline kept "current_density" before tubing, lost it after; 150-point one on same device kept it both times) -- so "Show streamlines" raised same `KeyError` class as glyph bug, different device/code path. Genuine data-dependent VTK behavior, not fixable upstream: fixed by checking `name in tube.point_data` AFTER tubing, falling back to solid-colored tube. Gated by `test_add_streamlines_falls_back_to_a_solid_tube_when_tube_drops_
  the_field` (monkeypatches `PolyData.tube` to reproduce observed drop deterministically, since VTK streamline seeding randomized and hand-built 2-point polyline did NOT reproduce drop when tried). Stress-tested after: 15 trials each of resistor_3d/pn_junction_3d/mosfet_3d/bjt_3d_example_spec through exact production glyph+streamline path, zero crashes. Gated in `gui/tests/test_viewer3d.py`/`test_result_store.py`; full `gui/tests/` suite green (795 passed) after all three fixes.
  Honest limit: Phase 4's sweep-playback snapshots (`result_store.SweepSnapshots`) scalar-only, so glyphs/streamlines NOT recomputed per playback frame -- toggle off before scrubbing sweep. NOT done: user-positioned streamline seed plane (uses grid center), E-field as second vector quantity (only current_density exported), same feature for 2D (M51 above = 1D/2D analogue, unscoped).
- PARAVIEW EXPORT -- LANDED 2026-09-16. `gui/services/paraview_export.py`
  (pure) writes genuine ParaView-native `.vtu` for current result and, once sweep-snapshot playback data exists, real `.pvd` time series keyed by each step's bias voltage -- reusing `viewer3d.py`'s own grid-building functions rather than from-source ParaView build (both `pq*` widgets and `paraview.simple` need one; investigated + rejected as out of proportion since PyVista/VTK already covers in-app viewer). `Viewer3DWindow` gained "ParaView Export" dock: export actions + "Open in ParaView" (`QProcess.startDetached` vs `QSettings`-persisted executable path). See `PARAVIEW-EXPORT-PLAN.md` for full writeup + honest limits (scalar-only `.pvd`, no real-ParaView visual verification on this machine). Real bug shipped past first green test run, caught only by opening actual app + clicking real button: export handlers referenced `paraview_export` w/ no import in scope (claimed "lazy import" never written) -- existing tests called underlying pure functions or different handler, none the two broken ones. Fixed (lazy import inside each handler, dodging real circular-import risk w/ `viewer3d.py`); test gap closed w/ two new handler-level tests. Gated in `gui/tests/test_paraview_export.py` (10/10); `test_viewer3d.py`'s pre-existing 48 tests re-run green, unchanged.

------------------------------------------------------------------------
8. NEXT SESSION QUEUE
------------------------------------------------------------------------
Live front of queue, updated 2026-09-18: M43 (self-heating -> 2D/3D, all 3 phases), M51/M52/ParaView export item (section 7), M35 (3D process, full S1-S6 scope incl. smooth level-set geometry + direct tet meshing), and M42-S1 through S4 (density-gradient -> Device2D ohmic + GateBC, then Device3D, then FinFET/GAA fin-corner confinement demo) all LANDED since paragraph first written -- left dated so reader sees what changed vs silent history rewrite. M42 now CLOSED as track (section 2/10.8 scoped it as S1-S4 exactly; nothing further defined w/o new plan doc). **M46 (S1+S2+S3)** also LANDED 2026-09-18 (Schottky contacts: Device1D's Dirichlet approximation + Robin thermionic-flux BC, lifted to Device2D -- full parity -- and Device3D -- Dirichlet approximation only, no Robin machinery there to generalize -- see M46-SCHOTTKY-PLAN.md), essentially complete for own stated scope. **M45 (transient/AC -> 3D)** also LANDED 2026-09-18: transient3d.py + ac3d.py, direct lifts of transient2d.py's/ac2d.py's already-gated pattern one axis further -- see M45-TRANSIENT-AC-3D-PLAN.md for two findings (missing bc.kappa factor caught by inspection; poorly-conditioned first reduction fixture caught by failing gate, root-caused before fix). Same-day follow-up closed M45's two cheap disclosed gaps: 3D transient physics reference gates (transient2d.py's gated G1/G4/G5 ported one axis further) + real 3D MOSFET fixture + gm/fT gates for ac3d.py. Reference-gate pass surfaced genuine efficiency bug in transient3d.py Newton loop (fully-failed line search, lam=0, not detected -- loop recomputed identical doomed step up to opts.max_iter=100 times, ~800s wasted on single failed step) and, after fix, genuine mesh-resolution finding (Nz=3's lone interior z-node has double boundary node's control-volume width, so one aggressive step can force Newton loop's single shared damping factor to 0 even though every other node -- incl. hypothetical 2D problem -- already converged; confirmed by re-running same comparison at Nz=7, converges cleanly). Neither finding case for porting to C++ (per-iteration cost never bottleneck, confirmed directly) -- see M45-TRANSIENT-AC-3D-PLAN.md section 8. Second follow-up (2026-09-19) closed M45's remaining GUI/wire-format exposure gap: solver_runner.py's transient/AC dispatch now routes Device3D spec to transient3d.py/ac3d.py instead of refusing, and AppController.canRunAc no longer excludes dimensionality==3. Pass found + fixed REAL regression in section-8 efficiency fix: `lam==0.0` short-circuit in transient3d.py's `_newton_step` returned "not converged" w/o first checking whether wanted correction already below tolerance -- wrong for device reaching steady state almost immediately (ohmic resistor, unlike M45's diode-based gates), where line search's merit comparison goes numerically unstable at already-converged (near-machine-precision) residuals and spuriously reports lam=0. Fixed by restoring original tolerance check BEFORE bail (see M45-TRANSIENT-AC-3D-PLAN.md section 11.1) -- fresh, physically different GUI fixture caught what M45's thorough gate suite hadn't exercised. M44 (hydrodynamic -> coupled, then 2D/3D) LANDED 2026-09-19 -- see pytcad/M44-HYDRODYNAMIC-PLAN.md (electron-only, no C++ needed, three real bugs found + fixed while gating Slice 4). M47 (3D engine completion) now front of dimensional-lift track + largest unscoped item, deliberately last. See `history.md` for session-by-session detail + open handoff notes.

Standing rules: every slice ships suite-green w/ pre-existing tests unchanged; adversarial probe pass before each commit; optional deps stay optional; gate-bearing milestones block dependents; "COMPLETE, all gates green" claim not evidence alone -- measure it, don't trust last status block (this file was wrong about M15 for full session once, per M15-IONIZATION-PLAN.md).