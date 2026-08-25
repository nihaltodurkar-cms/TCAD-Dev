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

## OPEN ITEM -- M13 PHASE 2 (1D core FD integration; nothing started)
Per M13-FERMI-DIRAC-PLAN.md sections 3-4. Remaining gates:
- G4: charge-neutrality consistency (uniform-doping root-finds,
  generalized mass action, degenerate V_bi)
- G5: FD-Jacobian on degenerate step junction + degenerate Si/GaAs
  heterointerface + incomplete-ionization rows (<=5e-5, house gate)
- G6b/c: fd=True nondegenerate equivalence (<=1e-6 densities,
  <=1e-4 currents); TAT/hetero paths fd=False bit-identity
- G7: published benchmarks (degenerate n/N_D vs Altermatt-style,
  B freeze-out 77K, degenerate C_max direction) with applicability
  limits in docstrings + catalog
- Design spike FIRST: pick generalized-SG scheme (nu-factor vs
  inverse-FD) by the detailed-balance gates — see plan section 3.2;
  the M11 lesson (shared delta passed Jacobian, broke hole detailed
  balance) is the reason the gate list is carrier-specific.
- Incomplete ionization behind Models(incomplete_ion=False), 1D only.
- 2D/3D ports repeat bit-identity + Jacobian + neutrality gates.
M15+ BLOCKED until every gate green (parity-plan standing rule 4b).

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
