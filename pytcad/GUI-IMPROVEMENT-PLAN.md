# GUI-IMPROVEMENT-PLAN.md
# PyTCAD Desktop GUI: v0.6+ improvement roadmap
# Formal milestone spec

Status: **PHASES 1-4 SHIPPED (2026-08-29), code-reviewed and fixed the
same day.** Phase 1 (1a/1b/1c) and Phase 2 (2a/2b/2c/2d) all implemented
and gated. Phase 3 (3a/3b/3c/3d — diagnostics, provenance, continuation
records) and Phase 4 (runtime state validation, StatusIndicator,
ValidationBanner, ValidatedTextField) landed, then a medium-effort
/code-review pass found 8 real bugs across them (a QML id/objectName typo
causing a runtime crash, dead validator logic, stale non-notifying
ListView bindings, a consumer with no real data producer, faked
placeholder checks, duplicated logic, hardcoded theme colors) — all 8
fixed same day; see history.md for the full list. Full suite verified
after the fixes: 833 passed, 19 skipped, 1 xfailed, 4 failed (1 M16 BTBT
gate — pre-existing on the unmodified base commit, confirmed by stashing
all changes and rerunning, spun off as its own task; 3 M20 DG gates,
user-decided open — see M20-DENSITY-GRADIENT-PLAN.md).

Follow-on work: 3D visualization -- see `3D-VISUALIZATION-PLAN.md`
(Phases 1-2 shipped 2026-08-29/30: a real 3D example device, a
PyVista/VTK viewer window with isosurface controls; Phases 3-5 not
started). That work also fixed a real bug in THIS plan's own Phase 1-4
landing: `gui/app.py` bootstrapped with `QGuiApplication`, which
hard-crashes the whole process on the first `QWidget` construction --
switched to `QApplication` (a confirmed strict superset; zero effect on
the QML-only behavior everything in this plan actually uses).

Scope decided with the user (2026-08-29): all four candidate areas below,
phased by dependency and effort rather than picked one at a time --
visualization gaps, dimensionality/backend selection, physics-model GUI
wiring gaps, and diagnostics/provenance UX.

Every item here is grounded in a gap the GUI's own docs already name
(`gui/README.md`'s "Honest limits" sections, ARCHITECTURE.md's UI gap
list) or a gap found by reading the actual rendering code
(`gui/visualization/mpl_canvas_item.py`) -- nothing invented. Where an
item is blocked on solver work that doesn't exist yet (M17 transient,
M23 2D process), that is stated as a real dependency, not glossed over
as a GUI-only task.

Conventions: same discipline as every other milestone in this tree --
red tests first (`gui/tests/`, headless QML pattern), no plot without
a store a test validates, honesty about what's NOT covered, suite
green before calling a phase done.

------------------------------------------------------------------------
0. CURRENT STATE (verified against the code, not just the docs)
------------------------------------------------------------------------
`gui/visualization/mpl_canvas_item.py` renders every 2D field
(`Structure`, `Doping`, `Bands`, `Recombination`, and the base
potential/n/p/doping modes) as a single `ax.pcolormesh(...)` raster --
there is no `contour`/`contourf` overlay and no facility to extract a
1D slice through a 2D field. `_draw_convergence` already exists and
plots the stored Newton residual trace (wired to the Physics Lab's
"Plot convergence" button) -- diagnostics are not starting from zero,
they're missing the rejected-point and continuation-stage layers on
top of an existing, working trace view.

Panel/controller landscape (`gui/qml/panels/`, `gui/controllers/`):
`ViewportPanel` + `AppController` own field/curve display;
`SweepPanel` + `FamilySweepController` own I-V/family sweeps;
`CvController` owns the MOS C-V sweep (data lives in `cvSweep.cvStore()`
today, no dedicated viewport mode); `PhysicsLabPanel` + `LabController`
own the model catalog and convergence view; `StructurePanel`/
`MeshPanel`/`ProcessPanel` own device construction. No panel exposes
dimensionality or backend choice anywhere -- both are implicit in
which construction path (Process Flow vs. Structure/Device Builder)
the user takes, and backend selection exists only in a job's raw JSON.

------------------------------------------------------------------------
1. PHASE 1 [S] -- LOW-EFFORT, HIGH-VALUE (data already exists)
------------------------------------------------------------------------
These three items wire UI onto data the backend already computes and
stores; none touch the solver.

1a. DEDICATED C-V PLOT MODE.
    `cvSweep.cvStore()` already holds a validated, gated C-V curve
    (`gui/tests/test_cv_mode.py` checks it against the analytic
    C_ox/C_min landmarks) but the only way to see it is through
    whatever ad hoc surface currently reads the store -- there is no
    "C-V" entry in `ViewportPanel`'s mode selector next to Curves/
    Bands/Recombination. Add one: a `_draw_cv(ax)` method in
    `mpl_canvas_item.py` (C vs. Vg, log or linear y), a `"CV"` viewport
    mode string, and a QML entry in `ViewportPanel.qml`'s mode list.
    Acceptance: headless smoke test renders CV mode after a C-V sweep
    and asserts the axes carry the expected C_ox-scale y-range (same
    landmark check `test_cv_mode.py` already performs on the raw data,
    now asserted on the rendered mode instead of just the store).

1b. FAMILY-SWEEP STALENESS WARNING.
    "Family sweeps re-solve the *last solved* device; editing the
    structure after a solve invalidates the batch until the next Run"
    (README, honest limits) -- today this is silent. Add a dirty-style
    indicator on the Family panel (reuse the existing dirty-marker
    pattern from the project title bar) that appears the moment
    `AppController`'s structure-dirty signal fires after a family
    result exists, and clears on the next successful Run. No new data
    path -- this listens to a signal that already exists.
    Acceptance: headless test edits structure after a family run and
    asserts the staleness flag is set; asserts it clears after Run.

1c. M20 (density-gradient) EQUILIBRIUM-ONLY RUN MODE.
    `dg` is selectable in the Physics Lab and fully landed at the
    Python level (`Models(dg=True)`, `MOSCapacitor(dg=True)` --
    M20-DENSITY-GRADIENT-PLAN.md, history.md Addendum 19) but the GUI
    has no way to invoke it: `Device1D.solve_bias` refuses `dg=True`
    with an actionable error, and the GUI always requests a biased
    solve. Add an "Equilibrium only" run mode toggle (Structure or
    Sweep panel -- TBD in design) that calls `solve_equilibrium()`
    instead of `solve_bias()` for the 1D Process-Flow path when `dg`
    is checked in the Physics Lab, surfacing psi/n/p at V=0 through
    the existing field viewport modes unchanged.
    Acceptance: headless test enables `dg` + equilibrium-only mode,
    runs, and asserts a result renders without the solve_bias refusal
    firing; a second test confirms the refusal still fires for a
    normal biased Run with `dg` on (regression: this mode must not
    silently swallow the refusal for 2D/3D or a biased 1D request).

------------------------------------------------------------------------
1d. PHASE 1 IMPLEMENTATION RECORD (2026-08-29)
------------------------------------------------------------------------
All three items landed as scoped, [x]:

1a: `CVController.cvResultForQml` (Property, mirrors AppController's own
    `sweepResultForQml`) + `MplCanvasItem.setCvSource`/`_draw_cv` (a
    dedicated mode rather than reusing "series"/Curves -- an I-V and a
    C-V SweepResult share the same dataclass shape, but "series" mode's
    labels are written in terms of a swept contact's current, not
    honestly labeled as capacitance) + a `"C-V"` entry in
    ViewportPanel's mode selector. Tests: `test_cv_mode.py`'s two new
    canvas-level tests (placeholder-before-any-run; rendered curve's
    y-range matches `MOSCapacitor.analytic_landmarks()['C_ox']`).

1b: `FamilySweepController._on_structure_changed` (connected to
    `AppController.structureChanged`) sets an `isStale` flag once
    curves exist; cleared at the start of the next accepted
    `runFamily()`. Surfaced in `SweepPanel.qml`'s existing status label
    rather than a new widget. Test:
    `test_family_goes_stale_after_a_structure_edit` (self-caught test
    bug along the way: the test's own second `runFamily()` call was
    silently no-op'd by `runFamily`'s "already running" guard because
    it only waited for the family's FIRST curve, not all three --
    fixed by waiting for `len(fam.curves) == 3`, not `bool(fam.curves)`,
    matching the same trap `test_family_curves_reach_the_canvas`'s own
    comment already documents).

1c: `PhysicsLabController.equilibriumOnly`/`setEquilibriumOnly`
    (Property/Slot) read by `AppController.run()`, which sets
    `spec.bias = None` instead of the usual contact-voltage dict when
    the toggle is on. Solver-side, this needed NO changes at all:
    `solver_runner.py`'s `_solve_all()` already skips `solve_bias`
    entirely whenever `spec.bias is None`
    (`test_solver_runner.py::test_equilibrium_only_when_bias_is_none`
    already proved this path works, pre-existing). Found and guarded
    one real interaction while implementing: a sweep always overrides
    the bias branch regardless of `spec.bias` (`_solve_all` checks
    `spec.sweep` FIRST), so equilibrium-only + an armed sweep would be
    silently ineffective rather than safely inert -- `run()` now
    refuses that combination with an actionable error before the
    subprocess starts. Checkbox lives in `PhysicsLabPanel.qml` next to
    the model catalog list. Three tests in `test_physics_lab.py`: the
    happy path (dg + equilibrium-only actually runs and produces
    `solved_bias=False`), the regression (dg WITHOUT the toggle still
    refuses on bias, i.e. the toggle doesn't silently widen M20's
    scope), and the sweep-conflict refusal.

Full non-slow suite (`tests/ gui/tests/`, `-n 6`, not slow): 766
passed, 1 xfailed, 0 regressions -- the only failures anywhere are the
3 pre-existing M20 gamma-calibration gates (unrelated, left open by
explicit user decision; see M20-DENSITY-GRADIENT-PLAN.md sections 6-7).

------------------------------------------------------------------------
2. PHASE 2 [M] -- VISUALIZATION DEPTH
------------------------------------------------------------------------
2a. CONTOUR OVERLAYS ON 2D FIELD MODES.
    Add an optional `ax.contour(...)` overlay (a handful of
    auto-selected levels, or a "levels" spinbox) on top of the
    existing `pcolormesh` for every 2D field mode. Purely additive to
    `_draw_*` methods already there -- no new data plumbing, since
    contour needs exactly the same `(x, y, values)` triple the raster
    already has.
    Acceptance: headless test renders a 2D field with contours on and
    asserts the axes contain both a `QuadMesh` and at least one
    `LineCollection`/`ContourSet` artist; contours-off path stays
    pixel-identical to today's render (regression pin).

2b. LINE-CUT MODE.
    A click-and-drag (or two-point-entry) horizontal/vertical cut
    through a 2D field, extracted from the already-stored field array
    (`values[j, :]` or `values[:, i]` at the nearest mesh row/column --
    no interpolation needed for v1, honestly labeled "nearest node,"
    not "exact cut," since the mesh may be non-uniform) and plotted
    through the EXISTING Curves rendering path (`_draw_series`) rather
    than inventing a second line-plot renderer.
    Acceptance: headless test requests a cut at a known y (or x) and
    asserts the returned 1D array matches the stored field's row/
    column at the nearest mesh index directly (no rendering-only
    check -- the extraction itself is gated).

2c. BACKEND SELECTOR (1D two-terminal scope only, matching what DEVSIM
    actually supports).
    Add a backend dropdown (pytcad / devsim, devsim greyed out and
    disabled with a tooltip when `workbench.solvers.devsim_backend`
    reports unavailable) to the Process-Flow path only -- the DEVSIM
    backend is 1D-two-terminal-only today (README, v0.5.x section), so
    the selector must not appear for the Structure/Device-Builder (2D)
    path, and must not silently accept an incompatible job (gates,
    heterostructures, impact ionization) with a wrong-backend choice --
    reuse the exact compatibility checks `workbench/solvers/` already
    raises on, surfaced as a disabled option with the same message
    rather than a run-time crash.
    Acceptance: headless test selects devsim on a compatible 1D device
    and asserts the result comes back tagged with that backend
    (`converge__trace` provenance already carries this per README);
    a second test asserts the selector is absent/disabled for a 2D
    device and for a device with an incompatible model (e.g. impact
    ionization) enabled.

2d. SIDE-BY-SIDE BACKEND COMPARISON (extends the existing "Compare
    models" pattern).
    "Compare models" already re-solves the identical device with
    every model disabled and overlays the result dashed (M9, README).
    Generalize the SAME mechanism to re-solve with a DIFFERENT backend
    instead of different models, for the compatible-device subset from
    2c, overlaying pytcad vs. devsim I-V curves the way the cross-
    backend validation test already does numerically
    (`tests/`-level cross-backend gate) -- this makes an existing,
    already-gated numerical comparison visible in the GUI rather than
    only in test output.
    Acceptance: headless test runs the comparison on a compatible
    device and asserts two curves land in the store with distinct
    backend tags; asserts the option is disabled for an incompatible
    device (same guard as 2c).

------------------------------------------------------------------------
2e. PHASE 2 IMPLEMENTATION RECORD (2026-08-29)
------------------------------------------------------------------------
All four items landed as scoped, [x]:

2a: a shared `MplCanvasItem._maybe_contour(ax, x, y, values)` inserted
    right after each of the FOUR existing `pcolormesh` call sites (the
    main field mode, doping preview, bands 2D map, recombination 2D
    map) -- reads the SAME already-log-transformed `values` array each
    site already builds for its own colour map, so the overlay lines
    align with what's actually shown rather than a second, possibly
    differently-scaled computation. A `contours` boolean Property
    (mirrors `logScale`'s own pattern exactly) + a checkbox in
    ViewportPanel.qml. Tests assert `len(ax.collections)` before/after
    (1 -> 2, a `pcolormesh` plus one `QuadContourSet`) across two
    independent code paths (NpzResultStore.scalar_field and the
    workbench-observables bands path), plus a regression pin that
    contours=False renders byte-for-byte the same single collection as
    before this phase.

2b: `extract_line_cut(axes, field, orientation, position_cm)` in
    `gui/services/result_store.py` -- a pure function, gated directly
    (5 tests: horizontal/vertical extraction match the stored field's
    row/column exactly; a NON-uniform-mesh case proves the "nearest
    node, not interpolated" honesty claim actually means something;
    rejection of non-2D fields and bad orientation strings) before any
    rendering test touches it. `MplCanvasItem._draw_cut` is a DEDICATED
    method (not SweepResult + `_draw_series` verbatim) for the same
    reason "cv" mode was in Phase 1a: a spatial coordinate in um is not
    honestly labeled through a code path written for a swept contact's
    voltage. Orientation ComboBox + position TextField + "Cut" button
    in ViewportPanel.qml; "Line Cut" in Main.qml's mode selector. The
    cut always reads whatever field the EXISTING field-mode dropdown
    already has selected -- no separate field-selection UI needed.

2c: by far the largest item -- the backend selector's real gap wasn't
    the missing dropdown, it was that NOTHING wired DEVSIM into a
    subprocess-invokable path at all (`AppController._runner` always
    spawned `gui.services.solver_runner` unconditionally; devsim's
    `SolverBackend.run()` was only ever called directly in tests).
    Landed:
    - `DeviceSpec.backend: str = "pytcad"` (additive field, same
      `d.get(key, default)` backward-compat pattern every prior field
      addition here used -- an old job file simply lacks the key).
    - `solver_runner.py`'s CLI `main()` now reads the job's own
      `backend` field and dispatches through `get_backend(id)` for
      anything but "pytcad" (which still calls `run_job()` directly,
      bit-identical to every pre-2c job) -- JobRunner still always
      spawns the SAME module; the job itself carries the choice.
    - `workbench/solvers/devsim_backend.py` gained
      `check_devsim_compatible(spec)`, refactored out of `run()`'s own
      3 existing raises (non-1D, wrong contact count, gate contacts)
      PLUS two NEW ones found while implementing this: the backend
      never read `spec.models` or `spec.region_materials` AT ALL, so a
      non-default model config or a heterostructure job was previously
      solved SILENTLY WITHOUT the requested physics rather than
      refused -- exactly the "hidden failure" pattern this codebase's
      own house rule exists to catch elsewhere (Device1D/2D/3D's dg/
      impact/incomplete_ion guards). Now raises for both, with the
      exact message the GUI selector also shows.
    - `AppController.canSelectBackend` (dimensionality==1 -- gates
      VISIBILITY, not just enabled-state, per the plan's own
      requirement) and `backendOptionsForQml()` (checked against the
      Lab's CURRENT model_config, not stale `spec.models`, since
      run() only copies that onto the spec at Run time) both reuse
      `check_devsim_compatible` as the single source of truth -- the
      selector can never promise a run that would then be refused.
      `run()` itself re-checks defensively in case the spec changed
      after a backend was picked without re-touching the selector.
    - ComboBox in Main.qml's toolbar, custom delegate greying out
      "devsim" with its exact refusal message as a tooltip.
    9 new tests: `check_devsim_compatible`'s 5 cases in isolation, the
    selector's visibility/enable-state logic, a REAL run through the
    devsim backend end-to-end tagging the result, the defensive re-
    check, and a QML presence/visibility smoke test.

2d: `AppController.runBackendComparison()` is a sibling of the
    existing `runModelComparison()` (M9), reusing the SAME
    `_comparison_runner`/`_comparison_store`/`comparisonChanged`
    machinery -- one dashed overlay at a time, whichever comparison
    ran most recently, rather than a second rendering path. Unlike the
    models-off comparison, `models` is left UNCHANGED (this compares
    ENGINES on the same physics request, not a different one), and it
    reuses `check_devsim_compatible` before starting rather than a
    separate guess. `MplCanvasItem` gained `setComparisonLabel`/
    `_comparison_label` (default "all models off", so M9's own call
    site is untouched) so the overlay's legend says which comparison
    produced it. Discovered while implementing: `runModelComparison`
    itself had NO QML entry point at all before this (Python-API/test-
    only, the same gap Phase 1c found for `dg`) -- added "Compare:
    all models off" alongside the new "Compare: other backend" button
    in the Physics Lab, both gated on `hasResult`/`canSelectBackend`.

Full non-slow suite (`tests/ gui/tests/`, `-n 6`, not slow): 790
passed, 1 xfailed, 0 regressions -- confirmed after each sub-item and
again at the end. Only pre-existing M20 failures anywhere (see status
line above).

------------------------------------------------------------------------
3. PHASE 3 [L] -- DIAGNOSTICS AND PROVENANCE — COMPLETE (2026-08-29)
------------------------------------------------------------------------
3a. REJECTED-BIAS-POINT OVERLAY ON THE CONVERGENCE VIEW.
    `_draw_convergence` already plots the Newton residual trace for
    the accepted path. M15/M22's continuation drivers already record
    which arm attempts were rejected (the "rejected arm attempt"
    machinery `app_controller.py:374` already reads from) -- extend
    `_draw_convergence` to mark rejected points distinctly (different
    marker/colour) on the same axes, sourced from data the continuation
    driver already returns, not a new solver-side computation.
    Acceptance: headless test runs a sweep that has at least one
    rejected/backtracked point (an existing M15/M22 test fixture
    should already produce one) and asserts the rendered convergence
    view's artist count/labels include a rejected-point marker.

3b. PER-STAGE CONTINUATION RECORD VIEW.
    M15's strength-ladder and M22's arc-length continuation both
    record a per-stage history (already the evidence those milestones'
    own gates read -- see M15-IONIZATION-PLAN.md, M22-LINSOLVE-PLAN.md).
    Surface it as a small table/strip next to the convergence plot:
    stage index, parameter value, node count if adaptive meshing (M21)
    was used, accepted/rejected. Read-only, no new computation.
    Acceptance: headless test runs a continuation-driven sweep and
    asserts the stage table's row count matches the driver's own
    returned history length.

3c. MESH STATISTICS PANEL.
    A small read-only panel (could live in `MeshPanel` or `ViewportPanel`'s
    sidebar) showing node count, grading ratio, and (when M21 adaptive
    refinement was used) the pass-by-pass history M21's own `adapt_solve_*`
    already returns (nodes/QoI/delta/cause per pass -- M21-MESHING-PLAN.md
    section 3). Purely a read of data the driver already produces.
    Acceptance: headless test runs an adaptive-mesh solve and asserts
    the panel's node-count value matches the final mesh's `.N`/`.size`.

3d. PROVENANCE TRACE (mesh -> physics -> material -> backend).
    The larger, explicitly-named vision-doc gap ("a dedicated
    provenance-trace UI... clicking through mesh -> physics ->
    material -> backend," ARCHITECTURE.md section 6): a single
    read-only summary view assembled from data that ALREADY exists
    across separate panels today (mesh stats from 3c, model config
    from the Physics Lab, material from `region_materials`, backend
    from 2c's tag) rather than a new data source. Scope this as
    "consolidate what's already computed into one view," not
    "instrument new provenance tracking" -- the latter would be a much
    larger, separate piece of work.
    Acceptance: headless test asserts the provenance view's rendered
    text/fields match each contributing controller's own current
    state (mesh controller, Physics Lab controller, structure
    controller, backend selector) for a device solved for through more
    than one of them, i.e. this is an aggregation-correctness gate.

------------------------------------------------------------------------
4. EXPLICITLY GATED ON CORE SOLVER WORK NOT YET DONE
------------------------------------------------------------------------
These items were part of the original "visualization gaps" answer but
are NOT pure-GUI tasks -- the underlying data does not exist yet:

- TRANSIENT PLOTTING: blocked on M17 (transient simulation), "not
  started" per ARCHITECTURE.md. No GUI work is possible before M17
  lands a transient result schema to plot.
- GEOMETRY-FROM-PROCESS VIEWER: blocked on M23 (2D process geometry
  engine), "not started." `pytcad.process` is 1D-only today (README's
  "Not supported, by design" list) -- there is no 2D process geometry
  for a viewer to show.
- DEVICE3D GUI PATH: superseded by a real plan as of 2026-08-29 -- see
  `3D-VISUALIZATION-PLAN.md` (PyVista/VTK, a separate top-level window
  launched from the QML app rather than embedded in it; phased as
  foundation -> isosurfaces -> volumetric rendering -> animated sweep
  playback -> exploded structural view). Phases 1-2 SHIPPED 2026-08-29/
  30 (a real 3D example device, a working isosurface viewer); Phases
  3-5 not started. Tracked entirely under that separate document, not
  as phases of THIS plan; do not start its remaining phases without an
  explicit "Start on Phase N" instruction against that document
  specifically. 3D structure/process AUTHORING (as opposed to
  visualizing an already-solved 3D result) remains unscoped even there
  (see that plan's Phase 5 and "Explicitly out of scope" section).

Do not schedule these under this plan's phases; revisit once their
solver-side dependency lands.

------------------------------------------------------------------------
5. AMENDMENT MECHANISM
------------------------------------------------------------------------
None of Phases 1-3 touch `pytcad/` (the numerical core) -- every item
reads data the solver/analysis layer already computes and stores. Per
the GUI's own house rule ("GUI grows only along validated data paths;
no plot without a store a test validates" -- SENTAURUS-PARITY-PLAN
material now in ARCHITECTURE.md section 4b.4), no FD-Jacobian or
core-amendment process applies here; the applicable discipline is
`gui/tests/`'s existing headless-QML pattern plus a store/data
assertion for every new view, exactly as specified per item above.

------------------------------------------------------------------------
6. SUGGESTED ORDER
------------------------------------------------------------------------
1a -> 1b -> 1c (Phase 1, independent, do in any order -- pick the one
that unblocks whatever the user needs next)
2a -> 2b (visualization, no dependency on 2c/2d)
2c -> 2d (backend selector must land before the comparison view that
depends on it)
3a -> 3b -> 3c -> 3d (diagnostics naturally builds toward the
provenance aggregation, which depends on the others existing)

Phases are independent of each other (1, 2, 3 do not block one
another) -- order among phases is a priority call, not a dependency.
