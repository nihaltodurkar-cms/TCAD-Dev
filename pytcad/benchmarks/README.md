# pyTCAD benchmark suite (M32)

Permanent performance cases **B1-B7** and the performance dashboard, per
`Architecture_Master_Plan.md` sections 34 and 35.

This exists because of section 36:

> Never use "The solver is HPC-ready" unless the benchmark proves
> correctness + scaling + memory behavior + reproducibility.
> Performance claims belong in benchmark tables, not marketing language.

Before this, nothing in the repo could satisfy that rule. Performance
numbers lived as one-off measurements typed into plan documents -- real
measurements, but not reproducible ones, and impossible to re-run after
a change. This makes them a command.

## Running it

```bash
# from the project root (pytcad/), same as the test suite
conda run -n TCAD python -m benchmarks                  # quick, all cases
conda run -n TCAD python -m benchmarks --size full      # what to quote
conda run -n TCAD python -m benchmarks --case B4 B7     # a subset
conda run -n TCAD python -m benchmarks --repeats 5      # best-of, with spread
conda run -n TCAD python -m benchmarks --out report.md --json report.json
```

Set `OPENBLAS_NUM_THREADS=1` for a comparable number, for the reason
AGENTS.md already documents: otherwise numpy's BLAS spawns its own
thread pool and the result depends on how loaded the machine was.

`--size quick` runs the whole suite in a second or so; `--size full` is
the configuration a published figure should come from. Both are stamped
into the report, so a quick number can never be mistaken for a full one.

Exit code is non-zero if a case FAILED, zero if a case was SKIPPED --
an absent optional dependency is a fact about the machine, not a
regression.

## The cases

| case | what section 34 asks it to test | what it actually is here |
|---|---|---|
| B1 | PDE IR, BCs, Jacobian | 1D Poisson equilibrium |
| B2 | DD, convergence, conservation | 1D diode, forward bias, SRH |
| B3 | device physics, Newton, current continuity | 2D MOSFET at Vg=1.0, Vd=0.1 |
| B4 | 3D mesh, memory, solver scaling | 3D MOSFET-like junction, equilibrium |
| B5 | traps, high field, avalanche, thermal | 4H-SiC vertical power MOSFET, **equilibrium only** |
| B6 | heterojunctions, interface charge, high-field transport | **2D AlGaAs/GaAs**, not 3D GaN |
| B7 | DOF scaling, AMG, MPI, GPU | large synthetic 3D junction, bicgstab |

Two of those rows do less than their section-34 description promises,
and say so rather than being labelled as if they did:

- **B5** runs equilibrium only. The avalanche and thermal coupling
  columns are not exercised.
- **B6** is a 2D AlGaAs/GaAs heterostructure, because no 3D GaN HEMT
  exists anywhere in the tree. It stresses what the case is for -- a
  material discontinuity through the solver -- but it is not a GaN
  device. When a real one exists, repoint the case rather than widening
  the label.

## What the dashboard columns mean

Read this before quoting a number.

| column | what it is |
|---|---|
| `DOF` / `NNZ` | read off the matrix the solver actually assembled, not derived from a node count |
| `assembly` | residual **and** Jacobian together (see below) |
| `asm calls` | assembly calls, **not** Newton iterations (see below) |
| `linsolve` / `ls calls` | time and count for the linear solve |
| `precond` | preconditioner construction time |
| `py peak MB` | `tracemalloc` peak: Python-level allocation only |
| `total` | wall time for the measured region; setup is excluded |
| `spread` | max-min across `--repeats`; large spread = noise-dominated |

Three of those need their limits stated explicitly, because a
right-looking heading over a wrong number is exactly what section 36
exists to prevent:

1. **`assembly` cannot be split into residual and Jacobian.** Section 35
   lists them separately. The core computes both in one pass and returns
   both, so from outside that function there is no way to attribute the
   cost between them, and inventing a split would be a fabricated
   number. When P5's C++ assembler lands it can report them honestly,
   because it will have them as separate entry points.
2. **`asm calls` is not the Newton iteration count.** No core solve
   method exposes one (checked, not assumed). Assembly calls equal
   Newton iterations only when no backtracking or damping retry
   occurred.
3. **`py peak MB` is a floor, not a measurement.** `tracemalloc` sees
   Python-level allocation. SuperLU's LU factors -- usually the dominant
   consumer for a direct solve -- live in SuperLU's own arena and are
   invisible to it, as are BLAS scratch and PETSc's arena.

## Why the instrumentation works the way it does

The timings come from temporarily wrapping the functions the solver
already calls (`linsolve.solve_linear`, each core's imported `spsolve`,
the instance's `_residual_jacobian`), never from timers added inside
`device.py` / `device2d.py` / `device3d.py`.

Those files are the frozen numerical core: editing them requires the
M11-S3 amendment mechanism, which is a disproportionate price for a
stopwatch and would put timing code on the hot path of every solve the
project ever runs. Patching is confined to a context manager and undone
in a `finally`, so an exception mid-benchmark cannot leave a wrapper
attached -- `tests/test_m32_benchmarks.py` gates exactly that, plus the
property that a probed solve is bit-identical to an unprobed one.

## Sizes, measured

`--size quick` is ~1.3 s for the whole suite. `--size full` is about six
minutes, dominated by two cases that are expensive on purpose:

| case | quick | full |
|---|---|---|
| B4 3D MOSFET (direct solve, 68,921 DOF) | 0.34 s | **179 s** |
| B5 3D SiC MOSFET | 0.27 s | 114 s |
| B7 large synthetic 3D (bicgstab, 91,125 DOF) | 0.28 s | 53 s |
| everything else | < 0.4 s each | < 4 s each |

B4 full is not a bug. It is the direct-LU wall this project already
measured by hand and now measures repeatably: 178.82 s of its 178.99 s
total is inside the linear solve, against 148 ms of assembly. B7 solves
32% MORE unknowns in 30% of the time by using an iterative method
instead -- which is the point.

**Measure on an idle machine.** Taking this same table while the test
suite ran alongside it inflated every timed case by 9-12% (B4 199.5 s
instead of 179 s) while DOF and NNZ stayed bit-identical -- the harness
is sensitive enough to see the contention, which also means it is
sensitive enough to be misled by it.

## These are not physics gates

A case asserts only that its solve converged. Correctness is `tests/`'s
job, and that is where a wrong answer must fail. A benchmark that also
tried to be a physics gate would eventually have its tolerance widened
to keep the timings running.
