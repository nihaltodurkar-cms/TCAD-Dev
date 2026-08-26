# PROJECT HISTORY — for the next AI session
Read this + AGENTS.md + ARCHITECTURE.md + SENTAURUS-PARITY-PLAN.md
before doing anything.

## AIM
Evolve PyTCAD into a Semiconductor Workbench: an open, modular,
understandable learning+research TCAD environment (DEVSIM/Silvaco/
Sentaurus class). REAL physics only — every educational surface backed
by actual computation. Never fake, never mock, never weaken tests.

## STATE (as of this handoff)
Suite: **541 passed, ZERO warnings** (527 prior + 10 M13 fermi gates
+ 4 G6a goldens). Working tree clean. Python 3.14, PySide6, devsim
2.11 (optional dep). Nothing pushed beyond the user's last push.

SHIPPED SINCE THE LAST HANDOFF (all committed, none pushed unless
user did):
- M12-S2 TAT COMPLETE (29b9764): Hurkx trap-assisted tunneling in
  Device1D, all 4 acceptance tests green. Root causes fixed along the
  way: (1) junction-node rho=+-1 is CORRECT abrupt-junction dipole
  physics -> neutrality gate is GLOBAL balance |int rho|/int|rho|;
  (2) WKB factors are SI-calibrated -> field must be V/m (the V/cm
  unit bug silently reduced TAT to SRH); (3) bulk-Si midgap TAT is
  genuinely negligible (P underflows to exactly 0) -> the SILC gate
  exercises the factor law over synthetic log-spaced fields
  (1e7..5e10 V/m), device-level enh==1.0 asserted as honest physics.
- AGENTS.md (4dba542): agent guidance — layout, commands, hard rules,
  full gotchas ledger. READ IT FIRST.
- docs/user-guide/ (0896ac4, 895583b, 07ecaea): 20-page PDF+HTML
  guide; screenshots are REAL (headless QML app, QQuickWindow
  grabWindow, controllers driven end-to-end); validation section uses
  the four-way result classification.
- All READMEs updated (0b169fb): 527-test era, M11/M12 capabilities,
  honest limits.
- SENTAURUS-PARITY-PLAN.md (801cd9d, 1b4e7bc): the master roadmap —
  three parity tiers, milestones M13..M30 with published-value gates.
- M13 PHASE 1 LANDED (58ca76c, 5c8a3ed): pytcad/fermi.py (complete
  F_{1/2}, F_{-1/2}, derivative, bracketed inverse, ni_fd; hybrid
  fixed-node Gauss-Legendre: s^2 transform on [0,1] + width-2
  t-panels beyond — O(1) transition width for every eta). G1-G3
  gates green: <=1e-9 vs independent quadrature, 30-digit mpmath
  spot audit, Boltzmann limit at exact-series deviations, Sommerfeld
  rate check, inverse roundtrip, eta-range refusal. G6a goldens
  captured PRE-core-edit (tests/goldens/m13/: 1D diode eq+bias, 1D
  Si/GaAs hetero, 2D diode, 3D resistor; array_equal enforced).
  Amendment sign-off for the core edit: RECORDED AS GIVEN in
  M13-FERMI-DIRAC-PLAN.md Status block.

## STATE ADDENDUM -- M13 PHASE 2 LANDED IN THE WORKING TREE (2026-08-26,
UNCOMMITTED at handoff; user decides commit/push)
All M13 gates GREEN (see M13-FERMI-DIRAC-PLAN.md "PHASE-2 STATUS").
Suite: 564 passed, zero warnings (541 prior + 23 new gate tests in
pytcad/tests/test_m13_solver.py; pre-existing tests unchanged except
the two catalog/wire-format pin points listed below).
- Design spike RESOLVED: scheme A (nu-factor modified SG), recorded in
  plan section 3.2bis. Exact equilibrium detailed balance for BOTH
  carriers incl. heterointerfaces; bit-level Boltzmann reduction via an
  eta<=-30 exact-zero branch.
- device.py: physical Nc/Nv FD statistics (n=Nc F(eta_n),
  eta_n=psi-ln(Nc/nie)-phi_n); fd_density/fd_ddensity_deta with the
  asymmetric eta policy (exact Boltzmann tail below -40, loud refusal
  above +40); recombination driving force np-nie^2*nu_n*nu_p (SRH/Auger
  via new optional args to materials.recombination, TAT mirrored);
  incomplete ionization (g_D=2/g_A=4, dE=45 meV) INDEPENDENT of the fd
  flag (works under Boltzmann too); moscap fd branch for G7d;
  band_diagram uses physical-statistics quasi-Fermi levels under fd.
- f_half_inv optimized (split analytic-tail + secured Newton);
  phase-1 gates re-verified unchanged; suite runtime ~5 min.
- Wire format: _default_models() gains fd/incomplete_ion (OFF) keeping
  ModelCatalog.default_config() == _default_models() invariant; two
  pre-existing pin tests updated accordingly (catalog key set, wire
  default dict) -- the ONLY touched pre-existing tests.
- SPEC-FIX (G6b): original 1e-6 density tolerance unattainable --
  exact-series nu correction at 1e16 cm^-3 is 1.24e-4; gates now derive
  from exp(eta)/2^{3/2} (mirrors the phase-1 G2 precedent).
- Catalog: fd + incomplete_ion entries with equations/references/
  applicability/limits (G7 metadata requirement).

## NEXT (priority order)
1. Commit the M13 working tree (user decides message/split).
2. M15 prep (impact ionization solver coupling) -- UNBLOCKED: the full
   M13 gate battery G1-G8 is green across 1D/2D/3D (suite 570 passed,
   zero warnings; +6 port tests in tests/test_m13_solver.py).
2D/3D PORT NOTES (for future sessions): shared helpers live in
pytcad/device.py (fd_node_factors, fd_ohmic_values, fd_density with
the exact Boltzmann tail below eta=-40 and loud refusal above +40);
Device2D/Device3D carry fd DOS scalars, eta-space bulk guesses, FD
contacts, per-axis delta modifications (+dL_n electrons / -dL_p holes)
and the verified density-column Jacobian chains. GOTCHA that cost a
debug cycle: the full-residual Poisson assembly in device2d/device3d
REUSES the dx/dy edge differences -- under fd those carry modified SG
deltas, so the Poisson fluxes must be recomputed from PURE potential
differences (fixed in both cores; the FD-Jacobian port gate catches
it). Incomplete ionization stays 1D-only (plan section 3.3).

## OPEN ITEM (was M13 phase 2 -- SUPERSEDED by the addendum above)

## HARD RULES (never break)
- pytcad/pytcad numerical core: changes ONLY under the M11-S3-style
  amendment mechanism (sign-off recorded in the plan file, goldens
  committed before the edit, FD-Jacobian-first, bit-identity off-path).
- Layering: QML → controllers → services → QProcess subprocess → npz →
  ResultStore → canvas. Controllers/visualization never import pytcad.
- DeviceSpec stays the wire format. Subprocess isolation per run kept.
- Every slice: suite green w/ pre-existing tests UNCHANGED, adversarial
  probe pass BEFORE commit, optional deps stay optional.
- Gate-bearing milestones block their dependents until ALL gates green
  ("mostly green" = hidden failure).

## HOW WE WORK
Plan → user approves → TDD (tests red first) → implement → hard debug
(fuzz/probe the new code adversarially, fix, regression tests) → commit
(user pushes). Honesty over polish: report blockers, document limits.

## NEXT (priority order)
1. M13 PHASE 2 (see OPEN ITEM above) — design spike for the FD-SG
   scheme, then density path + G4/G5 gates, then incomplete ionization,
   then G7 benchmarks, then 2D/3D ports.
2. M11-S4: 2D heterojunction box-integration (designed,
   HETEROSTRUCTURE-PLAN.md section 7) — independent of M13.
3. M11-S5: HBT/HEMT templates + UI.
4. M15 (impact ionization solver coupling) AFTER M13 gates green;
   devsim edge_volume blocker record: benchmarks/README-devsim-II-blocker.md.

## GOTCHAS LEARNED THE HARD WAY (new this session; older ones in AGENTS.md)
- bash tool cwd RESETS to /home/nihal between calls — always cd or pass
  workdir; the #1 cause of lost edits this session.
- str.replace patches SILENTLY no-op on stale strings — assert the
  replace applied.
- xhtml2pdf: white-space:pre-wrap on <pre> collapses newlines; &sup6;
  is NOT a real HTML entity and U+2076 is missing from the embedded
  font (renders as a box) — use <sup>6</sup>.
- mpmath mp.quad on [0, inf) under-resolves the t~eta knee of the
  Fermi integral (5e-5 off at eta=40) — subdivide [1, eta+20, inf].
  Audit your audit: scipy AND mpmath were both checked against the
  published Sommerfeld series.
- The complete Fermi integral's Boltzmann-limit deviation is
  e^eta/2^{3/2} (exact Taylor series) — set limit gates from the
  published math, not from round numbers (original G2 gates were
  unattainable; spec-fix documented).
- Writing a doc in two parts to the SAME path truncates it — the
  second write replaces the whole file (bit us on
  M13-FERMI-DIRAC-PLAN.md; restored in 5c8a3ed).
- familySweep.configureFamily's FIRST arg is the STEPPED CONTACT NAME
  (string), not a bool — passing False yields "Family cannot run".
- ViewportPanel.setViewMode takes INTERNAL mode names ("series",
  "bands"), not display names ("Curves", "Bands") — wrong name
  silently renders a field map instead.
- np.polynomial.legendre.leggauss is module-level (not
  Legendre.leggauss) in numpy 2.5.
