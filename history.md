# PROJECT HISTORY — for the next AI session
Read this + ARCHITECTURE.md (roadmap §4/§7) + gui/README.md before doing anything.

## AIM
Evolve PyTCAD into a Semiconductor Workbench: an open, modular,
understandable learning+research TCAD environment (DEVSIM/Silvaco/
Sentaurus class). REAL physics only — every educational surface backed
by actual computation. Never fake, never mock, never weaken tests.

## STATE (as of this handoff)
Suite: 523 passed + 4 skipped (M12-S2 TAT red tests), ZERO warnings
(excluding the 2 openly-failing uncommitted M12-S2 tests described
below -- working tree is dirty BY DESIGN, do not commit as-is).
Tag v0.5.0 pushed. Python 3.14, PySide6, devsim 2.11 (optional dep).

SHIPPED SINCE v0.5.0 TAG:
- C-V physics validation: tests/test_cv_physics_validation.py, 15
  quantitative gates (Poisson residuals, neutrality, Gauss balance,
  regime ordering, series-C + doping recovery, Cmin/Wmax vs theory,
  flatband/threshold turning points, LF-vs-HF, convergence, T-sweep,
  Vfb decomposition). Conventions learned: rho balances Qg SAME-sign;
  inversion at POSITIVE phi_s for p-substrate.
- MOS C-V GUI mode: gui/services/moscap_runner.py + CVController +
  SweepPanel section. GOTCHA: cv controller needed a @Property
  ("cvSweep") -- plain attribute was invisible to QML.
- Batch family sweeps: FamilySweepController (own JobRunner,
  sequential), canvas overlay, SweepPanel FAMILY section.
  Fixes: re-entry guard, direction validation, stepper contact sync.
- 2D Bands/Recombination viewport maps (heatmap decision).
- M11-S1/S2: Ge/GaAs/InGaAs/AlGaAs material sets; DomainDevice accepts
  known hetero materials; enforcement moved to adapters/spec.py
  (_refuse_unsolvable_regions) + solver_runner device-material guard;
  DeviceSpec.region_materials wire field with parse-time validation.
- M11-S3 1D HETEROJUNCTION CORE: per-node material lists in Device1D,
  eps(x) harmonic-mean flux form (uniform => algebraically identical),
  band-offset SG deltas, per-material recombination. Acceptance:
  FD-Jacobian across Si/GaAs interface <5e-5, Anderson step incl
  electrostatic share, equilibrium detailed balance exact.
  GOTCHA: hole delta = dpsi - dln(nie) (OPPOSITE sign to electron);
  shared delta passed FD-Jacobian but broke hole detailed balance --
  only a hole-side equilibrium check can catch that class.
- M12-S1 tunneling: workbench/physics/tunneling.py (FN + WKB),
  published-constant gates. GOTCHA: B = 4 sqrt(2 m_e q)/(3 hbar) --
  the 4/3 is the triangular-barrier integral; q belongs under the root.

## OPEN ITEM -- M12-S2 TAT (working tree dirty, ~90% done)
Implementation in pytcad/device.py (Models.tat flag, frozen-field WKB
P_n/P_p, recombination-block extension with analytic derivatives).
FD-Jacobian test PASSES. TWO FAILING TESTS remain, precisely scoped:
1. test_charge_neutrality_with_traps: absolute rho<1e-6 criterion hits
   an equilibrium residual floor of exactly ~1.0 scaled near the
   junction -- needs relative criterion or investigation of the 1.0.
2. test_silc_style_field_enhancement_monotone: WKB exponents underflow
   at bulk-diode fields (need ~1e7 V/cm); construct deliberate field
   scale (near-band-edge trap et_rel~0.999 or thin-barrier framing).
3. ALSO probe solve_bias([0,-vr]) early-return paths: _Pn stayed None
   after reverse-bias solves in one run.
Red tests live in tests/test_m12_tat.py; equations in
TUNNELING-PLAN.md section 5. Do not commit until green.

## HARD RULES (never break)
- pytcad/pytcad numerical core: NO changes except exposing values it
  already computes. Tolerances/scaling untouchable.
- Layering: QML → controllers → services → QProcess subprocess → npz →
  ResultStore → canvas. Controllers/visualization never import pytcad.
- DeviceSpec stays the wire format. Subprocess isolation per run kept.
- Every slice: suite green w/ pre-existing tests UNCHANGED, adversarial
  probe pass BEFORE commit, optional deps stay optional.

## HOW WE WORK
Plan → user approves → TDD (tests red first) → implement → hard debug
(fuzz/probe the new code adversarially, fix, regression tests) → commit
(user pushes). Honesty over polish: report blockers, document limits.

## NEXT (candidate directions, nothing queued yet)
1. COMPLETE devsim impact-ionization coupling: signs calibrated
   (+/+ both continuity equations, verified vs node-model ground
   truth), manual alpha Jacobian entries written, equation rewiring
   recipe proven. Remaining gap: generation's CURRENT-dependence is
   frozen out of the Jacobian -> marginally stable Newton beyond ~0.5 V.
   Needs upstream guidance or flux-folded discretization. Full record:
   pytcad/benchmarks/README-devsim-II-blocker.md + prototype script.
2. [DONE 9203975] 2D band/recombination maps: heatmap chosen over
   cut-plane; observables are element-wise so no physics changes.
3. Multi-material / heterostructure Regions to unlock BJT/HEMT templates
   (largest architectural item -- plan carefully).
4. C-V beyond the validated moscap path; batch/multi-parameter sweeps.

## GOTCHAS LEARNED THE HARD WAY
- devsim mesher adds nodes if ps < segment length → use FULL spacing.
- devsim solve() is PROCESS-GLOBAL (no device= arg) → delete your
  device+mesh in a finally block or stale states fail later solves.
- pytest warning filters are REGEX: escape '^' ("cm\^-3") or they
  silently never match.
- Qt writes QML warnings via a cached C stream, NOT sys.stderr/qInstall
  MessageHandler for Python-side TypeErrors → test teardown noise by
  asserting QObject ownership, not by capturing stderr.
- Engines ship different tabulated ni → cross-backend psi agrees only
  to ~25mV; compare against analytic Vbi too.
- Implant windows beyond substrate length silently no-op → validate_flow
  rejects them now; keep that guard.
- Qt context property names must match QML exactly ("deviceBuilder").
- Parent AppController to the engine in create_engine() or teardown
  spews null-binding TypeErrors.
- Checkpoint npz uses FLAT keys (species_P), not nested dicts.
