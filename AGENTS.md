# AGENTS.md — Guidance for AI agents working on PyTCAD

This file is the complete briefing for working on this repo -- it does
not assume you have seen any prior conversation, and it does not assume
any particular model. Read it in full before touching any file, and
follow it literally: where it says a file is frozen, do not edit it;
where it says run the tests, actually run them and read the real
output rather than assuming the change worked; where it gives a
concrete gotcha below, that gotcha has already cost a real debugging
session once and will cost another if repeated. If anything here
conflicts with what a user asks for in a specific conversation, say so
and ask, rather than silently picking one.

Read this before doing anything. Then read `history.md`
(current state + open items -- read at least its LAST few entries,
not just this file, since state changes faster than this file is
updated), `ARCHITECTURE.md` (roadmap + live queue,
including the governing future plan in section 4b, M13-M30), and
the active milestone spec -- as of 2026-08-31 the only genuinely OPEN
core-solver item is `pytcad/M14-SURFACE-MOBILITY-PLAN.md`'s G-A
(blocked on a paywalled source); M16/M17/M18/M19/M20/M21/M22 are all
landed for their stated scope (see "Milestone state & plans" below and
each milestone's own plan doc for exactly what that scope was and
what's honestly still deferred). Also read `pytcad/GUI-IMPROVEMENT-
PLAN.md` and `pytcad/3D-VISUALIZATION-PLAN.md` for GUI-side state.

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
                   ResultStore, solver_runner/moscap_runner/process_runner,
                   examples.py (File-menu quick-load DeviceSpecs, 1D/2D/3D),
                   viewer3d.py (PyVista/VTK 3D viewer, a separate QWidget
                   window -- see 3D-VISUALIZATION-PLAN.md)
  controllers/     AppController + small per-domain controllers
  qml/             Main.qml, panels/, components/, Theme.qml
tests/             core validation (incl. test_model_benchmarks.py --
                   new physics MUST land here first)
gui/tests/         GUI-level tests (headless QML pattern)
ARCHITECTURE.md sec 4b   governing roadmap M13-M30
pytcad/M14-SURFACE-MOBILITY-PLAN.md   the one genuinely OPEN item (G-A)
pytcad/M16-BTBT-PLAN.md / M17-TRANSIENT-PLAN.md / M18-AC-PLAN.md /
  M19-SELFHEATING-PLAN.md / M20-DENSITY-GRADIENT-PLAN.md /
  M21-MESHING-PLAN.md / M21-PHASE3-MESHING-PLAN.md /
  M22-LINSOLVE-PLAN.md   milestone plans (numerical core); all LANDED
  for their stated scope as of 2026-08-31 -- read each one's own
  "honest limits" section for what's deliberately still deferred
pytcad/GUI-IMPROVEMENT-PLAN.md   GUI feature roadmap (Phases 1-4 shipped)
pytcad/3D-VISUALIZATION-PLAN.md   PyVista/VTK 3D viewer roadmap
  (Phases 1-5 SHIPPED: 3D example, isosurface viewer, volumetric
  rendering, animated bias-sweep playback, exploded structural view)
history.md   session-by-session state + handoff notes
```

## Commands (run from `pytcad/`)

```bash
# fast dev loop (~70s): parallel, skips the multi-minute M15/M22 "slow" gates
python3 -m pytest tests/ gui/tests/ -n 6 -m "not slow" -q
# slow gate battery: must run before any milestone completion claim
python3 -m pytest tests/ gui/tests/ -n 6 -m "slow" -q
python3 -m pytest tests/ gui/tests/ -q     # full suite, serial (~4 min)
python3 -m pytest tests/test_model_benchmarks.py -q   # physics gates
QT_QPA_PLATFORM=offscreen python3 -m gui.app          # live app
python3 examples/01_pn_diode.py            # examples 01..05
```

One `pip install -r requirements.txt` (repo root: `pytcad/requirements.txt`)
covers the library, GUI, tests, and all optional deps (gmsh, devsim,
mpmath) -- verified on Linux and Windows. Run it once.
Cap workers at `-n 6` on this machine (not `-n auto`) -- more workers
oversubscribe available memory/cores.  Set `OPENBLAS_NUM_THREADS=1` (or
export it in your shell) when running in parallel: numpy/scipy's BLAS
otherwise spawns its own thread pool PER WORKER, oversubscribing the
CPU across all `-n` workers simultaneously and making the run slower,
not faster.  Running the two heavy M15 breakdown-ramp "slow" tests
concurrently with everything else also slows the whole run down (CPU
contention on the tests that need it least) -- run `not slow` and
`slow` as two separate invocations, not one.

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
- Optional deps stay optional (devsim auto-detected). EXCEPTION,
  deliberate: pyvista/pyvistaqt (in requirements.txt) are a HARD
  dependency of gui/ -- the 3D viewer (gui/services/viewer3d.py,
  3D-VISUALIZATION-PLAN.md) imports them unconditionally at module
  level, discussed and approved with the user, not an oversight.
  Do not silently make it optional/guarded to match the devsim
  pattern without asking first.
- Every slice: suite green with pre-existing tests unchanged, an
  adversarial probe pass BEFORE commit, honesty over polish (report
  blockers, don't hide failures, don't ship fudge factors).
- Do not commit automatically unless told; user pushes.
- Never claim a change works, a bug is fixed, or the suite is green
  without ACTUALLY RUNNING the command and reading its real output --
  not "this should work," not inferring pass/fail from reading the
  diff. If a run is still in progress, say so; don't guess the result.
- Never write a doc/history entry naming a file, function, or class
  you have not confirmed exists (grep or Read it first). A prior
  session's history.md entry claimed new files
  (`provenance_model.py`, `continuation_data.py`) that were never
  actually created -- the real logic landed in `lab_controller.py`
  and `solver_backend.py` instead. Do not repeat that mistake, and do
  not trust that specific entry's file list.

## Workflow

Plan -> user approves -> TDD (red first) -> implement -> hard debug
(fuzz/probe adversarially, run live app/examples) -> commit.
Working tree may be left dirty ONLY with openly-failing tests and a
precise handoff note in `history.md` (see M12-S2
precedent).

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
- A binding built from `&&`/ternary can hand QML a raw `null`/
  `undefined` instead of a real `false` (e.g. `a && a.b && a.b.c`
  evaluates to `null` when `a.b` is null, not `false`) -- assigning
  that to a `bool` property (`enabled:`, `visible:`) logs "Unable to
  assign [undefined] to bool" every time. Wrap the whole expression
  in `!!(...)` so it always resolves to a real boolean.
- `gui/app.py` MUST construct `QApplication` (QtWidgets), not
  `QGuiApplication` -- the 3D viewer (`gui/services/viewer3d.py`)
  opens a real `QMainWindow`, and `QWidget` construction hard-ABORTS
  THE WHOLE PROCESS if only a `QGuiApplication` exists ("QWidget:
  Cannot create a QWidget without QApplication" -- confirmed by
  reproducing it, not by reading docs). `QApplication` is a strict
  superset of `QGuiApplication` (QML behaves identically under it),
  so there is never a reason to use the narrower class once any
  QtWidgets code exists anywhere in the app. Qt's application
  singleton is fixed by whichever subclass constructs it FIRST in a
  process and can never be upgraded afterward -- this is why
  `gui/tests/conftest.py`'s session-scoped `_qt_application` fixture
  must also construct `QApplication`, ahead of every test file's own
  `gapp` fixture, not just the app's own bootstrap.
- `pyvistaqt.QtInteractor` (VTK's live render window) does its OWN
  windowing-system calls independent of Qt's platform plugin --
  `QT_QPA_PLATFORM=offscreen` does not make it headless, and building
  one under it raises an X11 `BadWindow` error, not a clean no-op
  (confirmed directly). `pyvista.Plotter(off_screen=True)` DOES work
  offscreen (VTK's own separate off-screen path) -- that asymmetry is
  real, not a configuration mistake to try to fix. To test code that
  builds a `Viewer3DWindow`, monkeypatch `viewer3d.QtInteractor` to a
  small fake recording `add_mesh`/`remove_actor` calls (see
  `gui/tests/test_viewer3d.py`'s `FakeInteractor`) -- this still
  exercises the REAL `QMainWindow`/`QComboBox`/`QDoubleSpinBox` widget
  tree and signal wiring, just not the actual GL surface.

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
- scipy's spsolve is NOT format-invariant: SuperLU solves CSR natively
  via a format flag rather than converting to CSC first, so
  spsolve(A_csr, b) and spsolve(A_csr.tocsc(), b) differ at ~1e-16
  relative error, not bit-identical -- a linear-solve wrapper that
  claims "exactly spsolve, bit-identical" must never reformat A for the
  direct method, or it silently breaks bit-identity golden gates (see
  pytcad/linsolve.py's solve_linear, M22 G2).
- a size/dimensionality GATING computation (e.g. "only for 3D jobs
  above N nodes") must have its OWN guard checked first -- writing the
  gate's math as a bare statement before the `if` that's supposed to
  protect it runs it unconditionally. Confirmed directly: an x-axis
  doping-variation check for gui/services/solver_runner.py's MPI-
  Schwarz gate called `doping.max(axis=2)` before checking
  dimensionality == 3, and broke EVERY 1D/2D job in gui/tests
  (AxisError -- a 1D array has no axis 2) -- caught only because the
  FULL suite (590 tests) was run before calling the change done, not
  just the handful of 3D-specific tests that seemed relevant. Run the
  whole suite after touching a shared dispatch function, not the
  subset the change is "about".
- clamping an out-of-range value to survive a TRANSIENT Newton overshoot
  (e.g. eta > FERMI_ETA_MAX during iteration) must not also clamp the
  FINAL, converged answer -- that silently defeats whatever loud-refusal
  check the clamp was protecting against, for the one case (a genuinely
  invalid converged state) it exists to catch. Clamp only the trial
  evaluation inside the loop; check the raw, unclamped value once more
  after convergence.
- sha256/np.array_equal "bit-identity" golden values (tests/goldens/
  m13/*.npz, test_m13_solver.py's TAT_EQ_DIGEST/TAT_FW_DIGEST/
  HETERO_FW_DIGEST) pin ONE machine's numpy/scipy/BLAS build's exact
  floating-point summation order, not portable solver behavior --
  confirmed directly merging a parallel branch 2026-09-04: goldens/
  digests re-captured in a different sandbox failed bit-identity here
  even with byte-identical code and byte-identical frozen_meshes.npz
  (a pure-Python/numpy mesh-coordinate array IS portable; a Newton-
  solve OUTPUT is not). Fix is the same either way: regenerate ON THE
  TARGET MACHINE (PYTCAD_REGEN_M13_GOLDENS=1 for the .npz goldens;
  recompute via the test module's own _digest() for the hardcoded
  hex-string ones), verify physical sanity (finite, correct sign/
  magnitude/positivity) before trusting the new value, never copy
  golden bytes or digest strings between machines/sandboxes.
- a safety gate built from ONE physical hazard does not automatically
  cover a DIFFERENT hazard that happens to correlate with the same
  axis/parameter. Confirmed directly 2026-09-04: gui/services/
  solver_runner.py's MPI-Schwarz split-axis picker checked only
  doping-gradient safety, which correctly judged finfet_3d's z-axis
  doping-uniform -- but a GateBC's Robin/oxide-coupling term runs
  along its own `normal_axis` (z, for finfet_3d's side gates)
  regardless of doping, a geometric/electrostatic confinement
  mechanism the doping check has no way to see. Result: a silently
  WRONG (1.4e-3 relative field error, vs. ~1e-17 for the gate-free
  devices the path was validated on) AND SLOWER (4.1x) production
  result for any gated 3D device above the size gate, caught only by
  actually exercising a "should be safe by the existing check" case
  end to end rather than trusting the check's own reasoning. Fix was a
  SECOND, independent exclusion (any axis matching a registered gate's
  normal_axis), not a tweak to the first. When adding a safety/gating
  heuristic, ask what OTHER mechanisms could break the same invariant
  before trusting one check to cover the whole risk.

**Physics/model conventions (empirically established)**
- Device3D's ENTIRE dimensionless scaling (Ns, LD, J0, and even the
  mesh coordinates themselves -- xs = mesh.x / LD) is derived from
  max(|doping|) OF WHATEVER ARRAY THE DEVICE WAS BUILT WITH, not a
  device-wide constant stored anywhere else. Two Device3D instances
  covering different SLICES of the same physical device (MPI Schwarz
  domain decomposition, gui/services/mpi_schwarz_runner.py) silently
  disagree on units unless BOTH are pinned to the same reference via
  the new `Ns_override` constructor param, computed once from the
  FULL device's own doping array -- confirmed as a real risk by
  reading the __init__ code before any correctness testing, not found
  by a failure. Any future per-subdomain or per-region Device3D
  construction needs the same pinning.
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

Governing roadmap: `ARCHITECTURE.md` section 4b (three parity tiers,
M13-M30, gate-blocking rule 4b.4). Completed: M1-M10 (v0.5.0 tagged),
M11-S1..S5 (heterostructure materials/wire/1D+2D core, HBT/HEMT
templates), M12-S1+S2 (FN/WKB + Hurkx TAT, all gates green), M13
(Fermi-Dirac + incomplete ionization, G1-G8 all green -- unblocked
M15+ per parity-plan rule 4b once green), M15 impact ionization
(coupled Jacobian + continuation driver, all gates green -- see
pytcad/M15-IONIZATION-PLAN.md and ARCHITECTURE.md section 5).
MILESTONE-BY-MILESTONE STATE (only M14's own G-A below is genuinely
OPEN; M16-M22 are landed for their stated scope -- read each entry for
what that scope actually was and what's honestly still deferred):
  M14 surface mobility -- MOSTLY COMPLETE: mobility_cvt() wired for
    Device2D.models.surface_mobility (G-D/G-E green); G-B (D_it) and
    G-C (S_n/S_p surface recombination velocity, a Robin flux-balance
    BC) are green in BOTH Device1D and, as of 2026-08-31, Device2D --
    the 2D fix reuses the already-computed box-integration residual
    instead of deriving per-edge boundary stamps, generalizing to any
    contact shape with no per-edge logic; one honest limitation found
    (Newton convergence for a deep-minority-carrier contact under
    reverse bias can be non-monotonic, traced to an interaction with
    the M11-S5 density-floor safeguard, not fixed). Only G-A (absolute
    curve vs Takagi/Taur) remains xfail'd -- 2026-08-28 research
    confirmed the real Lombardi phonon term is two-part and doping-
    dependent (this code has a one-term stand-in), but the numeric
    constants are blocked on the 1988 primary source, which is
    paywalled with zero open-access copies (verified via Unpaywall);
    re-searched fresh 2026-08-31 (Darwish-model alternative, DEVSIM/
    MINIMOS-NT source, academia.edu mirrors) with no new result. See
    pytcad/M14-SURFACE-MOBILITY-PLAN.md's "G-A LITERATURE SEARCH"
    sections and "G-C, DEVICE2D, TAKE 2".
  M17 transient simulation -- COMPLETE (2026-08-30/31), all 3 phases:
    1D (pytcad/transient.py) and 2D (pytcad/transient2d.py)
    backward-Euler/theta-scheme solvers, driving Device1D/Device2D
    through their own residual/Jacobian externally (continuation.py's
    pattern) -- device.py/device2d.py never touched. Phase 3 wires a
    transient run into the desktop app end-to-end (new Transient tab,
    schema v2->v3 bump, new viewport mode), reusing the existing
    JobRunner subprocess path unchanged. See
    pytcad/M17-TRANSIENT-PLAN.md for the full gate list and the
    honestly-recorded gaps (G2 diode-turn-off charge quantification,
    GateBC waveforms, project persistence of an armed config,
    per-step field snapshots).
  M18 small-signal AC -- Phase 1 LANDED 2026-08-31: pytcad/ac.py, an
    external module (device.py untouched) computing complex admittance
    Y(f)/C(f)/G(f) for Device1D by perturbing the converged DC Jacobian
    with jw*Cmat (Cmat verified bit-identical to transient.py's own
    storage term). A real bug (per-node FD step size breaking an exact
    analytic cancellation, silently doubling the low-frequency
    conductance) was caught by the G-LOWF gate before being reported.
    Library-only: no Device2D, no GUI. See pytcad/M18-AC-PLAN.md.
  M19 self-heating -- Phase 1 LANDED 2026-08-31: pytcad/thermal.py, an
    outer isothermal-DD + Gummel thermal loop (NOT a monolithic
    psi/n/p/T Newton system -- Device1D's whole scaling framework is
    built from a single scalar T, so that would be a much larger
    rewrite than the gates require). A real bug (naive J*E Joule
    heating gives thermodynamically impossible negative heat in a
    diode's diffusion-dominated depletion region) was found and fixed
    using the correct quasi-Fermi-potential-gradient dissipation term
    (Wachutka 1990), cross-checked against energy conservation (I*V) to
    0.04%. Added Semiconductor.kappa_th300/kappa_th(T) to materials.py
    (none existed before, despite the milestone spec's "no new
    material work" note). See pytcad/M19-SELFHEATING-PLAN.md, including
    an honest finding that a real diode's self-heating INCREASES
    current (the opposite of the "roll-off" language in the milestone
    spec, which fits a MOSFET, not a diode).
  M21 meshing -- phase 1 (1D adaptive h-refinement, pytcad/M21-MESHING-
    PLAN.md) and phase 2 (2D/3D separable adaptive refinement) shipped.
    Phase 3 (general unstructured 2D + Delaunay FV assembly,
    pytcad/M21-PHASE3-MESHING-PLAN.md) is now COMPLETE 2026-08-31: 3a
    (gmsh_mesh.py/region_resolver.py/unstructured_assembly.py geometry
    foundation), 3b (unstructured_poisson.py, Poisson-only equilibrium),
    3c (unstructured_dd.py, coupled SG bias solve), and 3d
    (Device2D(unstructured=True) -- a thin wrapper into Device2D's own
    solve_equilibrium/solve_bias/terminal_current API, verified
    bit-identical to calling the standalone functions directly) all
    landed and gated. Homojunction/Boltzmann-only by explicit design
    (unstructured_dd.py's own docstring); Device2D(unstructured=True)
    refuses any Models() flag that physics core doesn't implement.
  M22 linear solver -- phase 1 (Krylov+ILU+block-Jacobi preconditioner)
    shipped; a hard-debug pass found and fixed a real bit-identity bug
    in solve_linear(method="direct") reformatting the matrix before
    calling spsolve (see the scipy spsolve gotcha above); 3D-scaling
    gate green; phase 2 (continuation driver, strength-ladder-aware
    corrector) LANDED 2026-08-28 and is what let M15 R1b close; the
    section-7 Schur-complement preconditioner (solve_linear(precond=
    "schur")) landed 2026-08-29 and was VERIFIED 2026-08-31 (gates were
    written but never run until then; all 5 Schur-specific gates passed
    cleanly on first execution -- additive, default unchanged, not
    wired into NewtonOptions).  Phase 3 (2026-09-02) LANDED as MPI
    Schwarz domain decomposition (gui/services/mpi_schwarz_runner.py),
    not the distributed-matrix design originally scoped -- 4 ranks,
    5.1x on bjt_3d, exact to ~1e-17; a real regression on a device
    whose doping varies along the split axis (pn_junction_3d) was
    found and gated against before shipping. Same session: pyamg AMG
    for the GUI's 3D equilibrium solve (8x-44x) and a CUDA (CuPy/
    cuSOLVER) direct solve for bias/sweep (2.8x) -- both opt-in,
    size-gated, additive.  See pytcad/M22-LINSOLVE-PLAN.md section 9.
    GENERALIZED same day (section 10): the x-only safety check became
    _pick_mpi_split_axis(doping), which checks all three mesh axes and
    picks whichever is safe with the most nodes -- pn_junction_3d
    (refused outright by the x-only check) now qualifies via z, 1.5x
    over its single-process baseline, exact to ~1e-17.
  M16 BTBT -- local Kane/Hurkx generation, live Jacobian coupling,
    landed 2026-08-29, VERIFIED 2026-08-31: the gates had never been
    run; once executed, 2 of 13 failed, but all three root causes were
    bugs in the TEST assertions (inverted sort direction, a sign error
    comparing two negative slopes, a correlation-sign check that could
    never pass for a genuine negative-slope fit) -- not the physics.
    All 13 pass now. See pytcad/M16-BTBT-PLAN.md.
  M20 density gradient -- Ancona-Stafford DG quantum correction
    (equilibrium-only, MOSCapacitor dg flag + Device1D Models.dg), plus
    the pytcad/dg.py analysis layer (quantum_potential, Airy reference,
    Schroedinger-Poisson solver). COMPLETE, ALL GATES GREEN 2026-08-31:
    the original lagged-Lambda outer fixed point converged cleanly but
    to the WRONG physics (a gamma-calibration gap); replaced with a
    genuinely coupled Newton solve of (psi, Lambda_n, Lambda_p)
    together, plus a hard-wall interface boundary condition for
    MOSCapacitor (researched against DEVSIM's own density-gradient
    implementation) that fixed a real wrong-sign bug in the near-
    surface quantum potential. gamma stays at its documented default of
    1.0, untouched -- the boundary-condition fix closed the gates, not
    a gamma retune. See pytcad/M20-DENSITY-GRADIENT-PLAN.md section 7.
GUI end-to-end smoke test (2026-08-28): gui/tests/test_smoke_e2e.py
drives the real rendered QML tree (create_engine() + findChild +
QMetaObject.invokeMethod -- never a controller call as a substitute for
a UI action, except the couple of spots documented inline where Qt's
offscreen platform cannot incubate ListView/Repeater delegates at all)
across the 1D Process-Flow path and the 2D Structure/Device-Builder-
template path. AT THE TIME (2026-08-28) there was no GUI entry point
to a Device3D or the DEVSIM backend -- BOTH GAPS ARE NOW PARTLY CLOSED,
see the GUI-IMPROVEMENT-PLAN.md and 3D-VISUALIZATION-PLAN.md bullets
below; do not trust this sentence's claim in isolation, it describes a
point in time, not current state. Found and fixed: numeric QML fields
silently letting NaN through to the solver (app_controller.py
finite-number guard), and saved projects silently dropping the
Physics Lab's model toggles (project_store SCHEMA_VERSION 4->5,
"models" key; see gui/tests/test_persistence_v5.py).
GUI-IMPROVEMENT-PLAN.md (2026-08-29): Phases 1-4 SHIPPED -- C-V mode,
family-sweep staleness, equilibrium-only Run, contour overlays,
line-cut mode, a devsim/pytcad BACKEND SELECTOR (v0.6 Phase 2c, gated
on compatible 1D devices -- closes half of the "no DEVSIM entry
point" gap above), backend comparison, lab controller/provenance/
continuation records, and a runtime state validator. A medium-effort
/code-review pass on Phase 3/4 found and fixed 8 real bugs (a QML
id/objectName typo causing a runtime crash, dead validator logic,
non-notifying ListView bindings, a consumer with no real data
producer, faked placeholder checks, duplicated logic, hardcoded theme
colors) -- see history.md Addendum 22 for the full list. Do not
assume Phase 3/4 code is correct just because it exists; that
addendum is the record of what was actually verified, not the
original (less careful) landing.
3D-VISUALIZATION-PLAN.md (2026-08-29/30): Phases 1-5 SHIPPED -- a
hand-built `resistor_3d` example (the first GUI entry point to a
Device3D, closing the other half of the gap above) and a PyVista/VTK
viewer window (separate top-level QWidget, NOT embedded in QML) with
interactive isosurface controls, volumetric rendering (Phase 3),
animated bias-sweep playback with snapshot capture (Phase 4), and
exploded multi-layer structural view (Phase 5). Landing this ALSO
fixed a real bug from Phase 1: see the QApplication/QGuiApplication
gotcha above.
Live queue: ARCHITECTURE.md sections 5-7; session detail:
`history.md`.
