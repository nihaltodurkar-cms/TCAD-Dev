# PROJECT HISTORY — for the next AI session
Read this + ARCHITECTURE.md (roadmap §4/§7) + gui/README.md before doing anything.

## AIM
Evolve PyTCAD into a Semiconductor Workbench: an open, modular,
understandable learning+research TCAD environment (DEVSIM/Silvaco/
Sentaurus class). REAL physics only — every educational surface backed
by actual computation. Never fake, never mock, never weaken tests.

## STATE (as of this handoff)
Suite: 481 passed, ZERO warnings (pytest.ini policy). Tagged v0.5.0. Python 3.14, PySide6, devsim 2.11 installed (optional dep).
SHIPPED: M1 domain core+ModelCatalog; M2 RunRecord+schema v2; M3 store/
analysis boundaries + SolverBackend protocol; M4 Physics Lab foundation;
M5 device templates (NMOS golden == shipped example); M6 checkpoints→
DomainDevices + per-region implants; M7 GENUINE devsim backend now WITH
bias ramps + sweeps, cross-backend I-V validated (~2x constant offset
from tabulated ni), per-stage converge__trace; M8/M9/M10 first slices.
Also fixed: devsim 1D schema conformance (no fake terminal keys),
devsim global solve() state leak (device+mesh deleted per run), GUI
teardown ownership (lab/builder are Qt children of AppController).

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
