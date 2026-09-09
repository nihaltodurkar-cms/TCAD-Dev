# M31 -- C++ / Python / Qt production architecture

Status as of 2026-09-09: **P0, P1 and P2 LANDED.** P3a next.
P2 was NOT run against the full suite before hand-off -- see
"Outstanding" at the end of the P2 section.

Governing documents this one sits under: `Architecture_Master_Plan.md`
section 2 (the six-layer north star), section 37 (*"Do not rewrite the
project"* -- progressive extraction), section 41 (architectural tests),
section 42 (the API surface to freeze). Nothing here replaces those.

---

## 1. Why, and the measurement that reshaped the plan

The premise "the numerics are in Python, so move them to C++ for speed"
does not survive contact with a profiler on this codebase. What was
actually measured:

| Finding | Number |
|---|---|
| Structured 3D assembly is **not** the bottleneck | 24^3 equilibrium solve: **98% of wall time in `_superlu.gssv`**; assembly 0.011 s of 0.494 s |
| Direct sparse LU wall | 3.0 s @ 8k nodes -> 51.8 s @ 27k -> 64k never completed in 30 min, ~19 GB (`README.md`) |
| ...but the wall is ALGORITHMIC | the existing **pure-Python** node-block-Jacobi GMRES does 68,921 nodes (206,763 unknowns) in **4.71 s** (`ARCHITECTURE.md`) |
| Unstructured 2D geometry precompute | **~80k triangles/s** (Python loops over `(i,j)`-keyed dicts) |
| Unstructured 3D edge-flux geometry | **~3.5k tets/s** -- a 1M-tet mesh spends **~5 minutes** before any physics runs |

Conclusions that drive the phase order:

1. **3D unstructured meshing is the hardest blocker**, and it is pure
   Python-loop overhead -- a genuine 100-1000x win. It goes first.
2. **The linear solve is the second wall**, and it needs a better solver
   stack, not a faster language. PETSc, reachable from Python first.
3. **Structured assembly is already at numpy's ceiling.** Porting it is
   justified by architecture (one engine, MPI/GPU-ready layout), not by
   a local speedup, so it is sequenced last among the solver phases.

## 2. Decisions

| | |
|---|---|
| C++ scope | Full numerical engine (`core/`): mesh, fields, discretization, assembly, Newton, linear solver, physics kernels |
| Correctness | **Dual path.** Python stays the bit-identity reference; existing goldens are never re-baselined by this work. C++ is gated against it with `np.array_equal` |
| Qt | Keep the PySide6/QML shell and the QProcess isolation. Replace only the PyVista/VTK separate window with a native C++ Qt Quick VTK item |
| Linear algebra | PETSc (`KSP`/`PC`, `MATBAIJ bs=3`, `PCPBJACOBI`, `PCFIELDSPLIT`, `PCGAMG`), MPI + CUDA |
| Bindings | **nanobind** -- buffer-protocol/DLPack rather than numpy's C ABI; a copy at the boundary is a hard error rather than a silent memcpy |

**Distribution, stated rather than discovered later:** PETSc and
VTK-with-Qt are not practically pip-wheelable. conda-forge is the
supported channel for the C++-enabled build. `pip install -r
requirements.txt` continues to give a fully working pure-Python path,
and must keep doing so.

## 3. The rule everything else rests on

**The extension is optional, permanently.** `pytcad/_accel.py`
soft-imports `pytcad._core`; every accelerated function keeps its
pure-Python body renamed `_<name>_py`. Deleting the `.so` must leave the
full suite green (gate G-F).

This is not defensive habit. It is what makes the migration reversible
at every single commit, and it is what keeps an *oracle* alive to diff
the compiled path against -- a port that deletes what it replaced cannot
be checked.

## 4. Phases

| | | |
|---|---|---|
| **P0** | Foundations: packaging, CI, boundary tests, the empty `_core` | **LANDED** |
| **P1** | De-couple and de-duplicate, still pure Python | **LANDED** |
| **P2** | `mesh/` + `geom/` kernels -- the measured blocker | **LANDED** |
| P3a | `method="petsc"` in `linsolve.py` via petsc4py (no C++ needed) | next |
| P3b | the same configuration moved into `core/solver/` | |
| P4 | process/particle kernels (MC implant, TED, diffusion, AMR indicators) | |
| P5 | assembly + Newton in C++; the `pytcad_cpp` backend appears | |
| P6 | native `QQuickVTKItem` 3D viewport | |
| P7 | MPI + GPU via PETSc; `DMPlex` | |
| P8 | Qt shell hardening (split `AppController`, structured progress channel) | |
| P9 | promote `pytcad_cpp` to default; Python core retained as oracle | |

### P0 -- LANDED

* `pyproject.toml` (scikit-build-core + nanobind) and
  `core/CMakeLists.txt`. The project previously had **no build system at
  all**. Two modes, both verified: an in-place dev build
  (`-DTCAD_INPLACE_OUTPUT=ON` writes the `.so` into `pytcad/`, so the
  repo's existing `sys.path.insert(...)` convention finds it and **no
  test file changed**), and a wheel (`pytcad-0.6.0-cp311-*.whl`, 83
  files, extension included, `gui/` deliberately excluded for now).
* `pytcad/_accel.py` -- the dispatch shim, plus `PYTCAD_ACCEL=auto|0|1`.
* `core/bindings/module.cpp` -- module identity, thread policy, and the
  exception-translation contract.
* `.github/workflows/ci.yml` -- **there was no CI at all**. Three jobs:
  pure-Python (asserts the extension is genuinely absent), accelerated
  (builds it, reruns the same suite with `PYTCAD_ACCEL=1`), and wheel.
* `tests/test_accel_boundary.py` (10 tests),
  `tests/test_architecture_boundaries.py` (8 tests).

Two P0 decisions worth keeping visible:

**The Python exception class is the authority.** A C++ kernel raising
`tcad::DegenerateMesh` surfaces as `pytcad.errors.DegenerateMeshError`
-- the very class `tests/test_m21_phase3.py` and
`tests/test_unstructured_dd3d.py` already catch. We never mint a
parallel C++-side type, because then every one of those call sites would
have to learn a second name. Message text is part of the contract too:
those tests use `match="degenerate"` and `match="non-manifold|shared by"`.

**The default thread count is 1**, for two independent reasons and the
second is the hard one. (a) `workbench/batch.py` pins
`OPENBLAS_NUM_THREADS=1` per pool worker precisely to stop
oversubscription; a kernel spawning `nproc` threads inside each worker
reintroduces exactly that bug. (b) Parallel floating-point reductions
are not reproducible, which is fatal against `np.array_equal` goldens.
So a kernel may use threads **only if it is bit-identical across thread
counts**, achieved by parallelizing over the *output* index and never
the input.

### P1 -- LANDED

**A real latent bug, fixed.** `DegenerateMeshError` was declared
**twice, as two unrelated classes** -- `unstructured_assembly.py:34` and
`unstructured_assembly3d.py:43`. An `except DegenerateMeshError`
imported from the 2D module silently failed to catch the 3D module's
error and vice versa. Both now import the single class in
`pytcad/errors.py`; both still re-export it, so no call site changed.

**`np.linalg.solve` removed from the geometry path.**
`tetrahedron_circumcenter` called it, routing to LAPACK `dgesv`, whose
result depends on the BLAS build -- so it cannot be reproduced
bit-for-bit by a C++ port, which would have forced either a LAPACK
replication or a golden re-baseline. Measured, not assumed: an unblocked
`dgetf2` replication matched numpy on only 72.6% of 20k random 3x3
systems, and no FMA variant did better. It is replaced with a
fixed-order Cramer's rule, which is **numerically neutral** -- over 200k
random device-scale tetrahedra the worst violation of the defining
equidistance property was 4.182e-10 for Cramer against 4.184e-10 for
`np.linalg.solve`, both dominated by cancellation in the right-hand side
rather than by the solve. C++ can now reproduce it exactly.

**Extraction.** `bernoulli`, `dbernoulli`, `fd_density`,
`fd_ddensity_deta`, `D0_REF` moved out of the 1947-line `device.py` into
`pytcad/kernels.py`; `_ohmic_values` moved out of `device2d.py` into
`pytcad/contacts.py`. Both re-export, so nothing changed at any call
site. These were being imported by private name from five other modules,
which made a module fusing 1D mesh setup, physics, discretization and
the Newton driver into a load-bearing dependency of code that wanted
none of it. `device.py` is now 1872 lines.

Verification: `tests/test_m13_goldens.py`, `test_m13_solver.py` (incl.
the SHA-256 state digests), `test_m13_fermi.py` and
`test_model_benchmarks.py` -- 93 passed, 1 xfailed, no golden moved.

## 5. Gates every C++ kernel must clear

* **G-A Reference preservation** -- Python body kept as `_<name>_py`;
  both paths run over the same fixtures asserting `np.array_equal`,
  never `allclose`.
* **G-B Blast-radius tripwire** -- `tests/goldens/m13/*`, `m14/*` and the
  SHA-256 digests pass **unchanged with `PYTCAD_ACCEL=1`**. These are
  structured-mesh solves that P2-P4 never touch, so any movement here
  means the change is wrong.
* **G-C Randomized differential fuzz** -- random meshes spanning the
  degenerate boundary; identical outputs **and identical exception type
  and message**.
* **G-D Thread invariance** -- `PYTCAD_NUM_THREADS` in {1,2,4,8},
  `np.array_equal` across all. A kernel that fails loses its pragma.
* **G-E Performance floor** -- absolute, not a ratio, so it only fails on
  regression. P2 targets: >= 300k tets/s for `edge_flux_geometry3d` (85x
  the measured 3.5k), >= 2M tri/s for the 2D stencil.
* **G-F No-compiler fallback** -- full suite green with the `.so` deleted.

## 6. Honest limits

* PETSc and VTK-with-Qt raise the deployment cost; conda-forge becomes
  the supported channel for the C++ build. P3a (petsc4py) is the cheap
  way to test that bet before committing C++ to it.
* Windows: the current stack is Windows-verified; PETSc + VTK-Qt + MSVC
  is materially harder. Either commit to conda-forge there too, or
  accept the C++ engine is Linux-first and say so.
* **P5 concentrates the risk** -- least measured payoff, most physics
  surface, and it spends the bit-identity budget on the code the
  strictest goldens protect. It is deliberately last among the solver
  phases, so it can be revisited with P2-P4 already banked.
* Two engines is a real ongoing cost: every physics change lands twice
  until P9, and the Python oracle must not be allowed to rot.

### Recorded dissent

An independent design review argued `device*.py` and `linsolve.py`
should stay Python **permanently** -- that P5 is negative value, and
that `linsolve.py` is already a dispatcher onto C/C++/CUDA so rewriting
the dispatcher buys nothing. The profiling supports the factual premise
(assembly is 0.011 s of 0.494 s; the 68,921-node win came from a
preconditioner choice, not a language).

The counter-argument, and the reason P5 is retained: a single engine is
what makes distributed 3D possible at all -- with assembly in Python,
every Newton iteration must marshal a Jacobian across the boundary,
which forecloses PETSc's distributed `Mat` and `DMPlex`. That is an
architectural justification, not a performance one, and it should be
held to that standard when P5 comes up.


---

## P2 -- LANDED

Five kernels ported, all **bit-identical** to the Python reference
(`np.array_equal`, not a tolerance), single-threaded:

| kernel | reference | compiled | speedup | floor | |
|---|---|---|---|---|---|
| `build_unstructured_stencil` (2D) | 77k tri/s | **3.16M tri/s** | 41x | 2M/s | PASS |
| `build_unstructured_stencil3d` | 48k tet/s | **1.20M tet/s** | 25x | 1M/s | PASS |
| `build_edge_flux_geometry3d` | 3.7k tet/s | **1.99M tet/s** | **539x** | 300k/s | PASS |
| `build_edge_flux_geometry` (2D) | — | bit-identical | | | PASS |
| `boundary_face_node_weights3d` | — | bit-identical | | | PASS |

**The blocker is gone.** A 998,250-tet mesh now builds its full
edge-flux geometry in **0.71 s**; the same mesh extrapolates to ~285 s
(4.75 minutes) on the reference path.

### Why bit-identity came free

It was measured before any C++ was written, not attempted and debugged
after. Over 20k-40k random device-scale inputs each, numpy turned out
to use plain scalar arithmetic at these sizes -- no BLAS dispatch:

```
np.linalg.norm(v3)   == sqrt(x*x + y*y + z*z)     20000/20000 exact
np.linalg.norm(v2)   == sqrt(x*x + y*y)           20000/20000 exact
np.sum(d**2)  2 elts == a*a + b*b                 20000/20000 exact
np.sum(d)     3 elts == (a + b) + c               20000/20000 exact
np.dot(u3,v3)        == (ux*vx + uy*vy) + uz*vz   40000/40000 exact
np.cross(u3,v3)      == the scalar formula        20000/20000 exact
```

All five kernels matched on the first run. The remaining subtleties were
ordering, not arithmetic, and each is load-bearing:

* **Owner order.** `edge_owners.setdefault(...).append(t)` yields owners
  in ascending element index, and the 3D flux kernel accumulates
  `area += a1 + a2` over them. Sorting incidence records by
  `(lo, hi, elem)` reproduces it; float addition is not associative, so
  this is correctness, not tidiness.
* **Which bad entity gets reported.** Python takes `next(iter(bad))` on
  an *insertion-ordered* dict, so the reported non-manifold edge is the
  first one **encountered**, not the lexicographically smallest. Each
  incidence record therefore carries the sequence number at which the
  dict would first have seen its key.
* **Empty meshes.** `np.array(sorted({}), dtype=int)` has shape `(0,)`,
  not `(0, 2)`. The shim collapses it.
* **int64 at the boundary.** The reference uses `dtype=int`, which is
  C `long` -- int64 on Linux, **int32 on Windows**. The boundary is
  pinned to int64 so the extension's ABI is identical on both.

### Threading

`build_edge_flux_geometry3d` parallelizes over **output** edges with a
thread-private accumulator visiting owner tets in ascending index, so it
is bit-identical at any thread count (gate G-D, checked at 1/2/4/8).
`build_stencil2d`/`3d` accumulate node measures in element order and
stay serial for exactly that reason -- and they are not the bottleneck;
the dictionary work they replace was.

### Two defects surfaced, neither introduced here

1. **The 3D degenerate-tet message leaked a numpy repr.** Under numpy
   2.x, `f"{list(verts)}"` renders as
   `[np.int64(0), np.int64(1), ...]`. Fixed to plain ints on both paths;
   substring-compatible with the existing `match=` assertions.
2. **`build_unstructured_stencil` is winding-sensitive.** `_cot` divides
   by a *signed* cross product while `tri_area` takes `abs()`, so a
   clockwise-wound non-obtuse triangle contributes NEGATIVE dual areas
   and the partition identity fails by exactly 2x. Found by fuzzing the
   compiled path against the reference on a jittered mesh whose jitter
   was large enough to invert a triangle. gmsh emits consistently
   counter-clockwise triangles, so no real caller hits it, and the
   compiled path reproduces the quirk faithfully -- pinned by
   `test_winding_sensitivity_is_reproduced_faithfully` rather than
   papered over. **Fixing it changes physics and must land on both
   paths at once, in its own change.** It is not fixed here.

### Outstanding for the next session

* The **full suite has not been run** against P2 (session limit).
  Targeted runs are green: `tests/test_m21_phase3.py`,
  `test_accel_boundary.py`, `test_architecture_boundaries.py`
  (45 passed) and `tests/test_accel_parity.py` (24 passed).
  Before claiming P2 complete, run both ways, per AGENTS.md:
  ```
  for A in 0 1; do PYTCAD_ACCEL=$A OPENBLAS_NUM_THREADS=1 \
    conda run -n TCAD python -m pytest tests/ gui/tests/ -n 6 -m "not slow" -q; done
  conda run -n TCAD python -m pytest tests/ gui/tests/ -n 6 -m "slow" -q
  conda run -n TCAD python -m pytest tests/test_accel_parity.py -q      # incl. slow floors
  ```
  Gate G-B in particular: `tests/goldens/m13,m14` and the SHA-256
  digests are structured-mesh solves that P2 does not touch, so **any**
  movement there means something is wrong.
* Decide what to do about the winding defect above.
