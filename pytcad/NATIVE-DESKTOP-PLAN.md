# Native desktop application — plan (proposed M53)

Status: **PROPOSED, 2026-09-25. P0 IMPLEMENTED the same day** at the
user's request ("review the plans again and implement P0"). The review
revisions are in §13 and the P0 results and exit-gate status are in §14.
**P1 (§15) APPROVED 2026-09-25** by the user, with the §15.4 targets as
written. S1 (§15.10), S2 (§15.12), S3 (§15.14), S4 (§15.16) and S5
(§15.18), S6 (§15.20), S7 (§15.22) and S8 (§15.24) landed
2026-09-25/26, uncommitted; S7 (export and ParaView) was then REMOVED at the
user's decision (§15.25). **P1 CLOSED 2026-09-26** with the user's sign-off
on the exit checklist (§15.24, §15.26). **P2 planned** (§16, proposed, awaiting
approval); P3 and later are not started. The
remaining §12 decisions are still open.
Target platform: **Windows only** (the product is built and used on
Windows; see the Windows-only decision of 2026-09-25).

## 0. Decision record and how this fits the existing plans

The user asked for a commercial-grade desktop application built as
**native C++ + Qt Widgets + VTK, with custom GPU rendering where TCAD
needs it**, replacing the current PySide6/QML GUI (`gui/`).

Two existing commitments are affected. This plan resolves them as
follows; both need explicit sign-off.

1. **`Architecture_Master_Plan.md` §37 — "Do not rewrite the project.
   Use progressive extraction."** (read via
   `git show a117d03:Architecture_Master_Plan.md`). This plan is not a
   rewrite of the project:
   - the numerical core (`pytcad/`, `core/`, `workbench/`) and the
     solver subprocess are **untouched**;
   - the new app is built **beside** the QML GUI, sharing the existing
     wire contracts;
   - the QML GUI stays working and its test suite stays green until a
     parity gate retires it (Phase 6).

   It *is* a rewrite of the presentation layer. That is the part the
   user asked to replace.
2. **M31 P6 ("native `QQuickVTKItem` 3D viewport") and P8 ("Qt shell
   hardening: split `AppController`, structured progress channel")**,
   both NOT STARTED (ARCHITECTURE.md §5.1; full M31 spec in git history,
   `git show 9893ce0~1:pytcad/M31-CPP-ARCHITECTURE-PLAN.md`).
   - P6 embedded VTK *inside QML*. It is **superseded** by a native
     `QVTKOpenGLNativeWidget` in a Widgets shell. **DECIDED
     2026-09-25**: the user said "let P1 replace M31 P6". P1 (§15) is
     P6's replacement.
   - P8's two goals carry over. The structured progress channel is
     §4.3 (Phase 0), and splitting `AppController` (2,249 lines) happens
     naturally as its duties move into the C++ document model and views
     (Phases 1–4).

## 1. Why — the measured baseline

Measured 2026-09-25 on this PC (1920×1080 at 100% scaling), viewport at
1200×800, per-frame render time of `gui/visualization/mpl_canvas_item.py`:

| Interaction | 1D curve | 2D map (MOSFET 136×55) | 2D + contours + mesh lines |
|---|---|---|---|
| field / mode / theme change (full rebuild) | 33 ms | 57 ms | 102 ms |
| pan (fast path) | 16 ms | 28 ms | 35 ms |
| wheel zoom (fast path) | 16 ms | 27 ms | 33 ms |
| hover — before quick fixes | 37 ms | 58 ms | 105 ms |
| hover — after quick fixes (landed 2026-09-25, uncommitted) | 0.02 ms | 0.02 ms | 0.02 ms |

- Cold start to first frame: **1.16 s**. Of that, 0.93 s is imports
  (0.81 s is matplotlib + Agg) and 0.20 s is loading the QML.
- Where a full 2D rebuild's time goes (cProfile): `tight_layout` 39%,
  tick and axis text 33%, `add_subplot` 12%, colorbar 10%. Drawing the
  field itself (`pcolormesh` + collection draw) is ~4%.
- The 3D view (`gui/services/viewer3d.py`, PyVista) is a separate
  top-level window, not part of the main UI.
- The viewport renders at logical pixels, so it is blurry on HiDPI
  screens. This is from reading the code and was not observed on this
  1080p/100% screen.

**Honest framing.** The lag is **software rendering through
matplotlib**, not Python as such. A PySide6 + Widgets + VTK shell would
recover most of the interaction speed. The case for *native C++* is
product-level:
- a native look and feel;
- a single installer without a conda environment;
- faster startup;
- IP protection (Python source ships readable);
- no Python↔Qt binding layer to debug.

The plan's performance gates (§6) must still be met and measured; they
are not assumed from the language choice.

## 2. Goals and non-goals

**Goals**
- A native Windows desktop app: C++20, Qt 6 Widgets, docking UI, VTK
  field views inside the main window.
- ≤16.7 ms interaction frames on the reference datasets (§6).
- A consistent light and dark theme; correct HiDPI rendering.
- Feature parity with today's GUI (inventory in §10) before the QML GUI
  is retired.
- A commercial-grade installer (Phase 5).

**Non-goals**
- No change to the numerical core, the solver subprocess or the result
  grammar, beyond the additive items in §4.
- No numerical algorithms in the GUI (master plan: "GUI never contains
  numerical algorithms"). See §3.2 for where GUI-side computations live.
- No Linux or macOS build.
- Not a 1:1 transliteration of the QML panels. Workflows are redesigned
  for a docking Widgets UI, and feature parity is the bar, not layout
  parity.
- No custom GPU renderer unless a measured gate fails (§5.4).

## 3. Target architecture

```
TCAD Desktop  (C++20, Qt 6 Widgets, MSVC 2022, pytcad/desktop/)
 ├─ Shell        QMainWindow + dock manager, actions/menus, undo stack,
 │               settings, theme, HiDPI
 ├─ Document     Project, DeviceSpec (C++ mirror of the JSON wire
 │               format), Study/sweep definitions, run history
 ├─ Views        FieldView (VTK), PlotView (in-house), StructureEditor
 │               (QGraphicsView), property editors, tables, console
 ├─ Data         NpzReader -> ResultModel (C++ counterpart of
 │               gui/services/result_store.py's ResultStore API)
 └─ Process bridge
     ├─ JobRunner     QProcess -> python -m gui.services.solver_runner
     │                job.json out.npz           (EXISTING, unchanged)
     └─ BackendClient QProcess, JSON-RPC over stdio -> Python backend
                      service (NEW, Qt-free, wraps existing services)

Solver side (UNCHANGED): pytcad/ + core/_core (MinGW) + workbench/
```

The C++ app **never links `_core` or embeds Python**. Every
interaction with the Python world crosses a process boundary, exactly
as the QML GUI's solver runs already do. This keeps the MinGW-built
`_core` and the MSVC-built app independent, and it preserves "subprocess
isolation per run" (CLAUDE.md hard rule).

### 3.1 Repository layout (proposed)

```
pytcad/desktop/            separate CMake project (MSVC), not core/
  CMakeLists.txt
  src/shell/  src/document/  src/views/field/  src/views/plot/
  src/views/structure/  src/data/  src/bridge/  src/theme/
  tests/                   Qt Test / CTest
  bench/                   frame-time harness (§6)
pytcad/backend_service/    NEW Qt-free Python package: JSON-RPC server
                           wrapping existing gui/services modules
```

### 3.2 Where GUI-side computations live

Today some GUI features compute things in Python:
- `result_store.extract_line_cut`;
- `structure_model.rasterize_doping`;
- `sweep_derived.py` (Vth, gm and similar readouts);
- `process_derived.py`;
- `examples.py`, which builds DeviceSpecs via `pytcad`.

Rule: **one implementation**. These stay in Python, reached through
the backend service (§4.4). A later port to C++ is allowed only with a
parity test against the Python function as oracle, following the M31
kernel-port discipline.

The services side is already largely Qt-free. This was checked
2026-09-25 by importing each module in a fresh interpreter and looking
for PySide6, pyvista or matplotlib in `sys.modules`, not by grepping:

| Group | Services |
|---|---|
| Qt-free when imported (18) | `characterization`, `compact_runner`, `device_spec`, `examples`, `gate_vfb`, `moscap_runner`, `process_derived`, `process_model`, `process_result_store`, `process_runner`, `project_store`, `provenance_diff`, `result_store`, `solver_backend`, `solver_runner`, `structure_model`, `sweep_derived`, `undo_stack` |
| Pulls in Qt through its imports (1) | `paraview_export`: it imports `viewer3d`'s grid builders when it loads, which brings in PySide6, pyvista and matplotlib. Phase 0 moves those builders into a Qt-free module, or the native FieldView takes over export. |
| Solver side, not GUI (1) | `mpi_schwarz_runner`: needs `mpi4py`, which is not installed on this Windows machine. |
| Import PySide6 directly (5) | `gui_state_validator`, `icon_provider`, `job_runner`, `remote_job_runner`, `viewer3d` |

The five Qt-bound services are the ones re-implemented natively in C++.

## 4. Contracts (Phase 0 deliverables)

### 4.1 DeviceSpec (job input)
- Today: the JSON produced by `DeviceSpec.to_dict()`
  (`gui/services/device_spec.py`). It has **no explicit spec-version
  field** (checked). Projects carry `project_store.SCHEMA_VERSION = 5`.
- Deliverables (**revised in review, §13 item 3**):
  - a **lossless C++ document** (`desktop/src/document/`). Every key
    survives load → save in value and order, including keys this build
    has no accessor for;
  - typed accessors only for what the shell uses;
  - a round-trip gate over **every shipped example**: Python
    `DeviceSpec` → C++ → `DeviceSpec.from_dict`, which must compare
    equal. Python's `from_dict` stays the single authority on validity.
- The JSON Schema generated from the dataclasses is **dropped for P0**.
  `from_dict` applies checks that a schema would only approximate:
  region validators, sweep coercion and mutual exclusions. A schema
  would be a second, weaker specification. Revisit in P4 if the
  editors need one.
- Open decision: add an additive `spec_version` field. This touches the
  wire format, so it needs sign-off.

### 4.2 Results (solver output)
- Today: npz grammar v3 (`solver_backend.SOLVER_RESULT_SCHEMA_VERSION =
  3`), written with `np.savez`, which is uncompressed.
- Verified on the 1D diode, 2D MOSFET and 3D resistor examples:
  - every array has dtype kind `f`, `i`, `b` or `U`, and all of them
    load with `allow_pickle=False`, so there are no pickled objects;
  - sizes are 32–481 KiB.
- The C++ side therefore needs only a small reader for a zip file with
  `.npy` entries: no numpy, no pickle, and no zlib unless compression is
  ever turned on. miniz (MIT) can cover that case.
- Conformance gate: for every array in a reference set of result files,
  the C++ reader's bytes, shape and dtype are **identical** to numpy's.
  The C++ structural validation mirrors `solver_backend.py`'s validator.
- Not planned: switching the result format (HDF5 or VTKHDF). The npz
  contract is kept, which avoids any solver-side change.

### 4.3 Progress channel
- Today: `PYTCAD_STAGE=...` stdout markers, plus `SolverTelemetryPanel`'s
  best-effort scraping of verbose Newton lines (`job_runner.py`).
- Deliverable (M31 P8's goal): an additive JSON-lines progress record
  on stdout or a side pipe. It carries stage, iteration, residual norms
  and the sweep point. Existing markers stay, so the QML GUI is
  unaffected.
- **P0 spec (implemented in P3):**
  - **Line format.** Stdout lines of the form `PYTCAD_PROGRESS <json>`,
    one compact JSON object per line. Existing `PYTCAD_STAGE=` and
    `RESULT_PATH=` lines are unchanged.
  - **Fields.**
    - `"v": 1`;
    - `"event"`: one of `"stage"`, `"newton"`, `"sweep_point"`,
      `"transient_step"`, `"done"` or `"error"`;
    - `"stage"`: the same names `PYTCAD_STAGE` uses;
    - `"t"`: seconds since the job started;
    - `newton` events add `"iter"` and `"residual"`, a map of norm name
      to value, for example `{"F": ..., "dpsi": ..., "dn_rel": ...}`;
    - `sweep_point` events add `"index"`, `"count"`, `"contact"` and
      `"value"`.
  - **Non-finite numbers** are written as `null`, because NaN is not
    JSON.
  - **Rate limit:** at most one `newton` record per iteration and at
    most 50 records/s. Excess records are dropped, never buffered
    without bound.
  - **Where the numbers come from (stated honestly).** Per-iteration
    residuals exist today only as the frozen core's `verbose=True`
    prints. P3 therefore produces `newton` events *inside
    `solver_runner`*, by parsing those prints in-process. That is the
    same best-effort scraping `job_runner.py` does now, moved next to
    the source; it does not touch the core. A true structured hook in
    the core is a frozen-core amendment and needs its own sign-off.
  - **Change the QML GUI needs.** `job_runner.py` forwards every
    unrecognised stdout line to the console (`progressLine`). When P3
    lands the channel, it must also make `job_runner.py` swallow
    `PYTCAD_PROGRESS` lines. Otherwise the QML console fills with JSON.

### 4.4 Backend service (Python, Qt-free)
- A JSON-RPC 2.0 server over stdio, in `pytcad/backend_service/`,
  started lazily and asynchronously so it never blocks the first frame.
- Initial method set, all wrapping existing functions:
  - examples: list and build;
  - DeviceSpec: validate and normalize;
  - structure model → DeviceSpec;
  - derived: sweep and process;
  - line cut;
  - project: load and save (schema 5);
  - ParaView export (VTU/PVD), once it is Qt-free (§3.2);
  - provenance diff;
  - characterization.
- Gates:
  - a conformance test per method: the RPC result equals a direct
    Python call;
  - latency is measured, with a target of ≤5 ms round trip for small
    calls, measured and not assumed.

## 5. Rendering design

### 5.1 FieldView (VTK, inside the main window)
- Structured grids use `vtkRectilinearGrid`. Unstructured triangle and
  tetrahedral meshes (M21 phase 3, M47) would use
  `vtkUnstructuredGrid`, **but** the GUI's result grammar has no
  unstructured geometry today. See §15.2, a correction made while
  planning P1.
- 2D uses a parallel-projection camera with pan and zoom only; 3D adds
  orbit.
- Features:
  - log-scale colour maps;
  - region boundaries, contacts and a junction contour overlay;
  - mesh edges;
  - slice, clip, isosurface and volume rendering;
  - current-density glyphs and streamlines.
- Everything `viewer3d.py` ships today is ported: isosurface, volume
  rendering with transfer-function presets, sweep playback, exploded
  view, VTU/PVD export and open in ParaView.
- Hover readout uses VTK locators, O(log n), and snaps to a real mesh
  node, the same "never fake" rule as the M51 hover.
- Renders at device pixels, which fixes HiDPI.

### 5.2 PlotView (in-house)
- Covers I-V, C-V, transient, AC, convergence, band diagrams, line
  cuts, family and comparison overlays, log axes and hover snapping.
- First implementation: QPainter with per-pixel-column min/max
  decimation.
  - Rationale: TCAD curves are small (sweeps of 10–1,000 points, 1D
    profiles of about 10²–10⁵ points), so decimated QPainter drawing
    is expected to meet the 16.7 ms gate. This is an expectation to be
    measured in Phase 2.
- Moves to GPU (`QRhiWidget`) only if that gate fails.
- **Not** Qt Charts or Qt Graphs, which are GPL or commercial only
  (§7.3).

### 5.3 StructureEditor
- `QGraphicsView`: regions, contacts, gates, snapping to mesh lines,
  undo and redo.
- Structure hover readout, the same as M51's `_hover_structure`.

### 5.4 Custom GPU rendering — only where measured
Decision rule: **write custom GPU code only when a §6 gate fails on
the standard path**, and record the failing measurement in this file
first (master plan Principle 5, "optimize the dominant cost").
Candidates, none known to be needed today:
- very large 3D unstructured meshes beyond VTK's interactive rates;
- specialised overlays such as band-edge ribbons or animated process
  steps;
- the PlotView GPU path above.

### 5.5 Theme
- One palette, in light and dark, drives:
  - the Qt style (Fusion + `QPalette` + minimal QSS);
  - VTK background and annotation colours;
  - PlotView.
- No hard-coded colours in views. That was a Phase 3/4 review finding
  in the QML GUI.

## 6. Performance budgets and harness

- The harness lives in `pytcad/desktop/bench/` and prints a table in
  the same spirit as `benchmarks/BASELINE.md` (M32).
- No performance claim goes in a plan or commit without a harness run.
- Reference datasets:
  - the three examples above (1D diode, 2D MOSFET 136×55, 3D resistor);
  - a large synthetic 2D unstructured mesh and a large 3D tetrahedral
    mesh, sizes fixed in Phase 0.

| Metric | Today (measured) | Target |
|---|---|---|
| 2D pan / zoom frame, p95 | 28–35 ms | ≤ 16.7 ms |
| 3D orbit frame, p95 | not measured (separate window) | ≤ 16.7 ms |
| hover lookup | 0.02 ms (after quick fixes) | ≤ 1 ms, including large meshes |
| field / colour-map switch, 2D | 57–102 ms | ≤ 50 ms |
| field switch, large 3D | not measured | ≤ 200 ms |
| open result (reference files) | not measured | ≤ 100 ms for ≤ 1 MB |
| cold start to first frame | 1.16 s | ≤ 1.0 s (backend starts after first frame) |
| backend RPC round trip (small call) | n/a | ≤ 5 ms |

The targets are proposals. The user can tighten or relax them at
approval.

## 7. Toolchain, dependencies, licensing

### 7.1 Toolchain (Windows)
- **MSVC.** Qt and VTK binaries for Windows are MSVC-ABI, and MinGW
  cannot link them.
  - **Already installed on this PC** (found in review): Visual Studio
    18 Community, with MSVC 14.51 and Windows SDK 10.0.26100.
    `build.ps1` finds it via `vswhere`. No new system install was
    needed.
  - It is a system install, separate from every conda environment.
  - **Nothing is installed into `tcad-dev`** (CLAUDE.md: the compiler
    incident).
  - `_core` stays on the `tcad-cpp` MinGW toolchain. There is no link
    between the two artifacts.
- CMake + Ninja.

### 7.2 Dependency source — decide in Phase 0 by trying both
- **(a) conda-forge, in a separate `tcad-gui` environment** (qt6-main,
  vtk). Prebuilt MSVC binaries give the fastest start, and it mirrors
  the `tcad-cpp` pattern.
- **(b) vcpkg manifest mode.** Pinned and reproducible, suited to
  release builds, but the first Qt + VTK build takes hours.
- Recommendation: (a) for the spike, and (b) for release if (a) cannot
  produce a deployable, pinned build.
- **P0 used (a) successfully.** The `tcad-gui` env has:
  - Qt 6.11.2 (`qt6-main`);
  - VTK 9.7.0 (`vtk-base`, built against Qt 6 and the MSVC runtime);
  - `vc14_runtime` 14.51, which matches the compiler and the system
    runtime;
  - CMake 4.4.3, Ninja and nlohmann_json 3.12.
- Two conda-forge packaging quirks, each found by a failed configure:
  - `vtk-io-ffmpeg` is split out of `vtk-base`, but `vtk-base`'s CMake
    targets still reference its `.lib`;
  - `tbb-devel` has to match `tbb` 2023.1.0.
- The exact create command is at the top of `desktop/build.ps1`.
- The plan's P1 libraries are also on conda-forge for win-64 (checked):
  `qt6-advanced-docking-system` 5.1.1 and `qwt` 6.3.0.

### 7.3 Licensing (closed-source commercial product)

| Component | Licence | Use |
|---|---|---|
| Qt 6 Core/Gui/Widgets/OpenGL | LGPLv3 or commercial | OK with dynamic linking + LGPL obligations (notices, relinkability) — or buy commercial |
| Qt Charts / Qt Graphs / Qt Data Visualization | GPLv3 or commercial only | **Do not use** (without commercial licence) |
| VTK | BSD-3 | OK |
| Qt Advanced Docking System | LGPL-2.1 | OK (dynamic) |
| Qwt (if PlotView reuses it) | Qwt licence (LGPL-based) | OK |
| QCustomPlot | GPL or commercial | Avoid |
| nlohmann/json, miniz | MIT | OK |

Every other Qt module's licence is checked at qt.io/licensing before
first use and recorded here.

**The compiler's licence (found in review).** The installed Visual
Studio is the **Community** edition. Its licence limits use by
organisations: enterprises are excluded, and otherwise use is limited
to small teams. Check the current Microsoft licence terms for the exact
thresholds. Building a commercial product with it may therefore need
Visual Studio Professional (or a paid subscription covering the Build
Tools). This is added to the §12 decisions, not assumed either way.

## 8. Testing strategy

- **C++ unit tests:** Qt Test via CTest, covering the document model,
  NpzReader, DeviceSpec JSON, the theme and PlotView maths.
- **Contract tests, run from the Python suite so they gate every
  change:**
  - NpzReader bytes equal numpy's (§4.2);
  - DeviceSpec round trip (§4.1);
  - RPC result equals a direct call (§4.4).
- **Rendering tests:** VTK and PlotView render offscreen to an image,
  compared against a reference image with a tolerance. Reference images
  are regenerated on this machine only, following the same
  machine-specific-golden caution as the M13 digests.
- **End-to-end tests:** QTest input simulation drives real widgets
  (load example → run → view field → hover → line cut). This is the
  same philosophy as `gui/tests/test_smoke_e2e.py`: real UI actions,
  not controller shortcuts.
- **Invariant:** the existing Python suite stays at **N passed, zero
  warnings** throughout. That includes the 834 GUI tests, until
  Phase 6 retires what they test.

## 9. Phases

Sizes follow ARCHITECTURE.md's S/M/L/XL convention; there are no
calendar estimates. Each phase ends with an adversarial probe pass and
user sign-off (CLAUDE.md workflow).

**P0 — Spike and contracts [M]**
- Deliverables:
  - the toolchain is proven, with a one-command build of a minimal Qt
    Widgets + VTK window;
  - NpzReader and its conformance gate;
  - the DeviceSpec JSON Schema and round trip;
  - the progress-channel spec (§4.3) and a backend-service skeleton
    with 2 methods;
  - the benchmark harness, with today's baseline re-recorded.
- Exit:
  - a clean checkout builds with one documented command;
  - the reader is byte-identical on the 1D, 2D and 3D reference files;
  - measured VTK 2D-map pan and zoom frame times on the 2D MOSFET are
    recorded here.

**P1 — Results viewer [L]**
- Deliverables:
  - the shell (docking, menus, theme, HiDPI, settings);
  - open `.npz`;
  - FieldView 2D and 3D, with the field list, colour map, log scale,
    mesh and contour overlays and hover readout;
  - VTU/PVD export and open in ParaView.
  - Line cuts moved to P2: a cut is a curve and needs PlotView. See
    §15 for the detailed P1 plan.
- Exit:
  - the §6 gates for view interactions pass;
  - `viewer3d.py`'s features are ported (§10.3).
- This is already a usable post-processing tool, like SVisual.

**P2 — Plots [M]**
- Deliverables: PlotView and every curve-based viewport mode — series,
  cv, transient, ac, convergence, bands, recombination, cut — with
  family and comparison overlays. Line cuts come from the backend's
  `extract_line_cut` (moved here from P1).
- Exit: every mode in §10.2 has a C++ equivalent and an image test.

**P3 — Run and monitor [L]**
- Deliverables:
  - JobRunner and RemoteJobRunner equivalents: QProcess, cancel, and
    the remote SSH path including the Windows `mkdir -p` lesson from
    `gui/tests/fixtures/fake_ssh.py`;
  - solver telemetry, using the structured channel;
  - the console;
  - study and batch (M30);
  - the backend service at the full method set.
- Exit: an end-to-end run → view flow for the 1D, 2D and 3D examples.

**P4 — Build and edit [XL]**
- Deliverables:
  - StructureEditor;
  - mesh, doping, implant, anneal, oxidize, substrate, contact and gate
    editors;
  - process flow;
  - the Physics Lab model toggles;
  - device templates;
  - the validation panel;
  - projects (schema-5 compatible, both directions);
  - undo.
- Exit: parity checklist §10.1 complete; the QML GUI's saved projects
  open unchanged.

**P5 — Packaging [M]**
- Deliverables:
  - an installer (WiX or Inno Setup, to be decided);
  - a bundled Python runtime for the solver and backend (embedded
    distribution or conda-pack, to be decided);
  - `windeployqt`-based deployment;
  - code signing;
  - crash reporting;
  - LGPL compliance bundle;
  - clean-machine install test.
- Exit: install on a clean Windows VM → run all examples → uninstall
  cleanly.

**P6 — Retire the QML GUI [S]**
- Gate:
  - §10 is 100% ticked;
  - the P3/P4 end-to-end flows pass;
  - the user signs off.
- Then remove `gui/qml/`, the QML-only controllers and their tests.
  `gui/services/` stays, as the backend's implementation.

**Transition rule:** from P1 on, the QML GUI receives bug fixes only.
New GUI features land in the native app, so two GUIs never both grow.

## 10. Parity inventory (from the tree, 2026-09-25)

### 10.1 Panels and editors
- **QML panels (17):**
  - ACPanel, BandDiagramPanel, CompactModelPanel, ConsolePanel,
    DeviceTemplatesPanel, MeshPanel;
  - PhysicsLabPanel, ProbeStationPanel, ProcessPanel,
    ProjectTreePanel, PropertiesPanel, SolverTelemetryPanel;
  - StructurePanel, StudyPanel, SweepPanel, TransientPanel,
    ViewportPanel.
- **QML components (21):**
  - AnnealEditor, BusyOverlay, ContactEditor, DerivedQuantitiesPanel,
    DopingEditor, ErrorDialog, GateEditor;
  - GlowBlob, ImplantEditor, MainToolBar, MeshEditor, OxidizeEditor,
    PanelHeader, RegionList;
  - StatusIndicator, SubstrateEditor, ThemedComboBox, ThemedSpinBox,
    ValidatedTextField, ValidationBanner, ValidationPanel.
- **Controllers (18, in `gui/controllers/`):**
  - app_controller, band_diagram_controller, builder_controller,
    compact_model_controller, console_model, contact_list_model;
  - cv_controller, family_sweep_controller, gate_list_model,
    lab_controller, probe_station_controller;
  - process_step_list_model, project_tree_model, properties_model,
    region_list_model, solver_telemetry_controller, study_controller.

### 10.2 Viewport modes (`MplCanvasItem._build_figure`)
structure, mesh, process, bands, recombination, convergence, cv,
transient, ac, cut, series, doping/field — plus the contour and mesh
overlays, log scale, hover readout (1D, 2D field, structure, mesh),
pan, zoom, fit and reset.

### 10.3 3D viewer (`viewer3d.py`)
Isosurface, colour maps, volume rendering with transfer functions,
vector fields, sweep snapshot playback, exploded view. (VTU/PVD export
and Open in ParaView were removed from TCAD on 2026-09-26, §15.25.)

## 11. Risks

| Risk | Mitigation |
|---|---|
| Scale: P4 is the bulk of today's GUI behaviour | Phased; P1 alone is a shippable viewer; transition rule freezes QML growth |
| Qt + VTK Windows build complexity | P0 spike proves it before any feature work; two dependency sources evaluated |
| Contract drift between C++ and Python | Contract tests in the Python suite (§8) gate every change on either side |
| Licence mistake (GPL module) | §7.3 whitelist; check before first use |
| Bundling Python for the solver | Decided and tested in P5 on a clean VM; solver already runs as a plain `python -m` subprocess |
| Slower iteration in C++ than QML/Python | Keep computations in the Python backend; C++ owns only UI, rendering, I/O |
| RPC latency making the UI feel slow | Measured gate (§4.4); async calls; never on the paint path |

## 12. Open decisions (need the user)

1. Approve this plan and the milestone number (M53 appears unused;
   checked ARCHITECTURE.md, whose highest is M52).
2. Qt licence: LGPLv3 (free, with obligations) or commercial.
3. ~~Confirm that M31 P6 is superseded~~ — **DECIDED 2026-09-25**: P1
   replaces M31 P6 (user's decision). Folding P8 into this plan (§0)
   stays proposed; it was not part of that decision.
4. The additive `spec_version` field in the DeviceSpec wire format
   (§4.1).
5. The long-term home of GUI-side computations: stay in the Python
   backend (recommended) or port to C++ with oracle parity.
6. Installer technology and the Python-bundling approach (can wait for
   P5).
7. ~~The Visual Studio licence for commercial builds~~ — **DECIDED
   2026-09-25.** The project is currently individual / academic
   research, which the Community licence permits (user's decision).
   Revisit before any commercial distribution. The same framing
   applies to item 2: Qt stays **LGPLv3** with no GPL-only modules
   (§7.3), and the commercial-licence question is deferred to the same
   point.

Still open: 1 (M53 number), the P8 half of 3, 4 (`spec_version`,
needed by P4), 5 and 6. None of these blocks P1.

## 13. Review revisions (2026-09-25, before implementing P0)

What re-reading the plan against the tree and this machine changed:

1. **The toolchain was already present** (§7.1). Visual Studio 18
   Community has MSVC 14.51 and the Windows SDK, so there was no Build
   Tools install. Its licence may not cover commercial use (§7.3), so
   that is a new decision (§12 item 7).
2. **Dependency source (a) works** (§7.2). It needed two extra
   conda-forge packages (`vtk-io-ffmpeg`, `tbb-devel`). The P1 docking
   and plot libraries exist on conda-forge.
3. **No generated JSON Schema in P0** (§4.1). The contract is instead a
   lossless document plus a round trip through Python's own
   `DeviceSpec.from_dict`, so validation has one authority.
4. **The progress channel is specified, and its limits are explicit**
   (§4.3). Per-iteration numbers exist only as the frozen core's
   verbose prints. The QML GUI's `job_runner.py` needs a one-line
   filter when P3 lands the channel.
5. **Where the contract gates live.** They are in the Python suite,
   under `gui/tests/`, and skip cleanly when the app is not built (the
   `_core` pattern). A contract drift on either side therefore fails
   the normal `run_tests.py` run.
6. **What the frame benchmark measures (defined in §14).** A frame is
   the camera or scalar change, plus VTK's `Render()`, plus
   `WaitForCompletion()` (glFinish). Qt's composite of the finished
   frame, a single texture blit, is excluded. That is stated rather
   than hidden.
7. **Large datasets for P0 are structured.** They are synthetic
   1000×1000 2D and 100³ 3D grids in the real result grammar.
   Unstructured-mesh views are P1, so their budgets are measured there.

## 14. P0 results (2026-09-25)

### 14.1 What was built

| Piece | Where |
|---|---|
| One-command build (MSVC via vswhere + `tcad-gui` env; `-Test` runs the C++ unit tests) | `desktop/build.ps1`, `desktop/CMakeLists.txt` |
| `.npz` reader: zip (stored + deflate, zip64, CRC-checked) + `.npy` v1–3; dtypes b/i/u/f/U, C or Fortran order, 0-d; named rejections (pickled objects, big-endian, structured, corrupt) | `desktop/src/data/npz.{hpp,cpp}` |
| Result model (structural core of `validate_result`: schema stamp, dimensionality, axes, field shapes, units) | `desktop/src/data/result_model.{hpp,cpp}` |
| Lossless DeviceSpec document + typed accessors | `desktop/src/document/device_spec_document.{hpp,cpp}` |
| Contract tools | `desktop/src/tools/npz_dump.cpp`, `spec_roundtrip.cpp` |
| Spike app: Qt Widgets shell (docked field list, Fit, log scale, status-bar hover readout), VTK FieldView (2D map, 3D surface, viridis, scalar bar, 2D pan/zoom, 3D orbit, node-snapping hover), `--bench` mode | `desktop/src/{app,shell,views/field,bench}/` |
| Backend service (JSON-RPC 2.0 over stdio; `system.ping/methods/shutdown`, `examples.list/build`) | `backend_service/` |
| Frame-time harness: native vs today's viewport on the same files | `desktop/bench/run_bench.py`, `baseline_mpl.py` |

### 14.2 Gates

| Gate | Result |
|---|---|
| Clean MSVC build at `/W4 /permissive-` | no warnings |
| C++ unit tests (`desktop/tests/test_data.cpp`) | 15/15 pass |
| Reader identical to numpy (dtype, order, shape, raw bytes, logical values, strings) on solved 1D/2D/3D examples and on 16 edge-case arrays, stored and compressed | pass (`gui/tests/test_desktop_contracts.py`) |
| Reader rejects pickled, big-endian, bit-flipped (CRC), truncated and non-zip files, naming the cause | pass |
| Result model accepts what `NpzResultStore` accepts and rejects the 6 breakages `validate_result` rejects; schema versions equal `KNOWN_RESULT_SCHEMA_VERSIONS` | pass |
| DeviceSpec round trip, all 12 shipped examples: JSON equal, key order kept, `from_dict` equal | pass |
| Backend RPC equals the direct call for every method and example; error codes; notifications; `print()` cannot corrupt the protocol; NaN refused; shutdown; Qt-free | pass (`gui/tests/test_backend_service.py`) |
| Mutation check: dropping Fortran-order handling in the reader makes the contract test fail (`fortran_2d: c_order_f64_sha256 differs`); restored, it passes | done |

### 14.3 Frame times

Measured on this PC: RTX 5060 Ti, 1200×800 device px at DPR 1.0.
Numbers are p95 in ms unless stated. Native is `tcad_desktop --bench`;
matplotlib is today's `MplCanvasItem`.

| Dataset | Metric | Native | matplotlib | Target (§6) | Status |
|---|---|---|---|---|---|
| mosfet_2d (136×55) | pan | 3.2 | 33.9 | ≤16.7 | met |
| mosfet_2d | zoom | 0.8 | 35.4 | ≤16.7 | met |
| mosfet_2d | field switch | 3.8 | 85.5 | ≤50 | met |
| mosfet_2d | hover lookup | 0.001 | 0.022 | ≤1 | met |
| mosfet_2d | open result | 17.9 | — | ≤100 | met |
| resistor_3d | orbit / pan / zoom | 1.1 / 3.1 / 0.9 | (separate window) | ≤16.7 | met |
| resistor_3d | field switch / hover | 3.4 / 0.020 | — | ≤200 / ≤1 | met |
| synthetic 2D 1000×1000 | pan / zoom | 3.3 / 1.6 | 181 / 206 | ≤16.7 | met |
| synthetic 2D 1000×1000 | field switch | **86.1** | 338 | ≤50 | **missed** |
| synthetic 3D 100³ | orbit / pan / zoom | 0.7 / 3.9 / 2.8 | — | ≤16.7 | met |
| synthetic 3D 100³ | field switch | 17.2 | — | ≤200 | met |
| synthetic 3D 100³ | hover lookup | **3.46** | — | ≤1 | **missed** |
| all | cold start to first frame | 513–713 | 1,160 (Python app, §1) | ≤1,000 | met (warm); the first-ever launch after the build took 1,377 ms (one-time DLL load) |

Correctness probes, recorded by the bench. A hover at the view centre
after Fit lands on the device-centre node in every 2D and 3D dataset:
for the MOSFET, `doping: -1.000e+17 cm^-3 @ x=0.61, y=0.10 um`, against
a mesh centre of (0.60, 0.10). The nodes either side are 0.592 and
0.608, so this is the correct snap.

### 14.4 Open items carried into P1

1. **2D field switch on 1M nodes (86 ms; target ≤50).** Profile first.
   Suspects:
   - the per-element scalar copy (`to_doubles`, then a per-value
     `SetValue`);
   - the geometry filter re-running on 1M points.
2. **3D hover on large surfaces (3.5 ms; target ≤1).** `vtkCellPicker`
   walks the surface. Candidates are a static cell locator built once
   per result, or hardware selection. Measure, then choose.
3. **1D results** show no FieldView by design. Curves arrive with
   PlotView (P2).
4. ~~Unstructured meshes come with P1's FieldView~~. **Corrected in
   §15.2:** no GUI result carries unstructured geometry yet, so this
   needs a result-grammar extension first.
5. §12's decisions, now including item 7 (the Visual Studio licence).

## 15. P1 — Results viewer: detailed plan (2026-09-25, APPROVED)

Built on P0 (§14). This is the phase that makes the native app a usable
post-processing tool. It must match the **2D field modes** of today's
viewport and **everything `viewer3d.py` does**, on the same result
files.

### 15.0 Before P1 code starts

- ~~§12 item 3.~~ **Done 2026-09-25**: P1 replaces M31 P6 (VTK inside
  QML).
- **The two GUI-layer refactors in §15.6.** They touch files the QML GUI
  uses, and are each gated bit-identical.
- No numerical-core file changes in P1.

### 15.1 Scope

**In:**

| Area | Deliverable |
|---|---|
| Shell | Docking via Qt Advanced Docking System (conda-forge `qt6-advanced-docking-system` 5.1.1, built against qt6-main ≥ 6.11.2, which matches `tcad-gui`); layout save/restore (`QSettings`); recent files; drag-and-drop `.npz`; one theme-token set driving Qt palette, VTK background/annotations and scalar bar, in light + dark; result info panel (schema, dimensionality, node counts, terminals, solved bias) |
| Data | Full mirror of `validate_result` (adds vector fields, the v2 geometry block, sweep snapshots); ResultModel gains vector fields, sweep snapshots (`SweepSnapshots`), `region_materials`/`structure_regions`, terminals |
| 2D maps | The viewport's 2D field modes: every scalar field, doping (signed colour map), bands and recombination maps (§15.3); log scale; contours; true mesh-line overlay; manual/locked colour range; hover readout; Fit/Reset |
| 3D | Everything in §10.3: surface, axis-aligned slice planes (draggable), isosurface with level control, volume rendering with the four `TRANSFER_FUNCTION_PRESETS` (linear / log-high / log-low / threshold), colour-map choice, current-density glyphs + streamlines, sweep-snapshot playback (play/pause/step/slider), exploded view by region, clipping plane |
| Export | VTU and PVD (sweep series) through the backend calling the existing `paraview_export` (one implementation), plus "Open in ParaView" with a configured path |
| Backend client | C++ `BackendClient`: async JSON-RPC over a `QProcess`, request ids, per-call timeout, crash detection + restart, lazy start after first frame |
| Performance | Close §14.4 items 1–2; new budgets in §15.4 |

**Out (and where each goes):**
- **Line cuts and all curves:** P2. A cut is a curve, so it needs
  PlotView.
- **1D results:** P2.
- **Running solves:** P3.
- **Editing:** P4.
- **Unstructured meshes:** a separate item; see §15.2.

### 15.2 Correction: there are no unstructured results to view

Found while planning P1, and verified in the tree:
- the result grammar's only geometry kind is `structured_rectilinear`
  (`solver_backend._KNOWN_GEOM_KINDS`);
- `point_cloud` is reserved, and the validator rejects it;
- `solver_runner.py`, `device_spec.py` and `examples.py` have no
  unstructured path at all.

The unstructured solvers (M21 phase 3, M47) are library-level only.
The earlier promise of unstructured views in P1 (§5.1 and §14.4 item 4,
both now corrected) was therefore wrong.

Viewing unstructured results needs, in order:
1. result schema 4 (node coordinates + cell connectivity + cell type);
2. `solver_runner` support for unstructured jobs;
3. DeviceSpec wire support.

That is a solver-side milestone of its own (proposed **M53-U**, after
P1). FieldView's pipeline takes a `vtkDataSet`, so adding
`vtkUnstructuredGrid` later is additive.

### 15.3 New backend methods

All of these wrap existing code. Bulk arrays never go through JSON.

| Method | Wraps | Returns |
|---|---|---|
| `analysis.band_map {result}` | the band-edge computation `MplCanvasItem._draw_bands` does today via `workbench.analysis.observables.band_diagram` (after the refactor in §15.6) | an `.npz` path (Ec, Ev, EFn, EFp as `field__*` + `unit__*`) |
| `analysis.recombination_map {result}` | the computation in `_draw_recombination` (same refactor) | an `.npz` path |
| `export.vtu {result, out}` | `paraview_export.export_vtu` | the written path |
| `export.pvd {result, out_dir, base}` | `paraview_export.export_pvd_series` | the written paths |

**Bulk transport.** Derived maps are written by the backend as `.npz`,
in the result grammar, to a service-owned temp directory that is
removed on shutdown. The C++ side reads them with the reader already
conformance-gated in P0. A 1M-node map is about 8 MB per field as f8;
as JSON text it would be about 3×, plus parse time.

- Gate: write + read of a 1M-node derived map ≤ 150 ms on this PC,
  measured, not assumed.

### 15.4 Performance work and budgets

1. **2D field switch at 1M nodes (86 ms → target ≤ 50 ms).**
   - Profile first.
   - Planned fix, to be confirmed by the profile:
     - build the extracted geometry once per result;
     - swap only the scalar array on its output, instead of re-running
       the geometry filter;
     - bulk-copy contiguous `<f8` data (memcpy), instead of converting
       per element.
2. **3D hover on large surfaces (3.5 ms → target ≤ 1 ms).**
   - Replace `vtkCellPicker` with a static cell locator over the
     extracted surface, built once per result; hardware selection is
     the fallback.
   - Measure both and choose.
3. **New bench rows** (added to `run_bench.py`, all at 100³ and on the
   MOSFET):

| Row | Target |
|---|---|
| slice-plane drag, per frame | ≤ 16.7 ms |
| isosurface level change | ≤ 100 ms |
| volume-rendering orbit | ≤ 33 ms |
| snapshot playback step | ≤ 33 ms |
| streamline rebuild | ≤ 200 ms |
| ADS dock/undock and layout restore | ≤ 100 ms |

The targets were fixed as written at P1 approval (2026-09-25).

### 15.5 Gates

- **Contracts (Python suite, extending `test_desktop_contracts.py`):**
  - the validator mirror rejects every breakage `validate_result`
    rejects, now including vector, geometry-block and snapshot
    breakages;
  - the vectors, snapshots, regions and terminals the C++ ResultModel
    reports equal `NpzResultStore`'s on real results: a 2D MOSFET, a 3D
    resistor, and a **3D sweep**, which is the only producer of
    `sweep__snapshot__*`.
- **Backend:** each new method's result equals the direct call.
  Exports are byte-compared with the direct `paraview_export` output.
  `band_map`/`recombination_map` arrays are equal (`np.array_equal`) to
  what the refactored viewport path computes.
- **Rendering, with no golden images** (`*.png` is gitignored, and
  golden images would be machine-specific artifacts like the M13
  digests). Deterministic *pixel probes* on offscreen renders instead:
  - orientation: y = 0 at the top and x increasing to the right;
  - colour-map correctness: the pixel colour at a known node equals the
    LUT colour of that node's (log) value;
  - contour and mesh-line presence at known coordinates;
  - slice position.
- **HiDPI:** the pixel probes and hover probes are re-run under
  `QT_SCALE_FACTOR=1.5` and `2`. The render size must equal logical
  size × DPR, and hover must snap to the same node.
- **End-to-end (QTest input simulation on the real widgets):** open →
  select field → log on/off → hover → Fit → dock/undock → quit → reopen
  with the layout restored; open a 3D sweep → play → step → export PVD.
- **Adversarial probes:**
  - corrupt, truncated and schema-99 files;
  - a missing unit;
  - a 1D file opened in the viewer;
  - the backend killed mid-call, which must recover or give a clear
    error, never hang;
  - a result deleted while open;
  - a 2 GB file, where memory must be bounded and the refusal clear.
- **Parity checklist:** every §10.3 feature and every 2D field mode has
  a named test.
- **Invariant:** full suite green, zero new warnings, and the bench
  table re-recorded in this file.

### 15.6 Changes outside `desktop/` that P1 needs

Both are GUI-layer refactors, with no numerical-core change and the
pre-existing tests unchanged.

1. **Move the Qt-free grid builders out of `viewer3d.py`**
   (`build_rectilinear_grid`, `attach_scalar_field`,
   `attach_vector_field`, `extract_isosurface`) into a new Qt-free
   module that `viewer3d.py` and `paraview_export.py` both import.
   - This makes `paraview_export` importable without PySide6 (§3.2).
   - pyvista is imported lazily, inside the export methods only. The
     backend Qt-free test is narrowed to forbid PySide6 and matplotlib,
     and allows pyvista inside `export.*`.
   - Gate: `test_viewer3d.py` and the ParaView export tests are
     unchanged and green, and exported VTU/PVD bytes are identical
     before and after.
2. **Factor the bands/recombination computation** out of
   `MplCanvasItem._observable_fields` / `_draw_bands` /
   `_draw_recombination` into a Qt-free service function.
   - The QML viewport and the backend then call one implementation.
   - Gate: for the MOSFET and a 3D result, the arrays the viewport
     draws are `np.array_equal` before and after. Recorded with the
     reconstruct-and-compare discipline (md5 of the arrays in this
     file, before and after).

### 15.7 Slices, in order

| Slice | Size | Content | Exit |
|---|---|---|---|
| S1 | S | Data layer: full validator mirror, vectors, snapshots, regions, terminals | contract gates §15.5 (data) |
| S2 | S | Performance: profile, then fix §15.4 items 1–2 | 86→≤50 ms, 3.5→≤1 ms, re-measured |
| S3 | M | Shell: ADS docking, layout persistence, recent files, drag-drop, theme tokens (light/dark), info panel, HiDPI gate | e2e shell flow + HiDPI probes |
| S4 | S | C++ `BackendClient` (async, timeouts, restart) + the two §15.6 refactors + new backend methods + npz bulk transport | backend gates + kill-mid-call probe + bulk-transport budget |
| S5 | M | 2D map parity: per-mode colour maps, contours, mesh lines, colour-range lock, bands/recombination maps | pixel probes + parity checklist (2D) |
| S6 | L | 3D parity: slices, isosurface, volume + presets, glyphs/streamlines, playback, exploded view, clipping | pixel probes + parity checklist (§10.3) + §15.4 bench rows |
| S7 | S | Export VTU/PVD + Open in ParaView via the backend | byte-equality with direct export |
| S8 | S | Hardening: adversarial probes, full e2e, bench re-run, plan update | §15.8 |

S4 comes before S5 and S7 because both depend on the backend client.

### 15.8 P1 exit criteria

- Every slice's exit gate has been met.
- Every §6/§15.4 view budget is met on the reference datasets,
  including the 1M-node grids.
- The parity checklist (2D field modes + §10.3) is complete, with a
  test per item.
- Full suite green with zero new warnings; C++ unit tests green; clean
  `/W4` build.
- The bench table is re-recorded here.
- User sign-off.

At that point the native app can replace `viewer3d.py` and the 2D field
views of the QML viewport for looking at results. Per the transition
rule (§9), the QML versions then receive bug fixes only.

### 15.9 Risks specific to P1

| Risk | Mitigation |
|---|---|
| ADS conda build tracks Qt minor versions (5.1.1 needs ≥ 6.11.2) | Pin `qt6-main` and ADS together in the env recipe in `build.ps1` |
| Volume rendering cost at 100³ on weaker GPUs | Budget measured here; P5 adds a GPU-capability check and a fallback (surface/slices only) |
| Bulk npz transport too slow for 1M-node derived maps | Budgeted gate in S4; fallback is shared-memory transport (Qt `QSharedMemory`), only if the gate fails |
| Refactors in §15.6 change QML-GUI behaviour | Bit-identical gates before/after; pre-existing QML tests unchanged |
| Qwt unusable from conda-forge with Qt 6.11 (its builds pin Qt 6.9) | Not needed in P1; confirms the in-house PlotView for P2 (§5.2) |

### 15.10 S1 results (2026-09-25)

**Built.**
- `desktop/src/data/result_model.{hpp,cpp}`: `from_npz` is now the full
  mirror of `validate_result`. It runs the same checks in the same order
  with the same message text: vectors, the v2 geometry block, record and
  trace JSON, terminal pairs, and the sweep, transient and AC blocks.
- New `ResultModel` accessors:
  - `vector_names()` / `vector()`
  - `terminal_names()` / `terminal()`
  - `region_materials()` / `structure_regions()` (parsed JSON)
  - `has_sweep_snapshots()` / `sweep_snapshots()` / `snapshot_field()`
- `desktop/src/data/pyjson.{hpp,cpp}`: reads JSON the way Python's
  `json.loads` does.
  - `NaN` / `Infinity` / `-Infinity` are accepted outside strings.
    `json.dumps` writes these tokens, and nlohmann's strict parser would
    otherwise reject a file Python accepts.
  - `bool` counts as an `int`, as `isinstance` does in Python.
- `tcad_npz_dump` now reports all of the above.

**Like the store, snapshots and region metadata are checked when read,
not when the file opens.** `validate_result` never looks inside them. A
file it accepts therefore opens here too, and the accessor raises where
`NpzResultStore.sweep_snapshots()` / `region_materials()` would.

**Deliberately stricter than Python**, only on inputs no writer produces:
- an integer key holding a non-integer float or a string (Python's
  `int()` truncates or parses it);
- a non-numeric field, vector or series array (Python checks only its
  shape).

These are documented in the header rather than mirrored.

**Gates** (`gui/tests/test_desktop_contracts.py`, now 84 tests):

| Gate | Result |
|---|---|
| Every one of 38 breakages rejected by both, with the same message fragment (taken from Python's own message, asserted on both sides) | pass |
| 8 edge cases accepted by both (NaN/Infinity in `record__meta`, `true` as `dimensionality`, permuted `mesh__shape`, coords without a count, geometry without a kind, no optional blocks, snapshots alongside a sweep, non-ASCII JSON) | pass |
| Vectors (per-component sha256), terminals (value + unit), region metadata and snapshots (voltages, names, shape, per-index sha256) equal `NpzResultStore`'s on solved `diode_1d`, `mosfet_2d`, `resistor_3d` and a **3D sweep** (`resistor_3d` + `SweepSpec`, with `structure_regions` stamped) | pass |
| The same on the store's alternate encodings: numeric snapshot voltages, and `region_materials__meta` | pass |
| 4 lazy-block failures (a snapshot that cannot be reshaped, snapshots with no fields, and two region stamps that are not JSON): both open the file and fail on access | pass |
| C++ unit tests (4 new, for `pyjson`) | 21/21 pass (QtTest totals, which count data rows) |
| Clean `/W4` build | no warnings |
| Mutation check: dropping the NaN/Infinity handling fails `record-nan-inf` and the unit test. Making `snapshot_field` always return snapshot 0 fails the 3D-sweep and alternate-encoding gates. Restored, all pass. | done |

**Not re-measured in S1.** `from_npz` now parses the JSON stamps at
open, so the P0 "open result" time (17.9 ms against ≤100) may have
moved. S2 re-runs the bench.

**Gotcha (cost one build).** moc mis-lexes a C++ raw string literal that
contains `\"`. It then emits no metaobject for the class, and the build
fails at link time with `LNK2001 ... TestData::metaObject`. Use ordinary
escaped literals in any file moc scans.

### 15.11 S2 — Performance: plan (2026-09-25, APPROVED; landed, see §15.12)

**Targets** (fixed at P1 approval, §15.4):
- 2D field switch on the 1000×1000 grid: p95 **86.1 → ≤ 50 ms**;
- 3D hover on the 100³ surface: mean **3.46 → ≤ 1 ms** (p95 also
  reported);
- no other §14.3 row may regress past its target. "Open result" is
  re-measured, because S1 now parses the JSON stamps at open (§15.10).

**What the code does today** (read, not yet measured). One 2D field
switch (`FieldView::rebuildScalars`):
1. `model_->scalar()` decodes the array through `to_doubles()` one
   element at a time: a kind switch and a `storage_index()` call per
   element. The Fortran branch allocates a vector per element.
2. Every value is copied again with `vtkDoubleArray::SetValue`, taking
   `log10` in log mode.
3. `GetRange()` makes a third pass over the data.
4. `grid_->Modified()` re-runs `vtkRectilinearGridGeometryFilter` over
   all 1M points and quads, although the geometry has not changed.
5. `Render()` re-uploads to the GPU.

The 3D hover uses `vtkCellPicker` with no locator, so every pick walks
all ~60k surface cells.

#### Step 0 — measure first (no fix before this)

- **Phase timers in FieldView.** `setField` records decode / fill /
  range / pipeline update / render, and `readoutAt` records pick /
  snap+format. These are kept permanently as bench evidence, not as a
  debug hack; each timer costs microseconds.
- **Bench output** gains `field_switch_phases` and `hover_phases`
  (p50/p95 per phase) and `hover_lookup` p95.
- **Baseline.** Run the bench on all five datasets and record the
  per-phase breakdown here before any fix.

#### Candidate fixes

Each fix goes in only if Step 0 shows its phase matters, and stays only
if that phase's time drops when re-measured.

| # | Fix | Expected effect |
|---|---|---|
| F1 | `to_doubles()` fast path: C-order `<f8` is one `memcpy`; other C-order dtypes use a tight typed loop; Fortran order computes strides once, not per element | decode phase ~10× |
| F2 | Decode straight into the VTK array's buffer (`GetPointer`), and compute min/max during the fill | removes one copy and the range pass |
| F3 | Build the geometry **once per result**; a field switch only swaps the scalar array on the filter output. 3D gathers through `vtkOriginalPointIds` (`vtkDataSetSurfaceFilter::PassThroughPointIdsOn`). 2D keeps the current filter only if its output point order is verified to be the grid order; otherwise it uses the same ids mechanism | removes the 1M-point filter re-run |
| F4 | Only if the render phase dominates: check that VTK re-uploads just the modified scalar array, not positions (VTK's VBO group keys uploads by array MTime) | render phase |
| H1 | `vtkStaticCellLocator` over the extracted 3D surface, built once per result, attached with `picker_->AddLocator()`. Its build time is reported under "open result" | pick ~O(log n) |
| H2 | `vtkHardwareSelector`, only if H1 misses 1 ms | fallback |

#### Correctness gates

A faster path must still show the same numbers.

1. **Scalar equality.** After every field switch, linear and log, 2D and
   3D, the mapper's input scalars must be **bit-identical** to an
   independent reference. The reference is the model's raw values,
   gathered through the original point ids and transformed with the same
   `log10(max(|v|, 1e-30))`.
2. **Hover oracle.** In this slice the 3D view is the device's outer box
   surface, so the correct pick is an analytic ray–box intersection
   through the pixel. Over the bench's 1000 seeded samples, the new
   picker and the oracle must agree on hit/miss and on the snapped node:
   **0 mismatches**. S6's slices and clipping will outgrow this oracle;
   the locator itself carries over.
3. **Stale-state probe.** Open a 3D result, then a different 3D result,
   and re-run the oracle probe. This catches a locator or cached
   geometry left over from the previous result.
4. **Hover-centre strings** are unchanged from §14.3 (e.g. the MOSFET's
   `doping: -1.000e+17 cm^-3 @ x=0.61, y=0.10 um`).
5. **Decode fast path.** The existing contract gate already compares
   `c_order_f64_sha256` against numpy for every dtype and order. Two
   fixture arrays are added so each fast-path branch is covered: a
   Fortran-order 3D `<f8` and a C-order `<f4`.
6. **Mutations.** Each must fail its gate:
   - gather index off by one → gate 1 fails;
   - geometry not rebuilt on a new result → gate 3 fails;
   - `memcpy` used for a Fortran-order array → the contract gate fails.
7. **Wiring into the suite.** A new `tcad_desktop --selftest <npz>` mode
   runs gates 1–4 and exits non-zero on failure. A new
   `gui/tests/test_desktop_selftest.py` runs it on `mosfet_2d`,
   `resistor_3d`, a small synthetic 3D grid, and the two-result
   reopen, and skips when the app is not built. Whether it can render
   under `QT_QPA_PLATFORM=offscreen` is decided in S2 by trying. If it
   can't, the test uses a real window: this machine always has a
   display, and pytest does not run in CI for the desktop app yet.
8. **Invariants.**
   - full fast suite green, zero warnings;
   - C++ unit and contract tests green;
   - clean `/W4` build;
   - §14.3's table re-recorded here with the new numbers beside the old.

#### Out of scope for S2

- §15.4 item 3's new bench rows (slice drag, isosurface, volume,
  playback, streamlines) arrive with the S6 features they time.
- The ADS row arrives with S3.

**Exit.** 1M-node 2D field switch ≤ 50 ms p95 and 100³ hover ≤ 1 ms
mean, both re-measured, with every gate above green.

### 15.12 S2 results (2026-09-25)

**Step 0 found a different bottleneck than the plan guessed.** On the
1000×1000 2D grid, the field switch's p95 split into:

| Phase | p95 (two runs) |
|---|---|
| decode | 4.6–5.4 ms |
| fill | 2.4–2.8 ms |
| range | 2.2–2.4 ms |
| pipeline update | 41–47 ms |
| render | 66–70 ms |

The totals were 114.8 and 121.8 ms; P0 recorded 86.1 ms, a run-to-run
spread this PC shows throughout. The 3D pick alone was 10–12 ms p95,
3.6–4.2 ms mean.

**What landed:**
- **F1** decode fast path (`NpyArray::to_doubles`): C-order `<f8` is one
  `memcpy`, and Fortran order walks storage once with a carried index.
- **F3** geometry once per result (`FieldView::setResult`): a
  `tcad_node_id` point array rides through the geometry filter. A field
  switch then gathers values into the displayed points, and the colour
  range is still taken over every node, as in P0.
- **H1** a `vtkStaticCellLocator` over the displayed 3D surface, built
  per result.

The render phase fell from 66 to 11 ms with F3 alone: most of it was
VTK rebuilding GPU buffers for re-extracted geometry. **F4 and H2 were
therefore not needed.** F2 was folded into F1/F3: the gather writes
straight into the VTK buffer.

**Bench, same PC, native only** (`run_bench.py --native-only`), p95 in
ms unless stated:

| Dataset | Metric | Before S2 | After S2 | Target | Status |
|---|---|---|---|---|---|
| synthetic 2D 1000×1000 | field switch | 114.8–121.8 | **17.4** | ≤ 50 | met |
| synthetic 3D 100³ | hover, mean | 3.65–4.20 | **0.010** (p95 0.016) | ≤ 1 | met |
| synthetic 3D 100³ | field switch | 15.7–21.1 | 8.3 | ≤ 200 | met |
| mosfet_2d | field switch | 5.5–8.2 | 3.6 | ≤ 50 | met |
| resistor_3d | field switch | 3.3–5.3 | 3.8 | ≤ 200 | met |
| all | pan / zoom / orbit | ≤ 4.9 | ≤ 5.0 | ≤ 16.7 | met |
| mosfet_2d | open result | 21.4–32.8 | 20.0 | ≤ 100 (files ≤ 1 MB) | met |
| synthetic 2D / 3D (8–16 MB files) | open result | 276 / 135–156 | 221 / 158 | outside the §6 budget's size class | reported |

Open-result now includes the geometry extraction and the locator build.
The 1M-node files are outside §6's "≤ 1 MB" budget; their numbers are
recorded, not gated. The MOSFET hover-centre readout is unchanged from
§14.3 (`doping: -1.000e+17 cm^-3 @ x=0.61, y=0.10 um`).

**Gates** (`tcad_desktop --selftest`, driven by
`gui/tests/test_desktop_selftest.py`):
- Every displayed point sits on its node: exact on all five files,
  including all 1M points of the 2D grid.
- Scalars are bit-identical to a fresh decode, and the colour range is
  bit-identical to P0's `GetRange` method: 28/28 field × scale checks.
- The 3D hover matches the analytic ray–box oracle: 0 mismatches in
  3000 samples over three 3D files.
- The stale-state sequence (2D → 3D → a 3D of different geometry → 2D)
  passes.
- Contract fixtures now cover each decode branch: Fortran 3D `<f8`,
  Fortran 4D `<f4`, C 3D `<f8`.

**Finding: P0's brute-force picker was slightly wrong at silhouettes.**
Its 0.0005 tolerance registered hits up to about 0.7 px outside the
device: 1 of 1000 samples on `resistor_3d`, 2 of 1000 on the 100³
grid. The locator and the oracle agree those are misses. The gate is
therefore the oracle. A disagreement with the brute-force picker passes
only when the oracle sides with the locator, and all 3 did.

**Mutations**, each caught by its gate, then restored:
- gather reads the neighbouring node → thousands of mismatched values
  in every linear-mode row;
- geometry kept from the first result → 6712 node ids out of range in
  the second file;
- `memcpy` used for Fortran-order `<f8` → the `fortran_2d` contract
  sha256 differs.

**Invariants:**
- full fast suite: 2190 passed, 35 skipped, 2 xfailed, zero warnings;
- clean `/W4` build;
- C++ unit tests pass.

**Found and fixed along the way:** under `QT_QPA_PLATFORM=offscreen` the
viewer never gets a GL context, and `--bench` / `--selftest` spun
forever waiting for one. `wait_for_gl()` now fails after 10 s naming
the cause, and a test gates this. The viewer's gates therefore need a
real window: the selftest test briefly opens one.

**Gotcha: this machine's Bash tool collapses a doubled backslash into
one, even inside a quoted `<<'EOF'` heredoc.** A Python patch script
written that way twice put a real newline where the two characters
backslash-n were meant, and this paragraph's own first draft lost its
backslashes the same way. Edit C++/Python string escapes with the Edit
tool, not heredoc scripts.

### 15.13 S3 — Shell: plan (2026-09-25, reviewed; landed, see §15.14)

**Review revisions** (made before any S3 code; each overrides the text
below where they differ):
1. **HiDPI size.** This PC's screen is 1920×1080 at 100%. A 1200×800
   view at 2× is 2400×1600 device pixels, which Windows would clamp, and
   the gate would then measure the clamp. The selftest, bench and e2e
   gain `--size WxH`, and the HiDPI runs use **600×360 logical** (1200×720
   device at 2×, which fits with the window chrome).
2. **Colour maps are data, not theme.** The viridis table in
   `field_view.cpp` is a hex/float colour table the no-hard-coded-colours
   scan would flag. Colour maps move to `src/views/colormaps.{hpp,cpp}`,
   exempt from the scan with its reason stated. The scan covers
   everything else in `src/`.
3. **Theme tokens must be Qt-free** (`src/theme/tokens.hpp`: constexpr
   hex strings per token and scheme). The drift test then compares
   against `Theme.qml` through a small tool (`tcad_theme_dump`) that
   needs no window. The Qt palette and VTK colours are built from those
   tokens in `src/theme/theme.cpp`.
4. **The info contract compares `solved_bias` itself**, not
   `is_solved_result()`, which `NpzResultStore` hard-codes to `True` and
   so would test nothing.
5. **Recent files de-duplicate case-insensitively.** Windows paths are
   case-insensitive, and `canonicalFilePath()` does not normalise case.
6. **"System" theme is tested through Qt, not the OS.**
   `QStyleHints::setColorScheme()` (Qt ≥ 6.8; `tcad-gui` has 6.11.2)
   emits the same `colorSchemeChanged` that an OS switch does.
7. **Build structure.** The e2e test executable needs the shell and
   views, which today are compiled only into `tcad_desktop`. They move
   to a static library, `tcad_desktop_ui`, that the app, the selftest
   and `tcad_desktop_shell_tests` all link. There is one copy of the
   code; the app's behaviour is unchanged.
9. **Found by S3a's screenshot, and assigned to S5, not S3.** Since P0,
   the scalar bar has been drawn over the device: Fit uses the whole
   view, so the map runs under the bar. The bar's title also overlaps
   its top tick label. S5's 2D map parity must reserve the bar's width
   when fitting and lay the title out clear of the labels, with a pixel
   probe for each.
8. **Dock-state restore is gated structurally first.** Equal
   `saveState()` bytes is the strict form. If ADS turns out to write
   something run-dependent (a floating window's screen position, say),
   the gate falls back to comparing the decoded structure: which panels,
   where, visible or not. That change would be recorded, not made
   silently.

The goal is to turn the P0 spike window into the real shell. It must
not change what S1/S2 made correct and fast: `--selftest` and the bench
rows are re-run at the end.

**Facts checked before planning:**
- **Docking package.** `qt6-advanced-docking-system` 5.1.1 (conda-forge)
  resolves into `tcad-gui` as **one new package**, with nothing upgraded
  or downgraded (dry run, 2026-09-25). That is the check the
  `tcad-dev` compiler incident (CLAUDE.md) says to make first. Licence:
  LGPL-2.1, already cleared in §7.3.
- **`solved_bias` is a bool:** a bias solve vs equilibrium only. **The
  applied voltages are not in the result file**; they live only in the
  job's DeviceSpec. The info panel therefore shows "bias solved:
  yes/no". Showing voltages would need a result-grammar addition, which
  is out of S3's scope and listed as a follow-up.
- **`record__meta`** carries backend, `created_utc`, material, T, models
  and numerics, so the panel can show provenance.
- **Today's shell** (`src/shell/main_window.cpp`) has:
  - one `QDockWidget` (Fields), the FieldView as central widget,
    Open/Quit/Fit/Log actions, and the readout in the status bar;
  - no settings, recent files or drop support;
  - a dark palette hard-coded in `main.cpp`.

#### Steps, in order

| Step | Content | Exit |
|---|---|---|
| S3a | **Docking.** Install ADS into `tcad-gui` and pin it with `qt6-main` in `build.ps1` / README. Replace `QDockWidget` with `ads::CDockManager`. The FieldView is the dock manager's **central widget**, so it never floats: a floating native GL widget is reparented, which risks losing its GL context. Fields and Info are dock panels; View menu toggles for each; "Reset layout". | builds clean; `--selftest` and bench unchanged; ADS DLL found through `desktop_runtime.json` |
| S3b | **Settings, layout, recent files, drag-and-drop.** One settings object, `QSettings` in INI format. `--settings <file>` isolates tests from the user's real settings. Save window geometry + dock state + a layout version on close, and restore on start. Recent files: at most 10, de-duplicated by canonical path; a missing file is removed on use, with a message. One `tryOpen(path)` serves the command line, File > Open, Recent and drop. A failed open shows the error and **keeps the current result on screen**. | layout and recent files survive a restart; adversarial probes below |
| S3c | **Theme tokens.** A `Theme` (C++) with light and dark token sets. Where a token exists in both apps, its value is taken from `gui/qml/Theme.qml`'s opaque tokens (background, text, textDim, border, accent, ...), so the two apps look alike. One source drives the Qt palette (Fusion), the ADS stylesheet colours, VTK's background, scalar-bar title/label colours and the readout. Menu View > Theme > System / Light / Dark, persisted. "System" follows `QStyleHints::colorScheme()` and switches live. | theme gates below |
| S3d | **Result info panel.** Shows the file (name, size), schema, dimensionality, node counts, geometry kind, fields with units, vectors, terminals (value + unit), bias solved, run record (backend, created, material, T, enabled models) and sweep/transient/AC/snapshot presence with point counts. New `ResultModel` accessors: `solved_bias()`, `record()` (parsed JSON), and series lengths. | contract gate below |
| S3e | **HiDPI.** Run the selftest and the shell e2e under `QT_SCALE_FACTOR` = 1, 1.5 and 2. | HiDPI gates below |
| S3f | **Shell end-to-end.** A new Qt Test executable, `tcad_desktop_shell_tests`, drives the real `MainWindow` with QTest input. `gui/tests/test_desktop_shell.py` runs it and skips when the app is not built. Like the selftest, it needs a real window. | e2e gates below |

#### Gates

- **Contracts (S3d).** The info view `tcad_npz_dump` reports equals, on
  real solved results (1D, 2D, 3D, 3D sweep):
  - `NpzResultStore.run_record()` (backend, created_utc, material, T,
    models);
  - `is_solved_result`;
  - the store's series lengths.
- **Theme (S3c):**
  - Every token defined in both apps is equal in value. A test reads
    `Theme.qml` and the C++ tokens (dumped by a tool), so drift fails
    the suite.
  - **No hard-coded colours outside the theme.** A source scan fails on
    any `QColor(`, `setRgb`, `SetBackground(`, `SetColor(` or hex
    literal in `src/` outside `src/theme/`. This is the QML GUI's
    Phase 3/4 review finding, made a gate.
  - Switching light ↔ dark changes the palette, VTK's background and
    the scalar bar's text colour, all read back from the live objects.
- **Shell e2e (S3f), on real widgets:**
  - open via a synthesized drop event;
  - select a field by clicking the list;
  - toggle log;
  - hover with `QTest::mouseMove`: the status bar equals `readoutAt` for
    the same point;
  - Fit shortcut;
  - float and re-dock the Fields panel, after which the FieldView still
    renders (a frame is read back and is not blank);
  - close → a new `MainWindow` on the same settings file restores the
    same dock state (equal `saveState()` bytes), the geometry and the
    recent-files list;
  - theme switch.
- **Adversarial probes (S3b/f):**
  - a corrupt dock-state blob, and a future layout version, in the
    settings file → default layout, no crash;
  - drop a non-`.npz` file, two files, a missing file, a corrupt `.npz`,
    or a schema-99 file → a named error, and the previous result stays
    on screen;
  - a recent-files entry whose file was deleted → removed, with a
    message;
  - a result in a directory with non-ASCII characters (`µm`, `€`,
    emoji) opens, because `NpzFile::open` takes a wide path;
  - a read-only settings file → the app still runs, and says the layout
    could not be saved.
- **HiDPI (S3e), at 1, 1.5 and 2:**
  - render-window size = logical size × DPR;
  - `--selftest` green (its hover oracle already uses the DPR);
  - the MOSFET hover-centre readout identical at every scale;
  - the e2e hover check green.
- **Performance** (the §15.4 row fixed at approval):
  - ADS float/re-dock ≤ 100 ms;
  - layout restore ≤ 100 ms, measured by new bench rows;
  - cold start stays ≤ 1000 ms with ADS loaded;
  - the S2 rows do not regress.
- **Invariants:**
  - full fast suite green with zero warnings;
  - clean `/W4` build and C++ unit tests green;
  - `--selftest` green;
  - results recorded here as §15.14.

#### Out of scope for S3

- more than one result open at a time (P1 views one result, as P0
  does);
- showing applied bias voltages (needs a grammar addition);
- shortcut customisation;
- the installer (P5);
- 2D colour-map choices and range lock (S5).

#### Risks

| Risk | Mitigation |
|---|---|
| A native GL widget loses its context when reparented by docking | FieldView stays the central widget (never floats); the e2e float/re-dock check reads a frame back afterwards |
| ADS stylesheet fights the Qt palette | ADS colours are generated from the same theme tokens; the theme gate reads them back |
| Fractional DPR (1.5) rounds widget sizes, so hover lands one device pixel off | The render-size gate and the selftest's DPR-aware oracle at 1.5 |
| Tests touching the user's real settings or registry | `--settings <file>` in every test; the default location is used only by a normal launch |
| e2e tests need a real display | Same as the selftest (§15.12): skip when not built; the offscreen failure is already a clear error |

**Decisions with a default (say if you want otherwise):**
- colours follow `gui/qml/Theme.qml`;
- the default theme is **System**;
- settings are an INI file under the user's app-data folder, not the
  registry, so users and tests can read, reset or delete it.

### 15.14 S3 results (2026-09-25)

**Built**, as planned (§15.13 with its review revisions):

| Step | What landed |
|---|---|
| S3a | ADS 5.1.1 docking. It was installed into `tcad-gui` as exactly one new package (the environment's explicit package list gained one line, nothing else changed) and pinned with Qt in README/`build.ps1`. The FieldView is the fixed central dock. The shell and views moved to a `tcad_desktop_ui` static library. |
| S3b | `AppSettings`: an INI file, `--settings <file>`, ephemeral for `--bench`/`--selftest`. Layout + geometry persist, with a version stamp: now 2, bumped when the Info panel joined. Recent files: 10, case-insensitive de-duplication. One `tryOpen()` for the command line, menu, recent files and drop. Errors show in a non-modal box and the current result is kept. |
| S3c | Qt-free theme tokens (`src/theme/tokens.hpp`) mirroring `Theme.qml`; the Fusion palette; ADS's stylesheet rewritten with token colours; VTK background + scalar-bar text; View > Theme > System/Light/Dark, persisted, System followed live. Colour maps moved to `src/views/colormaps`. |
| S3d | `InfoPanel`: file, mesh, fields, vectors, terminals, run record, blocks. New `ResultModel` accessors: `solved_bias()`, `record()`, `geometry_kind()`, point counts. |
| S3e | `--size WxH`; a render-size check and a 2D node round-trip hover check in `--selftest`. |
| S3f | `tcad_desktop_shell_tests` (24 Qt Test functions) driving the real window, run by `gui/tests/test_desktop_shell.py`. |

**Found and fixed**, each gated and each gate checked against the bug:

1. **A result in a directory with an emoji in its name would not open**
   (a P0 bug). `NpzFile::open` built its message label with
   `path.string()`, which converts to the ANSI code page and *throws* for
   a character outside it. The file itself opened fine through the wide
   path. Now UTF-8 (`u8string`). The same was fixed in the DeviceSpec
   document's error paths.
2. **"Reset layout" left a 60 px Fields panel.** It replayed a state
   captured before the first show, whose splitters were 0 px. Reset now
   rebuilds the default arrangement, with Fields 240 px wide.
3. **The light theme drew the Fields panel stock grey (`#787878`).**
   - ADS paints from `palette(light)`, a role the palette never set.
   - After that fix, a *startup* theme (the saved choice) still showed
     stock palettes, because ADS polished its widgets before the theme
     applied.
   - Final fix: ADS's own stylesheet is rewritten with explicit token
     colours on every scheme change. Nothing depends on polish timing.
   - The live-switch test had passed throughout. It compared the palette
     and a panel pixel whose light value happened to equal stock white.
     The added startup gate reads back painted pixels from a clean
     palette, and it fails on each of the two earlier orderings.
4. **The colour-scan's hex pattern missed colours inside a stylesheet
   string.** Its self-check on known-bad snippets caught this before
   the scan was trusted. It now also has known-good snippets
   (`#include`, `#define`) that must not be flagged.
5. **One plan gate was ill-posed.** "The MOSFET hover-centre readout is
   identical at every scale" can legitimately flip: the view centre sits
   exactly between two nodes (§14.3). It was replaced by a node
   round-trip: 200 interior nodes are projected to logical pixels at
   each scale, and the hover there must name that exact node.

**Gates:**

| Gate | Result |
|---|---|
| Shell e2e (`test_shell.cpp`) | 24/24 functions pass. They cover opening, drop, recent files, restart persistence, corrupt and other-version layouts, read-only settings, a non-ASCII path, float/re-dock with the frame read back, field list, log, hover → status bar, Fit, info panel, live and startup themes, and System following the colour scheme |
| Info contract | `npz_dump`'s info equals the Python side on 4 solved results and a file with every block, including `solved_bias` truthiness (`False`, `True`, `"{}"`) |
| Theme drift | 16 tokens mirror `Theme.qml` exactly, 3 of them by RGB of a translucent panel; `onAccent` has no twin |
| No hard-coded colours | clean; the self-checks pass |
| HiDPI at 1, 1.5, 2 | render size = logical × DPR (e.g. 900×540 for 600×360 at 1.5); 0 node mismatches in 200 probes; 3D oracle 0 mismatches; shell view tests pass |

**Mutations**, each caught, then restored:
- a failed open drops the current result → the corrupt and schema-99
  rows fail;
- case-sensitive recent de-duplication → the dedupe test fails;
- theme applied after the widgets → both startup rows fail;
- no `Light` role → the painted-panel check fails with exactly
  `#787878`;
- `readoutAt` ignores the DPR → the selftest and shell tests fail at 1.5
  and 2, and pass at 1;
- P0's literal VTK background → the colour scan names the line.

**Performance** (this PC; p95 ms):

| Row | Result | Target |
|---|---|---|
| dock float + re-dock | 30.1–32.1 | ≤ 100 |
| layout restore | 49.4–81.5 (the 1M-node 2D grid is the slowest: the view re-renders after the resize) | ≤ 100 |
| cold start to first frame | 485–706 (with ADS loaded) | ≤ 1000 |
| 2D 1M field switch / 3D 100³ hover | 15.0 / 0.009 mean — no S2 regression | ≤ 50 / ≤ 1 |

**Honest limits:**
- **Drag-and-drop** is tested with synthesized drag/drop events sent to
  the window, not an OS-level drag from Explorer.
- **"System" theme** is tested through
  `QStyleHints::setColorScheme()`, not a real Windows light/dark
  toggle.
- **HiDPI** runs through `QT_SCALE_FACTOR` on this PC's 1920×1080 at
  100% display. No physical HiDPI monitor was used.
- **Real display needed.** The shell, selftest and HiDPI tests require
  one (the viewer needs a GL surface). Under
  `QT_QPA_PLATFORM=offscreen` they fail fast with a clear error.
- **Expected warning.** ADS logs `qUncompress: Input data is corrupted`
  (a Qt Test `QWARN`, not a pytest warning) for the deliberately
  corrupt saved layout.
- **Real settings file created.** Checking the default settings
  location wrote `%APPDATA%\PyTCAD\PyTCAD Desktop.ini` on this PC. That
  is the documented location, and it is safe to delete.

### 15.15 S4 — Backend client, refactors and bulk transport: plan (2026-09-25, reviewed; landed, see §15.16)

**Review revisions** (measured on this PC before any S4 code; each one
overrides the text below where they differ):

1. **The pipe is not UTF-8.** A piped stdin on Windows decodes with the
   ANSI code page (cp1252). The probe sent `{"path": "µm-€-😀"}` as raw
   UTF-8, and Python read a 12-character mojibake string. A result in
   a non-ASCII directory, or under a non-ASCII user profile
   (`C:\Users\Jürgen\...`), would fail with "file not found". The same
   JSON with `\u` escapes arrived intact. Fix on both sides:
   - the client sends ASCII-escaped JSON (nlohmann `ensure_ascii`);
   - the service reconfigures stdin/stdout to UTF-8 at start;
   - gate: `analysis.band_map` on a result in an emoji-named directory,
     through the C++ client.
2. **CRLF.** Python's text-mode stdout on Windows writes `\r\n`. The
   client's line framing strips a trailing `\r`, and a fake backend
   emits CRLF on purpose.
3. **Launching `tcad-dev`'s interpreter directly works, and loads
   nothing from `tcad-gui`.**
   - Probe: unactivated, even with `tcad-gui\Library\bin` first on PATH
     (as the launcher gives the app), the process imported numpy,
     scipy, pyvista/VTK, `pytcad._core` and the result store.
   - It loaded 485 DLLs, **0** from `tcad-gui` (`EnumProcessModules`).
   - Still, the client strips the app's runtime directory from the
     child's PATH (the result should not rest on Python's DLL-search
     rules).
   - A debug-only `debug.loaded_modules` lets the client test assert
     that none of the backend's DLLs come from outside its own prefix.
     That is the check the `tcad-dev` PySide6 incident (CLAUDE.md)
     says to make.
4. **One request in flight at a time, queued in the client.** The
   service is sequential, so a timer started at *send* for a request
   queued behind a slow one would time it out and kill a healthy
   service. The client therefore keeps its own FIFO, writes the next
   request only when the previous one has answered, and starts each
   call's timer when that call is written. "20 concurrent calls" in the
   gates below means 20 queued calls, answered in order.
5. **The backend exits on stdin EOF.** If the app dies, the pipe closes,
   `serve()` returns, and its `finally` removes the scratch directory.
   Gate (Python): close the service's stdin → it exits within 2 s, and
   the scratch directory is gone.
6. **1D is allowed.** A band or recombination map of a 1D result is a
   valid 1D result file, which P2's curves will use. The "1D result for
   a map" probe below is replaced by "a result missing a required field
   (for example no `doping` for recombination) → the error names it".
7. **`band_maps(store, names=None)` computes only the maps asked for.**
   The QML viewport's 2D mode asks for `["Ec"]`, so it gains no extra
   `log` work per repaint. The arrays it draws stay bit-identical, which
   refactor 2's gate checks.
8. **Re-reading the source result on every call is measured, not
   assumed away.** `NpzResultStore` loads the whole file; a 1M-node
   result costs about 0.2 s. A one-entry cache keyed on (path, size,
   mtime) is added only if the end-to-end numbers call for it.

S4 connects the native app to Python. It covers:
- the C++ `BackendClient`;
- the two GUI-layer refactors (§15.6);
- the four new service methods (§15.3), with results carried as `.npz`.

Using the maps in the viewer is S5, and the export UI is S7. S4 delivers
the plumbing and proves it: correct, fast enough, and it never hangs.

**Facts checked before planning:**
- **The service** (`backend_service/server.py`, 138 lines):
  - five methods;
  - **single-threaded and sequential**: a long call blocks every
    request behind it, pings included. The client therefore detects a
    hang by timeout, not by pinging;
  - stdout is protected; results with NaN are refused.
- **`paraview_export.py`** takes its grid builders from `viewer3d.py`,
  which imports PySide6 and `pyvistaqt` at module level. So today the
  backend cannot export without loading Qt.
- **`export_vtu` is byte-deterministic.** Two exports of the same
  resistor gave identical md5s (checked 2026-09-25), so export gates can
  compare bytes.
- **The QML viewport's 2D "bands" draws E_c only**, computed inline as
  `-psi - chi`. 1D uses `workbench.analysis.observables.band_diagram`,
  whose `Ec` is the **same expression**, so moving 2D onto it is exact.
  `band_diagram` and `recombination_rate` are element-wise, so they also
  give **3D maps**, which the QML viewport never had ("a later
  version").
- **Material and T** come from the run record (default SILICON / 300 K)
  — one material for the whole device. The existing heterostructure
  limitation is carried over unchanged and stated in the method
  docstrings, not fixed here.
- **The backend's Python is `tcad-dev`**, not `tcad-gui`. The app must
  be told where it lives.
- **The current Qt-free test** forbids `pyvista` outright. It is
  narrowed below.

#### Steps, in order

| Step | Content |
|---|---|
| S4a | **Refactor 1 — Qt-free grid builders.** `build_rectilinear_grid`, `attach_scalar_field`, `attach_vector_field` and `extract_isosurface` move verbatim to a new `gui/services/grid_builders.py` (pyvista only). `viewer3d.py` re-imports them under the same names, so no caller or test changes. `paraview_export.py` imports from `grid_builders`. |
| S4b | **Refactor 2 — observable maps.** `MplCanvasItem._observable_fields` moves to `gui/services/observable_maps.py` as `observable_inputs(store)`. New `band_maps(store)` returns `band_diagram`'s Ec/Ev/EFn/EFp in field shape, and `recombination_map(store)` returns R. The viewport's 2D bands draw `band_maps(...)["Ec"]`; its recombination draws `recombination_map(...)`. |
| S4c | **Service methods and bulk transport.** Adds `analysis.band_map`, `analysis.recombination_map`, `export.vtu` and `export.pvd` (§15.3). Each derived map is written as **a valid result file**: the source's axes, `field__<name>` + `unit__<name>`, `result__schema`, `solved_bias` and `dimensionality`. So the C++ side reads it through the same conformance-gated `NpzFile` + `ResultModel`, with no second format. Files go to a scratch directory owned by the service: `system.ping` reports it, and shutdown removes it. Each result carries `timings` (load / compute / write, in ms). `debug.sleep` and `debug.exit` exist **only** when `TCAD_BACKEND_DEBUG=1`, for the hang and crash probes; otherwise they are "method not found". |
| S4d | **C++ `BackendClient`** (`src/backend/`, Qt Core only). See the design below. |
| S4e | **Tests and bench** (gates below). |

#### `BackendClient` design

- **Process.** A `QProcess` runs `<python> -m backend_service` with the
  `pytcad/` directory as its working directory. `<python>` resolves in
  this order:
  1. the `TCAD_BACKEND_PYTHON` environment variable;
  2. the settings key `backend/python`;
  3. `backend_python` in `desktop_runtime.json`, which `build.ps1`
     fills with `tcad-dev`'s interpreter.

  A missing interpreter is a clear error, not a hang.
- **Lazy start.** The process starts on the first call, never before
  the first frame: cold start is unaffected. After starting, a
  `system.ping` handshake checks `protocol == 1`. A mismatch refuses to
  proceed, naming both versions.
- **Async API.** `call(method, params, timeout_ms)` returns a
  `BackendReply*` that emits exactly one of `finished(result)` or
  `failed(code, message)`.
  - Replies are matched by request id; responses are line-delimited
    JSON parsed with nlohmann.
  - A malformed or unmatched line fails the call it concerns, or is
    logged; it never crashes the client.
  - The last 200 lines of stderr are kept for error messages.
- **Timeouts.** Each call has a timer. Because the service is
  sequential, a timeout means it is stuck, so the client:
  1. kills it;
  2. fails the timed-out call ("timed out after N ms");
  3. fails every other pending call ("backend restarted");
  4. starts a fresh process on the next call.
- **Crash detection.** `QProcess::finished` or `errorOccurred` fails
  every pending call with the exit code and the stderr tail. Restarts
  back off: 3 crashes within 30 s → the client reports "backend keeps
  crashing" and stops restarting until asked.
- **Shutdown.** On app exit the client sends `system.shutdown`, waits
  at most 2 s, then kills. The client then removes the service's
  scratch directory if it is still there, which covers a service that
  died without cleaning up.

#### Gates

- **Refactor 1**, by the reconstruct-and-compare discipline:
  - `test_viewer3d.py` and the ParaView export tests are unchanged and
    green;
  - the md5 of `export_vtu` and of every file from `export_pvd_series`
    is recorded **here before the move** (resistor_3d; the 3D sweep
    fixture) and must be byte-identical after;
  - in a subprocess, `import gui.services.paraview_export` succeeds with
    PySide6 and `pyvistaqt` made unimportable.
- **Refactor 2**, by the same discipline:
  - for `mosfet_2d` and `diode_1d`, the md5 of the arrays the viewport
    draws (2D Ec and R; 1D Ec/Ev/EFn/EFp and |R|) is recorded here
    before the edit and must be equal (`np.array_equal`) after;
  - a mutation (for example `band_maps` returning `Ev` as "Ec") must
    fail the gate;
  - the existing viewport tests are unchanged and green.
- **Service** (`test_backend_service.py`):
  - each new method's arrays `np.array_equal` the direct call to
    `observable_maps`;
  - each derived-map file passes `validate_result` and opens in the
    C++ `ResultModel` (`npz_dump`);
  - `export.*` output is byte-identical to calling `paraview_export`
    directly;
  - the scratch directory exists while the service runs and is removed
    after `system.shutdown`;
  - `debug.*` is absent without the environment variable;
  - bad parameters (a missing file, a 1D result for a map, an unknown
    field) give named errors, and the service keeps serving.
- **Qt-free, precisely.** After start and ping, none of PySide6,
  matplotlib or pyvista is loaded. After `export.vtu`, PySide6 and
  matplotlib are still not loaded; pyvista is allowed.
- **Client** (`tcad_desktop_backend_tests`, a Qt Test executable driving
  the real service; `gui/tests/test_desktop_backend.py` runs it):
  - ping/handshake; `examples.list` equals Python's;
  - 20 concurrent `call`s all come back matched to the right ids;
  - `band_map` → `NpzFile` → `ResultModel` round trip on the MOSFET;
  - **timeout**: `debug.sleep 5` with a 300 ms timeout fails in ≤ 1 s,
    the process is replaced, and the next ping succeeds;
  - **kill mid-call**: the process is killed during `debug.sleep`, and
    the pending call fails in ≤ 1 s naming the exit;
  - `debug.exit` gives the same;
  - the three-crash backoff;
  - **fake backends** (small Python scripts standing in for the
    service): garbage output, a never-answering process, an immediate
    exit, a wrong protocol version, a 10 MB single line. Each gives a
    named failure, and none hangs or crashes;
  - a missing interpreter is a clear error;
  - shutdown leaves no process and no scratch directory.
- **Bulk-transport budget** (the §15.3 gate, measured by a new bench
  mode `tcad_desktop --bench-backend <npz>`):
  - on the 1000×1000 grid, write + read of a one-field derived map
    (R: the service's `write` timing plus the C++ `NpzFile::open` +
    `ResultModel`) ≤ 150 ms;
  - also reported, not gated: the 4-field band map; end-to-end call
    latency, including the service loading the source result;
    `QSharedMemory` is the named fallback only if the gate fails.
- **Invariants:**
  - full fast suite green with zero warnings;
  - clean `/W4` build;
  - `--selftest` green;
  - results recorded as §15.16.

#### Out of scope for S4

- Showing maps in FieldView (S5).
- The export UI and "Open in ParaView" (S7).
- Running solves through the service (P3).
- Cancelling a call without restarting the service. The sequential
  service cannot be interrupted, so this waits for P3's job model.

#### Risks

| Risk | Mitigation |
|---|---|
| The service's cold import (numpy, workbench) makes the first call slow | Measured and reported. The lazy start could become "start at idle after the first frame" if the first-call latency annoys, but that is decided with numbers |
| Pipe buffering hides a line or splits it | Line-framed parsing with a buffer; the fake-backend tests include a line split across writes and a 10 MB line |
| Windows file locks on the scratch `.npz` (reader still open while the service deletes it) | `NpzFile` reads eagerly and keeps no handle (P0), and the client deletes after reading |
| A hung numerical call (a huge map) is mistaken for a hang | Per-method default timeouts sized from the bench numbers; the caller can raise them |

**Decision with a default (say if you want otherwise):** the backend
interpreter is found through `desktop_runtime.json` (`tcad-dev`) for dev
builds. The P5 installer will bundle its own and set the same key.

#### S4 pre-edit baseline (recorded 2026-09-25, before any S4a/S4b edit)

These were captured by the S4 baseline script. It solves the fixtures
once and keeps the files, so the after-edit run reads the same inputs.

Inputs (md5 of the `.npz`):

| File | md5 |
|---|---|
| diode_1d | `0723756fa478a8258032643fcf78bfd2` |
| mosfet_2d | `56247ba4b4ac3d595c9998a042001547` |
| resistor_3d | `aeef36fd3dd2f90606c4f697f9afa39a` |
| resistor_3d_sweep | `0affc8524cb712ab1903587af1355b9d` |

Arrays the QML viewport draws: md5 of the C-order `<f8` bytes, taken
from `MplCanvasItem._series` / `_field_grid` after `renderToImage()`.

| Case | Array | md5 |
|---|---|---|
| diode_1d / bands | Ec (240,) | `d16b729da512015bd10d485729b6fa09` |
| | Ev (240,) | `d705631ea67b488e8cea3928d2695550` |
| | EFn (240,) | `d5a55d4ac3950f07aee2baca76d67813` |
| | EFp (240,) | `2872c567a343d0a1e8cb808bf7b6692a` |
| diode_1d / recombination | \|R\| (240,) | `5fa88a90a5eeb9f21e7d253114e3edaa` |
| mosfet_2d / bands | Ec (55, 136) | `7fbbb5acf3b4dd0e6be0e04babdcac81` |
| mosfet_2d / recombination | R (55, 136) | `4c8b83447a3d851090d2b641063fac71` |
| mosfet_2d (both modes) | x (136,), y (55,) | `9fd46496c7a67c09633b37690039591b`, `b70bacdeaf9183a06d9afe2ba3d2c9de` |

Export files (md5 of the bytes written):

| File | md5 |
|---|---|
| `export_vtu(resistor_3d)` | `4e5f7e8491d819aae18bb14ec0930015` (the same as the earlier determinism probe) |
| `export_pvd_series` sweep.pvd | `a886d5884ab78edb86c8837680d9a5d2` |
| sweep_0.vtu | `5c7e505ae4ea9850b87642339355e915` |
| sweep_1.vtu | `867724b32e0a68d5a85d1cf5615e4677` |
| sweep_2.vtu | `85d38d07be4aaec3436e51028f57c68e` |

### 15.16 S4 results (2026-09-25)

**Built** (§15.15 with its review revisions):

| Step | What landed |
|---|---|
| S4a | `gui/services/grid_builders.py`: the four grid builders, moved verbatim (5,185 bytes). `viewer3d.py` re-imports them under the old names; `paraview_export.py` imports from the new module. CRLF kept (small diff). |
| S4b | `gui/services/observable_maps.py`: `observable_inputs`, `band_maps`, `recombination_map`, `missing_fields`. The QML viewport's `_observable_fields`, its bands (1D and 2D) and its recombination (1D and 2D) all call it. |
| S4c | Service methods: `system.info`, `analysis.band_map`, `analysis.recombination_map`, `export.vtu`, `export.pvd`, and the `debug.*` probes (only with `TCAD_BACKEND_DEBUG=1`). Maps are written as result files in a scratch directory, removed on shutdown *and* on stdin EOF. Pipes are UTF-8 with `\n` line endings. A missing file gets a clear "result file not found" error. |
| S4d | `desktop/src/backend/backend_client.{hpp,cpp}` (Qt Core only, as designed in §15.15). `desktop_runtime.json` gains `backend_python` (`tcad-dev`, found by `build.ps1`) and `backend_root`. |
| S4e | `tcad_desktop_backend_tests` (22 Qt Test cases, including 6 fake-backend rows), `desktop/tests/fake_backend.py`, and `tcad_desktop --bench-backend`. |

**Refactor gates** (reconstruct-and-compare against the pre-edit md5s
recorded above, on the same input files):

| Gate | Result |
|---|---|
| S4a export bytes (`resistor.vtu`; `sweep.pvd` + 3 `.vtu`) | identical |
| S4b viewport arrays (1D Ec/Ev/EFn/EFp and \|R\|; 2D Ec, R, x, y) | identical |
| S4b mutation (`BAND_NAMES` order swapped, so "Ec" gets Ev) | caught in 1D and 2D bands; restored |
| Existing tests: `test_viewer3d`, `test_paraview_export`, 6 viewport files, `test_m3_observables`, `test_m9_plots` | pass, unchanged |

**Service gates** (`test_backend_service.py`, 38 tests; none of the P0
tests changed):
- maps equal `observable_maps` (`np.array_equal`) in 1D, 2D and 3D;
  each is a valid result file;
- `export.*` output is byte-identical to direct calls;
- named errors (missing doping, missing file, bad parameters, unknown
  band, no snapshots, a 2D export), and the service keeps serving;
- the scratch directory is removed after shutdown and after stdin EOF,
  with an exit in under 2 s;
- `debug.*` exists only when asked for;
- **Qt-free, precisely:** after maps, none of PySide6, matplotlib,
  pyvista or pyvistaqt is loaded; after an export, pyvista only;
- `paraview_export` imports with PySide6 and `pyvistaqt` blocked.

**Found while gating:**
1. **The UTF-8 gate was vacuous at first.** `conda run` exports
   `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1`, so the test child ran
   in UTF-8 mode, and removing the service's `reconfigure()` still
   passed. The spawn helper now strips both variables, as the app's
   direct launch does. With the fix removed, the raw-UTF-8 case fails
   and the escaped case passes, exactly as the probe measured.
2. **A timeout's replacement request was written into the dying
   process.** `kill()` is asynchronous, and the process still reads
   "Running". `pump()` now waits while a kill is in progress.
3. **Calls pending at shutdown were reported as "backend exited"** when
   shutdown had to kill a busy service. They now report "shut down".

**Client gates** (22/22):
- handshake; `examples.list` equals Python's; 20 queued calls answer in
  order;
- band map → C++ `NpzFile` → `ResultModel`;
- a non-ASCII path through the client;
- timeout: fails in < 1 s, then a fresh backend (new pid, the old one
  gone);
- kill mid-call: the pending call fails in < 1.5 s naming the method;
- exit code and stderr reported; 3 crashes → gave up → reset;
- a missing interpreter is a named error;
- shutdown: pending → "shut down", no process, no scratch directory;
- fakes: garbage / wrong id / wrong protocol → protocol errors named;
  silence → timeout; immediate exit → gave up with "code 7"; stderr
  then exit → the message; CRLF + split lines and a 10 MB line → read
  correctly.

**The backend loads nothing from `tcad-gui`.** The check ran after a
map and a VTU export (numpy, pytcad, pyvista, VTK), with the GUI env's
DLL directory on the test process's PATH. Every module came from the
backend's own prefix, Windows, or the project tree (`_core.pyd`, built
in place).
- **Honest limit:** the probe before S4 showed the same result *without*
  the client's PATH stripping. The gate checks the outcome, and the
  stripping is defence in depth; removing it would not fail this gate.
- The same holds for the client's ASCII escaping (the service now reads
  UTF-8 anyway) and its `\r` stripping (JSON parsers treat a trailing
  `\r` as whitespace). Neither is load-bearing today.

**Bulk transport** (`--bench-backend`, 7 repeats, p50 unless stated):

| Result | Map | Size | End-to-end | First call | Service load / compute / write | C++ read | Transport (write + read) |
|---|---|---|---|---|---|---|---|
| mosfet_2d | R | 0.1 MB | 8.8 | 763 | 4.1 / 0.6 / 2.5 | 9.0 | 11.9 |
| mosfet_2d | bands (4) | 0.2 MB | 5.8 | 7.3 | 2.9 / 0.1 / 2.5 | 10.5 | 12.6 |
| 1000×1000 | **R (gated)** | 8.0 MB | 215 | 1029 | 27.4 / 169.9 / 12.2 | 70.7 | **84.0 (p95 89.8) ≤ 150 — met** |
| 1000×1000 | bands (4) | 32 MB | 96.6 | 104 | 27.2 / 35.0 / 32.6 | 249 | 282 (not gated) |

- **The first call costs 0.8–1.0 s** for the Python imports. A bare
  backend start (to the first ping) is about 0.1 s.
- **No source cache** (revision 8): reloading costs 27 ms at 1M nodes,
  against R's 170 ms compute.
- **Follow-up, outside S4.** The C++ read runs at about 130 MB/s (249 ms
  for 32 MB). `NpzFile::open` reads through `istreambuf_iterator`, a
  byte-at-a-time idiom, which likely also explains S2's 221 ms "open
  result" on the 1M grid. Profile, then read with one sized `read()`.

**Not run:** the full fast suite. It was stopped at the user's request
because of its 15–22 minute runtime on this PC. The targeted set (every
desktop test file plus every file S4 touched, 296 tests) passed with
zero warnings. S3's own full-suite confirmation is still outstanding
for the same reason.

### 15.17 S5 — 2D map parity: plan (2026-09-25, reviewed; landed, see §15.18)

**Review revisions** (from reading the installed matplotlib 3.11.2 and
the native code before any S5 code; they override the text below where
they differ):

1. **Contour levels, exactly.**
   - `contour(levels=8)` uses `MaxNLocator(9, min_n_ticks=1)`:
     `_nonsingular` (with `expander=1e-13`, `tiny=1e-14`), then
     `scale_range`, the extended step staircase from steps
     `[1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]`, the `_Edge_integer`
     tolerance, and `autolimit_mode='data'`.
   - `_autolev` then trims, but **keeps one level just below zmin and
     one just above zmax**. They draw nothing but are part of the
     array.
   - The port reproduces all of it, and the contract test compares
     against matplotlib's own `ContourSet.levels`, so the special cases
     (constant fields, huge offsets) are matplotlib's by construction,
     not by reading.
2. **Patch edges, exactly.** For `shading="nearest"` the edges are the
   midpoints, with the first and last extended by half the neighbouring
   spacing. The contract test compares the C++ dual coordinates with
   the edges of matplotlib's own `pcolormesh(..., shading="nearest")`.
3. **3D stays smooth in S5.** Nearest shading changes the 3D surface's
   geometry (its outer faces move half a cell out), and with it the S2
   hover oracle's box. That decision belongs to S6, with the slices.
4. **The bar's viewport must not steal the pointer.** The bar's renderer
   is non-interactive, so wheel and drag events reach the map.
   `readoutAt` reports nothing for a point outside the map's viewport:
   a map that runs under the bar's region is clipped there, and a
   hover must not name a node that is not visible. The selftest's node
   round trip skips nodes outside the map's viewport, and a new gate
   checks that hovering over the bar gives no readout.
5. **The bar title is its own text actor, placed above the bar**
   (VTK's in-bar title is what overlaps the top label). The gate is
   structural: the title's box lies above the bar's box.
6. **Line widths.** A VTK line thinner than 1 device px draws as 1 px,
   so the QML view's 0.6 px contours and 0.3 px mesh lines cannot match
   in width. Parity is of *presence and colour* (white, with the QML
   alphas), scaled by the DPR. Stated, not hidden.
7. **Pixel probes live in the selftest and work on any 2D result**, not
   only synthetic ones:
   - **colour**: a node's projected pixel must equal
     `vtkLookupTable::GetColor` of its displayed value; that is exact
     under nearest shading;
   - **orientation**: the node at y = min projects above the node at
     y = max; x = min is left of x = max;
   - **contours and mesh lines**: with the overlay on, the pixel on a
     level crossing or on a node line is lighter than the bare patch;
     with it off, it is identical.
8. **matplotlib is in `tcad-dev` (3.11.2)**, so the colour-table
   generator and the contract tests run there. The generated table file
   (`src/views/colormaps_data.inc`) joins the colour-scan exemptions.
9. **S5a stays first.** The 4-field derived maps S5 displays (32 MB at
   1M nodes) take 249 ms just to read today.

The goal is that everything the QML viewport shows as a 2D field map,
the native FieldView shows too, from the same numbers. It must also fix
the scalar-bar overlap (§15.13 rev. 9). 3D (slices, isosurfaces,
volumes) is S6; curves and line cuts are P2.

**What the QML viewport actually does** (read in
`gui/visualization/mpl_canvas_item.py`, 2026-09-25):

| Mode | Data | Colour map | Scale | Notes |
|---|---|---|---|---|
| any field (potential, n, p, doping, ...) | the stored field | viridis | linear, or `log10(max(\|v\|, 1e-30))` with the log toggle | 3D results show the **central z-plane** |
| bands (2D) | Ec = −ψ − χ | viridis | linear | label "Ec [eV]"; 3D says "a later version" |
| recombination (2D) | R | inferno | **always** `log10\|R\|` (the toggle does not apply) | hover reports raw R |
| doping *preview* (no solve yet) | structure raster | RdBu_r | linear or log\|N\| | not a result view; out of scope |

Common to all rows:
- **Shading** is `pcolormesh(shading="nearest")`: each node owns a
  flat patch reaching halfway to its neighbours. What is on screen is
  only computed values; nothing is interpolated.
- **Contours**: `ax.contour(levels=8)` on the *displayed* (possibly
  log) values, in white at 0.6 px and alpha 0.7. `levels=8` is
  matplotlib's "nice numbers" `MaxNLocator`, not 8 evenly spaced
  levels.
- **Mesh overlay**: a line through every node coordinate (the true,
  non-uniform axes), in white at 0.3 px and alpha 0.35.
- **No colour-range lock exists.** A solved result's doping is shown in
  viridis, so the log view (`log10|N|`) loses the n/p sign.

**What the native view does today** (P0/S2):
- viridis from a **9-stop approximation**, not matplotlib's table;
- **smooth interpolation** between nodes (colours no node computed);
- the scalar bar drawn **inside** the map's viewport (it overlaps the
  device after Fit, and more after panning), with its title overlapping
  the top label;
- no contours, no mesh lines, no derived maps, no range control.

#### Steps, in order

| Step | Content |
|---|---|
| S5a | **Reader speed first** (the S4 follow-up). `NpzFile::open` reads with one sized `read()` instead of `istreambuf_iterator`; profile the CRC and inflate paths and fix only what the profile shows. The P0 conformance gates are unchanged, and "open result" plus the S4 read-back are re-measured. Done first because S5 displays 32 MB derived maps. |
| S5b | **Exact colour maps.** `colormaps.cpp` holds matplotlib's own 256-entry tables for viridis, inferno, plasma and RdBu_r. The tables are generated by a script from matplotlib, which runs in `tcad-dev`, not at runtime. |
| S5c | **Nearest shading**, as in the QML view. The 2D map is drawn on the *dual* grid: cell faces sit at the midpoints between nodes, with extended half-cells at the edges, and cell data holds the node values. Each node's patch is then exactly its value, as `pcolormesh(shading="nearest")` draws it. Contours still use the node grid. The S2 fast paths (build once, gather) carry over, with cell ids in place of point ids. The selftest's checks move to cells. |
| S5d | **The scalar bar gets its own viewport.** The map's renderer occupies [0, 1 − w] and the bar's renderer [1 − w, 1], with w sized from the bar's pixel width, so no pan, zoom or Fit can put the map under it. Fit fits the map viewport. The bar's title is laid out above its top tick label. |
| S5e | **Per-mode display, as in the QML table.** Default colour map per mode, the recombination map always in log, the log toggle for the rest. A Display panel (dock) gathers the colour map (override), log, contours, mesh lines, and the colour range (Auto, or Manual min/max with Lock, which keeps the range across field switches). |
| S5f | **Contours and mesh lines.** Contours use a C++ port of matplotlib's `MaxNLocator` level choice (so the levels are the same numbers), `vtkContourFilter` on the node grid, and white at 0.6 px, alpha 0.7. Mesh lines go through every node coordinate. Both widths are logical pixels, scaled by the DPR. |
| S5g | **Derived maps through the backend.** Under Fields, a "Derived" group adds Ec/Ev/EFn/EFp and R. These call `analysis.band_map` / `recombination_map` asynchronously, with progress in the status bar and a cancel that simply ignores the late reply. The returned file is read with the S4 reader; the hover reports raw values and units. An entry the result cannot support (for example no doping for R) is disabled, with a tooltip naming the missing fields. A failed call reports its named error, and the current view stays. |
| S5h | **Gates, bench and write-up** (below). |

#### Gates

- **Colour maps**: `tcad_npz_dump --colormaps` (or a small tool) dumps
  the C++ tables; they equal matplotlib's `cmap(i/255)` for all 4 maps
  and all 256 entries (to 1e-6).
- **Contour levels**: the C++ `MaxNLocator` port equals matplotlib's
  levels from `ax.contour(z, levels=8)`. The cases are 60 generated
  ranges: tiny, huge, negative, crossing zero, log-scaled, and a
  constant field, which must give **no** levels, as in matplotlib.
- **Pixel probes**, on real renders at scales 1, 1.5 and 2:
  - **orientation**: on a synthetic field f = x + 10y, node (0,0)
    appears top-left, x grows to the right, y downward;
  - **colour**: the pixel at the centre of a node's patch equals the
    LUT colour of that node's (log) value, within 1/255 per channel;
    this is exact because nearest shading puts no interpolation on
    screen;
  - **contours**: pixels on a known level line carry the contour
    colour, and pixels between lines do not;
  - **mesh lines**: a pixel on a node line is lighter than the pixel
    beside it;
  - **no overlap**: after Fit, and after a pan toward the bar, no map
    pixel falls inside the bar's viewport;
  - **title**: the bar title's box does not intersect any label's box.
- **Parity checklist, one named test each**:
  - field, linear;
  - field, log;
  - doping (see decision 2);
  - bands Ec, plus Ev/EFn/EFp;
  - recombination (always log);
  - contours on and off;
  - mesh lines on and off;
  - hover raw values, derived maps included;
  - Fit and Reset;
  - colour range Auto, Manual and Locked across switches;
  - derived map missing a field → disabled, naming it;
  - backend error → named, view kept.

  The QML view's "3D central z-plane" is listed as S6's (slices).
- **Selftest**: node ids → **cell** ids; values and range still
  bit-identical; the S2 bench rows do not regress.
- **Bench**, new rows:
  - contour toggle at 1M nodes ≤ 150 ms;
  - mesh-line toggle ≤ 100 ms;
  - derived map, click to first frame: first call and warm call,
    reported (the first includes the backend's ~1 s imports);
  - bands at 1M nodes ≤ 500 ms warm.
- **Invariants**:
  - clean `/W4` build;
  - every desktop test file green;
  - zero warnings;
  - results as §15.18.

#### Decisions with a default (say if you want otherwise)

1. **Nearest shading only**, as the QML view does and as the "show what
   was computed" rule (M51) implies. A smooth-interpolation toggle is
   left out, not built.
2. **A result's doping gets a signed map**: `sign(N)·log10(max(|N|, 1))`
   on RdBu_r, with a symmetric range, so n and p regions read at a
   glance. The QML result view shows viridis / `log10|N|`, so this is
   the one deliberate *improvement* over parity. Its test pins the
   formula, and the plain field view stays one click away.
3. **A colour-map selector is offered**: viridis, plasma, inferno,
   RdBu_r (the 3D viewer's set, plus inferno). Each mode keeps the QML
   default.
4. **The backend is warmed at idle.** After the first frame, an idle
   `system.warmup` (a new method) imports numpy, workbench and pytcad,
   so the first derived map does not pay ~1 s. It is measured both
   ways, and kept only if the numbers show the win.

#### Out of scope for S5

3D display modes (S6), line cuts and 1D curves (P2), exports (S7), and
the structure/mesh/process/C-V/transient/AC views (P2–P4).

#### Risks

| Risk | Mitigation |
|---|---|
| The dual grid doubles the edge work and breaks S2's gather assumptions | Built once per result, like S2; the selftest re-proves bit-identity on cells |
| The `MaxNLocator` port drifts from matplotlib's | A contract test against matplotlib itself over 60 ranges |
| Pixel probes are flaky from multisampling or gamma | Probe patch centres (flat colour), a 1/255 tolerance, MSAA off in the map renderer |
| Derived maps at 1M nodes are slow on first use | Measured; progress shown; decision 4's warm-up |

### 15.18 S5 results (2026-09-25/26)

All of S5a–S5h landed (uncommitted). A clean MSVC `/W4` build. Every desktop test file is green: 381 passed, zero warnings, over the 20 files S4/S5 touch (the desktop files, the backend service, the ParaView/3D-viewer exports that re-import `grid_builders`, the matplotlib canvas and viewport files that use `observable_maps`, and `test_m30_study_manifest.py`). Qt Test: `tcad_desktop_shell_tests` 32 passed (30 cases plus init/cleanup), `tcad_desktop_backend_tests` 22 passed. **Full suite, fast part** (`-m "not slow"`, 4 workers, 2026-09-26): 2331 passed, 35 skipped, 2 xfailed, zero warnings, in 20 min 27 s. The slow gate battery (`-m slow`) was not run, at the user's request; it is still owed before a milestone completion claim.

| Step | What landed |
|---|---|
| S5a | `desktop/src/data/npz.cpp` reads with one sized `read()`. CRC-32 is zlib's `crc32` in 1 GiB chunks (`TCAD_HAVE_ZLIB`, found in `tcad-gui`; the table version stays as the fallback). Stored entries are CRC-checked and parsed in place, without a copy. The label comes from `u8string()`, which fixes S3's non-ASCII-path open. |
| S5b | `colormap_tables.hpp` (not `colormaps_data.inc` as rev. 8 said), generated by `desktop/tools/gen_colormaps.py` from matplotlib 3.11.2. It holds viridis, plasma, inferno and RdBu_r, 256 entries each. `colormaps.hpp` adds `lut_input(v, lo, hi)`, matplotlib's `Normalize`; the VTK table itself spans [0, 1]. |
| S5c | Nearest shading on a dual rectilinear grid (`grid_edges.hpp`'s `nearest_edges`), with one cell per node. The S2 gather now carries cell ids. 3D stays a smooth point-data surface (rev. 3). |
| S5d | The scalar bar has its own non-interactive renderer in a 130 logical-px column (`w = 130·dpr / width`). The map's renderer spans [0, 1 − w]. `readoutAt` returns nothing outside the map viewport. |
| S5e | `FieldKind` (Generic / Band / Recombination / Doping) with the §15.17 table's defaults. A Display dock (`display_panel.{hpp,cpp}`) holds the colour-map override, log, contours, mesh lines, and Auto / Manual / Lock range. The overlays are disabled in 3D. |
| S5f | Contour levels come from a C++ port of `MaxNLocator` + `_autolev` (`contour_levels.{hpp,cpp}`), including CPython's `float_divmod`. Contours are drawn by `vtkFlyingEdges2D` on an index-space image and mapped back onto the true axes. Mesh lines go through every node coordinate. Both overlays are white, at the QML alphas 0.7 / 0.35. |
| S5g | Derived entries Ec / Ev / EFn / EFp / R call `analysis.band_map` / `recombination_map` through `BackendClient`. A generation counter drops stale replies. The maps are cached per result, and a missing field disables the entry with a tooltip. `system.warmup` (new, `backend_service/server.py`) runs 300 ms after a ≥2D result opens (decision 4; `backend/warmup=off` disables it). |
| S5h | Gates below. New bench rows: `contours_on` (+ phases), `mesh_lines_toggle`, `reset_layout`, `*_gl_reinits`; `--bench-backend --warm`. `theme_dump` gains `--colormaps`, `--contour-levels` and `--edges`. |

**Deviations from the reviewed plan** (each deliberate, each gated):

1. **Bar title vertical, right of the bar, not above it** (rev. 5). In a 130 px column, a title above the bar shares its row with the top tick label. A vertical title beside the bar has its own column. The gate: the title's box lies right of the bar's right edge.
2. **`vtkFlyingEdges2D`, not `vtkContourFilter`.** At 1M nodes the contour filter measured 159 ms for "contours on". Flying edges on an index-space image, remapped to the true axes, measured 12.8 ms p50 on a quiet machine and 17.8 ms p50 in this run under load (below).
3. **80 contour-level cases, not 60.** The 20 extra include 10 ranges where naive floor division gives a different level set than CPython's `float_divmod`. The 60 generated cases did not include one, and a mutant replacing the divmod survived them.

**Gates**

| Gate | Result |
|---|---|
| Colour tables = matplotlib `cmap(i/255)`, 4 maps × 256 | met (`test_tables_equal_matplotlib`) |
| VTK colour of a value = matplotlib's, rounded to 8 bits | met, 4 maps × 5 ranges including a constant field and 1e10–1e18. VTK quantises to 8 bits, so the gate compares 8-bit colours, not 1e-6 floats. |
| Contour levels = matplotlib `ContourSet.levels` | met, 80 cases (constant field gives no levels) |
| Patch edges = `pcolormesh(shading="nearest")` | met (4 real axes + a one-node axis) |
| Pixel probes at scales 1, 1.5, 2 (MOSFET, graded, 1000×1000 grid) | met; see *render noise* below. Colour at the node and at quarter points toward all four neighbours is within 1/255. Orientation. Mesh lines lighter at ≥90% of node probes. Contour crossings lighter at ≥80%. Overlay off restores the frame. No map pixel under the bar after Fit and after a pan. Title box right of the bar. No readout over the bar. |
| Parity checklist | met by 8 named shell tests (`fieldListSeparatesDerivedMaps`, `derivedEntryNeedsItsFields`, `bandsAndRecombinationComeFromTheBackend`, `backendWarmsUpAfterA2DResultOpens`, `backendFailureIsNamedAndTheViewStays`, `dopingGetsTheSignedMap`, `displayPanelDrivesTheView`, `overlaysAreDisabledIn3D`), plus the S3 test for field / log / Fit / hover. That is several items per test, not one test per item. The derived-map hover is checked value-for-value: the printed number is the source result's raw value at a node with the printed coordinates. |
| Selftest node ids → cells; values and range bit-identical | met |
| contours on at 1M ≤ 150 ms | met: 17.8 p50 / 26.2 p95 |
| mesh-line toggle ≤ 100 ms | met: 1.7 / 2.2 at 1M |
| derived map, first and warm call | cold first call 728 ms (MOSFET). With warmup: 8.3 ms, after a 690 ms `system.warmup` at idle. Warmup is kept (decision 4). |
| bands at 1M ≤ 500 ms warm | met by its measured parts: RPC end-to-end 97.3 ms p50 + C++ read 67.1 + field switch 18.2 = about 183 ms. That is a sum of bench phases, not a single click-to-frame timing. |

**Mutation checks** (each rebuilt, run, reverted and rebuilt clean):

| Mutant | Caught by | How |
|---|---|---|
| contours never hide once shown | selftest `contours_off_restores` | residue 940–5033 px against a limit of 43–97 |
| mesh lines never hide | selftest `mesh_off_restores` | residue 13,720 / 20,583 px |
| readout prints the displayed (log) value | `bandsAndRecombinationComeFromTheBackend` | printed `R: 9.111e+00`, which is log10 R |
| naive floor division in the level port | `test_desktop_contour_levels.py` | the 10 divergent ranges (found in S5f; the reason for deviation 3) |

**Bulk transport after S5a** (`--bench-backend`, 1000×1000 with carriers, 7 repeats, warm, p50):

| Map | Size | S4 C++ read | S5 C++ read | S5 transport (write + read) |
|---|---|---|---|---|
| R | 8 MB | 70.7 | 22.6 | 34.4 (p95 36.1) |
| bands (4) | 32 MB | 249 | 67.1 | 98.1 |

The 32 MB read runs at about 480 MB/s, up from 130 MB/s, a 3.7× gain. "Open result" on the 1M grid went from 224 to 189 ms. It is dominated by geometry, not the read.

**Findings**

- **Render noise.** Two renders of an unchanged scene are not always pixel-identical on this GPU:
  - at Fit on the 1M grid (patches under a pixel wide);
  - at DPR 1.5 on the MOSFET and graded meshes (12–14 px);
  - once in seven runs at DPR 2 on the graded mesh: 216 of 864k px after contours-off, gone on a re-render.

  The restore checks therefore allow 0.02% of the image. A frame over that gets one fresh render before it is judged, and the pixel counts are reported (`*_diff_pixels`, `fit_render_noise_pixels`). A left-over overlay differs by 20× to 480× that limit (the mutants above) and survives a re-render. Contour crossings are counted against both of two overlay-off renders.
- **ADS `restoreState` recreates the GL context every time** (20 of 20 restores). It reparents the central area, and a restore costs 67–111 ms p50. The app calls `restoreState` only at startup, before a result is open. Reset layout rebuilds the default with `addDockWidget`: 37–39 ms p50, with 0 GL re-inits.
- **Exact colours need `lut_input`.** Feeding VTK raw values with the table range set to the data range picked the adjacent entry at bin edges for extreme ranges. Normalising in double, as matplotlib does, and giving VTK [0, 1] made every probe exact.
- **Warmup pays.** It turns a 0.7–1.0 s first derived map into about 8 ms. The cost moves to idle time after the first frame.

**Bench under load, not compared.** This run's native bench (1200×800, DPR 1) ran while a game held the GPU with CPU load at 71%. Its interactive rows are 1.3–2× S3's on unchanged paths too: 1D cold start went 585 → 1837 ms, and 3D orbit 0.7 → 1.1 ms. So they are not a clean S3 → S5 comparison. The one S5 change on every frame is the second (bar) renderer. Every row is still far inside §15.4's targets: pan ≤ 2.4 / 3.6 ms, field switch 18.2 ms at 1M. The absolute S5 gates above are met under that load. **A quiet-machine re-run is owed**, to confirm "the S2 rows do not regress" and to measure the bar renderer's cost.

**Honest limits**

- VTK line widths are at least 1 device px. The QML view's 0.6 px contours and 0.3 px mesh lines are matched in presence, colour and alpha, not in width (rev. 6).
- 3D keeps smooth shading and no overlays. The QML view's central z-plane for 3D results belongs to S6.
- The slow gate battery has not run since S3 (above); the fast part is green.
- `graphify update .` segfaults under Git Bash (exit 139). It runs cleanly from PowerShell.

### 15.19 S6 — 3D parity: plan (2026-09-26, reviewed; landed, see §15.20)

The goal: everything `viewer3d.py` shows for a 3D result, the native FieldView shows too, from the same numbers. On top of that come the P1-scope additions §15.7 lists for S6 (slices, clipping) and the QML viewport's 3D central z-plane. VTU/PVD export and Open in ParaView are S7.

**Review findings** (from reading `viewer3d.py`, PyVista 0.4x in `tcad-dev` and VTK 9.7 in `tcad-gui` before any S6 code; they override the text below where they differ):

1. **The Python viewer's arrows are 7.9 million times the device.** `grid.glyph(orient=J, scale=J, tolerance=0.05)` scales each arrow by the raw magnitude |J| (A/cm², up to 3.2e3 on `resistor_3d`) with factor 1, in cm. Measured on `resistor_3d`: device diagonal 4.2e-4 cm, glyph bounds 3.3e3 cm. The native arrows are scaled so the largest has the glyph spacing's length (spacing = tolerance × diagonal, as PyVista merges points), with length ∝ |J|. This is a fix, not parity.
2. **PyVista's streamline seeds are random and unseeded** (`vtkPointSource`, 100 points in a sphere of radius diagonal/2 at the centre), so two runs differ. The native seeds use the same source with a fixed random sequence, so runs and tests repeat. The integrator settings are PyVista's defaults: RK45, both directions, initial step 0.5 / min 0.01 / max 1.0 cell lengths, 2000 steps, terminal speed 1e-12, max error 1e-6, max length 100 × diagonal; tube radius 0.002 × diagonal.
3. **Volume rendering needs no resampling.** PyVista hands the `RectilinearGrid` straight to the smart volume mapper, with a constant opacity (the preset's) and `opacity_unit_distance = diagonal / (mean(dims) − 1)`. The native view does the same on the node grid. It colours the *displayed* values (log when on) through the view's colour map and range, so volume, surface and bar agree; `viewer3d.py` colours raw values over their own range.
4. **The presets are colour map + constant opacity**, whatever their names say: linear viridis 0.3, log-high plasma 0.25, log-low viridis 0.35, threshold RdBu_r 0.5. They are ported exactly as written; their names promising more is recorded, not changed.
5. **The Python isosurface is coloured by an array that is constant (= the level)**, so its colour is whatever PyVista's LUT does with a zero-width range. The native isosurface takes the colour of its level under the view's colour map and range, so it reads against the bar. The level is in displayed units (log10 when log is on), with the Python default: the midpoint of the finite range.
6. **3D uses nearest shading** (the decision S5 rev. 3 deferred). Each node owns a voxel between the midpoints to its neighbours, as in 2D. The outer faces, slices and crop faces are then flat, node-exact patches: the M51 rule, one hover oracle, and exact pixel probes. Data-coloured faces are drawn unlit, as a 2D map is ("colours are data"); isosurfaces and exploded regions are lit, since their colour is not a value per pixel. The S2 hover oracle's box becomes the patch-edge box, which is still analytic.
7. **`viewer3d.py` has no slices or clipping.** Slices are axis-aligned planes at node positions (snapped, never interpolated), drawn as nearest-shaded 2D maps; the z-slice at the central index, viewed along z, is the QML viewport's "3D central z-plane". Clipping is an axis-aligned crop box in node indices. Its faces are node-exact patches like the outer faces, and the hover oracle is the crop box.
8. **The playback range spans every snapshot.** `viewer3d.py` re-ranges nothing while playing. With the native auto range, each frame would re-range and colours would not compare across frames, so while a snapshot is shown the auto range is the union over the field's snapshots (a manual range still wins). Glyphs and streamlines are not recomputed per snapshot (vectors have no snapshots), as in `viewer3d.py`; the panel says so.
9. **Glyph and streamline colour needs a second legend.** `viewer3d.py` adds a scalar bar per actor. Natively, when a vector overlay is on, the bar column holds two bars: the field (top) and |J| in plasma (bottom).
10. **The region palette** (the twelve colours `viewer3d.py` names) lives in `theme/tokens.hpp`, so the no-hard-coded-colour gate still holds.
11. **The bench's "on the MOSFET" is 2D.** The new 3D rows run on the 100³ synthetic grid (given a vector field, five snapshots, a sweep block and two regions, so every row has data) and on `resistor_3d`.
12. **VTK modules.** `FiltersFlowPaths`, `FiltersSources`, `FiltersExtraction`, `FiltersModeling`, `RenderingVolume` and `RenderingVolumeOpenGL2` join the link. Their headers are in `tcad-gui` (checked), so no environment changes.

#### Steps, in order

| Step | Content |
|---|---|
| S6a | **Nearest 3D surface, outline and crop.** A dual (patch-edge) grid with one cell per node, cropped by index with `vtkExtractRectilinearGrid`, and its outer faces. Node ids ride on the cells (the S2 gather), and picks go to the containing voxel's node directly. A box outline in the overlay colour. A surface mode: Field (default), Context (translucent, `viewer3d.py`'s context surface) or Hidden. It switches to Context on its own the first time an interior layer (isosurface, volume, vectors) is turned on over an opaque surface. View presets: iso, ±x, ±y, ±z. |
| S6b | **Slices.** Up to three axis-aligned slices, each at a node index (a slider), spanning the crop box, as nearest-shaded cell maps gathered like the surface. |
| S6c | **Isosurface.** `vtkFlyingEdges3D` on the index-space image of the displayed node values, mapped back along the true axes (S5's contour method in 3D), coloured by its level. |
| S6d | **Volume** with the four presets (findings 3–4). |
| S6e | **Glyphs and streamlines** (findings 1, 2, 9): a vector-field choice, glyph spacing (`viewer3d.py`'s 0.05 default, range 0–0.5) and a streamline toggle. |
| S6f | **Playback.** A bottom dock with step back, play/pause (300 ms), step forward, a slider, the voltage and a Result button (back to the result's own field). It is enabled only when the result has snapshots. |
| S6g | **Exploded view.** Regions from `region_materials`, else `structure_regions` (`viewer3d.py`'s order). Each region's nodes (inclusive box, the Python mask) are drawn as a lit, translucent (0.6) patch surface with edges, offset along z by index × separation. The separation defaults to 0.15 × diagonal, with range 1e-4…5 × diagonal. With no regions the control is disabled and its tooltip says why. |
| S6h | **Gates, bench and write-up.** |

All controls live in a **3D** dock tabbed with Display, which is disabled in 2D.

#### Gates

- **Selftest (3D, every scale):**
  - node ids and values bit-identical on the patch faces (cells, as in 2D);
  - hover oracle against the patch-edge box, and again against a crop box: 0 mismatches;
  - pixel colour on a face viewed along z, and on a z-slice with the surface hidden, is the LUT colour of that node within 1/255;
  - slice geometry: the plane coordinate is the node's, and the cell ids are that plane's nodes;
  - every isosurface vertex lies on one grid edge whose end values bracket the level, at the linear interpolation, to 1e-9 relative;
  - volume: the colour function equals the view's table, opacity equals the preset, and pixels change only inside the device's silhouette;
  - glyph sources are nodes; each vector equals J at its node; the largest arrow's length equals the spacing;
  - streamline points lie inside the device, and each segment is parallel to the interpolated J (|cos| > 0.99);
  - exploded regions: bounds equal each region's patch box, offset by index × separation along z;
  - playback: displayed values at snapshot k are bit-identical to the reference built from the file's snapshot k, and the range is the union.
- **Mutations**, each of which must fail its gate: slice index off by one; isosurface remap along the wrong axis; glyph vector components swapped; snapshot index off by one; exploded offset on the wrong axis; crop range off by one.
- **Parity checklist:** one named shell test per §10.3 display feature (isosurface, colour maps, volume + presets, glyphs, streamlines, playback, exploded view) and per addition (slices, central z-plane, clipping), plus the panel disabled in 2D.
- **Bench, new rows** (100³ and `resistor_3d`), with §15.4's targets:
  - slice drag ≤ 16.7 ms per frame;
  - isosurface level change ≤ 100 ms;
  - volume orbit ≤ 33 ms;
  - playback step ≤ 33 ms;
  - streamline rebuild ≤ 200 ms;
  - glyph rebuild, crop change and exploded toggle, reported.

  The S2/S5 rows are re-measured beside them.
- **Invariants:** clean `/W4` build, every desktop test file green, zero warnings, results as §15.20.

#### Out of scope for S6

Export (S7), line cuts and probes (P2), unstructured 3D meshes (the result grammar is structured), and a transfer-function editor.

### 15.20 S6 results (2026-09-26)

All of S6a–S6h landed (uncommitted), with a clean MSVC `/W4` build.

- **Tests:** every desktop test file is green, with zero warnings. That is 381 passed over the 20 files S4–S6 touch.
- **Qt Test:** `tcad_desktop_shell_tests` 44 passed (42 cases plus init/cleanup); `tcad_desktop_backend_tests` 22 passed.
- **Not run after S6:** the fast full suite (it last ran after S5: 2331 passed, 35 skipped, 2 xfailed, zero warnings) and the slow gate battery.

| Step | What landed |
|---|---|
| S6a | **Voxel surface.** 3D is nearest-shaded: a dual (patch-edge) grid, one cell per node, cropped with `vtkExtractRectilinearGrid`, and its outer faces unlit. Node ids ride on the cells, so the S2 gather is unchanged. **Controls:** a crop outline in the overlay colour; surface modes Field, Context (the `T::Context` token) and Hidden, which switches to Context on the first interior layer; view presets Iso and ±x/±y/±z. |
| S6b | **Slices.** Up to three axis-aligned slices at node planes. Each is a quad grid over the crop box's in-plane patch edges, gathered like the surface. **Central z-plane** is one action: the slice at nz // 2, surface hidden, looking along +z. |
| S6c | **Isosurface.** `vtkFlyingEdges3D` on the index-space image of the displayed node values, with each vertex mapped back along the true axes. It is coloured by its level under the view's map and range. The level is in displayed units, reset to the midpoint on a field or log change. |
| S6d | **Volume.** `vtkSmartVolumeMapper` directly on the rectilinear node grid (no resampling; the view's normalised values). The colour function is the view's 256-entry table. Opacity is the preset's constant, with PyVista's unit distance. A preset (and turning the volume on) sets the view's colour map, so the bar describes the volume. **Level of detail while dragging:** the interactor asks for 30 fps, and the GPU mapper coarsens its sampling to fit. |
| S6e | **Glyphs and streamlines** (findings 1, 2, 9). Glyph thinning is done natively (see below). Arrows are scaled so the longest equals the spacing. Streamlines use PyVista's integrator settings with a seeded point source and 20-sided tubes. \|J\| gets a second bar in the bar column. |
| S6f | **Playback dock** (`playback_panel.{hpp,cpp}`): step back, play/pause (300 ms, loops), step forward, a slider, the voltage, and a Result button. `FieldView::setSnapshot` decodes the snapshot, and the auto range is the union over the field's snapshots. |
| S6g | **Exploded view** from `region_materials`, else `structure_regions`: the Python node mask, extracted as patch sub-grids. The regions are lit, 0.6 opaque, with edges, in `theme::kRegionPalette`, offset along z by list index × separation. |
| S6h | **The 3D panel** (`view3d_panel.{hpp,cpp}`, tabbed with Display). **Code:** the 3D layers live in `field_view_3d.cpp`. **Gates:** `check_3d` in the selftest. **Data:** `run_bench._layers_3d` gives every synthetic 3D result a current density, five snapshots and two regions. **Tests and bench:** 12 shell tests; nine bench rows. |

**Found while implementing** (each measured, fixed, and gated where it is a behaviour):

1. **`vtkCleanPolyData` mispairs merged points.** Measured: node (0,0,0)'s position carried node (1,1,2)'s J, in 1184 of 1207 arrows. PyVista's `glyph(tolerance=)` uses the same filter, so `viewer3d.py` has the same fault on top of finding 1's scale. The native thinning is a greedy first-kept pass on a tolerance-sized bin grid: every arrow sits on the node whose J it shows. The selftest's glyph gate checks exactly that pairing.
2. **The cell locator can pick the coplanar neighbour.** Within the picker's sub-pixel tolerance of a shared patch edge, `vtkStaticCellLocator` picks the neighbouring face, and brute-force picking agrees with it. That gave 12 of 310 hover hits naming the adjacent node.
   - The picker now decides only *what* is hit first.
   - For a face or slice, *where* comes from the ray's analytic intersection with that known plane (the crop box or the node plane).
   - The node is the voxel holding that point.
   - Result: 0 mismatches against the oracle, full and cropped, at scales 1, 1.5 and 2.
3. **The first oracle was itself wrong on a crop.** A crop face lies ON a patch edge, where the nearest-node rule breaks the tie toward the node outside the crop. The oracle now takes the containing voxel, clamped to the crop.
4. **Docking Playback beside the view recreated the GL context on every Reset layout.** Measured in the bench: 10 re-inits in 10 resets, and 99–144 ms. Playback now docks below the left column's tabs. Reset layout is back to 0 re-inits and 36–40 ms. Gate: `resetLayoutAndSweepsKeepTheGlContext`.
5. **Nesting a dock beside the view also broke the Fields width.** `resetLayout` set the width on "the central area's splitter", which becomes vertical then. It now walks up to the first horizontal splitter (the S3 test `corruptSavedLayoutFallsBackToTheDefault` caught it).
6. **ADS unparents non-current tab pages.** A tabbed dock's hidden page has no parent, so `findChild` from the window cannot see it. The shell tests search from each panel. The UI is unaffected.
7. **Turning the volume on now applies the current preset's colour map.** Before, "linear" on a doping field kept RdBu_r, unlike `viewer3d.py`. Caught by `volumeRenderingPresets`.
8. **Gate precision revised from the plan:**
   - **Isosurface:** flying edges emits float points, so the gate is |interp − level| ≤ 1e-5 × the edge's value difference, not 1e-9 relative.
   - **Streamlines:** each chord is compared with the mean of its ends' unit tangents (exact on a circular arc). Against the start tangent, 95% passed at cos 0.99, from curvature alone; now 100% pass, worst 0.998.
   - **Volume:** the pixel check counts only the map viewport, because a preset recolours the bar.

**Gates**

| Gate | Result |
|---|---|
| Voxel node ids, and field values bit-identical (cells, 3D) | met on `resistor_3d`, `graded_3d`, `small3d`, `layers3d` |
| Hover oracle, full box and cropped (1000 px each) | 0 mismatches, at scales 1, 1.5 and 2 |
| Face and slice pixels = LUT colour (within 1/255), viewed along z | 0 mismatches (352 + 352 probes on `layers3d`) |
| Slice cells are exactly one node plane's patches (x, y, z) | 0 mismatches |
| Isosurface vertices on grid edges at the interpolated level | 0 of 1087 off |
| Volume colour function = the view's table, opacity = preset, pixels only inside the silhouette | met (0 changed outside) |
| Glyph sources are nodes carrying their own J; longest arrow = spacing | met (1207 arrows, 0 mispaired) |
| Streamlines inside the device, chords parallel to J | met (313/313 segments, worst cos 0.998) |
| Exploded regions on their patch boxes, offset along z | met (2 regions) |
| Playback: 5 snapshots bit-identical over the union range | met |
| Parity checklist, one named shell test each | `slicesShowNodePlanes`, `centralZPlaneMatchesTheQmlView`, `clippingCropsTheBox`, `isosurfaceFollowsTheLevel`, `colourMapsApplyIn3D`, `volumeRenderingPresets`, `glyphsFollowTheCurrent`, `streamlinesTraceTheCurrent`, `explodedViewSeparatesRegions`, `playbackStepsThroughSnapshots`, `view3dPanelIsDisabledIn2D`, plus `resetLayoutAndSweepsKeepTheGlContext` |

**Mutations** (each built, run and reverted by one script; the restored build's selftest is green):

| Mutant | Caught by |
|---|---|
| slice index off by one | slice geometry + slice pixels |
| isosurface remap along the wrong axis | isosurface vertex gate |
| glyph vector components swapped | glyph pairing gate |
| snapshot index off by one | playback gate |
| exploded offset on the wrong axis | exploded bounds gate |
| crop range off by one | cropped hover oracle |

**Bench** (1200 × 800, DPR 1, RTX 5060 Ti, p50 / p95 ms). The last run was on a quiet machine: CPU load 3% after it, and 1D cold start 494 ms against 1837 under load.

| Row | Target | `resistor_3d` | 100³ synthetic |
|---|---|---|---|
| slice drag, per frame | ≤ 16.7 | 0.8 / 1.0 | 1.3 / 1.6 |
| isosurface level change | ≤ 100 | 0.7 / 0.7 | 2.9 / 3.1 |
| volume orbit, drag (level of detail) | ≤ 33 | 1.1 / 1.4 | **3.1 / 3.4** |
| volume orbit, still quality | (reported) | 5.9 / 7.2 | 42.0 / 46.6 |
| playback step | ≤ 33 | — | 8.2 / 8.9 |
| streamline rebuild | ≤ 200 | 3.4 / 4.5 | 40.5 / 41.5 |
| glyph rebuild (spacing 0.05) | (reported) | 3.6 / 4.6 | 103.8 / 103.9 |
| crop change | (reported) | 0.8 / 1.1 | 11.2 / 12.0 |
| exploded toggle | (reported) | — | 9.5 / 11.3 |
| reset layout | ≤ 100 | 37.9 / 39.2 | 39.8 / 41.6 (0 GL re-inits) |

The still-quality volume frame at 100³ (42 ms) is over 33 ms. It is drawn once when a drag stops, not per frame; the drag itself runs at 3.1 ms.

**Quiet re-run against S3** (the comparison S5 owed):
- Field switch, zoom, orbit, hover and cold start are unchanged within noise.
- Dock float/redock is faster (29 → 20 ms).
- **Pan p50 is up** (MOSFET 1.1 → 2.4, resistor 0.9 → 2.0), with p95 unchanged (3.0–3.1). The likely cause is S5's second (bar) renderer, drawn on every frame, but it has not been isolated. Pan is still far under §15.4's 16.7 ms.
- **Layout restore is 7–10 ms slower,** with two more docks in the state.
- **The 100³ "open result" went 134 → 195 ms.** The bench file is now 117 MB (it carries S6's vectors and ten snapshots), and the voxel surface is new; the two are not separated.

**Honest limits**

- The full suite (fast and slow) has not run on S6.
- **One unexplained shell-test failure.** One run of `test_desktop_shell.py`, straight after a build, failed without writing a Qt Test report. The next five runs passed. It is not explained.
- **3D field faces are unlit** (exact colours; the depth cue is the outline). Isosurfaces and regions are lit.
- **Lines and bars:** line widths stay ≥ 1 device px (S5); the second bar shows only while a vector layer is on.
- **Found in `viewer3d.py`, not fixed:** the glyph scale (7.9e6 × the device) and the `vtkCleanPolyData` pairing. The QML/PyVista viewer is on bug-fix-only terms (§9), and fixing it is the user's call.
- Export (VTU/PVD, Open in ParaView) is S7.

### 15.21 S7 — Export and Open in ParaView: plan (2026-09-26, reviewed; landed, see §15.22; REMOVED, see §15.25)

**Goal.** `viewer3d.py`'s export dock, in the native app, through the backend service:
- export the result as `.vtu`;
- export a 3D sweep as a `.pvd` time series;
- open the last export in the user's ParaView.

**Review findings** (from `viewer3d.py`, `paraview_export.py`, `backend_service/server.py` and this machine, before any S7 code):

1. **The backend side exists.** `export.vtu` / `export.pvd` landed in S4, byte-compared with a direct `paraview_export` call in `test_backend_service.py`. S7 is the UI, the launcher, and the same byte gate through the UI.
2. **3D only.** `grid_builders.build_rectilinear_grid` raises for a non-3D mesh, as `viewer3d.py` (3D-only) assumes. The native actions are disabled for 1D/2D results, and the PVD action for results without sweep snapshots, each with a tooltip saying why.
3. **Timing measured at 100³:**
   - VTU 1.5 s (40 MB);
   - PVD 6.5 s (5 snapshots, 177 MB).

   The client's 30 s default would kill the service on a sweep about 5× larger, so exports use a 10-minute timeout. They run asynchronously, with a status-bar message, and a failure is a named error.
4. **What is exported is the result file**: every scalar and vector field, plus the snapshots for PVD. The view's state (derived maps, crop, the snapshot shown) is not exported, as in `viewer3d.py`. The action names say "result".
5. **PVD naming.** `viewer3d.py` asks for a folder and writes `sweep.pvd` plus `sweep_<i>.vtu`. The native save dialog asks for the `.pvd` path: `out_dir` is its folder and the base is its stem. The `.vtu` siblings overwrite silently, as in Python; the dialog confirms only the `.pvd`.
6. **ParaView lookup.** `viewer3d.py` defaults to `paraview` on PATH and remembers a path in `QSettings("PyTCAD", "Viewer3D")`. The native app looks, in order, at:
   - its own setting `paraview/path`;
   - `paraview` on PATH;
   - the newest `C:\Program Files\ParaView*\bin\paraview.exe`.

   If none exists, it asks with a file dialog (File > Locate ParaView). **ParaView is not installed on this machine**, so the launch is tested with a fake executable that records its arguments.

**Gates**
- **Byte equality through the UI:**
  - the `.vtu` from File > Export equals the fixture's direct `paraview_export.export_vtu` output;
  - the `.pvd` and every `.vtu` of the series equal `export_pvd_series`'s.
- **Disabled with a reason:** the exports for a 2D result, and PVD for a 3D result without snapshots.
- **Failure is named:** an export to an unwritable path reports the backend's error, and the app stays usable (a second export succeeds).
- **Open in ParaView** starts the configured executable with exactly the exported path. A missing executable is a named error.
- **Mutations:** a wrong PVD base name, and a launch without the file argument, must each fail their gate.
- **Invariants:** clean `/W4` build, every desktop test file green, zero warnings, results as §15.22.

### 15.22 S7 results (2026-09-26; REMOVED, see §15.25)

S7 landed (uncommitted), with a clean MSVC `/W4` build.

- **Tests:** every desktop test file is green, with zero warnings: 381 passed over the same 20 files.
- **Qt Test:** `tcad_desktop_shell_tests` 49 passed (5 new S7 cases).
- **Not run:** the full suite (fast and slow) has not run since S5.

**What landed**
- **File menu** (`main_window.{hpp,cpp}`):
  - Export result (.vtu)...
  - Export sweep animation (.pvd)...
  - Open last export in ParaView
  - Locate ParaView...
- **Exports:** they go through the S4 backend methods `export.vtu` / `export.pvd` with a 10-minute timeout. They run asynchronously, with a status-bar message, and `exportFinished(path, error)` reports the outcome.
- **Disabled states:** each action is disabled with its reason when it cannot run. That is the exports for a non-3D result, the PVD without sweep snapshots, and Open in ParaView before any export.
- **ParaView lookup:** the `paraview/path` setting, else PATH, else the newest `C:\Program Files\ParaView*\bin\paraview.exe`. Launched detached with the export's native path as its only argument.
- **Test stand-in:** `desktop/tests/fake_paraview.cpp` (`tcad_fake_paraview.exe`) records its arguments for the launch test.

**Gates**

| Gate | Result |
|---|---|
| `.vtu` from File > Export = `paraview_export.export_vtu` output, byte for byte | met (`exportVtuMatchesTheDirectExport`, on `resistor_3d`) |
| `.pvd` and all five `.vtu` of the series = `export_pvd_series` output | met (`exportPvdMatchesTheDirectExport`, on `layers3d`) |
| Disabled with a reason: 2D exports, PVD without snapshots | met (`exportsAreDisabledWithAReason`) |
| Unwritable target: named error naming the file; the next export succeeds | met (`exportFailureIsNamedAndTheAppStaysUsable`) |
| Open in ParaView: nothing exported → named; missing configured exe → named with its path; the stand-in receives exactly the exported path | met (`openInParaViewLaunchesTheExport`) |

**Mutations** (built, run and reverted by one script; the restored build's shell tests have no failures):

| Mutant | Caught by |
|---|---|
| wrong PVD base name | `exportPvdMatchesTheDirectExport` |
| ParaView launched without the file argument | `openInParaViewLaunchesTheExport` |

**Honest limits**

- **No real ParaView:** it is not installed on this machine. The launch is verified up to the process start and its arguments, through the stand-in; a real ParaView opening the file is not verified.
- **Result, not view:** the export writes the result file's fields, not the view's state (derived maps, crop, the snapshot shown), as `viewer3d.py` does (finding 4).
- **PVD siblings:** the `.vtu` files beside the `.pvd` overwrite silently; the save dialog confirms only the `.pvd` (finding 5).
- **No cancel:** there is none for a running export. A hung service is ended by the 10-minute timeout, which restarts it (S4's rule).

### 15.23 S8 — Hardening and P1 exit: plan (2026-09-26, approved with the default decisions; landed, see §15.24)

S8 closes P1: the gates §15.5 promised that no slice has met yet, the probes nothing has run, the one open flake, and the §15.8 exit checklist with its numbers. It adds no features.

**Review findings** (checked against the tree, the tests and this plan's own results before writing):

1. **Two §15.5 adversarial probes were never run:**
   - a result **deleted (or replaced) while open**;
   - a **2 GB file**.

   The reader reads the whole file into one buffer, then copies every array out of it (`NpyArray::data`). So an open briefly holds about 2× the file, and keeps about 1× for as long as the result is open. Nothing bounds that, and nothing refuses a file too large to view.
2. **§15.5's end-to-end scenario was never run as one sequence.** The S3–S7 shell tests cover its steps separately, mostly through `setChecked` / `click()` / public methods, not synthesized input. The scenario: open, field, log, hover, Fit, dock/undock, quit, reopen with the layout, a 3D sweep, play, step, export PVD.
3. **The 2D parity checklist shares tests.** S5 used 8 tests for 12 items; §15.8 asks for a test per item.
4. **The HiDPI suite runs no file with every 3D layer's data.** `test_desktop_hidpi.py` uses `resistor_3d`, which has no snapshots or regions. The layered file passed at 1.5 and 2 only in manual runs (§15.20).
5. **§6's "backend RPC round trip ≤ 5 ms (small call)" has never had a harness row.**
6. **§6's large unstructured / tetrahedral datasets do not exist** (§15.2: no result carries unstructured geometry). The exit table says so, and uses the structured 1M grids.
7. **One unexplained shell-test failure** (§15.20). It came right after a build, with no Qt Test report.
8. **The full fast suite last ran after S5; the slow gate battery has not run in P1.** The repo rules require the slow battery before a milestone completion claim.
9. **Two §15.4 readings need the user's sign-off, not a quiet choice:**
   - volume orbit: 3.1 ms while dragging, but 42 ms for the still frame drawn when the drag stops;
   - pan p50 doubled since S3 (p95 unchanged, far under budget).

#### Steps, in order

| Step | Content |
|---|---|
| S8a | **Big files, bounded.** Read by memory-mapping instead of into a buffer, so an open holds only the arrays actually decoded (fields are decoded on demand already). Refuse, with a named error, a result whose **node count** exceeds a limit (proposed 64M nodes, ≈ 512 MB per field; decision 1). Refuse before allocating, from the axes the header declares. Measure the peak working set opening a real 2 GB result (a synthetic grid) and a 2 GB non-zip file. |
| S8b | **Deleted or replaced while open.** With a result open, delete its file, then ask for: a derived map, an export, a field switch, and playback. Each either works from memory (field switch, playback: the data is already read) or reports the backend's "result file not found". Also: replace the file with another mesh; the derived map must refuse through `setDerivedField`'s axes check with a named error, not crash. |
| S8c | **Fuzzing the reader.** 2000 seeded mutations of a real 3D sweep result: bit flips, truncations, and edits to the zip directory, the `.npy` headers and the JSON metadata. Each is run through `tcad_npz_dump` in its own process. The gate: every exit is 0 (it parses) or 1 (a named `NpzError` / `ResultSchemaError`), with no crash and no hang (10 s each). |
| S8d | **Soak.** One window opens the 2D MOSFET, the layered 3D file and the 1M grid in turn, 30 times, switching fields and turning every 3D layer on and off. The gate: working-set growth after the first cycle stays under a measured bound (reported), and there are 0 GL re-inits. |
| S8e | **The §15.5 end-to-end scenario, as one test with synthesized input** (`QTest` mouse, key and drop events on the real widgets). File dialogs are the one exception, bypassed through the methods they call, as S3 does. |
| S8f | **One named test per 2D parity item**: field linear, field log, doping signed, Ec/Ev/EFn/EFp, recombination, contours on/off, mesh lines on/off, hover raw value, Fit/Reset, range Auto/Manual/Locked, derived map missing a field, backend error. Existing tests are split, not duplicated. |
| S8g | **HiDPI with every layer:** the layered 3D file joins `test_desktop_hidpi.py`'s selftest runs at 1, 1.5 and 2. |
| S8h | **Flake hunt:** the shell suite run 20 times, immediately after a build and cold. Any failure is kept with its report, then fixed, or recorded with its cause. |
| S8i | **Bench:** a `system.ping` round-trip row (p50/p95 over 200 calls), then one full quiet run re-recorded as P1's table. |
| S8j | **Suites:** the full fast suite and the slow gate battery, 4 workers each, run separately (repo rule). |
| S8k | **Write-up:** §15.24 results and the §15.8 exit checklist, item by item, each with its evidence. Then the user's sign-off (decision 4). |

#### Gates

- S8a: a 2 GB non-zip file is refused with the reader's error and a peak working set under 64 MB above idle. An over-limit result is refused naming its node count and the limit. A result under the limit opens with a peak no higher than (sum of the arrays decoded) + 64 MB.
- S8b: every action named above either succeeds or gives a named error; the app keeps working.
- S8c: 2000 of 2000 mutations exit 0 or 1 within 10 s each.
- S8d: 0 GL re-inits; the working-set growth is reported and bounded.
- S8e–S8g: the new tests pass. Mutations: a scenario step skipped, and a parity test pointed at the wrong field kind, must fail.
- Invariants: clean `/W4` build, the full fast suite and the slow battery green, zero warnings.

#### Decisions (defaults proposed; say if you want otherwise)

1. **Size limit:** refuse results above **64M nodes** (the 1M bench grids are 64× smaller). Also memory-map the reader. The alternative is no limit, only the mapping.
2. **Volume budget:** accept "orbit ≤ 33 ms" as met by the **drag** frame (3.1 ms), with the still frame at rest (42 ms at 100³) reported, not gated. The alternative is to gate the still frame too, by resampling the volume or lowering the full-quality sample rate.
3. **`viewer3d.py`'s arrow bugs** (7.9e6× the device; mispaired thinning, §15.20). Default: **fix them in S8** as the bug fixes §9 allows for the frozen QML/PyVista side, with a test that pins the pairing and the length. The alternative is to leave them.
4. **Exit:** P1 closes only with your sign-off on the §15.8 checklist (§15.8's last item).

#### Out of scope

- CI for the desktop app (`ci.yml` builds no desktop target; it needs a GL runner);
- packaging (P5);
- P2 views.

### 15.24 S8 results and the P1 exit checklist (2026-09-26)

S8 landed (uncommitted), with a clean MSVC `/W4` build.

- **Qt Test:** `tcad_desktop_shell_tests` 61 passed.
- **Test files:** every desktop test file is green, with zero warnings; the new one is `gui/tests/test_desktop_hardening.py`.
- **Full suites:** see the exit checklist below.

**Review revisions made while implementing** (each measured):

1. **S8a: not memory-mapping.** A mapping keeps the file open, and on Windows an open or mapped file cannot be deleted or replaced. That would break S8b's own probe, and the solver re-writing a result the user has open. The reader instead:
   - reads the archive's tail and central directory first;
   - refuses, before reading any array, when their total exceeds the limit (default ¾ of the free physical memory);
   - reads each array straight into its own buffer, and moves that buffer into the array without a second copy.

   The file closes when `open()` returns.
2. **S8a gate tightened.** The plan's "peak ≤ arrays + 64 MB" let the pre-S8 whole-file-buffer mutant through on the ~61 MB test file (its second copy fit in the margin). The measured reader overhead is ~0.3 MB, so the gate is now arrays + max(16 MB, 10%), and the mutant is caught.
3. **S8b found a quieter bug than deletion.** A file replaced by one on the **same mesh** passed the derived map's axes check, so bands or R of the new file were shown over the old result. The app now stamps the result file's size and modification time at open. Every backend call on it is refused with a named reason if the file was deleted or changed:
   - "…was deleted after it was opened…";
   - "…changed on disk after it was opened… Reopen it."
4. **S8c: the fuzzer's first "crashes" were in the tool, not the reader.** 53 of 2000 mutants killed `tcad_npz_dump` (0xC0000409). A mutated entry name or dtype put invalid UTF-8 into the reader's error message, and nlohmann's `dump()` threw while printing that rejection. The tool now prints with the replace handler, and reports any non-`NpzError` exception as exit 4, so the gate would name a real one. After that, 2000 of 2000 exit 0 (parsed) or 2 (named rejection).
5. **S8h: the "flake" hunt found a test defect.** The first 20-run batch failed 19 times, always the new scenario's hover step. `QTest::mouseMove` also moves the REAL cursor on Windows, so the move went to whichever window was on top at that screen point (another app window was open). The step now sends the `QMouseEvent` to the view itself. The next 20 runs: 20 of 20 passed. S6's unexplained single failure (no report) did not recur in those 40 runs; it stays unexplained.

**What landed**
- **S8a**
  - `NpzFile::open(path, max_array_bytes)` with `NpzSource` (file or memory), `default_limit()` and `array_bytes()`.
  - `ResultModel::kMaxNodes` = 64M, checked straight after the axes.
  - `tcad_npz_dump --open-only [--max-bytes N]`, which reports the reader's peak working set.
- **S8b:** `MainWindow::resultFileUnchanged`, called before `requestDerived` and `runExport`.
- **S8c:** the fuzz test (five mutation kinds: bit flips, truncations, zip-directory edits, and `.npy` header and JSON-metadata edits re-zipped with correct CRCs so they reach the parsers).
- **S8d:** `tcad_desktop --soak <files> --cycles N`.
- **S8e:** `endToEndScenarioWithSynthesizedInput`.
- **S8f:** nine `parity2d*` tests (the three other checklist items already had their own: `dopingGetsTheSignedMap`, `derivedEntryNeedsItsFields`, `backendFailureIsNamedAndTheViewStays`). The earlier combined tests stay as integration flows.
- **S8g:** the layered 3D file in the HiDPI selftest runs.
- **S8i:** a `ping_round_trip` row in `--bench-backend`.
- **Decision 3:** `viewer3d.glyph_sources`. It thins on real nodes, with the first node per tolerance-sized bin, so every arrow carries its own vector. The longest arrow equals the spacing. Three tests pin this in `test_viewer3d.py`. The file is CRLF, and that was preserved: 0 bare-LF lines.

**Gates**

| Gate | Result |
|---|---|
| 2 GB non-zip file: refused from its tail | refused; peak +0.3 MB |
| A result opens holding one copy of its arrays | 100³ layered: +114.7 MB for 114.4 MiB of arrays (~0.3 MB overhead) |
| Over the byte limit: refused before reading, naming both sizes | met; peak +0.3 MB |
| Over 64M nodes: refused naming the count and the limit | met (83,886,080 nodes) |
| Deleted while open: field switch, hover, playback work from memory; derived map and export refused, named | met |
| Replaced while open (same mesh): derived map refused ("changed on disk"), nothing fetched | met |
| Fuzz: 2000 mutations exit 0 or 2 within 10 s | met |
| Soak, 60 cycles (MOSFET, layered 3D, 1M grid): 0 GL re-inits, no upward memory trend over the last 20 | met. A 100-cycle probe: private memory peaks at 755 MB while caches warm, then falls back and holds at 530–540 MB |
| §15.5 scenario with synthesized input, as one test | met, including the double-click that floats a dock |
| One named test per 2D parity item | met (12 items) |
| HiDPI at 1, 1.5 and 2 with every 3D layer | met |
| Shell suite 20× in a row | 20 of 20 (after the test fix) |

**Mutations** (built, run and reverted by one script; nothing left behind; the restored build is clean):

| Mutant | Caught by |
|---|---|
| reader reads the whole file into a buffer again | `test_a_result_opens_holding_one_copy_of_its_arrays` (after revision 2) |
| node limit not enforced | `test_a_mesh_over_the_node_limit_is_refused` |
| a non-`NpzError` escapes the `.npy` header parser | `test_the_reader_survives_2000_mutations` |
| result stamp not checked | `replacedResultIsNotMixedWithTheShownOne` |
| the step-forward button does nothing | `endToEndScenarioWithSynthesizedInput` |
| R read as a generic field | `parity2dRecombinationAlwaysLog` |
| `viewer3d` arrows scaled by \|J\| again | `test_glyph_longest_arrow_is_the_spacing_not_millions_of_devices` |
| `viewer3d` arrows paired with a neighbour's vector | `test_glyph_sources_sit_on_nodes_carrying_their_own_vector` |

**P1's bench table** (the final quiet run: 1200 × 800, DPR 1, RTX 5060 Ti, CPU idle at 3%; p50 / p95 ms):

| Row | 2D MOSFET | 3D resistor | 2D 1000×1000 | 3D 100³ |
|---|---|---|---|---|
| pan | 2.9 / 3.0 | 2.9 / 3.1 | 2.9 / 3.1 | 2.8 / 3.1 |
| zoom | 2.9 / 3.1 | 2.9 / 3.0 | 0.9 / 1.0 | 0.6 / 0.7 |
| orbit | — | 2.9 / 3.0 | — | 0.6 / 0.7 |
| field switch | 2.8 / 3.7 | 2.6 / 3.6 | 12.8 / 13.7 | 6.2 / 6.6 |
| contours on | 1.2 / 3.3 | — | 9.9 / 15.9 | — |
| mesh lines toggle | 0.9 / 1.1 | — | 1.1 / 1.4 | — |
| slice drag | — | 0.7 / 2.9 | — | 1.2 / 1.3 |
| isosurface level | — | 0.7 / 0.7 | — | 2.5 / 2.6 |
| volume orbit, drag | — | 1.1 / 1.2 | — | 5.4 / 5.7 |
| volume orbit, still | — | 6.0 / 7.5 | — | 42.6 / 46.2 |
| playback step | — | — | — | 7.9 / 8.1 |
| streamline rebuild | — | 3.5 / 4.1 | — | 38.5 / 38.8 |
| glyph rebuild | — | 3.5 / 4.7 | — | 98.9 / 102.5 |
| crop change | — | 0.8 / 1.1 | — | 10.8 / 11.2 |
| exploded toggle | — | — | — | 10.2 / 10.5 |
| dock float / redock | 23.2 / 24.9 | 23.4 / 24.3 | 22.9 / 23.4 | 24.8 / 26.6 |
| layout restore (startup only) | 49.8 / 53.7 | 50.1 / 53.2 | 80.3 / 86.4 | 53.7 / 58.3 |
| reset layout (0 GL re-inits) | 35.7 / 37.5 | 35.9 / 36.1 | 34.4 / 36.8 | 37.2 / 39.2 |
| hover lookup, mean | 0.001 | 0.007 | 0.002 | 0.008 |
| open result | 18.0 | 16.4 | 145.2 | 148.3 |
| cold start to first frame | 580 | 482 | 611 | 619 |

- **Backend** (`--bench-backend`, the MOSFET):
  - `system.ping` round trip 0.036 / 0.060 ms (p50 / p95; 200 calls). An independent Python client over the same pipes measures 0.019 ms p50.
  - Cold start to first reply 59 ms.
  - Warm-up 429 ms, after which the first map takes 5.3 ms.
- **The 100³ open** went 195 → 148 ms from S6: the reader no longer copies the whole file.
- **Pan/zoom p50 ≈ 2.9 ms** on the small results, with p95 the same: a flat per-frame floor, far under budget, not investigated.

**The §15.8 exit checklist**

| Item | Status | Evidence |
|---|---|---|
| Every slice's exit gate met | met | §15.10, 15.12, 15.14, 15.16, 15.18, 15.20, 15.22, and above |
| Every §6 / §15.4 view budget on the reference datasets, including the 1M grids | met, with one reading for you to confirm (decision 2) | Table below |
| Parity checklist complete, one test per item | met | 2D: 12 items (9 `parity2d*` + `dopingGetsTheSignedMap`, `derivedEntryNeedsItsFields`, `backendFailureIsNamedAndTheViewStays`). §10.3: isosurface, colour maps, volume and presets, glyphs, streamlines, playback, exploded view (§15.20), VTU/PVD export and Open in ParaView (§15.22) |
| Full suite green with zero **new** warnings; C++ unit tests green; clean `/W4` | met | Fast suite (4 workers): 2342 passed, 35 skipped, 2 xfailed, 0 warnings. Slow battery (4 workers): 35 passed, 1 skipped (`tetgen` not installed), **6 warnings**. All six come from `pytcad/adapt_unstructured{,3d}.py` in six adaptive-refinement slow tests ("stopped on the pass limit", "Debye-length mesh adequacy"). Those files and tests import only the numerical core, which is unchanged since 2026-09-16 (before P1), so the warnings are not new. The slow battery was never run in P1 before now. They breach the suite's own "zero warnings" invariant, and fixing them is a core change that needs its own sign-off. `tcad_desktop_unit_tests` passed; `/W4` clean |
| Bench table re-recorded here | met | Above |
| User sign-off | **given 2026-09-26** | §15.26 |

§6 and §15.4 budgets against the final run:

| Budget | Target | Worst measured |
|---|---|---|
| 2D pan/zoom frame, p95 | ≤ 16.7 ms | 3.1 |
| 3D orbit frame, p95 | ≤ 16.7 ms | 3.0 |
| hover lookup | ≤ 1 ms | 0.014 (p95, S2 phases) |
| 2D field / colour-map switch (1M), p95 | ≤ 50 ms | 13.7 |
| large 3D field switch | ≤ 200 ms | 6.6 |
| open result, ≤ 1 MB files | ≤ 100 ms | 18.0 (MOSFET, 481 KB) |
| cold start to first frame | ≤ 1.0 s | 619 ms |
| backend RPC round trip (small call) | ≤ 5 ms | 0.060 |
| slice-plane drag | ≤ 16.7 ms | 2.9 |
| isosurface level change | ≤ 100 ms | 2.6 |
| volume orbit | ≤ 33 ms | 5.7 (drag). Still frame at rest: 46.2, reported, not gated (decision 2) |
| snapshot playback step | ≤ 33 ms | 8.1 |
| streamline rebuild | ≤ 200 ms | 38.8 |
| ADS dock/undock and layout restore | ≤ 100 ms | 86.4 (restore, 1M grid, startup only); reset 39.2 |

§6's "large unstructured / tetrahedral" datasets do not exist: no result carries unstructured geometry (§15.2). The structured 1M grids stand in, as P1 has done since S2.

**Honest limits**

- **Six pre-existing slow-battery warnings** in the numerical core (above). Not P1's, but they breach the zero-warnings invariant until fixed.
- **One single failure that never recurred:** S6's unexplained shell failure (no report, straight after a build) did not recur in 40 later runs; its cause is unknown.
- **The soak's memory gate is a trend gate** (no rise over the last 20 of 60 cycles), not an absolute bound. The 100-cycle probe shows the shape: a warm-up to 755 MB private, then settling at 530–540 MB.
- **What the fuzzer reaches.** It mutates one 3D sweep result; its seeds reach the zip, `.npy` and JSON parsers (all five kinds ran), but not every code path of every accessor.
- **ParaView** is still not installed here: the launch is verified through the recording stand-in only (§15.22).
- **No CI for the desktop app:** `ci.yml` builds no desktop target, and one needs a GL runner. The desktop tests skip there.

### 15.25 ParaView removed from TCAD (2026-09-26, user decision)

The user's instruction: "Don't connect / integrate ParaView in TCAD, remove it completely." Everything that wrote files for ParaView, or started it, is gone. The dependency map came from the code graph (graphify: `export_vtu`, `export_pvd_series`, `openInParaView`, `findParaView`, `_build_export_dock` and their callers), then a text sweep.

**Removed**
- **Python library:** `gui/services/paraview_export.py`, and its tests `gui/tests/test_paraview_export.py`; the plan `PARAVIEW-EXPORT-PLAN.md`.
- **Python 3D viewer** (`gui/services/viewer3d.py`): the "ParaView Export" dock (Export .vtu, Export animation (.pvd), the ParaView path and Browse, Open in ParaView), its `QSettings("PyTCAD", "Viewer3D")` path, and the imports only it used. CRLF preserved.
- **Backend service** (`backend_service/server.py`): `export.vtu` and `export.pvd`, and their tests in `gui/tests/test_backend_service.py` (the byte-equality and named-error tests, the export half of the Qt-free test, and the exporter's import test). The Qt-free test is now stricter: the service never loads pyvista at all. The C++ client test `backendLoadsOnlyItsOwnEnvironment` no longer runs an export to load VTK.
- **Native app:**
  - `MainWindow`: File > Export result (.vtu), Export sweep animation (.pvd), Open last export in ParaView, Locate ParaView; `exportVtu`, `exportPvd`, `openInParaView`, `findParaView`, `exportFinished`, `kExportTimeoutMs`; the `paraview/path` setting.
  - `desktop/tests/fake_paraview.cpp` and its CMake target.
  - The five S7 shell tests.
  - The PVD-export step of the end-to-end scenario, and the export step of the deleted-result test (its derived-map refusal stays).
- **`examples/08_3d_umos_amr.py`:** no longer writes a `.vtu` per pass for ParaView. The grid it drew its PNG previews from stays, as `_preview_grid()`. CRLF preserved.
- **Docs:** `ARCHITECTURE.md`'s item is marked removed; `DESIGN.md` no longer names ParaView as a reference; `desktop/README.md`; this plan's status, §10.3 and the §15.21 / §15.22 headings.

**Kept**
- **The resultFileUnchanged guard (S8b):** it now protects the derived maps only.
- **The pyvista-based viewers themselves.** The glyph fix (S8 decision 3) and `grid_builders.py` are not ParaView; that module's docstring no longer mentions the exporter.
- **Historical text** in §15.3–15.24 that describes S7 as it was is left as the record, now pointing here.

**Effect on P1's exit checklist (§15.24)**
- The §10.3 parity list loses "VTU/PVD export and open in ParaView", so the checklist item "one test per item" is unaffected: the removed feature's tests went with it.
- The end-to-end scenario ends at playback instead of a PVD export.

**Verification**
- Native app rebuilt with a clean `/W4`. Qt Test: shell 56 passed (61 minus the five S7 cases), backend 22 passed.
- The 20 desktop-related test files: 379 passed, zero warnings (the deleted `test_paraview_export.py` is no longer among them).
- A final text sweep, and the rebuilt code graph, find no ParaView reference in any code file.
- **One intermittent failure:** `test_a_soak_keeps_memory_and_the_gl_context` (S8d) failed once, inside the full batch, right after the fuzz test. It passed in the 11 runs since: 6 alone, 3 with its file, and the full batch again. Its failure message was not captured (my output filter cut it). It exercises no export code. Recorded, not explained.
- Full fast suite after the removal (4 workers): 2329 passed, 35 skipped, 2 xfailed, zero warnings. That is 13 fewer than S8's 2342: exactly the deleted ParaView/export tests.

### 15.26 P1 closed (2026-09-26)

The user signed off P1's exit checklist (§15.24), after ParaView's removal (§15.25). In their words: "Sign-off on the P1 exit checklist". This is the checklist's last item; P1 is closed.

Recorded with the sign-off:
- **Slow-battery warnings: left as they are.** The six warnings from the numerical core's adaptive-refinement tests (`pytcad/adapt_unstructured{,3d}.py`, pre-dating P1) are not fixed, by the user's decision ("Whether to fix the six slow-test warnings in the numerical core. not required").
- **Volume orbit budget:** the checklist's reading of §15.4 stands, as signed off with it: met by the drag frame; the still frame at rest reported, not gated (§15.23 decision 2).
- **Nothing is committed** (the user commits and pushes).

**Open, carried past P1**
- S8d's single unexplained soak failure (§15.25);
- S6's single unexplained shell failure (§15.20);
- no desktop CI (it needs a GL runner).

**Next:** P2 (not started) and the remaining §12 decisions.



## 16. P2 — Plots: detailed plan (2026-09-26, proposed)

§9 defines P2 as PlotView plus every curve-based viewport mode (series, cv, transient, ac, convergence, bands, recombination, cut) with family and comparison overlays. Its exit: every §10.2 mode has a C++ equivalent and an image test. This section makes that concrete against the tree.

### 16.1 Review findings (from `mpl_canvas_item.py`, the result grammar and the backend, before any P2 code)

1. **The native app shows nothing for a 1D result today.** `FieldView` hides for 1D ("curves are PlotView, P2"). Opening the diode should plot its fields, so P2 gains a **1D field curve** mode: the QML view's `ax.plot(x, field)` branch, with log.
2. **Every curve mode's data is already in the result file** (checked on real files):

   | Mode | Source in the file | QML draw path |
   |---|---|---|
   | series (I-V) | `sweep__*` block, `quantity` ≠ capacitance | `_draw_series` |
   | cv | `sweep__*` block, `sweep__meta.quantity == "capacitance"` (`moscap_runner.py` writes it) | `_draw_cv` |
   | transient | `transient__*` block | `_draw_transient` |
   | ac | `ac__*` block | `_draw_ac` |
   | convergence | `converge__trace` + `record__meta` (`RunRecord`) | `_draw_convergence` |
   | bands, recombination (1D) | the backend's `analysis.band_map` / `recombination_map`, verified on the 1D diode: 4 fields / R on its 240 nodes | `_draw_bands` / `_draw_recombination`, 1D branch |
   | cut | a 2D field, sliced at the nearest row or column | `_draw_cut` → `extract_line_cut` |
   | 1D field | `field__*`, 1D | the 1D branch of `_build_figure` |

   The C++ `ResultModel` validates these blocks (S1), but exposes only their sizes. P2 adds typed accessors, contract-tested against `NpzResultStore` / `RunRecord`, as S1 did for fields.
3. **Families and comparisons come from runs in the QML GUI**:
   - `FamilySweepController` runs one job per stepped value;
   - the M9 model on/off comparison and the backend comparison (`runBackendComparison`) run a second job.

   The native app runs no jobs until P3. In a viewer, an overlay is an **opened result file**: one comparison sweep (dashed, with a label) and a family of N sweeps (solid, one colour each, with a legend). Producing families and comparisons by running is P3's. (`record__meta` stores no stepped bias, so a family curve's label is its file name, editable.)
4. **Structure, mesh, process and the doping preview are in §10.2 but are not curves.** They draw a `DeviceSpec` or a process state, not a result, and belong with the StructureEditor (P4). P2's exit therefore reads "every **curve** mode of §10.2"; the other four move to P4's exit explicitly.
5. **The QML hover readout attaches the y value's unit to x**: `f"{label}: {y:.3e} @ {x:.2f} {unit}"` prints e.g. "device: 1.2e-05 @ 0.50 A/cm^2". Its snapping rule is sound (the nearest sample by normalised distance in DISPLAYED coordinates, log included; nothing past 0.08; the physical value reported). See decision 3.
6. **The AC twin axis is not hoverable in QML** (a documented limitation): only C(f) snaps; G(f) on the right axis does not.
7. **Colours are hard-coded** in the QML canvas: a 7-colour series palette, stage colours, the comparison purple, the rejected-step red. They become data-colour tokens in `theme/tokens.hpp`, the same "data colours, same in both schemes" rule as the region palette (S6), so the no-hard-coded-colour gate holds.
8. **Line-cut computation.** §9 says cuts come from the backend's `extract_line_cut`. That function is a nearest-row/column slice of an array the app already holds (no physics). A round trip per slider step would add latency for nothing. See decision 1.
9. **No golden images** (the §15.5 rule: machine-specific). An "image test" is a render to an offscreen image plus pixel and structure probes (below), as S5/S6 did for maps.

### 16.2 Design

- **PlotView** (`desktop/src/views/plot/plot_view.{hpp,cpp}`) is a QWidget painted with QPainter (§5.2). It draws:
  - a model of series: x, y, style (line / markers / dashed), colour token, axis (left or right), label;
  - linear or log x and y, and an optional right-hand y-axis (AC);
  - NaN as a gap, never interpolated; on log axes, non-positive values are absent (the QML rule);
  - markers when a series has ≤ 40 points (the QML rule);
  - legend, title, grid, and per-pixel-column min/max decimation above ~4× the plot width in points;
  - device-pixel rendering (HiDPI), and theme tokens only.
- **Ticks:** a port of matplotlib's `AutoLocator` (MaxNLocator with steps [1, 2, 2.5, 5, 10] and `nbins="auto"`) and `LogLocator` (decades, with minor ticks), reusing S5's MaxNLocator core. Contract-tested against matplotlib's own tick values, so the axes read like the QML view's (decision 4).
- **View control:**
  - fit: the x range from the data, y from all data, with matplotlib's 5% margins;
  - zoom about the centre (wheel), pan (drag), reset to home;
  - hover snaps to a real sample (finding 5's rule, decision 3's format).
- **The central area becomes a stack:** `FieldView` or `PlotView`, switched by a **View mode** selector (a toolbar combo plus menu). The selector offers only the modes the open result supports (finding 2's table). The default is the field map (2D/3D) or the 1D field curve (1D). `FieldView` is placed in the stack before its GL context exists, so switching views never reparents it (the S6 GL lesson). A test pins 0 GL re-inits across view switches.
- **A Plot panel** (dock, tabbed with Display):
  - the series channel (series mode);
  - log y;
  - cut orientation and position (a slider snapping to node coordinates, showing the actual node, as the QML title does);
  - overlays: Add comparison… / Add to family…, the list with labels, remove.

### 16.3 Steps, in order

| Step | Size | Content |
|---|---|---|
| P2-S1 | S | **Typed accessors** in `ResultModel`: sweep (voltages, converged, channels, unit, contact, quantity), transient (times, channels, unit, contact), AC (freqs, C, G, units, port) and the run record's trace (stages, metrics, converged). Contract gate: they equal `NpzResultStore.sweep_result()` / `transient_result()` / `ac_result()` / `run_record()` on real files, including a C-V result from `moscap_runner` and a transient and an AC run. |
| P2-S2 | M | **PlotView core**: axes, the tick port with its contract test, series styles, gaps, log, twin axis, legend, decimation, view control, hover, theme tokens (finding 7), HiDPI. Bench rows and pixel probes (below). |
| P2-S3 | M | **The modes**: 1D field, series (with channel), cv, transient, ac, convergence (stage colours, rejected-step marker, cumulative iteration axis, log y), and 1D bands and recombination through the backend (cached per result, like S5's maps). Each keeps the QML empty-state text. The view-mode stack and selector. |
| P2-S4 | S | **Line cut** (2D): decision 1's implementation, the cut controls, and — new — the cut's line drawn on the field map while in cut mode. |
| P2-S5 | S | **Overlays** from files (finding 3): one comparison sweep (dashed) and a family. Both must share the open result's swept contact and channel; otherwise refused with the reason. |
| P2-S6 | M | **Hardening and write-up**: one named test per curve mode, image probes per mode at scales 1, 1.5 and 2, adversarial files (a sweep with every point unconverged, an all-NaN channel, a one-point sweep, a trace with no steps, AC with one frequency), bench, the full fast suite, results as §16.6. |

### 16.4 Gates

- **Contracts:**
  - the S1 accessors equal the Python store's on real files;
  - the tick port equals matplotlib's ticks over ≥ 100 generated linear and log ranges;
  - the cut equals `extract_line_cut` on uniform and graded meshes, both orientations, including the reported actual position.
- **Image probes** on offscreen renders (no golden images):
  - for every series, a pixel at the projected position of a sample (away from other series) has that series' colour;
  - a NaN sample leaves no line through its neighbourhood;
  - with ≤ 40 points, markers are present;
  - the log axis carries no non-positive sample;
  - AC's G curve sits on the right axis's scale;
  - ticks are drawn at the tick port's values;
  - the legend and title are present.
- **Hover:** at the pixel of every plotted sample of a probe series, the readout names that sample's raw value; past the 0.08 snap distance, nothing.
- **View switching:** every mode reachable for a result is selectable; modes a result cannot show are absent; 0 GL re-inits across 20 switches.
- **Parity checklist:** one named shell test per curve mode, plus the 1D field mode, overlays and cut.
- **Mutations:** a gap interpolated, the log axis fed non-positive values, the family drawn on the wrong channel, a cut off by one node, and ticks at naive steps, must each fail their gate.
- **Bench:**
  - pan/zoom frame at 1,000-point and 100,000-point series ≤ 16.7 ms p95 (§5.2's expectation, now measured);
  - hover ≤ 1 ms;
  - mode switch ≤ 50 ms;
  - 1D bands (warm backend) reported.
- **Invariants:** clean `/W4` build, every desktop test file green, the full fast suite green with zero warnings.

### 16.5 Decisions (defaults proposed; say if you want otherwise)

1. **Line cuts in C++**, gated against `extract_line_cut`, instead of a backend call per slider step (finding 8). §12 decision 5 (where GUI computations live) stays open for physics. This is array slicing, not physics.
2. **Overlays come from opened result files** (finding 3). Running families and comparisons arrives with P3's job runner.
3. **The hover readout is fixed**, not copied: "device: 1.234e-05 A/cm^2 @ 0.500 V" — the y value with its unit, then x with its unit (V, s, Hz, um, iteration). This is the same kind of deliberate improvement as S5's signed doping map.
4. **Ticks port matplotlib's locators exactly** (contract-tested), so the native axes read like the QML ones. The alternative is simpler nice-number ticks without a contract.
5. **AC hovers both curves**, C on the left axis and G on the right (finding 6), instead of copying QML's C-only limitation.
6. **P2's exit covers every curve mode**; structure, mesh, process and the doping preview move to P4's exit (finding 4).

### 16.6 Out of scope

Running anything (P3); structure, mesh and process views (P4); data export (CSV or images); 3D line cuts (the QML cut is 2D only); new physics.
