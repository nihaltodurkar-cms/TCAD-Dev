# PyTCAD Desktop GUI (v0.1 + v0.2)

A PySide6 / Qt Quick desktop frontend for the PyTCAD solver.

**This is v0.1 — the architectural spine plus one working example, not a
complete TCAD workbench.** It loads a built-in 2D MOSFET, solves it, and
visualizes the result. Structure editing, process simulation, mesh
editing, bias sweeps, and 3D visualization are later versions.

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
  File → Save/Load Project... or Ctrl+S, through a path-entry dialog
  (typed path + name, not a native OS file browser — see "Planned"
  below); results stay separate `.npz` files, never embedded in the
  project file.
- Undo/redo and a dirty-state indicator (`*` in the title bar), scoped to
  structure/mesh metadata edits only.
- A close-confirmation dialog ("Don't Save"/"Cancel") when quitting with
  unsaved changes.
- A second, purpose-built structure example (`mosfet_2d_structure`) for
  exercising this workbench — see "Two examples" below.

**Planned (not yet implemented):**
- A native OS file-picker for Save/Load (currently a typed-path dialog,
  reachable via File menu or Ctrl+S — genuinely functional, just not a
  file browser). The close-confirmation dialog still offers only
  Don't Save/Cancel, not a Save option.
- Per-region doping *profiles* beyond uniform (e.g. exposing
  `mosfet_doping()`'s own Gaussian/erfc shape as a region option).
- The "Doping" viewport mode falls back to a "No project loaded"
  placeholder for a structure that hasn't been solved yet, rather than
  previewing the structure's own rasterized doping array live. The
  "Structure" mode already conveys per-region doping (color by sign,
  and exact values in the Regions list), so this is a redundancy gap,
  not a missing capability -- a live pre-solve doping heatmap for
  `_mode == "doping"` is a small, well-scoped follow-up.
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
