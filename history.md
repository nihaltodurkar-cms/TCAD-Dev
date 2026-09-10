# PROJECT HISTORY -- handoff for the next session

Read this + `CLAUDE.md` + `ARCHITECTURE.md` + `SENTAURUS-PARITY-PLAN.md`
before doing anything.

**What this file is.** A compacted record of what was built, what broke,
and what is still open -- kept at the level a new session needs to avoid
re-deriving decisions or re-making mistakes. It is deliberately NOT a
per-session diary; it was one, for 4,065 lines, and the duplication was
costing more than it carried. The full narrative of every session
remains in `git log` and in the per-milestone plan documents.

**Where the detail lives.** Each milestone below names its plan document.
Those documents are the authority on gates, formulas and honest limits;
this file only carries what a reader needs *before* opening one.

> **Caveat, 2026-09-09:** 13 plan documents (`M14`-`M22`,
> `3D-VISUALIZATION-PLAN.md`, `GUI-IMPROVEMENT-PLAN.md`,
> `M21-PHASE3-MESHING-PLAN.md`, and a session transcript) are currently
> **deleted from the working tree** and exist only in `HEAD`. Until they
> are restored (`git checkout -- <path>`), the milestone entries below
> are the only in-tree record for those milestones. Restore them before
> relying on a "see the plan doc" pointer.

---

## AIM

Evolve PyTCAD into a Semiconductor Workbench: an open, modular,
understandable learning+research TCAD environment (DEVSIM/Silvaco/
Sentaurus class). REAL physics only -- every educational surface backed
by actual computation. Never fake, never mock, never weaken tests.

---

## CURRENT STATE (2026-09-10)

**Suite, run both ways per CLAUDE.md:**

| run | result |
|---|---|
| fast, compiled kernels (`PYTCAD_ACCEL=1`) | 1589 passed, 2 skipped, 1 xfailed, 39 warnings |
| fast, pure Python (`PYTCAD_ACCEL=0`) | 1581 passed, 10 skipped, 1 xfailed, 39 warnings |

(the 2026-09-09 figures were 1444/1436, and the pre-M38 figures were
1548/1556; the +33 is M38's gate file. Everything before that: M32's 19
gates, P4b's 25, 6 benchmark/harness gates, P5-0's 18 and P5-1's 45
across phases B/C/D. The slow battery and `test_accel_parity.py` were
last run at P4 -- 25 passed and 55 passed -- and have not been re-run
since; neither M31 P5-1 nor M38 touches a compiled kernel.)

The 8-test gap between the two fast runs is exactly the PETSc
backend-vs-backend gates, which need both backends present.

**The single xfail is M14 G-A** (Lombardi phonon constants `B_n`/`B_p`,
blocked on a paywalled 1988 paper -- see the M14 entry). There are no
failures anywhere.

**Working tree is UNCOMMITTED.** Nothing has been pushed.

### 2026-09-10 -- M38 PHASES 1-3 LANDED (TCAD-to-SPICE extraction)

Plan and every measured number: `pytcad/M38-COMPACT-MODEL-PLAN.md`
(section 5 for results, 5b for the two real findings). Chosen as the
next milestone because `ARCHITECTURE.md` 4c.3's own cheapest-payoff
ordering reads `M32 -> M38 -> M33 -> M34` and M32 had just landed --
and because every ingredient already existed: `circuit.py`'s `Diode`
and `MOSFET1` are the models fitted INTO, `circuit.Circuit` is the
simulator the loop closes through, `calibration.py` supplied the
Nelder-Mead/finite-penalty shape, and `mosfet.build_mosfet` /
`Device1D.iv_sweep` supplied the reference curves.

**NO FROZEN-CORE EDIT.** Two new files only: `workbench/compact.py`
(616 lines) and `tests/test_m38_compact_model.py` (33 gates). In
particular `pytcad/mosfet.py` has an `id_vg_sweep` but no
`id_vd_sweep`; rather than amend a `pytcad/*.py` file under the M11-S3
mechanism for a bare `solve_bias` loop, the Id-Vd family driver lives
in the test and drives `Device2D` from outside, the pattern
`transient.py`/`continuation.py` established.

What it does: fits `circuit.Diode`'s (Is, N) and `circuit.MOSFET1`'s
(Vt0, kp*W_L, lambda) to a simulated I-V, emits a real SPICE `.MODEL`
card, reads it back, and re-simulates through `circuit.Circuit`'s own
MNA solver -- TCAD -> parameters -> netlist text -> parameters ->
circuit simulation -> back to the originating curve, with no external
SPICE and no network.

Headline measured numbers:

* **Real `Device1D` pn diode**: ideality **N = 1.0031**, log-space
  residual 1.57e-3. Independently corroborated -- `test_validation.py`
  already gates the SAME fixture's POINTWISE ideality to within 2% of
  1.0 above 0.3 V.
* **Real 2D `Device2D` MOSFET**: level-1 fit at **2.90% relative RMS**
  across 19 points spanning triode and saturation, with
  **Vt0 = 0.16883 V** against **0.16730 V** from the closed-form
  long-channel `Vfb + 2*phi_f + Qdep/Cox` built out of
  `moscap.flatband_voltage` and `materials.SILICON` -- **0.91%**, and
  the two share no code.

Two real findings from the hard-debug pass, both now permanent gates:

1. **`circuit.Circuit` shunts every node to ground through 1e-12 S**
   (its floating-node guard). Any terminal current below ~`1e-12 * V`
   amperes is dominated by it: a 1e-4 cm^2 diode at 0.25 V passes
   2.5e-14 A against 2.5e-13 A of guard leakage, a **10x** error that
   first read as a broken fit. The closed-loop gate now asserts a
   PREDICTION -- the only permitted discrepancy is exactly
   `MNA_LEAKAGE_G * V / I` -- so an error from any other cause still
   fails it even where the guard is large. `mna_resolvable()` exposes
   the floor at the API and one gate demonstrates it live.
2. **A pointwise-derivative ELR tangent is not noise-robust.** Taking
   the threshold tangent at the single `argmax(np.gradient(...))` point
   moved the extracted Vt0 by **0.6 V** under 5% multiplicative noise
   -- far enough to trip the extractor's own strong-inversion refusal
   on data it can actually handle. Now a least-squares fit over every
   point within 80% of peak gm: exact on a noiseless level-1 curve
   (gm is constant, so the plateau is the whole curve), and 2.6% / 2.0%
   / 2.7% on Vt0 / kp*W_L / lambda at 5% noise.

Honest limits, written into the plan and the module docstring BEFORE
implementation rather than discovered: `MOSFET1` has no subthreshold
conduction at all (Id is EXACTLY 0 below threshold), so the fit is
strong-inversion-only, REFUSES a window that crosses threshold, and
reports linear-space relative error -- never a log-space figure that
would imply subthreshold agreement the model cannot have. It also has
no body effect. And the three layers disagree on units (A/cm^2 vs A/cm
vs A), so every extractor takes its scaling factor as a REQUIRED
argument with no default.

Deliberately NOT claimed: any speedup from replacing `DeviceStamp`'s
two full `Device1D.solve_bias` calls per Newton iteration with a cheap
analytic element. It is real, but section 36 forbids a number that did
not come from a benchmark run; it earns a `benchmarks/cases.py` row or
it is not quoted.

Suite green BOTH ways after the change: `PYTCAD_ACCEL=0` 1581 passed /
10 skipped / 1 xfailed, `PYTCAD_ACCEL=1` 1589 passed / 2 skipped /
1 xfailed, 39 warnings and zero failures in both -- the pre-M38
baselines (1548/1556) plus exactly M38's 33 gates, warning count
unchanged.

### 2026-09-10 -- M31 P5-0 LANDED; P5 proper planned, not approved

**P5-0 landed** (`M31-P5-ASSEMBLY-NEWTON-PLAN.md` section 11 is the full
record, including the amendment record). Two Python-side changes to the
four unstructured Newton loops, no C++, no physics change:

* `dirichlet.stamp_dirichlet_rows` replaces the `J.tolil()` +
  LIL-row-assignment stamping -- **byte-identical** (indptr, indices AND
  data), **44.8x** faster on the step itself (115.4 ms -> 2.6 ms per
  Newton iteration at B8 full size).
* the update goes through `linsolve.solve_linear`, so
  `NewtonOptions.linsolve` -- and M22's Krylov methods and P3a/P3b's
  PETSc stack -- **reach these cores at all**. They called `spsolve`
  directly before and silently ignored the option.
* a second substitution rode along in the 3D loops (a gate's Robin
  coupling accumulated into a diagonal instead of stamped entry by entry
  through LIL) and is gated separately, including the shared-node
  wrap-around case.

Measured same-session A/B, full size: **B8 5.15 s -> 3.61 s (1.43x)**,
B9 7.96 s -> 7.56 s (1.05x -- its remainder was only 7%, the direct
solve is 91% of it). B8's non-assembly, non-solve remainder went 35% ->
2.7%. **All ten goldens byte-identical**, m13 digests unchanged; 18 new
gates in `tests/test_m31_p50_unstructured_linsolve.py`.

Two things worth carrying forward:

1. **P5-0 weakens the case for P5 proper rather than clearing the way.**
   The linear solve is now 92% of B8 full and 98% of B9 full; the C++
   assembler would be porting ~5%. The next experiment is
   `opts.linsolve="petsc"` on these cores -- now possible, and
   Python-side.
2. Routing through `solve_linear` broke M32's instrumentation (the cores
   `from .linsolve import solve_linear`, so patching
   `pytcad.linsolve.solve_linear` misses them). **The existing M32 gate
   caught it** -- `test_case_runs_and_reports_a_real_measurement`
   asserts `linsolve_calls > 0` -- before any number was quoted.

### 2026-09-10 -- M31 P5 planned, and its prerequisites landed

Written, not started, NOT APPROVED: `pytcad/M31-P5-ASSEMBLY-NEWTON-PLAN.md`.
Scope proposed there is the UNSTRUCTURED path only
(`unstructured_poisson.py`, `unstructured_dd.py`, `unstructured_dd3d.py`);
the structured cores stay Python. It needs the section-3 scope sign-off
and the section-8 amendment record before any core edit.

Landed this session (none of it touches the frozen core):

* **B8 and B9** -- 2D and 3D unstructured DD benchmark cases. Before
  them the code P5 targets had no dashboard row, so section 36 forbade
  any claim about it.
* **The profile P5 was waiting for**, and it is not encouraging for the
  C++ case: assembly is 3.5% of B8 full and **1.5%** of B9 full, and its
  share FALLS with problem size; the linear solve is 62-91%. The
  unstructured cores call `spsolve` directly and cannot reach P3a/P3b's
  PETSc stack at all. That created a new Python-side sub-phase (P5-0)
  which addresses ~90% of the runtime with no C++.
* **A tracemalloc defect in M32's harness**: the memory trace ran over
  the whole measured region, inflating wall time 1.19x on B3 but 4.05x
  on B8 -- worst exactly on the code P5 would be judged by. Timing and
  memory repeats are now separate. **Every M32 number published before
  2026-09-10 was inflated**; `BASELINE.md`/`FULL.md` are regenerated.
  Also fixed: `unstructured_dd3d` was missing from the `spsolve` patch
  list, and the unstructured module-level assemblers were not
  instrumented at all.
* **The impossible golden rule is gone.** "Goldens committed before the
  edit" cannot be satisfied (`.gitignore` excludes `*.npz`) and should
  not be -- a golden pins one machine's summation order. CLAUDE.md now
  specifies reconstruct-and-compare as four numbered steps; this file
  and ARCHITECTURE.md match, and `.gitignore` records why
  `tests/goldens/**` stays ignored.

**Environment (load-bearing, not a preference).** Run everything through
`conda run -n TCAD`. This machine's `base` anaconda env has an
ABI-mismatched Qt6 (`undefined symbol: _ZN14QObjectPrivateC2E16QtPrivate_6_11_0`)
that fails EVERY `gui/tests/*` QML test with "Main.qml failed to load",
independent of any code change -- confirmed by `git stash` reproducing
it on unmodified code. It fabricates ~90 GUI failures and has cost a
session already.

Cap workers at `-n 6` (not `-n auto`) and set `OPENBLAS_NUM_THREADS=1`:
numpy's BLAS otherwise spawns a thread pool PER xdist worker.

---

## OPEN ITEMS

0. **M31 P5-1 (linear-solver / preconditioner selection) is the
   recommended next milestone**, ahead of P5 proper --
   `pytcad/M31-P5-1-SOLVER-SELECTION-PLAN.md` -- **ALL FIVE PHASES (A-E)
   LANDED 2026-09-10.** Phase A's real per-solve numbers
   (not single-Jacobian extrapolations) moved the milestone's center of
   gravity: **B4 (3D structured equilibrium, Poisson-only) is the
   largest result in the whole study -- 179s direct -> 1.5-2.2s
   iterative, 82x-119x, every one of 9 Newton iterates converging with
   ZERO fallbacks needed.** B9 (3D unstructured) confirms the original
   10.6x petsc finding independently under a full Newton sequence. But
   **B8 (2D unstructured) turned out to have NO measured win**: the
   single-Jacobian sweep that motivated this milestone favored "ILU"
   (3-4 Krylov iterations), but the WHOLE-SOLVE number shows
   preconditioner SETUP cost (93% of every call, isolated and timed
   directly -- and it is `pyamg`'s AMG hierarchy construction on this
   machine, not literal `spilu`, since `_build_preconditioner` tries
   AMG first when installed) makes it slower than direct (8.41s vs
   3.43s) -- direct stays for B8, measured rather than assumed. A real
   methodology bug was caught and fixed along the way:
   scipy's `gmres`+`restart` treats `maxiter` as restart-cycle count
   (an effective ~100x larger budget than the same `maxiter` gives
   `bicgstab`/`petsc`), which had made two B8 configs look like near-
   total failures when they were actually iteration-starved; corrected
   in the plan and permanently documented in
   `benchmarks/preconditioners.py` (the new Phase A sweep script) so it
   isn't repeated. **Phase B landed same day**: `NewtonOptions` gained
   `precond`/`block_size` fields (defaults reproduce the old hardcoding
   exactly), threaded into the five coupled call sites that hardcoded
   `block_size=3` (`device.py`, `device2d.py`, `device3d.py`,
   `unstructured_dd.py`, `unstructured_dd3d.py`); both fields validated
   at construction (`ValueError` on an unknown `precond` or a
   nonsensical `block_size`, mirroring `Models.driving_force`'s
   existing refuse-don't-ignore pattern). Reconstruct-and-compare
   confirmed bit-identity: all 6 `tests/goldens/m13/*.npz` files came
   back md5-identical after the edit, including `frozen_meshes.npz`,
   which an over-eager `rm -f` deleted before regenerating (a real
   process mistake, not part of the plan) and had to be rebuilt from
   the `graded_mesh()`/`np.linspace()` conventions documented in
   `test_m13_goldens.py`'s own docstring -- the rebuild reproduced the
   original file byte-for-byte. New gate file
   `tests/test_m31_p51_phase_b.py` (22 gates). Suite green both ways
   (`PYTCAD_ACCEL=0`: 1503 passed/10 skipped/1 xfailed;
   `PYTCAD_ACCEL=1`: 1533 passed/2 skipped/1 xfailed; 39 warnings both,
   zero failures). **Phase C landed same day**: all four unstructured
   loops (`unstructured_poisson.solve_poisson_equilibrium`,
   `unstructured_dd.solve_bias`, and both loops in
   `unstructured_dd3d.py`) gained the identical try/except fallback
   shape the structured cores already used, plus a `linsolve_fallbacks`
   count in each returned dict (zero by default). Confirmed with
   `tests/test_m31_p51_phase_c.py` (6 gates): a 100%-forced fallback
   produces a result `np.array_equal` to the all-direct solve, for all
   four loops, and the fallback count is nonzero when it happens.
   **A real regression caught before it stuck**: Phase B's own test
   file originally forwarded a mismatched `block_size=7` to a genuinely
   REQUESTED iterative method, which made scipy's `gmres` actually
   grind through real (failing) iterations -- ballooning the combined
   P5-0/P5-1 test files from ~15s to over 600s. Fixed by having the spy
   record the request but always execute via `method="direct"`; full
   suite re-timed clean (`PYTCAD_ACCEL=0`: 1531/10/1 in 345.6s;
   `PYTCAD_ACCEL=1`: 1539/2/1 in 346.4s, 39 warnings both, zero
   failures -- matching the pre-Phase-C timing shape, not the
   regression). **Phases D and E landed same day, completing the
   plan.** `linsolve.select_auto(dim, unstructured, coupled, dof)`
   resolves `NewtonOptions.linsolve="auto"` from a 3-entry evidence
   table keyed on exactly what Phase A measured (B4 -> petsc >=4,913
   DOF, B9 -> petsc >=2,889 DOF, B8 -> direct, explicitly MEASURED not
   merely absent); every other `(dim, unstructured, coupled)` --
   notably ALL of 1D, every 2D/3D STRUCTURED coupled-bias
   configuration, and both scalar unstructured equilibrium paths --
   refuses to direct with a reason naming the absence (Gate D-3). Wired
   into all 9 call sites that dispatch on `opts.linsolve`; two
   (`Device1D`/`Device2D`'s `solve_equilibrium`) left untouched because
   they already hardcode `method="direct"` and never read
   `opts.linsolve` at all. `tests/test_m31_p51_phase_d.py` (17 gates)
   includes two real end-to-end checks beyond the lookup table: `auto`
   on a 5,832-DOF `Device3D` resolves to petsc and agrees with direct
   to `<=1e-14`; `auto` on a full-size B9-shaped 3D unstructured mesh
   resolves to petsc and agrees with direct to `<=1e-12`. Reconstruct-
   and-compare: all 6 `tests/goldens/m13/*.npz` md5-identical again --
   the default stays `"direct"` everywhere (**Phase E landed as
   E-opt-in**, requiring no new code beyond documenting the "auto"
   contract on `NewtonOptions.linsolve` itself; **E-auto -- changing
   the default -- was deliberately NOT taken**, per the plan's own
   written guardrail that it needs separate sign-off and more measured
   evidence than three cells currently cover).
1. **M31 P5** (the C++ assembler) has its own plan doc,
   `pytcad/M31-P5-ASSEMBLY-NEWTON-PLAN.md` -- **CLOSED 2026-09-10: P5-0
   landed, P5a-P5e STOPPED, not started** (below). The scope sign-off
   in its section 3 was never reached -- section 9's own pre-committed
   exit criterion fired first. The headline: the phase's own profile
   (section 6) said the assembler is 1.5-3.5% of a full-size
   unstructured solve. P5-0
   has since landed (section 11); after it the linear solve was 92-98%
   of these runtimes, which is what P5-1 above attacked -- P5-1 is now
   COMPLETE (all 5 phases), and **the decision is made: P5 STOPS after
   P5-0, per section 9's own pre-committed exit criterion, invoked
   2026-09-10 (section 12, measured through
   `benchmarks/p5_redecision.py` and the real M32 harness, not by
   hand)**. B8 full (auto picks direct, unchanged): assembly 5.45% of
   3.43s, no case. B9 full (auto picks petsc, 11x): assembly's SHARE
   rose to 16.3% of a 0.665s total (from 1.5% of 7.32s) while its
   ABSOLUTE cost stayed at ~109ms -- exactly the "percentage rises
   because the rest got faster" trap both plans warned against, now
   measured rather than predicted, and the absolute number (at most
   ~109ms saveable, realistically less) does not clear the bar against
   two engines' ongoing maintenance cost. P5a-P5e (the C++ assembler)
   are NOT started; `cases.py`'s `_b4`/`_b8`/`_b9` gained an optional
   `opts=` parameter for this measurement (default `None` reproduces
   the dashboard row exactly, confirmed unchanged by
   `tests/test_m32_benchmarks.py`). A related, out-of-scope finding: B4
   (structured 3D, not a P5-1 target) shows the same dynamic even more
   sharply -- assembly 29.5% of a 0.505s `auto`-resolved total -- worth
   a separate proposal if a structured C++ assembler is ever considered,
   not smuggled into this now-closed decision.

   **P5's closure propagated to `ARCHITECTURE.md`** (2026-09-10): the
   4c.3 spine STATUS line, the C++-gated milestone list (M36/M39
   flagged for re-scoping against the Python+PETSc stack P5-0/P5-1
   actually built, since the C++ assembler they depended on will not
   exist), and the adjoint-readiness section (M47 re-anchored to P4b's
   Python-path fix rather than a P5 acceptance gate that will never be
   evaluated) were all updated so a future reader does not plan against
   a P5 that stopped.

2. **P2/P3b/P4's hand-taken headline numbers -- RE-MEASURED 2026-09-10**
   through `benchmarks/p2_p3b_p4_remeasure.py` (M32-BENCHMARK-PLAN.md
   section 7's first open item, "doubly owed" after the tracemalloc
   fix), reusing `test_accel_parity.py`'s own fixture builders so this
   measures the exact thing the throughput-floor gates protect. Every
   number held up or exceeded the original: P2's 3 kernels (41x/25x/539x
   -> 43x/26x/560x), P3b's timing comparison (3.30ms/3.38ms ->
   3.31ms/3.38ms, same 399 iterations, confirms "no speedup expected"
   exactly), P4's 3 indicator kernels (835x/874x/123x ->
   1081x/939x/221x -- `indicator_log_density_tri` notably higher).
   `M31-CPP-ARCHITECTURE-PLAN.md`'s P2/P3b/P4 sections updated with both
   figures side by side. P4's two diffusion-loop kernels
   (`process.diffuse_numeric`, `ted.diffuse_with_defects`) needed a
   second script since wall-clock time for a timestep loop isn't a
   throughput rate -- **also RE-MEASURED 2026-09-10**,
   `benchmarks/p4_diffusion_remeasure.py`, same n=4000/t_s=1800s shape
   as the original claim, reusing `test_accel_parity.py`'s
   `_diffusion_case` implant profile. Speedup held up across two
   repeats: 3.3-3.7x (orig 3.3x) for `diffuse_numeric`, 4.4-4.5x (orig
   4.1x) for `diffuse_with_defects`. Absolute seconds are not claimed
   comparable to the original run (13.6-14.2s vs. the original's 24.6s)
   since the original's exact TED/OED enhancement parameters were never
   recorded -- only the speedup ratio is checkable against the prior
   claim, and it is. `tests/goldens/m14/` (an empty, untracked,
   unreferenced directory -- confirmed via grep across `tests/` and
   `pytcad/`) was also removed the same session as a small cleanup item.
3. **M14 G-A** -- blocked on external material, not effort. Two sessions
   searched (COMSOL docs, Sentaurus/Silvaco manuals, Prophet, TU Wien,
   CERN, ResearchGate, academia.edu, web.archive.org); Unpaywall
   confirms DOI 10.1109/43.9186 has zero open-access copies. Needs
   either institutional access to Lombardi 1988 or a Sentaurus/Silvaco
   manual PDF. Switching to the Darwish (1997) model that DEVSIM uses is
   a real option but a bigger decision than filling in a constant.
4. **The 13 deleted plan documents** (see the caveat at the top).
   **`Architecture_Master_Plan.md` joined them on 2026-09-10**, and
   `AGENTS.md` was renamed to `CLAUDE.md` the same day -- both at the
   user's direction. The master plan is cited by section number in
   CLAUDE.md, ARCHITECTURE.md, `M32-BENCHMARK-PLAN.md`, the P5 plan and
   several test/benchmark modules; those citations were LEFT IN PLACE
   because the sections are still the reasoning behind live gates.
   CLAUDE.md's header says where to read one
   (`git show a117d03:Architecture_Master_Plan.md`). Treat a citation as
   a pointer into git history, not a broken link.
5. **M32-M40** are PROPOSED in `ARCHITECTURE.md` 4c.2, not decided --
   nothing is committed until each has its own plan doc and gates.
   EXCEPT M32 (landed) and **M38, whose Phases 1-3 landed 2026-09-10**
   (`pytcad/M38-COMPACT-MODEL-PLAN.md`). M38 Phase 4 -- a GUI panel and
   a `workbench/workflow.py` deck statement -- is named in that plan
   and NOT started. Neither are BSIM-class models, temperature or
   geometry scaling, or AC/C-V parameter extraction.
6. **Not started, and worth knowing about before picking the next
   item:** M31 P5-1's `E-auto` (making `linsolve="auto"` the DEFAULT
   rather than opt-in) is still deliberately untaken -- its plan's
   section 4 says it needs more of Phase A's matrix measured first,
   starting with `device3d.py`'s coupled `solve_bias` and structured
   1D/2D. The prize behind it is Phase A's largest number, B4's
   179 s -> 1.5 s, which no caller reaches today without typing an
   option they will not discover.
7. **Housekeeping still owed:** the working tree remains fully
   UNCOMMITTED, and the slow battery plus `tests/test_accel_parity.py`
   have not been re-run since P4.

---

## HARD RULES (never break)

- `pytcad/pytcad` numerical core: changes ONLY under the M11-S3-style
  amendment mechanism (sign-off recorded in the plan file, golden
  baseline recorded before the edit and proved recoverable afterwards
  -- reconstruct-and-compare, see CLAUDE.md's hard rules; goldens are
  machine-specific and are never committed -- FD-Jacobian-first,
  bit-identity off-path).
- Layering: QML -> controllers -> services -> QProcess subprocess -> npz
  -> ResultStore -> canvas. Controllers/visualization never import
  `pytcad`.
- `DeviceSpec` stays the wire format. Subprocess isolation per run kept.
- Every slice: suite green with pre-existing tests UNCHANGED, adversarial
  probe pass BEFORE commit, optional deps stay optional.
- Gate-bearing milestones block their dependents until ALL gates are
  green. "Mostly green" is a hidden failure.
- A failing test is never commented out or skipped. A visible
  `pytest.xfail` with the reason in the body is the honest version of
  "not yet, and here is why."

## HOW WE WORK

Plan -> user approves -> TDD (tests red first) -> implement -> hard debug
(fuzz/probe the new code adversarially, fix, regression tests) -> commit
(user pushes). Honesty over polish: report blockers, document limits.

---

## GOTCHAS LEARNED THE HARD WAY

Consolidated from every session. These each cost real debugging time.

### Verification discipline

- **A "COMPLETE, all gates green" status claim is not evidence.** It was
  wrong for M15 in an inherited tree, and M16/M20/M22-Schur all sat at
  "LANDED-PENDING-VERIFICATION" -- code and gates written, never once
  executed -- until a later session actually ran them and found real
  defects. Measure before trusting a status block, especially your own.
- **A formula that "reduces to the existing code at the default value"
  is not automatically a valid generalization.** If the reduction works
  by multiplying an already-satisfied residual by a constant, the
  parameter has no effect at ANY value. The tell is that it looks
  elegant (no branching needed). Always sweep a new parameter across
  several orders of magnitude and confirm the SOLUTION moves -- this
  caught the same class of bug twice in one session (D_it and S_n/S_p).
- **A test can be structurally incapable of failing.** T5's HEMT band
  step diffed `chi` along the axis it was constant on (always exactly
  0.0); M14's FD-Jacobian probes sampled random columns and never hit
  the handful of boundary columns where the bug was; a `if bv_solver is
  not None:` guard meant "BV not found" passed silently. Ask what the
  assertion would do if the physics were wrong.
- **Random full-matrix FD-Jacobian sampling misses boundary rows.**
  Probe the specific columns a change touches.

### Numerics

- **NaN fails every comparison**, so a `< MIN or > MAX` range guard lets
  it through silently. Check `np.isfinite` explicitly wherever a bound
  check is meant to reject bad input.
- **A lagged fixed-point loop that sources its next iterate from a
  quantity the current iterate already modified** can produce a RIGID,
  non-damping oscillation -- immune to under-relaxation at every damping
  factor -- and the capped result looks like ordinary finite data. When
  a warm-started outer loop won't converge under any damping, check
  whether its own just-updated state is feeding back into computing its
  next update before blaming the tolerance.
- **scipy's gmres default restart (20) can stall COMPLETELY** -- zero
  residual progress in 500 iterations -- on a stiff coupled Jacobian.
  Silent unless you check iteration counts.
- **`spilu` can raise "Factor is exactly singular" on a non-singular
  matrix**, purely because the default `drop_tol` is too aggressive for
  rows spanning many orders of magnitude (this codebase's scaled
  psi/n/p unknowns). A fallback tolerance chain is cheaper than
  re-diagnosing it each time.
- **`spsolve(A_csr, b)` and `spsolve(A_csr.tocsc(), b)` differ at
  ~1e-16.** SuperLU solves CSR natively via a format flag. Any
  bit-identity claim must not reformat the caller's matrix.
- The complete Fermi integral's Boltzmann-limit deviation is
  `e^eta/2^{3/2}` (exact Taylor series) -- set limit gates from the
  published math, not from round numbers.
- `mpmath`'s `mp.quad` on `[0, inf)` under-resolves the `t~eta` knee of
  the Fermi integral (5e-5 off at eta=40). Subdivide `[1, eta+20, inf]`.
  Audit your audit: scipy AND mpmath were both checked against the
  published Sommerfeld series.

### Arrays and shapes

- **A `meshgrid(indexing='ij')` array handed to something that reshapes
  to a different axis order is silent data corruption**, not a crash.
  numpy's flat `.reshape` only checks element count. With a doping array
  holding two distinct values the corruption is invisible under
  `print()` or `np.unique()` -- ~49% of nodes had the wrong value for
  their position and it only showed as spatial nonsense.
- `np.array(sorted({}), dtype=int)` has shape `(0,)`, not `(0, 2)`.
- numpy's `dtype=int` is C `long`: int64 on Linux, **int32 on Windows**.
  Pin any C boundary to int64 explicitly.

### Tooling

- **The bash tool's cwd RESETS between calls.** Always `cd` or pass
  absolute paths -- the single most common cause of lost work here.
- **`str.replace` patches SILENTLY no-op on stale strings.** Assert the
  replacement applied.
- **Writing a doc in two parts to the SAME path truncates it** -- the
  second write replaces the whole file.
- `np.polynomial.legendre.leggauss` is module-level (not
  `Legendre.leggauss`) in numpy 2.5.
- `familySweep.configureFamily`'s FIRST arg is the stepped contact NAME
  (a string), not a bool.
- `ViewportPanel.setViewMode` takes INTERNAL mode names ("series",
  "bands"), not display names ("Curves", "Bands").
- Qt's offscreen platform never incubates ListView/Repeater delegates
  without a real event loop -- call the controller method the delegate's
  signal handler would invoke.
- xhtml2pdf: `white-space:pre-wrap` on `<pre>` collapses newlines;
  `&sup6;` is not a real HTML entity and U+2076 is missing from the
  embedded font -- use `<sup>6</sup>`.

---

## MILESTONE LOG

Reverse chronological. Each entry: what landed, what broke and why, and
the honest limits.

### M31 -- C++ numerical engine (2026-09-09)

Plan: `pytcad/M31-CPP-ARCHITECTURE-PLAN.md`. Re-architecture toward C++
(numerical engine) + Python (API/workflows) + Qt (GUI) by progressive
extraction, **not** a rewrite. **P0, P1, P2, P2b, P3a, P3b and P4 have
landed; P5 is next.**

**The measurement that ordered the phases -- do not skip this.** The
premise "the numerics are Python, so port them for speed" is only partly
true here:

- Structured 3D assembly is **not** the bottleneck. A 24^3 equilibrium
  solve spends **98% of wall time in `_superlu.gssv`**; assembly is
  0.011 s of 0.494 s. Porting `device*.py`'s assembly buys ~2%.
- The direct-LU wall (3.0 s @ 8k nodes -> 51.8 s @ 27k -> 64k never
  completing) is **algorithmic, not linguistic**: the existing
  pure-Python node-block-Jacobi GMRES already does 68,921 nodes
  (206,763 unknowns) in 4.71 s.
- The genuine blocker was **unstructured mesh geometry**, at ~3.5k
  tets/s.

That is why P2 went first and P5 is last.

**The rule the whole migration rests on.** The extension is optional,
permanently. `pytcad/_accel.py` soft-imports `pytcad._core`; every
accelerated function keeps its pure-Python body as `_<name>_py`. Deleting
the `.so` must leave the full suite green (gate G-F). This is both the
undo button at every commit and what keeps an ORACLE alive to diff
against -- a port that deletes what it replaced cannot be checked.

**Gates every kernel clears:** G-A reference preservation
(`np.array_equal`, never `allclose`), G-B blast-radius (m13/m14 goldens
+ SHA-256 digests unmoved), G-C differential fuzz (identical exception
type AND message), G-D thread invariance, G-E absolute throughput floors,
G-F no-compiler fallback.

**P2 -- mesh/geom kernels.** `build_unstructured_stencil` 77k -> 3.16M
tri/s (41x); `build_unstructured_stencil3d` 48k -> 1.20M tet/s (25x);
`build_edge_flux_geometry3d` 3.7k -> 1.99M tet/s (**539x**). A
998,250-tet mesh builds its edge-flux geometry in 0.71 s against ~285 s
extrapolated. Bit-identity is achievable because the numpy primitives
involved were MEASURED to be plain scalar arithmetic at these sizes (no
BLAS dispatch) before any C++ was written -- see
`core/include/tcad/geom/simplex.hpp`'s preamble.

P1 removed `np.linalg.solve` from the geometry path for the same reason:
it routes to LAPACK `dgesv`, whose result depends on the BLAS build, so
C++ could not reproduce it. An unblocked `dgetf2` replication matched
numpy on only 72.6% of 20k random 3x3 systems. Replaced with a
fixed-order Cramer's rule, verified numerically neutral over 200k random
tetrahedra (worst equidistance violation 4.182e-10 vs 4.184e-10).

P1 also fixed a real latent bug: `DegenerateMeshError` was declared
**twice as two unrelated classes**, so an `except` on the 2D name
silently failed to catch the 3D module's error.

**P2b -- the winding-sensitivity defect.** P2 surfaced, and deliberately
did not fix, a defect in the REFERENCE: `_cot` divided by a *signed*
cross product while `tri_area` took `abs()`, so a clockwise-wound
non-obtuse triangle contributed NEGATIVE dual areas and the partition
identity failed by exactly 2x. Fixed on both paths at once (one line
each: `abs(cross)` / `std::fabs(cross)`).

The fix is right rather than a clamp because the angle at a vertex is
*undirected* -- it lies in (0, pi), so its sine is positive by
definition and the cotangent's sign belongs entirely to the dot product.
The signed cross was importing orientation into a quantity that has none.
`fabs` on a positive double is the identity, so counter-clockwise input
(every gmsh mesh, every golden) is bit-for-bit unchanged.

One subtlety that had to be got right in the gate: all six vertex
orderings agree, but only a REVERSAL is bit-exact. `_triangle_area2` is a
difference of two products; a reversal negates it exactly, a cyclic
rotation recomputes it from different coordinate differences and lands a
ulp away. That is unrelated to the defect. The test compares reversals
with `array_equal` and rotations at `rel=1e-14`.

**P3a/P3b -- `method="petsc"`.** P3a added it via petsc4py; P3b moved the
same KSP/PC configuration into `core/src/solver/petsc_ksp.cpp`. Both
backends are kept forever and reported in `info["backend"]`. They are
**bit-identical** (`np.array_equal`, not a tolerance) on random SPD
systems, on a real 399-iteration interleaved psi/n/p device Jacobian, and
with a nonzero initial guess -- achievable only because both call the
same `libpetsc.so`, which is why the acceptance test (true-residual
recomputation) and CSR canonicalization deliberately stayed in Python.

**P3b bought no speed** -- 3.30 ms vs 3.38 ms warm. The justification is
entirely architectural (a single engine is what makes distributed
`Mat`/`DMPlex` reachable in P7) and the plan says so rather than
implying a win.

P3a's `x0` was **silently ignored**: it seeded the solution vector but
never called `KSPSetInitialGuessNonzero`, and PETSc zeroes that vector at
the top of `KSPSolve`. Found and fixed on both paths.

PETSc is optional INSIDE the extension (`TCAD_WITH_PETSC=AUTO|ON|OFF`,
found via pkg-config), so a pip-only build still compiles and falls back
to petsc4py. conda-forge's PETSc is 32-bit `PetscInt` -- a real ceiling,
reported by `_accel.status()`.

**P4 -- process/particle kernels.** Five kernels in
`core/src/process/`: three per-triangle AMR indicators
(`indicator_curvature_tri` 0.27 -> 227 Mtri/s, `debye_ratio_tri` 0.28 ->
242, `indicator_log_density_tri` 0.80 -> 99) and the two 1D explicit
diffusion time loops (`process.diffuse_numeric` 3.3x,
`ted.diffuse_with_defects` 4.1x).

Those are two different kinds of win. The indicators were the P2 shape
exactly (per-triangle Python loop calling `np.linalg.norm` on
two-element vectors). The diffusion loops were never doing too much
arithmetic -- they paid ~10 numpy dispatches per timestep against a step
count the explicit stability bound drives into the tens of thousands --
so removing the interpreter round trip is all there was to get.

**Bit-identity was made structural.** Every transcendental acting on a
whole array stays in numpy and only its RESULT crosses the boundary:
`np.log(n)` rather than `n`, the nodal Debye lengths rather than the
doping. numpy's `log` and C++'s are independent implementations and the
gate is `np.array_equal`. The one exception -- the TED supersaturation's
scalar `exp`, which would otherwise mean materializing one double per
timestep -- was MEASURED: over 400k arguments spanning the range the
decay reaches, `std::exp` and `np.exp` agreed bit-for-bit on every one,
through both numpy's array and 0-d scalar paths.

Python's builtin `max`/`min` reduce with `if item > current`, so with a
NaN operand the FIRST value wins; `std::max` and `std::fmax` do not both
behave that way. `py_max`/`py_min` in `indicators.cpp` reproduce the
reference's rule so a NaN propagates identically.

**Two candidates the phase line named were EXCLUDED by measurement, not
scope.** (a) **MC implant** is already vectorized over ions -- throughput
is flat at 61-81k ion/s from 500 to 100k, i.e. array-bound not
dispatch-bound -- *and* it could not be gated: bit-identity would need
numpy's PCG64 stream, ziggurat `standard_exponential` and bounded-uniform
algorithm replicated exactly, and a Monte-Carlo kernel whose stream
differs cannot be compared with `np.array_equal` at all. It would be the
first kernel here with no oracle. If ever wanted, draw the random arrays
in numpy and consume them in C++. (b) **`implant_2d`'s lateral
smoothing** is a BLAS `dgemv` after the fix below; C++ cannot reproduce
it bit-identically and has no reason to try.

**A defect found in a module P4 was not porting.** `process2d.implant_2d`
rebuilt the same dense `(Nx, Nx)` Gaussian kernel -- and the same
`(Nx, Nx)` `exp` -- once per depth row, making the call O(Ny*Nx^2) in
transcendentals where it is O(Nx^2). Hoisting it: **939 ms -> 15 ms at
400x600 (62x)**, verified bit-identical against a transcription of the
pre-hoist body.

Also in P4: `tcad::IndexOutOfRange` -> Python `IndexError`, the fourth
mapped exception (the reference gets this free from numpy fancy-indexing;
a kernel dereferencing a raw pointer would read out of bounds, so every
kernel taking connectivity validates the index range in one O(n) pass).
And a CI gap closed that predated the work: the G-E throughput floors are
marked `slow`, and the `python-only` job's slow battery skips the whole
parity file (no extension to measure), so they were running NOWHERE.

**Note on the slow battery's warning count** (11 -> 10 across P4): not a
behaviour change. Deselecting only the three new floor tests gives back
exactly `22 passed, 11 warnings`. pytest de-duplicates warnings per xdist
WORKER, so adding tests reshuffles the `-n 6` distribution.

### M30 -- workbench system features (2026-09-07)

Plan: `pytcad/M30-WORKBENCH-PLAN.md`. **COMPLETE -- all 12 phases**,
through Phase 12 (SSH remote execution + GUI wiring).

Part I (this addendum's four independently-gated phases) covered
workbench system features: splits, calibration, batch, deck-build-import.
None of it touches the numerical core. Two of ARCHITECTURE.md's five M30
bullets (2D contour/cut plots, transient plots) were already shipped by
`GUI-IMPROVEMENT-PLAN.md`/`M17-TRANSIENT-PLAN.md` and are explicitly not
part of this work.

This is the session that identified the broken `base` Qt6 env (see
CURRENT STATE) after a false "97 tests failed" scare.

### GUI reskin, QML cleanup, workflow-friction and performance passes (2026-09-04)

A run of GUI-side slices: visual reskin (slices 0-2), a workflow-friction
pass, a QML architecture cleanup (which itself surfaced two real bugs,
fixed), and a performance audit + optimization pass. Also M12-S2 GUI
exposure (TAT wired into the catalog) and tests added for panels merged
from a parallel development branch.

### GUI phases 3-4 + the code-review passes (2026-08-29/30)

Plan: `GUI-IMPROVEMENT-PLAN.md`. Phase 3 (lab controller, provenance,
continuation traces) and Phase 4 (runtime validation, state indicators):
`lab_controller.py`, `gui_state_validator.py`, `PhysicsLabPanel.qml`,
`StatusIndicator`/`ValidationBanner`/`ValidatedTextField`. Project
persistence schema bumped to v5 (model config was silently reset to
catalog defaults on reload).

Two `/code-review` passes on the uncommitted diffs found 16 real bugs
between them (not style nits), all fixed. The ones worth remembering:

- `solver_runner.build_material_grid()` built the per-node grid in
  `(Nx,Ny[,Nz])` order but Device2D/Device3D require row-major
  `(Ny,Nx)`/`(Nz,Ny,Nx)` -- **silently transposed heterostructure
  material boxes on any non-square mesh.** Same class as the meshgrid
  gotcha.
- `Models.S_n/S_p/driving_force` were declared, documented as
  controlling real physics, and read NOWHERE in the solver core -- a
  pure silent no-op, unlike `impact`/`incomplete_ion` which already
  raised. Now guarded in `Models.__post_init__`.
- `GuiStateValidator._check_input_values`/`_check_result_consistency`
  were bare `pass` bodies whose own docstring claimed real NaN/Inf
  checking -- a faked implementation. Removed outright (along with the
  timer that called them) rather than left as a placeholder; validation
  is genuinely event-driven.
- Two `ListView`s bound `model:`/`visible:` to plain `Slot()` calls with
  no NOTIFY signal -- QML evaluates that once and freezes it, so the
  tables never refreshed across repeated Runs.
- The Phase 3b "continuation stages" table read an npz key that **no
  real solve path ever wrote** -- only its own unit test fabricated it
  via `np.savez`.
- `fd_density()` raised on ANY `eta > FERMI_ETA_MAX`, including a
  transient overshoot during early Newton iterations that would still
  have converged -- aborting the whole solve. Clamped for the in-loop
  evaluation only, with an explicit post-convergence check on the
  UNCLAMPED eta so genuinely invalid converged states still raise.

Numeric QML fields (contact/gate voltage, tox, doping, every process-step
parameter) let `parseFloat("")`/`parseFloat("abc")` through to the solver
as NaN -- found by the end-to-end smoke test, fixed with a shared
finite-number guard.

### 3D device authoring, phase 1 (2026-08-31)

Closed the narrower half of the "3D device authoring absent from GUI"
gap named in `ARCHITECTURE.md` 4b: `Region`/`ContactDef`/`DomainDevice`
and `RegionSpec`/`BoundarySpec`/`MeshModel`/`StructureModel` now accept
an optional z-extent, additively.

The exploration finding that shaped the scope: the SOLVE and VISUALIZE
halves of the pipeline (`solver_runner`'s mesh/doping/device/contact
builders, and `viewer3d.py`) were **already fully
dimensionality-generic** before this work -- the entire gap was in the
AUTHORING half.

### M18 -- small-signal AC (2026-08-31 .. 2026-09-05)

Phase 1 (Device1D), Phase 3 (Device2D n-terminal AC / Y-parameters incl.
gate ports), Phase 3b (full 4-terminal `mosfet_2d` Y-parameter matrix +
fT), Phase 4 (GUI exposure).

`pytcad/ac.py` drives `Device1D` from OUTSIDE `device.py` through its own
`_residual_jacobian` -- the external-driver pattern M15/M16/M17
established. No new `Models` flag: AC is a different equation formulation
layered on the converged DC point, not a physics term to toggle.

Physics: `J_ac(w) = J0 + j*w_s*Cmat`, where `Cmat` is verified
BIT-IDENTICAL (not re-derived) to `transient.py`'s already-FD-gated
backward-Euler storage term at `dt_s=1.0` -- `d/dt -> j*w` replacing
`1/dt` is the only conceptual step. One complex linear solve, no Newton
loop (the system is genuinely linear at fixed state).

### M22 phase 3 -- MPI Schwarz, GPU and AMG (2026-09-02 .. 2026-09-04)

Plan: `M22-LINSOLVE-PLAN.md` section 9. Landed as MPI Schwarz domain
decomposition, **not** the distributed-sparse-matrix design the plan
originally sketched. All three accelerations are opt-in and
size-and-hardware-gated inside `solver_runner.run_job()`; a machine
without a GPU, pyamg or mpi4py sees byte-identical behaviour.

- **Equilibrium AMG**: `Device3D.solve_equilibrium` now honours
  `opts.linsolve` (it previously hardcoded "direct", silently ignoring
  the option). bicgstab+pyamg cuts equilibrium wall time 8x-44x on large
  3D meshes (bjt_3d 43.4 s -> 1.0 s) but is WORSE on small ones
  (mosfet_3d 2.1 s -> 21.4 s) -- gated at >20,000 nodes, the measured
  switch point.
- **GPU bias solve**: `linsolve`'s `"gpu_direct"` (CuPy/cuSOLVER).
- **MPI Schwarz**: later generalized past an x-only split, and a real
  correctness bug in it was found and fixed (2026-09-04), as was a
  gate-axis fix verified on `mosfet_3d`/`moscap_3d`.

Earlier M22: phase 1 (Krylov + ILU behind spsolve) and phase 2 (Schur-
complement preconditioner, `solve_linear(precond="schur")`). The Schur
work sat LANDED-PENDING-VERIFICATION for two days and passed cleanly on
its first actual run -- unlike M16.

### M21 phase 3 -- unstructured 2D FV (2026-08-31)

Plan: `M21-PHASE3-MESHING-PLAN.md` (scoped at 45-62 h, HIGH RISK because
it touches Device2D's frozen core). Delivered in four slices:

- **3a, geometry foundation**: `gmsh_mesh.build_diode_mesh()` (two OCC
  rectangles `fragment()`-ed so they share nodes exactly at the material
  interface, sized against `debye_length`), `unstructured_assembly.py`'s
  unique edge list + mixed Voronoi/barycentric dual-cell areas.
- **3b, Poisson-only equilibrium**: TPFA transmissibility via triangle
  circumcenters (`dual_facet_length/primal_edge_length`, scale-invariant
  -- confirmed, not assumed). MEASURED that TPFA's Delaunay requirement
  is only approximately met: 1.39% of triangles on the real diode mesh
  are obtuse, yet every transmissibility still comes out positive. That
  measurement is the actual grounding for using the method here.
- **3c, coupled bias solve**: Scharfetter-Gummel + SRH, interleaved
  `[psi, n, p]`. Key de-risking finding, re-derived rather than trusted:
  3b's per-edge `trans` factor serves the SG current term too with NO new
  geometry, because `dVy*D/hx = D*trans` algebraically.
- **3d, integration**: `Device2D(unstructured=True)` -- genuinely a thin
  dispatch wrapper, zero new Jacobian entries.

Earlier M21: phase 1 (1D h-refinement, 17 gates) and phase 2 (2D/3D).

Phase 1 caught two design errors BY the gates: (a) folding h/L_D into the
Doerfler error mass made it dominate selection and produced a
near-uniform "adaptive" mesh that LOST to a uniform one at equal node
count -- h/L_D is now a separate absolute constraint; (b) the default
grading ratio 1.2 is UNREACHABLE by bisection (a bisected cell abuts an
unbisected one at exactly 2), so the repair loop silently returned a mesh
that failed the request -- ratio 2.0 is the default and ratio<2 now
raises.

Phase 2's hard-debug pass found six real bugs, including a stale import
that had been breaking PHASE 1 unconditionally (10 of 17 phase-1 tests
were already failing and nothing had re-run them), a `tol` convergence
check that was dead code in both 2D and 3D drivers, and the headline
`meshgrid` axis-order corruption in the tests' own fixtures (see
GOTCHAS).

### M19 -- self-heating, phase 1 (2026-08-31)

`pytcad/thermal.py`. Architecture decided BEFORE implementation:
`Device1D`'s entire nondimensionalization is built once at `__init__`
from a scalar `T`, so a genuinely coupled 4th unknown would mean
rearchitecting the whole scaling framework -- disproportionate to what
the milestone's gates require. Chose the standard "isothermal DD + outer
Gummel thermal loop" instead; `device.py`/`moscap.py` untouched.

### M20 -- density gradient (2026-08-29 .. 2026-08-31)

Plan: `M20-DENSITY-GRADIENT-PLAN.md`. Ancona-Stafford quantum
correction, equilibrium-only, default-off bit-identical. **Now closed**
via a coupled-Newton reformulation; the road there is worth keeping:

- Gate-writing cross-check caught three real defects in `dg.py` before
  any run: a double-kT bug (`dos` is already in m^-2), an inverted
  `E_band` sign that put the inversion well in the BULK, and a
  far-boundary Hamiltonian diagonal never assigned (`main[-1] = main[-1]`
  on `np.empty` garbage -> nondeterministic `eigsh`).
- The **lagged** outer loop sourced each pass's target `Lambda` from the
  DG-CORRECTED density instead of the classical one, closing a 1-node
  self-reference. This produced a RIGID period-2 oscillation immune to
  every damping factor from 1.0 to 0.02 over 400 passes -- and a 188 nm
  centroid against a ~4 nm reference. Sourcing from the classical density
  converges in 4 passes with no damping.
- That exposed a second, separate problem: at gamma=1 the converged
  answer sat exactly at the clamp and INVERTED the required direction. A
  gamma sweep showed a hard BIFURCATION, not a calibration curve. Three
  hypotheses (boundary-condition mismatch, sub-physical mesh resolution,
  units) were tested and ruled out before concluding this was the known
  weakness of a lagged Gummel scheme -- which is why production tools
  solve the quantum potential COUPLED into the same Newton system.
- Fixed by doing exactly that: `(psi, Lambda_n, Lambda_p)` solved
  simultaneously, 3 unknowns/node, interleaved like `device.py`'s own
  convention.

### M17 -- transient simulation (2026-08-30/31)

Plan: `M17-TRANSIENT-PLAN.md`. Phase 1 (1D), Phase 2 (2D), Phase 3 (GUI).
`transient.py`/`transient2d.py` drive the device cores from outside;
`device.py`/`device2d.py` untouched. Backward-Euler/theta scheme with
adaptive dt and three `Waveform` primitives.

Two findings worth keeping:

- **The charge-conservation sign convention differs between 1D and 2D,
  genuinely.** 1D: `d(stored_charge)/dt == I_right - I_left`. 2D:
  `== -(I_left + I_right)`. Not a repeat of the same bug --
  `Device2D.terminal_current()`'s convention is "positive = INTO the
  device" independently at every contact, while 1D's `Jn+Jp` edge array
  is one continuous current sampled at two points.
- **The 2D `stored_charge()` had to be redefined as a delta** relative to
  the initial snapshot: on a symmetric Na=Nd diode the absolute
  `sum((n-p)*dA)` is near-zero by cancellation, so what remained was
  float64 roundoff, not the signal. A units bug was ruled out first.
- Usage lesson: the default adaptive-dt growth coarsens past a short
  decay timescale within a few steps, and backward Euler's `1/(1+dt/tau)`
  under-damps relative to `exp(-dt/tau)` once dt ~ tau. A caller
  measuring a specific timescale must pass an explicit `dt_max`.

Honest gap: G2's stored charge was NOT matched to a textbook
`Qs ~= I_F*tau_p` formula (off by a factor of several and sign-ambiguous;
this is voltage-driven switching, not the constant-reverse-current
assumption those formulas make). Descoped to the two independently
verifiable claims rather than forcing a tolerance.

### M16 -- band-to-band tunneling (2026-08-29, verified 2026-08-31)

Plan: `M16-BTBT-PLAN.md`. Local Kane model, `G = A F^2 exp(-B/F)`, Si
constants from Hurkx, Klaassen & Knuvers (1992) Table I. Live-coupled
generation in `_residual_jacobian`, placed AFTER both continuity `=`
assignments and BEFORE Dirichlet stamping (the M15 D1 invariant).

Landed unverified; when the gates were finally RUN two days later, all
failures root-caused to the TEST code, not the physics -- e.g. a
plateau check that sorted ascending by V then asserted J increases going
from the largest reverse bias to the smallest, backwards from the
intended trend.

**Provenance caveat that still stands:** the A/B constants were pinned
from model knowledge, not a fetched primary source (the authoring
session's web search was unavailable). If the pin fails review, fix the
constants deliberately -- never silently.

### 3D visualization (2026-08-29/30)

Plan: `3D-VISUALIZATION-PLAN.md`. PyVista/VTK in a SEPARATE top-level
window (VTK's Qt integration is a QWidget, not a QML item). Phases 1-2
(grid + isosurfaces) and Phase 5 (exploded multi-layer structural view).
Field node ordering (pytcad's `(Nz, Ny, Nx)` C-order) was verified
NUMERICALLY against VTK's point order, not assumed.

**A real bug found by actually building the thing:** `gui/app.py`
bootstrapped with `QGuiApplication`, but `QWidget` construction
hard-requires a real `QApplication` and ABORTS THE WHOLE PROCESS
otherwise. Phase 1 as landed would have crashed the entire application
the first time a user clicked "View in 3D" -- invisible to its own tests,
which all monkeypatched the window out before it could be constructed.
Switching to `QApplication` is a strict superset and also unlocked real
headless testing of the widget tree.

### M14 -- surface mobility (2026-08-28 .. 2026-08-31)

Plan: `M14-SURFACE-MOBILITY-PLAN.md`. G-B (D_it) and G-C (S_n/S_p)
landed; **G-A remains the suite's only xfail** (see OPEN ITEMS).

- **D_it**: a first pass "corrected" the plan's `Q_it = q*D_it*phi_s` to
  `q^2*D_it*phi_s` from a half-remembered heuristic, got user sign-off,
  implemented it -- then found it numerically to be a complete no-op
  (~1e-21x the scale of the existing term). Re-derived from first
  principles: D_it [cm^-2 eV^-1] times a shift of `dphi_s` VOLTS is a
  `dphi_s`-eV energy shift numerically, giving ONE factor of q. The
  plan's original text was right; the "correction" was wrong.
- **S_n/S_p**: the first wiring used `F_n[node] = (n[node]-n0)*(1+S)`,
  chosen because it reduces to Dirichlet at S=0 with no branching -- a
  mathematical no-op (see GOTCHAS). Redone as a genuine Robin flux
  balance from steady-state particle conservation in the boundary
  half-box, which does NOT reduce to Dirichlet at S=0 (S=0 there means
  zero current, a materially different BC).
- A later hard-debug pass found `fd=True` + `S_n/S_p != 0` gave 1.2e-3
  boundary FD-Jacobian error, 25x over gate: M13's Fermi-Dirac chain-rule
  correction to the SG edge-current Jacobian was applied to interior rows
  but never extended to the new boundary Robin rows.
- Device2D's S_n/S_p was reverted to `NotImplementedError` rather than
  shipped broken, then landed properly in a later session.

### M15 -- impact ionization (2026-08-26 .. 2026-08-28)

Plan: `M15-IONIZATION-PLAN.md`. The longest-running debugging arc in the
project and the source of several standing conventions.

An early "M15 COMPLETE, all gates green" claim was **false**. A hard-debug
pass found impact ionization was contributing EXACTLY ZERO at every bias,
via six defects:

1. **D1**: the generation term was added to the continuity rows and then
   OVERWRITTEN by `=` when those rows were assigned 30 lines later. This
   is the origin of the standing "generation goes after the continuity
   assignments, before Dirichlet stamping" invariant.
2. **D2**: the frozen-field snapshot was taken AFTER contact stamping,
   contradicting its own comment (a 2 MV/cm contact-cell artifact,
   harmless only while D1 discarded the source). D1+D2 must land
   together.
3. **D3**: the staged-generation ladder never reached 1.0x (guarded by
   `stage_factor < 1.0`, so the final rung reused 0.5x).
4. **D4**: toggling `Models.impact=False` after an on-solve left the
   frozen source applied.
5. **D5**: Device2D/Device3D SILENTLY IGNORED `Models(impact=True)` --
   now `NotImplementedError`, matching the `field_mobility` precedent.
6. **D6**: impact+fd used the wrong SG scheme (missing M13's nu-factor
   edge deltas), 13 orders of magnitude too much generation.

**Root cause of the spurious avalanche branch (confirmed):** the analytic
II Jacobian rows destabilize Newton itself -- the first `du` is
BIT-IDENTICAL between impact on/off at the same state, so the linear
algebra was fine; the instability is iteration dynamics through sign(J)
kinks. Fixed with a lagged-source / frozen-generation architecture (the
M12-TAT precedent): generation frozen per bias solve on the warm-start
state before contact stamping, no II Jacobian rows, an outer fixed-point
loop closing the feedback.

Closing R1b took three attempts (full coupled Jacobian alone: weaker
multiplication, a continuation-methodology gap; arc-length sweep: the
bordered corrector bypassed the strength ladder; finally: threading the
same ladder into the corrector plus backtracking it never had). A
cross-check against the original van Overstraeten-de Man 1970 paper found
a genuine literature bug along the way -- hole ionization's field-switch
point wrongly shared electrons' 5e5 V/cm instead of its own published
4e5 V/cm. The residual G-C/G-D gaps turned out to be the textbook local
field `M = 1/(1-I)` formula's own neglect of space-charge feedback, and
N=1e17's fold sitting 35% outside the 1970 fit's calibrated range --
neither fixable by more solver work. Closed by user-directed scope
decisions, recorded in the tests themselves.

### M13 -- Fermi-Dirac statistics (2026-08-26)

Plan: `M13-FERMI-DIRAC-PLAN.md`. Physical Nc/Nv FD statistics, the
nu-factor modified Scharfetter-Gummel scheme (exact equilibrium detailed
balance for both carriers including heterointerfaces), incomplete
ionization, ported through 1D/2D/3D.

- A genuine latent defect: deep-tail `f_half` carried ~2.5e-4 RELATIVE
  error (a fixed-node quadrature grid cannot resolve a feature at
  `t~exp(eta)`). `eta<=-10` now uses the exact Taylor series.
- Later, a tabulated fast path (cubic Hermite over **log F**, not F --
  `F_{1/2}` spans ~4e-18 upward, so an absolute-error interpolant would
  be worthless in the tail, and absolute error in log F IS relative error
  in F). Measured 150x-1260x: 4000 evaluations 214.7 ms -> 0.17 ms; an
  fd `solve_bias` 11.41 s -> 0.07 s. The exact quadrature survives as
  `f_half_exact`, gated against, and `PYTCAD_FERMI_EXACT=1` bypasses the
  table.
- GOTCHA that cost a debug cycle: the full-residual Poisson assembly in
  `device2d`/`device3d` REUSES the dx/dy edge differences, which under fd
  carry modified SG deltas -- Poisson fluxes must be recomputed from PURE
  potential differences.

### M11 -- heterostructures (2026-08-26)

S4 (Device2D per-node material lists, harmonic-mean edge eps, per-node fd
DOS grids so fd composes with heterojunctions) and S5 (structure-model
materials lossless end-to-end, HBT and HEMT templates).

A debug cycle found the `et_x` eps factors missing from the 3D Poisson
fluxes -- caught by the 3D->2D dimensional-reduction gate. Another found
Device2D/Device3D bias convergence dividing relative updates by RAW
densities, pinning the criterion to roundoff at deep-minority barrier
nodes (limit cycle ~8.5e-7); both cores now use a density floor.

### Earlier / cross-cutting

- **graded_mesh grading bug (2026-08-27)**: the docstring promised
  adjacent cells never differ by more than `ratio`; measured up to
  11.06x, because the forward-walk construction clamped every step onto
  the next focus point and onto L, leaving a STUB final cell -- always
  the ohmic contact cell, 2.5-5.5x SMALLER than `h_min`. Consequence was
  measured, not theoretical: an explicit diffusion step is limited by
  h^2, so a 4-anneal-step process flow went from 15.2 s to 0.19 s once
  fixed (~78x). Replaced with an arc-length construction plus a log-space
  gradient limiter whose scale-invariant rescale makes the fixed point
  satisfy the bound EXACTLY (fuzzed 2000 geometries: 0 violations).
  **Goldens were preserved, not regenerated**: the M13 `.npz` goldens
  rebuilt their meshes by CALLING `graded_mesh`, silently coupling
  solver-bit-identity gates to the mesh generator -- decoupled by
  freezing the exact pre-fix meshes into
  `tests/goldens/m13/frozen_meshes.npz`.
- **GUI scenegraph crash (2026-08-27)**: `__cxa_deleted_virtual` abort in
  `QQuickPaintedItem::updatePaintNode`, ~1-in-3 to 1-in-5 full-suite
  runs. Every test calling `create_engine()` built a `QQuickWindow` and
  never tore it down; Python's GC destroyed it outside Qt's safe close
  protocol. Fixed with a per-test + session teardown sweep that
  `.destroy()`s (not `.close()`s -- `Main.qml`'s `onClosing` can veto a
  close on unsaved changes) every top-level window.
- **Test suite parallelized (2026-08-28)**: pytest-xdist, after fixing
  four hardcoded shared `/tmp` paths that raced across workers.
- **Roadmap extension (2026-09-09)**: `ARCHITECTURE.md` gained sections
  4c (post-M31 roadmap M31-M40, recording the measurement that ordered
  M31's phases so it is never re-derived), 4d (the dimensional debt and
  the road to full 3D) and 4e (how this is meant to beat
  Sentaurus/Atlas, and where it deliberately concedes). 4c.2's M32-M40
  are PROPOSED, not decided.
