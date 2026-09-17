# ParaView export — plan and status

## Scope

PyTCAD's in-app 3D viewer (`gui/services/viewer3d.py`, see
`3D-VISUALIZATION-PLAN.md`, recovered via
`git show e948fbe~1:pytcad/3D-VISUALIZATION-PLAN.md`) is a self-contained
PyVista/VTK window. It has no export path of its own; the only VTK-file
writers in the repo before this landed were two standalone example scripts
(`examples/08_3d_umos_amr.py`, `examples/07_3d_sic_power_mosfet.py`) whose
docstrings tell the user to open the output in ParaView by hand — dev-example
code, not reachable from the GUI, and with no `.pvd` time-series writer.

Investigated embedding actual ParaView (`pq*` Qt widgets, `paraview.simple`)
directly into the app: both require building all of ParaView from source
(multi-hour CMake/C++ build; the Qt widgets are not a PySide6 drop-in). Given
PyVista/VTK already covers the in-app visualization surface, the chosen
scope is narrower and lower-risk: make the GUI able to **export a genuine,
ParaView-native file** (a real `.vtu`, and for a sweep a real `.pvd` time
series — not the ad-hoc numbered-file pattern the examples use) and launch
the user's own separately-installed ParaView pointed at it. No new Python
dependency; ParaView itself stays an optional external executable, not a
package this repo imports.

## What shipped

- `gui/services/paraview_export.py` (pure, no Qt): `export_vtu(store,
  out_path)` and `export_pvd_series(store, snapshots, out_dir, base_name)`.
  Reuses `viewer3d.py`'s own `build_rectilinear_grid`/`attach_scalar_field`/
  `attach_vector_field` rather than re-deriving the RectilinearGrid-from-
  MeshAxes logic a second time (both modules live under `gui/services`,
  already a hard PySide6 dependency, unlike the example scripts, which avoid
  `viewer3d.py` only because THEY must stay pytcad-core-only).
  `export_pvd_series` writes one `.vtu` per sweep snapshot plus a `.pvd`
  collection keyed by each step's real bias voltage as the `timestep`
  attribute, so ParaView's own time slider/animation shows actual bias
  points — the concrete gap versus `examples/08`'s bare numbered-file
  sequence, which has no `.pvd` at all.
- `Viewer3DWindow` (`viewer3d.py`) gained a "ParaView Export" dock: "Export
  .vtu…" (always available once a result is open), "Export animation
  (.pvd)…" (enabled only once sweep-snapshot playback data exists, same
  gating convention the playback dock already uses), a ParaView-executable
  path field (persisted via `QSettings("PyTCAD", "Viewer3D")` — the first use
  of `QSettings` in this codebase; no prior settings-persistence pattern
  existed to match) with a Browse… file picker, and "Open in ParaView"
  (`QProcess.startDetached`, so ParaView runs fully independent of this
  process — nothing to reap). A failed launch surfaces a real `QMessageBox`
  warning naming the configured path, never a silent no-op.
- `gui/tests/test_paraview_export.py`: round-trips every scalar and vector
  field through a real `pv.read()` of the exported `.vtu` (not a
  file-exists check); parses the `.pvd` XML and checks per-snapshot
  timestep/file correctness and that each referenced `.vtu` round-trips its
  OWN snapshot's values (built from a synthetic multi-step `SweepSnapshots`,
  not an actual multi-point sweep solve, to keep the test fast and scoped to
  `paraview_export.py`'s own logic rather than the solver); mocks
  `QProcess.startDetached` to check the launch command and the
  launch-failure error path, and the "no prior export" no-op path; two more
  tests (`test_export_vtu_button_handler_writes_a_real_file`,
  `test_export_pvd_button_handler_writes_a_real_pvd`) call the ACTUAL
  `_on_export_vtu_clicked`/`_on_export_pvd_clicked` button handlers, not
  just the pure functions underneath them (see the real bug below for why
  that distinction mattered). 10/10 passing
  (`python -m pytest gui/tests/test_paraview_export.py -q`); the
  pre-existing 48 `test_viewer3d.py` tests still pass unchanged.

**A real bug was caught only by opening the actual running app**, exactly
the gap CLAUDE.md's "test the golden path in a browser/live app" rule warns
about: the first landing's `_on_export_vtu_clicked`/`_on_export_pvd_clicked`
referenced `paraview_export.export_vtu`/`export_pvd_series` with NO import
of `paraview_export` in scope anywhere in `viewer3d.py` -- a comment above
the (never-added) top-level import claimed "the export dock's handlers
import it lazily instead," but the actual `from . import paraview_export`
line inside each handler was never written. Every unit test up to that
point called `paraview_export.export_vtu`/`export_pvd_series` directly, or
exercised `_on_open_in_paraview_clicked` (which never touches
`paraview_export`) -- none of them called the two handlers that actually
had the bug, so the suite was green while the real "Export .vtu…" button
raised `NameError: name 'paraview_export' is not defined` on every click,
caught by a real solve -> real `Viewer3DWindow` -> real button-click driver
script and a screenshot of the resulting "Export failed" dialog. Fixed by
adding the lazy `from . import paraview_export` INSIDE each handler (still
avoids the module-level circular import with `viewer3d.py`, which
`paraview_export.py` imports FROM). Closed the test gap itself by adding
the two handler-level tests above, which reproduce the exact `NameError`
against the pre-fix code.

## Honest limits (deliberately not addressed here)

- `export_pvd_series` is scalar-only, matching `Viewer3DWindow`'s own
  already-documented Phase 4 limit (`SweepSnapshots` carries no vector
  data) — a sweep `.pvd` export never carries current-density vectors, only
  whichever single-snapshot `.vtu` a user exports carries them.
- No settings UI beyond the one path field in the 3D viewer's own dock —
  no app-wide Preferences panel exists yet to move it into.
- "Open in ParaView" always launches a NEW ParaView process; it does not
  attempt to detect or reuse an already-running instance.

## Real ParaView visual verification -- DONE 2026-09-17

ParaView 6.2.0-RC1 was found installed on this machine
(`/usr/local/bin/paraview` -> `/home/nihal/Desktop/Paraview/bin/paraview`,
with `pvpython`/`pvbatch` alongside it), closing the one item the section
above used to leave open ("no actual ParaView install/build was
available"). Verified through `pvpython`/`paraview.simple` (ParaView's own
Python API, off-screen -- `QT_QPA_PLATFORM=offscreen`), not through
PyVista, against two REAL solved results (not synthetic fixtures):

1. **Single `.vtu`** — `resistor_3d_example_spec()` (bias `{"left": 0.0,
   "right": 0.1}`) run through the real `solver_runner.run_job`, exported
   via `paraview_export.export_vtu`, then loaded with ParaView's
   `XMLUnstructuredGridReader`. All 5 expected point arrays present
   (`doping`, `potential`, `electron_density`, `hole_density`,
   `current_density`) with physically sane ranges — a real 0.0999999… V
   potential drop end to end, uniform ~1e17 doping/electron density as
   expected for this uniform n-type bar. A genuine ParaView filter
   (`Glyph`, oriented/scaled by `current_density`) ran successfully on the
   loaded data. An off-screen render, colored by `potential`, shows a
   clean linear blue-to-red gradient across the bar — the expected linear
   IR drop for a uniform resistor.
2. **`.pvd` time series** — a real 3-point voltage sweep (`right`:
   0.05/0.10/0.15 V) through the same `run_job` path, exported via
   `export_pvd_series`. ParaView's `PVDReader` read back
   `TimestepValues == [0.05, 0.1, 0.15000000000000002]` (the exact bias
   values, not frame indices), and stepping `view.ViewTime` through all
   three drove ParaView's own pipeline to genuinely different data at each
   step: `potential` range `(0.415, 0.465)` at 0.05 V, widening to
   `(0.415, 0.515)` at 0.10 V and `(0.415, 0.565)` at 0.15 V — the min
   (left contact) pinned and the max (right contact) tracking the bias
   exactly, confirmed via `reader.GetPointDataInformation()` at each
   timestep, not just by trusting the XML.

Both checks are reproducible non-interactively (no GUI session, no manual
eyeballing needed to re-verify): `pvpython <script>.py <path>` against a
freshly exported `.vtu`/`.pvd`. This is the manual check the section above
said was "still worth doing once" — done, and it holds.
