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
- **timestamp**: 2026-09-25 06:46:17

## Dashboard

| case | what it tests | size | DOF | NNZ | assembly | asm calls | linsolve | ls calls | precond | py peak MB | total | spread |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **B1** 1D Poisson | PDE IR, BCs, Jacobian | quick | 2,002 | 6,000 | 0u | - | 3.6m | 9 | 0u | 0.7 | 6.8m | 157u |
| **B2** 1D diode | DD, convergence, conservation | quick | 1,206 | 7,606 | 4.4m | 11 | 3.4m | 10 | 0u | 0.9 | 10.6m | 3u |
| **B3** 2D MOSFET | device physics, Newton, current continuity | quick | 11,640 | 108,125 | 36.6m | 6 | 162.5m | 5 | 0u | 14.3 | 205.4m | 343u |
| **B4** 3D MOSFET | 3D mesh, memory, solver scaling | quick | 4,913 | 32,657 | 5.3m | 7 | 7.6m | 7 | 0u | 4.2 | 13.8m | 2.6m |
| **B5** 3D SiC MOSFET | traps, high field, avalanche, thermal | quick | 2,197 | 13,396 | 14.4m | 23 | 186.3m | 23 | 0u | 2.1 | 208.8m | 173u |
| **B6** GaN HEMT (2D AlGaAs/GaAs stand-in) | heterojunctions, interface charge | quick | 1,764 | 8,652 | 5.1m | 19 | 35.2m | 19 | 0u | 1.1 | 41.5m | 604u |
| **B7** Large synthetic 3D | DOF scaling, AMG, MPI, GPU | quick | 9,261 | 62,181 | 11.2m | 7 | 209.1m | 7 | 137.3m | 9.2 | 221.8m | 2.8m |
| **B8** 2D unstructured DD | gmsh triangles, box integration, coupled Newton | quick | 3,003 | 37,369 | 15.0m | 12 | 101.4m | 11 | 0u | 6.2 | 127.7m | 833u |
| **B9** 3D unstructured DD | gmsh tets, dual volumes, coupled Newton | quick | 2,889 | 62,907 | 29.4m | 15 | 144.2m | 14 | 0u | 4.8 | 193.7m | 24.2m |
| **B10** 2D nonlocal BTBT solve | field-line path tracing + nonlocal Newton block (M34) | quick | 7,110 | 171,948 | 616.2m | 17 | 1.26 | 16 | 0u | 53.3 | 1.98 | 10.7m |

Times in seconds unless suffixed `m` (ms) or `u` (us). `spread` is max-min across repeats; a large spread means the row's timings are noise-dominated and should not be quoted.

## Notes

- **B1**: assembly not instrumented (no device handle, or a path that does not use _residual_jacobian)
- **B5**: equilibrium only; the avalanche/thermal columns of section 34 are not exercised by this run
- **B6**: 2D AlGaAs/GaAs, not 3D GaN -- see the case docstring
- **B7**: iterative (bicgstab) by design; AMG/MPI/GPU columns need pyamg/mpi4py/CuPy and are reported separately
- **B8**: the M31 P5 assembler's own case; sized by geometry, not by the mesh size field -- see the case docstring. One assembly call is the post-convergence current extraction, not a Newton iteration
- **B9**: the case the DMPlex/distributed-Mat argument is about; deliberately small even at full size -- see the case docstring. One assembly call is the post-convergence current extraction, not a Newton iteration
- **B10**: an M34 addition, not a section-34 case; the path tracer is compiled (M34-S4) -- compare PYTCAD_ACCEL=0/1

## What these numbers are not

- `assembly` is residual AND Jacobian together: the core computes both in one pass and returns both, so no honest split is available from outside it.
- `asm calls` is assembly calls, NOT Newton iterations. They are equal only when no backtracking or damping retry occurred; no core solve method exposes an iteration count.
- `py peak MB` is `tracemalloc`, so it sees Python-level allocation only. SuperLU's LU factors, BLAS scratch and PETSc's arena are invisible to it -- treat it as a floor on real usage, not a measurement of it.
- Nothing here is a physics gate. A case asserts only that its solve converged; correctness is `tests/`'s job.

