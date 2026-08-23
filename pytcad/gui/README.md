# PyTCAD Desktop GUI (v0.1)

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
