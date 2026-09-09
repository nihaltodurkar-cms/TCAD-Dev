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
- **timestamp**: 2026-09-10 00:15:36

## Dashboard

| case | what it tests | size | DOF | NNZ | assembly | asm calls | linsolve | ls calls | precond | py peak MB | total | spread |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **B1** 1D Poisson | PDE IR, BCs, Jacobian | full | 200,002 | 600,004 | 0u | - | 575.0m | 9 | 0u | 48.9 | 691.8m | 0u |
| **B2** 1D diode | DD, convergence, conservation | full | 60,006 | 380,006 | 158.3m | 11 | 196.4m | 10 | 0u | 36.2 | 366.3m | 0u |
| **B3** 2D MOSFET | device physics, Newton, current continuity | full | 72,912 | 694,301 | 323.0m | 7 | 3.36 | 6 | 0u | 81.6 | 3.70 | 0u |
| **B4** 3D MOSFET | 3D mesh, memory, solver scaling | full | 68,921 | 472,361 | 148.0m | 9 | 178.82 | 9 | 0u | 59.8 | 178.99 | 0u |
| **B5** 3D SiC MOSFET | traps, high field, avalanche, thermal | full | 35,937 | 238,604 | 322.1m | 25 | 110.11 | 25 | 0u | 32.7 | 110.46 | 0u |
| **B6** GaN HEMT (2D AlGaAs/GaAs stand-in) | heterojunctions, interface charge | full | 14,884 | 73,932 | 47.7m | 19 | 433.1m | 19 | 0u | 9.4 | 487.1m | 0u |
| **B7** Large synthetic 3D | DOF scaling, AMG, MPI, GPU | full | 91,125 | 625,725 | 185.8m | 8 | 52.78 | 9 | 1.69 | 96.1 | 52.98 | 0u |

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

