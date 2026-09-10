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
- **timestamp**: 2026-09-10 10:34:19

## Dashboard

| case | what it tests | size | DOF | NNZ | assembly | asm calls | linsolve | ls calls | precond | py peak MB | total | spread |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **B1** 1D Poisson | PDE IR, BCs, Jacobian | quick | 2,002 | 6,000 | 0u | - | 4.9m | 9 | 0u | 0.7 | 8.2m | 125u |
| **B2** 1D diode | DD, convergence, conservation | quick | 1,206 | 7,606 | 4.6m | 11 | 5.0m | 10 | 0u | 0.9 | 12.5m | 107u |
| **B3** 2D MOSFET | device physics, Newton, current continuity | quick | 11,640 | 108,125 | 35.6m | 6 | 175.9m | 5 | 0u | 14.2 | 218.4m | 5.2m |
| **B4** 3D MOSFET | 3D mesh, memory, solver scaling | quick | 4,913 | 32,657 | 7.5m | 7 | 313.9m | 7 | 0u | 4.2 | 322.6m | 1.5m |
| **B5** 3D SiC MOSFET | traps, high field, avalanche, thermal | quick | 2,197 | 13,396 | 16.4m | 23 | 198.0m | 23 | 0u | 2.1 | 223.4m | 7.6m |
| **B6** GaN HEMT (2D AlGaAs/GaAs stand-in) | heterojunctions, interface charge | quick | 1,764 | 8,652 | 5.6m | 19 | 37.0m | 19 | 0u | 1.1 | 43.9m | 1.4m |
| **B7** Large synthetic 3D | DOF scaling, AMG, MPI, GPU | quick | 9,261 | 62,181 | 11.7m | 7 | 181.3m | 7 | 135.1m | 9.2 | 194.7m | 12.3m |
| **B8** 2D unstructured DD | gmsh triangles, box integration, coupled Newton | quick | 3,003 | 37,369 | 18.1m | 12 | 105.7m | 11 | 0u | 9.1 | 203.5m | 1.1m |
| **B9** 3D unstructured DD | gmsh tets, dual volumes, coupled Newton | quick | 2,889 | 62,907 | 42.9m | 16 | 670.7m | 15 | 0u | 15.2 | 901.6m | 4.1m |

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

