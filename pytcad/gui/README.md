# PyTCAD Desktop GUI (v0.1 – v0.5.x)

A PySide6 / Qt Quick desktop frontend for the PyTCAD solver.

**This is v0.5.0 — the solver-backend boundary formalized on top of the
v0.1–v0.4 spine.** It loads a built-in 2D MOSFET, solves it, and
visualizes fields; edits 2D structures and 1D process flows in undoable
workbenches; runs single-contact **voltage sweeps** (I–V, Id–Vg) with
curve visualization and derived readouts; validates every solved result
against an explicit, versioned schema before displaying it; and now has
a genuine second solver backend — DEVSIM, optional and auto-detected,
with warm-started bias ramps/sweeps validated by cross-backend I–V
tests. Multi-parameter batch sweeps, C–V analysis, and 3D visualization
remain later work.

## Install

```bash
cd pytcad
pip install -r requirements.txt
pip install -r gui/requirements.txt
```

Requires Python 3.9+ (tested on 3.14) and PySide6 >= 6.10.1.

## Run

```bash
cd pytcad
python -m gui.app
```

## What v0.1 does

- **Load example** builds a 2D n-channel MOSFET (~7.7k nodes) and draws its
  doping map immediately — no solve needed to see the structure.
- **Run** solves Poisson equilibrium then the biased drift-diffusion system.
  The solve runs in a **separate process**, so the window stays responsive;
  Newton iterations stream into the console as they happen.
- **Stop** kills that process. Because results are written atomically
  (temp file, then rename), a canceled run leaves nothing behind and no
  partial result is ever displayed.
- After a solve, the field dropdown offers potential, electron density,
  hole density, and doping, with zoom / pan / fit / reset and an optional
  log scale.
- Backend failures appear as a concise reason with an expandable
  traceback. The GUI process itself does not crash.

## Architecture

```
QML (presentation only)
  -> controllers/   Qt models + AppController: all UI-facing state
  -> services/      DeviceSpec, JobRunner, ResultStore: the backend boundary
  -> solver_runner.py   runs in a subprocess; imports pytcad; no Qt
  -> pytcad/        the numerical engine, unmodified
```

Three properties worth knowing:

1. **The numerical engine is untouched.** The GUI adds zero lines to
   `pytcad/`. Solves run out-of-process precisely so that cancellation
   never means killing a thread inside a sparse LU factorization.
2. **`solver_runner.py` imports no Qt** and works as a plain CLI:
   ```bash
   python -m gui.services.solver_runner job.json out.npz
   ```
   The same backend is therefore reachable from a notebook or a script —
   the GUI is replaceable.
3. **Dimensional differences stop at the boundary.** pytcad exposes
   current as `Jn` in 1D, `Jn_x`/`Jn_y` in 2D, `Jn_x/y/z` in 3D, and
   `terminal_current` returns A/cm in 2D but real amperes in 3D.
   `extract_result()` in `solver_runner.py` is the only code that knows
   this; everything above it sees uniform field names with explicit units.

## Tests

```bash
cd pytcad
QT_QPA_PLATFORM=offscreen python -m pytest gui/tests/ -v
```

Runs headless — no display needed. The numerical suite (`tests/`) is
independent and must keep passing unchanged.

## Known limitations in v0.1

- One built-in example; no structure/process/mesh editor yet.
- Single bias point per run — no I-V, C-V, or Id-Vg sweeps.
  *(Superseded in v0.4 for single-contact voltage sweeps; see v0.4 below.
  C–V and multi-contact/multi-parameter sweeps are still future work.)*
- 3D results are shown as a central z-slice; there is no 3D renderer.
  VTK/PyVista are intentionally not dependencies yet.
- The device spec is embedded in the job file as JSON, so very large
  meshes make large job files. Fine at v0.1 scale; a binary sidecar is
  the obvious later fix.
- Progress parsing reads the solver's printed iteration lines. If that
  format changes, progress display degrades to a plain running indicator —
  results are unaffected, since they come from the result file.
- No project save/load UI yet, though the format is designed
  (see the design spec).

## v0.2 — Structure + Mesh Workbench

**Implemented:**
- Named doping regions (rectangular, uniform doping) composed in list
  order onto a single silicon domain. Compositing order is shown as an
  explicit priority number in the Regions list, with up/down reorder
  buttons — reordering is undoable like any other structure edit.
- Contact and gate boundary editing (edge + optional sub-range, voltage).
- Gate flatband voltage: computed (via `moscap.flatband_voltage()`, the
  same path `build_mosfet()` uses) or a manual override.
- Structure validation (dimensions, duplicate IDs, boundary extents, gate
  substrate-doping uniformity) blocking Run/Save on any error.
- 2D mesh editing (uniform `Nx`/`Ny`, or graded via the existing
  `mesh.graded_mesh()`), with node/cell count and a rough memory estimate.
- Structure, Doping, Mesh, and Results viewport modes, plus a "Load
  structure example" toolbar button/menu item to reach the new example.
- Schema-versioned project save/load (`schema_version: 2`) via
  File → Save Project As.../Open Project... or Ctrl+S, through a native
  `QtQuick.Dialogs` `FileDialog` (see "v0.2.1 polish pass" below);
  results stay separate `.npz` files, never embedded in the project file.
- Undo/redo and a dirty-state indicator (`*` in the title bar), scoped to
  structure/mesh metadata edits only.
- A close-confirmation dialog ("Save"/"Don't Save"/"Cancel") when
  quitting with unsaved changes.
- A second, purpose-built structure example (`mosfet_2d_structure`) for
  exercising this workbench — see "Two examples" below.

**v0.2.1 polish pass:**
- Save/Open now use `QtQuick.Dialogs`' native `FileDialog` (the
  platform's real file picker, e.g. via the Wayland/GTK desktop portal)
  in place of the earlier typed-path `Dialog`. The project name saved
  into the file is derived from the chosen filename, since a native
  picker has no room for a separate name field.
- The close-confirmation dialog now offers Save/Don't Save/Cancel
  (previously Don't Save/Cancel only). Save opens the native Save dialog
  and quits once it actually saves; Cancel, or dismissing the file
  picker, leaves the app open with changes still unsaved.
- The "Doping" viewport mode now rasterizes the structure's own regions
  live (via the same `rasterize_doping()` `to_device_spec()` uses) when
  no solve has happened yet, instead of showing "No project loaded" for
  a structure that is perfectly valid but unsolved. Once a solve
  produces a ResultStore, Doping mode goes back to showing solved field
  data, as before.
- Fixed a real, previously-shipped bug found while re-verifying on a
  real display: `MplCanvasItem.setStructureSource()` unconditionally
  forced its internal mode to `"structure"`, silently overriding
  whatever mode `ViewportPanel.setViewMode()` had just set. Since QML
  always calls `setMode()` then `setStructureSource()` in that order,
  the **Mesh viewport mode was actually rendering the Structure
  diagram**, not a mesh grid, the whole time — no headless test caught
  it because the existing tests call the two methods in the opposite
  order. Also fixed a `GateEditor.qml` crash (`undefined.toString()`)
  that fired whenever a gate's flatband voltage was left in "computed"
  mode (Python `None` crosses to QML as `undefined`, not `null`).

**Planned (not yet implemented):**
- Per-region doping *profiles* beyond uniform (e.g. exposing
  `mosfet_doping()`'s own Gaussian/erfc shape as a region option).
- A second real semiconductor material, once the backend has one.

**Not supported, by design:**
- Meshed SiO2 or metal regions — oxide/metal remain boundary-condition
  concepts (`GateBC`'s `tox_cm`/`Vfb`, `DirichletBC`'s `V`), never
  separate materials, because `Device2D` takes exactly one material for
  the whole domain and `SILICON` is the only one pytcad defines. See the
  design spec section 3 for the full reasoning.
- Process simulation, FinFET/GAA, 3D structure/mesh editing, adaptive
  mesh refinement, arbitrary polygon/CAD geometry — all deferred to
  later versions.

**Two examples, not one retrofit:** `mosfet_2d` (v0.1, unchanged) uses
`build_mosfet()`'s smooth analytic doping profile and is not editable
through the Structure panel. `mosfet_2d_structure` (v0.2) is a second,
honestly-simpler MOSFET built from uniform rectangular regions so it
*is* fully editable. See the design spec section 17.5.

**Known limitations / gotchas in v0.2:**
- Scripting the app headlessly (CI, smoke tests): `Main.qml`'s
  `onClosing` handler opens a confirmation dialog whenever the project
  is dirty, and there's no human to dismiss it in a headless run — so
  calling `app.quit()` while `appController.isDirty` is `True` never
  actually lets `app.exec()` return. Always save (or undo back to
  clean) as the last state-changing step before quitting a script-driven
  session. This is the close-confirmation feature working as designed,
  not a bug; it's a real gotcha we hit writing this file's own
  verification script (see the v0.2 plan's Self-Review Notes).
- The mesh-info `ListView` in `MeshEditor.qml` can print a handful of
  benign "Unable to assign [undefined] to QString" warnings to stderr
  when its model array is replaced (e.g. after a mesh edit) — cosmetic
  console noise from delegate-recycling churn on a plain-array-bound
  model, not a data or rendering defect (verified: the bound values are
  always correct once settled).

**Verified on a real display, not just headlessly:** the whole 95-test
headless suite was passing before this app was ever actually shown on
screen — running it on a real Wayland session surfaced several real
layout defects (`Material: undefined`, overlapping region-row text,
missing reorder buttons, contacts/gates never wired into any panel at
all) that no headless test caught, since headless tests only check that
data is non-null, never pixel layout. All were found and fixed by
grabbing real `QQuickWindow.grabWindow()` screenshots, pixel-measuring
actual panel boundaries, and in one case a native `gdb` backtrace. If
you change QML layout code here, don't trust the test suite alone —
actually look at it.

The v0.2.1 polish pass repeated this real-display verification (Structure,
Doping-before-solve, Mesh, Results-after-solve, region reorder, contact
editor, gate editor, Save/Open, dirty-state indicator, close dialog) and
it caught two more real bugs the 95-test suite missed: the Mesh-mode
bug and the `GateEditor.qml` crash described above under "v0.2.1 polish
pass" — both are now covered by regression tests. One thing this pass
could *not* verify visually: the native `FileDialog` opens as a genuine
out-of-process window (via the desktop portal), confirmed by its
`visible` property toggling correctly across open/close with no growth
in this window's own scene graph — but that also means it falls outside
what `QQuickWindow.grabWindow()` can capture, so its actual on-screen
appearance was not screenshotted, only its wiring.

The Structure/Mesh viewport's diagram still renders zoomed to roughly
the left/top third of the domain instead of the full extent (axis limits
report correctly; only the rendered crop is wrong) — a known, pre-existing
cosmetic issue, unaffected by and out of scope for this pass.

## v0.3 — Process Workbench

A second, independent workflow built around the *existing*
`pytcad.process` backend: the user composes a **process flow** — an
ordered list of steps — runs it out-of-process, inspects the resulting
per-species doping profile at any intermediate step, and can hand the
final state off to a real 1D device solve. It is reached via a new
"Process" entry alongside Structure/Mesh/Doping/Results in the viewport
mode selector, and lives under its own "Process" node in the project
tree — **not** merged into or fed by the v0.2 2D Structure/Mesh
workbench, which stays completely unchanged. `pytcad.process` is
entirely 1D (every function takes/returns a plain NumPy array along one
depth axis), so there is no honest way to make a process flow produce a
v0.2 2D `StructureModel` without inventing 2D process physics — see
"Not supported, by design" below.

**Implemented:**
- Four process operations, each with a fixed parameter schema and a
  capability-disclosure block shown directly in its properties editor
  (`gui/qml/components/*Editor.qml`), so the GUI never implies a
  capability the backend doesn't have:
  - **Initialize Substrate** (`SubstrateEditor.qml`) — builds the
    initial 1D depth array and background doping via
    `pytcad.mesh.graded_mesh`. Its editor states plainly: *"There is no
    separate backend 'wafer' object — this substrate step's parameters
    define the initial 1D mesh and background doping that later steps
    in the flow build on directly."* Must be first among enabled steps
    in every flow.
  - **Implant** (`ImplantEditor.qml`) — `process.implant()`, a Gaussian
    profile from tabulated LSS moments. Disclosed capabilities: ✓ Dose
    ✓ Energy ✓ Species (B, P, As only) ✓ Tilt (first-order `cos(tilt)`
    range scaling). Explicitly not implemented: ✗ Channeling
    ✗ Transient-enhanced diffusion ✗ Monte-Carlo damage model. Energy
    must fall inside each species' tabulated range (10–200 keV) or
    validation rejects it before Run.
  - **Anneal** (`AnnealEditor.qml`) — `process.diffuse_numeric()`
    (explicit finite-difference diffusion, constant Arrhenius
    diffusivity). Has no species field of its own: it diffuses whichever
    dopant the **most recent enabled Implant step before it** in the
    flow introduced; an anneal with no preceding implant is a validation
    error, not a silent no-op or a fabricated default species.
  - **Oxidize** (`OxidizeEditor.qml`) — `process.oxide_thickness()` /
    `process.silicon_consumed()`, the Deal-Grove analytic model.
    Bookkeeping only — see its own subsection below.
- **Process Flow list/tree** (`ProcessPanel.qml`): add, reorder (up/down,
  undoable), duplicate (deep-copied parameters, independent of the
  original), enable/disable (a disabled step is skipped by the runner
  but keeps its ID, position, and parameters), and rename steps. Step
  IDs are UUIDs, stable across reorders — never derived from list
  position.
- **Process validation** (`ValidationPanel.qml`, generalized from v0.2's
  structure validator): a fixed per-operation validator (positive
  length/dose/time, in-range implant energy, valid species/ambient, a
  leading enabled Substrate step, an Implant step preceding every
  Anneal) blocks Run on any error and reports it scoped to the exact
  step, e.g. `Step 03 — Implant: Dose must be > 0`.
- **Undo/redo**, reusing v0.2's `UndoStack`/`Command` pattern verbatim
  for every process-flow edit (add/remove/reorder/duplicate/enable/
  rename/parameter change) — the undo stack only ever stores the small
  `ProcessFlow`/`ProcessStep` dataclasses, never `.npz` state.
- **Out-of-process execution**: reached via `ProcessPanel.qml`'s own
  "Run Process"/"Stop" buttons (mirroring the main toolbar's device-solve
  Run/Stop exactly, including sharing the same `controller.busy` flag),
  which drive `gui/services/process_runner.py`, a Qt-free CLI (`python -m
  gui.services.process_runner flow.json manifest.json`) run via a
  generalized `JobRunner` (now takes a `module` parameter so v0.1/v0.2's
  solver path and the new process path share one
  QProcess/cancellation/atomic-result implementation instead of two
  near-identical classes). Each run writes its checkpoints into its own
  per-run `<manifest-stem>-state/` subdirectory (derived from
  `JobRunner`'s already-unique-per-run manifest path), so two runs of the
  same flow — same step IDs — can never overwrite or mix each other's
  checkpoint files, and a canceled/failed run's entire subdirectory
  (including any `.tmp.npz` per-step file and the manifest's own
  `.tmp.json`) is removed outright rather than left behind, exactly like
  the v0.1 solve path's atomic-result guarantee.
- **Per-species doping state**: rather than one running `(x, C)` array
  (which would lose data the moment a second dopant species enters the
  flow — a second implant would either overwrite the first species'
  profile or silently co-diffuse both under the wrong diffusivity),
  state is kept as `species_profiles: {species: array}`, sparse (only
  implanted species are present), plus a scalar signed `background`.
  Two implants of the *same* species accumulate onto one profile; two
  implants of *different* species get independent entries. An Anneal
  step diffuses only its resolved species' array — every other species'
  profile passes through byte-for-byte unchanged, since
  `process.diffuse_numeric` has no cross-species/co-diffusion model.
  `net_doping` and `ntotal` are never stored independently — both are
  always produced by one shared reconstruction function
  (`process_model.reconstruct_doping`, `net = background +
  Σ DOPANT_TYPE[s]·C_s`, `ntotal = |background| + Σ C_s`, using only
  `pytcad.process.DOPANT_TYPE`), called from the runner, the Device1D
  handoff, and the Derived Quantities panel alike, so the three can
  never compute a different answer from the same state. This was a
  correction made during design review of the original single-array
  sketch, which would have silently lost data on a multi-implant flow.
- **Intermediate process states**: every *enabled* step writes its own
  checkpoint (`state-{step_id}.npz`, atomic temp-file-then-rename) into
  that run's own checkpoint subdirectory, read back via
  `ProcessResultStore`. A fresh "Run Process" click clears any previous
  run's `ProcessResultStore` immediately (not just once the new run
  finishes), so a result is never shown as "current" while a re-run is in
  flight or after that re-run fails/is canceled. The viewport's new "process" draw mode
  (`MplCanvasItem._draw_process`, a `semilogy(x, |net_doping|)` plot with
  each present species profile overlaid) renders whichever step is
  currently selected; clicking a different step in the Process Flow list
  re-selects the plotted state immediately, letting the user step through
  Initial → post-Implant → post-Anneal → ... states of the same flow. The
  Derived Quantities panel (junction depth, peak concentration and its
  depth, retained dose, sheet resistance, oxide thickness, silicon
  consumed) is scoped to whichever step is currently selected, and shows
  only backend-implemented, test-covered quantities — each row states its
  source function so the claim is checkable, not asserted.
- **Units**: internal storage stays in the backend's own units — depth in
  cm, dose in cm⁻², energy in keV, doping/`ntotal` in cm⁻³, anneal time in
  seconds (`diffuse_numeric`'s `t_s`), oxidize time in **hours**
  (`oxide_thickness`'s `t_hours` — a genuinely different unit for the
  same physical quantity than anneal time, so every time field's label
  states which). Temperature is **°C** everywhere (`diffuse_numeric`,
  `oxide_thickness`, and `deal_grove_coefficients` all take `T_C`
  directly — the GUI never silently converts to Kelvin). Display
  converts cm to nm/µm at the UI boundary only, following the exact
  convention `StructureModel`/`ViewportPanel` already use.
- **Save/load, schema v3**: `project.json`'s `schema_version` is now 3,
  adding a `"process": {"steps": [...]}` key alongside the unchanged
  `"structure"`/`"mesh"` keys. A v2 project (no `"process"` key) loads
  with an empty process flow and its structure/mesh data completely
  untouched — no information is discarded on migration. **v3 also
  supports process-only projects** (structure/mesh empty or absent,
  process flow populated) — this generalizes v0.2's assumption that a
  project always has a 2D structure, and was itself a correction made
  during design review of the original schema sketch. A v1 project still
  raises the same clear `UnsupportedProjectVersionError` it did before
  v0.3 (v1→v3 direct migration was never supported, even pre-v0.3, so
  nothing new is broken). Round-tripping a v3 project (save then reload)
  reproduces an identical `ProcessFlow`.
- **Process → Device(1D) handoff**: the final enabled step's checkpoint
  becomes a `DeviceSpec` through the *same* `device_spec.py` dataclasses
  and the *same* `JobRunner`/`solver_runner.py`/`NpzResultStore` path
  v0.1/v0.2 already use for 2D solves — literally the same code, first
  time exercised at `dimensionality == 1`. Both `net_doping` and
  `ntotal` from the checkpoint are carried across (never leaving
  `DopingSpec.ntotal` as `None`, which would otherwise make the solver
  silently fall back to `abs(net_doping)` — physically wrong the moment
  more than one species or a nonzero background is present). **The
  handoff exposes exactly two voltage fields ("Left V", "Right V") and a
  "Build Device from Process" button, all in `ProcessPanel.qml`** — not a
  general contact editor — because `Device1D` structurally has only two
  ends and `solver_runner.apply_bias` already requires exactly two
  contacts, read positionally. "Build Device from Process" is enabled
  once a process result exists; clicking it clears any loaded v0.2
  structure/mesh (Process handoff takes priority over a stale structure
  on the next Run, mirroring how loading a `StructureModel` already takes
  priority over a v0.1 spec) and emits the same `structureChanged` signal
  every other structure mutation does, so QML immediately reflects the
  switch rather than showing stale pre-clear data. This clear is a
  one-way precedence switch, not an undo-tracked edit — there is
  currently no way to get a cleared 2D structure back via Ctrl+Z.

**Planned (not yet implemented):**
- `ProcessFlow.to_json()`/`from_json()` directly on the dataclass
  (`gui/services/process_model.py`), mirroring `DeviceSpec`'s own
  pattern (`gui/services/device_spec.py`). Today `AppController` bridges
  the gap with a small internal `_ProcessFlowJob` adapter so `ProcessFlow`
  can be handed to `JobRunner`; adding the methods directly would let
  that adapter be deleted.
- A public `current_step_id` property on `ProcessResultStore`
  (`gui/services/process_result_store.py`). Today
  `gui/visualization/mpl_canvas_item.py` reaches into the store's
  private `_selected` attribute at its two call sites — a documented,
  brief-sanctioned workaround for v0.3 (see the plan's Task 10 review
  notes), not a defect, but a public accessor would be the more
  consistent long-term shape.
- Wiring `implant_pearson4_skewed()` (`pytcad/process.py`) into the
  Implant step as an alternate skewed-profile implant model, once it
  gains species/energy-shaped parameters — it currently takes
  Rp/dRp/gamma directly, unlike every other Implant field — and gets
  test coverage. See "Not supported, by design" below and the design
  spec's section 16, which already flags it as a candidate future step
  type rather than a permanent exclusion.
- A second real semiconductor material, once the backend has one — the
  same still-true item from v0.2's own "Planned" section above, and it
  applies equally here: `pytcad.materials` defines only `SILICON`, and
  nothing in the 1D process path (`pytcad.process`) is material-aware
  enough to use a second one yet.

**Not supported, by design:**
- **Deposition, etch** — no function exists anywhere in `pytcad.process`
  for either.
- **Any 2D or 3D process operation, and any process → 2D `StructureModel`
  handoff** — `pytcad.process` is entirely 1D; `Device2D`/`StructureModel`
  are solver-side/2D-only and nothing bridges the two without inventing
  new backend physics, which is out of scope.
- Channeling, transient-enhanced diffusion, oxidation-enhanced diffusion,
  advanced/Monte-Carlo implantation, level-set etching, multi-material
  process simulation, stress mechanics, crystal damage, quantum
  corrections — none exist in the backend, none are faked by the GUI.
- `implant_pearson4_skewed` — exists in `process.py` but takes
  Rp/dRp/gamma directly rather than species/energy and has no test
  coverage, so it is not wired into the Implant step's parameter shape.
- Cross-species interaction during Anneal (co-diffusion, segregation,
  pairing) — `diffuse_numeric` has no such model; every non-diffusing
  species' profile is left untouched, not approximated.
- A general contact editor for the process handoff — exactly two fixed
  ohmic ends, matching what `Device1D` structurally has.

**Oxidation is bookkeeping-only — stated plainly:** `oxide_thickness()`
and `silicon_consumed()` return **scalars** (oxide thickness in µm, Si
recession in µm). Running an Oxidize step **does not remap the x-axis
and does not alter the doping profile in any way** — `process.py`
implements no oxidation *geometry* model, only the scalar Deal-Grove
thickness. The step's own properties panel carries this exact,
non-dismissable note: *"Oxidation is bookkeeping-only in this backend:
it reports oxide thickness and Si consumed, but does not alter the
wafer's x-axis or doping profile."* If a later step should account for a
real recessed surface, the user must adjust that step's own parameters
by hand — nothing is automated. The reported thickness/consumption
numbers remain visible in the Derived Quantities panel for manual
bookkeeping only.

**Known limitations / real-display defects found and fixed (Task 15):**
Verified on a real Wayland display (`QQuickWindow.grabWindow()`
screenshots + pixel measurement), not just headlessly, following the same
methodology the v0.2.1 pass used — and it found the same class of "no
headless test could have caught this" defects:
- The Process viewport mode was completely unwired end to end (rendering
  was implemented and unit-tested, but no QML file ever called it) —
  running a flow and switching to "Process" view showed nothing.
- Canceling a running process flow left the app permanently stuck busy
  (`canceled` signal from the process `JobRunner` was never connected),
  silently blocking every subsequent Run for the rest of the session.
- The process semilogy plot had no y-axis floor, so floating-point
  underflow noise in a Gaussian implant's far tail (values as small as
  `~1e-312`) stretched the axis until the real, physically meaningful
  1e15–1e20 cm⁻³ range was squashed into an unreadable sliver.
- Sheet resistance rendered as the literal text "-1 Ω/□" for every step:
  a bare `numpy.float64` doesn't marshal to a JS number across a
  `Slot(result="QVariant")` boundary the way every other derived value
  (already wrapped in `float(...)`) does.
- The Process Flow list's reorder/duplicate/remove buttons were entirely
  clipped and invisible at the window's actual (SplitView-compressed)
  default width — not just at some drag-to-minimum edge case.
- Explanatory capability-disclosure text in the Implant/Substrate/Oxidize
  editors visibly overran its panel's real right edge, even though Qt's
  own wrap-metric check reported success (a `Layout.fillWidth`-reported
  width exceeding the panel's true clipped bounds — the same class of
  over-report this codebase's `RegionList.qml` already documents).

All six were found and fixed with regression tests; none touched
`pytcad/pytcad/`. See the v0.3 plan's Task 15 report (real-display
verification pass) for full detail, screenshots, and root causes.

**Final whole-branch review fix pass:** a review across all 16
implementation tasks together (rather than each task in isolation) found
one Critical defect and six Important ones, all now fixed with regression
tests, re-verified on a real Wayland display:
- **Critical — the Process Workbench was unreachable from the real app.**
  `runProcess()`/`cancelProcess()`/`buildDeviceFromProcess()` had zero
  callers anywhere outside `gui/tests/` — every prior test called them
  directly from Python, which is exactly the test shape that let this
  ship undetected. `ProcessPanel.qml` now has real "Run Process"/"Stop"
  buttons, "Left V"/"Right V" fields, and a "Build Device from Process"
  button (see "Out-of-process execution" and "Process → Device(1D)
  handoff" above), and the regression test drives the actual QML
  `Button.clicked` signal via `QMetaObject.invokeMethod`, not a direct
  Python call to the controller slot.
- A flow like `substrate → implant P → substrate → anneal` used to pass
  validation (only the *first* enabled step was checked to be
  `substrate`) and then crash with a raw `KeyError` inside
  `process_runner._anneal_species`, because the second substrate step
  resets `species_profiles` to `{}` and the anneal step still tried to
  resolve `"P"`. `validate_flow()` now rejects more than one enabled
  substrate step per flow.
- Two runs of the same flow (same step IDs, e.g. a re-run after tweaking
  a parameter) used to write checkpoints into the same shared work
  directory, so a second run could silently overwrite the first run's
  `state-{id}.npz` files in place; a failed/canceled run could then leave
  the `ProcessResultStore` from a *previous* successful run pointing at a
  now-mixed set of files. `process_runner.py` now isolates each run's
  checkpoints into their own `<manifest-stem>-state/` subdirectory, and
  `JobRunner` removes that whole subdirectory outright on cancel/failure;
  `AppController` additionally clears `_process_result` the moment a new
  run starts (not just once it settles), so a stale result is never
  reachable via `hasProcessResult`.
- `buildDeviceFromProcess()` cleared `self.structure`/`self.mesh_model`
  directly without emitting `structureChanged`, leaving QML bound to
  `structureForQml`/`meshModelForQml` showing stale pre-clear data. It
  now emits the signal (see the handoff bullet above for the full
  precedence-switch caveat).
- `sheet_resistance()` integrated conductivity over the *entire* depth
  array instead of masking to the doped-above-background region the way
  `examples/02_process_flow.py` (the script its own docstring claims to
  mirror) does — `mask = x <= xj[0]`. At realistic substrate lengths this
  could produce a value several times off from what the label/docstring/
  design spec all describe as "sheet resistance of the n-layer" (or
  p-layer). Fixed to apply the same junction-depth mask, falling back to
  the full array only when `junction_depth` finds no sign change (a
  uniformly-doped profile with no junction at all).
- The project tree's "Process" node showed a stale v0.1 placeholder
  ("Process editing arrives in a later version") predating this entire
  plan, and was additionally masked by an unconditional `self.spec is
  None` guard for the common process-only-session case. It now shows real
  step count / enabled-step count / validation status / result
  availability derived from `self.process_flow`, independent of whether a
  2D structure/device spec has ever been loaded.
- `tilt_deg` was unvalidated in `validate_flow()`'s implant checks —
  `process.implant()` scales `Rp` by `cos(tilt)`, so a tilt at or above
  90° silently yields a zero/negative implant range. `validate_flow()`
  now requires `0 <= tilt_deg < 90`.

See the SDD ledger's final-review-fix-report for the complete list with
covering tests and test output.

**Windows compatibility:** audited via **static analysis only** (Task 14)
against the clean pattern `job_runner.py` already established
(`tempfile.mkdtemp()`, `os.path.join`, `sys.executable`, `QProcess`, no
hardcoded `/tmp`, no bash-specific subprocess flags); `process_runner.py`
and `process_result_store.py` were written to that same standard from the
start. This has **not** been verified by actually running the GUI on
Windows — no Windows environment was available during this plan, and
that gap is reported honestly rather than implied to be covered.

## v0.4 — Swept Device Analysis

One coherent feature: a **single-contact voltage sweep** carried through
the full stack — QML → Controller → JobRunner (QProcess) → solver_runner
→ ResultStore → viewport — with no changes to the numerical backend.

### Using it

1. **Arm a sweep** in the *Voltage sweep* panel: pick the contact or gate,
   enter start / stop / step volts, press **Arm sweep**. The status label
   turns green ("sweep armed"); **Clear** disarms. Sweep settings are part
   of the saved project (schema v4). If Arm is rejected (bad numeric
   values), the fields snap back to whatever sweep is actually still
   armed and an amber note says so — the panel never leaves you looking
   at typed values that don't match what Run would actually execute.
2. **Run** as usual. Each ramp point reuses the warm-started solution of
   the previous point (the same pattern as pytcad's own `iv_sweep` /
   `id_vg_sweep`), and the console streams per-point progress. Stop kills
   the process exactly as for single-bias runs; atomic writes guarantee no
   partial result.
3. Switch the view mode to **Curves** to see I vs. V for any recorded
   channel (ohmic contacts at 2D/3D; total current density at 1D). The
   channel dropdown switches curves; log scale plots |I|.
4. Select the **Results** node in the project tree for derived readouts:
   converged point count and Imax/Imin (with explicit units) always; for
   **gate sweeps** also Ion/Ioff and a Vth estimate labeled "max-gm
   est.". Numeric sweep values are sanity-checked as soon as you arm a
   sweep; whether the named contact exists is checked when you Run.

### Semantics and guarantees

- **Non-converged points never become data.** A diverging Newton solve is
  detected via pytcad's own "did not converge" warnings (no numerical code
  was touched); the point stays in the curve's convergence mask but its
  value reads back as NaN — the plot shows an honest gap, and derived
  statistics exclude it. A bad point never aborts the rest of the sweep.
- **Stored fields are the last converged point's** solution, clearly kept
  apart from the series data (separate npz key namespaces: `field__*` vs
  `sweep__*`). All v0.1–v0.3 result keys and behavior are unchanged.
- **Units are explicit end to end**: A/cm² (1D current density), A/cm
  (2D per-depth terminal currents), A (3D real terminal currents).
- **Projects**: schema version 4 adds one optional `sweep` key. v2/v3
  files load unchanged (sweep = none). Structurally invalid sweeps fail at
  load with a specific error; contact-name validity is checked at Run time
  against the actual spec. Results are still never embedded in project
  files, and loading a project drops whatever results were on screen.
- **Arm-time and Run-time sweep failures are deliberately distinct
  errors**, not the same message twice. Numeric problems (nonzero step,
  finite values, a sane point count) are caught immediately on Arm.
  Contact-name validity can only be judged against the currently loaded
  device, so it's checked at Run — and if it fails there (e.g. the
  structure changed under an already-armed sweep, removing the contact
  it names), that is reported as the device no longer matching the
  sweep, never as "the arm attempt was rejected": no arm attempt
  happened, the sweep was valid when armed.
- **Derived readouts are curve statistics only** — extremes, ratio, and
  the max-transconductance linear-extrapolation threshold estimate that
  pytcad's own validation suite checks against the MOS-C analytic
  landmark (±0.1 V there; the GUI labels it an estimate because the GUI
  does not know each device's Vds). No new physics models were added.
- **The channel used for Ion/Ioff and Vth is chosen automatically**, not
  by contact-declaration order or by name. Sign convention (which
  terminal reads as "rising with the sweep") isn't derivable from a
  contact's name, so both signs are tried per channel and a result is
  kept only when it also lands near the actual swept range — a tangent
  extrapolated far outside the sweep is rejected even if the mechanics
  otherwise looked fine. This matters concretely on the bundled MOSFET
  example: its structure lists "source" before "drain", and a naive
  first-channel or largest-current choice would have reported nothing,
  or a fictional value, for that example's own gate sweep.

### Honest limits of v0.4

(Historical record — batch sweeps and the MOS C–V mode arrived later in
v0.5.x; see those sections.)

- One swept contact per run; every other terminal holds its configured
  bias. No multi-parameter or batch sweeps, no C–V mode.
- The Boltzmann-statistics degeneracy warning (>~1e19 cm⁻³) applies to
  swept results exactly as to single-bias ones; high-current sweep points
  can also leave the range where the validated tolerances were measured.
- The Vth estimate assumes the swept curve actually contains a
  transistor-like turn-on on AT LEAST ONE recorded channel, in either
  sign convention, with the extrapolated threshold landing near the
  actual swept range (it returns nothing if no channel qualifies), and
  carries a +Vds/2 bias unless the opposing terminal's bias happens to
  be 0. It is therefore only computed (and only shown) for gate sweeps.
- Sweeps store field snapshots for one setpoint (last converged), not
  the full space-time-of-the-ramp movie. Series + one snapshot keeps
  result files small.
- A session whose only device is a built-in example (the raw v0.1 spec)
  cannot be fully saved: project files store Structure/Process workbench
  state and the sweep settings, never a DeviceSpec. Saving such a
  session warns explicitly and writes only the sweep configuration;
  reopening that file restores an empty project (Run says "Nothing to
  run"), and the dangling sweep is dropped at load rather than silently
  re-arming against whatever device is loaded next.
- Windows runtime support remains unverified (see v0.3's note above);
  nothing in v0.4 changed the process-launch pattern.

## v0.5.0 — Solver Backend Boundary & Run Records

One preparatory task: promote the de-facto contract between the GUI and
the numerical solver into an explicit, versioned interface, with zero
behavior change to the numerical engine, the controller, or any
existing workflow.

### What changed

- **New `gui/services/solver_backend.py`** (Qt-free, pytcad-free):
  `SOLVER_RESULT_SCHEMA_VERSION`, the canonical result-key grammar
  documented as its own reference docstring (field/unit/vector/
  terminal/sweep key conventions, per dimensionality), and
  `validate_result()` — a *structural* validator (shapes agree with the
  mesh axes, every field has a declared unit, a sweep block is
  all-or-nothing) rather than an exhaustive key inventory, so
  hand-written minimal test fixtures elsewhere in the suite stay legal.
- `solver_runner.py` stamps every result with `result__schema =
  SOLVER_RESULT_SCHEMA_VERSION` (one additive key; older files written
  before this change have no stamp and are read as legacy version 1).
- `NpzResultStore` now validates on open and fails fast with a
  `ResultSchemaError` — a corrupt or malformed result file is reported
  the moment it's loaded, not as a cryptic `KeyError` deep inside a plot
  later.

### Why

This is preparation, not new capability: the solver is entirely
homegrown (numpy/scipy finite-difference + Newton) with zero coupling
to any external backend today. Formalizing the existing implicit
contract — rather than leaving it as an undocumented convention that
only `solver_runner.extract_result()` and `NpzResultStore` happen to
agree on — is the smallest safe step toward a future second backend,
without moving or rewriting anything in `pytcad/pytcad/` or the
controller.

### Found and fixed during review

Adversarial review of the validator itself (not just its own bundled
tests) found two real gaps between what it documents and what it
enforces:
- `solved_bias` was listed in the grammar docstring as always required
  but was never actually checked — a result file missing it passed
  validation silently. Now enforced.
- Terminal validation checked that a `__value` implies a matching
  `__unit`, but not the reverse — an orphan `terminal__X__unit` with no
  `__value` passed silently (harmless in practice, since no consumer
  ever reads an orphan unit key, but a real asymmetry in an otherwise
  symmetric check). Now enforced both directions.

A coverage gap was also closed: the grammar documents `dimensionality
in {1,2,3}` and a terminal-unit change at 3D (real amperes, not A/cm),
but the original test suite only exercised 1D and 2D through the real
CLI. A real 3D solve is now run and validated end to end as part of the
conformance tests.

### Task 2 — RunRecord + result schema v2

The second (and larger) half of v0.5.0 makes a *run* a first-class
artifact. Result schema 2 is purely additive over schema 1 — a v2 file
is a valid v1 file with more keys, so nothing that reads v1 breaks:

- **Geometry keys** (`geom__kind`, `mesh__shape`, `nodes__count`,
  `nodes__coords`): every result now also carries its mesh as flat node
  coordinates in the solver's own x-fastest node order, so a future
  backend is not boxed into rectilinear grids by the wire format.
- **Provenance** (`record__meta`, JSON): UTC timestamp, backend id,
  dimensionality, material, T, the exact model-flag config and
  NewtonOptions used, and sweep metadata when armed.
- **Convergence trace** (`converge__trace`, JSON): per-stage Newton
  history — `equilibrium`, `bias`, and one `sweep:<i>` stage per swept
  point — with iteration numbers and residual metrics.

The trace is captured with ZERO numerical changes: the runner tees its
own stdout (everything captured still streams to the console panel) and
parses the core's existing verbose Newton lines, split on the runner's
own `PYTCAD_STAGE` markers. A dedicated format-pin test fails loudly if
the core's line format ever drifts. `capture_trace=False` omits only
the trace. `NpzResultStore.run_record()` returns a `RunRecord`
(`None` for pre-v2 files); the Physics Lab planned for a later
milestone will render exactly this record.

Adversarial review of the first implementation found and fixed: geometry
consistency checks that could be bypassed by omitting `geom__kind`; a
misleading rejection for the reserved-but-unimplemented `point_cloud`
kind; and a stdout leak in the runner if a solve raised mid-capture.

### Honest limits of v0.5.0

- Preparation only: no second solver backend exists yet, and none is
  wired up. DEVSIM (or any other backend) integration is explicitly out
  of scope for this task.
- Validation is structural, not physical: it checks that a result
  file's shape is internally consistent, never that its numbers are
  correct. Physical correctness stays the numerical suite's job
  (`pytcad/tests/`), untouched by this work.
- `NpzResultStore`'s validate-on-open covers device-solve results only.
  Process-flow checkpoints (`ProcessResultStore`) and the pre-solve
  preview store (`SpecResultStore`) read npz files through entirely
  separate code paths and are not covered by this schema.
- Schema 2's `point_cloud` geometry kind is reserved but NOT readable:
  files declaring it are rejected with an explicit message until a
  backend actually produces one.
- The convergence trace is diagnostic, not load-bearing: it is parsed
  from human-readable solver output (pinned by a test), so a residual
  number in a trace is exactly what the core printed — no more. Only
  sweep stages carry an authoritative converged flag; equilibrium/bias
  steps assume convergence unless the run failed outright.

## v0.5.x — Second Backend (DEVSIM), Viewport Observables, Deck Growth

### The DEVSIM backend (M7)

`workbench/solvers/devsim_backend.py` is a real second engine behind the
M3 SolverBackend protocol. It builds its own DEVSIM mesh from the same
DeviceSpec job the homegrown runner consumes (1D devices, two ohmic
contacts), solves drift–diffusion with DEVSIM's canonical silicon physics
(Scharfetter–Gummel currents, Boltzmann statistics, SRH), and writes the
same schema-v2 result files.

- **Bias ramps**: `spec.bias` is reached by fixed 50 mV voltage steps,
  each solve warm-started from the previous point. `spec.sweep` emits
  the full documented sweep block; per-point convergence is DEVSIM's own
  `solve(info=True)` verdict ANDed with a finite/positive-carrier check.
- **Diverged points are flagged, never stored**: field snapshots come
  only from converged points, falling back to the equilibrium state.
- **Provenance parity**: every Newton stage lands in `converge__trace`
  in the same JSON shape the homegrown runner writes, so the Physics
  Lab's convergence view works identically for both backends.
- **Cross-backend validation gate**: the same 1D diode swept by both
  engines produces I–V curves agreeing to a constant factor ≈2 (set by
  the engines' tabulated intrinsic-carrier difference), both exponential,
  and both matching the analytic built-in potential within 5%.
- DEVSIM stays an **optional dependency**: without it, the registry
  silently offers only the pytcad backend; with it, jobs can select
  `"devsim"` explicitly.

### Viewport observables & model comparison (M9)

- New viewport modes **Bands** (E_c/E_v/E_Fn/E_Fp via
  `workbench.analysis.band_diagram`, pinned to the core's own band
  routine) and **Recombination** (`recombination_rate()` using the core's
  SRH/Auger/BGN conventions; lifetimes from |net doping| because stored
  results carry no Ntotal — stated in the code).
- **Model on/off comparison**: after any swept Run, "Compare models"
  re-solves the identical device with every catalog model disabled into
  a separate store; Curves mode overlays it dashed ("all models off").

### Deck growth (M10)

Decks gain `bias <contact> = <V>` and
`sweep <contact> start=S stop=P step=D` statements (contact names are
validated against the built device, errors stay line-numbered), and
Main.qml gains an **Open Deck...** file dialog. A deck becomes the same
editable Structure-workbench session the Device Builder produces — never
a second simulation path.

### First new physics (M8)

`workbench/physics/impact_ionization.py`: van Overstraeten–de Man impact
ionization coefficients plus the avalanche-breakdown integral for
one-sided abrupt junctions, gated by published values (coefficient table;
breakdown inside textbook ranges at 1e15/1e16/1e17 cm⁻³). Analysis-layer
only for now — catalog registration comes together with solver coupling.

### Sweeps growth: family (batch) and MOS C–V

The Sweeps panel grows three tiers. The original single-contact voltage
sweep stays as-is. Below it, **FAMILY (batch)** re-solves the exact last
solved device once per stepped terminal voltage while sweeping another
contact (`configureFamily(stepped, start, stop, step)` +
`runFamily(swept, start, stop, step)`): every curve re-runs the full
job→subprocess pipeline, diverged points are flagged, and all curves
overlay in Curves mode with a per-stepped-value legend. At the bottom,
the **MOS C–V** section runs the validated `MOSCapacitor` core
(poly-gate depletion, flat-band modes) through the standard job →
subprocess → schema-v2 result-store pipeline; the curve is gated
against the analytic C_ox/C_min landmarks in `gui/tests/test_cv_mode.py`
and surfaces through `cvSweep.cvStore()`.

### Physics Lab, projects, and the user guide

The **Physics Lab** tab exposes the ModelCatalog interactively: every
physics model is a checkbox with its exact equation and literature
reference shown on selection, "Plot convergence" jumps to the stored
residual trace, and the model toggles feed the next Run (and the
all-models-off comparison). Project files (v5 schema — see "Project
schema v5" below) carry structure, mesh, sweep config, process state,
and the Physics Lab's model config through save/load with a
dirty-marker guard. A 20-page illustrated guide with real GUI
screenshots — captured headlessly from this very app — lives in
`../docs/user-guide/`.

### Heterostructures and tunneling reach the wire format (M11/M12)

`DeviceSpec` gains `region_materials`: the material library resolves
case-insensitive names (Si, Ge, GaAs, InGaAs, AlGaAs factory) per
region, validation rejects unknown or mixed-unsupported combinations
loudly, and the homegrown 1D backend passes the per-node material list
into `Device1D`'s heterojunction core (flux-form Poisson with ε(x),
Anderson band offsets via ln(nie) edge factors). The analysis layer
gains `workbench/physics/tunneling.py` (Fowler–Nordheim constants/slope,
WKB κ/transmission — published-value gated), and the solver-side
Hurkx trap-assisted tunneling (`Models(tat=True, trap_et_rel=...)`) is
covered by its own acceptance tests (FD-Jacobian < 5e-5 with traps on;
traps-off bit-identity; WKB factor-law gate over 1e7–5e10 V/m).

### Project schema v5 and the GUI end-to-end smoke test (2026-08-28)

`gui/tests/test_smoke_e2e.py` drives the real rendered QML tree only
(`create_engine()` + `findChild(objectName)` + real property get/set +
`QMetaObject.invokeMethod()` for signals) across the two device-
construction paths the interactive GUI actually has: the Process Flow
(substrate/implant/anneal/oxidize, always 1D) and the Structure/Device-
Builder templates (region boxes, always 2D). It exercises every
physics-model toggle, contact/gate/mesh editors, IV and CV sweeps,
invalid-input handling, and save/reload — cross-checked against the
same analytic built-in-potential and C–V-landmark formulas
`tests/test_validation.py` and `test_cv_mode.py` already use. It also
confirmed there is no GUI path to a `Device3D` or the DEVSIM backend
(both recorded as N/A, not worked around). Several `ContactEditor`/
`GateEditor`/`MeshEditor`/`DopingEditor`/`SubstrateEditor`/
`ImplantEditor` QML controls had no `objectName` at all before this —
added so they can be driven as real QML rather than guessed at.

Two real defects surfaced and were fixed:
- Numeric QML fields (contact/gate voltage, gate tox, region doping,
  every process-step parameter) let `parseFloat("")`/`parseFloat("abc")`
  (NaN) through to the solver silently, unlike the sweep panel and the
  implant-window fields, which already validated. Fixed with a shared
  finite-number guard in `app_controller.py`.
- Saving a project never persisted the Physics Lab's model config;
  reloading always reset every model to `ModelCatalog.default_config()`.
  Fixed via a v5 project-schema bump: one new optional key, `"models"`
  (a dict or `null`). v2–v4 files simply lack the key, which loads as
  `model_config=None` — the documented signal to leave the Physics Lab
  untouched, so old projects still load byte-identically.
  `PhysicsLabController.setModelConfig()` merges the restored dict onto
  the catalog defaults rather than replacing wholesale, so a partial or
  malformed saved config degrades to documented defaults for the
  missing/bad keys instead of raising. See `gui/tests/test_persistence_v5.py`
  for the persistence-layer round-trip and backward-compatibility tests.

A `ListView`/`Repeater`-specific limitation of Qt's offscreen test
platform was also confirmed along the way: delegate items (the Physics
Lab's checkboxes, the Device Builder's per-parameter fields) never get
incubated without a real running event loop, so those two spots in the
smoke test call the exact controller method the delegate's own signal
handler invokes — the same substitute pattern `test_device_templates.py`
had already adopted (visible there as a disabled `if False` probe) for
the identical wall.

### Honest limits of v0.5.x

- The DEVSIM backend solves **1D two-terminal silicon devices only**
  (equilibrium, static bias, or one swept contact); no gates, no 2D/3D,
  no transient or AC analysis.
- Cross-backend I–V agreement is a *factor* comparison, not pointwise:
  the engines ship different tabulated ni, which shifts forward current
  by roughly its ratio squared. Both engines are separately anchored to
  analytic results instead.
- Band/recombination modes read stored fields of the current result;
  2D+ results get an honest placeholder rather than a fake cut.
- Impact ionization is selectable in the Physics Lab and fully coupled
  into the homegrown 1D solver's Newton assembly (M15, all gates green
  — see ARCHITECTURE.md section 5); the DEVSIM backend does not support
  it.
- Neither device dimensionality nor solver backend has a GUI selector:
  the Process Flow always builds 1D, Structure/Device-Builder templates
  always build 2D, there is no GUI path to a `Device3D`, and DEVSIM can
  only be selected from a job's JSON, not from any panel.
- The DEVSIM backend does not yet accept `region_materials`:
  heterostructure jobs must use the homegrown 1D backend.
- The MOS C–V result surfaces through `cvSweep.cvStore()` (and the
  validated test gates); there is no dedicated C–V plot mode yet.
- Family sweeps re-solve the *last solved* device; editing the
  structure after a solve invalidates the batch until the next Run.
