# Native desktop application — plan (proposed M53)

Status: **PROPOSED, 2026-09-25. P0 IMPLEMENTED the same day** at the
user's request ("review the plans again and implement P0"). The review
revisions are in §13 and the P0 results and exit-gate status are in §14.
**P1 (§15) APPROVED 2026-09-25** by the user, with the §15.4 targets as
written. S1 (§15.10), S2 (§15.12), S3 (§15.14), S4 (§15.16) and S5
(§15.18), S6 (§15.20), S7 (§15.22) and S8 (§15.24) landed
2026-09-25/26, uncommitted; S7 (export and ParaView) was then REMOVED at the
user's decision (§15.25). **P1 CLOSED 2026-09-26** with the user's sign-off
on the exit checklist (§15.24, §15.26). **P2 (§16, reviewed §16.7) APPROVED
2026-09-26** with its default decisions ("start"); **P2 CLOSED 2026-09-26** at the user's decision ("close P2"; S1-S6: §16.8-§16.16), uncommitted; the full fast suite and timing pass owed by §16.17 were run after P3-S2 (§17.9). **P3 APPROVED 2026-09-26** (§17, reviewed §17.7, decisions 1-9 as proposed); **P3-S1 to P3-S6 landed** (§17.8-§17.15; S5 closed 2026-09-27), uncommitted. P3-S7 onward,
and P4 and later, are not started. The
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
- ~~S8d's single unexplained soak failure (§15.25)~~ — **explained and fixed 2026-09-26** (§16.10): a one-step memory plateau read as a trend by a 20-cycle least-squares slope; it predates S2 (pre-S2 A/B); the gate is now a Theil–Sen slope over 40 cycles;
- S6's single unexplained shell failure (§15.20) — seen again 2026-09-26 under the full suite's load and identified as a crash (`0xC0000005`, between two window tests); not reproduced in 20 solo runs; the test now keeps the child's stack trace (§16.10);
- no desktop CI (it needs a GL runner).

**Next:** P2 (not started) and the remaining §12 decisions.



## 16. P2 — Plots: detailed plan (2026-09-26, reviewed §16.7; APPROVED with the default decisions)

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
5. **The QML hover readout attaches the y value's unit to x**: `f"{label}: {y:.3e} @ {x:.2f} {unit}"` prints e.g. "device: 1.2e-05 @ 0.50 A/cm^2". See decision 3. **Its snapping rule is not sound either** (corrected in review, §16.7):
   - it takes the sample nearest in **x**, then applies the 0.08 cut-off to that one sample's normalised distance; a neighbouring sample nearer the cursor on a steep curve never wins;
   - **one NaN in a series disables the cut-off.** `np.max` over the series is NaN, so every score is NaN and `NaN > 0.08` is false. Probed on `_hover_series` directly: an 11-point sweep with one NaN point, cursor far off the curve, printed `'device: 0.000e+00 @ 0.00 A/cm^2'`; the same series without the NaN printed `''`. Every sweep with an unconverged point has NaN, so this is the common case;
   - only the log-y toggle is honoured in "displayed coordinates"; AC's log x and convergence's and recombination's log y are snapped linearly.

   The native rule is decision 9. The NaN defect is a bug fix the QML GUI may take under the transition rule (§9).
6. **The AC twin axis is not hoverable in QML** (a documented limitation): only C(f) snaps; G(f) on the right axis does not. **Convergence is not hoverable at all** (`_draw_convergence` never calls `_remember_series`), and neither are family or comparison curves (only the primary series is remembered).
7. **Colours are hard-coded** in the QML canvas: a 7-colour series palette, stage colours, the comparison purple, the rejected-step red, and `_style_axes`'s four chrome colours (panel, grid, spines, text). The data colours become data-colour tokens in `theme/tokens.hpp`, the same "data colours, same in both schemes" rule as the region palette (S6); the chrome colours map to existing tokens (`Base`, `Border`, `TextDim`, `Text`), not new ones. The stage colours `#61bd6d` / `#d9a441` already equal `Ok` / `Warning` (dark). The no-hard-coded-colour gate then holds.
8. **Line-cut computation.** §9 says cuts come from the backend's `extract_line_cut`. That function is a nearest-row/column slice of an array the app already holds (no physics). A round trip per slider step would add latency for nothing. See decision 1.
9. **No golden images** (the §15.5 rule: machine-specific). An "image test" is a render to an offscreen image plus pixel and structure probes (below), as S5/S6 did for maps.
10. **QML has three log rules, not one** (added in review):
    - series, the comparison curve and 1D recombination: a log axis of |y|, so a negative value shows as its magnitude and only an exact zero is absent;
    - 1D field and cut: a **linear** axis of `log10(max(|v|, 1e-30))` (`_maybe_log`), so a zero is drawn at −30, not absent;
    - family curves: **signed** values on the primary's log axis (`_draw_series`, the family loop), so a negative stepped current silently disappears — a QML bug, not a rule.

    The native rule is decision 8.
11. **QML's view control is linear and partly unfitted** (from reading, not run):
    - `zoom()` and `pan()` scale the limits in data units, so zooming out on AC's log frequency axis can drive the lower limit negative;
    - `fit()` has no ac, convergence, cut, bands or recombination branch; they fall through to the mesh x extent in µm, which the pan/zoom fast path then applies to the plotted axis (AC's frequency axis, a vertical cut's y axis).

    Not ported: native fit is per mode, from the plotted data, and zoom/pan act in the axis's own (linear or log) coordinates (§16.2).
12. **QML plots the comparison against the primary's voltages** (`ax.plot(V, Ic)`), which only works because its comparison job reuses the primary's ramp. An opened file need not (finding 3), so every overlay plots against its own x.

### 16.2 Design

- **PlotView** (`desktop/src/views/plot/plot_view.{hpp,cpp}`) is a QWidget painted with QPainter (§5.2). It draws:
  - a model of series: x, y, style (line / markers / dashed), colour token, axis (left or right), label;
  - linear or log x and y, and an optional right-hand y-axis (AC);
  - NaN as a gap, never interpolated, and never bridged by decimation;
  - log y shows |y| on a true log axis, and an exact zero leaves a gap (decision 8) — one rule for every mode and every series, overlays included;
  - markers when a series has ≤ 40 points (the QML rule);
  - legend, title, grid, and per-pixel-column min/max decimation above ~4× the plot width in points; decimation is drawing only — hover and fit read the raw samples;
  - device-pixel rendering (HiDPI), and theme tokens only.
- **Ticks:** a port of matplotlib's `AutoLocator` (MaxNLocator with steps [1, 2, 2.5, 5, 10]) and `LogLocator` (decades, with minor ticks), reusing S5's MaxNLocator core (decision 4). The contract is on the locators' `tick_values(vmin, vmax)` at a **given** `nbins` / `numticks`: matplotlib's `nbins="auto"` derives the count from the axis length in pixels, font size and DPI, which the native app does not share, so tick **counts** could not match anyway. The native count is its own rule — the pixel length divided by a minimum label spacing from the font's metrics — stated in code and gated separately (labels never overlap). The LogLocator contract includes decade striding on wide ranges (convergence residuals span 10+ decades) and minor-tick labelling when the range is under one decade.
- **View control:**
  - fit, per mode, from the plotted data (all series, overlays included): x and y with matplotlib's 5% margins, in the axis's own coordinates (a log axis margins in log10);
  - zoom about the centre (wheel), pan (drag), reset to home — in the axis's own coordinates, so a log axis never reaches a non-positive limit (finding 11);
  - hover snaps to a real sample (decision 9's rule, decision 3's format), primary and overlay curves alike, with the curve's label in the readout.
- **The central area becomes a splitter**, not a stack (decision 7): `FieldView` and `PlotView` sit in one `QSplitter` for the app's lifetime, and a **View mode** selector (a toolbar combo plus menu) shows one or the other — or, in cut mode, both, the map with the cut's line over the cut's curve. The selector offers only the modes the open result supports (finding 2's table). The default is the field map (2D/3D) or the 1D field curve (1D). `FieldView` is placed in the splitter before its GL context exists and is only ever hidden or shown, never reparented (the S6 GL lesson). A test pins 0 GL re-inits across view switches, cut mode included.
- **A Plot panel** (dock, tabbed with Display):
  - the series channel (series mode);
  - log y;
  - cut orientation and position (a slider snapping to node coordinates, showing the actual node, as the QML title does). The cut slices whatever 2D map the field view shows — a stored field, or a backend-derived Ec or R map (S5) — which is wider than QML (stored fields only); log follows decision 8;
  - overlays: Add comparison… / Add to family…, the list with labels, remove. An overlay is accepted only when its swept contact, channel, **unit** and **quantity** (current or capacitance) match the open result's; otherwise it is refused with the mismatching item named. Each overlay plots against its own voltages (finding 12).

### 16.3 Steps, in order

| Step | Size | Content |
|---|---|---|
| P2-S1 | S | **Typed accessors** in `ResultModel`: sweep (voltages, converged, channels, unit, contact, quantity), transient (times, channels, unit, contact), AC (freqs, C, G, units, port) and the run record's trace (stages, metrics, converged). Contract gate: they equal `NpzResultStore.sweep_result()` / `transient_result()` / `ac_result()` / `run_record()` on real files, including a C-V result from `moscap_runner` and a transient and an AC run, **plus a synthetic sweep with `sweep__converged` partly False**, so the store's NaN masking of unconverged points is exercised (real files may have none). |
| P2-S2 | M | **PlotView core**: axes, the tick port with its contract test, series styles, gaps, log, twin axis, legend, decimation, view control, hover, theme tokens (finding 7), HiDPI. Bench rows and pixel probes (below). |
| P2-S3 | M | **The modes**: 1D field, series (with channel), cv, transient, ac, convergence (stage colours, rejected-step marker, cumulative iteration axis, log y, hoverable — new), and 1D bands and recombination through the backend (cached per result, like S5's maps). Each keeps the QML empty-state text. The view-mode splitter and selector (decision 7). |
| P2-S4 | S | **Line cut** (2D): decision 1's implementation, the cut controls, and — new — the cut's line drawn on the field map, visible beside the curve in cut mode's split (decision 7). |
| P2-S5 | S | **Overlays** from files (finding 3): one comparison sweep (dashed) and a family, each on its own voltages. Contact, channel, unit and quantity must match the open result's; otherwise refused with the mismatch named. Overlays hover like the primary. |
| P2-S6 | M | **Hardening and write-up**: one named test per curve mode, image probes per mode at scales 1, 1.5 and 2, adversarial files (a sweep with every point unconverged, an all-NaN channel, a one-point sweep, a trace with no steps, AC with one frequency), bench, the full fast suite, results as §16.6. |

### 16.4 Gates

- **Contracts:**
  - the S1 accessors equal the Python store's on real files;
  - the tick port's `tick_values(vmin, vmax)` equals matplotlib's `MaxNLocator` / `LogLocator` at the same `nbins` / `numticks` over ≥ 100 generated linear and log ranges, including log ranges under one decade and over ten;
  - the native tick-count rule: over a sweep of axis lengths and scales 1 / 1.5 / 2, no two tick labels overlap;
  - the cut equals `extract_line_cut` on uniform and graded meshes, both orientations, including the reported actual position and a request exactly midway between two nodes (numpy's `argmin` takes the first; so must the port).
- **Image probes** on offscreen renders (no golden images):
  - for every series, a pixel at the projected position of a sample (away from other series) has that series' colour;
  - a NaN sample leaves no line through its neighbourhood — on a ≤ 40-point series and on a series long enough to be decimated;
  - with ≤ 40 points, markers are present;
  - on a log axis, a negative sample is drawn at its magnitude and a zero sample leaves a gap (decision 8), for the primary and for a family curve;
  - AC's G curve sits on the right axis's scale;
  - ticks are drawn at the tick port's values;
  - the legend and title are present.
- **Hover:**
  - at the pixel of every plotted sample of a probe series, the readout names that sample's raw value; past the snap distance, nothing;
  - the same on a series containing NaN (finding 5's QML defect), and on a decimated series (the raw sample, not a decimated vertex);
  - on log-x AC, both C and G; on convergence; on a family and a comparison curve, each with its own label.
- **View control:** in every mode, fit shows every plotted sample; zoom out ×10 and pan by a full span on a log axis keep both limits positive; reset returns to fit.
- **View switching:** every mode reachable for a result is selectable; modes a result cannot show are absent; 0 GL re-inits across 20 switches, cut mode included.
- **Overlays:** a family or comparison file differing in contact, channel, unit or quantity is refused with the mismatch named; one with a different voltage ramp from the primary is drawn on its own voltages.
- **Parity checklist:** one named shell test per curve mode, plus the 1D field mode, overlays and cut.
- **Mutations:** a gap interpolated (and one bridged by decimation), a zero drawn at a floor on the log axis, the family drawn on the wrong channel or on the primary's voltages, a cut off by one node, hover without the NaN guard, zoom in data units on a log axis, and ticks at naive steps, must each fail their gate.
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
4. **Ticks port matplotlib's locators exactly** (contract-tested at a given `nbins` / `numticks`, §16.2), so the native axes read like the QML ones; the tick **count** is the native app's own rule, gated on non-overlapping labels. The alternative is simpler nice-number ticks without a contract.
5. **AC hovers both curves**, C on the left axis and G on the right (finding 6), instead of copying QML's C-only limitation. Convergence, family and comparison curves hover too.
6. **P2's exit covers every curve mode**; structure, mesh, process and the doping preview move to P4's exit (finding 4).
7. **The central area is a splitter, and cut mode shows the map and the curve together** (added in review). A stack shows one view, so the cut's line on the map (P2-S4) would never be visible beside its curve. The alternative is a stack, with the cut line visible only after switching back to the map.
8. **One log rule** (added in review, finding 10): log y shows |y| on a true log axis; an exact zero leaves a gap; every mode and every series, family included. This changes the 1D field and cut from QML's "log10 on a linear axis, zeros at −30" and fixes QML's signed family curves. The readout still reports the raw, signed value.
9. **Hover snapping** (added in review, finding 5): the nearest sample by normalised distance in displayed coordinates — each axis's own scale, log x included — over the finite samples of every hoverable series, normalised by the **current view's** span; nothing past 0.08. NaN samples are skipped, never scored. Exact ties (EFn and EFp coincide everywhere at equilibrium) go to the series first in legend order, and the readout lists every series tied at that sample. This replaces QML's nearest-in-x rule and fixes its NaN defect.

### 16.6 Out of scope

Running anything (P3); structure, mesh and process views (P4); data export (CSV or images); 3D line cuts (the QML cut is 2D only); new physics.

### 16.7 Review revisions (2026-09-26, before any P2 code)

A review of §16 against `gui/visualization/mpl_canvas_item.py`, `gui/services/result_store.py`, `backend_service/server.py` and `desktop/src/` confirmed findings 1–4, 8 and 9: the 1D placeholder (`main_window.cpp`, "curve views arrive with PlotView (P2)"), the C-V `quantity` stamp (`moscap_runner.py`), both `analysis.*_map` methods, `extract_line_cut` being a plain nearest-node slice, and S5's MaxNLocator core in `data/contour_levels.cpp`. It changed the plan as follows:

1. **Finding 5 was wrong.** QML's hover is nearest-in-x, not nearest-by-distance, and one NaN disables its 0.08 cut-off (probed: a far-off cursor over a one-NaN sweep printed `'device: 0.000e+00 @ 0.00 A/cm^2'`; the clean sweep printed nothing). New decision 9 and hover gates on NaN, decimated, log-x, convergence and overlay series.
2. **The log rule was misstated** (new finding 10). QML has three behaviours, one of them a bug (signed family curves on a log axis). New decision 8; the probe and mutation now name zeros and negatives separately.
3. **Cut mode could not show its own map line.** The stack became a splitter (decision 7); the GL gate covers cut mode.
4. **Overlays needed more than contact and channel** (new finding 12): unit and quantity must match too, and each overlay plots on its own voltages. QML's comparison reuses the primary's voltages.
5. **The tick contract was not satisfiable as written**: `nbins="auto"` depends on matplotlib's font and DPI. The contract is now on `tick_values` at a given count; the native count rule is gated on non-overlap. Log striding and sub-decade labelling are named in the contract.
6. **View control is in axis coordinates and fit is per mode** (new finding 11), with a view-control gate. QML's linear zoom and its fit fall-through to the mesh extent are not ported (the fall-through read from code, not run).
7. **Smaller:** decimation never bridges a NaN gap and hover reads raw samples; the S1 contract adds a synthetic partly-unconverged sweep; the cut contract adds a midway tie; convergence, family and comparison curves become hoverable; finding 7 names `_style_axes`'s chrome colours, mapped to existing tokens; the cut may slice backend-derived maps.

Decisions 1–3, 5 and 6 are unchanged. Decisions 7–9 are new and, like the others, defaults awaiting approval. **Approved 2026-09-26 with every default** (the user's "start").

### 16.8 P2-S1 results (2026-09-26)

**Built.**
- `ResultModel` (`desktop/src/data/result_model.{hpp,cpp}`) gains `has_sweep/transient/ac()`, `sweep()`, `transient()`, `ac()` and `trace()`, returning `SweepSeries`, `TransientSeries`, `AcSeries` and `TraceStep`s. They mirror `NpzResultStore.sweep_result()` / `transient_result()` / `ac_result()` / `run_record().trace`:
  - channels in archive order (the store's dict order);
  - unconverged sweep points masked to NaN, as the store does;
  - `quantity` from `sweep__meta` ("current" when absent; `moscap_runner` stamps "capacitance");
  - trace defaults as `ConvergenceStep.from_dict` (stage "?", converged True by Python truthiness);
  - a JSON null metric reads as NaN, `_draw_convergence`'s gap.
- `tcad_npz_dump` reports them under `result.series`, or `<block>_error` when an accessor fails.
- **Deliberately stricter than the store**, on files no writer produces: text `sweep__converged` is refused (numpy reads `"no"` as True), as are a non-string contact, port, stage or unit, and non-numeric iterations or metric values.

**A defect found and fixed on the way.** `parse_python_json` mapped `NaN` / `Infinity` / `-Infinity` to null. Its header said nothing the viewer reads needs them, which stopped being true with the trace: Python reads a blown-up residual as inf, and the C++ side read it as a gap. The tokens now become marker strings for nlohmann's strict parse and are turned back into NaN / ±inf afterwards.
- A genuine string that spells the marker is never captured: the marker is tried again with the next index when more marker strings come back than tokens were replaced.
- A token used as an object key is refused, as in Python.
- For the validator nothing changes: `is_python_int` of a float is false either way.

The unit tests that pinned the null mapping now pin the values, and add a marker-collision test and `{NaN: 1}` / `-NaN` rejections.

**Gates** (`gui/tests/test_desktop_contracts.py`, section 2c; all green):
- **Real runs:** the accessors equal the store's on a 1D I-V sweep, a C-V sweep from `moscap_runner`, a 1D transient and a 1D AC run. Each fixture asserts its block really exists, and the I-V run's trace really carries metrics.
- **The P1 reference results:** the same equality holds on all four (1D, 2D, 3D, 3D sweep).
- **Synthetic sweep:** unconverged points (NaN-masked), channels in an archive order different from sorted order, and a trace with null, NaN and inf metrics, a missing-fields step and a falsy `converged`.
- **Absent blocks** are null on both sides.
- **Accessors fail on access like the store** for malformed trace items.
- **Stricter refusal:** text convergence flags are refused.
- **Mutations, each rebuilt and run:** dropping the NaN mask, defaulting `converged` to False, reading a null metric as 0, sorting channels, and not restoring non-finite tokens each fail exactly one gate.

**Invariants:**
- a clean `/W4` build of every target;
- C++ unit tests 22/22;
- the contract file 102/102 (13 new);
- every desktop and backend-service test file: 263 passed, none skipped;
- the full fast suite (6 workers): **2312 passed, 37 skipped, 2 xfailed, zero warnings, 0 failed**.

**Not explained, recorded rather than hidden (S1).** The fast suite collects 2349 tests, which means 2336 at HEAD before S1's 13. That is 30 fewer than P1's close (§15.25: 2329 passed + 35 skipped + 2 xfailed = 2366), and 2 more tests skip. S1 only adds tests, and none of the skips is in a desktop or backend-service file. Where the 30 went (the commit made after P1 closed changed test files) and which 2 tests newly skip was not investigated.

### 16.9 P2-S2 results (2026-09-26)

**Built.**
- **Axis maths** (`desktop/src/views/plot/axis_ticks.{hpp,cpp}`, Qt-free). Ports of matplotlib 3.11's own code at a given tick count:
  - AutoLocator's tick values;
  - LogLocator's major and minor tick values, including decade striding and the minor locator's AutoLocator fall-back;
  - ScalarFormatter's labels and offset text (offset threshold 4, power limits (−5, 6), unicode minus);
  - LogFormatterSciNotation's labels, including which minor ticks it labels (minor thresholds (1, 0.4)).
- **Shared locator.** The MaxNLocator core moved from `contour_levels.cpp` to `data/max_n_locator.{hpp,cpp}`, with CPython float helpers in `data/pyfloat.hpp`; the contour levels now call it. S5's 80-case contour gate is unchanged and green.
- **PlotView** (`views/plot/plot_view.{hpp,cpp}`, `plot_model.hpp`). A QWidget painted with QPainter, from a `PlotModel` of series. It has:
  - linear and log axes and a right-hand y-axis;
  - NaN gaps, and decision 8's log rule;
  - markers at ≤ 40 points;
  - a legend, title, grid and offset text;
  - fit, zoom, pan and reset in each axis's own coordinates;
  - decision 9's hover and decision 3's readout.
- **Geometry** (`views/plot/plot_geometry.{hpp,cpp}`, Qt-free): the log rule, polyline clipping, column decimation, dense-column drawing and the hover search.
- **Data colours as tokens** (`theme/tokens.hpp`): the QML canvas's series palette and its comparison, rejected-step and stage colours. `theme::seriesColour` and `theme::dataColour` read them; the no-hard-coded-colour gate holds.
- **New tools:**
  - `tcad_plot_ticks` (the contract tool);
  - `tcad_desktop_plot_tests` (Qt Test, `desktop/tests/test_plot.cpp`), run by `gui/tests/test_desktop_plot.py`.

**Rules chosen while building (the plan left them open).**
- **Tick count.** matplotlib's own heuristic in logical pixels: the axis length over 3× the tick font size for x, 2× for y, clipped to 1–9 (2–9 on a log axis). It is then lowered until no two major labels overlap. A minor log label is dropped where it would overlap a placed label. matplotlib would let those overlap; here the no-overlap gate forbids it.
- **Legend.** matplotlib's `loc="best"`, the QML canvas's default. Its nine candidates are tried in matplotlib's order, and the first with the least data under it (vertices inside plus segments crossing) wins. The first version put the legend at the upper right always and hid data; the probes found it.
- **Readout x format.** `%.3f` for |x| in [1e-3, 1e4) or 0, else `%.3e`. For example: "device: 1.234e-05 A/cm^2 @ 0.500 V", "G: 3.000e-04 S/cm^2 @ 1.000e+06 Hz".
- **Snapping.** Axis lines (grid, spines, tick marks) sit on device-pixel centres, as matplotlib snaps them. Unsnapped, a 1-px tick mark was smeared over two half-lit pixels, which a probe found.

**Performance: three problems found by the bench, each measured before it was fixed.**
1. **The legend search dominated panning** (300 ms at 100k points). It clipped every data segment against each of nine candidate positions with an allocating clip. Fixed with an allocation-free segment test on points thinned to ≤ 2k per series; the view change is now ≤ 0.25 ms p95.
2. **Decimation did not run on a curve leaving the view.** Clipping ran first and cut it into short pieces, each under the threshold (48k vertices drawn at 100k points). It now decimates each gap-free segment before clipping (2,092 vertices).
3. **Qt's wide-pen antialiased stroker is the cost, not the vertex count.** Measured on the same frames:

   | Variant | 1k paint p95 | 100k paint p95 |
   |---|---|---|
   | one polyline, round joins | 10.2 ms* | 91.5 ms |
   | no line at all | 1.5 ms | 3.9 ms |
   | 1-device-px pen (the fast path) | 1.9 ms | 6.0 ms |
   | bevel joins | 7.7 ms* | 65.7 ms |
   | no antialiasing | 4.9 ms* | 20.6 ms |

   \* on the drifting bench (item 4), which understated the 1k cost.

   Two fixes, kept together:
   - a dense solid line's tall columns (≥ 3 points spread over > 2 device px) are drawn as filled bars covering their extent (`dense_columns`); the other columns stay a stroked polyline;
   - solid polylines are stroked in 8-segment chunks with round caps. One 1,000-vertex noisy polyline took 25 ms; chunked, it takes 5 ms.

   Dashed lines stay one polyline, so their pattern runs on across the joints.
4. **The bench itself misled at first.** It panned up by 0.5% of the span every frame, so the curve slid out of view and later frames got cheaper. The per-frame times showed it: 25 ms for the first ten frames, 5 ms at the end. It now alternates its pans and stays on the data; that is what exposed item 3 at 1k points.

**A defect found by mutation.** Mutating the paint to skip a NaN without ending the segment (a gap interpolated) was not caught by the decimated-gap probe. The cause was a bug in `dense_columns`, not a weak test: when a dense curve jumped across empty columns into a bar column, the connecting segment was never drawn. The bar only extended vertically at the destination column. Unevenly sampled data would have lost that stretch of line. An edge from a non-adjacent column is now stroked on its own. A unit test reproduces the defect (it failed first) and the mutation is now caught.

**Bench** (Windows, this PC, 1200×800 logical; `TCAD_PLOT_BENCH`). A frame is the view change plus the paint into a device-resolution image, the analogue of P1's Render() + finish without the present. `repaint()`'s wall time, which includes the flush to screen, is reported beside it.

| Series | Scale | Pan p50 / p95 | Zoom p95 | `repaint()` wall p95 | Hover p95 / max | Vertices drawn |
|---|---|---|---|---|---|---|
| 1,000 points (noisy) | 1 | 6.0 / 6.8 ms | 7.4 ms | 7.7 ms | 0.004 / 0.03 ms | 1,000 |
| 100,000 points | 1 | 5.3 / 6.0 ms | 6.1 ms | 6.6 ms | 0.19 / 0.32 ms | 2,054 |
| 1,000 points (noisy) | 2 | 9.5 / 11.0 ms | 10.8 ms | 11.4 ms | 0.004 / 0.03 ms | 1,000 |
| 100,000 points | 2 | 6.0 / 8.0 ms | 7.4 ms | 8.5 ms | 0.23 / 0.57 ms | 3,246 |

Gated at scale 1 (`test_plot_view_bench_meets_the_budgets`): frames ≤ 16.7 ms p95, hover ≤ 1 ms p95, and decimation ran at 100k. The scale-2 rows are reported, not gated. Mode switching and the warm 1D-bands call are S3's.

**Gates** (all green):
- **Tick contract** (`test_desktop_plot_ticks.py`), 265 cases:
  - 137 linear ranges with every tick count, including the offset and scientific cases and degenerate views;
  - 127 log ranges: 18 views under 0.4 decades, 20 under one decade and 45 over ten (striding, no minors);
  - plus one test that the case lists really cover those kinds;
  - each compared with matplotlib's own locators and formatters, not with a reading of its code.
- **PlotView** (`test_desktop_plot.py` → `test_plot.cpp`), 24 tests at scales 1, 1.5 and 2, rendered with `grab()`, with no golden images:
  - every series' colour at its samples;
  - a NaN gap stays empty, also at 100k points through decimation, whose envelope still covers every raw sample (300 seeded probes);
  - markers at 20 and 40 points, none at 41;
  - log: negative values at their magnitude (primary and family), a zero leaves a gap, ticks positive;
  - a right-axis series on its own scale;
  - ticks equal the port's for some count and are drawn where it says; matplotlib's "1e−6" offset text;
  - legend and title present, and the legend over no sample when a free spot exists;
  - no two tick labels overlap, and all lie inside the widget, over 6 axis combinations × 5 sizes;
  - hover names each sample pointed at (exact readout); nothing far away; a NaN never reported (the QML defect, including exactly one entry beside a NaN); raw samples of a decimated series; log x and both AC axes; tied series all listed;
  - fit shows every sample on every scale combination; zoom and pan keep a log view positive; reset returns to fit;
  - the render is at the display scale;
  - an empty model shows its text;
  - unit tests of the clipping, decimation, dense columns (every point and every edge covered, including the jump) and the hover search.
- **Mutations**, each rebuilt and run, all caught:

  | Mutation | Caught by |
  |---|---|
  | a gap interpolated | 3 gates, since the `dense_columns` fix |
  | a gap bridged across segments | 3 gates |
  | a zero drawn at a floor on a log axis | 1 gate |
  | hover without the NaN guard | 2 gates |
  | zoom in data units on a log axis | 1 gate |
  | naive tick steps | 131 tick-contract cases |

- **Refactor guard:** the contour gate (80 cases) green after the MaxNLocator move.
- **Invariants:** a clean `/W4` build; the theme, contour and contract gates green (454 passed together). The full fast suite (6 workers): **2580 passed, 1 failed, 37 skipped, 2 xfailed, zero warnings**.

**The one failure is P1's open soak item (§15.25), now with its message captured.** It is `test_desktop_hardening.py::test_a_soak_keeps_memory_and_the_gl_context`: "private memory still rising 0.86 MB/cycle over the last 20 cycles".
- **The series has no steady rise.** It is flat plateaus with steps: about 547 MB, a drop to about 523 MB at cycle 30, then a single +12 MB step at cycle 48, inside the last-20 window. The gate fits a line through those 20 cycles, so one step reads as a slope.
- **Reruns:** it failed once more in 9 runs on its own (1 in 3, then 6 of 6 passed); the whole file passed (6/6).
- **S2 does not touch the path it drives** (the main window's FieldView), but that was not proven with a pre-S2 build.
- **Not changed then:** making the gate robust to steps would alter a test, which needs the user's decision. The user decided: "pre-S2 soak first; threshold/statistical relaxation second". See §16.10.

### 16.10 The soak's memory gate: pre-S2 A/B, then a robust gate (2026-09-26)

**Step 1: is S2 involved? No.**
- **Method.** A pre-S2 build, reconstructed as HEAD plus S1's six files (S1 is uncommitted too), was built in a separate git worktree, then removed. It was run against the current build on the same inputs and the same command as the test, interleaved, with the order flipped each round.
- **Result, 15 rounds:**
  - pre-S2: **2/15 failed** (slopes +0.90 and +0.56);
  - current: **0/15**.
- **All runs today:** the current build fails 2 in 25 runs (one of them in the full suite) and the pre-S2 build 2 in 15. The failure predates S2, as §15.25 recorded.

**Step 2: the gate itself.** Candidate gates were scored on real series: 30 A/B runs plus the suite's failing run. Each was also scored with a synthetic steady leak added to every series. Findings:
- **The old gate was weak as well as flaky.** Its threshold is a 0.5 MB/cycle leak, yet with that leak added it caught only 14 of 31. The noise (10–25 MB plateau steps) is as large as the 10 MB such a leak adds over 20 cycles.
- **Its second assertion was vacuous.** `mem[-1] <= max(mem)` is always true. Its likely intent, "final ≤ the warm-up peak", fails on 6 of 51 real runs, so it was removed rather than replaced.
- **The chosen gate:** the Theil–Sen slope (the median of every pairwise slope) over the last 40 cycles must be < 0.3 MB/cycle. It was selected on those 31 runs, then checked on **20 fresh holdout runs** it was not selected on. All 51 runs:

  | Leak added (MB/cycle) | Old gate (least squares, last 20, < 0.5) | New gate (Theil–Sen, last 40, < 0.3) |
  |---|---|---|
  | 0 (false failures) | 4/51 | **0/51** (0/20 on the holdout) |
  | 0.25 | 10/51 | 6/51 |
  | 0.5 | 21/51 | 34/51 |
  | 0.75 | 36/51 | 40/51 |
  | 1.0 | 42/51 | 41/51 |

- **What the new gate buys.** The largest leak-free Theil–Sen slope over the 51 runs is 0.18 MB/cycle. So the gate stops the false failures and loses no power (more at 0.5, about the same at 1.0).
- **What it does not buy.** Neither gate catches a 0.5–1 MB/cycle leak every time in 60 cycles: memory is often still falling in the window and hides a small leak (holdout, 1.0 MB/cycle: 13/20 caught). A longer soak would help; that costs test time and is the user's decision.

**Built.**
- `test_desktop_hardening.py` gains `_rise_per_cycle`, `SOAK_RISE_LIMIT = 0.3` and `SOAK_WINDOW = 40`.
- A new fast test, `test_the_soak_memory_gate_ignores_a_step_and_catches_a_steady_rise`, pins the gate on the recorded failing run:
  - the step passes, and the old gate is confirmed to fail it;
  - the same run plus a 0.5 MB/cycle leak fails, as does a clean 0.35 MB/cycle ramp.
- **Mutations:** the limit loosened to 0.5 and the statistic returning 0 each fail that test.
- **Results:** the hardening file 7/7; the soak 5/5 on its own after the change.

**The full fast suite after the change: 2581 passed, 1 failed, 37 skipped, 2 xfailed, zero warnings.** The soak passed. The one failure was a different test: `test_desktop_shell.py::test_shell_end_to_end`.
- **It was a crash, not an assertion.** The shell test binary exited `0xC0000005` (access violation) right after `overlaysAreDisabledIn3D`. That test opens 3D then 2D, and its window is destroyed; the next test, `view3dPanelIsDisabledIn2D`, creates a new window. So the crash was in a window's GL/VTK teardown or the next window's creation.
- **It is very likely P1's open item** (§15.20): S6's shell failure "without writing a Qt Test report", which matches a crash.
- **Not reproduced.** 20 consecutive runs of the shell binary on the test's own data, outside the suite, all exited 0. It appears only under the full suite's load.
- **The stack trace was lost.** Qt printed it to the child's stdout, and the test showed only the report. The test now also shows the child's own output and the exit code on a non-zero exit, so the next occurrence arrives with its trace. This changes the failure message only; the pass condition is unchanged. The shell test passes (1/1).
- **Still open**, and not caused by S2: S6 predates S2, and PlotView is not in the window.

### 16.11 P2-S3 handoff (2026-09-26; superseded — S3 landed, see §16.12)

**Done:** PlotView has matplotlib's `:` and `-.` line styles (`LineStyle::Dotted` and `LineStyle::DashDot`, patterns in `plot_view.cpp`'s `setDashes`), which convergence needs. The tree builds clean; this change has no test yet.

**Designed, not written:**
- **Modes.** Field map (2D/3D), Field (1D curve), Curves, C-V, Transient, AC, Convergence, Bands (1D), Recombination (1D). Each is offered only when the result has its data: a C-V file is a capacitance sweep; Convergence needs a non-empty trace; Bands needs potential and both densities, and Recombination also needs doping.
- **Defaults.** Field map (2D/3D) or Field (1D); a C-V result defaults to C-V.
- **Model builders.** `views/plot/curve_modes.{hpp,cpp}` builds a PlotModel from S1's accessors, with the QML labels, titles, empty texts, colours and markers (§16.1's table).
- **Central area.** A vertical `QSplitter` holding FieldView and PlotView, made the ADS central widget, so FieldView is never reparented. The selector hides one view or the other.
- **Controls.** A "ViewModeCombo" in the toolbar plus a View-menu submenu; a Plot dock tabbed with Display, holding "SweepChannelCombo" and "PlotLogCheck". Bump `AppSettings::kLayoutVersion` to 5.
- **1D bands and recombination** come through the existing `requestDerived` (cached per result), and warm the backend for 1D results too.
- **Routing.** The toolbar's Log and Fit act on the visible view.
- **Tests.** One shell test per mode; modes absent when unsupported; 0 GL re-inits over 20 switches; mode switch ≤ 50 ms p95. `test_desktop_shell.py`'s fixture gains diode_1d, a diode I-V sweep, a C-V file, a transient and an AC run.

**Not done in S2 (by the plan's steps):** the curve modes and the view-mode selector (S3), line cuts (S4) and overlays (S5). PlotView is built and gated but not yet in the app's window.

### 16.12 P2-S3 results (2026-09-26)

**Built.**
- **The curve modes** (`desktop/src/views/plot/curve_modes.{hpp,cpp}`). They build a `PlotModel` from S1's accessors. Each mode takes its labels, titles, colours, markers and empty-state texts from the QML draw path that §16.1's table names:
  - **Field**, a 1D field against x [um], with no markers;
  - **Curves**, one sweep channel. The first channel is the default, as in QML; the title notes any unconverged points;
  - **C-V**, the first channel against Vg;
  - **Transient**, every channel sorted by name, one colour each;
  - **AC**, C on the left axis and G on the right, on a log frequency axis, each axis coloured like its curve;
  - **Convergence**, one `.`-marked line per step and metric:
    - on a log y-axis and a cumulative iteration axis;
    - coloured by stage and styled by metric index (`-`, `--`, `:`, `-.`);
    - a red cross on a rejected step's last value;
    - legend entries once per `stage:metric`, and one for "rejected";
  - **Bands** and **Recombination**, for 1D results only, through the backend's `analysis.band_map` / `recombination_map`. The maps are cached per result, like S5's.
- **The plan's changes to QML behaviour**, applied in every mode:
  - decision 8: the 1D field's log view is a true log axis, and R is passed signed;
  - decisions 5 and 9: every curve hovers, AC's G and convergence included.
- **Mode availability.** A mode is offered only when the result holds its data:
  - a capacitance sweep is offered as C-V, not as Curves;
  - Convergence needs a non-empty trace;
  - Bands needs potential and both densities, and Recombination also needs doping;
  - a 2D/3D result's bands and R stay maps in the Fields list (S5).
- **Defaults.** Field map (2D/3D), Field (1D), and C-V for a capacitance sweep.
- **A block that fails to read is still offered.** Its mode shows "Cannot read the …" with the error, rather than disappearing.
- **The central area** (decision 7) is a vertical `QSplitter` holding the FieldView and the PlotView. It is the ADS central widget for the window's lifetime. The selector hides one view and shows the other; the FieldView is never reparented.
- **Selector.** A `ViewModeCombo` in the toolbar and a View > View mode submenu, both rebuilt on every open.
- **Plot panel** (`shell/plot_panel.{hpp,cpp}`), a dock tabbed with Display. It holds `SweepChannelCombo`, enabled in Curves only, and `PlotLogCheck`, enabled in Field and Curves, the modes QML gives a log toggle.
- **Routing.**
  - The toolbar's Log and Fit act on the visible view.
  - Log is disabled in modes without a toggle: convergence and R are always log; C-V, transient and bands are linear.
  - Clicking a field of a 1D result draws its curve. Clicking a field or derived map of a 2D/3D result returns to the field map.
- **Backend warm-up** now also runs for a 1D result that offers Bands.
- **A failed or unreadable derived map** is shown in the plot, as well as reported. A second request while one is pending is not sent.
- **Settings.** `AppSettings::kLayoutVersion` is now 5, so an older saved layout is ignored.

**A crash found and fixed: closing a window while a backend call is in flight.**
- **The first run of the new view-switch test crashed** with `0xC0000005` in `QMainWindow::statusBar()`, called from `~QWidget`'s `deleteChildren`.
- **The mechanism.**
  1. `~BackendClient` runs `shutdown()`, and `failAll()` emits `finished` on every pending reply.
  2. The handlers are connected with the window as their context. They are still connected at that point: `~QObject`, which disconnects them, runs after `~QWidget`.
  3. So the handlers ran after `~QMainWindow` and called `statusBar()` on a half-destroyed window.
- **When it happens.** Only when a call is still pending at close: the warm-up that tryOpen schedules 300 ms after a 2D open, or a derived map.
- **Repro.** A new test, `windowClosesWhileABackendCallIsInFlight`, closes a window with `system.warmup` pending and another with `analysis.band_map` pending. It crashed every time before the fix and passes after it.
- **The fix.** `~MainWindow` now disconnects the pending replies from the window, then deletes the backend client while the window is still whole.
- **This is very likely P1's open shell crash** (§15.20, §16.10): an access violation between two window tests, seen only under load, never reproduced solo, with no stack trace captured.
  - It fits: `overlaysAreDisabledIn3D` ends with a 2D open. Under load the test runs past 300 ms, so the warm-up timer fires, and the window closes while the warm-up is pending.
  - That link is inferred from the shape of the failure, not proven: the original failure left no stack trace. The item stays open until the full suite has run clean enough times to trust it.

**Gates** (all green):
- **Shell tests** (`test_shell.cpp`), one per curve mode, on real runs built by `test_desktop_shell.py`'s fixture: the diode, its I-V sweep, transient and AC runs, a `moscap_runner` C-V sweep, and the I-V run with one step marked rejected (no real run rejects one).
  - `curveModeFieldIsTheDefaultFor1D`:
    - Field is the default, with the plot shown and the map hidden;
    - the curve equals the stored field against x × 1e4;
    - hover shows the exact readout, in the status bar too;
    - Log gives a log axis and "|name| [unit]", and leaves the map's log alone;
    - the Fields list picks the field.
  - `curveModeCurvesDrawsTheSweep`: the title and axis labels are QML's; the data equals `sweep()`; hover; the channel combo; an unknown channel is refused; log |I|.
  - `curveModeCVIsTheDefaultForACapacitanceSweep`: C-V is the default and Curves is absent; the labels and data are right; Log is disabled.
  - `curveModeTransientDrawsEveryChannel`: both channels, sorted, in distinct colours; a legend; hover.
  - `curveModeACHoversBothAxes`: log x; G on the right axis; axis colours equal their curves'; C and G both hover.
  - `curveModeConvergenceDrawsTheTrace`, checked for every step and metric:
    - data, cumulative x offset, colour and label;
    - exactly one rejected cross, at the step's last value, in the legend once;
    - legend entries unique;
    - hoverable, with the x unit "iteration";
    - Log disabled.
  - `curveModeBandsAndRecombinationThroughTheBackend`:
    - four bands equal the backend's map, with EFn and EFp dashed;
    - R equals the map, signed, on a log axis;
    - returning to Bands uses the cache.
  - `curveModeBackendFailureIsShownInThePlot`: with a bad interpreter configured, the error is named and the plot shows "Could not compute the bands…".
  - `curveModesAbsentWhenUnsupported`:
    - `mosfet_2d` offers exactly Field map and Convergence, and every other mode is refused;
    - the menu matches the combo;
    - the C-V file offers exactly Field and C-V;
    - the diode offers exactly Field, Convergence, Bands and Recombination;
    - a 2D result opened next shows the map again.
  - `viewSwitchesKeepTheGlContextAndAreFast`: 20 switches between the map and Convergence, then 20 across the 1D modes that need no backend. The FieldView's GL initialisations stay unchanged, and the map still renders.
  - `fitAndLogActOnTheVisibleView`:
    - F refits the plot, not the hidden map;
    - the Plot panel's log and the toolbar's are one state;
    - Log is disabled in Convergence and restored on return;
    - on a 2D result, Log drives the map again.
  - `windowClosesWhileABackendCallIsInFlight`: above.
- **Mutations**, each rebuilt and run, all caught:

  | Mutation | Caught by |
  |---|---|
  | convergence x offset not accumulated | `curveModeConvergenceDrawsTheTrace` |
  | no rejected-step cross | `curveModeConvergenceDrawsTheTrace` |
  | AC's G on the left axis | `curveModeACHoversBothAxes` |
  | the Log action always driving the (hidden) map | `curveModeFieldIsTheDefaultFor1D`, `curveModeCurvesDrawsTheSweep` |

  The crash fix was checked the other way round: the repro test crashed before it and passes after.
- **Bench.** Mode switch, measured as `setViewMode` plus a synchronous `repaint()` of the shown widget over 40 switches: **p50 0.36 ms, p95 0.75 ms, max 5.1 ms**, against a 50 ms budget, which is gated.
  - For the FieldView, this `repaint()` may leave the GL frame itself to the event loop, so the map direction measures the switch, not a full GL frame.
  - The warm 1D bands call is not timed separately: the bands test's backend round trip is inside its wait.
- **Invariants:**
  - a clean `/W4` build of every target;
  - every desktop and backend-service test file: **533 passed**, none skipped;
  - the full fast suite (6 workers, run 2026-09-26 after the black-and-white theme change too): **2586 passed, 37 skipped, 2 xfailed, 0 failed, zero warnings** (15 min 54 s). The slow battery was not run: no solver code changed.

**Looked at in the app (2026-09-26).**
- **The main window, launched live** on the diode's I-V result: the Field mode drew doping against x with the `1e19` offset text.
- **Every other curve mode**, from grabs of the real `MainWindow` in the shell tests (`TCAD_SHELL_SNAPSHOT=<dir>`; Windows refused keyboard focus to a background-driven window, and driving the real mouse was avoided).
- **All eight render as intended**: stage colours, one rejected cross and a deduplicated legend in Convergence; C/G twin axes coloured like their curves; dashed quasi-Fermi levels; log R; no markers above 40 points; Log greyed out where a mode has no toggle.
- **Found:**
  1. **The inactive dock-tab labels (Info, 3D, Plot) are nearly invisible.** This predates S3 (it is the ADS tab styling), but it now hides the Plot panel's controls. Not fixed.
  2. **The view-mode combo had no accessible name.** Fixed (`setAccessibleName`).
  3. **The C-V readout at 0 V reads `@ 1.776e-15 V`.** That is the file's own voltage (float accumulation in `moscap_runner`'s ramp), shown raw by decision 3's rule. Left as is.
  4. **The fixture's "I-V sweep" is not a forward sweep.** The diode example holds the cathode at 0.6 V, so sweeping the anode from 0 to 0.6 V takes V_ak from −0.6 V to 0. The falling |I| in Curves mode is that data, drawn correctly.

**Not done in S3** (by the plan's steps): line cuts (S4), overlays (S5), and S6's adversarial files and per-mode image probes at scales 1.5 and 2. The curve modes feed PlotView, whose rendering is S2's gated widget. S3's tests check the models, the routing and the hover, not the pixels per mode.

### 16.13 One black-and-white theme, both apps (2026-09-26, user decision)

**The decision.** The user asked: "make the GUI only Light mode (I meant no modes), just black and white". Asked to choose, they picked **chrome only** (data keeps its colours) and **both apps**. This replaces S3c's System/Light/Dark choice (§15.13) and the QML GUI's light/dark toggle and glass design (`DESIGN.md` now carries a superseding note).

**Native app.**
- `theme/tokens.hpp` has one value per token: white surfaces, black text, grey borders, a black accent. The only hued tokens are `warning`, `error` and `ok`, flagged `status`.
- `Scheme`, `Choice` and `ThemeController` are gone. `theme::apply()` sets Fusion and the palette once, and the OS colour scheme is not followed. The View > Theme menu is gone, and an old `theme/choice` setting is ignored.
- `FieldView::applyTheme()` and PlotView take no scheme. The 3D outline box is now text-coloured: the white overlay colour vanished on a white background (the old light scheme had the same bug).

**QML GUI.**
- `Theme.qml` has one set of values, with no `dark` property and no `toggle()`. Token names are kept, and panels are opaque.
- Removed:
  - Ctrl+D and the View menu's theme item (the View menu itself, now empty);
  - the toolbar's sun/moon button and the status bar's "dark/light" label;
  - the wallpaper image and glow blobs (`assets/glass_wallpaper.png`, `components/GlowBlob.qml` deleted);
  - the magenta button gradient stop.
- The matplotlib canvas's `applyTheme` is gone; `_style_axes` draws black on white.
- **Kept with their hue:** the status colours (running, warning, error, ok and their backgrounds), including the green Run and red Stop buttons, because they carry meaning.

**Gates.**
- `test_theme_tokens.py` was rewritten. It reads every colour token Theme.qml declares from a running QML engine and requires each non-status token to be a grey. It also checks black on white, opaque panels, and that no mode switch remains. Mutation: restoring the violet accent fails 2 of its 4 tests.
- `test_desktop_theme.py`: native tokens equal Theme.qml's exactly and are grey except status.
- The shell tests `theBlackAndWhiteThemeReachesQtVtkAndAds` and `theThemeIgnoresTheOsColourScheme` replace the three mode-switching tests. The first checks the palette, VTK background and text, the painted ADS panel, the ADS stylesheet, the plot background, that no theme menu exists, and that a stale `theme/choice=dark` is ignored.
- **Pre-existing tests changed**, because the feature they tested is gone:
  - `test_viewport_quick_fixes.py` lost its `applyTheme` parameter case;
  - `test_shell_icons.py` no longer expects sun/moon;
  - `test_shell_layout.py` pins the new panel colours.

**Found in the running QML app, and fixed.**
- **The menu titles were nearly invisible, and the split handles were black.** Qt's own controls paint from the application palette, which nothing had set, so it followed the OS (dark on this PC). The dark theme had hidden this.
  - `Main.qml` now pins the window's palette to Theme tokens, with a new `textOnAccent` token for text on the black accent. It is not named `onAccent`: QML reads `on<Name>` as a signal handler, and that name broke `Theme.qml`'s load.
  - The native token mirrors it.
  - Gated by `test_window_palette_is_black_and_white_even_under_a_dark_os`, which forces a dark OS colour scheme.
- **The earlier invisible dock-tab labels in the native app** (§16.12, found 1) are legible now, since the tab text is dark on light.

**Result.**
- `gui/tests/` (QML app offscreen, plus the native shell, plot, theme, HiDPI and selftest files): **1336 passed, 3 skipped, zero warnings**.
- Both apps were looked at on screen: the native app on `mosfet_2d`, and the QML app's start screen.
- The solver suite (`tests/`) was not run; nothing under `pytcad/` changed.

### 16.14 P2-S4 results: line cuts (2026-09-26)

**Built.**
- **The cut** (`desktop/src/data/line_cut.{hpp,cpp}`, Qt-free). A port of `extract_line_cut`: the nearest row (horizontal) or column (vertical), not interpolated, with the node actually used reported.
  - `nearest_node` reproduces numpy's `argmin(abs(axis - position))` exactly: the first minimum on a tie, and NaN propagating (the first NaN distance wins, so a NaN position gives node 0).
  - `tcad_npz_dump --line-cut` (Python JSON on stdin, NaN allowed) is the contract tool.
- **The mode.** `Line cut` (`ViewMode::Cut`, offered for 2D results only, as in QML; 3D cuts stay out of scope, §16.6) shows the map AND the curve in the central splitter, map above at 60/40 (decision 7). The FieldView is only shown, never reparented. The curve (`plot::cutModel`) takes `_draw_cut`'s labels and title ("cut at y=… um (nearest node)"), with decision 8's log rule.
- **The cut follows the map.** It cuts whatever the FieldView shows:
  - a stored field, or a backend-derived Ec/Ev/EFn/EFp/R map (wider than QML, which cut stored fields only);
  - choosing a field or derived map from the list stays in Line cut mode and re-cuts;
  - a colour-map or range edit does not rebuild the curve.
- **The line on the map** (`FieldView::setCutLine`): a dark halo (`Text`) under a light line (`Overlay`), so it reads on any colour map. It spans the device at the node's exact coordinate, since the points are stored as doubles; float32 put it ~1e-10 µm off, which the tests caught. It is hidden outside Line cut mode and on a new result.
- **Controls** (Plot panel):
  - `CutOrientationCombo`;
  - `CutPositionSlider`, over the cut axis's NODES, so it snaps to them;
  - `CutPositionLabel` ("y = 0.0094 um (node 3 of 41)").

  All are enabled in Line cut mode only. An orientation switch keeps the node index where the new axis allows it. The default is QML's: horizontal at y = 0, node 0.
- **Routing.** In Line cut mode, Log acts on the curve (the Display panel still edits the map), and Fit fits both.

**Gates** (all green):
- **Contract** (`test_desktop_contracts.py`, section 2d; 7 tests), C++ vs `extract_line_cut`:
  - uniform and graded meshes, both orientations;
  - every node, every midpoint, just off each node both ways, outside both ends, NaN and ±inf positions, NaN data;
  - an exact midway tie on both axes (the first node);
  - every field of the real MOSFET result;
  - the refusal message equals Python's.
- **Shell** (`test_shell.cpp`):
  - `cutModeIsOffered2DOnly`;
  - `cutModeShowsTheMapAboveItsCurve`: both views shown, map above; the curve equals the cut of the shown field; labels and title; the line at the exact node coordinate, spanning the device; 0 GL re-inits; the line hidden again outside the mode;
  - `cutFollowsTheSliderAndTheOrientation`: the slider over the nodes; row values; label; the line moves; vertical gives the column along y; out-of-range refused; controls off outside the mode;
  - `cutFollowsTheFieldAndDerivedMaps`: a list field re-cuts and stays in the mode; the derived Ec map through the backend;
  - `cutLogAndHoverFollowDecisions8And9`;
  - `cutSwitchesKeepTheGlContext` (20 switches through Line cut, Field map and Convergence);
  - `curveModesAbsentWhenUnsupported` updated: the MOSFET now offers Field map, Line cut and Convergence.
- **Mutations**, each rebuilt and run, all caught:

  | Mutation | Caught by |
  |---|---|
  | a tie takes the last node | 5 contract tests |
  | a row off by one | 4 contract tests |
  | the curve ignores the slider | both targeted shell tests |
  | the map line one node off | both targeted shell tests |

- **Looked at:** a snapshot of the window in Line cut mode (`TCAD_SHELL_SNAPSHOT`): the MOSFET doping map with the cut line near the surface, and the source/drain profile below it.
- **Not run, at the user's request:** the full suite. Run instead: the line-cut contract (7/7), the theme gate (4/4), and the 7 cut and mode shell tests, plus S3's `viewSwitchesKeepTheGlContextAndAreFast` and `fitAndLogActOnTheVisibleView` (all pass). A clean build of every target.

### 16.15 P2-S5 results: overlays from files (2026-09-26)

**Built.**
- **Model** (`plot::OverlayCurve`, `plot::overlayMismatch`, in `curve_modes`). Overlays are sweeps from other result files drawn over the open one:
  - **one comparison**, dashed in the comparison colour, lw 1.2;
  - **a family of any size**, solid, series colours 1, 2, …, lw 1.1: QML's `_draw_series` styles, with markers at ≤ 40 points;
  - order: primary, the family, then the comparison; a legend once there is more than one curve;
  - **each overlay on its OWN voltages** (finding 12);
  - they hover like the primary, and follow decision 8's log rule.
- **Modes.** Overlays work in **Curves and C-V** (QML had them in Curves only; the quantity check exists so C-V can have them too). In other modes they are not drawn, and adding is refused.
- **Refusal.** `overlayMismatch` names the FIRST mismatch against the open sweep: the swept contact, the quantity (current/capacitance), the unit, or the channel shown (Curves: the selected channel; C-V: the first). `MainWindow::addOverlay` also refuses, with the reason:
  - a missing, corrupt or sweep-less file;
  - the open result itself;
  - the same file twice as the same kind.

  A refusal is reported (non-modal box and status bar), and the list is unchanged.
- **Behaviour.**
  - A second comparison replaces the first (QML's `setComparisonSource`).
  - The sweep is decoded at add time; the file is not kept open.
  - Overlays are cleared when another result opens (they compare against ONE result).
  - An overlay without the channel now shown is not drawn, and is greyed out in the list with the reason.
- **Controls** (Plot panel): "Add comparison…" / "Add to family…" (a file dialog), `OverlayList` with labels editable in place (the file name by default; an empty edit is undone; the comparison in italics), and "Remove".

**Gates** (all green; shell tests on new fixture files):
- **Fixture files.** Finer and coarser ramps of the diode I-V (valid overlays, on other voltages). Five that differ from it in exactly one respect: a sweep of the other contact; the run re-stamped as capacitance; a unit-edited copy; a channel-renamed copy; and the C-V run with its quantity stamp removed. Also a second C-V sweep, and two-channel copies ("extra" = 3 × "device").
- **Tests:**
  - `overlayComparisonIsDashedOnItsOwnVoltages`: style and colour; the overlay's own voltages (≠ the primary's) and values; a legend; hover; a second comparison replaces the first;
  - `overlayFamilyGetsOneColourEachBeforeTheComparison`: colours 1 and 2, solid, order, all in the legend; a duplicate refused;
  - `overlayRefusesAMismatchNamingIt`, 9 rows: contact, quantity, unit, channel, no sweep, the result itself, missing, corrupt, and "contact first" (the real C-V file also sweeps another contact, which is named first). Each is reported, and nothing is added;
  - `overlayLabelsEditRemoveAndClear`: a label edited in the list reaches the legend; an empty label is undone; Remove; log keeps the overlays' raw values on the |y| axis; other modes refuse and disable; a new result clears them;
  - `overlayFollowsTheSelectedChannel`: two-channel files; the overlay follows the channel shown, including after a switch;
  - `overlaysInCVMode`: a C-V family on its own voltages; a current sweep refused by quantity.
- **Mutations**, each rebuilt and run, all caught:

  | Mutation | Caught by |
  |---|---|
  | the family drawn on the primary's voltages | 2 tests |
  | the overlay's first channel instead of the one shown | `overlayFollowsTheSelectedChannel` (the only test that can: every other fixture has one channel) |
  | the contact check removed | the 2 contact rows |
  | the comparison drawn solid | 2 tests |

- **Looked at:** a snapshot of the family and comparison over the primary: the diode I-V with the fine ramp (green, its own 0-0.4 V points), the coarse ramp (gold) and the dashed comparison over it.
  - **An observation it made visible (not S5's):** the same diode at the same bias gives a ~3 % different reverse current on the fine ramp at 0.3 V (≈ −1.62e-9 vs −1.67e-9 A/cm²). That suggests the answer at nanoamp level depends slightly on the continuation path. Not investigated here.
- **Not run, at the user's request:** the full suite. Run instead: the 7 overlay tests (with 9 refusal rows), plus the S3 and S4 tests that share the models and routing (`curveModeCurvesDrawsTheSweep`, `curveModeCVIsTheDefaultForACapacitanceSweep`, `cutModeShowsTheMapAboveItsCurve`, `fitAndLogActOnTheVisibleView`, `curveModesAbsentWhenUnsupported`): 21/21 passed with the harness's two. The theme gate: 4/4. A clean build.

### 16.16 P2-S6 results: hardening, and the P2 exit checklist (2026-09-26)

**Built.**
- **`plot::nothingToPlot`**, applied to every curve mode. When no sample of any series can be shown on its axes (finite, and non-zero on a log axis: decision 8), the mode shows a message keeping its title, for example "anode sweep (7 point(s) did not converge)" followed by "Nothing to plot: no finite value". It no longer draws empty axes over an invented 0-1 range.
- **Edge-case files**, each a real run with one thing broken, all accepted by both `validate_result` and the native reader:
  - every sweep point unconverged;
  - a one-point sweep;
  - a trace whose steps carry no metrics;
  - a transient with one all-NaN channel;
  - AC at one frequency.
- **Image probes** (`probeSeriesColours`). On the widget as rendered (`grab()`), the render must be at the display scale (logical size × DPR). Each series' colour must be drawn at one of its samples that no other series' polyline comes within 4 logical px of; dashed and dotted series are probed only where markers are drawn.

**Gates** (all green):
- **`curveModeImagesProbe`, one row per curve mode**: 1D field, Curves, Curves with a family overlay, C-V, transient, AC, convergence (with a rejected step), bands and recombination (through the backend), and the line cut. Each checks the colours, ticks on both axes, the legend when there is one, and the title when there is one. **Run at display scales 1, 1.5 and 2** by `test_desktop_hidpi.py::test_curve_modes_draw_at_scale` (3/3).
- **`curveModesSurviveAdversarialFiles`**:
  - all unconverged: the message with the note, in linear and log;
  - one point: a marker, a finite non-degenerate view, the exact readout;
  - no metrics: the Convergence message;
  - an all-NaN channel: the good channel drawn, and a NaN never read out anywhere on a 17-px hover grid;
  - one AC frequency: a positive single-decade log view. **Found:** C's and G's single markers land on the SAME pixel, since each axis centres its only value, so G, drawn last, is the one seen. The test asserts exactly that.
- **Mutations**, each rebuilt and run, both caught:
  - `nothingToPlot` removed: the all-unconverged row fails;
  - every series painted in series 0's colour: 6 of the 10 image rows fail (every mode with more than one series).
- **Bench row: 1D bands through a warm backend**, from the request to the curves drawn: **1066.5 ms**, reported and not gated (`bandsWithAWarmBackendIsReported`).

**P2 exit checklist (§9: every curve mode of §10.2 has a C++ equivalent and an image test).**

| §10.2 mode | Native | Named test | Image test |
|---|---|---|---|
| series (Curves) | S3 | `curveModeCurvesDrawsTheSweep` | `curveModeImagesProbe(curves)` |
| family + comparison | S5 | `overlay*` (6 tests, 9 refusal rows) | `(curves_overlays)` |
| cv | S3 | `curveModeCVIsTheDefaultForACapacitanceSweep` | `(cv)` |
| transient | S3 | `curveModeTransientDrawsEveryChannel` | `(transient)` |
| ac | S3 | `curveModeACHoversBothAxes` | `(ac)` |
| convergence | S3 | `curveModeConvergenceDrawsTheTrace` | `(convergence)` |
| bands (1D) | S3 | `curveModeBandsAndRecombinationThroughTheBackend` | `(bands)` |
| recombination (1D) | S3 | the same | `(recombination)` |
| cut | S4 | `cutMode*`, `cutFollows*` | `(cut)` |
| doping/field, 1D | S3 | `curveModeFieldIsTheDefaultFor1D` | `(field_1d)` |
| bands / recombination / field, 2D-3D | P1 (FieldView maps) | P1's `parity2d*` and derived-map tests | P1's selftest pixel probes |
| structure, mesh, process, doping preview | **moved to P4** (decision 6) | -- | -- |

Every image test runs at scales 1, 1.5 and 2. The §16.4 bench rows:
- pan/zoom frames at 1k and 100k points ≤ 16.7 ms p95 and hover ≤ 1 ms: S2, gated; now a `timing` test;
- mode switch ≤ 50 ms: S3, p95 0.75 ms;
- 1D bands, warm: above.

**Not yet done for the P2 close:**
- **The full fast suite and the timing pass.** They were not run during S4-S6, at the user's instruction. They must run before P2 is called closed.
- **Sign-off.**

### 16.17 P2 closed (2026-09-26)

The user closed P2 ("close P2, plan P3") on the §16.16 exit checklist. Recorded with the closure, not hidden:

- **Owed before commit: the full fast suite and the timing pass.** They last ran after S3: the fast suite was 2610 passed, 0 failed (with the AC-sensitivity change); the timing pass had one open item, `stencil3d`'s throughput floor measured while a game was running (`AC-SENSITIVITY-PLAN.md` §9). S4-S6 were verified by targeted runs only, at the user's instruction:
  - the line-cut contract;
  - the theme gate;
  - every cut, overlay and S6 shell test, and the S3 tests they touch;
  - the image probes at three scales;
  - mutations for each gate.
- **Carried to P3 and later:**
  - P1's unexplained shell crash: probably the window-close crash fixed in S3 (§16.12), unconfirmed until a few full-suite runs pass;
  - no desktop CI (it needs a GL runner);
  - the ~3 % path dependence of a nanoamp reverse current seen in S5 (a solver question, §16.15).


## 17. P3 — Run and monitor: detailed plan (2026-09-26, reviewed §17.7; APPROVED with the default decisions 1-9)

§9 defines P3 as running solver jobs from the native app, and watching them:
- the JobRunner and RemoteJobRunner equivalents: QProcess, cancel, and the remote SSH path (including the Windows `mkdir -p` lesson from `gui/tests/fixtures/fake_ssh.py`);
- solver telemetry on the structured progress channel (§4.3);
- the console;
- study and batch (M30);
- the backend service's full method set.

Exit: an end-to-end run → view flow for the 1D, 2D and 3D examples. P2 adds one item: families and comparisons made by RUNNING, which feed S5's overlays (§16.1 finding 3).

### 17.1 Review findings (from the tree, before any P3 code)

1. **A run is already a clean process contract.**
   - The command: `python -m gui.services.solver_runner <job.json> <result.npz>`. `process_runner` and `moscap_runner` follow the same shape; `moscap_runner` takes a plain dict job, not a DeviceSpec.
   - Stdout markers: `PYTCAD_STAGE=`, `RESULT_PATH=`, `PYTCAD_ERROR=`, plus the core's `verbose=True` Newton lines. `job_runner.py` scrapes an iteration number and `|dpsi|` from those.
   - Results are written atomically, so a killed run leaves nothing half-written.
   - The native app should start the same process with the same interpreter as the backend service (`resolveBackendConfig`). Nothing about solving moves into C++.
2. **Cancel does less than the QML code suggests, on Windows.**
   - `JobRunner.cancel()` calls `terminate()`, then `kill()` after 3 s. On Windows, `QProcess::terminate()` only posts WM_CLOSE to the process's windows, and a console Python process has none. So every QML cancel is in fact a 3 s wait and then a kill.
   - The atomic writes make an immediate kill safe. See decision 3.
3. **Run configuration is DeviceSpec state, validated in Python.**
   - `SweepSpec`, `TransientSpec` and `ACSpec` each have `validate(contact_names)` in `device_spec.py`.
   - `AppController.run()` refuses more than one of sweep, transient and AC armed at once; refuses equilibrium-only with a sweep; and checks devsim compatibility (`check_devsim_compatible`) before using the devsim backend.
   - It stamps `spec.models` from the Physics Lab, and `backend`/`engine` from the run options.
   - The native app must not re-implement these rules; it asks the backend (decision 1).
4. **Without P4's editors, there are three places a device can come from:**
   - the bundled examples (`examples.list` / `examples.build` already exist in `backend_service`);
   - a DeviceSpec JSON file;
   - a saved project (schema 5), whose DeviceSpec the backend can produce.

   Model toggles (the Physics Lab) are P4 editors, so P3 runs a device with the models its spec carries.
5. **Remote runs** (`remote_job_runner.py`) chain four QProcess stages: mkdir, push (scp), run (ssh, the same entry point), pull. It uses BatchMode=yes, no credential storage, and has the same signals as the local runner. `gui/tests/fixtures/fake_ssh.py` is a ready local stand-in.
6. **Telemetry today** is scraping, not a structured channel. §4.3 (P0) specifies `PYTCAD_PROGRESS <json>` lines, produced in `solver_runner` by parsing the core's verbose prints in-process. The core is frozen, and no core change is needed. `job_runner.py` must then swallow those lines, or the QML console fills with JSON.
7. **Study (M30)** (`study_controller.py`): a split matrix (`workbench.splits.run_split_matrix`) is run as a pool of runners, local or round-robin over remote hosts. Row statuses are `build_error | pending | running | done | failed`. It is shaped like `FamilySweepController`.
8. **Families and comparisons in QML are runs:**
   - `FamilySweepController`: one job per stepped value;
   - the M9 models-off comparison and `runBackendComparison`: a second job.

   In P2 the native app could only open their result files (S5). P3 runs them and adds the results as S5 overlays.
9. **Not solver-backed in QML:**
   - The Probe Station's "real-solver DC sweep dispatch" is "NOT YET IMPLEMENTED"; it generates demo data in-process (`probe_station_controller.py`). P3 does not port a demo as if it were a feature (decision 6).
   - The compact-model extraction (`CompactModelPanel`, M38) is analysis over results, not a run: P4.

### 17.2 Design

- **`run/job_runner.{hpp,cpp}`: the local runner** (QProcess, Qt Core only).
  - It starts `<python> -u -m <module> <job> <result>` in the backend root, with a per-run id so a cancelled run's missing file can never be mistaken for another's.
  - It parses the markers and `PYTCAD_PROGRESS` lines, and forwards every other line to the console.
  - Signals: `started`, `stage`, `progress(event)`, `line`, `finished(result)`, `failed(summary, details)`, `canceled`.
  - One job file per run, removed on every outcome.
  - Cancel is decision 3, and targets the same process even if a new run started.
- **`run/remote_job_runner.{hpp,cpp}`**: mkdir → push → run → pull, the same signals, and the same BatchMode command shapes as `remote_job_runner.py`. It is gated against `fake_ssh.py`, including its Windows `mkdir -p` case.
- **Jobs are built by the backend** (new `backend_service` methods, each with a conformance test and a measured latency, §4.4):
  - `spec.from_example`, `spec.load` (a DeviceSpec JSON file) and `project.spec` (a schema-5 project's DeviceSpec);
  - `spec.configure_run`: sweep, transient, AC or equilibrium-only; backend and engine. It applies `AppController.run()`'s refusals, with the same messages, and returns the normalized DeviceSpec JSON the runner writes;
  - `study.rows`: a split matrix into row specs.
- **The progress channel** (§4.3, implemented here):
  - `solver_runner` writes `PYTCAD_PROGRESS` records with events stage, newton, sweep_point, transient_step, done and error;
  - non-finite numbers become null; at most one newton record per iteration and 50 records/s;
  - `job_runner.py` swallows them;
  - `process_runner` and `moscap_runner` emit stage events only.
- **The UI:**
  - **A Run dock.** Device: an example, a DeviceSpec file or a project. Run kind: equilibrium, bias, sweep, C-V, transient or AC, with each kind's parameters. Backend and engine: the QML options, gated the same way. Where: local, or a remote host. Toolbar Run and Stop.
  - **A Console dock**: every line, stage lines marked, and a failure's details.
  - **A Telemetry dock**: stage, iteration, a live residual history (a PlotView, log y), sweep point k of N, and elapsed time.
  - **On success**: the result opens (`tryOpen`) in its natural view (a sweep in Curves, a C-V in C-V, and so on).
  - **Families and comparisons**: "Run family" (a stepped bias, N jobs) and "Run comparison" (models off, or the other backend). Their results arrive as S5 overlays.
  - **A Study dock**: the rows, their statuses and a pool size; a row opens its result.

### 17.3 Steps

| Step | Size | Content |
|---|---|---|
| P3-S1 | S | **Progress channel** (Python only): `PYTCAD_PROGRESS` in `solver_runner` (+ stage events in `process_runner`/`moscap_runner`); `job_runner.py` swallows them. Contract tests: record grammar, null for non-finite, rate limit, event order on a real 1D sweep and a 3D solve; the QML console receives no JSON. |
| P3-S2 | S | **Backend job methods** (`spec.*`, `project.spec`), each conformance-tested against the direct Python call, including every `run()` refusal message. |
| P3-S3 | M | **C++ JobRunner**. Tests against the real `solver_runner` (the 1D diode) and misbehaving fakes: crash, hang (cancel), garbage and very long lines, no `RESULT_PATH`, exit 0 with no file, a non-ASCII work dir, cancel then immediate restart. |
| P3-S4 | M | **Run dock, Console, Run/Stop, open on success.** The exit flow: run → view for the 1D, 2D and 3D examples, e2e in the shell tests. |
| P3-S5 | S | **Telemetry dock**: the live residual plot, stage, sweep progress; gated against the `PYTCAD_PROGRESS` records of a real run. |
| P3-S6 | M | **Families and comparisons by running**, into S5's overlays; refusals as S5's; cancel of a family mid-way. |
| P3-S7 | M | **Remote runner** against `fake_ssh.py`: every stage fails in turn, cancel in each stage, the Windows mkdir case. |
| P3-S8 | M | **Study** (M30): build rows through the backend, a pooled local/remote run, statuses, open a row's result, cancel all. |
| P3-S9 | M | **Hardening and exit.** Bench rows: Run click to first progress record; native vs direct `run_job` overhead. The full fast suite, the timing pass and the slow battery (P3 edits `solver_runner`), and a live run of all three examples, looked at. |

### 17.4 Gates

- **Contracts:**
  - the progress grammar;
  - every new backend method equals its Python call;
  - `configure_run`'s refusals equal `AppController.run()`'s messages;
  - a native job file equals the QML one for the same inputs (byte-compared JSON).
- **Runner robustness:**
  - every misbehaving fake yields a named failure, never a hang or a crash;
  - cancel leaves no result and no job file, and a run started straight after a cancel is never killed by the old cancel's timer (QML's final-review I-5 bug, tested).
- **End to end:** the 1D, 2D and 3D examples run and open, with a sweep and a transient on the 1D diode, a C-V run, and an AC run, all in the real window.
- **Remote and study:** every stage failure is named; round-robin over two fake hosts; statuses as M30's vocabulary.
- **Mutations**, each rebuilt and run:
  - no rate limit;
  - cancel on the wrong process;
  - progress events not forwarded;
  - an overlay run on the primary's contact when it should be refused;
  - the remote pull step skipped.
- **Invariants:** a clean `/W4` build; the full suite green with zero warnings.

### 17.5 Decisions (defaults proposed; say if you want otherwise)

1. **Jobs are built and validated by the Python backend**, not re-implemented in C++. This is §12 decision 5's recommended default, applied to P3.
2. **One device run at a time in the main window, as in QML.** Families and studies have their own pools.
3. **Cancel kills at once on Windows.** `terminate()` cannot stop a console Python process there, so QML's 3 s wait is dead time. The atomic writes make an immediate kill safe, and the tests prove no partial file.
4. **Results are kept in `%LOCALAPPDATA%\PyTCAD\runs\`, the 20 most recent**, reachable from Open Recent, plus a "Save result as…". The alternative is QML's temp dir per session, lost on exit.
5. **The Physics Lab model toggles stay P4.** P3 runs a device with its spec's models; equilibrium-only is a P3 run kind.
6. **The Probe Station is not ported in P3**: its solver dispatch does not exist in QML. When it gets real solver runs, it arrives through this runner. The compact-model extraction goes to P4.

### 17.6 Out of scope

- Editors, projects' editing and undo (P4).
- Packaging and the bundled Python (P5).
- Any change to the frozen core: the progress channel scrapes verbose prints, per §4.3.
- MPI launch outside what `solver_runner` already does.

### 17.7 Review revisions (2026-09-26, before any P3 code)

Every §17.1 claim was checked against the tree, and three were measured by running `solver_runner` through a pipe. Where the plan was wrong or incomplete, it changes as follows.

**Corrections to §17.1**

1. **`PYTCAD_ERROR` is on stderr, not stdout** (`solver_runner.main`: a JSON payload plus the traceback). The runner must read both streams. The failure summary comes from stderr's `PYTCAD_ERROR` line; the details are the rest of stderr (as `job_runner.py` does).
2. **Progress is only stage-level for two engines.**
   - The MPI Schwarz engine relays only its workers' `PYTCAD_STAGE` lines (`_run_mpi_schwarz`).
   - The devsim backend prints no Newton lines.

   So `newton` events exist only for the pytcad engine without MPI; the Telemetry dock must say "stage-level progress only" instead of showing an empty residual plot.
3. **Transient progress has a source.** The transient modules print `[transient] t=… dt=…` (and `[transient2d]`, `[transient3d]`, with `SHRINK` lines); `solver_runner` can turn these into `transient_step` events. Sweep points already have `PYTCAD_STAGE=sweep point i/N`.
4. **C-V is not a run kind of the loaded device.** `moscap_runner` takes its own MOS-capacitor inputs (`nsub_cm3`, `tox_nm`, `gate`, `qf_cm2`, `T`, `vstart/vstop/vstep`): a separate job type with its own small form, as QML's C-V section is.
5. **Remote runs are a Study feature in QML, not a single-run one.** `RemoteJobRunner` is created only by `StudyController.setRemoteHosts`. A single-run "local or remote" choice would be new scope. See decision 8.
6. **A project gives more than a DeviceSpec** (`project_store.load_project`): it also returns a sweep and a models config (schema 5). P3 applies both. Applying a saved models config needs no Physics Lab editor, so decision 5 is narrowed to editing the toggles. A project with no structure (a process flow only) has no DeviceSpec and is refused, named.
7. **Process-flow runs are P4.** `process_runner` produces a process manifest whose views (process, doping preview) moved to P4 in P2 (§16.5 decision 6). P3 drops `process_runner` from its scope; its stage events come with P4.
8. **The engine options are computed.** QML's engine list (`AppController`, around the `mpi_schwarz` option) depends on the device's size and on which optional packages import (pyamg, cupy, mpi4py). The devsim backend likewise needs `check_devsim_compatible` and devsim installed. P3 needs a backend method for the options, not a fixed list.

**New findings, measured**

9. **QML's live telemetry is not live.**
   - `job_runner.py` starts `python -m …` without `-u` or `PYTHONUNBUFFERED`, and the core's `verbose` prints do not flush. So through a pipe, a stage's Newton lines are block-buffered until the next flushed `PYTCAD_STAGE` marker.
   - Measured on the 2D MOSFET job, the same run twice:

     | Stage | Without `-u` (as QML) | With `-u` |
     |---|---|---|
     | equilibrium: 12 Newton lines | all at 0.94 s | 0.73-0.94 s |
     | bias: 9 lines | all at 2.30 s, the stage's end | 1.09-2.28 s |

   - So for the whole 1.3 s bias stage, QML's Solver Telemetry panel shows nothing, then everything at once.
   - The native runner uses `-u` (as §17.2 had). QML gets the same one-line fix as a bug fix (decision 7).
10. **Remote runs can be abused, in both the Python and the planned C++ runner.**
    - `remote_job_runner.py` (and `workbench.remote_executor`) pass the host string to `ssh`/`scp` as a plain argument. A host typed as `-oProxyCommand=<command>` would be parsed as an ssh OPTION, which runs a local command.
    - The remote command is built unquoted: `mkdir -p {remote_workdir}` and `" ".join(argv)`. A remote path with a space breaks it, and a shell metacharacter injects into the remote shell.
    - The port must validate hosts: no leading `-`, and `--` before the target; and it must quote the remote command. Decision 9 asks whether to fix the Python side too.
11. **Nothing bounds the console.** `console_model.py` appends forever. A long 3D sweep's verbose output would grow without limit. The native Console keeps the last N lines (50,000 proposed), with the count of dropped lines shown.
12. **A window closed mid-run.**
    - Qt's `~QProcess` kills its process, so no orphan solver keeps the CPU. But the runner's signal handlers can then run into a half-destroyed `MainWindow`: the same class of crash P2-S3 fixed for the backend client (§16.12). The native runner is torn down first in `~MainWindow`, with its handlers disconnected.
    - This is gated: close the window during a run; no crash, no orphan `python.exe`, no job file left behind.
13. **The Study needs its definition UI.** A split matrix is factors and their levels (`StudyController`'s slots take them). §17.2's Study dock listed only the rows. It gains the factor/level table, which is study configuration, not device editing, so it stays in P3.

**Unverified, so tested rather than assumed.** Windows `scp` with a local path like `C:\…`. Some scp builds read a `C:` prefix as a host name. S7's fake-ssh tests and one real `scp` call decide it.

**Changes to §17.2-§17.5**

- **§17.2:**
  - the runner reads stderr (point 1);
  - the Telemetry dock states stage-level-only progress (point 2);
  - `transient_step` comes from the `[transient*]` lines (point 3);
  - C-V is its own job form (point 4);
  - the backend gains `run.options(spec)`, the engines/backends offered with each refusal named (point 8), and `project.spec` returns the sweep and models config too (point 6);
  - the Console is bounded (point 11);
  - the Study dock gains the factor/level table (point 13).
- **§17.3 steps:**
  - S1 adds `transient_step` and the stage-only engines;
  - S3 adds stderr parsing and the window-close teardown;
  - S7 and S8 swap: **S7 Study (local)**, then **S8 remote**, since QML's remote runs exist for studies only (point 5);
  - S8 adds host validation and quoting (point 10).
- **§17.4 gates, added:**
  - a live-telemetry gate: the Newton lines of a real 2D bias stage arrive while the stage runs, measured as above, in the native runner (and in QML, if decision 7 is accepted);
  - a window-close-mid-run gate (point 12);
  - hostile host names and paths are refused or quoted, never executed (point 10);
  - the console cap;
  - a project with a models config runs with those models (point 6);
  - a flow-only project is refused, named.
- **§17.5 decisions:** 1-4 unchanged. Decision 5 narrows: a saved models config is applied; editing the toggles stays P4. Decision 6 unchanged. New:
  7. **QML's telemetry buffering is fixed** by starting the solver with `-u` (or `PYTHONUNBUFFERED=1`) in `job_runner.py`, a bug fix under the transition rule, gated by the measurement above. The alternative is to leave QML as it is.
  8. **Remote stays a Study feature in P3**, as in QML. A single-run remote choice can follow if wanted.
  9. **The remote-command hardening (point 10) is applied to the Python runners too** (`remote_job_runner.py`, `workbench.remote_executor`), as a security fix under the transition rule. The alternative is native only, with the Python side recorded as a known issue.

Decisions 7-9 are new and, like 1-6, defaults awaiting approval.

### 17.8 P3-S1 results: the progress channel (2026-09-26)

**Built (Python only; the frozen core is untouched).**
- **`gui/services/progress_channel.py` (new).** `ProgressTap` wraps the runner's stdout for the whole job. Every line passes through unchanged, and it adds `PYTCAD_PROGRESS <json>` records (§4.3), v1:
  - `stage`;
  - `sweep_point`: index, count, and the swept contact and bias (null when relayed by the MPI engine);
  - `newton`: stage, iter, residual;
  - `transient_step`: time, dt, iters;
  - `done`: result, dropped;
  - `error`: error, message.

  Other properties:
  - non-finite numbers are written as null;
  - one newton record per (stage, iteration);
  - at most 50 records/s; excess newton and transient_step records are dropped and counted in `done`;
  - stage, sweep_point, done and error are never dropped.
- **One definition of the line grammars.** `STAGE_LINE`, `SWEEP_POINT`, `ITERATION` and `METRIC` moved from `solver_runner` into `progress_channel` (checked identical to the committed patterns). `solver_runner`'s names now alias them, so the stored convergence trace and the live records read every line the same way.
- **`solver_runner`:**
  - `main()` installs the tap and emits `done`, or `error` beside the unchanged stderr `PYTCAD_ERROR`;
  - the sweep loop gives each point's contact and bias;
  - the three `solve_transient` calls pass `verbose=True`. That only prints: a transient result from before and after the change has every array identical, and its run record differs only in `created_utc`. Without it, a transient job printed no step lines at all, so `transient_step` had no source (a finding of this step);
  - an MPI-engine or devsim job gets stage-level records only, as §17.7 recorded.
- **`moscap_runner`:** a new `PYTCAD_STAGE=cv` marker, plus the tap: stage, then done or error.
- **QML `job_runner.py`**, under the transition rule:
  - it swallows `PYTCAD_PROGRESS` lines, so the console shows none;
  - it starts the child with `PYTHONUNBUFFERED=1` (decision 7);
  - it now assembles whole lines from BYTES across reads. The unbuffered child makes a read that ends mid-line (or mid-UTF-8 character) common, and the old per-read `splitlines()` would have split a `RESULT_PATH` or a record in two. A final line without a newline is read at exit.

**Departures from the P0 spec (§4.3), each deliberate:**
- metric names are the trace's own (`F`, `dpsi`, `dn/n`), not §4.3's example `dn_rel`;
- `done` carries `dropped`;
- the essential events are exempt from the rate limit;
- a record emitted while a line is unfinished starts on its own line.

**Found and fixed while testing:**
- **A record glued to a line.** The tap first wrote a whole chunk and then its records, so a record could be glued onto the end of a partial line (`partialPYTCAD_PROGRESS {…}`) and corrupt both. The pass-through test found it; the tap now writes line by line, each record after its line's newline.
- **The wrong clock.** `time.monotonic` ticks at 15.6 ms on Windows; the records use `perf_counter`.
- **A test that did not test decision 7.** The first live test did not fail when `PYTHONUNBUFFERED` was removed. The tap's flush after each record already makes `solver_runner`'s Newton lines live, and the variable only matters for lines that produce no record. A second fixture (`slow_printer`, unflushed plain lines 0.25 s apart) gates decision 7 itself.

**Gates** (`gui/tests/test_progress_channel.py`, 14, all green):
- **Real runs, as subprocesses:**
  - a 1D sweep: the v1 grammar, non-decreasing `t`, one record per `PYTCAD_STAGE` marker in order, sweep points with contact `anode` and the exact bias values, `done` naming the written result;
  - a transient: one `transient_step` per accepted step, equal to the stored `transient__times` to the printed precision;
  - a C-V run: `stage` then `done`;
  - a failing job: an `error` record equal to its stderr `PYTCAD_ERROR` payload, and no `done`.
- **The live newton records ARE the stored trace:** each record is a stored iteration, in order, with equal metric values, and records + dropped = the trace's iterations.
- **The tap:**
  - pass-through unchanged;
  - a record emitted mid-line starts its own line;
  - non-finite numbers as null, with no `NaN`/`Infinity` token;
  - one newton record per (stage, iteration);
  - 49 newton records plus the stage in one second, 151 dropped, the essential stage record still written, and the window reopening after a second;
  - a relayed sweep line with a null contact.
- **QML runner:**
  - the 2D MOSFET's bias-stage residuals arrive spread over the stage, and no record reaches the console;
  - unflushed lines arrive live (decision 7);
  - lines split across reads: mid-marker, mid-number, mid-JSON, mid-UTF-8 character, and a last line with no newline.
- **Mutations**, each run and restored, all caught:

  | Mutation | Caught by |
  |---|---|
  | no rate limit | 1 test |
  | QML child buffered | the decision-7 test |
  | no line assembly | the split-reads test |
  | records forwarded to the console | 2 tests |
  | no newton de-duplication | 1 test |
  | a record written before its line | 5 tests |

- **Existing tests:** every test file touching the runners, the trace, telemetry, studies or families (55 files): **632 passed, 3 skipped**, zero warnings. The full suite was not run.

### 17.9 P3-S2 results: the backend job methods (2026-09-26)

**Built (Python only; the frozen core is untouched).**
- **`gui/services/run_config.py` (new, Qt-free): one pre-flight for both GUIs.**
  - `configure_run(spec, sweep, transient, ac, equilibrium_only, models, backend, engine)` holds `AppController.run()`'s checks, in the same order and with the same messages, and returns the spec to run. It raises `RunConfigError(title, detail)`. It works on a shallow copy and never changes its input. `models=None` keeps the spec's own models.
  - `backend_options` and `engine_options` are the QML selectors' lists, moved here unchanged.
  - `merged_models` merges a models config the way the Physics Lab restores one.
  - `project_run_inputs(path)` gives a project's name, DeviceSpec, sweep and merged models. It refuses a project with no structure ("Nothing to run", naming a flow-only project) and an invalid structure, with QML's message.
- **`AppController` delegates.**
  - `run()` calls `configure_run` and emits a `RunConfigError` through `errorRaised`. It then stamps the run fields back onto `self.spec`, which keeps its identity (`_last_run_spec` and the comparisons read it).
  - `backendOptionsForQml` and `engineOptionsForQml` call the shared functions.
- **Backend methods** (`backend_service/server.py`):
  - `spec.from_example` (the same as `examples.build`), `spec.load` and `project.spec`, which returns `{name, spec, sweep, models}`;
  - `run.options` gives `{backends, engines}`, each option as `{id, label, enabled, reason}`;
  - `spec.configure_run {spec, run: {...}}` gives the DeviceSpec dict to run.
  - An error's data now includes the exception's `rpc_data` if it has one, so a refusal arrives as `{type: "RunConfigError", title, detail}`.
  - Unknown run keys and wrongly typed values are refused as INVALID_PARAMS; an unknown backend or engine id is refused, named.
- **`study.rows` is not here.** It belongs with the Study (S7).

**One behaviour change, deliberate.** Before S2, a refused devsim run had already stamped the sweep, the models and so on onto `self.spec` before the devsim check refused it. Now a refusal leaves `self.spec` as it was. Nothing reads those fields between a refused run and the next one, which stamps them again.

**Gates** (`gui/tests/test_run_config.py`, 49; 48 in the fast run and 1 `timing`):
- **Every `run()` refusal** (7 cases) gives the same `(title, detail)` through the RPC as QML's `errorRaised`. A further test checks that these cases reach every title `configure_run` can raise.
- **Every accepted run** (8 cases) gives the RPC the same spec QML hands its runner. The cases are bias, sweep, transient, AC, equilibrium-only, a forced engine, a toggled model, and devsim.
- The run options equal the QML selectors' for 1D, 2D and 3D, with and without an armed transient.
- A project runs with its saved sweep and models exactly as in QML, including a partial models config with an unknown key.
- A flow-only project and an invalid one are refused, named.
- The loaders equal their direct calls, and malformed params are refused.
- **A/B against pre-S2 code.** HEAD's `app_controller.py` was loaded beside the new one (as a temporary module, since deleted). On all 15 scenarios, the old and new `run()` give the same errors, the same runner spec, the same options and the same `self.spec` afterwards. This proves the refactor kept QML's behaviour, which the conformance gates alone cannot: both sides of those go through `run_config`.
- **Mutations**, each applied, run and restored, all caught:

  | Mutation | Caught by |
  |---|---|
  | the RPC ignores models | 5 tests |
  | the error drops title and detail | 9 tests |
  | `run.options` ignores the transient | 1 test |
  | `project.spec` drops the sweep | 1 test |
  | `configure_run` changes its input | 1 test |
  | the controller does not stamp the spec | 8 tests |
  | devsim keeps the pytcad engine | 1 test |
  | the project's models are not merged | 1 test (added after this mutation first passed the tests) |

- **Latency**, median round trip through a real service process after warm-up:

  | Method | Median |
  |---|---|
  | `spec.from_example` | 0.57 ms |
  | `project.spec` | 0.45 ms |
  | `run.options` (3D) | 0.30 ms |
  | `spec.configure_run` (3D) | 1.19 ms |

  The `timing` test's bound is 250 ms.
- **Existing tests:** 27 files touching `run()`, the selectors, projects, the backend service and the runners: **325 passed, 1 skipped**, zero warnings. The full suite was not run.

**The full suite, run after S2 (2026-09-26), settling the run §16.17 owed:**
- **Fast suite** (`-n 6 -m "not slow and not timing"`): **2682 passed, 37 skipped, 2 xfailed**, zero warnings, in 6:09.
- **Timing pass** (serial): **10 passed, 2 skipped, 1 failed.** The failure was the soak's memory gate: 0.354 MB/cycle against a 0.3 limit.
  - The last 40 cycles swing between two levels (about 752 and 776 MB), and there is one step up of about 15 MB near the window's start. This is the plateau pattern §16.10 recorded.
  - S2 touched no native code.
  - Re-run alone twice, it passed both times.
  - The gate was not changed.
- **The slow battery was not run.**

### 17.10 P3-S3 results: the C++ job runner (2026-09-26)

**Built.**
- **`desktop/src/run/job_runner.{hpp,cpp}` (new):** the library `tcad_desktop_run`, Qt Core only. It is not in the window yet; that is S4.
- **One run in the main window at a time** (decision 2). `start()` takes an entry point (`moduleEntry("gui.services.solver_runner")`, or a script) and the job file's bytes, and returns the run's id or a named refusal.
- **Signals:**
  - `started(id)`;
  - `line(text, kind)`, where kind is Output, Stage or Stderr;
  - `stage(name)`;
  - `progress(record)`, the §4.3 records;
  - `finished(id, result)`;
  - `failed(id, summary, details)`;
  - `canceled(id)`.
- **A run succeeds only if** it exits 0, prints `RESULT_PATH` equal to the path it was given (compared after normalizing), and that file exists.
- **Failures are named, most specific first:**
  - the child's `PYTCAD_ERROR` payload: the summary is `error: message`, the details its traceback;
  - a crash (`exit code 0x...`);
  - a non-zero exit;
  - no `RESULT_PATH`;
  - a result at another path;
  - a missing result file.

  The details default to the last 400 stderr lines.
- **The child:**
  - is started as `python -u` with `PYTHONUNBUFFERED=1` (decision 7) and `PYTHONIOENCODING=utf-8` (finding below);
  - runs in the backend root;
  - has the app's DLL directory removed from its PATH.
- **Output handling:**
  - Lines are assembled from bytes across reads, with the trailing CR stripped.
  - A line over 1 MiB is delivered truncated and the rest dropped up to the next newline, so memory stays bounded.
  - A malformed progress record goes to the console as text and is counted.
  - A canceled run's remaining output is dropped.
- **Cancel** (decision 3):
  - Each run's process is put in its own Windows job object, which kills it on close. Cancel terminates the whole job, so grandchildren (MPI, pools) die too, and closing the job at the end of a run kills any grandchild a finished run left behind.
  - The process is assigned right after `CreateProcess` returns, before the interpreter can have started a child.
  - After `cancel()`, a new run can start at once. The old run is a separate object: its end removes only its own files and emits only its own `canceled(id)`.
- **The destructor** disconnects every process, kills its tree, waits, and removes its files. It emits nothing into an owner being destroyed (§17.7 point 12).
- **Every outcome removes the job file.** A failed or canceled run also loses its partial and `.tmp.npz` result.
- **Results stay in the configured work directory.** Where that directory lives and how many results are kept (decision 4) is S4's.
- **Backend: `spec.job_text {spec}`** returns the job file's text, from `json.dump(spec.to_dict())`, the same call as `DeviceSpec.to_json`. The native app writes these bytes verbatim.

**Finding: a piped Python stdout on Windows is cp1252, which breaks runs in non-ASCII directories. The QML app has this bug.**
- **Measured with QML's own `JobRunner`,** running `diode_1d` in three work directories:
  - `ascii`: finished;
  - `José`: the solve succeeded, but `RESULT_PATH` arrived garbled (é went out as the cp1252 byte, which does not decode as UTF-8). The run was reported "Simulation failed (see details)", with "no output" as the details;
  - `😀`: the solver's final `print` raised `UnicodeEncodeError` after the result was written.
- **Impact.** QML's work directory is under `%TEMP%`, so any Windows user whose account name has a non-ASCII character cannot run anything in the QML app.
- **Fix.** The native runner sets `PYTHONIOENCODING=utf-8`. The QML fix is the same one line in `job_runner.py`'s child environment. **Applied 2026-09-26** at the user's "proceed". It is gated by `gui/tests/test_job_runner_encoding.py`, which runs QML's runner in `José` and in `µm € 😀` with the parent's encoding variables removed. Before the fix, both runs failed exactly as measured above; after it, both finish.

**Gates**, all green. `tcad_desktop_run_tests` reports 26 results (7 of them failure-mode rows, and the init and cleanup steps), driven by `gui/tests/test_desktop_run.py`.
- **Real `solver_runner`**, with job files written by the QML path:
  - **the 1D diode's bias run:** it opens through `ResultModel` with `solved_bias`. The records start with stage and end with done naming the result, with Newton records between. No record or `RESULT_PATH` text reaches the console, and only the result file is left;
  - **a 4-point sweep:** 4 `sweep_point` records with contact `anode`, and the result holds 4 points;
  - **an unparsable job:** the solver's own `JSONDecodeError`, with its traceback, and no file left;
  - **a run in a directory named `µm € 😀`:** it succeeds.
- **Fakes** (`desktop/tests/fake_solver.py`):
  - a real access violation, exit 5, a `PYTCAD_ERROR` payload, no marker, no file, a wrong path and a 5,000-line stderr flood each fail with their own summary;
  - garbage (invalid UTF-8, a NUL, 3 malformed records) is shown, counted and not fatal;
  - lines of 3 MB and 2 MB (the second split over writes) are truncated, and the next line is intact;
  - a last line without a newline is read at exit;
  - `RESULT_PATH`, a record, and a UTF-8 character each split across writes are reassembled;
  - unflushed lines 50 ms apart arrive spread over more than 1 s.
- **Cancel:**
  - it takes under 2 s, leaves no file and no process, and kills the grandchild;
  - a finished run leaves no grandchild;
  - canceled from inside the handler of a burst's first line, no later line of the burst is shown;
  - cancel then an immediate restart: the first run reports canceled, and the second keeps its job file, finishes, and shows exactly its own 41 lines;
  - a second `start()` is refused, named;
  - destroying the runner mid-run emits no signal and leaves no process, grandchild or file.
- **Refusals:** a missing interpreter and an empty one are named.
- **Job-file bytes:** a job with CRLF, a float repr and non-ASCII text arrives verbatim. `spec.job_text`'s text, as UTF-8, equals the file QML's runner writes (`spec.to_json`) for all 8 accepted-run cases of `test_run_config.py`.
- **Mutations**, each rebuilt and run, all caught:

  | Mutation | Caught by |
  |---|---|
  | child buffered | liveness |
  | stdio not UTF-8 | the non-ASCII run |
  | no job object | the tree, orphan and teardown tests |
  | QML's I-5 (a deferred kill hitting the current run) | restart |
  | the ended run's files taken from the current run | restart |
  | a canceled run's output shown | the burst test |
  | no line bound | the long-line test |
  | no line assembly | the split and long-line tests |
  | any `RESULT_PATH` accepted | `wrong_path` |
  | the destructor not disconnecting | teardown |

  Two of these first went uncaught, and the tests and code changed:
  - **The canceled-output mutation.** The kill is immediate, so no test produced output after a cancel. The burst test was added.
  - **A destructor flag that could never fire.** It was removed, and the mutation moved to the disconnect that makes it unneeded.

  The first crash fake was wrong too. `ctypes.string_at(0)` is caught by ctypes and becomes a clean exit 1, so the fake uses `faulthandler._read_null()`, which gives a real `0xC0000005`.
- **Build:** clean at `/W4`, with both new files recompiled to confirm it.
- **Existing tests:** the runner, `run_config`, backend service, backend client, progress channel and desktop contract files: **217 passed**, zero warnings. The full suite was not run.

### 17.11 P3-S4 design: Run dock, Console, Run/Stop, open on success (2026-09-26)

**What is built.**

- **`run/run_controller.{hpp,cpp}`** (Qt Core): the pipeline from a Run click to a result.
  - **Device.** Load the device through the backend: `spec.from_example`, `spec.load`, or `project.spec`. A project brings its sweep and its models.
  - **Options.** Ask `run.options` for the backends and engines.
  - **Run.** `spec.configure_run`, then `spec.job_text`, then `JobRunner.start`. A C-V job goes through `cv.job_text` and `moscap_runner` instead.
  - **Stop** works in either phase. If the run is still in the backend calls, the late reply is ignored. If it is running, the runner cancels it.
  - **Refusals keep their titles.** A `RunConfigError` arrives with its own title and detail, now readable through a new `BackendReply::errorData()`. A spec that fails its own validation is titled as QML titles it at arm time, e.g. "Invalid sweep configuration".
- **`shell/run_panel.{hpp,cpp}`, the Run dock:**
  - **Device:** an example, a DeviceSpec file or a project.
  - **Run kind:** Equilibrium, Bias (the device's own contact voltages), Sweep, Transient, AC, or C-V (MOS capacitor).
    - Sweep: contact, start, stop, step.
    - Transient: contact, waveform (step, ramp, pulse, constant), v0, v1, t0, t1, t_end, dt0.
    - AC: contact, f_start, f_stop, points.
    - C-V: Nsub, tox, and the gate ramp. C-V needs no device.
  - **Contacts** come from the loaded spec.
  - **Backend and engine** come from `run.options`. A disabled entry carries its reason as a tooltip.
  - **Numbers** are typed text in C locale, so scientific notation works. A non-finite value is refused before anything is sent.
- **`shell/console_panel.{hpp,cpp}`, the Console dock:**
  - every line, with stage lines in bold and stderr lines in the muted token colour;
  - a failure's summary and details in the error colour;
  - capped at 50,000 lines, with the number of dropped earlier lines shown (§17.7 point 11);
  - lines batched every 50 ms, so a flood does not stall the window.
- **MainWindow:**
  - toolbar and Run menu entries Run (F5) and Stop (Shift+F5);
  - the Run dock on the right edge and the Console along the bottom (layout version 6);
  - the status bar shows the stage and the elapsed time;
  - on success, `tryOpen(result)` opens the result in its natural view (`defaultMode`), and it joins Open Recent;
  - File > Save result as... copies the open result;
  - the run controller is torn down first in `~MainWindow` (§17.7 point 12).
- **Runs directory** (decision 4):
  - the settings key `run/dir`, else `%LOCALAPPDATA%/PyTCAD/runs`;
  - after each run, the 20 newest `result-*.npz` are kept and the open result is never removed;
  - job and `.tmp.npz` files older than 24 h are removed. That age is the guard for a second app instance sharing the directory.
- **Backend:** `cv.job_text {nsub_cm3, tox_nm, vstart, vstop, vstep}` gives the job text QML's `CVController` writes. That builder moves to the Qt-free `gui/services/cv_job.py`, which `CVController` then uses.

**Gates** (new executable `tcad_desktop_run_shell_tests`, the real window; driven by `gui/tests/test_desktop_run_shell.py`):
- **Run to view, end to end:**
  - the diode's bias, sweep, transient, AC and equilibrium runs;
  - a C-V run;
  - `mosfet_2d` and `resistor_3d`.

  Each opens in its natural mode, in the runs directory, and the console holds its stage lines and no record text.
- **Sources:** a DeviceSpec file; a project whose models config reaches the result's run record; a flow-only project refused, named.
- **Refusals:** a sweep step of 0 is refused, named, and nothing runs.
- **Stop:**
  - during the solve: canceled, nothing opened, the previous result still shown, no job file;
  - during the backend phase: nothing starts.
- **Closing the window mid-run:** no crash, no process left, no job file.
- **The console cap:** 60,000 lines leave 50,000 and report 10,000 dropped.
- **Retention:** 25 results leave the 20 newest, plus the open one if it is older.
- **Mutations**, each rebuilt and run:
  - Stop ignored in the backend phase;
  - no console cap;
  - the open result pruned;
  - the job run with the spec's own models instead of the project's.

### 17.12 P3-S4 results: Run dock, Console, Run/Stop, open on success (2026-09-26)

**Built** as §17.11 designed, with these changes found while building:

- **Where the docks go.** Run is tabbed with Fields, and Console with Info, Display, 3D and Plot. Fields and Display stay in front.
  - Docked beside the view (Run on the right, Console along the bottom), they cut the view from nearly the whole 1500 x 950 window to 1014 x 616 (measured).
  - That also broke the P2 curve-image probes, `curveModeImagesProbe(recombination)` and `(transient)`, in the shell and HiDPI suites. Existing tests stay unchanged, so the layout changed instead.
  - Now the view is exactly the size it is with both docks closed, in a fresh window and after Reset layout (gated).
  - The cost: in the left column the Run form scrolls, and its Backend/Engine selectors and Run/Stop buttons sit below the fold. The toolbar's Run and Stop are always visible. Either dock can be dragged elsewhere, and the layout persists.
- **No Python before it is needed** (the shell's P1 rule, gated by `backendWarmsUpAfterA2DResultOpens`), kept:
  - the run controller gets the backend client through a function, so the client is still created on first use;
  - the examples are listed when the Run tab is first shown or focus enters it, never with the window.
- **The natural view.** A run opens in the mode of its kind: sweep in Curves, transient in Transient, AC in AC, C-V in C-V. Otherwise it opens in the default an opened file gets. `defaultMode` alone opened a sweep in the Field mode.
- **Signals carry `JsonPayload`, not `nlohmann::json`.**
  - Declaring `nlohmann::json` as a Qt metatype made Qt's traits probe its catch-all converting constructors, which failed to compile with QtWidgets included (the incomplete Windows `MSG`).
  - `JobRunner::progress` and `RunController::optionsChanged` now carry a one-member struct.
- **A project's sweep in the form** is written in the shortest round-trip form: 0.2, not 0.20000000000000001.
- **Found in the window grabs: the status bar never showed a message (P1 bug, fixed).**
  - The hover readout was a permanent status widget with stretch 1, and Qt draws a temporary message only beside the permanent widgets. So every `showMessage()` since P1 had zero width. Errors were still seen, because each also opens a message box.
  - The readout now has no stretch. A pixel test failed first (0 dark pixels with a message set) and passes now.
- **`BackendReply::errorData()`** exposes a JSON-RPC error's data, so a `RunConfigError` keeps its title and detail.
- **`cv.job_text`** comes from the Qt-free `gui/services/cv_job.py`, which QML's `CVController` now uses too. It equals the file `CVController` writes, byte for byte, in three cases: its zero-step fallback, its absolute step, and a plain one.

**Gates.** `tcad_desktop_run_shell_tests` reports 24 results, all green. It runs the real window, the real backend and the real solver, driven by `gui/tests/test_desktop_run_shell.py`.
- **The Run and Console docks cost the view nothing.**
- **No Python starts until the Run tab is shown.** Once it is, the examples are listed and the diode loads.
- **The status message is drawn.**
- **Run to view:**
  - the diode's bias, equilibrium, sweep (4 points, Curves), transient (Transient) and AC (7 points, AC) runs;
  - a C-V run (17 points, C-V, with no device loaded);
  - `mosfet_2d` (2D) and `resistor_3d` (3D).

  Each checks that:
  - the result is in the runs directory and joined Open Recent;
  - the view is in its natural mode;
  - the console has `PYTCAD_STAGE` lines and no record or `RESULT_PATH` text;
  - no job or tmp file is left;
  - Run is enabled again and Stop disabled.
- **Sources:**
  - a DeviceSpec file runs;
  - a project selects its armed sweep, and its `auger: false` reaches the result's run record;
  - a flow-only project is refused as "Nothing to run", naming the process flow.
- **Refusals:**
  - a zero sweep step fails as "Invalid sweep configuration: sweep step must be nonzero", QML's arm-time title, and nothing runs;
  - a non-number is refused in the form.
- **Stop:**
  - during a 101-point `mosfet_2d` gate sweep: canceled, the process dead, the job file gone, the runs directory empty, the previous result still shown;
  - before the solver starts: canceled at once, and the late backend replies start nothing.
- **Closing the window:**
  - mid-run: no process, no file, no error box;
  - while the backend prepares: no failure reported into the dying window, no error box.
- **Save result as** makes a byte copy, and saving onto the open file itself is refused.
- **The console:** 60,000 lines keep the last 50,000 and report 10,000 dropped; a traceback's last newline adds no line.
- **Retention:** 25 results leave the 20 newest plus the open (oldest) one. Stale job and tmp files go; a fresh job file and a file that is not the runner's stay.
- **Looked at:** window grabs after a sweep run and after a Stop (the `TCAD_SHELL_SNAPSHOT` hook, as in the shell tests).
- **Mutations**, each rebuilt and run, all caught:

  | Mutation | Caught by |
  |---|---|
  | Stop ignored while the backend prepares | stop before the solver starts |
  | a late backend reply not disowned | stop before the solver starts |
  | no console cap | the console test |
  | the open result pruned | retention |
  | the project's models not sent | the project test |
  | no natural view | the sweep, transient, AC and project tests |
  | the Run dock beside the view | the layout test and the no-Python test |
  | Python started with the window | the no-Python test |
  | the run controller not torn down before the backend | closing while the backend prepares |

  The last mutation first went uncaught, and the test after it was added for it.
- **Existing tests:** every native-app test file (`gui/tests/test_desktop_*.py`, among them the P2 shell and HiDPI suites) and the Python files S2 to S4 touch, `-m "not slow and not timing"`: **726 passed, 1 skipped**, zero warnings.
- **Also this step:** QML's `job_runner.py` got the `PYTHONIOENCODING=utf-8` fix (§17.10, applied).
- **Not run:** the full suite.

### 17.13 P3-S5 results: the Telemetry dock (2026-09-27) -- CLOSED

**Built.**
- **`run/telemetry.{hpp,cpp}`: `TelemetryModel`, Qt-free.** It folds the §4.3 records into state:
  - the stage;
  - the newton records, as trace steps. A new step starts at each stage change, and each metric is a channel in the order the record wrote it, with a gap where a record lacks a metric;
  - the sweep point, whose index is 0-based as written (it matches the trace's `sweep:0`);
  - the transient step, done with its dropped count, and error.

  A record outside the grammar is counted and changes nothing, and a null value becomes NaN.
- **`shell/telemetry_panel.{hpp,cpp}`, the Telemetry dock**, tabbed with Console, Info, Display, 3D and Plot:
  - status, elapsed time, stage, "Newton: iteration i of stage s (n in all)", "Sweep: point k of N, contact = V", "Transient: step n, t, dt, iterations", and notes;
  - the residual history on a log axis, redrawn at most every 100 ms.
- **The plot is drawn by the Convergence mode's own function.** `convergenceModel(const std::vector<TraceStep>&, empty_text)` is the old body; the `ResultModel` overload now calls it. So a finished run's live plot is its result's Convergence plot (gated below).
- **Stage-level progress only** (§17.7 point 2) is stated, not left as an empty plot:
  - up front, for a C-V run or the MPI Schwarz engine;
  - at the end, for a run that reported stages but no Newton iteration. The auto engine can pick MPI.
- **Dropped records are said too:** "N progress records were dropped...; the Convergence mode has every iteration".
- **Records keep their key order.** They travel as `ProgressRecord{nlohmann::ordered_json}`, as the result reader keeps the trace's order (`ordered_json`). The sorting `nlohmann::json` would put F, dn/n, dpsi in the wrong line styles (mutation-tested).
- **`RunController::lastOutcome()`** is set before `busyChanged(false)`, and the dock ends on it. After a Stop, `runCanceled()` arrives only when the process is gone, possibly after the next run began.
- **Layout version 7.**
- **The status bar says "Run finished in 0.6 s"**, not "0 s".

**Found while testing:**
- **The sweep label was 0-based.** It showed "point 3 of 4" at the last point, because the record's index is 0-based by S1's design. It now shows index + 1.
- **devsim was offered but could not run on this machine (pre-existing).**
  - pip's devsim 2.11.0 finds no BLAS (`libopenblas.dll` missing, no MKL) and raises "Issues initializing DEVSIM" on import.
  - `workbench.solvers.base._register_devsim` imports only the adapter module, and the adapter loads devsim lazily. So `backend_ids()` lists devsim, both apps' selectors enabled it, and every devsim run failed.
  - Resolved for the native app by the decision below.

**Gates** (`tcad_desktop_run_shell_tests`, 31 results after the decision below, all green):
- **A diode sweep's telemetry is its convergence plot:**
  - every record folded (newton count equal, nothing ignored, done, 0 dropped);
  - the stage, iteration and sweep labels equal the last records' ("point 4 of 4, anode = 0.3 V");
  - the live plot equals `convergenceModel(result)`: labels, colours, line styles, legend entries, x, and y (NaN-aware), series for series.
- **Live and ends with the run:**
  - on a 101-point `mosfet_2d` gate sweep, while it runs: "Running: ...", "point k of 101, gate = ...", Newton series drawn;
  - Stop ends the dock at once as "Canceled", and no record is folded after it;
  - the next run starts afresh.
- **Transient:** the step count and last time equal the records'.
- **Stage-level only:** a C-V run shows the note and the stage-level plot message.
- **`TelemetryModel`:** stage grouping, metric order kept, gaps for absent and null metrics, five malformed records ignored and counted, a relayed sweep point, done's dropped count, error.
- **The layout gate now includes the Telemetry dock:** the view still loses nothing.
- **Looked at:** a window grab after the diode sweep, with the Telemetry tab in front.
- **Mutations**, each rebuilt and run:

  | Mutation | Caught by |
  |---|---|
  | records not forwarded to the dock (§17.4's "progress events not forwarded") | 4 tests |
  | metrics sorted by name | 2 tests |
  | no new step per stage | 2 tests |
  | the sweep point 0-based | 1 test |
  | stage-level runs not said | 2 tests (the C-V test, and a devsim test since replaced) |
  | the dock not ended with the run | 2 tests |
  | the outcome not recorded on Stop | 1 test |
  | records after the run's end still applied | **missed** |

  The missed mutation's guard was unreachable: a canceled run's output is dropped by the JobRunner (S3's burst test), and a finished or failed run's records all arrive before its end. It was removed rather than kept untested.
- **Existing tests:** every native-app test file plus the Python files S2 to S5 touch, `-m "not slow and not timing"`: **631 passed**, zero warnings.
- **Not run:** the full suite.

**Decision (user, 2026-09-27): the native app does not support devsim.** P3-S5 is closed with it.
- **What changed:**
  - The native backend list is pytcad only. `RunController` keeps only the backends the app runs when `run.options` answers.
  - `run()` refuses any other backend, named ("Backend not supported: the native app runs the pytcad backend only"), before any backend call or process.
  - §17.2's "Backend and engine: the QML options" now means, for the backend, pytcad alone.
  - The Telemetry dock's devsim note is gone.
- **What did not change:**
  - The backend service's `run.options` still lists devsim. It is QML's list, gated equal to QML's selector in `test_run_config.py`, and the native app filters it.
  - No devsim Python code was touched (`workbench/` has no change), and QML is unchanged. It still offers devsim, which still fails on this machine.
  - No BLAS or MKL was installed, and no import probing was added.
- **Gates** (the devsim telemetry test is replaced by these):
  - **`theNativeAppOffersPytcadOnly`:** for the diode, which the service lists devsim for, the Backend selector holds exactly `pytcad`. The service's own `run.options` is asserted to still list devsim, so the gate cannot pass vacuously.
  - **`aRunOnAnotherBackendIsRefusedNamed`:** a programmatic run with `backend = "devsim"` fails as "Backend not supported". Nothing is busy, no process starts and no file is written.
  - **`theSupportedBackendRunsWithAChosenEngine`:** the diode with the Direct engine opens as a result whose run record says `"backend": "pytcad"`.
  - **Mutations**, each rebuilt and run, both caught:

    | Mutation | Caught by |
    |---|---|
    | devsim let through the native filter | the selector test and the refusal test |
    | `run()` taking any backend | the refusal test |
- **The supported backend still works:**
  - `tcad_desktop_run_shell_tests` is green (31), with every run kind on pytcad;
  - every native-app test file plus the Python files S2 to S5 touch, with `test_m7_devsim.py` and `test_engine_selector.py`: **639 passed, 1 skipped** (an existing devsim test), zero warnings.
  - The full suite was not run.

### 17.14 P3-S6 design: families and comparisons by running (2026-09-27)

The P2-S5 overlays (families and one comparison, from result files) now also come from runs started in the app. The jobs are built by the backend (decision 1), with QML's own rules.

- **`gui/services/family_jobs.py` (new, Qt-free):**
  - It holds QML's family rules, moved from `FamilySweepController`: the stepped values (the step must move toward the stop), each curve's spec (the base spec with the swept ramp, and the stepped contact's bias set), the labels (`cathode=0.1 V`), and the refusals with QML's titles ("Invalid family configuration", "Family cannot run", "Invalid family sweep").
  - It also holds the models-off comparison spec, moved from `AppController.runModelComparison` (label "all models off").
  - Both QML controllers call these functions, so the two apps build the same jobs.
- **Backend methods:**
  - `family.jobs {spec, stepped, values: {start, stop, step}, swept: {contact, start, stop, step}}` returns `[{label, value, job_text}]`;
  - `comparison.job {spec}` returns `{label, job_text}`.

  Each `job_text` is byte-identical to the job file QML's runner writes for the same inputs.
- **Native: `run/batch_controller.{hpp,cpp}`.**
  - It runs a family's jobs or a comparison **sequentially on its own JobRunner** (decision 2: families have their own pool), beside the main run.
  - The base is the last main run's configured spec, and it must be a sweep. A family re-solves that sweep at each stepped value, and a comparison re-solves it with every model off. Anything else is refused, named.
  - Each finished curve is added as an overlay (`addOverlay`, its P2-S5 checks and refusals unchanged) with its label, in the Curves view.
  - The batch belongs to the result that was open when it started. If another result is opened, the batch is canceled, named.
  - Stop cancels the batch mid-way; the curves already added stay, as in QML.
  - `~MainWindow` tears the batch controller down before the backend, as for the run controller.
- **The Run dock:** a "Family and comparison" group (the stepped contact, start/stop/step, Run family, Run comparison, Stop batch, and a status line).
- **Not in S6:** the backend comparison, which needs devsim (not a native backend, §17.13).

**Gates:**
- **Python:** `family.jobs` and `comparison.job` job texts equal QML's job files byte for byte, and every refusal equals QML's `errorRaised`. The existing family and comparison tests pass unchanged.
- **Native, end to end:**
  - a family of 3 on the diode's sweep gives 3 labelled Family overlays;
  - the comparison gives 1 Comparison overlay whose result's run record has every model off;
  - a family before any sweep run, a wrong step direction, and a result opened elsewhere are refused, named;
  - a family canceled mid-way keeps its finished curves, with no process and no job file left;
  - opening another result cancels the batch;
  - closing the window mid-family leaves nothing running.
- **Mutations:**
  - a curve added to a result the batch does not belong to;
  - the curves not labelled;
  - cancel leaving the queue running;
  - the batch controller not torn down first.

### 17.15 P3-S6 results: families and comparisons by running (2026-09-27)

**Built** as §17.14 designed:
- **`gui/services/family_jobs.py`:**
  - `family_values`, `family_specs`, `family_label` and `comparison_spec`, with QML's titles as `RunConfigError`s;
  - `FamilySweepController` (`configureFamily`, `runFamily`, its labels and console lines) and `AppController.runModelComparison` now call it;
  - `import copy`, left unused in the controller, is removed.
- **Backend:** `family.jobs` and `comparison.job`, each job text written by `DeviceSpec.to_json`'s own `json.dump`.
- **Native:**
  - **`run/batch_controller.{hpp,cpp}`:** runs a family or the comparison sequentially on its own JobRunner. The base is `RunController::lastRunSpec()`, the configured spec of the last finished DeviceSpec run; a C-V run does not count.
  - **Refusals before anything starts:** no run yet, the last run not a sweep, and the open result not the last run's.
  - **Each finished curve** becomes a P2-S5 overlay with QML's label, drawn in the Curves view.
  - **Opening another result stops the batch.** A curve the overlay checks refuse also stops it.
  - **The Run dock's "Family and comparison" group:** the stepped contact, start/stop/step, Run family, Run comparison, Stop, and a status line.
  - **`~MainWindow`** deletes the batch controller right after the run controller, before the backend.
- **Not built:** the backend comparison, which needs devsim (§17.13).

**Gates:**
- **Python** (`gui/tests/test_family_jobs.py`, 13 tests):
  - `family.jobs` job texts equal the files QML's family runner writes, byte for byte, for three cases: three curves, a reverse step, and one value;
  - labels and values are QML's;
  - `comparison.job` equals QML's comparison job file byte for byte, with every model off;
  - four family refusals equal QML's `errorRaised` (wrong direction, stepped or swept contact missing, invalid sweep), and so do "Nothing to sweep" and "Nothing to compare";
  - the base is not modified;
  - malformed params are INVALID_PARAMS.
- **A/B against pre-S6 code.** HEAD's `family_sweep_controller.py` and `app_controller.py` were loaded as temporary modules, since deleted. Same job bytes, values, console lines and refusals in all 8 family and 4 comparison scenarios. The conformance gates cannot prove this, since both sides of them go through `family_jobs`.
- **Existing tests:** `test_family_sweep.py`, `test_m30_run_comparison.py` and `test_performance_family_sweep_signals.py` pass unchanged.
- **Native end to end** (`tcad_desktop_run_shell_tests`, now 38 results, all green):
  - a family of 3 on the diode's anode sweep gives three Family overlays labelled `cathode=0 V`, `cathode=0.1 V` and `cathode=0.2 V`, each on the base sweep's voltages, with 4 series drawn and no job file left;
  - the comparison gives one overlay labelled "all models off", whose result's run record has every model off;
  - refusals are named: nothing run yet; a bias run as base ("Nothing to compare"); a wrong step direction (QML's "Invalid family configuration", from the backend); another result open;
  - a family stopped mid-way keeps its finished curves, no more arrive, no process or job file is left, and the status reads "Family stopped after ...";
  - opening another result stops the batch, draws nothing over it and refuses nothing on it, with a console note;
  - closing the window mid-family, and while `family.jobs` is in flight, leaves no process, no error box and no batch signal during teardown.
- **Looked at:** a window grab of the diode's anode sweep with its cathode family. The forward current falls as the cathode is raised.
- **Mutations**, each rebuilt and run:

  | Mutation | Caught by |
  |---|---|
  | a batch's curves drawn over another result | the reopen test |
  | the curves not labelled | the family and comparison tests |
  | Stop leaving the batch going | the stop and reopen tests |
  | the batch controller not torn down first | the prepares-close test, after a fix to it |

  The last mutation first went uncaught. The warm backend answered `family.jobs` during `~MainWindow`, so the batch started a solver job in the dying window (killed by its runner) and reported no failure, while the test watched only `failed()`. The test now counts any batch signal during teardown, and catches the mutation.
- **Existing tests:** every native-app test file plus the Python files S2 to S6 touch (including the family, comparison, controller and QML smoke tests), `-m "not slow and not timing"`: **694 passed, 1 skipped** (an existing devsim test), zero warnings.
- **Not run:** the full suite.

### 17.16 P3-S7 plan: the local Study (2026-09-27, awaiting approval)

A Study (M30) is a split matrix: one device per combination of parameter levels, each solved as an ordinary job, in a pool of parallel runners. P3-S7 brings QML's local Study to the native app. Remote hosts are S8.

**What QML does today** (checked in the tree, `gui/controllers/study_controller.py` and `gui/qml/panels/StudyPanel.qml`):
- **Definition.** A template id, base parameters as `KEY=value` lines, and splits as `PARAM = v1, v2, ...` lines.
  - `configureStudy` runs `workbench.splits.run_split_matrix` (a Cartesian product, the last axis fastest).
  - A row the template rejects is `build_error` and never runs.
- **Rows** are statuses `build_error | pending | running | done | failed`. Each row's job is `spec_from_domain(device)` with `bias = None` and `sweep = None`.
  - **Every QML study row is an equilibrium solve.** `setBias` exists, but no QML code calls it.
- **The pool:**
  - its size is `workbench.batch.default_worker_count(n)`: `min(6, cpu count, n)`;
  - each runner takes the next pending row when it frees;
  - a failed row does not stop the others.
- **Cancel all** returns the running rows to `pending`, and Run re-runs pending and failed rows.
- **A row's View** opens its result in the main view (`loadStudyResult`).
- **Matrix viewer** (M30 phase 6): for a 2-axis study, a grid of `max(field)` per done row. A row not done is shown as nothing, never as 0 (gate G-PARTIAL).
- **Row comparison** (M30 phase 7): a horizontal line cut of a 2D field across chosen done rows, with a provenance diff table of their run records.

**Design (decision 1 as before: the backend builds the jobs).**
- **`gui/services/study_jobs.py` (new, Qt-free).** It moves QML's row building out of `StudyController`: `configureStudy`'s matrix and statuses, `_spec_for_row`, and `matrixCells`'s reduction. `StudyController` calls it, as S2/S6 did for runs and families.
- **Backend methods:**
  - `study.templates` gives each template's id, title, description and parameters (name, label, unit, default, bounds, integer);
  - `study.rows {template_id, base, splits}` gives `{axes, rows: [{params, status, error, job_text|null}]}`. A row that builds has a `job_text` byte-identical to QML's job file; a `build_error` row has none.
- **Native `run/study_controller.{hpp,cpp}`** (Qt Core):
  - the rows and QML's status vocabulary;
  - a pool of N JobRunners, N defaulting to QML's `default_worker_count(n)` and adjustable from 1 to 6;
  - dispatch in row order, with failed rows isolated;
  - Cancel all, which returns running rows to pending as QML does, and Run, which re-runs pending and failed rows;
  - independent of the main run and the family batch (decision 2);
  - torn down before the backend in `~MainWindow`.
- **The Study dock** (`shell/study_panel.{hpp,cpp}`), with the factor/level table of §17.7 point 13:
  - a template combo; a base-parameter table from the template (name, value, unit, default);
  - a splits table (parameter, levels "v1, v2, ...", add and remove);
  - pool size; Build rows, Run and Cancel;
  - the rows table: index, the split parameters, status, error. Double-click opens a done row's result in the main view (`tryOpen`, as QML's View);
  - a status line with counts;
  - the matrix grid for a 2-axis study, with a field chosen from the done rows' results.

  Its placement follows S4's rule: a tab in the left column, costing the view nothing.
- **The matrix value** `max(field)` is computed in C++ from `ResultModel`, the reader already gated equal to Python's. A contract test compares it with `StudyController.matrixCells` on the same files.
- **Where results go:** each study writes into its own `runs/study-<stamp>/` directory, so the main runs' keep-20 retention never removes a study's rows.

**Decisions (defaults proposed):**
1. **Rows are equilibrium solves, as QML's.** No bias or sweep per study in S7. A bias option would be new behaviour, not a port.
2. **The matrix viewer is in S7.** It is what makes a study readable, and the 2-axis grid is small.
3. **The row comparison is deferred to P4.** It needs multi-result line cuts plus a provenance diff table, a new view kind. The alternative is to include it in S7, which makes it about twice as big.
4. **Study results are kept per study.** The 5 most recent `study-*` directories stay, and the directory of an open result is never removed. The alternative is to keep every study's results.
5. **Definition by tables, not QML's free text.** Bounds come from the template, and a value it rejects is still a named `build_error` row. The alternative is the same text areas as QML.

**Gates:**
- **Python:**
  - `study.rows` equals `StudyController.configureStudy`'s rows (params, statuses, errors, axes) for a 2 x 2 `mos_capacitor` study that includes a rejected value;
  - every `job_text` equals the job file QML's pool runner writes, byte for byte;
  - `study.templates` equals the templates' own parameter lists;
  - an A/B against HEAD's `StudyController` (as S2/S6);
  - the existing M30 tests pass unchanged.
- **Native, end to end:**
  - a 2 x 2 `mos_capacitor` study (tox x na, plus one rejected value) with pool 2: the rejected row shows `build_error` and never runs; never more than 2 rows `running`; all others reach `done`; a done row opens in the main view;
  - the matrix grid's values equal `matrixCells` on the same files, and a row not done shows empty, not 0;
  - a row made to fail is `failed` with its error, and the rest finish;
  - Cancel all mid-way: running rows back to `pending`, no process, no job file; then Run completes the rest;
  - closing the window mid-study leaves no process;
  - the default pool size equals `default_worker_count(n)` for several n;
  - the dock costs the view nothing.
- **Mutations**, each rebuilt and run:
  - the pool size not honoured;
  - Cancel leaving rows pending in the queue;
  - a failed row stopping the study;
  - a not-done matrix cell shown as 0;
  - a row dispatched twice;
  - the study controller not torn down first.
- **Size: M**, as §17.3 had it. About half is the dock and its tables, and half the controller, the backend methods and the gates.
