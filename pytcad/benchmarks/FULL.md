# pyTCAD benchmark suite

## Environment

- **python**: 3.11.16
- **numpy**: 2.4.6
- **scipy**: 1.17.1
- **platform**: Linux-7.0.0-34-generic-x86_64-with-glibc2.43
- **processor**: unknown
- **cpu_count**: 10
- **OPENBLAS_NUM_THREADS**: 1
- **OMP_NUM_THREADS**: unset
- **PYTCAD_ACCEL**: unset
- **accel**: pytcad._core: 0.1.0, threads=1, petsc=3.25.4/32-bit-int
- **timestamp**: 2026-09-25 06:46:29

## Dashboard

| case | what it tests | size | DOF | NNZ | assembly | asm calls | linsolve | ls calls | precond | py peak MB | total | spread |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **B1** 1D Poisson | PDE IR, BCs, Jacobian | full | 200,002 | 600,000 | 0u | - | 545.8m | 9 | 0u | 63.6 | 733.6m | 0u |
| **B2** 1D diode | DD, convergence, conservation | full | 60,006 | 380,006 | 161.3m | 11 | 187.2m | 10 | 0u | 41.4 | 392.7m | 0u |
| **B3** 2D MOSFET | device physics, Newton, current continuity | full | 72,912 | 694,301 | 270.9m | 6 | 2.82 | 5 | 0u | 90.7 | 3.13 | 0u |
| **B4** 3D MOSFET | 3D mesh, memory, solver scaling | full | 68,921 | 472,361 | 139.0m | 9 | 1.42 | 9 | 0u | 60.8 | 1.57 | 0u |
| **B5** 3D SiC MOSFET | traps, high field, avalanche, thermal | full | 35,937 | 238,604 | 293.0m | 25 | 799.8m | 25 | 0u | 36.1 | 1.17 | 0u |
| **B6** GaN HEMT (2D AlGaAs/GaAs stand-in) | heterojunctions, interface charge | full | 14,884 | 73,932 | 41.1m | 19 | 386.5m | 19 | 0u | 9.6 | 433.9m | 0u |
| **B7** Large synthetic 3D | DOF scaling, AMG, MPI, GPU | full | 91,125 | 625,725 | 160.0m | 8 | 48.70 | 9 | 1.54 | 96.1 | 48.89 | 0u |
| **B8** 2D unstructured DD | gmsh triangles, box integration, coupled Newton | full | 34,023 | 436,789 | 188.5m | 12 | 3.11 | 11 | 0u | 72.8 | 3.41 | 0u |
| **B9** 3D unstructured DD | gmsh tets, dual volumes, coupled Newton | full | 7,464 | 177,012 | 109.9m | 17 | 660.9m | 16 | 0u | 13.5 | 847.0m | 0u |
| **B10** 2D nonlocal BTBT solve | field-line path tracing + nonlocal Newton block (M34) | full | 29,256 | 776,043 | 3.21 | 15 | 4.67 | 14 | 0u | 277.1 | 8.36 | 0u |

Times in seconds unless suffixed `m` (ms) or `u` (us). `spread` is max-min across repeats; a large spread means the row's timings are noise-dominated and should not be quoted.

## Notes

- **B1**: tracemalloc was active: total_s is inflated and is not comparable with an untraced run
- **B1**: assembly not instrumented (no device handle, or a path that does not use _residual_jacobian)
- **B2**: tracemalloc was active: total_s is inflated and is not comparable with an untraced run
- **B3**: tracemalloc was active: total_s is inflated and is not comparable with an untraced run
- **B4**: tracemalloc was active: total_s is inflated and is not comparable with an untraced run
- **B5**: equilibrium only; the avalanche/thermal columns of section 34 are not exercised by this run
- **B5**: tracemalloc was active: total_s is inflated and is not comparable with an untraced run
- **B6**: 2D AlGaAs/GaAs, not 3D GaN -- see the case docstring
- **B6**: tracemalloc was active: total_s is inflated and is not comparable with an untraced run
- **B7**: iterative (bicgstab) by design; AMG/MPI/GPU columns need pyamg/mpi4py/CuPy and are reported separately
- **B7**: tracemalloc was active: total_s is inflated and is not comparable with an untraced run
- **B8**: the M31 P5 assembler's own case; sized by geometry, not by the mesh size field -- see the case docstring. One assembly call is the post-convergence current extraction, not a Newton iteration
- **B8**: tracemalloc was active: total_s is inflated and is not comparable with an untraced run
- **B9**: the case the DMPlex/distributed-Mat argument is about; deliberately small even at full size -- see the case docstring. One assembly call is the post-convergence current extraction, not a Newton iteration
- **B9**: tracemalloc was active: total_s is inflated and is not comparable with an untraced run
- **B10**: an M34 addition, not a section-34 case; the path tracer is compiled (M34-S4) -- compare PYTCAD_ACCEL=0/1
- **B10**: tracemalloc was active: total_s is inflated and is not comparable with an untraced run

## What these numbers are not

- `assembly` is residual AND Jacobian together: the core computes both in one pass and returns both, so no honest split is available from outside it.
- `asm calls` is assembly calls, NOT Newton iterations. They are equal only when no backtracking or damping retry occurred; no core solve method exposes an iteration count.
- `py peak MB` is `tracemalloc`, so it sees Python-level allocation only. SuperLU's LU factors, BLAS scratch and PETSc's arena are invisible to it -- treat it as a floor on real usage, not a measurement of it.
- Nothing here is a physics gate. A case asserts only that its solve converged; correctness is `tests/`'s job.

