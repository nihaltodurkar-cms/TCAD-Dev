# M31 P5 -- assembly + Newton in C++

Status: **P5-0 LANDED (section 11); P5a-P5e (the C++ assembler itself)
STOPPED, not started -- section 9's own pre-committed exit criterion
was invoked 2026-09-10 (section 12) once M31 P5-1 made the re-run
possible. B8 shows no case (`auto` picks `direct`, unchanged); B9's
assembly SHARE rose to 16.3% but its ABSOLUTE cost (108.6ms of a 665ms
solve) does not clear the bar against two engines' ongoing cost. This
was not a scope sign-off refusal -- section 3's C++ scope question was
never reached, because section 9's OWN prior condition for stopping
fired first.** Written 2026-09-10, after P4b landed; section 6 updated
the same day once B8/B9 existed and the phase had a real profile --
which added a sub-phase (P5-0) and weakened the case for the C++ ones.

Parent: `M31-CPP-ARCHITECTURE-PLAN.md` (phase table section 4, gates
section 5, honest limits section 6, and the **P5 addendum** at the end
of that file, which this document expands rather than replaces).
P5 is large enough to warrant its own doc, on the M21-Phase-3
precedent; the parent's P5 row should point here once this is approved.

Governing: `Architecture_Master_Plan.md` section 37 (*"Do not rewrite
the project"* -- progressive extraction), section 41 (architectural
tests), section 36 (no performance claim without a benchmark table).

---

## 1. Why this phase exists, and the standard it must be held to

The parent plan records a dissent, and it is the right frame for
reading this document:

> An independent design review argued `device*.py` and `linsolve.py`
> should stay Python **permanently** -- that P5 is negative value [...]
> The counter-argument, and the reason P5 is retained: a single engine
> is what makes distributed 3D possible at all -- with assembly in
> Python, every Newton iteration must marshal a Jacobian across the
> boundary, which forecloses PETSc's distributed `Mat` and `DMPlex`.
> That is an architectural justification, not a performance one, and it
> should be held to that standard when P5 comes up.

P5 has now come up. This plan holds it to that standard in three
concrete ways:

1. **The scope is chosen to be the code that actually needs the
   architecture** (section 3): the unstructured path, which is the only
   one `DMPlex` means anything for. A structured numpy grid does not
   become distributable by being written in C++.
2. **The performance claim is deferred to a measurement that does not
   exist yet** (section 6). No B-case covers the unstructured DD solve
   today, so P5 cannot quote a speedup until one exists -- and per
   M32's own lesson, the benchmark goes in *before* the thing it
   polices, not after.
3. **A named exit** (section 9): if the P5b measurement comes in below
   the stated floor and no distributed-`Mat` path is demonstrated, P5
   stops there and the parent plan records the dissent as upheld.

## 2. What "assembly + Newton in C++" cannot mean here

Three findings from reading the current code, before any scope call.
Each of them shrinks what C++ can honestly own in this phase, and all
three are consequences of the bit-identity rule (parent gate G-A,
`np.array_equal`, never `allclose`) rather than of effort.

**(a) The linear solve must not move in the same step as the
assembly.** Every unstructured core ends at `spsolve` (SuperLU).
Bit-identity to the Python oracle survives a C++ assembler *only if the
identical matrix reaches the identical SuperLU*. Swapping in PETSc at
the same time makes the comparison `allclose` at best -- and P3a
already documented that PETSc's convergence test runs on the
preconditioned residual, so `rtol=1e-8` is not a bound on the returned
solution. Assembly and solver therefore land as separate sub-phases
with separate gates (P5c vs P5e), and only the assembly one is gated
bit-identical.

**(b) Dirichlet elimination stays on the scipy side in this phase.**
`unstructured_dd.solve_bias` builds `J` as CSR, converts with
`.tolil()`, stamps the contact rows, then calls
`dirichlet.eliminate_csr` -- which is a sequence of sparse matmuls
(`Jc @ g`, `Jc @ keep_cols`). A C++ path emitting triplets would
naturally use `eliminate_coo` instead, and that is a *different
floating-point accumulation order* -- the same system, not the same
bits. Porting elimination is a re-baseline, and P4b already spent one
re-baseline on this exact code. So P5 keeps `eliminate_csr` where it
is and the C++ assembler hands back a matrix in the shape scipy
already expects.

**(c) `np.add.at` and duplicate-triplet summation fix an order that
C++ must reproduce, not improve on.** The residual scatters edge
fluxes with `np.add.at(F[0::3], i_idx, dpsi_flux)`, and the Jacobian
emits *repeated* `(row, col)` triplets that `sp.csr_matrix` sums in its
own order. Both are order-dependent in floating point. Consequences,
stated so no one rediscovers them at the debugger:

* The edge loop cannot be parallelised with atomics or a
  non-deterministic reduction and still pass G-A. Parent gate G-D
  (thread invariance under `np.array_equal`) already forbids it; here
  it bites in the phase's central loop rather than at its edges.
* Either C++ reproduces scipy's duplicate-summation order exactly, or
  C++ returns triplets and lets scipy build the matrix. **The second
  is the plan's choice** -- it keeps the risky part in the oracle's own
  code, and it is the same call P4 made about BLAS `dgemv` in
  `implant_2d`.

The residue after (a), (b) and (c) is: **C++ owns the per-edge and
per-node arithmetic that produces the triplets and the residual
vector.** That is a real thing to own -- it is the whole inner loop,
and it is what a distributed `Mat` would later be filled from -- but it
is deliberately less than the phase title suggests, and saying so up
front is cheaper than discovering it in review.

## 3. Scope decision (needs sign-off)

**Target: the unstructured path.**

```
pytcad/unstructured_poisson.py   _residual_jacobian            (2D Poisson, block 1)
pytcad/unstructured_dd.py        _residual_jacobian            (2D coupled DD, block 3)
pytcad/unstructured_dd3d.py      _residual_jacobian_poisson3d  (3D Poisson, block 1)
                                 _residual_jacobian_dd3d       (3D coupled DD, block 3)
```

**Explicitly NOT in P5: `device.py`, `device2d.py`, `device3d.py`,
`moscap.py`** -- the structured cores.

Four reasons, in decreasing order of how much they should count:

1. **The architectural justification only applies to the unstructured
   path.** `DMPlex` is an unstructured-mesh topology object. A
   structured numpy device does not gain distribution from a C++
   rewrite, so porting it is justified by nothing this milestone has
   claimed.
2. **The physics surface is bounded and enumerable.**
   `unstructured_dd._residual_jacobian` is Poisson + Scharfetter-Gummel
   continuity + SRH/Auger + the Anderson `dlnnie` band-offset shift +
   harmonic-mean edge mobility. That is the whole list.
   `device.py:_residual_jacobian` is ~500 lines carrying Fermi-Dirac
   nu-factor SG, incomplete ionization, TAT, impact ionization with a
   frozen-generation outer loop, Kane BTBT, density-gradient coupling,
   and M14's Robin surface-recombination rows. Porting that
   bit-identically is a milestone, not a phase.
3. **G-B stays a tripwire instead of becoming a target.** The parent's
   blast-radius gate is "`tests/goldens/m13/*`, `m14/*` and the SHA-256
   digests pass unchanged" -- and those are *structured*-mesh solves.
   That gate is only meaningful while the phase has no business
   touching them. Porting `device.py` would make the strictest goldens
   in the repo the thing under test, which is exactly the risk
   concentration section 6 of the parent warns about.
4. **P2 already put this path's inputs in C++.** `edge_flux_geometry3d`
   and the 2D stencil feed precisely these assemblers. P5 on the
   unstructured path continues a chain; P5 on the structured path
   starts a new one.

**What is lost by this call, stated honestly:** the structured cores
are where the validated device physics lives and where nearly all user
traffic goes today. P5 as scoped here makes the *research* path (large
unstructured 3D) faster and distributable, and leaves the *taught* path
untouched. If the user wants the structured cores in C++, that is a
separate, larger decision and should get its own milestone number
rather than being folded in here.

## 4. Sub-phases

| | | gate summary |
|---|---|---|
| **P5-0** | Python-side: route through `linsolve`, drop the `tolil()` stamping | **LANDED 2026-09-10** -- see section 11 |
| **P5a** | Parameterized assembler API, **Python first** | closes adjoint gate 2 on the oracle before C++ exists |
| **P5b** | C++ assembler: 2D unstructured Poisson (block 1) | G-A/G-C/G-D/G-F + first real measurement |
| **P5c** | C++ assembler: 2D unstructured coupled DD (block 3) | the main event; G-A at every Newton iterate |
| **P5d** | 3D: Poisson + coupled DD | reuses P5c kernels; G-B untouched throughout |
| **P5e** | Newton driver + `pytcad_cpp` backend + PETSc KSP | NOT bit-identical -- gated on physics, not bits |

### P5-0 -- the Python-side prerequisites

Created by section 6's measurement, which did not exist when the rest of
this plan was drafted. Two changes, neither of them C++:

1. Route the unstructured cores' linear solve through
   `linsolve.solve_linear` instead of calling `spsolve` directly, so
   `method=`/`precond=` -- and therefore P3a/P3b's PETSc KSP stack --
   reach them at all. They cannot today.
2. Stamp the Dirichlet contact rows before the CSR is built, instead of
   converting to LIL and row-assigning on every Newton iteration.

Together these address ~90% of B8's measured runtime against the ~9%
the C++ assembler targets. Both are gated bit-identical against the
current path (gate P5-0-1). Full rationale and the numbers: section 6.

### P5a -- parameterized assembler, Python path first

This is P4b's move repeated: make the *oracle* have the property first,
so the C++ port has something bit-identical to be checked against. The
addendum's gate 2 says `dR/dp` is only meaningful if `p` is a named
vector the assembler knows about rather than values closed over inside
Python. Today the parameters arrive as a dozen positional arrays
(`C_s`, `nie_s`, `D_n_s`, `D_p_s`, `tau_n`, `tau_p`, `eps_trans`, ...).

Deliverable: a `ParameterVector` (names -> slices) plus an assembler
entry point that takes it, with the existing positional signature kept
as a thin adapter so **no caller changes and no golden moves**. This
sub-phase must be provably a no-op on results: gate P5a-1 below.

Parameters to name, at minimum one of each kind the addendum asks for:
doping magnitude (`C_s`), a mobility coefficient (`D_n_s`), a lifetime
(`tau_n`), and a geometry scalar (`eps_trans`, which carries the dual
facet/primal edge ratio).

### P5b -- 2D unstructured Poisson in C++

The smallest assembler in the tree (`unstructured_poisson.py`, 158
lines total). It exists in this plan to establish the boundary contract
cheaply: triplet layout, residual buffer ownership, index validation
(`tcad::IndexOutOfRange`, the P4 precedent), and the first honest
throughput number for a P5-shaped kernel.

**The Bernoulli question is settled here, not in P5c.** `bernoulli`/
`dbernoulli` (`pytcad/kernels.py:88`) reduce to `np.expm1` plus
`clip`/`where`. P4's rule is that array transcendentals stay in numpy
and only results cross, with exactly one measured exception (TED's
scalar `exp`, proven bit-identical over 400k arguments and gated at
runtime by `test_ted_exp_matches_numpy`). Two options, and P5b picks
one with a measurement rather than a preference:

* **Option A (default):** numpy computes `Bp/Bm/dBp/dBm` per edge; C++
  receives them and does the stamping. Bit-identity is free. Cost: one
  array round trip per Newton iteration, and the kernel is no longer
  self-contained for a future distributed `Mat`.
* **Option B:** C++ owns `bernoulli`, proven by the TED protocol -- a
  sweep over the argument range the SG delta actually reaches
  (including the `|x| < 1e-4` series branch and both `clip` boundaries
  at +/-700), asserting `std::expm1` == `np.expm1` bit-for-bit on every
  sample, plus a runtime gate.

Option B is what the architecture wants and Option A is what ships if
the sweep finds a single disagreement. Poisson has no Bernoulli, so
P5b runs the sweep as a standalone experiment while porting something
that does not depend on the answer. That sequencing is the point.

### P5c -- 2D unstructured coupled DD in C++

The phase's real content: `unstructured_dd._residual_jacobian`, block
size 3, interleaved `[psi, n, p]`.

Kept in Python, deliberately: the `recombination()` call (SRH/Auger --
transcendental-free but shared with the structured cores, and moving it
would widen the blast radius to code `device.py` also calls), the
`eliminate_csr` step (section 2b), the matrix construction (section
2c), and `spsolve`.

Moved: the residual assembly, the flux stamping, and the ~20 `add()`
triplet blocks.

**One incidental finding to fix in this sub-phase, on the Python side
and separately gated:** `solve_bias` does `Jl = J.tolil()` then
row-assigns `Jl[rows, :] = 0.0` on every Newton iteration. LIL
row-assignment on a `3N x 3N` matrix is a known-expensive path, and it
is pure overhead -- the contact rows could be stamped before the CSR is
built. Whether it is worth fixing is a measurement (take it in P5b's
profiling pass), but it must be measured and recorded either way,
because if it dominates then the C++ assembler is optimising the wrong
half of the iteration and the phase's own justification changes shape.

### P5d -- 3D

`unstructured_dd3d.py` carries the same two shapes with volumes instead
of areas and tets instead of triangles, plus `_gate_node_terms`. If
P5c's kernels are written against an edge list and a per-node measure
rather than against 2D-ness, this sub-phase is mostly binding work.
That is the design constraint P5c should be written under, and the
reason 3D is a separate sub-phase rather than the same one is that
"mostly" is a prediction.

### P5e -- Newton driver, `pytcad_cpp` backend, PETSc

The point at which the phase table's `pytcad_cpp` backend appears, as a
new `workbench/solvers/` backend next to `PytcadBackend` and
`devsim_backend` (`workbench/solvers/base.py:36`, `get_backend`).

**This sub-phase is not bit-identical and must not claim to be.** A
C++ Newton loop calling PETSc `KSP` produces a different iterate
sequence from `spsolve`. It is gated on physics and on convergence
behaviour, not on bits (gates P5e-1..3 below). Keeping it behind its
own backend id -- rather than switching the existing path -- is what
makes that acceptable: the oracle stays reachable and the default
unchanged until P9.

## 5. Gates

Parent gates **G-A, G-B, G-C, G-D, G-E, G-F apply unchanged** to every
compiled kernel in P5b-P5d. In addition:

**P5-0-1 (bit-identity of the Python-side prerequisites).** With
`method="direct"`, routing through `linsolve.solve_linear` and stamping
the contact rows pre-CSR must leave `(psi, n, p)` `np.array_equal` to
the current path on every unstructured fixture. Note the trap M22
already hit and documented: `solve_linear` must not reformat the matrix
for the direct method -- `spsolve(A_csr, b)` and
`spsolve(A_csr.tocsc(), b)` differ at ~1e-16, so a wrapper that
converts silently breaks bit-identity (`CLAUDE.md`'s scipy gotcha,
M22 G2). The current call site passes `Jc.tocsc()` explicitly, so the
conversion has to be preserved, not dropped.

**P5a-1 (no-op proof).** The parameterized assembler and the positional
one produce `np.array_equal` `F` and identical `J` triplets on every
existing unstructured fixture. No golden regenerated in P5a.

**G-T (adjoint gate 1, transposability -- addendum).** On a converged
bias point, `J^T x` from the assembled matrix matches a dense-transpose
reference to `rtol <= 1e-12`, and the forward solve stays bit-identical
to the Python oracle. P4b closed this on the Python path already
(`tests/test_dirichlet_elimination.py`, 25 gates); P5 must not
re-break it, and the C++ path inherits it by handing back a matrix
`eliminate_csr` then processes unchanged.

**G-P (adjoint gate 2, parameterization -- addendum).** For at least
one parameter of each kind named in P5a, the assembled `dR/dp` column
matches a finite-difference column to `5e-5` relative -- the same
tolerance `tests/test_m13_solver.py:127`'s FD-Jacobian probe uses.

**G-N (Newton-path identity).** New, and the one most likely to catch a
real defect. Parity is asserted at **every Newton iterate**, not only at
convergence: same iteration count, and `np.array_equal` on
`(psi, n, p)` after each step. A converged-only comparison passes even
when the two paths took different routes there, which is precisely the
failure mode the M15 impact-ionization debugging showed is possible
(bit-identical first `du`, divergent iteration dynamics).

**G-W (non-convergence parity).** The `warnings.warn("unstructured
coupled bias solve did not converge.")` path fires on the same inputs,
with the same text, on both paths -- and `tcad::ConvergenceFailure`'s
existing translation is not used to convert a warning into an
exception. G-C's rule ("identical exception type and message") extended
to warnings, because this core warns where others raise.

**P5e-1..3 (the non-bit-identical sub-phase).**
1. Terminal currents agree with the oracle to the tolerance the
   existing unstructured validation tests already assert against
   analytic/reference values -- i.e. the physics gates pass unchanged
   with the new backend selected.
2. Iteration count is within a stated factor of the direct path on
   every B-case; a regression here is reported, never averaged away.
3. `LinearSolveError` is raised rather than a non-converged iterate
   being returned silently -- `tests/test_m22_linsolve.py`'s G4 rule,
   applied to the new backend.

**G-E floor for P5:** deliberately left blank in this draft. It cannot
be written honestly before section 6's baseline exists. It must be an
absolute number, per the parent's rule, and it must be set from a
harness run rather than from a hand-timed script.

## 6. The measurement -- taken 2026-09-10, before P5 starts

When this plan was drafted, **no B-case exercised the unstructured DD
solve**: `benchmarks/cases.py` B1-B7 all run the structured cores. The
code P5 targets had no row in the dashboard, so section 36 of the master
plan forbade any performance claim about it. That has now been fixed
ahead of the phase rather than after it, which is M32's own lesson:

> M32 landed AFTER P4 rather than before it -- so P4's own speedups were
> measured by hand, not by the harness, and should be re-measured
> through it before being quoted again.

**B8** (2D unstructured DD, gmsh triangles) and **B9** (3D unstructured
DD, gmsh tets) now exist, both `requires=("gmsh",)`, both sized by
geometry rather than by mesh density (`build_diode_mesh` clamps the bulk
cell at `SizeMax = 2e-5` cm, so `Nd_scale` is not a size knob:
1e16 -> 2,102 nodes, 1e17 -> 3,350).

### 6.1 A harness defect the new rows exposed

Adding them surfaced a real defect in M32's own instrumentation, and it
had to be fixed before any P5 baseline could be trusted: **every timing
M32 has published so far was inflated by `tracemalloc`, unevenly.**
The harness ran the whole measured region under a memory trace, and that
hook charges per allocation -- so it taxes an allocation-heavy path far
harder than an array-heavy one:

| case | untraced | traced | |
|---|---|---|---|
| B3 (2D MOSFET, structured) | 0.047 s | 0.056 s | 1.19x |
| B8 (2D unstructured DD) | 0.205 s | 0.832 s | **4.05x** |

B8's 4x is the LIL row-stamping in `solve_bias` making ~66k
`ndarray.tolist` calls per solve -- which is to say, the inflation was
concentrated in exactly the code P5 exists to judge. Left alone it would
have put a 4x thumb on the scale of P5's own before/after.

Fixed in `harness.run_case`: the first repeat runs traced and supplies
`py_peak_mb` only; the timing repeats run untraced. At `--repeats 1`
there is no untraced run and the row now says so in its notes. Gated by
`test_timing_and_memory_come_from_separate_runs` and
`test_repeats_of_one_admits_its_timing_is_inflated`. **`BASELINE.md` and
`FULL.md` were regenerated**; the pre-2026-09-10 numbers in them (and
any quoted from them) were inflated -- B2's assembly column, for
instance, was 38.1 ms and is 4.6 ms.

### 6.2 The split, and what it says about P5

Untraced, this machine (`BASELINE.md` quick, best of 3; `FULL.md` full):

| | B8 quick | B9 quick | B8 full | B9 full |
|---|---|---|---|---|
| DOF | 3,003 | 2,889 | 34,023 | 7,464 |
| total | 203.5 ms | 901.6 ms | 5.28 s | 7.32 s |
| **assembly** (what P5 ports) | **18.1 ms -- 8.9%** | **42.9 ms -- 4.8%** | **183.6 ms -- 3.5%** | **112.1 ms -- 1.5%** |
| linear solve | 105.7 ms -- 52% | 670.7 ms -- 74% | 3.27 s -- 62% | 6.67 s -- 91% |
| remainder | ~80 ms -- 39% | ~190 ms -- 21% | ~1.83 s -- 35% | ~0.54 s -- 7% |

The full-size columns are the ones to quote, and they are worse for P5
than the quick ones: assembly's share FALLS as the problem grows
(8.9% -> 3.5% on B8, 4.8% -> 1.5% on B9), because the direct solve
scales superlinearly and the assembly does not. A C++ assembler's
ceiling shrinks exactly as the problems get big enough to care about.

Three conclusions, and none of them is "port the assembler and win":

1. **The assembler is 1.5-8.9% of the solve, and falls with size.** An infinitely fast C++
   assembler buys at most that. This is the same shape as the parent
   plan's structured finding (0.011 s of 0.494 s) and it should be read
   the same way: P5 is an architectural change, and any speed claim it
   makes must be quoted against these two rows.
2. **The linear solve dominates, at 52-91%** -- and the
   unstructured cores call `spsolve` DIRECTLY, bypassing `linsolve.py`
   entirely, so they cannot reach P3a/P3b's PETSc KSP stack at all
   today. Routing them through `linsolve.solve_linear` is a
   Python-side change, needs no C++, and addresses three-to-fifteen
   times more of the runtime than the assembler port does.
   **This should be split out as its own sub-phase and done first**
   -- see P5-0 below.
3. **The remainder is ~35-39% on B8**, and the profile says it is the
   `tolil()` + LIL row-assignment + `eliminate_csr` block, not physics.
   That is more than four times the assembly cost, in code that is pure
   bookkeeping.

### 6.3 P5-0 -- the sub-phase this measurement created

Before any C++: route the unstructured cores' linear solve through
`linsolve.solve_linear` (so `method=` reaches them, PETSc included), and
stamp the contact rows before the CSR is built instead of via `tolil()`.
Both are Python-side, both are gated bit-identical against the current
path with `method="direct"`, and together they address ~90% of B8's
runtime -- against the ~9% P5c targets.

If P5-0 lands and the profile then says assembly has become the
bottleneck, P5b-P5d start with a real justification. If it does not, the
section 9 exit applies with better evidence than this plan could have
had before the case existed.

**This is the phase-order lesson of the parent plan repeating itself.**
Section 1 there records that "the premise 'the numerics are in Python,
so move them to C++ for speed' does not survive contact with a
profiler", and reordered M31's phases around what was measured. The same
profiler, pointed at the unstructured path, says the same thing again.

## 7. Bit-identity hazards specific to this port

A checklist, each item already sitting in the code being ported:

| hazard | where | handling |
|---|---|---|
| `np.add.at` scatter order | `unstructured_dd.py:136-165` | serial edge loop in index order; G-D forbids the alternative |
| duplicate `(row,col)` triplets summed by scipy | the `add()` helper, ~20 call sites | C++ returns triplets; scipy still builds the matrix |
| `np.expm1` vs `std::expm1` | `kernels.py:88,99` | P5b decides by sweep (Option A/B) |
| `np.log(nie_s[j]/nie_s[i])` | `solve_bias`, per edge | stays in numpy, result crosses (P4 rule) |
| `hmean` on edge mobilities | `solve_bias:284` | pure arithmetic, safe to move, but computed once per solve so there is no reason to |
| `np.clip` NaN semantics | `dpsi` damping, `bernoulli`'s +/-700 | reproduce numpy's rule explicitly, the `py_max`/`py_min` precedent from P4 |
| object-dtype `mats` array | `solve_bias:250` | never crosses the boundary; per-node scalars are extracted Python-side |

## 8. Amendment record (to be completed before any edit)

P5 edits `pytcad/pytcad`, the frozen numerical core, so it goes through
the M11-S3 amendment mechanism:

* **Sign-off:** NOT YET GIVEN. Required scope statement: "M31 P5,
  unstructured path only, structured cores untouched, no deliberate
  golden re-baseline expected."
* **Goldens committed before the edit:** P4b established that this rule
  as written is **impossible to satisfy** -- `.gitignore:29` excludes
  `*.npz`, so `tests/goldens/**` has never been tracked. The
  reconstruct-and-compare protocol P4b used is the achievable
  equivalent and is what P5 will use. **This should be fixed in
  `CLAUDE.md` before P5 rather than worked around a second time**; it
  is a one-line `.gitignore` carve-out or a one-sentence rule rewrite,
  and right now the rule reads as satisfied by a step nobody can
  perform.
* **FD-Jacobian-first:** G-P is exactly this, and it is a gate rather
  than a habit here.
* **Bit-identity off-path:** the whole of G-A/G-N. P5 expects **no
  golden movement at all** -- unlike P4b, which had a predicted and
  measured re-baseline. If a golden moves in P5b-P5d, that is a defect,
  not a re-baseline, and the phase stops until it is explained.

Also worth closing while in this code, both inherited from P4b's
findings and neither strictly P5's job:

* **`tests/goldens/m14/` is read by no test** (four files, 515 KB,
  gating nothing). Wire them into a gate or delete them.
* The `.gitignore` / CLAUDE.md contradiction above.

## 9. Exit criteria, and the named stopping point

P5 is complete when P5-0 and P5a-P5e have landed with every gate in
section 5 green, the dashboard carries an unstructured row measured through the
harness, and `pytcad_cpp` is selectable as a workbench backend with the
default path unchanged.

**The stopping point, agreed in advance:** section 6 has already taken
the profile this criterion was written to wait for, and it says assembly
is 4.8-8.9% of the solve. So the trigger is now sharper: if P5-0 lands
and a re-run of B8/B9 does not move assembly into a position where
porting it is worth a second engine, P5 stops after P5-0 and P5a. What is banked in that case is still real -- the
unstructured cores reaching the PETSc stack for the first time (P5-0),
the parameterized assembler (P5a), the adjoint gates closed on the
Python path, and an honest measurement that settles the recorded
dissent with a number instead of an argument. The parent
plan's dissent section is then updated to say the dissent was upheld,
and P6-P9 are re-planned without a C++ assembly layer under them.

Deciding that in advance is what keeps the phase from being defended
after the fact.

## 10. Honest limits

* P5 leaves the structured cores in Python. Most users, and all of the
  teaching surface, stay on the Python path after this phase. Anyone
  reading "assembly is in C++" without section 3 will overestimate what
  landed.
* Two engines is an ongoing cost the parent already names, and P5 is
  where it starts being paid on physics code rather than on kernels:
  every future change to unstructured DD physics lands twice until P9.
* PETSc in P5e inherits P3a's caveat verbatim -- the reported
  `info["residual"]` and PETSc's own convergence test are not the same
  quantity, and can differ by roughly an order of magnitude.
* Nothing in P5 implements adjoints. G-T and G-P only keep M47-M50
  reachable as an addition rather than a rewrite. That is the entire
  claim.

---

## 11. P5-0 -- LANDED 2026-09-10

### Amendment record (M11-S3 mechanism)

* **Sign-off:** user, 2026-09-10 ("start P5-0"), scoped by section 4's
  P5-0 entry: the unstructured cores' linear-solve routing and Dirichlet
  row stamping, Python-side, no C++, no physics change.
* **Golden baseline:** recorded before the edit, per CLAUDE.md's
  reconstruct-and-compare rule. All ten goldens
  (`tests/goldens/m13/*` x6, `m14/*` x4) came back **byte-identical
  after** the edit -- md5 of the combined manifest
  `ca2a370fb1e5a39e7e91f87e02a21c4a` before and after -- so step 3's
  shim-and-regenerate was not needed: nothing moved to explain. The
  m13 digests (`TAT_EQ`, `TAT_FW`, `HETERO_FW`) pass unchanged.
  This is the expected result and was the gate: the unstructured path
  contributes to no golden, so **any** movement would have meant the
  change was wrong.
* **FD-Jacobian-first:** N/A -- the Jacobian's VALUES are untouched.
  What changed is how the constrained rows are written into it, gated
  byte-identically instead (below).
* **Bit-identity off-path:** there is no "off" path; the equivalent is
  byte-identity of the matrix and `np.array_equal` on the solve, which
  is what the 18 gates in
  `tests/test_m31_p50_unstructured_linsolve.py` assert.

### What changed

`pytcad/dirichlet.py` gained `stamp_dirichlet_rows(J, rows)` -- left
multiplication by a 0/1 diagonal, plus the unit diagonal added back --
replacing this, in all four unstructured Newton loops:

```python
Jl = J.tolil()
Jl[rows, :] = 0.0
Jl[rows, rows] = 1.0
```

and the update now goes through `linsolve.solve_linear(..., method=
opts.linsolve, rtol=opts.linsolve_rtol, block_size=3)` instead of a
bare `spsolve`. Touched: `unstructured_poisson.solve_poisson_equilibrium`,
`unstructured_dd.solve_bias`, `unstructured_dd3d.solve_poisson_equilibrium3d`
and `.solve_bias3d`.

A **second substitution** rode along in the two 3D loops and is gated
separately: a gate contact's Robin coupling was stamped one entry at a
time through the same LIL view (`J[k, k] -= gt`) and is now accumulated
into a diagonal and added once. `d + (-gt)` is the same IEEE-754
operation as `d - gt`, so this is bit-identical -- but only while each
node is touched once per pass, which the accumulate-then-add form makes
true by construction. The gate covers the shared-node wrap-around case
`unstructured_dd3d`'s own docstring warns about.

### What it bought

Same-session A/B (the new path and a shim of the old one, alternating in
one process, best of 2, full size):

| | old | new | |
|---|---|---|---|
| B8 2D unstructured DD | 5.15 s | **3.61 s** | **1.43x** |
| B9 3D unstructured DD | 7.96 s | 7.56 s | 1.05x |
| the stamping step alone, per Newton iteration (B8 full) | 115.4 ms | **2.6 ms** | **44.8x** |

B8's "remainder" -- the share that is neither assembly nor linear solve
-- went from **35% to ~2.7%**. B9 barely moves because its remainder was
only 7% to begin with: at 7,464 nodes on a tet mesh's wider stencil the
direct solve is 91% of the run, and no amount of bookkeeping speed
touches that. Both numbers are reported; quoting only B8's would be the
kind of selective reporting M32 exists to prevent.

An earlier cross-run comparison appeared to show B9 getting *slower*
(7.32 s -> 7.81 s). That was machine noise between two separate report
runs, not the change -- `solve_linear`'s own overhead measured 2 ms on a
434 ms solve (0.5%). The same-session A/B above is what settled it, and
the lesson is the one `benchmarks/README.md` already records: timings
are comparable only within a run on a quiet machine.

### A defect this surfaced in M32's harness

Routing through `solve_linear` made both new benchmark rows report
**zero linear solves**. The cause is a Python binding rule, not a
solver problem: the cores do `from .linsolve import solve_linear`, so
they hold their own reference, and `instrument.py` was patching only
`pytcad.linsolve.solve_linear`. It now patches the module-local name
too, the way it already did for `spsolve`.

Worth noting for its own sake: **the existing M32 gate caught this**
before any number was quoted from it.
`test_case_runs_and_reports_a_real_measurement` asserts
`linsolve_calls > 0` for exactly this reason, and it failed the moment
the binding escaped. That is the gate doing the job it was written for.

### What P5-0 does NOT settle

It does not make the case for P5b-P5e. Assembly's share of B8 full went
from 3.5% to ~5.4% -- higher only because the denominator shrank, not
because assembly got more expensive. The linear solve is now **92%** of
B8 full and 98% of B9 full. Section 9's exit criterion reads on that:
the next question is whether the PETSc stack these cores can now reach
moves it, and that is a Python-side experiment (`opts.linsolve="petsc"`)
before it is ever a C++ one.

**That experiment has since been run**, and it moves it a great deal:
10.6x on B9 full, to machine-precision agreement. It also found that the
preconditioner ranking INVERTS between the 2D and 3D unstructured cores,
and that both ask for the wrong one in 2D. See
`M31-P5-1-SOLVER-SELECTION-PLAN.md`, which is now the recommended next
milestone ahead of P5b.

## 12. The re-decision -- M31 P5-1 LANDED, exit criterion invoked (2026-09-10)

M31 P5-1 (all 5 phases) landed the same day as this note, making
`linsolve="auto"` reachable from `NewtonOptions` -- Phase D's own
evidence-based selection, not a guess (see that plan's section 4).
Section 9 above named the exact trigger to watch: *"if P5-0 lands and a
re-run of B8/B9 does not move assembly into a position where porting it
is worth a second engine, P5 stops after P5-0 and P5a."* That re-run has
now been done, through the real M32 harness
(`benchmarks/p5_redecision.py`, `cases.py`'s `_b4`/`_b8`/`_b9` gaining an
optional `opts=` parameter for exactly this, default `None` reproducing
the dashboard's own row bit-for-bit -- confirmed via
`tests/test_m32_benchmarks.py` unchanged), not hand-extrapolated:

| case | assembly_s | linsolve_s | total_s | **assembly %** | `auto` resolved to |
|---|---|---|---|---|---|
| B8 full | 0.187 s | 3.147 s | 3.425 s | **5.45%** (was 3.5%) | `direct` (B8's own measured winner -- unchanged from before P5-1) |
| B9 full | 0.109 s | 0.500 s | 0.665 s | **16.33%** (was 1.5%) | `petsc` -- 11x faster than direct |

(Best-of-5 repeats, matching `harness.run_case`'s own "best wall time,
not the mean" convention. A real, separate finding surfaced taking
repeats at all: B9's petsc path pays a one-time ~1s initialization cost
on its FIRST call in a process -- repeat 1 took 1.49s, repeats 2-5
495-525ms -- which is not assembly, not the algorithm, and would have
overstated the case for OR against porting if a single cold measurement
had been quoted either way.)

**This is the "percentage rises because the rest got faster" trap named
in section 6.2's own last paragraph, now measured rather than
predicted.** B9's assembly share went up 11x (1.5% -> 16.3%) while its
ABSOLUTE cost did not move a millisecond (112.1ms before, 108.6ms now,
within measurement noise) -- the entire rise is P5-1 shrinking
everything else around it by 11x. B8, where `auto` measured `direct` as
the winner and therefore changes nothing about B8's own total, shows the
same share (3.5% -> 5.45%) moving only slightly, from run-to-run
variance, not from a real shift -- consistent with the reasoning above.

**The decision, applying section 9's own pre-committed rule:**

* **B8: no change, no case.** `auto` picked `direct`; B8's total is
  unchanged; 5.45% is not different in kind from the 3.5-8.9% this plan
  already judged insufficient. Nothing here moves it.
* **B9: the share crossed further into "worth asking about" territory
  than section 9 anticipated (16.3% vs. an original 1.5-4.8% range),
  but the ABSOLUTE number does not support porting anyway.** The most a
  perfect (zero-cost) C++ assembler could save on B9 is its own 108.6ms,
  taking 665ms to ~556ms -- and a real port would not be free, so the
  realistic saving (a kernel like this, not the scatter-heavy pattern
  P5-0 already fixed) is more plausibly a fraction of that. Weighed
  against section 10's own named cost -- "every future change to
  unstructured DD physics lands twice until P9" -- a savings measured in
  tens of milliseconds on an already-sub-second solve does not clear
  that bar.

**P5 stops after P5-0, per section 9's own advance commitment.** P5a-P5e
(the C++ assembler itself) are NOT started. What is banked, exactly as
section 9 anticipated: the unstructured cores reaching the PETSc stack
for the first time (P5-0), and now considerably more -- `precond`/
`block_size` exposed and validated (P5-1 Phase B), fallback parity
across all four unstructured Newton loops (P5-1 Phase C), and a
evidence-gated `linsolve="auto"` (P5-1 Phase D/E) that already delivers
B9's 11x with no C++ and no bit-identity budget spent. The parent plan's
dissent section should be updated to record that the dissent was upheld
a second time, now with the P5-1-informed number rather than the
P5-0-informed one. P6-P9 should be re-planned without a C++ unstructured
assembly layer under them, matching section 9's own stated consequence.

This is not a claim that C++ assembly is worthless everywhere in this
tree -- B4 (structured 3D equilibrium, out of THIS plan's scope by its
own section 8 sign-off statement: "unstructured path only, structured
cores untouched") shows the identical dynamic even more sharply
(assembly 0.149s of a 0.505s `auto`-resolved total, 29.5%, up from an
implicit <0.1% under `direct`'s 179s). If a structured C++ assembler is
ever proposed, it should be proposed and measured on its own terms, not
smuggled in under this plan's now-closed scope.

