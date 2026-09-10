# M31 P5-1 -- linear-solver and preconditioner selection

Status: **DRAFT, ALL FIVE PHASES (A-E) LANDED 2026-09-10** -- E as
E-opt-in; E-auto explicitly not taken, see section 4. The plan as a
whole is not "approved" in the sense of a separate milestone sign-off
document, but every phase's own gates are green; see section 4 for
each phase's landing record. Written 2026-09-10, immediately after
P5-0 landed and made
these measurements possible for the first time. Phase A's own findings
(section 4) moved the milestone's center of gravity from the
unstructured path this plan was originally scoped around to the
structured 3D equilibrium path (B4, 82x-119x) and found B8 (2D
unstructured) has no measured win at all -- both are Phase A doing its
job, not scope creep, but they mean whoever signs off Phase B onward
should read section 4 in full, not just this status line.

Sits between P5-0 (landed) and P5 proper (the C++ assembler, scope not
signed off). Parent: `M31-CPP-ARCHITECTURE-PLAN.md`; sibling:
`M31-P5-ASSEMBLY-NEWTON-PLAN.md`, whose sections 6, 9 and 11 this one
reads on directly.

---

## 1. Why this exists, and why it did not before

P5-0 routed the unstructured cores through `linsolve.solve_linear`.
Before that they called `spsolve` directly and `NewtonOptions.linsolve`
was silently ignored, so **no measurement in this section could have
been taken.** The first thing done with the new capability was to take
them, and they say something the roadmap did not anticipate.

Whole-solve, full benchmark size, this machine:

| | direct | gmres | petsc | bicgstab |
|---|---|---|---|---|
| **B8** 2D unstructured (34,023 DOF) | **3.54 s** | 117.80 s | did not converge | did not converge |
| **B9** 3D unstructured (7,464 DOF) | 7.55 s | 2.48 s | **0.71 s** | did not converge |

The 3D result is a **10.6x** speedup, and it is *correct*: on the 3D
diode, `gmres` and `petsc` agree with the direct solve to
`|dpsi| = 3.6e-15` and a terminal current identical to
`dI/I = 0` (petsc) / `1.1e-16` (gmres). That is machine precision, not a
tolerance being waved through.

The 2D result is the opposite in every respect, and understanding why is
what this milestone is actually about.

## 2. The finding: the preconditioner ranking INVERTS with dimension

The obvious reading of section 1 is "2D suits a direct solve, 3D suits
an iterative one" -- the textbook fill-in argument, and the one
`M31-CPP-ARCHITECTURE-PLAN.md` section 1 already measured for the
structured path. **That reading is wrong**, or at least badly
incomplete. Taking one representative Jacobian out of each core and
sweeping the preconditioner:

| preconditioner | B8 (2D, 34,023 DOF) | B9 (3D, 7,464 DOF) |
|---|---|---|
| direct (SuperLU) | **0.29 s** | 0.38 s |
| gmres, node-block-Jacobi `block_size=3` | 1.99 s, **409 iters** | **0.14 s**, 106 iters |
| gmres, ILU (`block_size=None`) | 0.71 s, **3 iters** | 1.55 s, 129 iters |
| gmres, Schur (`precond="schur"`) | **FAILED** (500 iters, 357 s) | 0.53 s, 260 iters |
| petsc (point-block PBJACOBI) | 1.53 s, 387 iters | 1.01 s, 103 iters |

Read the iteration counts, not the times. In 2D, ILU converges in
**3** iterations where node-block-Jacobi needs **409**. In 3D the
ranking flips: node-block-Jacobi is the best of the five and ILU is the
worst. The same two preconditioners, opposite orders.

**And the cores ask for the wrong one in 2D.** Every coupled call site
in this tree passes `block_size=3` (`unstructured_dd.py`,
`unstructured_dd3d.py`, `device2d.py:1005`, `device3d.py:1017`), which
selects node-block-Jacobi -- the 409-iteration column. `block_size=None`
is what reaches ILU, and no core passes it for a coupled solve.

So P5-0's "2D iterative is hopeless" conclusion was an artifact of a
preconditioner choice nobody made deliberately for the unstructured 2D
case: it was inherited from the structured cores, where it was measured
and correct (M22 phase 1's G6).

**A second reading of the same numbers, which the plan must not skip.**
One B8 Jacobian at gmres/block-Jacobi is 1.99 s; twelve Newton
iterations of it should be ~24 s, and the whole solve measured
**117.8 s**. The preconditioner is therefore getting materially worse
as the Newton iteration proceeds -- the first Jacobian is the easy one.
Any selection rule built from a single representative matrix will be
wrong for the same reason. Phase A exists because of this paragraph.

## 3. What the code cannot currently express

Three concrete gaps, each of which this milestone has to close before a
selection rule is even writable:

1. **`NewtonOptions` has no `precond` field.** It carries `linsolve` and
   `linsolve_rtol` and nothing else, so `solve_linear`'s `precond=`
   ("auto" / "block_jacobi" / "schur") is unreachable from any solver
   entry point. The winning 2D configuration is not expressible today.
2. **`block_size` is hardcoded at the call sites**, so the ILU path --
   the 3-iteration one in 2D -- cannot be selected either.
3. **The unstructured cores have no per-iteration fallback.** The
   structured cores already degrade gracefully:

   ```python
   try:
       du, _ = linsolve.solve_linear(Jd, rhs, method=opts.linsolve, ...)
   except linsolve.LinearSolveError:
       du, _ = linsolve.solve_linear(Jd, rhs, method="direct")
   ```

   (`device3d.py:1017`, and the equilibrium path at `device3d.py:619`.)
   P5-0 did not add this to the unstructured cores, so a non-converged
   iterate raises out of the whole solve there. **That asymmetry is a
   P5-0 gap, not a design decision**, and it is why B8's petsc row in
   section 1 reads "did not converge" rather than "fell back and
   finished". Closing it is Phase C.

## 4. Phases

| | | |
|---|---|---|
| **A** | the measurement matrix -- per Newton iterate, not per matrix | **LANDED 2026-09-10** -- see section 4 |
| **B** | `NewtonOptions` gains `precond` and `block_size`; plumbed to every core | **LANDED 2026-09-10** -- see section 4 |
| **C** | unstructured cores get the structured cores' fallback | **LANDED 2026-09-10** -- see section 4 |
| **D** | the selection rule, and its refusal path | **LANDED 2026-09-10** -- see section 4 |
| **E** | defaults -- change, or document and leave | **LANDED 2026-09-10 as E-opt-in**; E-auto not taken -- see section 4 |

### Phase A -- measure properly

Section 2's table is one Jacobian per core. That is enough to find the
inversion and not enough to choose a default. What Phase A produces:
for each of {B8, B9} x {quick, full} x {direct, gmres, bicgstab, petsc}
x {block_jacobi, ILU, schur}, **per Newton iterate**: iteration count,
wall time, and achieved residual -- so the degradation in section 2's
last paragraph is visible rather than inferred.

Delivered through the M32 harness, not a script, per
`Architecture_Master_Plan.md` section 36 and this project's own history
of one-off numbers. The natural shape is a new
`benchmarks/preconditioners.py` report rather than more B-case columns:
it is a study, not a per-commit dashboard row.

Also in Phase A, because it is the same measurement: **the structured
cores.** `device3d.py`'s B4 full row is 185 s with 99.9% in the direct
solve, and it already accepts `opts.linsolve`. Nobody has swept its
preconditioners either. If 3D structured behaves like 3D unstructured,
Phase E's scope grows considerably -- and that should be discovered in
Phase A, not in Phase E.

#### Phase A -- QUICK-SIZE RESULTS (landed 2026-09-10)

`benchmarks/preconditioners.py` exists now: it patches the module-local
`solve_linear` name the unstructured cores hold since P5-0 (see the
script's own docstring for why that patch point, not
`pytcad.linsolve.solve_linear` directly, is required), forces each of 8
method x preconditioner configs across a WHOLE Newton solve, and records
every call -- not one representative matrix. A bounded per-config wall-
clock budget (150s) and an emulated Phase-C fallback (recorded, never
silent -- see the script's docstring) keep a config that fails on every
iterate from consuming the whole run.

Quick size, both cases, full Newton sequence (`benchmarks/phase_a_out/
quick.json` is the raw per-call record; summarized here):

| B8 (2D, 1001 nodes) | calls | total_s | iters (min-max) | fell back |
|---|---|---|---|---|
| direct | 11 | 0.14 | 1-1 | 0 |
| gmres/block_jacobi | 11 | 0.69 | 182-307 | 0 |
| gmres/ilu | 11 | 0.23 | **3-4** | 0 |
| gmres/schur | 5 (aborted) | 35.3 | - | 5/5 |
| bicgstab/block_jacobi | 11 | 0.14 | 1-154 | 1 |
| bicgstab/ilu | 11 | 0.23 | 1-2 | 1 |
| bicgstab/schur | 11 | 0.65 | - | 11/11 |
| petsc | 11 | 1.22 | 1-195 | 4 |

| B9 (3D, smaller mesh) | calls | total_s | iters (min-max) | fell back |
|---|---|---|---|---|
| direct | 15 | 0.76 | 1-1 | 0 |
| gmres/block_jacobi | 14 | 0.35 | 62-125 | 0 |
| gmres/ilu | 3 (aborted) | 40.0 | - | 3/3 |
| gmres/schur | 14 | 0.69 | 70-155 | 0 |
| bicgstab/block_jacobi | 14 | 0.18 | 1-73 | 1 |
| bicgstab/ilu | 15 | 3.91 | - | 15/15 |
| bicgstab/schur | 14 | 0.45 | 1-87 | 1 |
| petsc | 14 | 0.19 | 62-84 | 0 |

Two things this adds beyond section 2's single-matrix table:

1. **The degradation is now visible, not inferred.** B8's
   gmres/block_jacobi iteration count climbs 182 -> 307 across the
   Newton sequence (and its wall time per call roughly follows, 0.044s
   -> 0.073s) -- confirming section 2's closing paragraph without
   needing to extrapolate from one matrix.
2. **A finding section 2 could not have made: the ranking is also
   SIZE-dependent, not just dimension-dependent.** At quick size, ILU
   fails completely on B9 (every call falls back -- 100% failure,
   `gmres/ilu` hit the wall-clock budget before finishing 4 of 14
   calls) even though section 2's FULL-size sweep found ILU converged
   there in 129 iterations. Schur is the mirror image of section 2's
   full-size finding: it fails completely on B8 at BOTH sizes (100%
   fallback) and works cleanly on B9 at both. So dimension predicts the
   schur result but not the ILU one -- a selection rule keyed on
   dimension alone, the obvious reading of section 2, would already be
   wrong at this size. This is exactly why Phase D is gated on "every
   fixture in tests/", not the two benchmark cases alone (Gate D-1).

#### Phase A -- FULL-SIZE RESULTS, and a `maxiter` methodology bug

Full-size, whole Newton solve (`benchmarks/phase_a_out/full.json`):

| B8 (2D, 34,023 DOF) | calls | total_s | iters (typical) | fell back |
|---|---|---|---|---|
| **direct** | 11 | **3.43** | 1 | 0 |
| gmres/block_jacobi | 12 | 105.92 | ~1200-2000 | 0 |
| gmres/ilu | 11 | 8.41 | (small) | 0 |
| gmres/schur | 1 (aborted) | 170.15 | stagnant | 1/1 |
| bicgstab/block_jacobi | 11 | 5.55\* | ~300-470 | 0\* |
| bicgstab/ilu | 11 | 7.96 | (small) | 0 |
| bicgstab/schur | 11 | 15.12 | diverging | 11/11 |
| petsc | 11 | 18.3\* | mostly ~1000+ | 8/11\* |

| B9 (3D, 7,464 DOF) | calls | total_s | iters (typical) | fell back |
|---|---|---|---|---|
| **direct** | 17 | 7.85 | 1 | 0 |
| **gmres/block_jacobi** | 15 | **2.59** | modest | 0 |
| gmres/ilu | 2 (aborted) | 239.77 | stagnant at ~18% | 2/2 |
| gmres/schur | 16 | 8.12 | modest | 0 |
| bicgstab/block_jacobi | 15 | 1.06 | modest | 1 |
| bicgstab/ilu | 17 | 50.45 | diverging | 17/17 |
| bicgstab/schur | 16 | 4.39 | modest | 2 |
| **petsc** | 16 | **0.68** | modest | 0 |

\* See the methodology note below -- these two B8 rows are corrected
from the first pass, not the raw sweep output.

**A real bug in this measurement, caught before being reported as a
finding: `solve_linear`'s `maxiter` does not mean the same thing for
every method.** scipy's `gmres(restart=100, maxiter=200)` in this
scipy version (1.17.1) treats `maxiter` as a count of **restart
cycles**, not total iterations -- the callback (`callback_type=
"pr_norm"`, called every inner iteration) recorded gmres/block_jacobi
on B8 running to **2025** actual iterations under a `maxiter=200`
request, i.e. up to `200 * restart(100) = 20000` were available.
`bicgstab` has no restart concept, and PETSc's `KSP.setTolerances
(max_it=maxiter)` sets a literal cap -- both honor `maxiter=200`
exactly. The first pass therefore gave gmres-based configs a ~100x
larger effective budget than bicgstab/petsc configs at the SAME
`maxiter` argument, and two B8 rows (`bicgstab/block_jacobi`, `petsc`)
that looked like near-total failures (11/11 and 11/11 fell back) were
partly an artifact of that mismatch, not a property of the method.

Rerunning just those two at `maxiter=1000` (`benchmarks/phase_a_out/
b8_full_maxiter1000_recheck.json`):

* `bicgstab/block_jacobi`: **0/11 fell back**, 5.55s total (312-474
  iterations/call) -- the 200-cap failure was pure starvation; the
  corrected number replaces "11/11 fell back" in the table above.
* `petsc`: still **8/11 fell back** even at maxiter=1000, but every
  failure's true relative residual (from the raised error, not the
  fallback) is `1.2e-7` to `6.4e-9` against a `1e-10` target --
  converging, genuinely close, not stagnant. This reads as "needs
  ~1500-2000 iterations, or `rtol` should be relaxed for this method,"
  not "petsc is broken on B8" -- a materially different conclusion
  from the uncorrected row, and one Phase D's rule must be built from,
  not the raw number.

The two genuine (non-`maxiter`-artifact) failures on B8 hold up under
this check: `gmres/schur` and `bicgstab/schur` both show the residual
NOT decreasing (schur: stuck at exactly relative residual 1.0, zero
progress; bicgstab/schur: residual growing across Newton iterates,
4.4e-3 -> 2.9e-2 -> 9.1 -> 1866 -- a real bicgstab breakdown, not a
budget problem). Likewise on B9, `gmres/ilu`'s plateau at ~18% relative
residual after its full effective budget (~20,000 inner iterations)
and `bicgstab/ilu`'s wildly oscillating residual (5.3e4 -> 45.7 -> 2.5
-> 6.1) are genuine stagnation/breakdown, confirmed by the same check.

**What this means for the milestone, stated plainly:** the single most
important number in this whole plan is still section 1's -- **direct
remains the fastest whole-solve option on B8 full** (3.43s vs every
iterative config's 5.5s or worse), which reverses this plan's own
opening framing. Section 2's single-Jacobian sweep found "ILU"
converging in 3-4 iterations and read as "ILU should win 2D" -- the
WHOLE-SOLVE number shows why that reading does not survive: **isolated
and timed directly** (`ls._build_preconditioner(A, block_size=None,
precond="auto")` on B8 full's own Jacobian, 34,023 DOF, 434,957 NNZ),
preconditioner construction alone costs **0.653s of the 0.701s total
per-call time** -- 93% of every single call, confirmed by timing the
build and the full `solve_linear` call separately on the identical
matrix. And it is not `spilu` doing that: this environment has `pyamg`
installed, and `_build_preconditioner`'s own chain (`linsolve.py`,
`_build_preconditioner`) tries algebraic multigrid (`pyamg.
ruge_stuben_solver`) BEFORE falling back to ILU when `block_size=None`
-- so the config this plan's sweep script labels `"gmres/ilu"` is, on
this machine, actually running AMG SETUP, not incomplete-LU, every
single Newton iterate with no reuse across iterates. (`CONFIGS`'s label
in `benchmarks/preconditioners.py` should be read as "whatever
`block_size=None` + `precond="auto"` resolves to on this build," not
literally ILU -- a naming gap in the sweep script itself, not a new
finding about the core.) Either way, the 3 Krylov iterations per call
really are cheap (the remaining 0.048s); the entire story is
precondition SETUP cost with no amortization across a Newton sequence
that reuses the same sparsity pattern nine times over. **A
cheap-per-iteration preconditioner is not the same claim as a cheap
solve**, and section 2 conflated them by measuring only the Krylov
iteration count, never the setup it rides on. B9 is the opposite and
unaffected by this: `gmres/block_jacobi` (2.59s) and `petsc` (0.68s)
both beat direct's 7.85s convincingly, confirming section 1's 10.6x
finding independently (that number used `method="petsc"` at default
settings; this sweep's 0.68s for the SAME whole solve, at
`maxiter=1000` rather than 500, is consistent) -- node-block-Jacobi's
setup (invert N independent 3x3 blocks) is far cheaper than an AMG
hierarchy or an ILU factorization, which is a second, independent
reason (beyond section 2's iteration-count story) node-block-Jacobi
suits this codebase's coupled systems.

#### Phase A -- STRUCTURED CORE (B4) RESULTS

`device3d.py`'s `solve_equilibrium` (B4) is a SCALAR system (one
unknown, psi, per node -- `block_size` is structurally `None`
throughout, so `block_jacobi`/`schur` do not apply; only `method`
varies). Quick size (16^3 mesh) converges trivially for every method
(3-10 iterations, sub-millisecond per call) -- not a useful data point,
included for completeness in `benchmarks/phase_a_out/b4_quick.json`.

Full size (40^3 mesh, 68,921 DOF, the case whose 185s direct baseline
motivated including the structured cores in Phase A at all --
`benchmarks/phase_a_out/b4_full.json`):

| method | calls | total_s | iters/call | fell back |
|---|---|---|---|---|
| **direct** | 9 | **179.02** | 1 | 0 |
| gmres (ILU) | 9 | **2.17** | 5-6 | 0 |
| bicgstab (ILU) | 9 | **1.90** | 2-3 | 0 |
| **petsc** | 9 | **1.51** | 9-20 | 0 |

**This is the single largest number this plan has produced: an 82x
(gmres) to 119x (petsc) whole-solve speedup, on the case the plan
picked specifically because nobody had swept it, with every one of the
9 Newton iterates converging cleanly to a real residual
(`1e-11`-`1e-15`) and ZERO fallbacks needed** -- unlike every result in
the two tables above, where at least one config fell back at least
once. Every per-call residual was individually verified (table above),
not inferred from the aggregate.

Why this is bigger and cleaner than B8/B9's results, and not a
coincidence: `solve_equilibrium`'s system is SCALAR (one unknown, psi,
per node -- see this section's opening paragraph), so ILU is the
*only* preconditioner in play; there is no block-Jacobi/schur
ambiguity, no ranking to invert, and none of the psi/n/p coupling that
made B8's ILU setup cost dominate its whole solve (Phase A's B8
finding above). A scalar Poisson system's Jacobian is closer to a
textbook elliptic operator than a coupled drift-diffusion system's is,
which is exactly the regime ILU is strong in -- consistent with, not
contradicting, the device3d.py:594-610 comment's own finding that a
LATER Newton iterate on a DIFFERENT device (a 3D resistor) failed to
converge in 500 bicgstab iterations: different device, different
doping profile, different conditioning. This result does not
contradict that comment; it says the failure mode described there is
not universal to every structured 3D equilibrium solve, which is
exactly why Phase A's job was to measure rather than extrapolate from
one prior anecdote either way.

**Consequence for Phase E's scope, stated as the plan's section 4
already anticipated:** "If 3D structured behaves like 3D unstructured,
Phase E's scope grows considerably." It does, more dramatically than
B9 did -- B4's absolute time saved (177s per solve) dwarfs B9's (7.2s)
and B8's (net negative, direct still wins), and B4's config needed no
fallback at all across a full Newton solve, which is the strongest
single-fixture evidence in this whole study for actually changing a
default (Phase E), not just making the option reachable (Phase B).
This is still ONE case, ONE machine, ONE doping profile, and it is a
Poisson-ONLY equilibrium solve, not the coupled bias solve
`solve_bias` performs at `device3d.py:1017` (Gate D-1's "every fixture
in tests/, not the benchmark cases" requirement stands unchanged) --
but it is the strongest number in the plan, and Phase D's rule needs to
be built to find it, not just the smaller unstructured wins.

### Phase B -- make the choice expressible

`NewtonOptions` gains `precond: str = "auto"` and
`block_size: int | None = 3`, threaded through every `solve_linear` call
site that currently hardcodes them.

*Gate B-1:* with the defaults, every core is **bit-identical** to
today on every existing fixture, and no golden moves. The defaults are
chosen to reproduce exactly what the call sites hardcode now, so this
phase is a pure widening of the API surface.

*Gate B-2:* `precond`/`block_size` are validated at the
`NewtonOptions` boundary the way `driving_force` already is
(`device.py:303` raises `NotImplementedError` rather than silently
no-op'ing) -- an unknown preconditioner must refuse, not be ignored.
This project has been bitten by a silently-ignored option once already:
it is the reason P5-0 exists.

#### Phase B -- LANDED 2026-09-10

`NewtonOptions` gained `precond: str = "auto"` and
`block_size: int | None = 3`, plus a `__post_init__` that raises
`ValueError` for an unknown `precond` (validated against
`linsolve._PRECOND` exactly, gated so the two can never drift apart) or
a `block_size` that is neither `None` nor a positive int -- Gate B-2.
Threaded into the five call sites that hardcoded `block_size=3`:
`device.py` (Device1D `solve_bias`), `device2d.py` (Device2D
`solve_bias`), `device3d.py` (Device3D `solve_bias`), `unstructured_dd.py`
(`solve_bias`), `unstructured_dd3d.py` (`solve_bias3d`). The SCALAR
Poisson-equilibrium call sites (`solve_equilibrium` on all three
dimensionalities, `unstructured_poisson.py`, `moscap.py`) are
deliberately untouched -- they never hardcoded a block size (there is
no psi/n/p interleaving to block on), so widening the API there would
mean threading a field that does not apply, not fixing a gap.

**Gate B-1, the reconstruct-and-compare record** (the protocol this
file's own CLAUDE.md governs): before the edit, every file under
`tests/goldens/` was md5-summed. The edit was then made, and the
regeneration run accidentally DELETED the pre-edit goldens first
(`rm -f` before regenerating, rather than regenerating over them) --
including `frozen_meshes.npz`, which four other golden tests depend on
and which itself has no regeneration path (it is reconstructed from
`graded_mesh()`/`np.linspace()` calls matching "geometrically
equivalent" fixtures elsewhere in `tests/test_m13_solver.py`, the same
recovery this project's own history required once already, 2026-09-03,
per `test_m13_goldens.py`'s own docstring). Reconstructed
`frozen_meshes.npz` from that same convention
(`diode1d_x` from `_step_device`'s `graded_mesh(2.0e-4, [1.0e-4],
h_min=1.0e-8, h_max=1.0e-6, ratio=1.12)`; `diode2d_x`/`diode2d_y` from
`_step2d`'s `graded_mesh(1.0e-4, [0.5e-4], 4e-7, 4e-6, 1.25)` /
`graded_mesh(0.3e-4, [0.0], 4e-7, 4e-6, 1.25)`; `resistor3d_y` as
`np.linspace(0.0, 0.4e-4, 5)`, the one key with no exact match
elsewhere in the tree, chosen for consistency with the zero-doping
resistor's own already-uniform x/z spacing -- recorded here as a
documented choice, not a rediscovery), regenerated all four m13 golden
files with `PYTCAD_REGEN_M13_GOLDENS=1` against the POST-Phase-B code,
and re-summed:

| file | pre-edit md5 | post-edit md5 |
|---|---|---|
| `frozen_meshes.npz` | `ce5850ecaf56ee0db5e05be4d9b17a80` | `ce5850ecaf56ee0db5e05be4d9b17a80` |
| `diode1d_eq.npz` | `f78dd28dbd24b39f6995e423d59e24cc` | `f78dd28dbd24b39f6995e423d59e24cc` |
| `diode1d_fwd.npz` | `36662794eb2f849ac6263f23921ebb86` | `36662794eb2f849ac6263f23921ebb86` |
| `diode2d_eq.npz` | `f31b42c7b4cded7d10ff0831d92f8174` | `f31b42c7b4cded7d10ff0831d92f8174` |
| `hetero1d_eq.npz` | `a2791e63f070ae749ae5bc11fde99ed1` | `a2791e63f070ae749ae5bc11fde99ed1` |
| `resistor3d_eq.npz` | `7b2e8ad51672c9fd66ec26b30d88446e` | `7b2e8ad51672c9fd66ec26b30d88446e` |

**All six identical, including the reconstructed `frozen_meshes.npz`
itself** -- the reconstruction reproduced the exact bytes of the file
it replaced, which is stronger evidence than "regenerating from the
same recipe usually agrees": on this machine, with this numpy/scipy
build, it agreed byte-for-byte. Combined with the diode1d forward-bias
golden's own bit-identity (the one fixture that actually exercises the
call site Phase B changed, `device.py`'s coupled `solve_bias`), this is
the reconstruct-and-compare proof Gate B-1 asks for: the pre-edit and
post-edit behavior are the SAME computation, not merely close.

Also landed: `tests/test_m31_p51_phase_b.py` (22 gates) -- defaults
match the old hardcoding; every one of the five coupled call sites
demonstrably threads a non-default `block_size`/`precond` to
`solve_linear` (via a spy that still performs the real solve, so
physics is unaffected -- deliberately mismatched values are used to
prove reachability, not to prove convergence, since an odd block size
is not expected to converge and the loops without Phase C's fallback
(all but `device3d.py`) would otherwise raise before any assertion
ran); the structured 3D equilibrium solve is confirmed to NEVER receive
a non-None `block_size` even when one is requested, proving the
scalar/coupled asymmetry holds in code, not just in the docstring;
every `NewtonOptions.precond`/`block_size` validation path raises
`ValueError` as designed, and `linsolve._PRECOND`'s own tuple is
checked to still match `NewtonOptions`'s accepted set exactly.

`PYTCAD_ACCEL=0`: 1503 passed / 10 skipped / 1 xfailed / 39 warnings.
`PYTCAD_ACCEL=1`: 1533 passed / 2 skipped / 1 xfailed / 39 warnings --
more passes and fewer skips under ACCEL=1 is the expected shape
(compiled-extension-conditional tests un-skip), not a discrepancy;
zero `FAILED`/`ERROR` lines in either run's full log, confirmed by
grep rather than by reading the summary line alone. Warning count (39)
identical both ways, matching the suite's own "N passed, zero
[unexpected] warnings" invariant. Nothing in `pytcad/*.py` moved except
the six call sites and the `NewtonOptions` dataclass itself; no other
module was touched.

### Phase C -- fallback parity

Give the four unstructured loops the structured cores' try/except
degrade, including its `if opts.linsolve == "direct": raise` guard so a
direct failure still surfaces.

*Gate C-1:* a solve whose iterative method fails on iteration k
completes, with a result `np.array_equal` to the all-direct solve when
every iteration falls back.
*Gate C-2:* the fallback is **reported**, not silent -- the returned
scale/diagnostics dict records how many iterations fell back. A quiet
fallback turns a 10x speedup claim into a lie in the cases where it
degraded, and this milestone's whole output is a performance claim.

#### Phase C -- LANDED 2026-09-10

All four unstructured loops (`unstructured_poisson.solve_poisson_equilibrium`,
`unstructured_dd.solve_bias`, `unstructured_dd3d.solve_poisson_equilibrium3d`,
`unstructured_dd3d.solve_bias3d`) gained the identical
try/except/`if opts.linsolve == "direct": raise` shape
`device.py`/`device2d.py`/`device3d.py`'s own equilibrium and (for
`device3d.py`) coupled loops already used -- copied structurally, not
reinvented, so there is exactly one fallback pattern in the tree rather
than five slightly different ones. Each function's returned dict
(`scale` for the two coupled `solve_bias`/`solve_bias3d` functions, the
plain scaling dict for the two equilibrium functions) gained
`linsolve_fallbacks: int`, zero by default (`opts.linsolve="direct"`
never enters the except branch, so this key's addition is the only
change to the return shape and no existing key moved).

**Gate C-1 and C-2, both confirmed** by
`tests/test_m31_p51_phase_c.py` (6 gates): each of the four loops is
driven once with `opts.linsolve="direct"` (`linsolve_fallbacks == 0`,
confirmed) and once with a monkeypatched `solve_linear` that raises
`LinearSolveError` immediately for any non-"direct" method --
deterministically forcing 100% fallback on every Newton iterate without
needing a genuinely ill-conditioned fixture (Phase A already showed
that is fixture- and iterate-dependent, not reliably reproducible on
demand). The 100%-fallback result is `np.array_equal` to the all-direct
result in every case (Gate C-1), and `linsolve_fallbacks > 0` confirms
the count is not silently dropped (Gate C-2). A fifth pair of tests
confirms the `if opts.linsolve == "direct": raise` guard itself: when
`opts.linsolve="direct"` and even THAT fails, the error propagates
rather than looping or being swallowed.

**A real regression caught and fixed before it reached the fast dev
loop, not after:** Phase B's own gate file
(`tests/test_m31_p51_phase_b.py`) originally forwarded a deliberately
mismatched `block_size=7` to the REQUESTED iterative method to prove
the value reached `solve_linear` -- which made scipy's `gmres` actually
attempt to converge (up to `maxiter * restart` inner iterations, per
Phase A's own finding about this exact scipy version's `gmres`/
`restart` interaction) before failing. Confirmed directly: this
ballooned the combined P5-0/P5-1 test files from ~15s to over 600s, and
the full `-m "not slow"` suite this milestone's own commands run before
every claim would have silently absorbed that cost forever. Fixed by
rewriting the spy to always execute via `method="direct"` while still
recording the REQUESTED kwargs -- the plumbing check needs the request
to be observed, not the (nonsensical) request to actually run. Full
suite re-timed after the fix: `PYTCAD_ACCEL=0` 1531 passed / 10 skipped
/ 1 xfailed / 39 warnings in 345.6s -- matching the pre-Phase-C
baseline's shape (previously 1503/10/1/39 in ~360s), not the 600s+
regression. `PYTCAD_ACCEL=1`: 1539 passed / 2 skipped / 1 xfailed / 39
warnings in 346.4s. Zero `FAILED`/`ERROR` lines in either full log,
confirmed by grep. The pass-count deltas (+28 ACCEL=0, +34 ACCEL=1
versus the pre-Phase-B baseline) are exactly the new gate files' sizes
(22 Phase B + 6 Phase C = 28, plus ACCEL=1's usual extra
compiled-extension-conditional passes) -- accounted for, not a
surprise.

### Phase D -- the selection rule

Only after A. The rule is expected to key on dimension and problem
size, but the shape must come from the data.

**This is the phase that can be silently wrong, and the precedent is
in-tree.** CLAUDE.md records the M22 MPI-Schwarz split-axis picker: a
safety gate built from ONE physical hazard (doping gradient) that
correctly cleared an axis a DIFFERENT hazard (a GateBC's Robin coupling
along its own normal axis) made unsafe -- producing a result that was
both wrong (1.4e-3 relative field error) and slower, on a device the
existing check judged safe. The fix was a second, independent
exclusion, not a tweak to the first.

So Phase D's gates are written against that failure mode:

*Gate D-1:* the rule's chosen method agrees with `direct` to the
machine-precision standard section 1 already demonstrated
(`|dpsi| <= 1e-14`, terminal currents to `1e-12` relative) on **every**
fixture in `tests/`, not on the benchmark cases it was tuned against.
*Gate D-2:* the rule is asked, for each fixture, what it would choose
and why, and the answer is asserted -- so a rule that happens to pick
correctly for the wrong reason is visible.
*Gate D-3:* an explicit **refusal path**: a configuration the rule has
no evidence for selects `direct` rather than guessing. "No opinion"
must be representable.

#### Phase D -- LANDED 2026-09-10

`linsolve.select_auto(dim, unstructured, coupled, dof)` -- a pure
function, never raises, never touches a matrix -- resolves
`NewtonOptions.linsolve="auto"` to a concrete method from a small
evidence table (`_AUTO_EVIDENCE`) keyed on exactly the three
`(dim, unstructured, coupled)` tuples Phase A actually measured:

| tuple | case | method | min DOF (that case's OWN "quick" size) |
|---|---|---|---|
| (3, False, False) | B4 | `petsc` | 4,913 |
| (3, True, True) | B9 | `petsc` | 2,889 |
| (2, True, True) | B8 | `direct` | 0 (measured, not absent) |

Every OTHER tuple -- notably dim=1 entirely, every 2D/3D STRUCTURED
coupled-bias configuration, and both SCALAR unstructured equilibrium
paths -- has NO entry, and `select_auto` returns `("direct", reason)`
naming the absence explicitly (Gate D-3). B8's entry is deliberately
NOT an absence: its reason string says `MEASURED`, distinct from the
generic "no Phase A measurement exists" text the other refusals carry
-- Gate D-2 requires the reason to be checkably true, and "direct wins
here" and "nobody has looked" are different claims that must not read
the same. Below an entry's own `min_dof` (B4/B9's own "quick" size,
not a separately chosen threshold), the rule ALSO refuses to direct
rather than extrapolating below the smallest size it has real evidence
for.

**Wired into every call site that dispatches on `opts.linsolve`** (9
in total: `device.py`'s coupled `solve_bias`; `device2d.py`'s coupled
`solve_bias`; `device3d.py`'s scalar `solve_equilibrium` AND coupled
`solve_bias`; `unstructured_poisson.solve_poisson_equilibrium`;
`unstructured_dd.solve_bias`; both loops in `unstructured_dd3d.py`),
each resolving ONCE per solve (dof is constant across a Newton
sequence) rather than per iterate, and passing its own static
`(dim, unstructured, coupled)` -- a fact of which function it is, not
something inferred from the matrix. `Device1D`/`Device2D`/`Device3D`
gain `last_auto_method`/`last_auto_reason` instance attributes after a
call; the four unstructured functions gain `auto_method`/`auto_reason`
keys in their returned dict (both `None` when `opts.linsolve` was not
`"auto"`) -- Gate D-2's "the answer is asserted" made checkable from
outside, not just printed under `opts.verbose`.

Two call sites (`Device1D`/`Device2D`'s `solve_equilibrium`) were
**deliberately left untouched**: both already hardcode `method="direct"`
unconditionally and have never read `opts.linsolve` at all (a
pre-existing simplification, not something this phase's scope covers)
-- wiring `"auto"` in there would be inventing a knob nothing currently
turns, not fixing a gap.

**A scope discipline enforced while wiring this in:** `device.py`'s
coupled `solve_bias` and `device2d.py`'s coupled `solve_bias` had NO
Phase-C-style fallback before this phase (unlike `device3d.py`'s own
coupled loop and the four unstructured loops) -- an uncaught
`LinearSolveError` from an explicit non-`"direct"` `opts.linsolve` was,
and remains, their existing behavior. Since dim=1 and 2D-structured
have no evidence entries, `"auto"` always resolves to `"direct"` at
those two sites regardless, so this phase did NOT retrofit a Phase-C
fallback there -- doing so would have been an unrequested behavior
change for any caller already passing an explicit iterative
`opts.linsolve` value outside `"auto"`, silently swallowing an error
that caller may have relied on seeing.

**Gates D-1/D-2/D-3, all confirmed** by `tests/test_m31_p51_phase_d.py`
(17 gates): every evidenced tuple returns its own method with a
matching reason at its floor; every unmeasured tuple (including ones
that superficially resemble a measured one, e.g. 2D STRUCTURED coupled
next to B8's 2D UNSTRUCTURED coupled) refuses; below-floor refuses with
a reason naming the original evidence AND the shortfall; B8's refusal
reads as measured, not absent. Two END-TO-END gates go beyond the
lookup table to the real solves Gate D-1 actually asks for: `auto` on a
5,832-DOF `Device3D` (above B4's floor) resolves to `petsc` and agrees
with `direct` to `<= 1e-14`; `auto` on a full-size B9-shaped 3D
unstructured mesh resolves to `petsc` and agrees with `direct` to
`<= 1e-12`. A third confirms `Device1D`'s 1D coupled solve is
bit-identical under `"auto"` and `"direct"` (both resolve to the same
call). Reconstruct-and-compare: all 6 `tests/goldens/m13/*.npz` files
came back md5-identical after the edit -- the default (`"direct"`)
path is untouched everywhere, exactly as the "wired in but always
refuses" design for every unevidenced call site requires.

### Phase E -- defaults

Two options, and the plan deliberately does not pre-commit:

* **E-opt-in:** the default stays `direct` everywhere; the rule is
  reachable as `linsolve="auto"` and documented with section 1's table.
  Nothing existing changes behaviour. Cheapest, and the honest choice
  if Phase A's per-iterate data is noisy.
* **E-auto:** `linsolve="auto"` becomes the default above a size
  threshold. This is a **behaviour change for every existing caller**,
  including the GUI and every `examples/` script, and it re-baselines
  nothing but changes timings and failure modes. It needs its own
  sign-off, and it should not ride along inside this milestone.

#### Phase E -- LANDED 2026-09-10 as E-opt-in; E-auto NOT taken

**E-opt-in is what landed, and it required no code of its own** --
`NewtonOptions.linsolve` already defaulted to `"direct"` before this
milestone, Phase D never touched that default, and Phase D's own
reconstruct-and-compare (all 6 `tests/goldens/m13/*.npz` md5-identical)
is the direct evidence that nothing existing changed behavior. The one
piece of actual E-opt-in work was documentation: `NewtonOptions`'s
`linsolve` field comment (`device.py`) now states the "auto" contract
and points at `linsolve.select_auto`'s evidence table, so a reader
finds it from the option itself, not only from this plan.

**E-auto was deliberately NOT taken, per this section's own written
guardrail.** The case against taking it now is stronger than "process
says wait": Phase A found evidence for exactly THREE
`(dim, unstructured, coupled, size)` cells, one of them (B8) an
explicit "direct wins" result -- flipping the default above some size
threshold today would mean guessing a threshold for the many cells
Phase D's own evidence table refuses to have an opinion about (every
2D/3D structured coupled-bias configuration, all of 1D, both scalar
unstructured equilibrium paths), which is precisely the failure mode
Phase D's gates were built to catch, not something to reintroduce at
the default-value layer one phase later. E-auto remains available to
propose separately, with its own sign-off, if and when more of Phase A's
matrix gets measured (starting with `device3d.py`'s coupled `solve_bias`
and structured 1D/2D, the combinations section 4's own Phase D writeup
names as unmeasured).

## 5. What this is worth, stated honestly

Phase A ran (see section 4's own subsections for the full tables), and
it changed this section's answer twice over from what section 1 alone
suggested:

* **B8 (2D unstructured): the prize is smaller than section 1 implied,
  possibly zero.** Section 1/2's single-Jacobian sweep found "ILU"
  converging in 3-4 iterations and read as a 2D win; the WHOLE-SOLVE
  measurement shows direct (3.43s) beats every iterative configuration
  Phase A tried, including that config (8.41s) -- isolated and timed
  directly on B8's own Jacobian, preconditioner construction (which
  this environment's installed `pyamg` makes an AMG setup, not a
  literal `spilu`, per `_build_preconditioner`'s own fallback order)
  costs 0.653s of every 0.701s call, 93%, paid fresh every Newton
  iterate with no reuse. The plan's own section 7 anticipated exactly
  this ("the plausible outcome for 2D is 'direct stays'"); it is now
  measured, not merely allowed for, and section 4's B8 subsection has
  the isolated-timing evidence.
* **B9 (3D unstructured): confirmed, independently.** `gmres/
  block_jacobi` (2.59s) and `petsc` (0.68s) both beat direct's 7.85s,
  reproducing section 1's 10.6x finding with a different `maxiter` and
  a full Newton sequence rather than one matrix.
* **B4 (3D STRUCTURED equilibrium): the largest prize in this plan,
  and not one section 1 predicted at all.** 179s -> 1.5-2.2s, 82x-119x,
  every iterate converging with no fallback -- see section 4's B4
  subsection for the full table and why a scalar Poisson system is a
  cleaner case for ILU than either unstructured core's coupled system.

So the milestone's center of gravity has moved: the strongest case for
Phase D/E is now the STRUCTURED 3D equilibrium path, not the
unstructured path this plan was originally scoped around. That is a
real scope question for whoever signs off Phase B onward, not a detail
to fold in quietly -- B4's win is bigger, cleaner (no observed
fallback), and sits in code this plan did not center itself on.

What it is NOT: a scaling claim. Nothing here touches MPI, GPU or
`DMPlex` (M31 P7), and section 36 forbids claiming HPC-readiness from a
single-machine table. This milestone makes the existing solver stack
*reachable and correctly configured*, which is a different and smaller
claim than making it fast at scale.

## 6. Relationship to P5 proper

P5's exit criterion (`M31-P5-ASSEMBLY-NEWTON-PLAN.md` section 9) asks
whether assembly is worth porting to C++. After P5-0 the linear solve
is 92% of B8 full and 98% of B9 full. **P5-1 attacks that 92-98%
directly, in Python, with no bit-identity budget spent** -- and if it
succeeds, it shrinks the denominator again and makes the C++ assembler's
share *larger* without making the assembler more valuable in absolute
terms.

That is worth saying plainly so it is not mistaken for progress toward
P5: a percentage that rises because the rest got faster is not evidence
that the remainder is worth porting. P5's decision should be re-taken on
absolute milliseconds after P5-1, using the same B8/B9 rows.

## 7. Honest limits

* Section 2's sweep was **one Jacobian per core**; Phase A (section 4)
  ran the full per-iterate sweep this bullet originally called for, and
  it changed section 5's conclusion twice (B8 shrank to near-zero, B4
  emerged as the largest single result) -- exactly the correction this
  bullet anticipated, now landed rather than pending.
* Every number here is one machine, one BLAS, one PETSc build, one
  scipy version (1.17.1) whose `gmres`/`maxiter` interaction with
  `restart` was itself a source of a real measurement bug this plan
  caught and corrected (section 4's B8 subsection) -- a different scipy
  version could plausibly change what `maxiter` even means for that
  call, not just the ranking. The preconditioner ranking is a property
  of the matrices AND the implementations; conda-forge PETSc on another
  machine may rank them differently, and the rule must be
  re-measurable rather than hard-coded from this table.
* `bicgstab` genuinely fails (residual diverging across Newton
  iterates, not merely slow) on B8's schur config and B9's ILU config
  at full size -- confirmed by the `maxiter=1000` recheck in section 4,
  which is what distinguishes it from `bicgstab/block_jacobi`'s
  full-size failure, which WAS a `maxiter` artifact and converges fine
  once corrected. Not every `bicgstab` failure in this plan is the same
  kind of failure; section 4 records which is which.
* B8 (2D unstructured) is now NEGATIVE evidence, not an open question:
  Phase A's whole-solve measurement found direct (3.43s) beats every
  iterative configuration tried, including the ILU config section 2's
  single-Jacobian sweep favored (8.41s, slower). "Direct stays" for B8
  is the Phase A finding, not merely the plausible default this section
  guessed at before the sweep ran.
* B4's 82x-119x result (section 4/5) is **one device, one doping
  profile, Poisson-equilibrium only** -- it says nothing yet about
  `solve_bias`'s coupled 3D solve (`device3d.py:1017`, block_size=3,
  the same structure as B8/B9's coupled systems), which is a separate,
  unmeasured question Phase A did not reach.
