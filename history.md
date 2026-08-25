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

## NEXT (priority order, details in ARCHITECTURE.md §7)
1. M6 UI: surface x_range_cm implants + checkpoint→device in ProcessPanel.
3. M9 plots: band diagram / recombination viewport modes from
   workbench/analysis; model on/off comparison runs.
4. M8 first new physics model (thermionic or impact ionization) — MUST
   land with a published-value benchmark test first.
5. M10 growth: sweep/bias deck statements + file-open UI.
6. Release pass: gui/README final wording, tag v0.5.0.

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
