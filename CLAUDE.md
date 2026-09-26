# CLAUDE.md — Guidance for AI agents working on PyTCAD

Complete briefing for repo. Assumes no prior conversation, no particular model. Read in full before touching any file. Follow literally: frozen file = don't edit; "run tests" = actually run, read real output, don't assume. Each concrete gotcha below already cost one real debugging session; repeat costs another. If anything here conflicts with user request in a conversation, say so and ask — don't silently pick.

**`Architecture_Master_Plan.md` removed from working tree 2026-09-10, lives only in git history.** Docs still cite it by section number (34-37: benchmark cases, dashboard, no-unproven-performance-claims rule; 41-42: architectural tests, frozen API surface) — those sections still reason behind existing gates. Read via `git show a117d03:Architecture_Master_Plan.md`; citation not broken link.

Read this first. Then read `history.md` (current state + open items — read at least LAST few entries; state changes faster than this file), `ARCHITECTURE.md` (roadmap + live queue; governing future plan in sections 4b (M13-M30, essentially closed) and 4c (M31 onward — C++/Python/Qt re-architecture, plus proposed M32-M40 map)), and active milestone spec. As of 2026-08-31 only genuinely OPEN core-solver item: `pytcad/M14-SURFACE-MOBILITY-PLAN.md`'s G-A (blocked on paywalled source); M16/M17/M18/M19/M20/M21/M22 all landed for stated scope (see "Milestone state & plans" below and each milestone's plan doc for scope and what's honestly deferred). Also read `pytcad/GUI-IMPROVEMENT-
PLAN.md` and `pytcad/3D-VISUALIZATION-PLAN.md` for GUI state.

## What this is

PyTCAD: validated TCAD toolkit (1D/2D/3D drift-diffusion, process simulation) + Semiconductor Workbench layer (`workbench/`) + PySide6/QML desktop GUI (`gui/`). Every educational surface backed by real computation. Never fake, never mock, never weaken tests.

## Layout

```
pytcad/            numerical core (device.py, device2d.py, device3d.py,
                   moscap.py, process.py, materials.py, mesh*.py)
workbench/
  core/            domain objects (Region, DomainDevice, ModelCatalog,
                   MaterialLibrary, templates)
  adapters/        lossless DomainDevice <-> DeviceSpec conversions
  solvers/         SolverBackend protocol + pytcad & devsim backends
  analysis/        observables (band_diagram, recombination_rate, ...)
  physics/         analysis-layer physics (impact_ionization,
                   tunneling) -- published-value gated
  workflow.py      deck front end (TEMPLATE/BIAS/SWEEP statements)
gui/
  services/        DeviceSpec (wire format), JobRunner (subprocess),
                   ResultStore, solver_runner/moscap_runner/process_runner,
                   examples.py (File-menu quick-load DeviceSpecs, 1D/2D/3D),
                   viewer3d.py (PyVista/VTK 3D viewer, a separate QWidget
                   window -- see 3D-VISUALIZATION-PLAN.md)
  controllers/     AppController + small per-domain controllers
  qml/             Main.qml, panels/, components/, Theme.qml
tests/             core validation (incl. test_model_benchmarks.py --
                   new physics MUST land here first)
gui/tests/         GUI-level tests (headless QML pattern)
ARCHITECTURE.md sec 4b   governing roadmap M13-M30
pytcad/M14-SURFACE-MOBILITY-PLAN.md   the one genuinely OPEN item (G-A)
pytcad/M16-BTBT-PLAN.md / M17-TRANSIENT-PLAN.md / M18-AC-PLAN.md /
  M19-SELFHEATING-PLAN.md / M20-DENSITY-GRADIENT-PLAN.md /
  M21-MESHING-PLAN.md / M21-PHASE3-MESHING-PLAN.md /
  M22-LINSOLVE-PLAN.md   milestone plans (numerical core); all LANDED
  for their stated scope as of 2026-08-31 -- read each one's own
  "honest limits" section for what's deliberately still deferred
pytcad/GUI-IMPROVEMENT-PLAN.md   GUI feature roadmap (Phases 1-4 shipped)
pytcad/3D-VISUALIZATION-PLAN.md   PyVista/VTK 3D viewer roadmap
  (Phases 1-5 SHIPPED: 3D example, isosurface viewer, volumetric
  rendering, animated bias-sweep playback, exploded structural view)
history.md   session-by-session state + handoff notes
```

## Commands (run from `pytcad/`)

```bash
# fast dev loop: parallel, skips the multi-minute "slow" gates and the
# "timing" budgets (frame times, soak memory slope, solve-time bound) that
# six busy workers skew; measured 7-13 min on 2026-09-26, load-dependent
python3 -m pytest tests/ gui/tests/ -n 6 -m "not slow and not timing" -q
# timing budgets: SERIAL, right after (no -n; ~1 min). Part of every full run
python3 -m pytest tests/ gui/tests/ -m timing -q
# slow gate battery: must run before any milestone completion claim
python3 -m pytest tests/ gui/tests/ -n 6 -m "slow" -q
python3 -m pytest tests/ gui/tests/ -q     # full suite, serial (~4 min)
python3 -m pytest tests/test_model_benchmarks.py -q   # physics gates
QT_QPA_PLATFORM=offscreen python3 -m gui.app          # live app
python3 examples/01_pn_diode.py            # examples 01..05
```

## Gotcha: line endings are MIXED, and no .gitattributes guards them

`pytcad/pytcad/` mixes both; no `.gitattributes`.

**Don't trust checked-in list of WHICH files — measure.** Paragraph once named `device.py` and `device2d.py` as CRLF; re-measured 2026-09-10, both LF, counts drifted "18 CRLF / 28 LF" → **13 CRLF / 36 LF**. Set moves whenever file rewritten; only durable form is the check:

```bash
cd pytcad/pytcad && for f in *.py; do
  grep -qU $'\r' "$f" && echo "CRLF: $f"; done
```

As of 2026-09-10 the 13: `adapt.py`, `constants.py`, `continuation.py`, `fermi.py`, `__init__.py`, `ionization.py`, `linsolve.py`, `materials.py`, `mesh.py`, `mesh2d.py`, `mesh3d.py`, `mosfet.py`, `process.py` — plus `CLAUDE.md` itself. `linsolve.py` on list = exactly file M31 P5-1 keeps editing.

Script doing the obvious thing —

```python
s = open(path).read();  ...;  open(path, "w").write(s)
```

— silently rewrites WHOLE FILE: Python universal-newline read turns `\r\n` into `\n`, write doesn't restore. Edit correct, diff 3,800 lines, real change invisible. Happened once already.

Editing CRLF file programmatically: use binary mode (`open(p, "rb")` / `"wb"`) or restore endings after; check `git diff --stat` before believing change small. Don't "fix" by adding repo-wide `.gitattributes` mid-branch: renormalizing touches every CRLF file, buries in-flight work.

## The C++ engine (M31) -- REQUIRED as of M43 phase 4 (2026-09-16)

`pytcad/core/` = C++ numerical engine exposed as single extension module `pytcad._core`. Through M43 phase 3 **always optional** (`pytcad/_accel.py` soft-imported, fell back to pure-Python reference per kernel). **At user's explicit request, fallback removed in phase 4**: pure-Python bodies (`_<name>_py`) for mesh-geometry kernels (P2), process/adaptivity kernels (P4), M34-S4 nonlocal path tracer, and M43 thermal-grid assembly no longer exist. `_accel.require_accel()` raises clear ImportError naming build command below if `_core` not importable when one called. `import pytcad` ITSELF still never fails without extension (gate G-F survives in narrower import-only form — see `pytcad/_accel.py` docstring) — but `process.diffuse_numeric`, `ted.diffuse_with_defects`, `adapt_unstructured.indicator_*_tri`/`debye_ratio_tri`, `unstructured_assembly{,3d}.build_*`, `nonlocal_path.build_structured`, `thermal_grid._residual_jacobian_grid` now require it. ONE deliberate exception: `linsolve.py`'s petsc4py backend (`_solve_petsc_py`) = real independent second implementation (PETSc's official Python bindings), not pure-Python stand-in; untouched — `method="petsc"` still works via petsc4py when `_core` built without PETSc or absent entirely.

Practical consequence: **checkout without compiled `_core` can `import pytcad`, but cannot run process simulation, AMR refinement, nonlocal-BTBT tracer, or M43 self-heating.** `tests/test_accel_parity.py`, `test_accel_boundary.py`, `test_m34_s4_trace_parity.py`, M43 thermal test files all `skipif(not _accel.HAVE_ACCEL)`, rewritten to check correctness/reproducibility on sole compiled path (no second implementation to diff) instead of cross-path parity.

**No C++ compiler installed on this machine when M43 phase 3 started.** See "No C++ compiler was installed..." note below for full incident (compiler installed into Python env broke PySide6 once) and why compiler lives in SEPARATE conda env (`tcad-cpp`) from Python env (`tcad-dev`).

```bash
# in-place dev build -- nothing installed; the .so lands in pytcad/ so
# the existing sys.path convention finds it and no test file changes.
# CMAKE_CXX_COMPILER/CMAKE_AR/CMAKE_RANLIB point at the SEPARATE
# compiler env if the Python env itself has no compiler -- see
# core/CMakeLists.txt's header comment.
cmake -S core -B build/dev -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo \
      -DTCAD_INPLACE_OUTPUT=ON \
      -DPython_EXECUTABLE="$(conda run -n TCAD which python)"
cmake --build build/dev
conda run -n TCAD python -c "from pytcad import _accel; print(_accel.status())"

# wheel / editable install
conda run -n TCAD python -m build --wheel
conda run -n TCAD pip install --no-build-isolation -ve .
```

**PETSc optional inside extension** (M31 P3b), same principle one level down: CMake option `TCAD_WITH_PETSC` is `AUTO`, so build without PETSc still compiles and `linsolve.solve_linear(method="petsc")` falls back to petsc4py — or, if missing too, raises `LinearSolveError` naming both routes. In-place build above picks PETSc up automatically inside `TCAD` conda env; otherwise `PKG_CONFIG_PATH` must point at `<prefix>/lib/pkgconfig`. Force with `-DTCAD_WITH_PETSC=ON` (configure fails if absent) or `=OFF` (reproduce pip-only CI job locally). `_accel.status()` says which you got; `info["backend"]` from `method="petsc"` solve says which actually ran.

**What's compiled so far.** Mesh geometry (`unstructured_assembly{,3d}` — M31 P2), PETSc KSP/PC config (`linsolve`, P3b), process/adaptivity kernels (P4): three per-triangle AMR indicators in `adapt_unstructured.py` and 1D explicit diffusion time loops in `process.diffuse_numeric` / `ted.diffuse_with_defects`; M34-S4 nonlocal-BTBT path tracer (`nonlocal_path._trace_paths_py`'s C++ mirror); and, as of M43 phase 3 (2026-09-16), structured-grid (D=2-or-3) self-heating assembly, `thermal_grid._residual_jacobian_grid_py` -> `core/src/thermal/grid.cpp` (`_core.thermal_grid_residual_jacobian`). Since then (verified in tree 2026-09-24, not memory): M42-S3 density-gradient Lambda-row assembly (`core/src/dg/grid.cpp`); M47 3D assembly — `unstructured_dd3d.py`'s equilibrium and coupled residual/Jacobian (`core/src/unstructured3d/`) and `Device3D._residual_jacobian`'s four base COO blocks (`core/src/device3d/`); exact MUMPS sparse LU inside PETSc path (`linsolve.solve_linear(method="mumps")`, which `NewtonOptions(linsolve="auto")` picks for 3D structured coupled bias solves — see `linsolve._AUTO_EVIDENCE`). Every binding taking node indices or per-edge arrays range/length-checks up front, raises `IndexError`/`ValueError` (`core/include/tcad/base/checks.hpp`, gated by `tests/test_core_input_validation.py`) — before 2026-09-23 malformed array SEGV'd interpreter. Everything else still pure Python, none on deprecation path.

**No C++ compiler on this machine until M43 phase 3; compiler toolchain lives in SEPARATE conda env from Python's — `tcad-cpp`, never `tcad-dev`.** `cmake`/`ninja` already in `tcad-dev`, but no `cl.exe`/`g++`/`clang++` anywhere — confirmed by compiling trivial `<optional>` TU, not assumed. FIRST fix attempt — `conda install -n tcad-dev -c conda-forge gxx` — silently broke PySide6 (`ImportError: DLL load failed while importing QtCore`): install channel-switched `libhwloc` conda-forge → `defaults` (same version, different binary/ABI) and downgraded `libxml2`, both transitive resolution side effects of adding compiler to env with large unrelated dep graph. Caught only by running GUI test suite after, not at `_core` build/import. Fixed: reverted `tcad-dev` (`conda install -n tcad-dev -c conda-forge --revision N`), created separate env `tcad-cpp` (`conda create -n tcad-cpp -c
conda-forge gxx cmake ninja binutils`), used ONLY to supply `CMAKE_CXX_COMPILER`/`CMAKE_AR`/`CMAKE_RANLIB` paths — `tcad-dev` gained zero new/changed packages second time. Compiler and interpreter in different envs, so `_core.pyd` must not depend on `tcad-cpp`'s runtime DLLs (`libstdc++-6.dll`/`libgcc_s_seh-1.dll`/`libwinpthread-1.dll`/`libgomp-1.dll`) at import — `core/CMakeLists.txt` statically links all four into `_core` (`-static-libgcc
-static-libstdc++` plus `-Wl,-Bstatic,--whole-archive
-lwinpthread -lgomp -Wl,--no-whole-archive,-Bdynamic` group; `objdump
-p` on built `.pyd` confirms zero non-system DLL deps beyond `python3XX.dll` — checked directly). Durable SAFE env change: `tcad-cpp` exists alongside `tcad-dev`, never touches it; `pytcad/_core*.pyd` persists in repo (gitignored), imports with no runtime coupling to `tcad-cpp`. Fresh checkout reports `_accel.status()` "not built" → rebuild via `tcad-cpp` compiler as above — never install compiler into `tcad-dev` again.

**Where accelerated function's transcendentals live matters.** P4 kernels take `np.log(n)`, not `n`, and nodal Debye lengths, not doping — numpy's `log`/`exp` and C++'s are independent implementations, gate is `np.array_equal`, so such things computed ONCE Python-side, only result crosses. New kernel: follow that; don't assume two libm builds agree without measuring (as `core/src/process/diffuse.cpp` documents for the one exception).

## Performance claims (M32)

Benchmark suite exists. Use it.

```bash
cd pytcad
OPENBLAS_NUM_THREADS=1 conda run -n TCAD python -m benchmarks            # quick
OPENBLAS_NUM_THREADS=1 conda run -n TCAD python -m benchmarks --size full
```

`Architecture_Master_Plan.md` section 36 forbids claiming solver "HPC-ready" (or fast, or scalable) without correctness + scaling + memory + reproducibility in a table. `benchmarks/` makes that table; `benchmarks/BASELINE.md` = checked-in reference to compare against. **Performance number not from benchmark run doesn't belong in plan doc or commit message** — project already has drawer of unre-runnable one-off measurements; M32 exists to end that.

Read `benchmarks/README.md` before quoting a column: `assembly` = residual + Jacobian together, `asm calls` NOT Newton iteration count, `py peak MB` is floor not measurement. Each has reason, each gated so can't be quietly dropped.

Two env vars govern boundary:

| var | effect |
|---|---|
| `PYTCAD_ACCEL` | As of M43 phase 4 (2026-09-16), read ONLY by `linsolve.py`'s PETSc backend selection (`0` forces petsc4py, `1`/unset uses compiled PETSc path when `_core` built with it). No effect on other kernels — no pure-Python fallback left for `_accel.require_accel()`-gated functions, so no-op there. |
| `PYTCAD_NUM_THREADS` | kernel threads. **Defaults to 1** — threads oversubscribe `workbench/batch.py`'s pool workers AND make scatter-add reductions non-reproducible, breaking `np.array_equal` goldens |

**"Run both ways" / "one CI job with no extension" pattern RETIRED as of M43 phase 4.** `_core` now required for most numerical core (see "The C++ engine (M31)") — no-extension run can't pass suite, so `.github/workflows/ci.yml`'s "one job with no extension at all" leg (if still configured) needs updating to always build `_core` first; flagged but NOT changed when fallback removed — check actual CI config before assuming old or new description accurate.

One `pip install -r requirements.txt` (repo root: `pytcad/requirements.txt`) covers library, GUI, tests, all optional deps (gmsh, devsim, mpmath) — verified Linux and Windows. Run once. Cap workers `-n 6` on this machine (not `-n auto`) — more oversubscribe memory/cores. Set `OPENBLAS_NUM_THREADS=1` (or export) when parallel: numpy/scipy BLAS otherwise spawns own thread pool PER WORKER, oversubscribing CPU across all `-n` workers, slower not faster. Running two heavy M15 breakdown-ramp "slow" tests concurrently with everything also slows whole run (CPU contention) — run `not slow` and `slow` as two separate invocations.

Suite invariant: **N passed, zero warnings**. `pytest.ini` exempts one intentional warning; anything new fixed at source or asserted with `pytest.warns` in intending test.

## Hard rules

- Numerical core (`pytcad/*.py`): frozen EXCEPT where milestone plan explicitly amends (M11-S3 for Device1D heterojunctions; M12-S2 added TAT). Further core change needs same explicit sign-off + FD-Jacobian-first + bit-identical-off-path gates.
- **Golden baseline before core edit — achievable version.** Older wording said "goldens committed before the edit". IMPOSSIBLE, always was: `.gitignore` excludes `*.npz`, so `tests/goldens/**` never tracked, and shouldn't be — golden pins ONE machine's summation order (see bit-identity gotcha below), so committed one = machine-specific artifact posing as shared reference. Unperformable rule worse than none, so actually required: **reconstruct-and-compare**, protocol M31 P4b used:
    1. BEFORE the edit, record the md5sum of every golden the change
       could touch, in the plan file (not in git -- in the plan).
    2. Make the edit and regenerate.
    3. Prove the old baseline is recoverable AND that this change is
       its sole cause: shim the pre-edit behaviour back, regenerate
       again, and check the md5sums come back byte-identical.
    4. Record which goldens moved, which did not, and WHY each --
       a golden that moves for an unexplained reason is a defect, not
       a re-baseline.
- Layering: QML -> controllers -> services -> QProcess subprocess -> npz -> ResultStore -> canvas. Controllers/canvas never import pytcad.
- `DeviceSpec` stays wire format. Subprocess isolation per run.
- New physics model = published-value benchmark in `tests/test_model_benchmarks.py` FIRST + catalog metadata.
- Optional deps stay optional (devsim auto-detected). Deliberate EXCEPTION: pyvista/pyvistaqt (in requirements.txt) HARD dependency of gui/ — 3D viewer (gui/services/viewer3d.py, 3D-VISUALIZATION-PLAN.md) imports unconditionally at module level, discussed and approved with user, not oversight. Don't silently make optional/guarded to match devsim pattern without asking.
- Every slice: suite green with pre-existing tests unchanged, adversarial probe pass BEFORE commit, honesty over polish (report blockers, don't hide failures, no fudge factors).
- Don't commit automatically unless told; user pushes.
- Never claim change works, bug fixed, or suite green without ACTUALLY RUNNING command and reading real output — not "should work," not inferring from diff. Run still in progress → say so; don't guess.
- Never write doc/history entry naming file, function, or class not confirmed to exist (grep or Read first). Prior session's history.md entry claimed new files (`provenance_model.py`, `continuation_data.py`) never created — real logic landed in `lab_controller.py` and `solver_backend.py`. Don't repeat; don't trust that entry's file list.

## Workflow

Plan -> user approves -> TDD (red first) -> implement -> hard debug (fuzz/probe adversarially, run live app/examples) -> commit. Working tree may be left dirty ONLY with openly-failing tests + precise handoff note in `history.md` (see M12-S2 precedent).

## Gotchas learned the hard way (each cost a debugging session)

**devsim**
- `solve()` PROCESS-GLOBAL (no device= arg): delete device+mesh in finally block or stale state fails later solves.
- Mesher adds nodes if ps < segment length -> use FULL spacing.
- Engines tabulate ni differently -> cross-engine psi agrees only ~25 mV, I-V to constant factor ~2; anchor each engine to analytic values, not pointwise comparison.
- `solve(info=True)` returns {'converged', 'iterations'} — use it.

**QML / PySide6**
- Plain Python attributes INVISIBLE to QML property lookup: every controller handed to QML needs @Property(QObject). (Bit twice: treeModel/consoleModel, then cv controller.)
- Context-property controllers must be Qt children of parent controller, not bare attributes — else shutdown GC races QML bindings, TypeError spam. Test ownership via shiboken validity after engine teardown, not stderr capture (Qt writes via cached C stream fd redirection misses).
- `.visible` reflects EFFECTIVE visibility through hidden ancestors (StackLayout/tabs): headless tests must activate right tab before asserting child visibility.
- Guard new bindings against null during teardown (`canvas ? ...`).
- Binding built from `&&`/ternary can hand QML raw `null`/`undefined` instead of real `false` (e.g. `a && a.b && a.b.c` → `null` when `a.b` null, not `false`) — assigning to `bool` property (`enabled:`, `visible:`) logs "Unable to assign [undefined] to bool" every time. Wrap whole expression in `!!(...)`.
- `gui/app.py` MUST construct `QApplication` (QtWidgets), not `QGuiApplication` — 3D viewer (`gui/services/viewer3d.py`) opens real `QMainWindow`, and `QWidget` construction hard-ABORTS WHOLE PROCESS if only `QGuiApplication` exists ("QWidget: Cannot create a QWidget without QApplication" — confirmed by reproducing). `QApplication` strict superset of `QGuiApplication` (QML identical under it), so never use narrower class once any QtWidgets code exists. Qt app singleton fixed by whichever subclass constructs FIRST in process, never upgradable — why `gui/tests/conftest.py`'s session-scoped `_qt_application` fixture must also construct `QApplication`, ahead of every test file's `gapp` fixture, not just app bootstrap.
- `pyvistaqt.QtInteractor` (VTK live render window) does OWN windowing-system calls independent of Qt platform plugin — `QT_QPA_PLATFORM=offscreen` doesn't make it headless; building under it raises X11 `BadWindow`, not clean no-op (confirmed). `pyvista.Plotter(off_screen=True)` DOES work offscreen (VTK's separate off-screen path) — asymmetry real, not config mistake. To test code building `Viewer3DWindow`, monkeypatch `viewer3d.QtInteractor` to small fake recording `add_mesh`/`remove_actor` (see `gui/tests/test_viewer3d.py`'s `FakeInteractor`) — still exercises REAL `QMainWindow`/`QComboBox`/`QDoubleSpinBox` widget tree and signal wiring, just not GL surface.
- **On this machine (NVIDIA RTX 5060 Ti, proprietary driver 610.57.04, Wayland + XWayland), genuinely real `Viewer3DWindow` — not `FakeInteractor`-mocked one tests use — SEGFAULTS WHOLE PROCESS**, not only under `QT_QPA_PLATFORM=offscreen` (documented `BadWindow` case) but also against REAL display (`DISPLAY=:0`, no offscreen). Confirmed 2026-09-17: `AppController.loadExample("resistor_3d")` -> `.run()` -> `hasResult=True` with correct mesh stats, zero errors, all clean; crash isolated to `AppController.openViewer3d()`'s `Viewer3DWindow(store)` construction, failing with `X Error ... BadAccess ... GLX ...
  X_GLXMakeCurrent` + segfault (exit 139) — reproduced identically with real NVIDIA GL, with `LIBGL_ALWAYS_SOFTWARE=1`, and with `QT_QUICK_BACKEND=software`, so not simple hardware-vs-software rasterizer switch. `glxinfo` reports direct rendering fine; conflict is VTK's OWN GLX context creation colliding with NVIDIA driver's Wayland+XWayland GLX resource handling once Qt Quick's RHI context holds one. Not investigated further (driver/windowing-stack issue, no PyTCAD source implicated), not fixed. Consequence: on THIS machine, 3D viewer's real VTK render surface never verified end-to-end outside `FakeInteractor` — future session needing real `Viewer3DWindow` screenshot: expect crash, don't retry GL env vars already ruled out.

**Python/testing**
- pytest warning filters are REGEX: `cm^-3` never matches (caret = anchor); escape as `cm\^-3`.
- str.replace() patches SILENTLY no-op on stale strings — always assert applied ("assert old in s").
- Bash tool cwd RESETS to /home/nihal between calls — always `cd` or pass workdir; #1 cause of lost edits.
- `pgrep`/`pkill`/`ps | grep` WAIT CONDITION MATCHES OWN COMMAND LINE, never terminates. `until ! pgrep -f "python -m pytest";
  do sleep 10; done` finds its own shell (pattern substring of shell argv), waits forever; `ps -eo args | grep -c "conda run"` reports 1 when answer is 0. Confirmed 2026-09-12: four such loops blocked 13-38 min on already-finished runs. Fix: use Bash tool's `run_in_background` on real command (harness tracks THAT process, notifies on exit) instead of polling; if must poll, use bracket (`[p]ytest`), match `$!`/a pidfile, or wait on artifact job writes. Two related traps same session: loop waiting on log of killed run waits forever (nothing writes it); loop waiting for task-output file's last line to match `passed|failed` never fires because harness appends own `[exited with code N]` line after pytest summary.
- Writing doc in two parts to SAME path truncates (second write replaces) — write once, or append via bash.
- Keep engine/QObject refs alive in tests: dropping engine ref lets GC destroy whole QML tree mid-test.
- Heredocs double backslashes: check line continuations after writing test files through bash.
- np.polynomial.legendre.leggauss is module-level (not Legendre.leggauss) in numpy 2.5.
- GUI controller APIs: familySweep.configureFamily's FIRST arg = STEPPED CONTACT NAME (string); ViewportPanel.setViewMode takes INTERNAL mode names ("series"/"bands"), not display names ("Curves"/"Bands") — wrong names silently no-op or render wrong view.
- np.trapezoid is modern name; scipy.sparse diags order (lo,main,up).
- scipy spsolve NOT format-invariant: SuperLU solves CSR natively via format flag instead of converting to CSC, so spsolve(A_csr, b) vs spsolve(A_csr.tocsc(), b) differ ~1e-16 relative, not bit-identical — linear-solve wrapper claiming "exactly spsolve, bit-identical" must never reformat A for direct method, or silently breaks bit-identity golden gates (see pytcad/linsolve.py's solve_linear, M22 G2).
- Size/dimensionality GATING computation (e.g. "only for 3D jobs above N nodes") needs OWN guard checked first — writing gate's math as bare statement before protecting `if` runs it unconditionally. Confirmed: x-axis doping-variation check for gui/services/solver_runner.py's MPI-Schwarz gate called `doping.max(axis=2)` before checking dimensionality == 3, broke EVERY 1D/2D job in gui/tests (AxisError — 1D array has no axis 2) — caught only because FULL suite (590 tests) run before calling done, not just 3D-specific subset. Run whole suite after touching shared dispatch function.
- Clamping out-of-range value to survive TRANSIENT Newton overshoot (e.g. eta > FERMI_ETA_MAX during iteration) must not clamp FINAL converged answer — silently defeats loud-refusal check clamp protects, for exactly the case (genuinely invalid converged state) it exists to catch. Clamp only trial evaluation in loop; check raw unclamped value again after convergence.
- sha256/np.array_equal "bit-identity" golden values (tests/goldens/m13/*.npz, test_m13_solver.py's TAT_EQ_DIGEST/TAT_FW_DIGEST/HETERO_FW_DIGEST) pin ONE machine's numpy/scipy/BLAS build's exact FP summation order, not portable solver behavior — confirmed merging parallel branch 2026-09-04: goldens/digests re-captured in different sandbox failed bit-identity here even with byte-identical code and byte-identical frozen_meshes.npz (pure-Python/numpy mesh-coordinate array IS portable; Newton-solve OUTPUT not). Fix: regenerate ON TARGET MACHINE (PYTCAD_REGEN_M13_GOLDENS=1 for .npz goldens; recompute via test module's _digest() for hardcoded hex strings), verify physical sanity (finite, correct sign/magnitude/positivity) before trusting, never copy golden bytes or digest strings between machines/sandboxes.
- Safety gate built from ONE physical hazard doesn't automatically cover DIFFERENT hazard correlated with same axis/parameter. Confirmed 2026-09-04: gui/services/solver_runner.py's MPI-Schwarz split-axis picker checked only doping-gradient safety, correctly judged finfet_3d's z-axis doping-uniform — but GateBC's Robin/oxide-coupling term runs along own `normal_axis` (z, for finfet_3d side gates) regardless of doping, geometric/electrostatic confinement doping check can't see. Result: silently WRONG (1.4e-3 relative field error vs ~1e-17 for gate-free validated devices) AND SLOWER (4.1x) production result for any gated 3D device above size gate, caught only by exercising "should be safe by existing check" case end to end. Fix: SECOND independent exclusion (any axis matching registered gate's normal_axis), not tweak to first. Adding safety/gating heuristic: ask what OTHER mechanisms could break same invariant before trusting one check.

**Physics/model conventions (empirically established)**
- Device3D's ENTIRE dimensionless scaling (Ns, LD, J0, even mesh coords — xs = mesh.x / LD) derived from max(|doping|) OF WHATEVER ARRAY DEVICE BUILT WITH, not device-wide constant stored elsewhere. Two Device3D instances covering different SLICES of same physical device (MPI Schwarz domain decomposition, gui/services/mpi_schwarz_runner.py) silently disagree on units unless BOTH pinned to same reference via new `Ns_override` constructor param, computed once from FULL device's doping array — found by reading __init__ before correctness testing, not by failure. Future per-subdomain/per-region Device3D construction needs same pinning.
- MOSCapacitor rho balances Qg SAME-sign; inversion at POSITIVE phi_s for p-substrate; abrupt-junction discretization leaves rho=+-1 exactly at two doping-step nodes (global charge balance is correct neutrality criterion, not node-wise).
- Heterojunction SG deltas: electron dpsi + dln(nie), hole dpsi - dln(nie) — OPPOSITE signs; shared delta passes FD-Jacobian but breaks hole detailed balance. Only carrier-specific equilibrium detailed-balance check catches it.
- TAT WKB factors SI-calibrated (F in V/m): mixing V/cm underflows every probability, silently reduces TAT to SRH. Bulk-Si midgap TAT underflows to exactly 0 at any realizable field — gate factor law over synthetic fields, assert device-level enh==1.0 as honest physics.
- devsim ni tables differ from pytcad's -> cross-backend I-V agrees only to constant ~2x factor.
- Implant windows beyond substrate length must be rejected by validate_flow (keep guard).
- Checkpoint npz uses FLAT keys (species_P), not nested dicts.
- 1D sweep channel name is "device", not contact name.
- Fermi integral: Boltzmann-limit deviation is exp(eta)/2^{3/2} (exact Taylor series) — set limit gates from published math, not round numbers. mpmath mp.quad on [0, inf) under-resolves t~eta knee (5e-5 off at eta=40): subdivide [1, eta+20, inf].

## Milestone state & plans

Governing roadmap: `ARCHITECTURE.md` sections 4b and 4c (three parity tiers, M13-M30, gate-blocking rule 4b.4). Completed: M1-M10 (v0.5.0 tagged), M11-S1..S5 (heterostructure materials/wire/1D+2D core, HBT/HEMT templates), M12-S1+S2 (FN/WKB + Hurkx TAT, all gates green), M13 (Fermi-Dirac + incomplete ionization, G1-G8 all green — unblocked M15+ per parity-plan rule 4b), M15 impact ionization (coupled Jacobian + continuation driver, all gates green — see pytcad/M15-IONIZATION-PLAN.md and ARCHITECTURE.md section 5).
MILESTONE-BY-MILESTONE STATE (only M14's G-A below genuinely OPEN; M16-M22 landed for stated scope — read each entry for actual scope and what's honestly deferred):
  M14 surface mobility -- MOSTLY COMPLETE: mobility_cvt() wired for
    Device2D.models.surface_mobility (G-D/G-E green); G-B (D_it) and
    G-C (S_n/S_p surface recombination velocity, a Robin flux-balance
    BC) are green in BOTH Device1D and, as of 2026-08-31, Device2D --
    the 2D fix reuses the already-computed box-integration residual
    instead of deriving per-edge boundary stamps, generalizing to any
    contact shape with no per-edge logic; one honest limitation found
    (Newton convergence for a deep-minority-carrier contact under
    reverse bias can be non-monotonic, traced to an interaction with
    the M11-S5 density-floor safeguard, not fixed). Only G-A (absolute
    curve vs Takagi/Taur) remains xfail'd -- 2026-08-28 research
    confirmed the real Lombardi phonon term is two-part and doping-
    dependent (this code has a one-term stand-in), but the numeric
    constants are blocked on the 1988 primary source, which is
    paywalled with zero open-access copies (verified via Unpaywall);
    re-searched fresh 2026-08-31 (Darwish-model alternative, DEVSIM/
    MINIMOS-NT source, academia.edu mirrors) with no new result. See
    pytcad/M14-SURFACE-MOBILITY-PLAN.md's "G-A LITERATURE SEARCH"
    sections and "G-C, DEVICE2D, TAKE 2".
  M17 transient simulation -- COMPLETE (2026-08-30/31), all 3 phases:
    1D (pytcad/transient.py) and 2D (pytcad/transient2d.py)
    backward-Euler/theta-scheme solvers, driving Device1D/Device2D
    through their own residual/Jacobian externally (continuation.py's
    pattern) -- device.py/device2d.py never touched. Phase 3 wires a
    transient run into the desktop app end-to-end (new Transient tab,
    schema v2->v3 bump, new viewport mode), reusing the existing
    JobRunner subprocess path unchanged. See
    pytcad/M17-TRANSIENT-PLAN.md for the full gate list and the
    honestly-recorded gaps (G2 diode-turn-off charge quantification,
    GateBC waveforms, project persistence of an armed config,
    per-step field snapshots).
  M18 small-signal AC -- Phase 1 LANDED 2026-08-31: pytcad/ac.py, an
    external module (device.py untouched) computing complex admittance
    Y(f)/C(f)/G(f) for Device1D by perturbing the converged DC Jacobian
    with jw*Cmat (Cmat verified bit-identical to transient.py's own
    storage term). A real bug (per-node FD step size breaking an exact
    analytic cancellation, silently doubling the low-frequency
    conductance) was caught by the G-LOWF gate before being reported.
    Library-only: no Device2D, no GUI. See pytcad/M18-AC-PLAN.md.
  M19 self-heating -- Phase 1 LANDED 2026-08-31: pytcad/thermal.py, an
    outer isothermal-DD + Gummel thermal loop (NOT a monolithic
    psi/n/p/T Newton system -- Device1D's whole scaling framework is
    built from a single scalar T, so that would be a much larger
    rewrite than the gates require). A real bug (naive J*E Joule
    heating gives thermodynamically impossible negative heat in a
    diode's diffusion-dominated depletion region) was found and fixed
    using the correct quasi-Fermi-potential-gradient dissipation term
    (Wachutka 1990), cross-checked against energy conservation (I*V) to
    0.04%. Added Semiconductor.kappa_th300/kappa_th(T) to materials.py
    (none existed before, despite the milestone spec's "no new
    material work" note). See pytcad/M19-SELFHEATING-PLAN.md, including
    an honest finding that a real diode's self-heating INCREASES
    current (the opposite of the "roll-off" language in the milestone
    spec, which fits a MOSFET, not a diode).
  M21 meshing -- phase 1 (1D adaptive h-refinement, pytcad/M21-MESHING-
    PLAN.md) and phase 2 (2D/3D separable adaptive refinement) shipped.
    Phase 3 (general unstructured 2D + Delaunay FV assembly,
    pytcad/M21-PHASE3-MESHING-PLAN.md) is now COMPLETE 2026-08-31: 3a
    (gmsh_mesh.py/region_resolver.py/unstructured_assembly.py geometry
    foundation), 3b (unstructured_poisson.py, Poisson-only equilibrium),
    3c (unstructured_dd.py, coupled SG bias solve), and 3d
    (Device2D(unstructured=True) -- a thin wrapper into Device2D's own
    solve_equilibrium/solve_bias/terminal_current API, verified
    bit-identical to calling the standalone functions directly) all
    landed and gated. Homojunction/Boltzmann-only by explicit design
    (unstructured_dd.py's own docstring); Device2D(unstructured=True)
    refuses any Models() flag that physics core doesn't implement.
  M22 linear solver -- phase 1 (Krylov+ILU+block-Jacobi preconditioner)
    shipped; a hard-debug pass found and fixed a real bit-identity bug
    in solve_linear(method="direct") reformatting the matrix before
    calling spsolve (see the scipy spsolve gotcha above); 3D-scaling
    gate green; phase 2 (continuation driver, strength-ladder-aware
    corrector) LANDED 2026-08-28 and is what let M15 R1b close; the
    section-7 Schur-complement preconditioner (solve_linear(precond=
    "schur")) landed 2026-08-29 and was VERIFIED 2026-08-31 (gates were
    written but never run until then; all 5 Schur-specific gates passed
    cleanly on first execution -- additive, default unchanged, not
    wired into NewtonOptions).  Phase 3 (2026-09-02) LANDED as MPI
    Schwarz domain decomposition (gui/services/mpi_schwarz_runner.py),
    not the distributed-matrix design originally scoped -- 4 ranks,
    5.1x on bjt_3d, exact to ~1e-17; a real regression on a device
    whose doping varies along the split axis (pn_junction_3d) was
    found and gated against before shipping. Same session: pyamg AMG
    for the GUI's 3D equilibrium solve (8x-44x) and a CUDA (CuPy/
    cuSOLVER) direct solve for bias/sweep (2.8x) -- both opt-in,
    size-gated, additive.  See pytcad/M22-LINSOLVE-PLAN.md section 9.
    GENERALIZED same day (section 10): the x-only safety check became
    _pick_mpi_split_axis(doping), which checks all three mesh axes and
    picks whichever is safe with the most nodes -- pn_junction_3d
    (refused outright by the x-only check) now qualifies via z, 1.5x
    over its single-process baseline, exact to ~1e-17.
  M16 BTBT -- local Kane/Hurkx generation, live Jacobian coupling,
    landed 2026-08-29, VERIFIED 2026-08-31: the gates had never been
    run; once executed, 2 of 13 failed, but all three root causes were
    bugs in the TEST assertions (inverted sort direction, a sign error
    comparing two negative slopes, a correlation-sign check that could
    never pass for a genuine negative-slope fit) -- not the physics.
    All 13 pass now. See pytcad/M16-BTBT-PLAN.md.
    M16-S2 (2026-09-13): local Kane BTBT ported to structured
    Device2D/Device3D -- pytcad/btbt_grid.py, a dimensional lift of
    the already-gated 1D model (no new constant), following
    pytcad/M16-S2-PLAN.md. G depends on psi alone (no carrier-density
    dependence, unlike M34-S6's impact ionization), so the Jacobian
    has exactly two nonzero columns per (node, incident edge) pair.
    Drives the same stiff-generation ladder/backtrack/floor as impact
    ionization (Device1D already grouped btbt into stiff_gen; Device2D/
    Device3D's solve_bias did not -- fixed here). Gated in
    tests/test_m16_s2_btbt_grid.py (G1-G7: kernel's 1D reduction, FD-
    Jacobian in 2D and 3D, transverse-uniform reduction to Device1D in
    2D/3D, btbt=False bit-identity, reverse-ramp steepness). Closes the
    ARCHITECTURE.md 4d.1 matrix's one remaining local/nonlocal BTBT
    inversion.
  M20 density gradient -- Ancona-Stafford DG quantum correction
    (equilibrium-only, MOSCapacitor dg flag + Device1D Models.dg), plus
    the pytcad/dg.py analysis layer (quantum_potential, Airy reference,
    Schroedinger-Poisson solver). COMPLETE, ALL GATES GREEN 2026-08-31:
    the original lagged-Lambda outer fixed point converged cleanly but
    to the WRONG physics (a gamma-calibration gap); replaced with a
    genuinely coupled Newton solve of (psi, Lambda_n, Lambda_p)
    together, plus a hard-wall interface boundary condition for
    MOSCapacitor (researched against DEVSIM's own density-gradient
    implementation) that fixed a real wrong-sign bug in the near-
    surface quantum potential. gamma stays at its documented default of
    1.0, untouched -- the boundary-condition fix closed the gates, not
    a gamma retune. See pytcad/M20-DENSITY-GRADIENT-PLAN.md section 7.
  M34 nonlocal tunneling & ionization -- LANDED 2026-09-11, all five
    slices (pytcad/M34-PLAN.md "Status" is the record): nonlocal path
    Kane BTBT (Models.btbt_nonlocal) in Device1D and structured
    Device2D/Device3D through one engine, pytcad/nonlocal_path.py
    (exact per-segment WKB quadrature, live band profile, frozen path
    geometry re-located after convergence; 2D/3D field-line paths,
    whose transversely uniform devices reproduce Device1D to
    round-off); nonlocal effective-field impact ionization
    (Models.impact_nonlocal, pytcad/ii_nonlocal.py, 1D only); the
    tracer compiled in core/src/nonlocal/paths.cpp, bit-identical to
    nonlocal_path._trace_paths_py; both flags in the catalog and wire
    format. 2026-09-12: M34-S6a/b put M15's coupled local impact
    ionization into structured Device2D/Device3D (pytcad/ii_grid.py;
    alpha at the field along each carrier's current), and M34-S7 fixed
    the stiff-path Newton convergence test in all three devices: it
    read the line-search-DAMPED update and stopped short (M15's diode
    at -30V returned 0.698 of the discrete solution's current). Stiff
    paths (impact, btbt, btbt_nonlocal) now judge the full Newton
    correction against a 1e-8 density floor, line-search only above a
    1e-3 correction and halve at most 10 times (device.py
    _STIFF_DENSITY_FLOOR, _LS_NEWTON_REGION, _LS_MAX_HALVINGS); plain
    paths bit-identical. M15's G-C gap was this artifact: M_sim/M_int
    = 0.76, gate back on the plan's [0.5, 2.0] band. Same day, S6c:
    the nonlocal effective field ported to the same structured grid
    (pytcad/ii_nonlocal_grid.py; one sparse LU factor-and-solve for the
    exact E_eff and its Jacobian across all axes at once, generalizing
    ii_nonlocal.effective_field's 1D relaxation chain to the grid's
    edge graph -- see M34-S6-PLAN.md section 6). Two real performance
    bugs were found and fixed before this was fast enough to gate: a
    per-grid-line Python loop for the weak-edge direction search
    (vectorized: every line on a structured axis has the same length,
    so it reshapes into one array op) and a per-node Python dict DP for
    the exact Jacobian walk (replaced by recognizing it as solving one
    sparse triangular linear system, done in compiled code). Device2D/
    Device3D's impact_nonlocal refusal is now Device1D's own
    precondition (needs impact=True, lambda>0), not a hard refusal.
  M41 incomplete ionization -> 2D/3D -- LANDED 2026-09-12, the first of
    ARCHITECTURE.md 4d.3's dimensional-lift milestones (see
    pytcad/M41-INCOMPLETE-ION-2D3D-PLAN.md). M13's shallow-dopant
    freeze-out model now enters Poisson's charge term as
    rho = n - p - C_ion in structured Device2D/Device3D exactly as in
    Device1D; the constructor refusals are gone. A port, not new
    physics -- so the gate is the 1D code that already passed
    (4d.4's rule), and no new constant was introduced. The formula was
    NOT copied a third time: Device1D's `_ionized_C` body and the
    ionized half of its neutrality root were factored to module level
    in device.py (ionized_doping, ionized_eta_doping, ionized_dE_kt,
    plus an optional ion= argument to fd_ohmic_values), so all three
    devices evaluate one implementation and Device1D's own arithmetic
    is unchanged (M13's gates and all six m13 golden md5s re-checked
    after the extraction). Two things to know before touching it:
    the equilibrium (carriers slaved to psi) and coupled (n, p
    independent unknowns) Poisson blocks need DIFFERENT chain rules and
    so have SEPARATE FD-Jacobian gates -- the convergence gates do not
    substitute, since Newton tolerates a wrong Jacobian by iterating
    more (mutation-tested: dropping the equilibrium chain moves the
    probe to 0.52 against a 5e-5 threshold, while every convergence
    gate still passes); and band_offset='affinity' + incomplete_ion is
    REFUSED in 2D/3D exactly as in 1D (the eta-space contact solver and
    the affinity shift each carry their own ln(Nc/nie) offset), rather
    than silently composed. The 4d.1 matrix's other remaining
    inversion -- local Kane BTBT in structured 2D/3D -- was planned in
    pytcad/M16-S2-PLAN.md (2026-09-12) and LANDED 2026-09-13; see the
    M16 entry above for what that closed.
GUI end-to-end smoke test (2026-08-28): gui/tests/test_smoke_e2e.py drives real rendered QML tree (create_engine() + findChild + QMetaObject.invokeMethod — never controller call substituting for UI action, except couple spots documented inline where Qt offscreen platform can't incubate ListView/Repeater delegates) across 1D Process-Flow path and 2D Structure/Device-Builder-template path. AT THE TIME (2026-08-28) no GUI entry point to Device3D or DEVSIM backend — BOTH GAPS NOW PARTLY CLOSED, see GUI-IMPROVEMENT-PLAN.md and 3D-VISUALIZATION-PLAN.md bullets below; sentence describes point in time, not current state. Found and fixed: numeric QML fields silently passing NaN to solver (app_controller.py finite-number guard), saved projects silently dropping Physics Lab model toggles (project_store SCHEMA_VERSION 4->5, "models" key; see gui/tests/test_persistence_v5.py).
GUI-IMPROVEMENT-PLAN.md (2026-08-29): Phases 1-4 SHIPPED — C-V mode, family-sweep staleness, equilibrium-only Run, contour overlays, line-cut mode, devsim/pytcad BACKEND SELECTOR (v0.6 Phase 2c, gated on compatible 1D devices — closes half of "no DEVSIM entry point" gap), backend comparison, lab controller/provenance/continuation records, runtime state validator. Medium-effort /code-review pass on Phase 3/4 found and fixed 8 real bugs (QML id/objectName typo causing runtime crash, dead validator logic, non-notifying ListView bindings, consumer with no real data producer, faked placeholder checks, duplicated logic, hardcoded theme colors) — see history.md Addendum 22 for full list. Don't assume Phase 3/4 code correct because it exists; addendum is record of what actually verified, not original (less careful) landing.
3D-VISUALIZATION-PLAN.md (2026-08-29/30): Phases 1-5 SHIPPED — hand-built `resistor_3d` example (first GUI entry point to Device3D, closing other half of gap) and PyVista/VTK viewer window (separate top-level QWidget, NOT embedded in QML) with interactive isosurface controls, volumetric rendering (Phase 3), animated bias-sweep playback with snapshot capture (Phase 4), exploded multi-layer structural view (Phase 5). Landing ALSO fixed real Phase 1 bug: see QApplication/QGuiApplication gotcha above.
Live queue: ARCHITECTURE.md sections 5-7; session detail: `history.md`.


Project has knowledge graph at graphify-out/ with god nodes, community structure, cross-file relationships.

Rules:
- Codebase questions: first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships, `graphify explain "<concept>"` for focused concepts. Return scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep.
- If graphify-out/wiki/index.md exists, use for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain insufficient.
- After modifying code, run `graphify update .` to keep graph current (AST-only, no API cost).

- Codebase questions: use `graphify query`, `graphify path`, `graphify explain` first when graphify-out/graph.json exists.
- Use `ast-grep` for precise structural Python/C++ searches instead of reading whole files or broad grep when AST pattern fits.
- Read only files/regions needed.
- Use `repomix` only for broad architecture/context snapshots, not routine implementation.
- Don't read `repomix-output.xml` wholesale for ordinary coding.
- Prefer concise tool output, avoid unnecessary explanations.