# PyTCAD native desktop app (P0 spike)

A native C++20 / Qt 6 Widgets / VTK desktop application, built beside
the QML GUI (`gui/`). Plan, contracts, gates and measured results:
`../NATIVE-DESKTOP-PLAN.md`.

## Build (Windows)

Needs Visual Studio with the C++ x64 tools, plus the separate
`tcad-gui` conda env (never `tcad-dev`):

```powershell
conda create -n tcad-gui -c conda-forge --override-channels python=3.13 `
    "qt6-main>=6.11,<6.12" "qt6-advanced-docking-system=5.1.1" vtk-base vtk-io-ffmpeg cmake ninja nlohmann_json
conda install -n tcad-gui -c conda-forge --override-channels tbb-devel==2023.1.0
```

Qt and the docking system (ADS) are pinned together: each ADS build on
conda-forge targets one Qt minor version, and 5.1.1 is built against
qt6-main 6.11 (NATIVE-DESKTOP-PLAN.md §15.9). An existing env gains ADS
as one new package, with nothing else changed (checked 2026-09-25):

```powershell
conda install -n tcad-gui -c conda-forge --override-channels "qt6-advanced-docking-system=5.1.1"
powershell -ExecutionPolicy Bypass -File desktop\build.ps1 -Test
```

The output goes to `build\desktop\` (gitignored). Dev builds copy no
DLLs. `desktop_runtime.json` records where the Qt/VTK DLLs live, and
the generated launcher `tcad_desktop.cmd` puts them on PATH.

## Run

```powershell
build\desktop\tcad_desktop.cmd path\to\result.npz
build\desktop\tcad_desktop.cmd --settings my.ini path\to\result.npz   # a settings file of your own
build\desktop\tcad_desktop.cmd --bench path\to\result.npz --frames 120 [--size 600x360]
build\desktop\tcad_desktop.cmd --selftest a.npz [b.npz ...] [--size 600x360]
build\desktop\tcad_desktop.cmd --bench-backend path\to\result.npz [--repeats 5]   # backend round trip
python desktop\bench\run_bench.py [--native-only]   # native vs today's viewport
```

The toolbar's view-mode box (also View > View mode) offers what the
open result holds: the field map (2D/3D) or the field curve (1D), the
sweep (Curves or C-V), a transient, an AC run, the convergence record,
a line cut of a 2D map (the map above, the cut below; the Plot panel
sets its orientation and node),
and for 1D results the bands and recombination (computed by the
backend). Log and Fit act on the view shown; the Plot panel picks the
sweep channel and adds overlays: a comparison sweep (dashed) and a family
of sweeps from other result files, each on its own voltages, refused
(with the reason) when the contact, quantity, unit or channel differ.

The app has one black-and-white look (no light/dark modes; data keeps its
colours). Settings (window layout, recent files) live in
`%APPDATA%\PyTCAD\PyTCAD Desktop.ini`; delete it to reset. `--bench` and
`--selftest` never read or write it.

## Tests

All are skipped when the app is not built. The ones that open windows
need a real display: the viewer needs a GL surface, and
`QT_QPA_PLATFORM=offscreen` fails with a clear error.

- **C++ unit tests:** `build.ps1 -Test`, or through the Python suite.
- **C++ <-> Python contracts:**
  - `gui/tests/test_desktop_contracts.py`: `.npz` reader vs numpy;
    result model vs `validate_result` and `NpzResultStore`; the info
    view; the curve blocks (sweep, transient, AC, convergence trace);
    DeviceSpec round trip.
  - `gui/tests/test_backend_service.py`: the `backend_service/`
    JSON-RPC server.
- **Viewer correctness:** `gui/tests/test_desktop_selftest.py` runs
  `--selftest` (displayed values and range vs a fresh decode; the 3D
  hover oracle, full and cropped; stale state across results; 2D pixel
  probes; and the 3D layers -- faces, slices, isosurface, volume,
  glyphs, streamlines, exploded view, playback -- NATIVE-DESKTOP-PLAN.md
  15.19/15.20).
- **Shell end-to-end:** `gui/tests/test_desktop_shell.py` runs
  `tcad_desktop_shell_tests` (`tests/test_shell.cpp`). It covers
  open/drop/recent files, layout persistence, the black-and-white theme, the info panel,
  the Display, 3D and Playback panels (one test per 3D parity item),
  deleted/replaced results, the end-to-end scenario, one test per 2D
  parity item, adversarial files and settings, and (P2-S3) one test per
  curve mode on real 1D runs, the modes a result cannot show, and view
  switching without re-creating the GL context.
  `TCAD_SHELL_SNAPSHOT=<dir>` saves the window in each curve mode as a
  PNG, to look at.
- **Backend client:** `gui/tests/test_desktop_backend.py` runs
  `tcad_desktop_backend_tests` (`tests/test_backend.cpp`) against the
  real `backend_service` and the misbehaving fakes in
  `tests/fake_backend.py`: timeouts, kills mid-call, crashes, protocol
  errors. No display needed.
- **Theme:** `gui/tests/test_desktop_theme.py` (tokens equal
  `gui/qml/Theme.qml`'s; every token a grey except the status colours;
  no hard-coded colours outside `src/theme/`).
- **HiDPI:** `gui/tests/test_desktop_hidpi.py` (the selftest and the
  shell view tests at `QT_SCALE_FACTOR` 1, 1.5 and 2).
- **PlotView (P2):** `gui/tests/test_desktop_plot.py` runs
  `tcad_desktop_plot_tests` (`tests/test_plot.cpp`) at `QT_SCALE_FACTOR`
  1, 1.5 and 2 -- the real widget rendered with `grab()` and probed pixel
  by pixel, hover, view control, label overlap -- plus its bench
  (`TCAD_PLOT_BENCH=<out.json>`). `TCAD_PLOT_SNAPSHOT=<dir>` saves renders
  to look at. `gui/tests/test_desktop_plot_ticks.py` compares the axis
  maths (`tcad_plot_ticks`) with matplotlib's locators and formatters.

## Layout

```
src/data/       .npz reader, result model, Python-compatible JSON   (Qt-free)
src/document/   lossless DeviceSpec document                        (Qt-free)
src/theme/      colour tokens (Qt-free) + Qt palette / ADS stylesheet
src/tools/      contract tools run by the Python suite
src/shell/      MainWindow (ADS docking, the view-mode selector), settings, panels
src/views/      VTK FieldView; colour maps (data, not theme);
                plot/: PlotView (QPainter), its Qt-free axis maths, and the
                curve modes (curve_modes: a result -> PlotModel)
src/bench/      --bench frame timing, --selftest correctness checks
tests/          Qt Test: unit tests (test_data.cpp), shell e2e (test_shell.cpp),
                PlotView (test_plot.cpp)
bench/          benchmark harness (Python)
```
