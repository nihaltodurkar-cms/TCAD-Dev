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
- **timestamp**: 2026-09-09 23:53:21

## Dashboard

| case | what it tests | size | DOF | NNZ | assembly | asm calls | linsolve | ls calls | precond | py peak MB | total | spread |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **B1** 1D Poisson | PDE IR, BCs, Jacobian | quick | 2,002 | 6,004 | 0u | - | 6.5m | 9 | 0u | 0.5 | 10.1m | 1.3m |
| **B2** 1D diode | DD, convergence, conservation | quick | 1,206 | 7,606 | 38.0m | 11 | 6.8m | 10 | 0u | 0.7 | 46.6m | 241u |
| **B3** 2D MOSFET | device physics, Newton, current continuity | quick | 11,640 | 108,125 | 76.7m | 7 | 227.8m | 6 | 0u | 12.8 | 307.6m | 3.3m |
| **B4** 3D MOSFET | 3D mesh, memory, solver scaling | quick | 4,913 | 32,657 | 11.8m | 7 | 328.5m | 7 | 0u | 4.1 | 342.0m | 6.6m |
| **B5** 3D SiC MOSFET | traps, high field, avalanche, thermal | quick | 2,197 | 13,396 | 40.4m | 23 | 229.5m | 23 | 0u | 1.9 | 273.5m | 6.9m |
| **B6** GaN HEMT (2D AlGaAs/GaAs stand-in) | heterojunctions, interface charge | quick | 1,764 | 8,652 | 11.8m | 19 | 41.3m | 19 | 0u | 1.1 | 55.3m | 884u |
| **B7** Large synthetic 3D | DOF scaling, AMG, MPI, GPU | quick | 9,261 | 62,181 | 16.1m | 7 | 263.5m | 7 | 173.9m | 9.2 | 281.6m | 9.7m |

Times in seconds unless suffixed `m` (ms) or `u` (us). `spread` is max-min across repeats; a large spread means the row's timings are noise-dominated and should not be quoted.

## Notes

- **B1**: assembly not instrumented (no device handle, or a path that does not use _residual_jacobian)
- **B5**: equilibrium only; the avalanche/thermal columns of section 34 are not exercised by this run
- **B6**: 2D AlGaAs/GaAs, not 3D GaN -- see the case docstring
- **B7**: iterative (bicgstab) by design; AMG/MPI/GPU columns need pyamg/mpi4py/CuPy and are reported separately

## What these numbers are not

- `assembly` is residual AND Jacobian together: the core computes both in one pass and returns both, so no honest split is available from outside it.
- `asm calls` is assembly calls, NOT Newton iterations. They are equal only when no backtracking or damping retry occurred; no core solve method exposes an iteration count.
- `py peak MB` is `tracemalloc`, so it sees Python-level allocation only. SuperLU's LU factors, BLAS scratch and PETSc's arena are invisible to it -- treat it as a floor on real usage, not a measurement of it.
- Nothing here is a physics gate. A case asserts only that its solve converged; correctness is `tests/`'s job.

