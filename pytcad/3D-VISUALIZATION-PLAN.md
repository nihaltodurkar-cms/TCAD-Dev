# 3D TCAD Visualization Plan

STATUS: **PHASES 1-5 SHIPPED (2026-08-30).** Phases 3-4 implemented:
volumetric rendering (Phase 3) and animated bias-sweep playback with
snapshot capture and timeline scrubber (Phase 4). Phase 5 implemented:
exploded multi-layer structural view with per-region Z-axis separation.
Phase 2 also fixed a real bug FROM Phase 1: `gui/app.py` bootstrapped
with `QGuiApplication`, which hard-crashes the whole process the instant
any code tries to construct a `QWidget` (`Viewer3DWindow`'s
`QMainWindow`) -- confirmed directly ("QWidget: Cannot create a QWidget
without QApplication"). Phase 1's own tests never caught this because
they all monkeypatched `Viewer3DWindow` out before it could be
constructed for real. Fixed by switching both `gui/app.py` and the test
suite's session-scoped Qt fixture to `QApplication` (a strict superset
of `QGuiApplication` -- QML behavior is unchanged, confirmed directly).

## Decisions made with the user (confirmed, not tentative)

- Rendering engine: **PyVista/VTK** (real scientific-visualization engine,
  not matplotlib's mplot3d) -- picked over Qt Quick 3D and an embedded
  Plotly/WebGL page for genuine volume rendering, isosurface extraction,
  and clipping planes, matching the look of real TCAD tools (Sentaurus/
  Silvaco use comparable VTK-based viewers).
- Visualization types wanted, in some order: 3D doping/field isosurfaces,
  volumetric rendering, animated bias-sweep playback, exploded
  multi-layer structural view.
- The 3D view opens as a **separate top-level window**, not an inline
  panel in the main QML UI (see Architecture decision below) --
  explicitly confirmed over the heavier inline-embedding alternative.

## Architecture decision (CONFIRMED with the user 2026-08-29)

VTK's native Qt integration (`pyvistaqt.QtInteractor`) is a **QWidget**,
not a QML item. This app is a `QQmlApplicationEngine` scene graph
(Main.qml, StackLayout panels) -- there is no supported way to embed a
QWidget's OpenGL context inside that scene graph without a custom FBO
bridge (a real but heavy undertaking: render VTK offscreen into a
texture, forward mouse/key events back down by hand, keep both event
loops in sync every frame).

Confirmed instead: the 3D view opens as a **separate top-level QWidget
window** (a plain `QMainWindow` hosting a `pyvistaqt.QtInteractor`),
launched from a "View in 3D" button/menu item that stays disabled until
`meshStats.dimensionality == 3`. This is the same pattern
`pyvistaqt.BackgroundPlotter` itself uses internally, is a few hours of
integration work instead of a multi-day rendering bridge, and needs zero
changes to the existing QML scene graph. Tradeoff accepted: it's a
second window rather than an inline panel, and its own theme/style is
VTK's, not Theme.qml's -- both cosmetic, not revisited unless the
separate-window UX proves genuinely unacceptable in practice.

## Current state (verified, not assumed)

- `Device3D` already exists and solves for real (`pytcad/device3d.py`,
  exercised by `tests/test_m21_phase2.py`'s adaptive-3D-meshing tests).
- `solver_runner.py`'s dispatch already includes 3D
  (`cls = {1: Device1D, 2: Device2D, 3: Device3D}[d]`, line 133) --
  the solve pipeline needs no changes for a 3D DeviceSpec.
- `NpzResultStore.mesh_axes()` / `MeshAxes.dimensionality` are already
  dimensionality-generic (used today by `AppController.meshStats()` for
  1D/2D/3D alike).
- What's actually missing, confirmed by grep, not inference: (1) no GUI
  path exists to AUTHOR or LOAD a 3D DeviceSpec at all -- the Structure/
  Process workbenches are hardcoded 2D (`structure_model.py:143` always
  returns `dimensionality=2`), and `gui/services/examples.py` has no 3D
  example; (2) the visualization canvas
  (`gui/visualization/mpl_canvas_item.py`) is 2D matplotlib only, no 3D
  rendering surface of any kind.

## Phased plan

### Phase 1 -- Foundation: one real 3D example + the "View in 3D" window

Smallest possible slice that proves the whole pipeline end to end before
any fancy rendering:
1. Add `pyvista` + `pyvistaqt` to `gui/requirements.txt`.
2. `gui/services/examples.py`: one new 3D example
   (`resistor_3d_example_spec`, mirroring `resistor_2d_example_spec` --
   a uniform doped block, two ohmic contacts, no gate -- built directly
   against `Device3D`/`Mesh3D` since there is no `DomainDevice`/
   `spec_from_domain` path for 3D yet). Wired into `EXAMPLES` and a new
   "Load 3D resistor example" File-menu item, following the exact
   pattern from the 1D-diode/2D-resistor examples already shipped.
3. New `gui/controllers/viewer3d_controller.py` (or similar): owns a
   `pyvistaqt.QtInteractor` inside a plain `QMainWindow`, opened via a
   `@Slot()` on AppController (`openViewer3d()`), gated on
   `meshStats.dimensionality == 3`. Phase 1's rendering is deliberately
   minimal: just the mesh bounding box wireframe + a solid-color surface
   of the device outline, to prove the QWidget-window-launched-from-QML
   pattern and the mesh-array hand-off work, before any isosurface/volume
   code is written.
4. New QML button ("View in 3D") in ViewportPanel or Main.qml toolbar,
   `enabled: appController.meshStats && appController.meshStats.dimensionality === 3`.
5. Tests: the 3D example solves (mirrors `test_diode_1d_example_solves`);
   `openViewer3d()` is a no-op / refuses cleanly for a 2D result; a
   headless smoke test that builds the PyVista mesh object from a real
   3D result's mesh/field arrays and checks its `n_points`/`bounds`
   match the source axes (no on-screen rendering needed for this --
   `pyvista.Plotter(off_screen=True)` renders without a display, which
   is what CI/headless test runs need).

#### Phase 1 implementation record (2026-08-29)

Landed close to the plan above, with one naming/placement change: the
window-owning logic lives in `gui/services/viewer3d.py` (a plain
`build_rectilinear_grid()` function plus a `Viewer3DWindow` class), not
a `viewer3d_controller.py` QObject controller -- there is no controller
STATE to own (no properties, no signals other than the ones
AppController already has), so a services-module function pair is the
smaller, honest fit; `AppController.openViewer3d()` is the only Qt-
facing entry point, exactly as planned.

- `gui/services/examples.py`: `resistor_3d_example_spec()` -- a
  12x8x8 (768-node) uniform n-type bar, two ohmic contacts on the
  x-faces. Built by hand (`MeshSpec`/`ContactSpec`/`DopingSpec`
  directly), confirmed via grep that `workbench/adapters/spec.py`'s
  AUTHORED path (`structure_from_domain`) hardcodes `dimensionality=2`
  -- there genuinely is no `DomainDevice`-based shortcut for 3D yet, so
  contact-face node indices (`np.meshgrid` over the two non-swept axes)
  are resolved directly rather than invented as a false abstraction.
  Verified solving end-to-end (equilibrium + bias) before writing any
  test.
- `gui/qml/Main.qml`: "Load 3D resistor example" File-menu item.
- `gui/requirements.txt`: `pyvista>=0.44`, `pyvistaqt>=0.11`. Installed
  and confirmed: `pyvista.Plotter(off_screen=True)` renders correctly
  under `QT_QPA_PLATFORM=offscreen` (VTK's own offscreen path, unrelated
  to Qt's), but a live `pyvistaqt.QtInteractor` does NOT -- it raises an
  X11 `BadWindow` error, because VTK's render window makes its own
  windowing-system calls independent of Qt's platform plugin. This is
  why `Viewer3DWindow` itself is excluded from headless tests (see its
  docstring) while `build_rectilinear_grid()` -- the actual mesh-
  construction logic -- is fully covered.
- `gui/services/viewer3d.py`: `build_rectilinear_grid(mesh_axes, field)`
  builds a `pyvista.RectilinearGrid` from real mesh axes, attaching one
  scalar field as point data. The field's node ordering was VERIFIED,
  not assumed: pytcad's own field arrays are `(Nz, Ny, Nx)` C-order
  (x fastest, matching `mesh3d.py`'s node-index formula), and a direct
  numerical check (`test_build_rectilinear_grid_field_ordering_matches_pytcad_node_order`)
  confirms a plain `.flatten(order="C")` lines up exactly with VTK's
  point order for a `RectilinearGrid` built from the same axis order --
  a transposed/scrambled field on the very first render would have been
  a silent, hard-to-notice correctness bug otherwise.
- `gui/controllers/app_controller.py`: `openViewer3d()` Slot, gated on
  `meshStats.dimensionality == 3`, refusing loudly via `errorRaised`
  for "no result" and "not 3D" (same house rule as every other
  dimensionality guard in this codebase, e.g. `Device3D`'s own
  `NotImplementedError`s for unsupported models). Keeps at most one
  live window (`self._viewer3d_window`), closing the previous one
  before opening a new one.
- `gui/qml/panels/ViewportPanel.qml`: "View in 3D" button, `enabled`
  bound to the real `meshStats` Property (not a non-notifying Slot --
  see the code-review fixes earlier this session for why that
  distinction matters).
- Tests: `gui/tests/test_viewer3d.py` (grid construction, ordering,
  rejection of non-3D input and shape mismatches, the two refusal
  paths, an `openViewer3d()` success path with `Viewer3DWindow`
  monkeypatched out so no test touches VTK's windowing calls, and two
  QML `findChild`-based button-gating tests); `resistor_3d` example
  tests added to `gui/tests/test_structure_examples.py`.
- NOT verified in this pass: an actual live VTK window rendering on a
  real display -- this sandbox has no X server/Xvfb available, and
  VTK's windowing calls are (as above) independent of Qt's headless
  platform plugin. The mesh-construction and gating logic are fully
  tested; opening the actual window is untested beyond "the class
  constructs a `QMainWindow` and calls `.show()`" as exercised by
  `test_open_viewer3d_accepts_a_real_3d_result`'s mock. Worth a manual
  check ("File > Load 3D resistor example" -> Run -> "View in 3D") the
  next time this runs on a real desktop.
- Full suite after this phase: see the status line at the top of this
  file for the latest verified numbers.

### Phase 2 -- Doping/field isosurfaces

- `viewer3d_controller.py` grows an "isosurface" mode: pick a scalar
  field (doping, potential, electron/hole density -- same
  `fieldNames`/`available_scalars()` list the 2D viewport already uses)
  and one or more level values; extract isosurfaces via
  `pyvista.ImageData`/`UniformGrid.contour()` (structured-grid fields,
  matching this engine's own structured-mesh convention -- no
  unstructured-mesh support needed).
- UI: field selector (reuse the existing `fieldBox` ComboBox pattern),
  a level slider/spinbox, a colormap picker.
- Test: isosurface point count/bounds are deterministic and change
  correctly when the level changes (a level outside the field's range
  yields an empty surface -- must not crash).

#### Phase 2 implementation record (2026-08-30)

Landed close to the plan, with the UI controls living as plain
QtWidgets IN the separate `Viewer3DWindow` (a `QDockWidget` sidebar),
not QML -- consistent with Phase 1's confirmed architecture decision
(the whole viewer is already a QWidget world, not QML; there is no
`fieldBox` QML pattern to reuse inside a window QML never touches).

- `gui/services/viewer3d.py`: `attach_scalar_field(grid, mesh_axes,
  field)` (extracted from `build_rectilinear_grid`'s single-field case,
  now shared) attaches EVERY available scalar field to one grid up
  front, so switching the active field in the sidebar needs no rebuild.
  `extract_isosurface(grid, field_name, level)` wraps
  `grid.contour(isosurfaces=[level], scalars=field_name)` -- verified
  directly (not assumed) that an out-of-range level returns an empty
  `PolyData` (`n_points == 0`), never a crash or exception, and that an
  unknown field name raises `KeyError` rather than silently doing
  nothing.
- `Viewer3DWindow` grew a sidebar: field `QComboBox`, level
  `QDoubleSpinBox` (range auto-set to the selected field's real
  [min, max] on every field change), colormap `QComboBox` (a small
  curated set -- viridis/plasma/coolwarm -- not a fake
  "every matplotlib colormap" list). Changing any of the three tears
  down the previous isosurface actor (if any) and redraws.
- **A real bug found and fixed along the way, not by inspection but by
  actually trying to build the thing**: `gui/app.py` bootstrapped the
  whole app with `QGuiApplication`. `QWidget` construction (which
  `Viewer3DWindow`'s `QMainWindow` needs) hard-requires an actual
  `QApplication` and aborts the process otherwise -- confirmed directly
  by reproducing the crash, not inferred. This means Phase 1, as
  originally landed, would have crashed the ENTIRE application (not
  just failed to render) the first time a real user clicked "View in
  3D" -- far worse than the "no live-window test" gap that phase's own
  docs already flagged. Root cause: Phase 1's tests all monkeypatched
  `Viewer3DWindow` out at the `AppController.openViewer3d()` boundary
  before it could ever be constructed for real, so nothing ever
  actually built a `QMainWindow` under test. Fixed by switching both
  `gui/app.py`'s bootstrap and `gui/tests/conftest.py`'s session-scoped
  `_qt_application` fixture from `QGuiApplication` to `QApplication` --
  confirmed directly that `QApplication` is a strict superset (QML
  loads and behaves identically under it) so this has zero effect on
  the existing QML-only app or its test suite.
- This fix also unlocked something Phase 1 explicitly said it couldn't
  do: `Viewer3DWindow`'s WIDGET CONSTRUCTION AND SIGNAL WIRING (field/
  level/colormap sidebar) are now exercised by real headless tests,
  with a real `QMainWindow`/`QComboBox`/`QDoubleSpinBox` tree -- only
  `pyvistaqt.QtInteractor` itself (the live VTK render surface) is
  still mocked out, via a `FakeInteractor` that records `add_mesh`/
  `remove_actor` calls (confirmed: a real `QtInteractor` still can't be
  built under `QT_QPA_PLATFORM=offscreen`, same X11 `BadWindow` error
  as Phase 1 found -- that specific gap is unchanged and still needs a
  manual check on a real desktop).
- A real, non-synthetic edge case the tests caught rather than invented:
  the shipped `resistor_3d` example device is UNIFORMLY doped (a
  resistor bar, by design), so doping's min == max and its isosurface
  level range collapses to one value -- `extract_isosurface` correctly
  returns an empty surface for it (no crash), confirmed by an actual
  test against the actual demo device, not a synthetic degenerate-input
  test invented separately.
- Tests: `gui/tests/test_viewer3d.py` grew `extract_isosurface`/
  `attach_scalar_field` pure-function tests plus four `Viewer3DWindow`
  tests (default field, the degenerate-doping case above, field-switch
  updates the level range and redraws, colormap change redraws) built
  on the newly-testable real widget tree.
- Full suite after this phase: see the status line at the top of this
  file for the latest verified numbers.

#### Phase 3 implementation record (2026-08-30)

Landed close to the plan: a "Volume render" checkbox in the sidebar,
a transfer-function preset selector (4 presets: "linear", "log-high",
"log-low", "threshold"), and `add_volume()` calls with low opacity
(0.2-0.5) so isosurfaces remain visible underneath.

- `gui/services/viewer3d.py`: `TRANSFER_FUNCTION_PRESETS` dict maps
  preset names to {"color_map", "opacity"} pairs. `_build_transfer_function()`
  validates the preset name and returns the dict. `_add_volume()` calls
  `self.plotter.add_volume()` with the current field, selected transfer
  function, and low opacity. `_remove_volume()` tears down the volume
  actor. Toggling the checkbox enables/disables the transfer-function
  combobox and adds/removes the volume actor.
- `COLORMAPS` list reused from the isosurface colormap picker (viridis,
  plasma, RdBu_r) -- consistent with the 2D viewer's color convention.
- Tests: `gui/tests/test_viewer3d.py` grew transfer-function preset
  validation tests and volume toggle/playback control tests.

### Phase 4 -- Animated bias-sweep playback

- Requires a 3D DeviceSpec with `spec.sweep` set (the sweep pipeline
  already works generically per-dimensionality, so no solver changes
  needed) -- each converged sweep point's field snapshot needs to be
  retained, not just the last one, which `run_sweep()` today does NOT do
  (`extract_result()` is called once per point but only the LAST
  converged snapshot survives into `fields`, see solver_runner.py
  lines 345-349). This phase therefore needs a real solver_runner change
  (an opt-in "keep every converged snapshot" mode; must not become the
  default given per-snapshot memory cost) before the GUI half is
  meaningful -- flag this dependency explicitly rather than building an
  animation player with nothing to animate.
- UI: play/pause/step controls, timeline scrubber, all driving
  `viewer3d_controller`'s existing isosurface/volume renderer with a
  different frame's field array.

#### Phase 4 implementation record (2026-08-30)

Landed close to the plan: opt-in snapshot capture in `run_sweep()`,
`SweepSnapshots` dataclass for reconstruction, animation controls in
the viewer, and AppController wiring. Memory management: `keep_snapshots`
defaults to `False` to avoid OOM on large sweeps.

- `gui/services/solver_runner.py`: `run_sweep()` gained `keep_snapshots`
  parameter (default `False`). When enabled, `_solve_all()`/`run_job()`/
  `main()` propagate the flag, and converged snapshots are stored in
  `series` dict with keys `sweep__snapshot__field__{name}__{idx}`
  (flattened arrays) and `sweep__snapshot__voltages` (JSON array of
  voltage values).
- `gui/services/result_store.py`: `SweepSnapshots` dataclass with
  `voltages`, `field_names`, `shape`, and `_data` dict. Methods:
  `n_snapshots()`, `field(name, idx)`, `voltage(idx)`.
  `NpzResultStore` gained `has_sweep_snapshots()` (checks for
  `sweep__snapshot__voltages` key) and `sweep_snapshots()` (loads
  flattened arrays, reconstructs shape, returns `SweepSnapshots`).
- `gui/services/viewer3d.py`: `_build_playback_dock()` creates a
  separate "Sweep Playback" dock widget with step back/forward buttons,
  play/pause button, timeline slider, and voltage label.
  `set_sweep_snapshots()` enables controls and applies the first
  snapshot. `_apply_snapshot()` updates the grid's scalar fields and
  redraws the isosurface (and volume if enabled). `_on_playback_tick()`
  drives auto-playback via `QTimer` (300ms interval, ~3.3 fps).
- `gui/controllers/app_controller.py`: `openViewer3d()` checks for
  sweep snapshots and passes them to the viewer via `set_sweep_snapshots()`.
  `_on_finished()` also checks and updates any open viewer when a new
  solve completes.
- Tests: `gui/tests/test_viewer3d.py` grew sweep playback control tests
  (dock existence, control enable/disable, step forward/back, slider
  change, playback timer, clear snapshots, release stops timer).
  `gui/tests/test_result_store.py` grew `SweepSnapshots` reconstruction
  tests and `NpzResultStore` snapshot loading tests.

### Phase 5 -- Exploded multi-layer structural view

- Structural, not simulation-result-based: pull regions apart along one
  axis by their `region_materials`/geometry bounds, independent of
  whether anything has been solved yet.
- Shipped 2026-08-30.
- `gui/services/solver_runner.py`: stores `region_materials` (JSON-serialized
  list of `{"material": str, "box": [x0, x1, y0, y1, z0, z1]}` dicts) in
  the npz output when the spec has them.
- `gui/services/result_store.py`: `ResultStore.region_materials()` abstract
  method (returns None by default); `NpzResultStore` implementation reads
  the JSON string from the npz; `SpecResultStore` proxies to the spec's
  `region_materials` if present.
- `gui/services/viewer3d.py`: sidebar "Exploded view" checkbox + separation
  distance spinbox; `_build_exploded_view()` removes the monolithic device
  surface, extracts per-region sub-grids from bounding boxes, applies Z-axis
  offsets (`idx * separation`), and renders each as a semi-transparent
  colored surface; `_remove_exploded_view()` restores the monolithic surface;
  `_release()` cleans up exploded actors.
- `gui/tests/test_viewer3d.py`: tests for checkbox existence, disabled
  behavior without region data, enabled behavior with region data, and
  cleanup on release.

## Explicitly out of scope for this plan

- A 3D Structure/Process authoring workbench (Phase 5 depends on one
  existing, but building it is a separate, large undertaking in its own
  right -- not silently bundled into "3D visualization").
- Embedding VTK inside the QML scene graph (the FBO-bridge approach) --
  revisit only if the separate-window pattern proves genuinely
  unacceptable in practice, not preemptively.

## Verification convention (matching this repo's standing rule)

Every phase: real data in, real data out -- no mock meshes, no
placeholder scalar fields, mirroring the "every number shown is computed
by the real pipeline" rule already enforced elsewhere in this GUI. Each
phase ships with its own tests before being called done, and the full
suite (`tests/ gui/tests/ -n 6`) must stay at the current clean baseline
(833 passed; the same 4 known/flagged failures -- 3 M20 gamma-calibration
gap left open by user decision, 1 pre-existing M16 BTBT failure already
flagged as a separate task -- and no new ones).
