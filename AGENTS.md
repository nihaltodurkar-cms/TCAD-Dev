# AGENTS.md — Guidance for AI agents working on PyTCAD

Read this before doing anything. Then read `history.md` (current
state + open items), `ARCHITECTURE.md` (roadmap + live queue),
`SENTAURUS-PARITY-PLAN.md` (the governing future plan, M13-M30), and
the active milestone spec (`M13-FERMI-DIRAC-PLAN.md` while M13 is in
flight).

## What this is

PyTCAD: a validated TCAD toolkit (1D/2D/3D drift-diffusion, process
simulation) plus a Semiconductor Workbench layer (`workbench/`) and a
PySide6/QML desktop GUI (`gui/`). Every educational surface must be
backed by real computation. Never fake, never mock, never weaken tests.

## Layout

```
pytcad/            numerical core (device.py, device2d.py, device3d.py,
                   moscap.py, process.py, materials.py, mesh*.py)
workbench/
  core/            domain objects (Region, DomainDevice, ModelCatalog,
                   MaterialLibrary, templates)
  adapters/        lossless DomainDevice <-> DeviceSpec conversions
  solvers/         SolverBackend protocol + pytcad & devsim backends
  analysis/        observables (band_diagram, recombination_rate, ...)
  physics/         analysis-layer physics (impact_ionization,
                   tunneling) -- published-value gated
  workflow.py      deck front end (TEMPLATE/BIAS/SWEEP statements)
gui/
  services/        DeviceSpec (wire format), JobRunner (subprocess),
                   ResultStore, solver_runner/moscap_runner/process_runner
  controllers/     AppController + small per-domain controllers
  qml/             Main.qml, panels/, components/, Theme.qml
tests/             core validation (incl. test_model_benchmarks.py --
                   new physics MUST land here first)
gui/tests/         GUI-level tests (headless QML pattern)
HETEROSTRUCTURE-PLAN.md / TUNNELING-PLAN.md   M11/M12 plans w/ design notes
```

## Commands (run from `pytcad/`)

```bash
python3 -m pytest tests/ gui/tests/ -q     # full suite (~2 min)
python3 -m pytest tests/test_model_benchmarks.py -q   # physics gates
QT_QPA_PLATFORM=offscreen python3 -m gui.app          # live app
python3 examples/01_pn_diode.py            # examples 01..05
```

Suite invariant: **N passed, zero warnings**. `pytest.ini` exempts one
intentional warning; anything new must be fixed at source or asserted
with `pytest.warns` in the test that intends it.

## Hard rules

- Numerical core (`pytcad/*.py`): frozen EXCEPT where a milestone plan
  explicitly amends it (M11-S3 did for Device1D heterojunctions;
  M12-S2 added TAT). Any further core change needs the same explicit
  sign-off + FD-Jacobian-first + bit-identical-off-path gates.
- Layering: QML -> controllers -> services -> QProcess subprocess ->
  npz -> ResultStore -> canvas. Controllers/canvas never import pytcad.
- `DeviceSpec` stays the wire format. Subprocess isolation per run.
- New physics model = published-value benchmark in
  `tests/test_model_benchmarks.py` FIRST + catalog metadata.
- Optional deps stay optional (devsim auto-detected).
- Every slice: suite green with pre-existing tests unchanged, an
  adversarial probe pass BEFORE commit, honesty over polish (report
  blockers, don't hide failures, don't ship fudge factors).
- Do not commit automatically unless told; user pushes.

## Workflow

Plan -> user approves -> TDD (red first) -> implement -> hard debug
(fuzz/probe adversarially, run live app/examples) -> commit.
Working tree may be left dirty ONLY with openly-failing tests and a
precise handoff note in history.md (see M12-S2 precedent).

## Gotchas learned the hard way (each cost a debugging session)

**devsim**
- `solve()` is PROCESS-GLOBAL (no device= arg): delete your
  device+mesh in a finally block or stale states fail later solves.
- mesher adds nodes if ps < segment length -> use FULL spacing.
- Engines tabulate ni differently -> cross-engine psi agrees only to
  ~25 mV and I-V to a constant factor ~2; anchor each engine to
  analytic values instead of pointwise comparison.
- `solve(info=True)` returns {'converged', 'iterations'} -- use it.

**QML / PySide6**
- Plain Python attributes are INVISIBLE to QML property lookup:
  every controller handed to QML needs a @Property(QObject).
  (Bit twice: treeModel/consoleModel, then cv controller.)
- Context-property controllers must be Qt children of their parent
  controller, not bare attributes -- else shutdown GC races QML
  bindings and prints TypeError spam. Test ownership via shiboken
  validity after engine teardown, not by capturing stderr (Qt writes
  through a cached C stream that fd redirection misses).
- Reading `.visible` reflects EFFECTIVE visibility through hidden
  ancestors (StackLayout/tabs): headless tests must activate the
  right tab before asserting child visibility.
- Guard new bindings against null during teardown (`canvas ? ...`).

**Python/testing**
- pytest warning filters are REGEX: `cm^-3` never matches (caret =
  anchor); escape as `cm\^-3`.
- str.replace() patches SILENTLY no-op on stale strings -- always
  assert the replace applied ("assert old in s").
- The bash tool's cwd RESETS to /home/nihal between calls -- always
  `cd` or pass workdir; the #1 cause of lost edits.
- Writing a doc in two parts to the SAME path truncates it (second
  write replaces the file) -- write once, or append via bash.
- Keep engine/QObject references alive in tests: dropping the engine
  reference lets GC destroy the whole QML tree mid-test.
- Heredocs double backslashes: check line continuations after
  writing test files through bash.
- np.polynomial.legendre.leggauss is module-level (not
  Legendre.leggauss) in numpy 2.5.
- GUI controller APIs: familySweep.configureFamily's FIRST arg is the
  STEPPED CONTACT NAME (string); ViewportPanel.setViewMode takes
  INTERNAL mode names ("series"/"bands"), not display names
  ("Curves"/"Bands") -- wrong names silently no-op or render the
  wrong view.
- np.trapezoid is the modern name; scipy.sparse diags order (lo,main,up).

**Physics/model conventions (empirically established)**
- MOSCapacitor rho balances Qg SAME-sign; inversion sits at POSITIVE
  phi_s for p-substrate; abrupt-junction discretization leaves rho=+-1
  exactly at the two doping-step nodes (global charge balance is the
  correct neutrality criterion, not node-wise).
- Heterojunction SG deltas: electron dpsi + dln(nie), hole
  dpsi - dln(nie) -- OPPOSITE signs; shared delta passes FD-Jacobian
  but breaks hole detailed balance. Only a carrier-specific
  equilibrium detailed-balance check catches it.
- TAT WKB factors are SI-calibrated (F in V/m): mixing V/cm underflows
  every probability and silently reduces TAT to SRH. Bulk-Si midgap
  TAT underflows to exactly 0 at any realizable field -- gate the
  factor law over synthetic fields, assert device-level enh==1.0 as
  honest physics.
- devsim ni tables differ from pytcad's -> cross-backend I-V agrees
  only to a constant ~2x factor.
- Implant windows beyond substrate length must be rejected by
  validate_flow (keep that guard).
- Checkpoint npz uses FLAT keys (species_P), not nested dicts.
- 1D sweep channel name is "device", not the contact name.
- Fermi integral: Boltzmann-limit deviation is exp(eta)/2^{3/2}
  (exact Taylor series) -- set limit gates from the published math,
  not round numbers. mpmath mp.quad on [0, inf) under-resolves the
  t~eta knee (5e-5 off at eta=40): subdivide [1, eta+20, inf].

## Milestone state & plans

Governing roadmap: `SENTAURUS-PARITY-PLAN.md` (three parity tiers,
M13-M30, gate-blocking rule 4b). Completed: M1-M10 (v0.5.0 tagged),
M11-S1/S2/S3 (heterostructure materials/wire/1D core), M12-S1+S2
(FN/WKB + Hurkx TAT, all gates green), M13 phase 1 (fermi.py +
G1-G3 gates + G6a pre-edit goldens; 541 tests, zero warnings).
ACTIVE: M13 phase 2 (1D core FD integration, gates G4-G8; amendment
sign-off recorded in M13-FERMI-DIRAC-PLAN.md). BLOCKED until M13
green: M15+ (parity-plan rule 4b). Open & independent: M11-S4 (2D
heterojunctions), M11-S5 (HBT/HEMT templates). Live queue:
ARCHITECTURE.md sections 5-7; session detail: history.md.
