"""Run benchmark cases and collect the section-35 dashboard rows (M32).

The harness is deliberately thin: build the case (untimed), instrument,
run the measured callable, record.  Everything interesting about the
measurement lives in `instrument.py`'s docstring, which says what each
number does and does not mean.

REPRODUCIBILITY IS PART OF THE MEASUREMENT
------------------------------------------
Section 36 lists reproducibility alongside correctness, scaling and
memory as a precondition for any performance claim.  So a report carries
its environment -- interpreter, numpy/scipy versions, BLAS threading, the
compiled-extension status, the machine -- and NOT just the numbers.  A
timing table without that is not reproducible, and this project's own
history has an example of why: a 60x apparent slowdown that turned out
to be one-time PETSc initialization paid by whichever backend ran first
(M31 P3b).

REPEATS
-------
Each case runs `repeat` times and the report keeps the BEST wall time,
not the mean.  The FIRST repeat is the only one that runs under
`tracemalloc`, and it supplies `py_peak_mb` and nothing else: the hook
inflates wall time by 1.19x on one case here and 4.05x on another, so
mixing the two would make `total_s` incomparable between rows.  At
`--repeats 1` there is no untraced run and the row's notes say the
timing is inflated -- quote a number from `--repeats 3` or more.  That
threshold is also what `spread` needs: at `--repeats 2` exactly one
untraced run happens, so the spread column is 0 for want of a second
sample rather than because the timings agreed.  The best run is the one least contaminated by scheduler
noise, page faults and cache eviction, which is what you want when
comparing two implementations of the same computation.  The spread is
reported too, so a case whose runs disagree wildly is visible rather
than averaged into looking stable.
"""
from __future__ import annotations

import platform
import os
import sys
import time
from dataclasses import dataclass, field, asdict

from .cases import CASES, get, _skip_reason
from .instrument import instrumented


@dataclass
class Row:
    """One case's dashboard row."""

    name: str = ""
    title: str = ""
    tests: str = ""
    size: str = ""
    dim: int = 0
    skipped: str = ""          # non-empty = why it did not run
    error: str = ""            # non-empty = it ran and failed
    dof: int = 0
    nnz: int = 0
    assembly_s: float = 0.0
    assembly_calls: int = 0
    linsolve_s: float = 0.0
    linsolve_calls: int = 0
    precond_s: float = 0.0
    py_peak_mb: float = 0.0
    total_s: float = 0.0
    spread_s: float = 0.0
    repeats: int = 0
    notes: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.skipped and not self.error


def environment():
    """What a reader needs to know before comparing two reports."""
    import numpy as np
    import scipy

    try:
        from pytcad import _accel
        accel = _accel.status()
    except Exception as exc:                       # never fail a report on this
        accel = f"unavailable ({exc.__class__.__name__})"

    return {
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS", "unset"),
        "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS", "unset"),
        "PYTCAD_ACCEL": os.environ.get("PYTCAD_ACCEL", "unset"),
        "accel": accel,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def run_case(case, size="quick", repeats=1):
    """Run one case and return its `Row`.

    A case that raises is RECORDED as an error row, not propagated: one
    broken case must not deny you the other six, and a silently missing
    row is the failure mode this whole milestone exists to prevent.
    """
    row = Row(name=case.name, title=case.title, tests=case.tests,
              size=size, dim=case.dim, repeats=repeats)
    if case.notes:
        row.notes.append(case.notes)

    reason = _skip_reason(case.requires)
    if reason:
        row.skipped = reason
        return row

    # The FIRST repeat carries tracemalloc and supplies py_peak_mb only;
    # every later repeat runs untraced and supplies the timings. They are
    # separated because tracemalloc's per-allocation hook is not a
    # uniform tax -- 1.19x on B3, 4.05x on B8 (see instrument.py's MEMORY
    # COSTS TIME) -- so a traced total_s is not comparable with anything.
    # At repeats=1 there is no untraced run to fall back on, and the row
    # says so rather than quietly reporting an inflated number.
    n_repeats = max(1, repeats)
    best = None
    memory_probe = None
    times = []
    for i in range(n_repeats):
        traced = (i == 0)
        try:
            device, run = case.build(size)
        except Exception as exc:
            row.error = f"build failed: {exc.__class__.__name__}: {exc}"
            return row
        try:
            with instrumented(device, memory=traced) as probe:
                run()
        except Exception as exc:
            row.error = f"{exc.__class__.__name__}: {exc}"
            return row
        if traced:
            memory_probe = probe
            if n_repeats > 1:
                continue          # its timings are inflated; do not keep them
        times.append(probe.total_s)
        if best is None or probe.total_s < best.total_s:
            best = probe

    if best is None:                                  # cannot happen; be safe
        best = memory_probe

    row.dof = best.dof
    row.nnz = best.nnz
    row.assembly_s = best.assembly_s
    row.assembly_calls = best.assembly_calls
    row.linsolve_s = best.linsolve_s
    row.linsolve_calls = best.linsolve_calls
    row.precond_s = best.precond_s
    row.py_peak_mb = memory_probe.py_peak_mb if memory_probe else 0.0
    row.total_s = best.total_s
    row.spread_s = (max(times) - min(times)) if len(times) > 1 else 0.0
    for n in best.notes:
        row.notes.append(n)
    if memory_probe is not None and memory_probe is not best:
        # The timing rows come from an untraced run, so drop the traced
        # probe's own warning -- it applies to a number nobody reported.
        for n in memory_probe.notes:
            if "tracemalloc" not in n and n not in row.notes:
                row.notes.append(n)
    return row


def run_all(size="quick", repeats=1, only=None):
    """Run the suite. `only` is a list of case names, else all of them."""
    cases = [get(n) for n in only] if only else CASES
    return [run_case(c, size=size, repeats=repeats) for c in cases]


def to_dict(rows, env=None):
    return {"environment": env or environment(),
            "rows": [asdict(r) for r in rows]}
