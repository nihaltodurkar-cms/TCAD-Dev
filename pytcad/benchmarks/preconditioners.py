"""M31-P5-1-SOLVER-SELECTION-PLAN.md Phase A: per-Newton-iterate
method/preconditioner sweep on the unstructured cores (B8, B9).

WHY THIS IS A SEPARATE MODULE FROM harness.py
----------------------------------------------
`harness.py`/`instrument.py` answer "how fast is the case today" -- one
number (or a few, best-of-`repeats`) per case, meant to be a per-commit
dashboard row. This module answers a different question: "which of
scipy/PETSc x {block_jacobi, ILU, schur} converges, and how does that
change ACROSS a single Newton solve's iterates" -- section 2 of the plan
found the ranking of a fixed preconditioner set INVERTS between B8 (2D)
and B9 (3D), and found the one Jacobian it swept there is not
representative of the whole solve (a 1.99s single-matrix gmres/
block_jacobi solve does not multiply out to B8's measured 117.8s
whole-solve time). That is a study, run occasionally, not a per-commit
row -- Architecture_Master_Plan.md section 36 still applies (no
performance number belongs in a plan or commit message unless it came
from a real run), it just does not belong in the dashboard table.

HOW THE PER-ITERATE MEASUREMENT WORKS
--------------------------------------
The unstructured cores (`unstructured_dd.py`, `unstructured_dd3d.py`)
hold their own `from .linsolve import solve_linear` module-local name
(P5-0), which this module patches per case, exactly like
`instrument.py` does for timing -- nothing in the frozen core is
touched. Unlike `instrument.py`, this patch also OVERRIDES the
`method`/`block_size`/`precond` the call site passes, so a sweep can
force e.g. "gmres + ILU" through code that hardcodes `block_size=3` --
that override is the only way section 3's gap (no core can currently
choose ILU for a coupled solve) can be measured before Phase B closes
it.

THE EMULATED FALLBACK IS A MEASUREMENT DEVICE, NOT A CODE CHANGE
------------------------------------------------------------------
Neither unstructured core has Phase C's per-iterate fallback yet (P5-1
plan section 3, item 3): today a non-converged iterative solve raises
out of the whole Newton loop, which means a config that fails on
iterate 3 of 12 produces NO data for iterates 4-12. This module's patch
catches that failure, records it, and falls back to `method="direct"`
FOR THAT ONE CALL ONLY so the Newton loop can keep going and later
iterates are still measured -- exactly the behavior Phase C is planned
to add for real. This is scaffolding inside the sweep harness, invoked
only from this file; it does not change `unstructured_dd.py` or
`unstructured_dd3d.py`, and every fallback is recorded (`fell_back`),
never silent.

WHAT IS BOUNDED, AND WHY
--------------------------
Section 2 already measured one schur config taking 357s to FAIL a
single linear solve at `maxiter=500`. A 12-iterate Newton loop with
that failure mode at every iterate would cost approaching an hour for
one (case, size, config) cell. Two independent caps exist so a sweep
finishes in bounded time and says so rather than hanging:

  * `maxiter` (default 200, not solve_linear's default 500) bounds a
    single failing iterative solve.
  * `budget_s` (default 180) is a wall-clock cap per (case, config):
    once exceeded, the remaining Newton iterates of that config are
    not run and the result says `aborted="budget exceeded"` -- an
    honest "not measured" rather than a truncated number presented as
    complete.

Neither cap changes what a config that DOES converge reports; they only
bound how long this module spends confirming that one does not.

`maxiter` DOES NOT MEAN THE SAME THING FOR EVERY METHOD
----------------------------------------------------------
Confirmed directly (M31-P5-1-SOLVER-SELECTION-PLAN.md Phase A, first
full-size run): `linsolve.solve_linear`'s `gmres` branch passes
`maxiter` straight to `scipy.sparse.linalg.gmres`, which in the scipy
on this machine (1.17.1) treats it as a count of RESTART CYCLES, not
total iterations -- with `restart=100` (this module's default), a
`maxiter=200` request let one config run to 2025 actual iterations
before converging, an ~10x-100x larger effective budget than the same
`maxiter` gives `bicgstab` (no restart concept, so `maxiter` there is a
literal total-iteration cap) or `method="petsc"` (PETSc's
`KSP.setTolerances(max_it=maxiter)` is also literal). A sweep that uses
one `maxiter` value across all four methods is therefore NOT
apples-to-apples unless it is generous enough that none of
bicgstab/petsc is starved by it -- which is why this module's default
is 2000, not the smaller value an earlier run used and had to correct
afterward (see the plan's "Phase A -- FULL-SIZE RESULTS" section for
the specific numbers that turned out to be a starvation artifact, not a
finding about the method). `budget_s` is the fair, method-independent
constraint; `maxiter` is not, and should be set generously with
`budget_s` doing the real bounding.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from dataclasses import asdict, dataclass, field

import numpy as np
import scipy

from pytcad import linsolve as _linsolve
from pytcad.linsolve import LinearSolveError

from .cases import get

# label, method, block_size, precond -- see module docstring.
CONFIGS = [
    ("direct", "direct", None, "auto"),
    ("gmres/block_jacobi", "gmres", 3, "block_jacobi"),
    ("gmres/ilu", "gmres", None, "auto"),
    ("gmres/schur", "gmres", 3, "schur"),
    ("bicgstab/block_jacobi", "bicgstab", 3, "block_jacobi"),
    ("bicgstab/ilu", "bicgstab", None, "auto"),
    ("bicgstab/schur", "bicgstab", 3, "schur"),
    ("petsc", "petsc", 3, "auto"),
]

# Which module(s) hold the `solve_linear` name this case's Newton loop
# actually calls -- see the P5-0 module-local-import note in the
# docstring above. B8's case exercises unstructured_dd only (the
# Poisson-only module is a separate, un-benchmarked entry point);
# B9's exercises unstructured_dd3d, whose solve_bias3d calls its own
# equilibrium sub-solve first, through the same module-local name.
CASE_MODULES = {
    "B8": ("unstructured_dd",),
    "B9": ("unstructured_dd3d",),
}


@dataclass
class IterRecord:
    call_index: int
    seconds: float
    converged: bool
    iterations: int
    residual: float
    fell_back: bool
    error: str = ""


@dataclass
class ConfigResult:
    label: str
    method: str
    block_size: object
    precond: str
    records: list = field(default_factory=list)
    total_s: float = 0.0
    aborted: str = ""

    def as_dict(self):
        d = asdict(self)
        return d


def _sweep_one(case_name, size, label, method, block_size, precond,
               maxiter, budget_s):
    """Run one (case, size, config) cell, patching every module this
    case's Newton loop reaches `solve_linear` through."""
    case = get(case_name)
    _, run = case.build(size)

    result = ConfigResult(label=label, method=method, block_size=block_size,
                          precond=precond)
    call_index = [0]
    t_start = time.perf_counter()

    def swept_solve_linear(A, b, **kwargs):
        # Ignore the caller's own method/block_size/precond/rtol=default
        # choice for everything the sweep controls; keep whatever else
        # it passed (x0, restart, maxiter override) except maxiter,
        # which this sweep bounds itself.
        idx = call_index[0]
        call_index[0] += 1
        if time.perf_counter() - t_start > budget_s:
            result.aborted = result.aborted or "budget exceeded"
            raise LinearSolveError("preconditioners.py: budget exceeded")
        rtol = kwargs.get("rtol", 1e-10)
        t0 = time.perf_counter()
        try:
            x, info = _linsolve.solve_linear(
                A, b, method=method, rtol=rtol, maxiter=maxiter,
                block_size=block_size, precond=precond)
            dt = time.perf_counter() - t0
            result.records.append(IterRecord(
                call_index=idx, seconds=dt, converged=True,
                iterations=info.get("iterations", 1),
                residual=info.get("residual", float("nan")),
                fell_back=False))
            return x, info
        except LinearSolveError as exc:
            dt = time.perf_counter() - t0
            if method == "direct":
                # direct has no fallback to fall back TO; record and
                # re-raise so the Newton loop fails honestly, exactly
                # as it does today.
                result.records.append(IterRecord(
                    call_index=idx, seconds=dt, converged=False,
                    iterations=0, residual=float("nan"), fell_back=False,
                    error=str(exc)))
                raise
            # Emulated Phase-C fallback -- see module docstring. Falls
            # back to direct so later iterates are still measured; the
            # failure and its cost are both recorded, never hidden.
            t1 = time.perf_counter()
            xd, infod = _linsolve.solve_linear(A, b, method="direct")
            dt_fb = time.perf_counter() - t1
            result.records.append(IterRecord(
                call_index=idx, seconds=dt + dt_fb, converged=True,
                iterations=infod.get("iterations", 1),
                residual=infod.get("residual", float("nan")),
                fell_back=True, error=str(exc)))
            return xd, infod

    modules = []
    for modname in CASE_MODULES[case_name]:
        mod = __import__(f"pytcad.{modname}", fromlist=["_"])
        modules.append(mod)
    undo = []
    for mod in modules:
        old = getattr(mod, "solve_linear", None)
        if old is None:
            continue
        setattr(mod, "solve_linear", swept_solve_linear)
        undo.append((mod, old))
    try:
        run()
    except LinearSolveError as exc:
        result.aborted = result.aborted or f"Newton loop raised: {exc}"
    except Exception as exc:  # noqa: BLE001 -- a study script must not
        # let one config's unexpected failure kill the whole sweep; the
        # failure itself is the data point.
        result.aborted = result.aborted or f"{type(exc).__name__}: {exc}"
    finally:
        for mod, old in undo:
            setattr(mod, "solve_linear", old)

    result.total_s = time.perf_counter() - t_start
    return result


def run_sweep(cases, sizes, configs=CONFIGS, maxiter=200, budget_s=180.0):
    out = []
    for case_name in cases:
        for size in sizes:
            for label, method, block_size, precond in configs:
                sys.stderr.write(
                    f"[preconditioners] {case_name} {size} {label} ...\n")
                sys.stderr.flush()
                res = _sweep_one(case_name, size, label, method, block_size,
                                 precond, maxiter, budget_s)
                out.append(dict(case=case_name, size=size, **res.as_dict()))
                n_fb = sum(1 for r in res.records if r.fell_back)
                sys.stderr.write(
                    f"[preconditioners]   -> {res.total_s:.2f}s, "
                    f"{len(res.records)} calls, {n_fb} fell back"
                    f"{', ABORTED: ' + res.aborted if res.aborted else ''}\n")
    return out


# ----------------------------------------------------------------------
#  Structured cores (B4 etc.) -- a SEPARATE, smaller sweep
# ----------------------------------------------------------------------
# device3d.py/device2d.py look up `linsolve.solve_linear` through the
# MODULE OBJECT (`from . import linsolve`, then `linsolve.solve_linear`
# at call time), unlike the unstructured cores' `from .linsolve import
# solve_linear` module-local binding -- see CLAUDE.md's CRLF-adjacent
# "read the actual import" discipline. That means the override here has
# to patch the ATTRIBUTE on `pytcad.linsolve` itself, not a name inside
# device3d's own namespace, and the two sweeps are kept as separate
# functions rather than one that guesses which pattern a case uses.
#
# B4's own `solve_equilibrium` is scalar (one unknown -- psi -- per
# node), so `block_size` is always None there and block_jacobi/schur
# cannot apply structurally; only the METHOD varies. That is not a
# limitation of this sweep, it is a structural fact about the equation
# being solved, already reflected in the call site
# (device3d.py:619 passes no block_size).
STRUCTURED_METHODS = ["direct", "gmres", "bicgstab", "petsc"]


def _sweep_structured(case_name, size, method, maxiter, budget_s):
    from pytcad.device import NewtonOptions
    from pytcad import linsolve as _mod

    case = get(case_name)
    dev, _ = case.build(size)

    result = ConfigResult(label=method, method=method, block_size=None,
                          precond="auto")
    call_index = [0]
    t_start = time.perf_counter()
    real_solve_linear = _mod.solve_linear

    def swept(A, b, **kwargs):
        idx = call_index[0]
        call_index[0] += 1
        if time.perf_counter() - t_start > budget_s:
            result.aborted = result.aborted or "budget exceeded"
            raise LinearSolveError("preconditioners.py: budget exceeded")
        rtol = kwargs.get("rtol", 1e-10)
        t0 = time.perf_counter()
        try:
            x, info = real_solve_linear(A, b, method=method, rtol=rtol,
                                        maxiter=maxiter)
            dt = time.perf_counter() - t0
            result.records.append(IterRecord(
                call_index=idx, seconds=dt, converged=True,
                iterations=info.get("iterations", 1),
                residual=info.get("residual", float("nan")),
                fell_back=False))
            return x, info
        except LinearSolveError as exc:
            dt = time.perf_counter() - t0
            if method == "direct":
                result.records.append(IterRecord(
                    call_index=idx, seconds=dt, converged=False,
                    iterations=0, residual=float("nan"), fell_back=False,
                    error=str(exc)))
                raise
            t1 = time.perf_counter()
            xd, infod = real_solve_linear(A, b, method="direct")
            dt_fb = time.perf_counter() - t1
            result.records.append(IterRecord(
                call_index=idx, seconds=dt + dt_fb, converged=True,
                iterations=infod.get("iterations", 1),
                residual=infod.get("residual", float("nan")),
                fell_back=True, error=str(exc)))
            return xd, infod

    _mod.solve_linear = swept
    try:
        opts = NewtonOptions(linsolve=method if method != "direct" else "direct")
        dev.solve_equilibrium(opts=opts)
    except LinearSolveError as exc:
        result.aborted = result.aborted or f"Newton loop raised: {exc}"
    except Exception as exc:  # noqa: BLE001 -- see _sweep_one's rationale
        result.aborted = result.aborted or f"{type(exc).__name__}: {exc}"
    finally:
        _mod.solve_linear = real_solve_linear

    result.total_s = time.perf_counter() - t_start
    return result


def run_structured_sweep(cases, sizes, methods=STRUCTURED_METHODS,
                         maxiter=200, budget_s=180.0):
    out = []
    for case_name in cases:
        for size in sizes:
            for method in methods:
                sys.stderr.write(
                    f"[preconditioners] (structured) {case_name} {size} "
                    f"{method} ...\n")
                sys.stderr.flush()
                res = _sweep_structured(case_name, size, method, maxiter,
                                        budget_s)
                out.append(dict(case=case_name, size=size, **res.as_dict()))
                n_fb = sum(1 for r in res.records if r.fell_back)
                sys.stderr.write(
                    f"[preconditioners]   -> {res.total_s:.2f}s, "
                    f"{len(res.records)} calls, {n_fb} fell back"
                    f"{', ABORTED: ' + res.aborted if res.aborted else ''}\n")
    return out


def _environment():
    from . import harness
    try:
        return harness.environment()
    except AttributeError:
        return {"python": platform.python_version(),
               "numpy": np.__version__, "scipy": scipy.__version__,
               "platform": platform.platform()}


def render_markdown(rows):
    lines = ["# M31 P5-1 Phase A -- preconditioner sweep (per Newton iterate)",
             "",
             "Generated by `python -m benchmarks.preconditioners`. See "
             "`M31-P5-1-SOLVER-SELECTION-PLAN.md` section 4 for what this "
             "measures and why.",
             ""]
    by_case_size = {}
    for r in rows:
        by_case_size.setdefault((r["case"], r["size"]), []).append(r)
    for (case_name, size), group in by_case_size.items():
        lines.append(f"## {case_name} ({size})")
        lines.append("")
        lines.append("| config | calls | total_s | mean_s/call | "
                     "min iters | max iters | fell back | aborted |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for r in group:
            recs = r["records"]
            n = len(recs)
            mean_s = (r["total_s"] / n) if n else float("nan")
            iters = [rec["iterations"] for rec in recs if rec["converged"]]
            min_i = min(iters) if iters else "-"
            max_i = max(iters) if iters else "-"
            n_fb = sum(1 for rec in recs if rec["fell_back"])
            lines.append(
                f"| {r['label']} | {n} | {r['total_s']:.3g} | {mean_s:.3g} | "
                f"{min_i} | {max_i} | {n_fb} | {r['aborted'] or '-'} |")
        lines.append("")
        lines.append("Per-iterate detail:")
        lines.append("")
        for r in group:
            lines.append(f"**{r['label']}**")
            lines.append("")
            lines.append("| call | seconds | converged | iterations | "
                         "residual | fell_back |")
            lines.append("|---|---|---|---|---|---|")
            for rec in r["records"]:
                lines.append(
                    f"| {rec['call_index']} | {rec['seconds']:.4g} | "
                    f"{rec['converged']} | {rec['iterations']} | "
                    f"{rec['residual']:.3g} | {rec['fell_back']} |")
            lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cases", default="B8,B9")
    ap.add_argument("--size", default="quick", choices=("quick", "full", "both"))
    ap.add_argument("--maxiter", type=int, default=2000)
    ap.add_argument("--budget", type=float, default=180.0)
    ap.add_argument("--structured", default=None,
                    help="comma-separated structured-core case names "
                         "(e.g. B4) to sweep by METHOD ONLY, via "
                         "dev.solve_equilibrium -- see "
                         "run_structured_sweep's docstring for why this "
                         "is a separate, smaller sweep than --cases")
    ap.add_argument("--out", default=None,
                    help="write JSON to this path (also prints markdown "
                         "to stdout)")
    args = ap.parse_args(argv)

    cases = args.cases.split(",") if args.cases else []
    sizes = ["quick", "full"] if args.size == "both" else [args.size]

    rows = run_sweep(cases, sizes, maxiter=args.maxiter,
                     budget_s=args.budget) if cases else []
    if args.structured:
        rows += run_structured_sweep(args.structured.split(","), sizes,
                                     maxiter=args.maxiter,
                                     budget_s=args.budget)

    if args.out:
        with open(args.out, "w") as f:
            json.dump({"environment": _environment(), "rows": rows}, f,
                     indent=2)
        sys.stderr.write(f"[preconditioners] wrote {args.out}\n")

    print(render_markdown(rows))


if __name__ == "__main__":
    main()
