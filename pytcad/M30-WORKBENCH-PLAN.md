# M30 — Workbench System Features + Interop — Implementation Plan

Status (2026-09-07): Part I Phases 1, 2, 3, 4 LANDED -- see section 8c
below for what actually shipped and where the gates live. Part II
(Phases 5-12, the GUI/product layer) is PLANNED ONLY, not yet
implemented -- see PART II below.

Environment note: this repo must be run under the `TCAD` conda env
(`conda run -n TCAD ...`), not `base` anaconda3 -- `base`'s Qt6 install
is ABI-mismatched and fails every `gui/tests/*` QML test with "Main.qml
failed to load", independent of any code change (confirmed directly via
`git stash` reproducing the identical failure on unmodified code).

Per ARCHITECTURE.md
§4b.2, M30 "depends: most things; do last, incrementally" -- every
milestone it could plausibly sweep or calibrate over (M13-M29) is now
landed, so this is unblocked, but the spec explicitly asks for an
incremental landing, not one big-bang PR. This plan splits it into 4
independently-shippable phases, each with its own gates, so a partial
landing is still honest progress rather than a half-finished feature.

## 0. What M30 actually still covers (re-scoped against current state)

ARCHITECTURE.md's M30 line lists five things. Two of them are **already
shipped** by earlier, unrelated work and are NOT part of this plan:

- "2D field contours/cuts ... in the GUI" -- SHIPPED, GUI-IMPROVEMENT-
  PLAN.md Phase 3 (`MplCanvasItem._maybe_contour`, `extract_line_cut`).
- "transient plots in the GUI" -- SHIPPED, M17-TRANSIENT-PLAN.md Phase 3
  (Transient tab, schema v3, dedicated viewport mode).

Confirmed by reading both plan docs' own "SHIPPED"/acceptance sections
before writing this plan, not assumed from the milestone summary line.

What is genuinely open (the real M30 backlog):

1. **Parameter table x deck = run matrix** ("splits"). The deck front
   end (`workbench/workflow.py`) already parses a single TEMPLATE +
   BIAS + one SWEEP statement into one `DeckRun`. There is no notion of
   a *parameter table* (N named parameters x M values each) crossed
   against a deck to produce a run matrix, and no runner that executes
   that matrix. The GUI's `FamilySweepController` is adjacent but
   narrower: it only steps ONE bias contact across a single device,
   sequentially, and is GUI-only (no library-level, deck-driven
   equivalent).
2. **Calibration / optimization loop.** Goal function vs. a reference
   curve, simple Nelder-Mead search over 1+ deck parameters. Nothing
   in the repo does this today (`grep -rn "nelder\|calibrat\|optimiz"`
   across `pytcad/` and `workbench/` returns no implementation, only
   the milestone-summary mentions already read).
3. **DeckBuild-dialect import filter.** Nothing parses Silvaco
   DeckBuild syntax today; `workbench/workflow.py`'s `run_deck*` is our
   OWN dialect (TEMPLATE/BIAS/SWEEP), not an import path for a
   foreign format.
4. **Batch parallelism.** `gui/services/job_runner.py`'s `JobRunner`
   drives exactly one subprocess per instance; `FamilySweepController`
   (`gui/controllers/family_sweep_controller.py` -- confirm exact path
   at implementation time) runs its N curves through repeated
   sequential `JobRunner` invocations, one at a time. There is no
   pool that runs several independent jobs (split-matrix rows,
   calibration trial points) concurrently. Note this is orthogonal to
   the M22 MPI-Schwarz work, which parallelizes ONE job's linear
   solve across ranks -- batch parallelism here parallelizes MANY
   independent jobs, at the process-pool level, reusing the existing
   one-job-per-subprocess contract unchanged.

## 1. Ground rules (per AGENTS.md / ARCHITECTURE.md §4b.4)

- Nothing here touches `pytcad/*.py` numerical core. All four phases
  are pure additions in `workbench/`, a new top-level runner module,
  and `gui/` -- following the M16/M17/M18/M19 precedent of driving the
  existing solvers from outside, never amending `device.py`/
  `device2d.py`/`device3d.py`.
- Each phase lands with its own acceptance gates in
  `tests/test_m30_*.py` (library-level) and, where it touches the GUI,
  `gui/tests/test_m30_*.py`, BEFORE being called done -- same rule as
  every prior milestone (`tests/test_model_benchmarks.py` FIRST for
  new physics does not apply here since M30 adds no physics, but the
  "gate before merge" discipline carries over).
- Suite invariant unchanged: full suite green, zero new warnings,
  `-n 6` cap, `OPENBLAS_NUM_THREADS=1` under parallel batch execution
  (this now matters directly -- Phase 4's process pool multiplies the
  BLAS-oversubscription risk AGENTS.md already warns about, since each
  pool worker's own subprocess can itself spawn a BLAS thread pool).
- Working tree left dirty only with an explicit failing-test handoff
  note in `history.md`, per the standing workflow rule.
- Do not commit automatically; user pushes (per AGENTS.md).

## 2. Suggested order and why

Phase 1 (splits) first: it is the prerequisite data structure for
Phase 2 (calibration needs to run many parameterized trials -- that IS
a split matrix, generated adaptively by the optimizer instead of a
fixed table) and for Phase 4 (batch parallelism has nothing to
parallelize until there is a matrix of independent runs). Phase 3
(DeckBuild import) is fully independent of 1/2/4 and can land in any
order, including in parallel with them -- it is a pure text-format
translator with no solver or runner coupling, so it is placed last
here only because it is lowest-value without the other three (an
imported deck matrix is more useful once splits/batch exist to
consume it).

```
Phase 1: parameter splits (run matrix)      <- no dependency
Phase 2: calibration / Nelder-Mead           <- depends on Phase 1's runner
Phase 4: batch parallelism                   <- depends on Phase 1's runner
Phase 3: DeckBuild-dialect import filter     <- independent, do anytime
```

---

## 3. Phase 1 — Parameter splits (run matrix)

### Scope
- `workbench/splits.py` (new): a `SplitSpec` (named parameter ->
  sequence of values, e.g. `{"tox_cm": [7e-7, 8e-7, 9e-7], "vth_shift":
  [0.0, 0.05]}`) and `expand_splits(deck_values, split_spec)` producing
  the full cartesian-product run matrix as a list of parameter dicts
  (each = the base deck's parsed KEY=value map with the split values
  substituted in). No implicit clamping/dedup beyond what the deck's
  own template `.build()` already validates.
- `workbench/workflow.py`: extend the deck grammar with a `SPLIT`
  statement (`split tox_cm = 7e-7, 8e-7, 9e-7`), parsed the same
  line-numbered-error way as the existing `BIAS`/`SWEEP` statements,
  collected into a `DeckRun.splits: dict` (empty when absent -- fully
  backward compatible, an old deck with no SPLIT line is untouched).
- A `run_split_matrix(deck_run)` entry point that, for each row of the
  expanded matrix, builds the device via the existing template path
  and returns `(row_params, DomainDevice, build_error_or_None)` --
  library-level only in this phase (no GUI, no subprocess pool; that
  is Phase 4). A row that fails to build (invalid parameter
  combination) is recorded, not fatal to the rest of the matrix --
  mirrors `run_deck_full`'s existing pattern of collecting `problems`
  rather than aborting on the first one, generalized to per-row
  isolation.

### Explicitly out of scope this phase
- Executing bias/sweep solves per row (that needs Phase 4's pool to be
  worth doing for anything but a tiny matrix; a naive sequential
  version is acceptable as the Phase 1 gate but is not the shipped
  batch story).
- GUI surface (a "Splits" tab/table) -- library-first, same precedent
  as M18 Phase 1-3 landing library-only before Phase 4 GUI exposure.

### Acceptance gates (`tests/test_m30_splits.py`)
- G-EXPAND: `expand_splits` on a 2-parameter x {3,2} split spec
  produces exactly 6 rows, the correct cartesian product (order
  documented, not just "some permutation").
- G-STUDY: "split matrix reproduces a documented study" per
  ARCHITECTURE.md's own acceptance language -- ties one gate to a real
  published parameter-sweep result reproduction (e.g. a MOSFET
  tox/Vth family), not just row-counting.
- G-PARSE: a deck with a `SPLIT` line round-trips through
  `run_deck_full` unchanged for all pre-existing BIAS/SWEEP behavior
  (regression gate -- old decks unaffected).
- G-ISOLATION: one deliberately-invalid split row (e.g. a parameter
  value the template rejects) does not abort the other rows.
- G-BACKCOMPAT: every existing `test_workbench_m1.py` /
  `workbench/workflow.py`-touching test still passes unmodified.

---

## 4. Phase 2 — Calibration / optimization loop

### Scope
- `workbench/calibration.py` (new): `GoalFunction` (a reference curve
  = array of (bias, target_value) pairs + an interpolation/error norm,
  e.g. RMS log-current error for an I-V goal) and
  `calibrate(deck_run, free_params, goal, method="nelder-mead")`
  driving a plain Nelder-Mead simplex search (small, dependency-free
  implementation, OR `scipy.optimize.minimize(method="Nelder-Mead")`
  reused directly -- prefer the scipy call, since scipy is already a
  hard dependency and a from-scratch simplex is exactly the kind of
  unnecessary abstraction AGENTS.md's engineering rules warn against
  when a validated library call does the same job).
- Each trial evaluation: build device with the free params' proposed
  values (via Phase 1's per-row build path), run the existing solver
  (equilibrium or bias sweep, whichever the goal curve needs), compute
  the goal function against the reference curve, return the scalar
  error scipy's optimizer minimizes.
- Output: best-fit parameter dict + convergence record (iterations,
  final error, per-iteration trace) for the GUI/CLI to display.

### Explicitly out of scope this phase
- Any optimizer beyond Nelder-Mead (no gradient-based/Bayesian
  methods -- spec says "simple Nelder-Mead" explicitly).
- Multi-objective calibration (single scalar goal function only).
- GUI surface (deferred; a calibration run is exposed first as a
  library call + a small script/example, same as M15/M16 landed
  library-first before any GUI wiring).

### Acceptance gates (`tests/test_m30_calibration.py`)
- G-RECOVER: "optimizer recovers a planted parameter" (ARCHITECTURE.md's
  own acceptance language) -- generate a synthetic reference curve from
  a KNOWN parameter value, perturb the initial guess, assert
  `calibrate` recovers the planted value within a stated tolerance.
  This is the load-bearing gate for the whole phase; the rest are
  supporting infrastructure checks.
- G-GOAL-NORM: the goal function's error norm is unit-tested standalone
  against hand-computed values (not just exercised indirectly through
  the optimizer).
- G-NOCONVERGE: a goal curve that is physically unreachable within the
  free parameters' domain reports a clear non-convergence result
  rather than silently returning a bogus "best" fit (honesty-over-
  polish rule).

---

## 5. Phase 3 — DeckBuild-dialect import filter

### Scope
- `workbench/deckbuild_import.py` (new): a translator from a documented
  subset of Silvaco DeckBuild syntax into our own `workbench/workflow.py`
  dialect (TEMPLATE/BIAS/SWEEP/SPLIT), NOT a second simulation path --
  it only ever produces a `DeckRun` via the existing `run_deck_full`,
  identical to a hand-written deck. Scope the subset explicitly up
  front (device statement -> template mapping table, `solve`/`method`
  statement -> bias/sweep translation) and document what is
  deliberately NOT translated (DeckBuild has decades of syntax; import
  a documented, honestly-bounded subset, not a full parser).
- Round-trip gate direction is OUR decks through the DeckBuild subset
  we choose to support, per ARCHITECTURE.md's own acceptance line
  ("dialect import round-trips our own decks") -- i.e. the practical
  gate is: take an existing `.dck`-style example, express it in the
  supported DeckBuild subset, import it, and confirm the resulting
  `DeckRun` matches building the same device/bias directly from our
  own dialect. This sidesteps needing a real external DeckBuild
  license/corpus to validate against -- an honest limitation to state
  in the plan up front, not discover late.

### Acceptance gates (`tests/test_m30_deckbuild_import.py`)
- G-ROUNDTRIP: the documented subset round-trips as above.
- G-REJECT: an unsupported DeckBuild construct raises a clear,
  line-numbered error (same style as `run_deck_full`'s existing error
  reporting) rather than silently mis-translating.

---

## 6. Phase 4 — Batch parallelism

### Scope
- A process pool (likely `concurrent.futures.ProcessPoolExecutor` or
  `multiprocessing.Pool`, reusing the SAME `gui/services/solver_runner.py`
  subprocess-per-job contract Phase 1's rows and Phase 2's trials
  already produce) that runs N independent jobs concurrently, capped
  at a worker count derived the same way M22's `-n 6` guidance already
  reasons about this machine (do not hardcode a different constant;
  reuse whatever cap convention M22/AGENTS.md already establishes).
- Must set `OPENBLAS_NUM_THREADS=1` (or verify it's already forced) for
  pool workers -- the exact oversubscription hazard AGENTS.md already
  documents for `pytest -n`, now doubled by running actual solves (not
  just test collection) concurrently.
- Wires into Phase 1 (`run_split_matrix`) as the default executor when
  a matrix has more than one row, and is reusable by the GUI's
  existing `FamilySweepController` as a drop-in replacement for its
  current sequential loop (confirm the controller's exact file/API
  before touching it -- not yet grep-confirmed in this plan).

### Acceptance gates (`tests/test_m30_batch.py`)
- G-PARALLEL-CORRECT: results from the parallel pool are bit-identical
  (or within the same tolerance the MPI-Schwarz gates already accept
  for cross-process numerical work) to running the same rows
  sequentially -- parallelism must not change answers.
- G-OVERSUBSCRIPTION: a benchmark confirms the pool does not
  oversubscribe cores under the `OPENBLAS_NUM_THREADS=1` setting
  (same category of regression M22's linsolve work already guards).
- G-ISOLATION: one worker's job failure (bad params, solver
  non-convergence) does not crash the pool or lose other workers'
  results.

---

## 7. Honest limits (stated up front, not discovered late)

- Nelder-Mead only, single scalar goal -- no multi-objective or
  gradient-based calibration.
- DeckBuild import covers a documented, bounded syntax subset, not the
  full commercial-tool grammar; no external DeckBuild corpus is
  available to validate against, so the round-trip gate is
  necessarily self-referential (our own decks through our own chosen
  subset).
- Batch parallelism parallelizes independent JOBS (many decks/rows),
  not a single job's internal linear algebra -- that is already M22's
  separate, already-shipped concern.
- GUI exposure for splits/calibration is explicitly deferred past this
  plan's four phases (library-first, matching the M15-M19 precedent);
  add it as a Phase 5 only after the user confirms the library-level
  behavior is what they want exposed.

## PART II — Workbench/product layer (Phases 5-12)

Added 2026-09-07, before any of Phases 5-12 below were implemented, at
the user's explicit request to "review this plan and implement the
missing Workbench/product layer after the current 4 phases" with a
stated priority order. This part is RESEARCH + PLAN ONLY as of this
writing -- Part I's Phase 1 (splits) is implemented and gated (see
`tests/test_m30_splits.py`); Phases 2-4 (calibration, DeckBuild import,
batch parallelism) are designed in Part I but NOT YET implemented.
Phases 5-12 below build ON TOP of Phases 1-4's infrastructure, so their
real implementation order cannot fully match the user's priority
numbering where a dependency runs the other way -- each phase section
below states its actual prerequisite explicitly, and section 16
reconciles the requested priority against the dependency graph.

### 8b. What already exists that this part must integrate with, not duplicate

Confirmed by reading the actual code (not assumed from names):

- **Batch controller pattern**: `gui/controllers/family_sweep_controller.py`
  -- a small, app-independent `QObject` controller (constructor takes
  the `AppController` reference, like `BuilderController`), owning its
  own `JobRunner`, running jobs SEQUENTIALLY today (queue + `_start_next`
  driven off `JobRunner.finished`/`.failed` signals), reading results
  back through `NpzResultStore`. This is the template Phase 5's Study
  controller follows -- and per the user's explicit instruction, this
  controller itself is NOT touched/retrofitted in this plan.
- **Provenance substrate (per-job)**: `gui/services/solver_backend.py`'s
  `RunRecord` (backend, created_utc, dimensionality, material, T,
  models, numerics, sweep/transient config, convergence trace,
  continuation records, schema_version) is already written into every
  result `.npz` (`record__meta`, `converge__trace`,
  `continuation__records` keys) and already surfaced read-only through
  `PhysicsLabController.provenanceRows()`/`convergenceData()`/
  `continuationData()` (`gui/controllers/lab_controller.py`). Phase 9
  extends this per-JOB record into a per-STUDY manifest; it does not
  reinvent per-job provenance, which is already solid.
- **"Checkpoint" is an existing, DIFFERENT term**: `gui/services/
  process_runner.py` / `process_result_store.py` already use
  "checkpoint" for a per-PROCESS-STEP device snapshot (walking a
  process flow, e.g. after an implant step). Phase 8 ("Checkpoint/
  Resume") is about resuming an INTERRUPTED STUDY (a split matrix or
  calibration run killed partway through), a completely different
  object. To avoid confusion with the existing term, Phase 8's own
  code and docs call this a **study manifest resume**, never
  "checkpoint," even though the user's priority list uses that word.
- **Subprocess execution model**: `gui/services/job_runner.py`'s
  `JobRunner` drives exactly one `QProcess` per instance via Qt's
  non-blocking process API (chosen specifically because a Newton solve
  cannot be safely killed from a Python thread -- see the module's own
  docstring). GUI-level batch parallelism (Phase 4's GUI exposure, and
  Phase 5's pool) means running several `JobRunner` instances
  concurrently in the SAME Qt event loop, not `multiprocessing` --
  that mechanism is for the LIBRARY-level executor Phase 4 already
  scopes (`concurrent.futures.ProcessPoolExecutor` around
  `gui/services/solver_runner.py:run_job`, used by CLI/library callers
  with no Qt event loop at all). These are two different concurrency
  mechanisms for two different layers; Phase 5 reuses Phase 4's
  library executor where there is no GUI, and a small QProcess pool
  (bounded by the same worker-count convention) inside the GUI.
- **Layering rule already in force** (AGENTS.md): `QML -> controllers
  -> services -> QProcess subprocess -> npz -> ResultStore -> canvas`.
  Controllers already import `workbench` directly (`lab_controller.py`,
  `builder_controller.py`, `app_controller.py`) -- so a new Study
  controller importing `workbench.splits`/`workbench.calibration`
  directly, the same way, is consistent with existing precedent, not
  a new exception.
- **QML panel naming convention**: one `<Name>Panel.qml` per feature
  area under `gui/qml/panels/` (`SweepPanel.qml`, `ACPanel.qml`,
  `TransientPanel.qml`, ...), each backed by its own controller
  instantiated once by `AppController` and exposed as a
  `@Property(QObject, constant=True)`.

### 9. Phase 5 — GUI Split/Study Manager

**Prerequisite**: Phase 1 (splits, DONE) + Phase 4 (batch parallelism,
not yet built).

**Scope**: `gui/controllers/study_controller.py`, a new `StudyController`
(app-independent, `FamilySweepController`-shaped: takes the
`AppController` reference, owns its own execution resources, is
instantiated once by `AppController` and exposed as a new
`@Property(QObject, constant=True) def study(self)`). Responsibilities:
  - Accept a deck (or the current builder-authored device + a
    `SplitSpec` entered in the UI) and call `workbench.splits.
    run_split_matrix` to materialize the row list (build errors only --
    no solving yet).
  - For rows that build cleanly, run each through Phase 4's executor
    (GUI-side: a small pool of `JobRunner`s bounded by the same
    worker-count convention Phase 4 establishes; library-side calls
    Phase 4's `ProcessPoolExecutor` path directly when driven
    headless/from a script).
  - Track per-row state (`pending` / `running` / `done` / `failed` /
    `build_error`) as a bindable Qt model (`QAbstractListModel`,
    mirroring `CatalogModel`'s existing pattern in `lab_controller.py`)
    so Phase 6's viewer has something to bind to.
  - New QML panel `gui/qml/panels/StudyPanel.qml`: a table (one row per
    split-matrix row: parameter values + status), a Run/Cancel control,
    and per-row "open result" wiring into the existing viewport.

**Explicitly out of scope this phase**: the matrix VISUALIZATION beyond
a plain status table (that is Phase 6), cross-run comparison (Phase 7),
resume-after-crash (Phase 8), and any constraint validation on split
parameter combinations (Phase 10) -- rows that violate an implicit
device constraint simply fail at template `.build()` today, same as
Phase 1's `G-ISOLATION` gate already exercises.

**Acceptance gates** (`gui/tests/test_m30_study_controller.py`):
- G-BUILD: a `SplitSpec` with a known-bad row surfaces that row as
  `build_error` without blocking the others (GUI-level restatement of
  Phase 1's `G-ISOLATION`, now through the Qt model).
  - G-RUN: a small (2-3 row) split matrix on a fast device runs all
  rows to completion and each row's status ends `done`, with a real
  result path readable by `NpzResultStore` (no faked/interpolated
  results -- same rule `FamilySweepController`'s own docstring states).
- G-CANCEL: canceling mid-study stops in-flight rows and leaves
  completed rows' results intact (mirrors `JobRunner.cancel()`'s
  existing single-job contract, generalized to "cancel the rest of the
  queue, keep what already finished").
- G-NO-RETROFIT: `family_sweep_controller.py` is byte-identical
  (untouched) after this phase -- a regression gate literally diffing
  the file, since the user was explicit this controller is not to be
  touched yet.

### 10. Phase 6 — Sweep Matrix Viewer

**Prerequisite**: Phase 5 (need a study's row/result data to visualize).

**Scope**: a read-only visualization layer over a completed (or
partially completed) study: for a 2-parameter split, a heatmap/grid
view (reusing the existing Matplotlib canvas item,
`gui/visualization/mpl_canvas_item.py`, the same one M-plan already
extended for contour overlays -- not a new plotting stack); for a
1-parameter split, a simple per-row curve-family view (reusing the
`FamilySweepController`'s own curve-list rendering pattern read-only,
without touching that controller). Selecting a cell/row opens that
row's result in the normal viewport, exactly like today's per-run
result opening.

**Acceptance gates** (`gui/tests/test_m30_matrix_viewer.py`):
- G-GRID: a 2-parameter, 3x2 study renders a 3x2 grid whose cell
  values match the underlying result scalars exactly (no
  interpolation/synthesis between cells).
- G-PARTIAL: a study with some rows still `pending`/`failed` renders
  the grid with those cells visibly distinguished, not silently
  skipped or shown as zero.
- G-SELECT: clicking a cell/row loads that row's actual result path
  into the existing viewport machinery (reuse, not reimplementation).

### 11. Phase 7 — Run Comparison

**Prerequisite**: Phase 5 (a set of runs to compare) and, for
side-by-side provenance display, Phase 9's manifest is convenient but
not required -- this phase can compare any two `ResultStore`-backed
runs (a study's rows, or two arbitrary saved results), so it is
sequenced before full Phase 9 despite the user's numbering; see
section 16.

**Scope**: a comparison view taking N result paths (from a study, or
picked from the project tree / result history) and showing: overlay of
the same field/cut/I-V curve across runs (reuse `extract_line_cut` and
the existing curve-plot machinery -- no new extraction code), and a
side-by-side provenance diff table built directly from each run's
existing `RunRecord` (`PhysicsLabController.provenanceRows()`'s data
shape, generalized to N runs instead of one).

**Acceptance gates** (`gui/tests/test_m30_run_comparison.py`):
- G-OVERLAY: two runs of the same device at different split parameter
  values overlay correctly on one axes with correct per-curve labels.
- G-PROVDIFF: the provenance diff table flags every field that differs
  between two `RunRecord`s (e.g. different `tox_cm` via `models`/
  `numerics` metadata) and shows identical fields as such, verified
  against a hand-constructed pair of `RunRecord`s with known diffs.
- G-MISMATCHED-DIM: comparing a 1D and a 2D result's field overlay
  fails with a clear message rather than silently producing garbage.

### 12. Phase 8 — Study manifest resume ("Checkpoint/Resume")

**Prerequisite**: Phase 5 (need a study's row list/state to resume) and
Phase 9's manifest format (a resume needs a persisted, on-disk record
of which rows are done -- this is really the write-and-reload half of
Phase 9, so it is implemented together with Phase 9's manifest schema
even though it is listed as its own phase both here and in the user's
priority list).

**Scope**: `workbench/study_manifest.py` (new, library-level, no Qt): a
`StudyManifest` -- one JSON document per study run, listing the split
spec, each row's parameters, status, and result path (or build/solve
error), written incrementally as rows complete (not just at the end,
so a crash mid-study leaves a usable partial manifest). `resume_study
(manifest_path)` rebuilds a `DeckRun`-equivalent row list, skips rows
already `done` in the manifest, and re-queues only `pending`/`failed`
rows. `StudyController` (Phase 5) writes/reads this manifest
transparently -- resuming a study in the GUI is "load manifest, click
Run" on the same `StudyPanel.qml`, not a separate UI surface.

**Acceptance gates** (`tests/test_m30_study_manifest.py` library-level;
`gui/tests/test_m30_study_resume.py` for the GUI reload path):
- G-INCREMENTAL: the manifest file on disk reflects each row's status
  immediately after that row finishes, not only at study end (verified
  by killing the study process partway and reading the manifest as it
  stood).
- G-RESUME-SKIPS-DONE: resuming a manifest with 2 of 5 rows already
  `done` only re-runs the remaining 3, and the 2 `done` rows' original
  result paths are unchanged (not re-solved, not overwritten).
- G-RESUME-RETRIES-FAILED: a row marked `failed` in the manifest IS
  re-run on resume (failures are not treated as permanently done).
- G-SCHEMA: the manifest JSON has an explicit schema version field from
  day one (this repo's own history -- `project_store.py`'s
  SCHEMA_VERSION bumps -- is the argument for versioning a persisted
  format before the first real user, not after the first breaking
  change).

### 13. Phase 9 — Provenance / Reproducibility

**Prerequisite**: none blocking (extends the already-solid per-job
`RunRecord`), but most useful once Phase 8's manifest exists to attach
study-level provenance to.

**Scope**: extend the study manifest (Phase 8) with enough to
plausibly REPRODUCE a study, not just describe it after the fact: the
deck/split-spec text verbatim, the resolved parameter values per row
(already in the manifest), each row's `RunRecord` (already written per
result `.npz`, just referenced by path from the manifest rather than
duplicated), and a coarse "code identity" stamp -- `git rev-parse
HEAD` if running inside a git checkout, else an honest "unknown"
rather than a fabricated value (this repo's own AGENTS.md rule against
ever claiming something unverified applies directly here: never
invent a commit hash or dependency version). Explicitly NOT in scope:
capturing full dependency versions/OS/hardware fingerprints (that is a
much larger reproducibility-infrastructure project; state the honest
limit rather than half-build it).

**Acceptance gates** (`tests/test_m30_provenance.py`):
- G-MANIFEST-COMPLETE: a manifest for a completed study round-trips
  into "the exact same split matrix + row parameters" when re-parsed,
  independent of whether the original process is still alive.
- G-GIT-STAMP: inside a git checkout, the stamped commit hash matches
  `git rev-parse HEAD` at manifest-write time; outside one (or a dirty
  tree -- decide and document which), the field is honestly `null`/
  `"unknown"`, never fabricated.
- G-NO-DUPLICATION: the manifest does not copy each row's full
  `RunRecord` inline (that data already lives in the row's own
  `.npz`) -- it references the result path, keeping the manifest small
  and avoiding a second, driftable copy of the same facts.

### 14. Phase 10 — Parameter constraints

**Prerequisite**: Phase 1 (splits) and Phase 2 (calibration) -- this
phase adds validation ON TOP of both, not a new runner.

**Scope**: `workbench/constraints.py` (new): a small constraint
vocabulary attachable to a `SplitSpec` or a calibration's free-parameter
set -- inequality/relationship constraints between named parameters
(e.g. `lg_cm < width_cm`, or a template-specific physical constraint
like "gate must sit within the device width" already implicitly
enforced by `DomainDevice.validate()` today, just not stated
declaratively before a whole matrix is expanded). `expand_splits`
(Phase 1) grows an optional `constraints` argument that filters rows
BEFORE building (cheaper than discovering the same violation via a
`ValueError` from `.build()`, and lets the UI show "excluded by
constraint" distinctly from "build failed" in Phase 6's grid).
Calibration (Phase 2) gains the same optional constraint check on
proposed trial points, returned to scipy's optimizer as a large
penalty rather than letting an out-of-constraint trial reach the
solver at all.

**Acceptance gates** (`tests/test_m30_constraints.py`):
- G-FILTER: a split matrix with a stated constraint drops exactly the
  rows that violate it, and Phase 1's existing `expand_splits`/
  `run_split_matrix` gates remain green with `constraints=None`
  (backward compatible default).
- G-DISTINCT-STATUS: a constraint-excluded row is reported distinctly
  from a template-build-error row (different `SplitRow.error` shape or
  a new explicit status field -- exact shape decided at implementation
  time, but the distinction must be observable, not collapsed).
- G-CALIBRATION-PENALTY: an out-of-constraint calibration trial point
  never reaches `template.build()`/the solver -- verified by a trial
  proposal deliberately outside the constraint, asserting no device
  build was attempted for it.

### 15. Phase 11 — Adaptive sweep

**Prerequisite**: Phase 1 (splits) and Phase 4 (batch parallelism) --
adaptive refinement is only worth the complexity once rows already run
in parallel; a sequential adaptive sweep would work but defeats the
point of having Phase 4.

**Scope**: `workbench/adaptive_sweep.py` (new): given an initial coarse
split grid and a refinement criterion (e.g. "refine where the goal
quantity's gradient between adjacent grid points exceeds a threshold" --
scope the exact criterion narrowly and document it, per this repo's
consistent "honest, bounded scope over generality" pattern), generate
successive rounds of additional split rows targeting the
under-resolved region, stopping at a max-rounds or convergence
tolerance. This is INTENTIONALLY the smallest useful adaptive
criterion, not a general DOE/adaptive-sampling framework -- matches
the spirit of M30's own spec language ("simple Nelder-Mead" for
calibration; adaptive sweep gets the same "simple, stated, bounded"
treatment).

**Acceptance gates** (`tests/test_m30_adaptive_sweep.py`):
- G-REFINES-WHERE-NEEDED: a synthetic goal quantity with a sharp
  feature in a known sub-region gets measurably denser sampling there
  than in a flat sub-region, after a fixed number of rounds.
- G-TERMINATES: the refinement loop terminates within its stated
  max-rounds bound even when the criterion never quiets down (no
  infinite-loop risk from a pathological goal function).
- G-REUSES-BATCH: each refinement round's new rows are dispatched
  through Phase 4's executor, not a bespoke sequential loop (a direct
  regression check: the same executor entry point Phase 5 already
  calls, not a parallel reimplementation).

### 16. Phase 12 — Remote execution

**Prerequisite**: Phase 4 (batch parallelism) -- remote execution is
"replace/augment the executor's worker pool with remote workers," not
a new runner concept, and it is the highest blast-radius, most
speculative item on the list (new failure modes: network, auth,
partial results, version skew between client and remote worker) --
done LAST for that reason, matching both the user's own numbering and
the actual risk ordering.

**Scope**: an `Executor` protocol (small ABC or `Protocol`, matching
the existing `SolverBackend` protocol precedent in
`workbench/solvers/base.py`) with the local `ProcessPoolExecutor`-based
implementation (Phase 4) as one concrete backend, and a new
`RemoteExecutor` backend that dispatches a job's `DeviceSpec` JSON (the
existing wire format, unchanged) to a remote worker over a documented,
narrow transport (e.g. SSH + the SAME `gui.services.solver_runner`
CLI entry point already used locally, or a small HTTP job-submission
service -- concrete transport choice deferred to a dedicated design
doc before implementation, since it is genuinely a new architectural
surface, not a small addition). Explicitly descoped from this plan:
authentication/credential management design (flag as a hard
prerequisite question for the user before this phase starts, not an
implementation detail to improvise), and any change to what a
"job" IS (still one `DeviceSpec` in, one result `.npz` out).

**Acceptance gates** (`tests/test_m30_remote_executor.py`, most of
which will need a local stand-in "remote" -- e.g. a second local
process pretending to be remote over loopback -- since a real remote
worker fleet is outside this repo's test environment):
- G-PROTOCOL-PARITY: `RemoteExecutor` and the local executor implement
  the identical `Executor` protocol -- `StudyController`/Phase 4's
  matrix runner works unmodified against either.
- G-PARTIAL-FAILURE: a remote worker that drops mid-job is detected and
  reported as that row's failure, not a hang or a silently-lost row.
- G-NO-TRANSPORT-IN-DEVICESPEC: `DeviceSpec`'s wire format itself gains
  no remote-transport-specific fields -- the job payload stays
  identical whether dispatched locally or remotely (this is the same
  "wire format stays the wire format" discipline `DeviceSpec`/
  `ResultStore` already hold to).

**Open design question for the user, to resolve before implementation
starts** (not answerable from the existing codebase alone): what
remote transport is actually wanted (SSH to lab machines? a cloud
queue? an existing internal service?) -- this determines the whole
shape of `RemoteExecutor` and should not be guessed.

### 17. Reconciling the user's priority order with the dependency graph

User's stated priority: Study Manager, Matrix Viewer, Run Comparison,
Checkpoint/Resume, Provenance, Constraints, Adaptive Sweep, Remote
Execution. The real build order, given what each phase needs to
already exist:

```
Phase 5  Study Manager        (needs: Phase 1 done, Phase 4 built first)
Phase 6  Matrix Viewer        (needs: Phase 5)
Phase 8  Study manifest/resume (needs: Phase 5; built together with 9's schema)
Phase 9  Provenance           (needs: Phase 8's manifest to attach to;
                                built alongside Phase 8, not strictly after)
Phase 7  Run Comparison       (needs: Phase 5's runs to compare; independent
                                of 8/9's manifest, so can land any time
                                after Phase 5 -- placed here only to match
                                the user's numbering as closely as the real
                                dependencies allow)
Phase 10 Constraints          (needs: Phase 1 + Phase 2)
Phase 11 Adaptive sweep       (needs: Phase 1 + Phase 4)
Phase 12 Remote execution     (needs: Phase 4; last -- highest risk)
```

This preserves the user's intent (Study Manager and Matrix Viewer
first, Remote Execution last) while fixing the one real inversion:
Provenance (listed 5th) and Checkpoint/Resume (listed 4th) share a
single manifest schema and are built together, and Run Comparison
(listed 3rd) does not actually need either of them to land first.

## 8. Decisions (confirmed with user 2026-09-07)

1. Phase order: 1 (splits) -> 2 (calibration) -> 4 (batch
   parallelism) -> 3 (DeckBuild import), as proposed.
2. Phase 2 uses `scipy.optimize.minimize(method="Nelder-Mead")`, not a
   from-scratch simplex.
3. Phase 3's DeckBuild import covers a documented, bounded syntax
   subset with a self-referential round-trip gate (our own decks
   through the supported subset) -- not blocked on sourcing a real
   external DeckBuild corpus.
4. Phase 4 lands as new infrastructure only; `FamilySweepController`'s
   existing sequential loop is NOT retrofitted in this plan (left for
   a later follow-up if wanted).

Implementation proceeds in this order, each phase gated (tests green)
before moving to the next.

### 8c. What actually landed (2026-09-07)

- **Phase 1 (splits)**: `workbench/splits.py` (`expand_splits`,
  `run_split_matrix`, `SplitRow`) + a `SPLIT` statement added to
  `workbench/workflow.py`'s deck grammar (`DeckRun.splits`).
  Gates: `tests/test_m30_splits.py`, 15/15 green.
- **Phase 2 (calibration)**: `workbench/calibration.py`
  (`GoalFunction`, `CalibrationResult`, `solve_field`, `calibrate`),
  driving `scipy.optimize.minimize(method="Nelder-Mead")` over
  template parameters, each trial solved equilibrium-only through the
  existing `gui.services.solver_runner.run_job`. An unreachable/
  out-of-range trial is penalized (`UNREACHABLE_PENALTY = 1e6`), never
  raised out of the optimizer; a search where every trial fails reports
  `converged=False` honestly. Gates: `tests/test_m30_calibration.py`,
  5/5 green, including the load-bearing G-RECOVER gate (a planted
  `na_cm3` on a `pn_diode` template recovered within 3% from a
  perturbed initial guess).
- **Phase 4 (batch parallelism)**: `workbench/batch.py`
  (`run_jobs_parallel`, `solve_split_matrix`, `BatchOutcome`), a
  `concurrent.futures.ProcessPoolExecutor` pool (worker count capped by
  `default_worker_count`, same conservative convention as AGENTS.md's
  own `-n 6` guidance) with `OPENBLAS_NUM_THREADS=1` pinned per worker
  via the pool initializer. `solve_split_matrix` wires Phase 1's row
  builder directly into the pool: a row that fails to BUILD never
  reaches the solver. Gates: `tests/test_m30_batch.py`, 7/7 green,
  including a bit-identity check (parallel vs. sequential `run_job`
  results are `np.array_equal`, not just close) and a real worker-
  process check that `OPENBLAS_NUM_THREADS` is actually `"1"` inside a
  pool worker.
- **Phase 3 (DeckBuild-dialect import)**: `workbench/
  deckbuild_import.py` (`import_deckbuild`), translating the documented
  five-statement subset (module docstring: `go atlas`, `#template ID`,
  `electrode name=... voltage=...`, `solve name=... vstep=...
  vfinal=... [vstart=...]`, plain `KEY=value`) into our own dialect and
  handing off to the real `run_deck_full` -- no second validator.
  Anything outside that subset (e.g. a `mesh`/`region` statement)
  raises a line-numbered error citing the ORIGINAL deck's line number,
  not the internal translation's. Gates:
  `tests/test_m30_deckbuild_import.py`, 6/6 green, including the
  self-referential round-trip gate (an `nmos` deck in both dialects
  producing bit-identical `DeckRun.bias`/`.sweep`/built
  regions/contacts).
- **Regression status**: full suite (`tests/ gui/tests/`, `-n 6`, `-m
  "not slow"`) under the `TCAD` env: 1279 passed / 1 xfailed before
  Phases 2-4 (Phase 1 only), 1297 passed / 1 xfailed after all four
  phases (+18 = exactly the new Phase 2/3/4 tests) -- zero failures,
  same 39 pre-existing warnings both times (unrelated scipy sparse-
  solver `RuntimeWarning`s and an intentional mesh-refinement
  `UserWarning`, not introduced by this work). No numerical core
  (`pytcad/*.py`) file was touched by any of the four phases. The
  `-m "slow"` gate battery (`tests/ gui/tests/`, `-n 6`) also run this
  session per AGENTS.md's "slow gate battery must run before any
  milestone completion claim" rule: 19 passed, 0 failures, only
  pre-existing adaptive-refinement `UserWarning`s. Part I (Phases
  1-4) is therefore fully gated as of 2026-09-07.
