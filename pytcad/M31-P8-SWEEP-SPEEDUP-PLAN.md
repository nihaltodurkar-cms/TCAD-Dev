# M31 P8 -- Sweep speedup: measure first, this time

Status: **CLOSED, no code change -- both gates run, both say stop.**
Written 2026-09-14 after three prior same-session experiments each
failed to find a win; sections 1 and 2's gates were then actually
executed the same day (not left as a future TODO) and both came back
negative, by the plan's own pre-committed criteria. No code has been
touched; `pytcad/core/`, `pytcad/linsolve.py` and `gui/services/
solver_runner.py` are all at their last-committed state. This is the
outcome section 3 explicitly anticipated as legitimate: there is
nothing worth chasing on the linear-solve side of Sweep, evidenced
rather than assumed.

Governing: `Architecture_Master_Plan.md` section 36 (no performance
claim without a benchmark table) and section 37 (progressive
extraction, not a rewrite). Parent: `M31-CPP-ARCHITECTURE-PLAN.md`.

## 0. What was already tried this session, and why each failed

Three ideas, each measured on real matrices from this codebase's own
`benchmarks/cases.py` fixtures, not synthetic ones. All three are
**closed**, not just untried:

1. **Persistent PETSc `KSP`/`PC` across calls** (reuse the compiled
   `method="petsc"` backend's Mat/KSP/PC instead of rebuilding every
   Newton iterate). Measured on B9 (3D unstructured coupled DD, the one
   real case where `auto` picks `"petsc"`): the current preconditioner
   (`PCPBJACOBI`) has near-zero symbolic setup cost to amortize -- a
   *correct* implementation of this idea would save nothing. A first
   Python prototype was also outright buggy (wrong answers); a proper
   C++ `PersistentKspSolver` was then built, hit a SEPARATE, deeper
   correctness bug (silently wrong answers on the real 2889-row device
   Jacobian despite passing every synthetic/random-matrix test -- see
   the session transcript for the debugging trail: `MatMult` inside
   PETSc reported a tiny residual for an `x` that NumPy, given the
   identical `A`/`b` by every norm check, said was wrong by 6 orders of
   magnitude). **The C++ was reverted in full** rather than left in the
   tree half-working. Do not re-attempt this exact approach without
   first understanding that specific inconsistency -- it smells like a
   real PETSc/MatSetValues-after-preallocation interaction this session
   did not get to the bottom of, not a shallow typo.
2. **Preconditioner lagging** (reuse the last Newton iterate's
   node-block-Jacobi preconditioner for 2-5 iterates instead of
   rebuilding every one). Measured on B8 (2D unstructured coupled DD)
   at the exact 34,023-DOF scale `linsolve.py`'s own evidence table
   cites for its "93% of every call is preconditioner setup" claim:
   that claim **does not reproduce today** (measured build fraction:
   0.5%, not 93%; the real cost is 1882 GMRES iterations of raw
   matvec+orthogonalization). Lagging made every configuration tried
   monotonically SLOWER (114s baseline vs 130-169s lagged), because the
   small setup saved was outweighed by a worse-quality preconditioner
   needing more iterations.
3. **Compiling `_residual_jacobian`'s assembly into C++.** Not even
   attempted this session -- `M31-P5-ASSEMBLY-NEWTON-PLAN.md` section 9
   already tried exactly this and stopped on its own pre-committed exit
   criterion (section 12, 2026-09-10): assembly's ABSOLUTE cost stayed
   flat (~109ms) even as its SHARE of total time rose 11x once P5-1's
   linear-solve speedups landed around it. A second engine's ongoing
   maintenance cost was judged not worth 109ms. **This is a closed
   door**, not an open opportunity -- do not re-propose it without new
   evidence that the 109ms figure has changed.

The common lesson across all three: this codebase's own `auto`
solver-selection evidence table (`linsolve._AUTO_EVIDENCE`) is already
fairly well-optimized for the matrix shapes it was measured against.
Guessing at a new "avoid redundant setup" trick and measuring it after
the fact has a 0-for-3 record this session. The plan below inverts
that order.

## 1. What was NEVER measured: does linear-solve time even dominate a
   real GUI Sweep? -- RUN 2026-09-14, RESULT: YES, but only at real 3D
   scale; NO at 1D/2D

Every measurement in section 0 used `benchmarks/cases.py`'s
Newton-loop-only harness (`solve_bias`/`solve_bias3d` called directly,
no subprocess, no GUI). **No one has profiled an actual GUI Sweep
click end to end** -- `gui/services/solver_runner.py`'s `run_sweep`,
driven from a real `DeviceSpec` through the real `JobRunner` subprocess
path, on a device size a user would actually build in the Structure
workbench.

A real Sweep's wall-clock time is NOT only Newton-iterate linear
solves. It also includes, per point: `apply_bias`'s warm-start Newton
loop (already warm-started, per `run_sweep`'s own docstring), residual/
Jacobian assembly (numpy, per section 0.3 above -- small but not
zero), `extract_result`'s per-point field extraction (numpy field
copies, unit conversions), and -- only for 3D -- per-point snapshot
field storage (`dev.psi_V`/`n_cm3`/`p_cm3` copies for the playback
dock). Plus, once per job rather than per point: subprocess startup,
`DeviceSpec` JSON parsing, mesh/device construction, and npz writing
at the end.

**This is Gate S1, and it is the FIRST thing to do, before proposing
any more solver-internals tricks:**

- Instrument `gui/services/solver_runner.py`'s `run_sweep` (a local
  timing dict around each labeled block: assembly, linear solve,
  extract_result, snapshot capture -- `time.perf_counter()`, no new
  dependency) for one representative real device at each
  dimensionality (a `pn_diode` template sweep, an `nmos` sweep, a
  `resistor_3d`-shaped 3D sweep at a size actually reachable from the
  GUI, e.g. 20-50k nodes).
- Report the wall-clock SHARE of each block, the same way
  `M31-P5-ASSEMBLY-NEWTON-PLAN.md` section 9's exit criterion is
  phrased (share AND absolute cost, not just one).
- **Exit criterion, decided in advance (the M31 P5 precedent this plan
  is following):** if linear-solve time is not the dominant share
  (say, comfortably >50%) of a real multi-point sweep at a realistic
  GUI size, STOP here. Chasing linear-solve microseconds while
  subprocess/JSON/npz overhead dominates would repeat exactly the
  mistake M31 P5 already corrected for once (measuring one engine in
  isolation rather than the thing a user actually waits on).

**RESULTS (measured 2026-09-14, `gui.services.solver_runner.run_job`
driven in-process, real `DeviceSpec`s, a real sweep on each):**

| device | nodes | total | linear solve | share |
|---|---|---|---|---|
| 1D diode (`diode_1d_example_spec`) | 240 | 0.075s | 0.0011s | 1.4% |
| 2D `pn_diode` template | ~3,200 (80x40) | 1.86s | 0.024s | 1.3% |
| 3D `resistor_3d_example_spec` (toy) | 768 | 0.30s | 0.204s | 69.0% |
| 3D `mosfet_3d_example_spec` (realistic) | ~15,800 | **82.1s** | **80.1s** | **97.6%** |

Decisive on both ends. 1D and every 2D sweep a user actually builds
from a template is dominated by fixed overhead (Python startup, mesh/
device construction, per-point orchestration) -- **total wall time is
already under 2 seconds**, so no linear-solve optimization would be
visible to a user there regardless of how much it saved. A realistic
3D device (the size this repo's own `mosfet_3d_example_spec` docstring
calls "realistic", not a stress test) is the opposite: linear solve is
97.6% of a genuinely slow 82-second sweep. **Gate S1 clears, but only
for structured 3D coupled bias -- section 2 below must target THAT
case specifically, not guess at which method it uses.**

One correction to the guess in the original (pre-measurement) version
of this plan: `select_auto`'s evidence table says `(3, False, True)`
(structured 3D coupled bias) resolves to `"gmres"`, so section 2 below
originally targeted `"direct"` reuse for 1D/2D instead. That guess was
overtaken by the OWN measurement above before it was ever acted on:
`gui/services/solver_runner.py`'s `run_job` never lets a job reach
`auto` at all -- it always sets `opts.linsolve` explicitly (`"direct"`
below its 20,000-node AMG/GPU threshold, `"bicgstab"`/`"gpu_direct"`
above it; see `run_job`'s own size-gate comment block). `mosfet_3d` at
~15,800 nodes sits BELOW that threshold, so its dominant 80 seconds is
plain `scipy.sparse.linalg.spsolve` (direct), confirmed directly:
capturing every `solve_linear` call during this exact sweep with a
`method="gmres"` filter caught zero calls, and a `method="direct"`
filter caught all 32. Section 2 was rewritten below to test the
`"direct"` case on THIS real workload rather than an assumed one.

## 2. Reusable symbolic factorization for `"direct"` -- RUN 2026-09-14,
   RESULT: NO, symbolic cost is 2.7% of the real thing, not the double
   digits the plan required before building anything

Gate S1 having landed on `"direct"`-method 3D structured coupled bias
as the actually-dominant case (not the 1D/2D guess the first draft of
this section made), the question became: for THIS real workload, is
enough of a direct solve spent on the reusable part (fill-reducing
ordering + symbolic analysis) to justify a persistent-factorization
wrapper?

**Gate S2, run 2026-09-14, on the real 32-call `method="direct"`
matrix sequence captured from `mosfet_3d_example_spec`'s own sweep**
(same job as section 1's table, ~15,800-node structured 3D Jacobians):
routed through PETSc's own `KSPPREONLY`+`PCLU` (not scipy) specifically
so the symbolic/numeric split could be read from PETSc's own internal,
already-instrumented event log (`MatLUFactorSym`/`MatLUFactorNum`) via
`PETSc.Log.begin()` -- a real per-call breakdown, not an estimate.

| event | total time (32 calls) | share |
|---|---|---|
| `MatLUFactorSym` (reusable across same-sparsity solves) | 13.92s | 2.7% |
| `MatLUFactorNum` (NOT reusable -- redone every Newton iterate) | 499.83s | 97.3% |
| `KSPSolve` (triangular solves once factored) | 1.06s | -- |

All 32 solves verified correct (residual 4e-16 to 1e-14 against the
real `A`, `b` pair). **The plan's own pre-committed bar (section 2,
original wording: "a real double-digit percentage") is not cleared --
2.7% is nowhere close.** This is the expected, textbook result for a
genuinely 3D structured Jacobian: unlike a 2D mesh, 3D fill-in under
LU is severe, so the FLOP-bound numeric factorization dominates a
sparse direct solve's cost by nearly two orders of magnitude over the
one-time graph-ordering step. There is nothing to amortize by keeping
a symbolic factorization alive across a sweep's Newton iterates --
each one pays for genuinely new floating-point work regardless.

**Per section 4's own order of work, this closes the plan: STOP. Do
not build `PersistentDirectSolver`.**

(Side observation, not actionable here: PETSc's own default `PCLU`
took ~16s per solve on this matrix, vs. `scipy.sparse.linalg.spsolve`'s
~2.5s/call inside the real job -- PETSc's serial LU is markedly slower
than SuperLU for this exact problem, most likely ordering-quality
related. That is a live discrepancy worth knowing about if `"petsc"`
or a `PCLU`-based method is ever considered for THIS shape of matrix,
but it does not change section 2's own conclusion, which was about the
sym/num SPLIT, not absolute engine speed.)

## 3. What was originally section 2, kept for the record (superseded
   by the measured section above)

The original (pre-measurement) draft of this section proposed the same
idea -- reusable symbolic factorization for `"direct"` -- but aimed at
`(1, False, True)`/`(2, False, True)` (1D and structured-2D coupled
bias), reasoning from `select_auto`'s evidence table alone rather than
a measurement of what a real Sweep actually spends time on. Section 1's
own results made that target moot before it was ever tested: 1D/2D
sweeps are not solver-bound at all (1.3-1.4% share, sub-2-second total
times) -- there was never anything to gain there regardless of the
symbolic/numeric split, which is why section 2 above re-aimed at the
workload Gate S1 actually found dominant instead of the one this
paragraph guessed. Left here as a record of the correction, not a
second open item.

## 4. Honest limits, stated up front

- This plan does not promise a speedup, and in the end did not find
  one -- both gates it proposed were run the same day they were
  written, and both closed. That is the legitimate, useful outcome
  section 3 (in its original, pre-measurement wording) anticipated,
  not a failure to write up.
- Section 2's dead end is specific to the case actually measured
  (structured 3D coupled bias, `method="direct"`, below the 20,000-
  node AMG/GPU threshold). It says nothing about `"gmres"` (already a
  dead end in section 0.2, on a different cell) or `"petsc"` (dead end
  in section 0.1) either, so no combination examined this session has
  a viable "reuse the setup" win.
- No claim here is to be quoted in a commit message or another plan
  doc until it has a benchmark-run number behind it (section 36's
  rule) -- every number in sections 0-2 is backed
  by a real run, and they are all negative results.

## 5. Order of work, and how it actually went

1. Gate S1 (section 1): instrument and measure a real end-to-end GUI
   Sweep at 1D, structured 2D, and structured 3D. Report shares. --
   DONE 2026-09-14: 1D/2D not solver-bound at all; structured 3D at a
   realistic size is 97.6% solver time, dominant case identified as
   `method="direct"` (not the `"gmres"` the plan's first draft guessed).
2. Decide, from S1's own numbers: stop here, or proceed to Gate S2. --
   proceeded, retargeted at the measured case.
3. Gate S2 (section 2): measure the symbolic-vs-numeric split via
   petsc4py's PCLU event log on the REAL captured `mosfet_3d` matrix
   sequence. Report the split. -- DONE 2026-09-14: 2.7% symbolic, 97.3%
   numeric.
4. Decide, from S2's own numbers: stop here, or scope the
   `PersistentDirectSolver` C++ work as its own follow-up slice. --
   STOPPED. 2.7% does not clear the pre-committed double-digit bar.
   No C++ work scoped; none should be, absent new evidence that this
   ratio has changed (e.g. a device shape with dramatically less 3D
   fill-in, which is not a realistic near-term case).
