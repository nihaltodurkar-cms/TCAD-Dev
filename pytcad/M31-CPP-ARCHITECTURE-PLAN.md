# M31 -- C++ / Python / Qt production architecture

Status as of 2026-09-10: **P0, P1, P2, P2b, P3a, P3b, P4, P4b, P5-0 and
P5-1 (all 5 phases) LANDED.** P4b cleared the first adjoint-readiness
gate on the Python path; P5-0 (its own doc,
`M31-P5-ASSEMBLY-NEWTON-PLAN.md`) then made the unstructured cores
reachable by `linsolve`/PETSc at all and removed the LIL row stamping,
1.43x on the 2D unstructured benchmark; P5-1 (`M31-P5-1-SOLVER-
SELECTION-PLAN.md`) added `precond`/`block_size` (Phase B), fallback
parity (Phase C), and an evidence-gated `linsolve="auto"` (Phase D/E)
that measures 10.6-11.5x on 3D unstructured with no C++.

**P5 proper -- the C++ assembler -- STOPPED after P5-0, not started.**
This was not a scope-sign-off refusal (section 3's C++ scope question
below was never reached): P5's own section 9 pre-committed an exit
criterion ("if a re-run of B8/B9 does not move assembly into a position
where porting it is worth a second engine, P5 stops"), and re-running
it AFTER P5-1 (`M31-P5-ASSEMBLY-NEWTON-PLAN.md` section 12) fired that
criterion. B8 (`auto` picks `direct`, unchanged) shows no case; B9's
assembly SHARE rose to 16.3% (from 1.5%) but its ABSOLUTE cost (108.6ms
of a 665ms `auto`-resolved solve) did not move, and does not clear the
bar against two engines' ongoing cost. Read that plan's sections 6, 9,
11 and 12 for the full record.
P2's full-suite validation (see "Outstanding" at the end of the P2
section) has now been run: `PYTCAD_ACCEL=0` fast suite (1404 passed,
1 xfailed, 39 warnings), `PYTCAD_ACCEL=1` fast suite (identical: 1404
passed, 1 xfailed, 39 warnings -- gate G-B confirmed, no golden/digest
drift), the slow gate battery (22 passed, 11 warnings), and
`tests/test_accel_parity.py` incl. slow floors (27 passed). All green,
zero regressions. The winding-sensitivity defect in
`build_unstructured_stencil` (see the P2 section) has since been fixed
on both paths -- that is P2b below.

P3a (`method="petsc"` in `linsolve.py` via petsc4py) landed and was
verified against a REAL petsc4py, not just the not-installed fallback:
`petsc4py` 3.25.4 was installed into the `TCAD` conda env from
conda-forge (the plan's own predicted channel -- pip has no practical
PETSc wheel). That pulled conda-forge's `numpy` (MKL-backed `libblas`)
on top of this env's previously pip-installed `numpy`/`scipy` -- a real
BLAS-backend swap, not a no-op -- so the full fast suite
(`tests/ gui/tests/ -n 6 -m "not slow"`) was re-run after the install
specifically to catch any fallout: **1407 passed, 1 skipped, 1 xfailed,
39 warnings**, zero regressions (the 1 skip is the new
petsc4py-not-installed fallback test, correctly skipping now that it
IS installed; net +4 tests over P2's 1404 -- 3 new `TestPetscMethod`
cases plus that skip). See `tests/test_m22_linsolve.py`'s
`TestPetscMethod` class and `test_petsc_without_petsc4py_raises_not_importerror`.

Implementation notes: `solve_linear(method="petsc")` builds a plain
`MATAIJ` from this module's existing scalar CSR (not a true `MATBAIJ` --
that constructor wants block-row indptr/block-column indices/block-dense
data, a reformat this phase didn't need), then calls
`Mat.setBlockSize(block_size)` before assembly to get the same
point-block `PCPBJACOBI` preconditioning the plan's sec 2 target names,
confirmed sufficient without true BAIJ storage. GMRES restart needed
raising from PETSc's default (30) to `min(restart or 100, n)`, the same
stall this file's scipy `gmres` branch already documents on the
coupled 3D device Jacobian. And PETSc's internal GMRES convergence test
runs on the (left-)preconditioned residual, not the plain
`||Ax-b||/||b||` this module reports as `info["residual"]` -- the two
can differ by roughly an order of magnitude at a requested
`rtol=1e-8` (confirmed: ~4e-6 actual vs. 1e-8 requested on the 1D
diode Jacobian test), so don't read `rtol=` as a tight bound on the
returned solution's actual accuracy the way it is for scipy's methods.
All three carried over unchanged into P3b's C++ backend.

P3b (the same configuration in `core/solver/`) landed; see the P3b
section at the end of this document for what moved, what deliberately
did not, and the measurement that says what it was and was not worth.

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
| P2b | the winding-sensitivity defect P2 surfaced, fixed on both paths | **LANDED** |
| P3a | `method="petsc"` in `linsolve.py` via petsc4py (no C++ needed) | **LANDED** |
| P3b | the same configuration moved into `core/solver/` | **LANDED** |
| P4 | process/particle kernels (MC implant, TED, diffusion, AMR indicators) | **LANDED** |
| P4b | symmetric Dirichlet elimination, Python path (adjoint-readiness) | **LANDED** |
| P5-0 | unstructured cores reach `linsolve` (hence PETSc); LIL row stamping dropped | **LANDED** -- see `M31-P5-ASSEMBLY-NEWTON-PLAN.md` sec 11 |
| P5-1 | linear-solver / preconditioner selection (Python) | **LANDED, all 5 phases** -- `M31-P5-1-SOLVER-SELECTION-PLAN.md` -- 10.6-11.5x measured on 3D unstructured, `linsolve="auto"` reachable |
| P5 | assembly + Newton in C++; the `pytcad_cpp` backend appears | **STOPPED after P5-0**, not started -- section 9's own exit criterion fired post-P5-1; see `M31-P5-ASSEMBLY-NEWTON-PLAN.md` sec 12 -- **adjoint gates below stay relevant if this is ever revisited** |
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
  way to test that bet before committing C++ to it. **Outcome, now that
  P3a and P3b have both landed:** the bet held on Linux/conda-forge, and
  the deployment cost turned out to be containable because PETSc is
  optional *inside* the extension (`TCAD_WITH_PETSC=AUTO`) rather than a
  precondition for building it -- a pip-only build still compiles, still
  passes, and still gets `method="petsc"` via petsc4py. What P3b did NOT
  buy is speed: the compiled and petsc4py backends are within 2% of each
  other, so the justification is entirely architectural. See the P3b
  section.
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
(`np.array_equal`, not a tolerance), single-threaded. Original figures
below were hand-taken when this landed; **re-measured 2026-09-10**
through `benchmarks/p2_p3b_p4_remeasure.py` (M32-BENCHMARK-PLAN.md
section 7's first open item, reusing `test_accel_parity.py`'s own
fixture builders so this measures the exact thing the throughput-floor
gates protect) -- both sets shown, current holds up or exceeds the
original:

| kernel | reference | compiled | speedup (orig / 2026-09-10) | floor | |
|---|---|---|---|---|---|
| `build_unstructured_stencil` (2D) | 77k / 81k tri/s | 3.16M / **3.53M tri/s** | 41x / **43x** | 2M/s | PASS |
| `build_unstructured_stencil3d` | 48k / 52k tet/s | 1.20M / **1.34M tet/s** | 25x / **26x** | 1M/s | PASS |
| `build_edge_flux_geometry3d` | 3.7k / 4.0k tet/s | 1.99M / **2.06M tet/s** | 539x / **560x** | 300k/s | PASS |
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
  Before claiming P2 complete, run both ways, per CLAUDE.md:
  ```
  for A in 0 1; do PYTCAD_ACCEL=$A OPENBLAS_NUM_THREADS=1 \
    conda run -n TCAD python -m pytest tests/ gui/tests/ -n 6 -m "not slow" -q; done
  conda run -n TCAD python -m pytest tests/ gui/tests/ -n 6 -m "slow" -q
  conda run -n TCAD python -m pytest tests/test_accel_parity.py -q      # incl. slow floors
  ```
  Gate G-B in particular: `tests/goldens/m13,m14` and the SHA-256
  digests are structured-mesh solves that P2 does not touch, so **any**
  movement there means something is wrong.
* ~~Decide what to do about the winding defect above.~~ Decided and
  done -- see the P2b section.


---

## P2b -- LANDED

The winding-sensitivity defect P2 surfaced, and deliberately did not
fix, is fixed. One line on each path:

```python
# pytcad/unstructured_assembly.py, _cot
-    return dot / cross
+    return dot / abs(cross)
```
```cpp
// core/include/tcad/geom/simplex.hpp, geom::cot
-    return dot / cross;
+    return dot / std::fabs(cross);
```

**Why that is the right fix, not a clamp.** `_cot` returns the
cotangent of the *undirected* angle at a vertex, subtended by rays to
the other two. That angle lies in `(0, pi)`, so its sine is positive by
definition and the cotangent's sign belongs entirely to the dot product.
The signed cross product in the denominator was importing the
triangle's orientation into a quantity that has none -- which is why
reversing a non-obtuse triangle flipped all three of its dual-area
contributions negative while `tri_area` (an `abs`) did not follow, and
the partition identity failed by exactly 2x.

**Blast radius: none.** `fabs` on a positive double is the identity, so
on counter-clockwise input -- every gmsh mesh, every fixture, every
golden -- the result is bit-for-bit what it was. Measured, not argued:
the full suite moved by exactly the four tests this change adds and
removes, with the m13/m14 goldens and SHA-256 digests unmoved (gate
G-B) and the warning count unchanged at 39.

**What the gate looks like now.**
`test_winding_sensitivity_is_reproduced_faithfully` -- which pinned the
defect -- is replaced by `test_winding_is_irrelevant_to_the_dual_areas`
(acute / right / obtuse triangles, all six vertex orderings, checking
the partition identity and positivity per triangle) and
`test_an_inverted_mesh_still_partitions_exactly` (every triangle in a
20x20 jittered grid reversed).

One thing that had to be got right in the test rather than assumed: all
six orderings agree, but only a REVERSAL is expected to agree
bit-for-bit. `_triangle_area2` is a difference of two products; a
reversal negates it exactly, whereas a cyclic rotation recomputes it
from different coordinate differences and lands a ulp or two away. That
has nothing to do with this defect and would have been there before it.
So the test compares reversals with `np.array_equal` and rotations at
`rel=1e-14`, and says which is which and why.

**Honest scope.** The 3D path was checked and needs nothing: its dual
volumes are a barycentric quarter-split of `fabs(tet_volume)`, which
carries no orientation. The obtuse branch in 2D was likewise never
affected (it splits `tri_area`, already an `abs`) -- it is in the new
test anyway, so that a future "fix" that broke it would be caught.

### Validation

| run | result | vs. P3b |
|---|---|---|
| fast suite, compiled backend | **1428 passed, 2 skipped, 1 xfailed, 39 warnings** | +3 passed |
| fast suite, `PYTCAD_ACCEL=0` | **1420 passed, 10 skipped, 1 xfailed, 39 warnings** | +3 passed |
| slow gate battery | **22 passed, 11 warnings** | unchanged |

---

## P3b -- LANDED

The PETSc `KSP`/`PC` configuration now lives in
`core/src/solver/petsc_ksp.cpp`, reached through `_core.petsc_solve_csr`.
`solve_linear(method="petsc")` has two interchangeable backends and says
which one ran in `info["backend"]`:

| backend | what it is | when it runs |
|---|---|---|
| `"cpp"` | `core/solver/`, this phase | extension built against PETSc, `PYTCAD_ACCEL` not `0` |
| `"petsc4py"` | P3a, kept forever | anything else, including `PYTCAD_ACCEL=0` |

### The result that matters

**The two backends are bit-identical.** `np.array_equal`, not a
tolerance -- the same bar P2's mesh kernels cleared, which is not
usually available for a Krylov solve and is here only because both paths
call the *same* `libpetsc.so` with the same KSP type, restart, PC,
tolerances and matrix. Checked on random systems at n = 30 / 300 / 600 /
2001, on the real interleaved psi/n/p 1D diode Jacobian (399 iterations,
identical residual to the last bit), and with a nonzero initial guess.
Iteration counts and residuals match exactly too, not just the answers.

That is the whole reason the split below was drawn where it was.

### What moved, and what deliberately did not

Moved to C++: which Krylov method (`KSPGMRES`), the restart, which
preconditioner (`PCPBJACOBI` when `block_size` divides the system,
`PCBJACOBI` otherwise), the tolerances, `MatSetBlockSize`,
`KSPSetInitialGuessNonzero`, and PETSc's own start-up.

Stayed in Python, on purpose:

* **The acceptance test.** Both backends return a raw
  `(x, iterations, KSPConvergedReason)` and judge nothing.
  `solve_linear` recomputes the true residual and raises the one
  `LinearSolveError` with the one message. Two backends that disagreed
  about when a solve "converged" would be a parity hole no test could
  paper over, and there is no version of that bug that is cheap to find
  later.
* **CSR canonicalization.** Done once, before dispatch, so both are
  handed the identical matrix. (Not a bug fix: PETSc 3.25's
  `MatSeqAIJSetPreallocationCSR` was checked directly and sorts a
  reversed-index CSR correctly. It removes a way the two could ever
  diverge.) It copies only when scipy's `has_canonical_format` says it
  must, so a caller's assembled Jacobian is never mutated behind its
  back -- gated by `test_the_callers_matrix_is_never_mutated`.

### A real defect, found and fixed on both paths at once

**P3a's `x0` was silently ignored.** It seeded the PETSc solution vector
but never called `KSPSetInitialGuessNonzero`, and PETSc zeroes that
vector at the top of `KSPSolve` unless the flag is set. Measured rather
than reasoned: an *exact* initial guess produced the same iteration count
and the bit-identical answer as no guess at all. With the flag it costs
0 iterations. Fixed in the petsc4py backend and the C++ backend in this
change, so the two cannot disagree about it, and pinned by
`test_nonzero_initial_guess_is_actually_used`. No caller passed `x0`
with `method="petsc"`, so nothing downstream changes.

### Honest accounting of the payoff

Warm (PETSc already initialized), on the 603-unknown device Jacobian,
best of 8: **3.30 ms compiled vs 3.38 ms petsc4py.** There is no
speedup, and none was expected -- PETSc does the arithmetic either way
and the petsc4py wrapper was never the cost. The first-call difference
(~1 s) is PETSc/MPI start-up, paid once per process by whichever backend
runs first, not by the backend.

**Re-measured 2026-09-10** through `benchmarks/p2_p3b_p4_remeasure.py`
(same fixture, same methodology, same 399 iterations both times): 3.31
ms compiled vs 3.38 ms petsc4py. Confirms the original claim exactly --
still no speedup, still none expected, still the same reason.

So P3b is justified by section 1's third conclusion and by the
"Recorded dissent" counter-argument above -- a single engine is what
makes a distributed `Mat`/`DMPlex` reachable in P7 -- and by nothing
else. It should be held to that standard rather than a performance one,
and the same question should be asked again at P5.

### PETSc is optional at build time too

Gate G-F applies one level down. `TCAD_WITH_PETSC` is `AUTO` by default:
found via pkg-config -> compiled backend; absent -> the extension still
builds, `have_petsc()` is false, and `method="petsc"` runs petsc4py (or
raises `LinearSolveError` naming *both* recovery routes if that is
missing too). `petsc_ksp.cpp` is in the source list either way, so the
no-PETSc configuration is a compiled stub that is actually exercised
rather than a branch nobody builds. Verified by building both ways:
with PETSc **74 passed, 2 skipped**; with `-DTCAD_WITH_PETSC=OFF`
**66 passed, 10 skipped**, the skips being exactly the backend-vs-backend
gates that cannot run with one backend.

pkg-config, not a hand-written `FindPETSc.cmake`, because PETSc's own
build writes the include/link line for *that* installation -- which
BLAS, which MPI, 32- or 64-bit indices -- and second-guessing it is how
mismatched PETSc builds get linked together.

### Boundary decisions worth knowing before P7

* **The array boundary is int64 in both directions**, matching the rule
  `_accel.py` states for every kernel (numpy's `dtype=int` is int64 on
  Linux, int32 on Windows). conda-forge's PETSc is built with a 32-bit
  `PetscInt`, so the C++ side converts once, range-checked -- an index
  that does not fit is a thrown `LinearSolveError`, never a truncation
  that would corrupt the matrix into something that still solves and
  still returns a plausible answer. `_accel.status()` now prints the
  width, because 32-bit is a real ceiling (>2^31 nonzeros) and is
  otherwise invisible from Python.
* **PETSc initialization is shared, carefully.** The C++ side calls
  `PetscInitialized` first and initializes only if nobody has, so it
  never fights petsc4py in the same interpreter (which is exactly what
  the parity tests do); it registers `PetscFinalize` at exit only if it
  was the initializer; and it never touches the global error-handler
  stack, because petsc4py owns that and pushing ours would break the
  Python backend's error reporting. The cost is that a genuine PETSc
  error prints its traceback to stderr before being translated --
  identical to what the petsc4py path already does.
* **Whole solves are serialized** under one mutex. PETSc's default build
  is not thread-safe and the binding releases the GIL; a nanosecond lock
  around a millisecond solve is free, and it matches
  `runtime/threads.hpp`'s single-threaded default. Revisit at P7, where
  the parallelism is MPI ranks rather than threads anyway.
* **The compiled path reports better errors.** On a matrix PETSc cannot
  precondition it raises `LinearSolveError: petsc KSPSolve failed
  (PetscErrorCode 73: Object is in wrong state)` where petsc4py gives
  only `error code 73`. The parity gate therefore pins the exception
  *class* across backends, not the message -- unlike P2's mesh kernels,
  where identical message text was the point.

### CI

The existing `accelerated` job builds from a plain pip environment,
which has no PETSc -- so it is now the standing proof that the
PETSc-less configuration works, and it would have skipped every P3b gate
in silence forever. A third job, `petsc`, installs `petsc`/`petsc4py`
from conda-forge, builds with `-DTCAD_WITH_PETSC=ON`, asserts
`_accel.have_petsc()`, and runs the solver gates. The bit-identity claim
can only be checked where both backends exist, so that is the only place
it is checked.

### Validation

Full battery, run both ways per CLAUDE.md, all green, zero regressions:

| run | result | vs. P3a |
|---|---|---|
| fast suite, compiled backend | **1425 passed, 2 skipped, 1 xfailed, 39 warnings** | +18 passed |
| fast suite, `PYTCAD_ACCEL=0` | **1417 passed, 10 skipped, 1 xfailed, 39 warnings** | — |
| slow gate battery | **22 passed, 11 warnings** | unchanged |
| `tests/test_accel_parity.py` incl. slow floors | **35 passed** | +11 |

The 8-test gap between the two fast runs is exactly the
backend-vs-backend gates, which need both backends and correctly skip
when `PYTCAD_ACCEL=0` leaves only one. Warning count is identical to
P2's and P3a's (39), and gate G-B is intact -- `tests/goldens/m13,m14`
and the SHA-256 digests did not move, which they must not, since a
linear-solve backend that changes a structured-mesh golden is wrong by
construction.

Test files:
`tests/test_m22_linsolve.py` (P3a/P3b method gates, backend selection),
`tests/test_accel_parity.py` (the bit-identity gates + binding argument
validation), `tests/test_accel_boundary.py` (capability reporting on all
three optional layers), `tests/test_architecture_boundaries.py`
(`linsolve.py` now imports `_accel`, which is the sanctioned route and
still passes `test_only_accel_imports_the_extension`).


---

## P4 -- LANDED

Five kernels moved to `core/src/process/`, reached through
`_core.{indicator_curvature_tri, indicator_log_density_tri,
debye_ratio_tri, diffuse1d_const, diffuse1d_enhanced}`. Two of the
things the phase line named did NOT move, and the reason in each case
is a measurement rather than a scope call -- see "What deliberately did
not move" below.

### What moved, and what it bought

Measured on this machine, best of 3, `-n 1`, against the Python bodies
that are kept as the oracle. The three indicator rows were hand-taken
originally; **re-measured 2026-09-10** through
`benchmarks/p2_p3b_p4_remeasure.py` (M32-BENCHMARK-PLAN.md section 7),
reusing `test_accel_parity.py`'s own fixtures -- current holds up or
exceeds the original in every row (`indicator_log_density_tri` notably
so, 123x -> 221x). The two diffusion rows were originally left
unmeasured by that script (a different shape -- timestep loops, not a
per-triangle kernel) and are **now re-measured 2026-09-10** through a
second script, `benchmarks/p4_diffusion_remeasure.py`, same n=4000/
t_s=1800s shape, reusing `test_accel_parity.py`'s own `_diffusion_case`
implant profile. The exact TED/OED enhancement parameters were never
recorded alongside the original hand-taken absolute times, so this
re-measurement's absolute seconds are not the same run (13.6-14.2 s
reference vs. the original's 24.6 s) -- what is checkable is the
speedup ratio, and it holds: 3.3-3.7x across two repeats (orig 3.3x)
and 4.4-4.5x (orig 4.1x):

| kernel | reference | compiled | speedup (orig / 2026-09-10) |
|---|---|---|---|
| `indicator_curvature_tri` | 0.27 / 0.27 Mtri/s | 227 / **288 Mtri/s** | 835x / **1081x** |
| `debye_ratio_tri` | 0.28 / 0.27 Mtri/s | 242 / **256 Mtri/s** | 874x / **939x** |
| `indicator_log_density_tri` | 0.80 / 0.81 Mtri/s | 99 / **178 Mtri/s** | 123x / **221x** |
| `process.diffuse_numeric` (n=4000, 1800 s) | 0.325 / 0.32-0.36 s | 0.098 / 0.10 s | 3.3x / **3.3-3.7x** |
| `ted.diffuse_with_defects` (same, params not recorded) | 24.6 / 13.6-14.2 s | 6.07 / 3.1-3.2 s | 4.1x / **4.4-4.5x** |

The indicators are the P2 shape exactly: a per-triangle Python loop
calling `np.linalg.norm` on two-element vectors, run over every triangle
on every AMR pass. `indicator_log_density_tri` gains "only" 123x because
its compiled path still pays for `np.log` over every node, which stays
in numpy on purpose (below).

The diffusion loops are a different shape and give a correspondingly
honest 3-4x: they were never doing too much arithmetic, they were paying
~10 numpy dispatches per timestep against a step count the explicit
stability bound drives into the tens of thousands. Removing the
interpreter round trip is the whole change. At n=4000 the arrays are
large enough that the dispatch is no longer most of the cost, which is
why this is 3-4x and not 800x -- stated because a reader comparing the
two halves of that table deserves to know they are not the same kind of
win.

### The split that makes bit-identity structural

Every transcendental acting on a whole array stays on the numpy side and
only its RESULT crosses: `np.log(n)`/`np.log(p)` for the log-density
indicator, `mesh.debye_length(...)` for the Debye ratio, the peak `scale`
for curvature. numpy's `log` and C++'s are independent implementations,
and the gate is `np.array_equal`, so the only defensible move is to
compute such a value once and hand it down. Same reasoning as P3b's
"C++ owns configuration, Python owns the acceptance test".

There is exactly one exception, and it is measured rather than assumed:
the TED supersaturation's scalar `exp`. Keeping it in Python would mean
materializing one double per timestep -- millions on a fine grid --
purely to hand back. So it was checked directly: over 400k arguments
spanning the range the decay reaches, `std::exp` and `np.exp` agreed
bit-for-bit on every one, through both numpy's array path and its 0-d
scalar path (which is what `ted_supersaturation` actually calls). It is
also gated at runtime by `test_ted_exp_matches_numpy`, which sweeps tau
deep into the tail rather than staying near 0 where any two exps agree.

Reproducing Python's builtin `max`/`min` was the other place bit-identity
had to be earned rather than assumed. These reduce with `if item >
current`, so with a NaN operand the FIRST value wins; `std::max` and
`std::fmax` do not both behave that way. `py_max`/`py_min` in
`indicators.cpp` are written to the reference's rule, so a NaN
propagates the same way rather than the same way "on finite input".

### A defect the port surfaced, in a module it was not porting

`process2d.implant_2d` smooths each depth row with
`_gaussian_smooth_1d`, which builds a dense (Nx, Nx) kernel matrix. The
kernel depends only on `(x, sigma)` -- and it was being rebuilt, with an
(Nx, Nx) `exp`, once per row. The call was O(Ny * Nx^2) in
transcendentals where it is O(Nx^2). Hoisting it out of the loop:

| Nx x Ny | before | after | |
|---|---|---|---|
| 80 x 120 | 4.3 ms | 0.6 ms | 7x |
| 200 x 300 | 124 ms | 8.1 ms | 15x |
| 400 x 600 | 939 ms | 15.1 ms | **62x** |

Bit-identical by construction (the identical matrix, into the identical
rows, in the identical order) and verified as such against a
transcription of the pre-hoist body, not merely argued.

### What deliberately did not move, and why

* **Monte-Carlo implant (`mc_implant.mc_implant_bca`).** Two independent
  reasons, both measured. (a) It is already vectorized over ions, not
  over steps: throughput is flat at 61-81k ion/s from 500 to 100k ions,
  i.e. array-bound rather than dispatch-bound, so there is little of the
  P4 win available. (b) A C++ port could not be gated: bit-identity
  would require replicating numpy's PCG64 stream, its ziggurat
  `standard_exponential`, and its bounded-uniform algorithm exactly, and
  a Monte-Carlo kernel whose stream differs cannot be compared with
  `np.array_equal` at all -- it would be the first kernel in this
  migration with no oracle. Not attempted. If it is ever wanted, the way
  in is to draw the random arrays in numpy and consume them in C++, and
  that should be a decision taken on its own merits.
* **`implant_2d`'s lateral smoothing.** What remains after the hoist is
  a BLAS `dgemv`. C++ cannot reproduce it bit-identically (different
  blocking) and has no reason to try to beat it. The 62x above is the
  whole available win and it is already taken.

### Also in this phase

* **`tcad::IndexOutOfRange` -> Python `IndexError`**, the fourth mapped
  exception. The reference gets this free from numpy fancy-indexing; a
  kernel dereferencing a raw pointer would read out of bounds instead.
  So every kernel taking connectivity validates the index range in one
  O(n) pass up front. The CLASS matches the reference, which is what a
  caller catches; the message text deliberately does not try to
  reproduce numpy's wording.
* **CI gap closed.** The G-E throughput floors are marked `slow`, and
  the `python-only` job's slow battery skips the whole parity file (no
  extension to measure). They therefore ran NOWHERE. The `accelerated`
  job now has a `-m slow` step.

### Validation

| run | result | vs. P2b |
|---|---|---|
| fast suite, compiled backend | **1444 passed, 2 skipped, 1 xfailed, 39 warnings** | +16 passed |
| fast suite, `PYTCAD_ACCEL=0` | **1436 passed, 10 skipped, 1 xfailed, 39 warnings** | +16 passed |
| slow gate battery | **25 passed, 10 warnings** | +3 passed, -1 warning |
| `tests/test_accel_parity.py` | **55 passed** | +16 |

Both fast runs move by exactly +16 -- the 14 new non-slow parity tests
plus the 2 new boundary tests -- with the skip, xfail and warning counts
unchanged. Gate G-B is the one that matters for a phase touching process
code: the m13/m14 goldens and SHA-256 digests are structured-mesh solves
that none of these kernels participate in, so any movement would mean
the change is wrong. There was none.

**The slow battery's warning count went 11 -> 10, and that is not a
behaviour change.** It was chased rather than waved past: re-running the
slow battery with only the three new floor tests deselected gives back
exactly `22 passed, 11 warnings`. pytest de-duplicates warnings per
xdist WORKER, so adding three tests reshuffles the `-n 6` distribution
and two tests that previously emitted the same warning on two different
workers can land on one. No existing test changed what it warns about,
and in particular the compiled kernels are not swallowing a numpy
warning the Python loop used to raise.

### Optionality, re-checked at all three layers

| configuration | result |
|---|---|
| `-DTCAD_WITH_PETSC=OFF` build | `petsc=no`; 96 passed, 10 skipped |
| no `_core.so` at all (gate G-F) | `not built`; parity/boundary 13 passed, 65 skipped; `test_m22_linsolve` + `test_m21_phase3` 53 passed, 2 skipped |

The P4 kernels are PETSc-independent, so the middle layer is only
confirming that adding them did not accidentally couple them to it.

---

## P4b -- LANDED (symmetric Dirichlet elimination, Python path)

Closes the FIRST of the two P5 adjoint-readiness gates below, on the
Python path, **before** P5 starts -- which is the whole point: that
addendum says the decision is free until the assembler lands and a
rewrite afterwards.

### Amendment record

This edits `pytcad/pytcad`'s frozen numerical core, so it goes through
the M11-S3 amendment mechanism:

* **Sign-off:** requested explicitly by the user (2026-09-10), scoped as
  "an isolated Python-path change, before M31 P5", with deliberate
  golden re-baselining authorised.
* **Goldens committed before the edit:** **NO -- and it is not possible
  to satisfy this rule as written.** `.gitignore:29` excludes `*.npz`,
  so `tests/goldens/**` has never been tracked by git and no commit has
  ever contained a golden. (This was mis-stated during the work as
  "HEAD holds the pre-edit set"; it does not.) Regenerating therefore
  overwrote the only copies on disk.

  What was done instead, and is stronger than a git diff: the pre-edit
  goldens were RECONSTRUCTED by shimming `eliminate_csr` back to
  row-only behaviour and re-running the regeneration. All six files came
  back byte-identical to their pre-edit md5sums. That proves both that
  the old baseline is recoverable on demand and that this change is the
  SOLE cause of the difference -- nothing else in the tree contributed.

  **Process gap -- CLOSED 2026-09-10, ahead of P5.** The hard rule was
  rewritten rather than the `.gitignore` carved out: a golden pins ONE
  machine's summation order (`CLAUDE.md`'s own 2026-09-04 merge
  finding), so committing one would publish a machine-specific artifact
  as if it were a shared reference. `CLAUDE.md`'s hard rules now specify
  the reconstruct-and-compare protocol this section used, as four
  numbered steps; `history.md` and `ARCHITECTURE.md` carry the same
  wording, and `.gitignore` says why `tests/goldens/**` is deliberately
  inside the `*.npz` rule.
* **FD-Jacobian-first:** the substitution is proved exact in
  `tests/test_dirichlet_elimination.py` (25 gates) before any core used
  it, and every existing FD-Jacobian gate still passes unchanged.
* **Bit-identity off-path:** N/A -- there is no "off" path here; instead
  the equilibrium goldens are bit-identical (below), which is the
  strongest available equivalent.

### What changed

`J[k,:] = 0; J[k,k] = 1` (row only) became row **and column**
elimination with the known value substituted into the RHS. One shared
helper, `pytcad/dirichlet.py`, applied at every Dirichlet site in the
core: `device.py` (equilibrium Poisson, coupled bias, DG-coupled
equilibrium), `device2d.py` (x2), `device3d.py` (x2), `moscap.py` (x2),
`unstructured_poisson.py`, `unstructured_dd.py`, `unstructured_dd3d.py`
(x2).

Three things were deliberately NOT done:

1. **`F` is never modified.** The substitution changes the RHS only, at
   the solve site. Folding it into the residual would have been tidier
   but `F` is read by M15's backtracking merit function and by every
   convergence test, so it would have changed damping decisions rather
   than only the arithmetic.
2. **Robin rows are never eliminated.** M14's `S_n`/`S_p` surface
   recombination replaces the Dirichlet density rows with a flux
   balance. A Robin row is an EQUATION, not a constraint; eliminating
   its column would delete real physics. The Dirichlet set is recorded
   by the assembler itself (`self._dirichlet_rows`) rather than
   re-derived at the solve site, so the two cannot drift apart, and
   `test_robin_rows_are_never_eliminated` pins it: 6 constrained rows at
   `S=0`, exactly 2 (the psi rows) when `S != 0`.
3. **The C++ path is untouched**, per the requested scope.

### Why the physics is unchanged, and why goldens still moved

Symmetric elimination is a SUBSTITUTION of known values, so it solves
the identical system -- same solution, exactly, in exact arithmetic.
What changes is which matrix reaches SuperLU, hence pivoting, hence
roundoff.

That prediction is borne out precisely:

| golden | moved? | why |
|---|---|---|
| `m13/diode1d_eq.npz` | **no, byte-identical** | at equilibrium psi starts exactly at the contact value, so the substituted term is identically zero |
| `m13/hetero1d_eq.npz` | **no, byte-identical** | same |
| `m13/resistor3d_eq.npz` | **no, byte-identical** | same |
| `m13/diode1d_fwd.npz` | yes | bias: the contact value moves, so the substitution is non-trivial |
| `m13/diode2d_eq.npz` | yes | the 2D initial guess is not exactly at the contact value |
| `TAT_FW_DIGEST`, `HETERO_FW_DIGEST` | yes | bias paths |
| `TAT_EQ_DIGEST` | **no** | equilibrium |

### The measurement that justified the re-baseline

State variables moved by at most **2.1e-15** relative (psi <= 1.1e-14).
Currents moved more -- `Jp` by 4.3e-05 on the heterojunction path -- and
that was chased rather than waved through, because the worst case sits
at the PEAK current, not on a cancelling near-zero value.

The answer: those currents are inherently that badly conditioned. A
**one-ulp** perturbation of the converged `psi`, pushed through the
unchanged current code, moves `Jn` by **5.6e-04** and `Jp` by
**2.4e-04** relative to peak -- an order of magnitude MORE than the
elimination change produced. The change is smaller than one ulp of input
noise on a quantity whose conditioning is ~1e-4/ulp.

### A finding worth acting on separately

**`tests/goldens/m14/` is read by no test.** Only `test_m13_goldens.py`
and `test_m22_linsolve.py` load goldens, both from `m13/`. The four
files in `m14/` (`diode1d_eq`, `diode1d_fwd`, `diode2d_eq`,
`mosfet_eq`, 515 KB) are dead artifacts gating nothing. They are
therefore unaffected by this change -- by not being wired up, not by
being insensitive to it. Either wire them into a gate or delete them;
leaving them looks like coverage that does not exist.

---

## P5 addendum -- adjoint-readiness gates (added 2026-09-09)

`ARCHITECTURE.md` section 4e names differentiable simulation / adjoint
sensitivities as the single differentiator neither Sentaurus nor Atlas
can answer architecturally. That capability (M47-M50) is incremental
IF the C++ assembly is built to support it, and a second rewrite if it
is not.

**P5 has not started, so this decision is currently free. It stops
being free the moment the assembler lands.** Two gates are therefore
added to P5:

1. **The assembler must be transposable.** An adjoint solve applies
   `J^T`. PETSc gives that essentially free for `MATAIJ`/`MATBAIJ` --
   but only if the ASSEMBLY has not baked in something that destroys
   it. **It currently has.** Today's Dirichlet handling zeroes the
   contact rows and writes a unit diagonal
   (`unstructured_dd.py:337`, `device2d.py:920`), which is not
   transpose-friendly: the transpose of a row-eliminated matrix does
   not impose the same constraint on the adjoint problem. The C++ path
   must use a symmetric constraint elimination instead (eliminate both
   row and column, moving the known value to the RHS), which is
   standard, preserves symmetry of the constraint, and costs nothing
   extra in the forward solve.
   *Gate:* on a converged bias point, `J^T x` computed by the
   assembler matches a dense-transpose reference to `rtol <= 1e-12`,
   and the forward solve remains bit-identical to the Python oracle.

2. **The residual must be parameterized.** `dR/dp` is only meaningful
   if `p` is a named vector the assembler knows about (doping
   magnitudes, mobility coefficients, lifetimes, geometry scalars),
   rather than values closed over inside Python. `ResidualAssembler`
   takes an explicit parameter vector and can report which entries a
   given residual row depends on.
   *Gate:* for at least one parameter of each kind, the assembled
   `dR/dp` column matches a finite-difference column to the `5e-5`
   relative tolerance `tests/test_m13_solver.py:127`'s FD-Jacobian
   probe already uses.

Neither gate requires implementing adjoints in P5 -- only not
foreclosing them. If P5 ships without these, record it as a deliberate
decision with its cost (M47 becomes a rewrite of P5, not an addition),
rather than discovering it later.
