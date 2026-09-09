# M32 -- Benchmark suite and performance dashboard

Status as of 2026-09-09: **LANDED.**

Implements `Architecture_Master_Plan.md` sections 34 (cases B1-B7) and 35
(the dashboard), so that section 36's rule becomes enforceable rather
than aspirational.

`benchmarks/README.md` is the usage guide and the authority on what each
column means. This document is the plan record: why the milestone
exists, what it deliberately does not do, and what gates it.

---

## 1. Why

Section 36:

> Never use "The solver is HPC-ready." unless the benchmark proves
> correctness + scaling + memory behavior + reproducibility.
> Performance claims belong in benchmark tables, not marketing language.

Before M32, **nothing in the repo could satisfy that rule.** Not for lack
of measurement -- this project measures unusually carefully -- but
because every measurement was a one-off. M31's own phase ordering rests
on a profile (98% of a 24^3 solve in `_superlu.gssv`; 206,763 unknowns in
4.71 s) that exists as prose in a plan document and cannot be re-run. P2
reports 41x/25x/539x, P3b reports 3.30 ms vs 3.38 ms, P4 reports
835x/874x/123x. All real, all taken by hand, none reproducible after the
code moves.

That is a drawer of numbers with a shelf life, and `ARCHITECTURE.md` 4c.2
predicted the consequence: *"Building the dashboard after the thing it is
meant to police is the standard way to end up with unfalsifiable
numbers."*

**M32 landed after P4 rather than before it**, against 4c.3's own spine.
The cost is exactly what 4c.3 warned about and is recorded rather than
glossed: P2's, P3b's and P4's headline figures were measured by hand and
should be re-measured through the harness before being quoted again.

---

## 2. What landed

```
pytcad/benchmarks/
  cases.py       B1-B7, each at two sizes
  instrument.py  the probes -- timing/counting without touching the core
  harness.py     run a case, collect a Row, record the environment
  dashboard.py   render the section-35 table as markdown
  __main__.py    python -m benchmarks
  README.md      usage + what every column means
  BASELINE.md    a checked-in reference run (quick size, best of 3)
  BASELINE.json  the same, machine-readable
  FULL.md        a full-size run of this tree (~6 min)
  FULL.json      the same, machine-readable
tests/test_m32_benchmarks.py   19 gates (18 fast + 1 slow)
```

### The design decision that matters

**The instrumentation does not touch the numerical core.** Section 35
wants per-phase timings, and the obvious implementation is timers inside
`device.py`/`device2d.py`/`device3d.py`. That was rejected twice over:
those files are the frozen core (edits need the M11-S3 amendment
mechanism -- sign-off, goldens first, FD-Jacobian-first -- a
disproportionate price for a stopwatch), and it would put timing code on
the hot path of every solve the project ever runs.

Instead the probe temporarily wraps the functions the solver *already*
calls: `linsolve.solve_linear`, each core's own imported `spsolve` (they
differ -- `device2d.py:984` calls `spsolve` directly where other paths go
through `solve_linear`, and patching only one silently reports zero), and
the instance's `_residual_jacobian`. Patching is confined to a context
manager and undone in a `finally`.

Two properties are gated rather than asserted: nothing stays patched
after the block (including when the body raises), and a probed solve is
**bit-identical** to an unprobed one.

---

## 3. Honest limits

Three of section 35's columns are **not** reported as specified. Each
would require either a core amendment or a fabricated number, and a
right-looking heading over a wrong number is precisely what section 36
exists to prevent.

| section 35 asks for | what is reported | why |
|---|---|---|
| "Residual time" and "Jacobian time" | one `assembly` column | `_residual_jacobian` computes both in one pass and returns both; from outside it there is no way to attribute the cost, and a split would be invented |
| "Newton iterations" | `asm calls` | no core solve method exposes an iteration count (checked, not assumed); assembly calls equal Newton iterations only when no backtracking occurred |
| "Memory" | `py peak MB` | `tracemalloc` sees Python-level allocation; SuperLU's LU factors -- usually dominant -- live in its own arena, as do BLAS scratch and PETSc's. A floor, not a measurement |

The first becomes reportable honestly at P5, when the C++ assembler has
residual and Jacobian as separate entry points. The second needs a core
amendment and should ride along with whatever next touches those files
under the amendment mechanism, not be forced through on its own.

**Not implemented from section 35:** strong/weak scaling, parallel
efficiency, communication time, and the GPU column set. Those need
mpi4py/CuPy runs and a multi-configuration sweep, which is a second
milestone's worth of work; the case declaring them (B7) says so in its
notes rather than showing empty columns as if they had been measured.

**Two cases do less than their section-34 description.** B5 (SiC) runs
equilibrium only -- no avalanche or thermal coupling. B6 is a **2D
AlGaAs/GaAs** heterostructure, not a 3D GaN HEMT, because no GaN device
exists anywhere in the tree; it stresses what the case is for (a material
discontinuity through the solver) but it is not a GaN device, and when a
real one exists the case should be repointed rather than the label
widened. Both are stated in the case docstrings, in the rendered report's
Notes section, and in the README table.

**These are not physics gates.** A case asserts only that its solve
converged. Correctness is `tests/`'s job. A benchmark that also tried to
be a physics gate would eventually have its tolerance widened to keep
the timings running.

---

## 4. Gates

`tests/test_m32_benchmarks.py`, 19 tests (18 in the fast suite, 1
slow-marked end-to-end CLI run). In order of how badly a failure would
hurt:

1. **The probe restores every patch** -- including when the body raises,
   and including the instance attribute that shadows a class method
   (restoring that means *deleting* it, not assigning the bound method
   back). A leaked wrapper would stay on `linsolve.solve_linear` for the
   rest of the process and mis-measure every later solve in the same
   pytest session.
2. **A probed solve is bit-identical to an unprobed one**
   (`np.array_equal` on the converged `psi`). Instrumentation is a
   stopwatch, not a code path.
3. **Every case builds and runs**, parametrized so a break names the
   case. Asserts a real measurement was taken (DOF > 0, NNZ > DOF, at
   least one linear solve) rather than asserting a time -- a timing
   threshold on CI hardware fails on a loaded runner and teaches
   everyone to ignore it.
4. **A failing case is a row, not an exception**, and a missing optional
   dependency **skips** rather than fails. An absent row reads as "not
   measured yet"; a skipped row reads as "cannot be measured here". Those
   are different facts and the table must not conflate them.
5. **The report keeps its caveats.** The three limits in section 3 are
   asserted to be present in the rendered markdown, so deleting them
   fails a test.

CI runs `python -m benchmarks` in the `accelerated` job and uploads the
report as an artifact. Deliberately **not** a timing gate: what CI proves
is that the suite still runs and still produces a dashboard, which is
what stops it rotting the way the G-E throughput floors silently did
(they ran nowhere at all for two phases -- see the P4 section of
`M31-CPP-ARCHITECTURE-PLAN.md`).

---

## 5. Baseline

`benchmarks/BASELINE.md`, quick size, best of 3, `OPENBLAS_NUM_THREADS=1`.
It is a reference point for "did this change make things worse", not a
published figure -- a published figure comes from `--size full` on a
quiet machine, and the report stamps which size it was so the two can
never be confused. `benchmarks/FULL.md` is a full-size run of the same
tree; it takes about six minutes, which is why it is not the default.

### The first thing the harness proved

The full-size run reproduces M31's own motivating measurement --
independently, and now repeatably:

| case | DOF | assembly | linear solve | total | solve share |
|---|---|---|---|---|---|
| B4 3D MOSFET (direct) | 68,921 | 148 ms | **178.82 s** | 178.99 s | **99.9%** |
| B7 large synthetic 3D (bicgstab) | 91,125 | 186 ms | 52.78 s | 52.98 s | 99.6% |

(the exact rows in `benchmarks/FULL.md`, so the claim is checkable
against the checked-in file rather than against this paragraph)

`M31-CPP-ARCHITECTURE-PLAN.md` opens with "structured 3D assembly is
**not** the bottleneck -- 98% of wall time in `_superlu.gssv`", measured
by hand at 24^3 on a profiler. B4 says 99.9% at 41^3 through the harness,
and B7 says the wall is algorithmic rather than linguistic: 32% MORE
unknowns solved in 30% of the time, purely by switching to an iterative
method.

A caution the harness taught immediately: a first attempt at this table
was taken while the test suite was running on the same machine, and came
out 9-12% high across every timed case (B4 199.5 s, B5 124.9 s, B7
59.2 s) with DOF and NNZ bit-identical. Timings here are only comparable
when the machine is otherwise idle, which is why `OPENBLAS_NUM_THREADS=1`
and a quiet box are documented as part of the procedure rather than as
advice.

That is the whole argument for M31's phase ordering, and for P5 being
last among the solver phases, now standing on something a future session
can re-run instead of on a number in a paragraph.

---

## 6. What next

* Re-measure P2/P3b/P4's headline numbers through the harness so they
  stop being hand-taken (section 1's recorded cost).
* Add the scaling/GPU columns when M31 P7 needs them -- that is the
  milestone that will actually make scaling claims, and section 36 says
  it may not make them without these.
* Revisit the residual/Jacobian split at P5.
