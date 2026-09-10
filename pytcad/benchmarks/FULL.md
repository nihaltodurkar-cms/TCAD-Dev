# pyTCAD benchmark suite

## Environment

- **python**: 3.11.16
- **numpy**: 2.4.6
- **scipy**: 1.17.1
- **platform**: Linux-7.0.0-31-generic-x86_64-with-glibc2.43
- **processor**: unknown
- **cpu_count**: 10
- **OPENBLAS_NUM_THREADS**: 1
- **OMP_NUM_THREADS**: unset
- **PYTCAD_ACCEL**: unset
- **accel**: pytcad._core: 0.1.0, threads=1, petsc=3.25.4/32-bit-int, PYTCAD_ACCEL=auto
- **timestamp**: 2026-09-10 10:34:46

## Dashboard

| case | what it tests | size | DOF | NNZ | assembly | asm calls | linsolve | ls calls | precond | py peak MB | total | spread |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **B1** 1D Poisson | PDE IR, BCs, Jacobian | full | 200,002 | 600,000 | 0u | - | 551.3m | 9 | 0u | 62.0 | 716.9m | 0u |
| **B2** 1D diode | DD, convergence, conservation | full | 60,006 | 380,006 | 104.0m | 11 | 210.6m | 10 | 0u | 41.3 | 358.2m | 0u |
| **B3** 2D MOSFET | device physics, Newton, current continuity | full | 72,912 | 694,301 | 262.2m | 6 | 3.20 | 5 | 0u | 90.4 | 3.51 | 0u |
| **B4** 3D MOSFET | 3D mesh, memory, solver scaling | full | 68,921 | 472,361 | 145.5m | 9 | 185.01 | 9 | 0u | 60.3 | 185.17 | 0u |
| **B5** 3D SiC MOSFET | traps, high field, avalanche, thermal | full | 35,937 | 238,604 | 400.0m | 25 | 126.29 | 25 | 0u | 35.8 | 126.78 | 0u |
| **B6** GaN HEMT (2D AlGaAs/GaAs stand-in) | heterojunctions, interface charge | full | 14,884 | 73,932 | 39.0m | 19 | 424.3m | 19 | 0u | 9.5 | 468.8m | 0u |
| **B7** Large synthetic 3D | DOF scaling, AMG, MPI, GPU | full | 91,125 | 625,725 | 163.3m | 8 | 51.08 | 9 | 1.57 | 96.0 | 51.26 | 0u |
| **B8** 2D unstructured DD | gmsh triangles, box integration, coupled Newton | full | 34,023 | 436,789 | 183.6m | 12 | 3.27 | 11 | 0u | 106.5 | 5.28 | 0u |
| **B9** 3D unstructured DD | gmsh tets, dual volumes, coupled Newton | full | 7,464 | 177,012 | 112.1m | 18 | 6.67 | 17 | 0u | 43.2 | 7.32 | 0u |

Times in seconds unless suffixed `m` (ms) or `u` (us). `spread` is max-min across repeats; a large spread means the row's timings are noise-dominated and should not be quoted.

## Notes

- **B1**: assembly not instrumented (no device handle, or a path that does not use _residual_jacobian)
- **B5**: equilibrium only; the avalanche/thermal columns of section 34 are not exercised by this run
- **B6**: 2D AlGaAs/GaAs, not 3D GaN -- see the case docstring
- **B7**: iterative (bicgstab) by design; AMG/MPI/GPU columns need pyamg/mpi4py/CuPy and are reported separately
- **B8**: the M31 P5 assembler's own case; sized by geometry, not by the mesh size field -- see the case docstring. One assembly call is the post-convergence current extraction, not a Newton iteration
- **B9**: the case the DMPlex/distributed-Mat argument is about; deliberately small even at full size -- see the case docstring. One assembly call is the post-convergence current extraction, not a Newton iteration

## What these numbers are not

- `assembly` is residual AND Jacobian together: the core computes both in one pass and returns both, so no honest split is available from outside it.
- `asm calls` is assembly calls, NOT Newton iterations. They are equal only when no backtracking or damping retry occurred; no core solve method exposes an iteration count.
- `py peak MB` is `tracemalloc`, so it sees Python-level allocation only. SuperLU's LU factors, BLAS scratch and PETSc's arena are invisible to it -- treat it as a floor on real usage, not a measurement of it.
- Nothing here is a physics gate. A case asserts only that its solve converged; correctness is `tests/`'s job.

