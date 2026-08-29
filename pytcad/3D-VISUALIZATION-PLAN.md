# 3D TCAD Visualization Plan

STATUS: PLANNED, NOT STARTED -- approved by the user 2026-08-29, deferred
to a later session ("will do it later"). Start only on an explicit
"Start on Phase N" instruction, matching how every GUI-IMPROVEMENT-PLAN
phase in this repo has been kicked off.

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

### Phase 3 -- Volumetric rendering

- Add a "volume" render mode using PyVista's `add_volume()` with an
  opacity/color transfer function over the same scalar field list.
- UI: a transfer-function editor is real scope creep for a first pass --
  ship with a small set of preset transfer functions (e.g. "linear",
  "log-emphasize-high", "log-emphasize-low") rather than a full curve
  editor, and revisit a custom editor only if the presets prove
  insufficient.

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

### Phase 5 -- Exploded multi-layer structural view

- Structural, not simulation-result-based: pull regions apart along one
  axis by their `region_materials`/geometry bounds, independent of
  whether anything has been solved yet.
- Needs a 3D-capable region/geometry authoring path first (there isn't
  one today -- Phase 1's 3D example is hand-built in Python, not
  authored via any Structure-workbench equivalent) -- likely the
  largest and least-defined phase; scope it concretely only once
  Phases 1-4 are shipped and the 3D authoring gap has either been
  closed for other reasons or is tackled here directly.

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
