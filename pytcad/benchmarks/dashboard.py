"""Render the performance dashboard (M32, Architecture_Master_Plan s.35).

The output is a markdown table plus an environment block, because
section 36's rule is that "performance claims belong in benchmark tables,
not marketing language" -- so the table has to be the thing that is easy
to produce and paste, or the rule loses to convenience.

WHY THE COLUMN NAMES DIFFER FROM SECTION 35 IN TWO PLACES
---------------------------------------------------------
Section 35 lists "Residual time" and "Jacobian time" separately, and
"Newton iterations".  This renders `assembly_s` and `assembly_calls`
instead, because those are what can honestly be measured from outside the
frozen numerical core -- see `instrument.py`'s docstring for both
reasons.  Renaming them to match the spec while measuring something else
would put a wrong number under a right-looking heading, which is the
precise failure section 36 is written against.
"""
from __future__ import annotations


def _fmt_s(v):
    if v >= 1.0:
        return f"{v:.2f}"
    if v >= 1e-3:
        return f"{v * 1e3:.1f}m"
    return f"{v * 1e6:.0f}u"


def _fmt_int(v):
    return f"{v:,}" if v else "-"


def render_markdown(rows, env=None, title="pyTCAD benchmark suite"):
    out = [f"# {title}", ""]

    if env:
        out += ["## Environment", ""]
        out += [f"- **{k}**: {v}" for k, v in env.items()]
        out += [""]

    out += ["## Dashboard", ""]
    out += ["| case | what it tests | size | DOF | NNZ | assembly | asm calls "
            "| linsolve | ls calls | precond | py peak MB | total | spread |"]
    out += ["|---|---|---|---|---|---|---|---|---|---|---|---|---|"]

    for r in rows:
        if r.skipped:
            out.append(f"| **{r.name}** {r.title} | {r.tests} | {r.size} | "
                       f"SKIPPED: {r.skipped} " + "| " * 9 + "|")
            continue
        if r.error:
            out.append(f"| **{r.name}** {r.title} | {r.tests} | {r.size} | "
                       f"FAILED: {r.error} " + "| " * 9 + "|")
            continue
        out.append(
            f"| **{r.name}** {r.title} | {r.tests} | {r.size} "
            f"| {_fmt_int(r.dof)} | {_fmt_int(r.nnz)} "
            f"| {_fmt_s(r.assembly_s)} | {r.assembly_calls or '-'} "
            f"| {_fmt_s(r.linsolve_s)} | {r.linsolve_calls or '-'} "
            f"| {_fmt_s(r.precond_s)} | {r.py_peak_mb:.1f} "
            f"| {_fmt_s(r.total_s)} | {_fmt_s(r.spread_s)} |")

    out += ["", "Times in seconds unless suffixed `m` (ms) or `u` (us). "
            "`spread` is max-min across repeats; a large spread means the "
            "row's timings are noise-dominated and should not be quoted.", ""]

    notes = [(r.name, n) for r in rows for n in r.notes]
    if notes:
        out += ["## Notes", ""]
        out += [f"- **{name}**: {n}" for name, n in notes]
        out += [""]

    out += ["## What these numbers are not", "",
            "- `assembly` is residual AND Jacobian together: the core "
            "computes both in one pass and returns both, so no honest "
            "split is available from outside it.",
            "- `asm calls` is assembly calls, NOT Newton iterations. They "
            "are equal only when no backtracking or damping retry "
            "occurred; no core solve method exposes an iteration count.",
            "- `py peak MB` is `tracemalloc`, so it sees Python-level "
            "allocation only. SuperLU's LU factors, BLAS scratch and "
            "PETSc's arena are invisible to it -- treat it as a floor on "
            "real usage, not a measurement of it.",
            "- Nothing here is a physics gate. A case asserts only that "
            "its solve converged; correctness is `tests/`'s job.", ""]
    return "\n".join(out)
