# SENTAURUS-PARITY-PLAN.md
# Bringing PyTCAD to Sentaurus-grade capability

Status: PLAN (not yet approved for implementation)
Owner: session handoff via history.md
Conventions: same discipline as HETEROSTRUCTURE-PLAN.md / TUNNELING-PLAN.md
-- red tests first, published-value benchmarks before features, FD-
Jacobian-first for any core-physics change, bit-identity when a model
is off, optional deps stay optional, suite green + zero warnings.

------------------------------------------------------------------------
0. HONEST FRAMING -- what "same level" can mean
------------------------------------------------------------------------
Sentaurus is ~30 person-decades of engineering. Literal feature parity
is not a plan, it is a fantasy. What IS plannable is parity in tiers,
where each tier is a device/process class we can simulate END-TO-END
with published-value validation at the same fidelity Sentaurus users
actually exercise. This plan defines three parity tiers and the
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
1. GAP ANALYSIS (Sentaurus capability vs PyTCAD today)
------------------------------------------------------------------------
Legend: [have] [partial] [missing]

DEVICE PHYSICS
  [partial] Fermi-Dirac statistics / incomplete ionization
            (we are Boltzmann + full-ionization; code already warns)
  [partial] Mobility: Caughey-Thomas + Canali in 1D; no surface/
            inversion-layer mobility (Lombardi CVT, PUMobi) in 2D
  [partial] Impact ionization: coefficients + breakdown integral exist
            as analysis layer; NOT coupled to any Newton assembly
            (devsim edge_volume_model unit anomaly documented)
  [partial] TAT (Hurkx, frozen field, 1D); no Schenk variant
  [missing] Band-to-band tunneling (local Kane; nonlocal path)
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
2. THE PLAN -- milestones M13..M30
------------------------------------------------------------------------
Sizes: S ~1 session, M ~1-2, L ~2-4, XL ~4+ (with tests, honest).

=== TIER 1: SDevice local-physics parity ===========================

M13  FERMI-DIRAC STATISTICS + INCOMPLETE IONIZATION          [L]
  Formal physics-foundation milestone -- full spec with
  quantitative acceptance gates in M13-FERMI-DIRAC-PLAN.md
  (G1 F_{1/2} vs independent quadrature reference + published
  spot values; G2 Boltzmann limit; G3 Sommerfeld degenerate
  limit; G4 charge-neutrality consistency vs independent root
  finds; G5 FD-Jacobian gates incl. degenerate heterointerface;
  G6 bit-identity goldens for the off-path; G7 published-value
  benchmarks with explicit applicability limits; G8 suite
  invariant).  Scope: Models(fd=False) default, parabolic-band
  F_{1/2} via a published rational approximation audited against
  quadrature, generalized SG chosen from candidate schemes by the
  detailed-balance gates, incomplete ionization (B/P/As) behind
  its own flag.  DEPENDENCY-CLEAN AND BLOCKING: M13 depends on
  nothing; M15-M20 may not START until all gates are green.
  Touches ALL THREE cores' residual+Jacobian -> the M11-S3
  amendment mechanism applies (goldens committed before the edit,
  FD-Jacobian-first, bit-identity proven before composition).
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
  Scope: as designed in TUNNELING-PLAN.md section 5 (DG term in
  Poisson, flag default off, bit-identical when off). Plus an
  analysis-layer Schrodinger-Poisson solve for the inversion
  centroid as the published-value gate.
  Acceptance: DG-off bit-identity; inversion centroid depth vs
  Schrodinger-Poisson result and vs the literature ~1 nm figure
  (retires the C_max overestimate caveat in README section 6).
  Depends: nothing hard; after M13 so FD composes.

TIER 1 EXIT CRITERIA: a user can, from the GUI or a deck, solve a
Si MOSFET/diode/MOS-C with FD statistics + CVT mobility + II + BTBT
+ TAT + self-heating + DG, run a DC/AC/transient sweep, and every
model on/off difference is validated against literature or analytic
form. This is the honest definition of "Sentaurus default-physics
parity" for silicon 1D/2D.

=== TIER 2: process-lite + general geometry =======================

M21  GENERAL 2D MESHING + FV ASSEMBLY                        [XL]
  Scope: optional-dependency meshers (triangle / gmsh); box-
  integration on general 2D meshes (Delaunay FV); solution-driven
  adaptive refinement (Debye length, II rate, field); the
  tensor-product assembly becomes a special case.
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
3. CRITICAL PATH & SUGGESTED ORDER
------------------------------------------------------------------------
Spine: M13 -> M15 -> M17 -> M18 -> M21 -> M23 -> M27
       (statistics) (II)   (transient)(AC) (meshing)(process)(mixed)

Finish-first queue (already designed, do before M13):
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
4. STANDING ENGINEERING RULES FOR THIS PLAN
------------------------------------------------------------------------
1. Any milestone touching a device core reuses the M11-S3 amendment
   mechanism: explicit user sign-off, FD-Jacobian-first, bit-identity
   with the model off, acceptance tests before merge.
2. Every new model lands in tests/test_model_benchmarks.py FIRST with
   published constants; the benchmark error is quoted in the commit.
4b. GATE BLOCKING: a milestone whose spec defines quantitative
   acceptance gates (currently M13, see M13-FERMI-DIRAC-PLAN.md
   section 4) blocks all milestones it declares blocked until every
   gate is green under the full-suite invariant.  "Mostly green" is
   not green; a skipped or weakened gate is a hidden failure.
3. New meshes/linear solvers ship with golden parity tests against
   existing validated paths (tensor-product, spsolve) before anything
   uses them.
4. Optional dependencies stay optional: triangle/gmsh, pyamg, any MC
   helper -- auto-detected, graceful refusal with a precise message.
5. Result schema changes are additive + versioned (v3 for transients).
6. Honesty clauses are mandatory in every milestone: what is NOT
   modeled, where the model breaks, and which gates are qualitative.
7. GUI grows only along validated data paths; no plot without a store
   that a test validates.

------------------------------------------------------------------------
5. IMMEDIATE NEXT ACTIONS (on approval)
------------------------------------------------------------------------
1. Close out M12-S2 (TAT) -- the two failing tests get rewritten to
   the global-neutrality + factor-law gates already designed; commit
   green.  (In flight, this session's open thread.)
2. M11-S4 (2D heterojunctions) -- design exists; medium.
3. M12-S3 / M20 (density gradient) -- design exists; medium-large.
4. M13 (Fermi-Dirac) -- spec formalized in M13-FERMI-DIRAC-PLAN.md;
   on approval: write the G1-G3 red tests (fermi.py is pure addition,
   no amendment needed), commit goldens, obtain the amend-core
   sign-off BEFORE touching any residual/Jacobian.  M15+ stay
   blocked until every gate in that spec is green.
