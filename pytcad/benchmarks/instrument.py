"""Timing and counting probes for the benchmark harness (M32).

WHY THIS IS A PROBE AND NOT AN INSTRUMENTED SOLVER
--------------------------------------------------
The performance dashboard `Architecture_Master_Plan.md` section 35 asks
for wants per-phase timings: assembly, linear solve, preconditioner
setup.  The obvious way to get them is to add timers inside
`device.py`/`device2d.py`/`device3d.py` -- and that is exactly what this
module exists to avoid.  Those files are the frozen numerical core:
touching them requires the M11-S3 amendment mechanism (sign-off in a
plan file, a recorded and recoverable golden baseline, FD-Jacobian-
first, bit-identity off-path), which is a disproportionate price for a
stopwatch, and it
would put timing code on the hot path of every solve the project ever
runs.

So the measurement happens from OUTSIDE, by temporarily swapping the
functions the core already calls for wrappers that time and count them.
Nothing is patched permanently, nothing is patched while ordinary code
runs, and the numerical path is byte-for-byte the same -- the wrappers
forward arguments unchanged and return the callee's own result.

WHAT IS MEASURED EXACTLY, AND WHAT IS NOT
-----------------------------------------
Measured exactly:
  * wall time and call count for residual+Jacobian assembly;
  * wall time and call count for the linear solve;
  * wall time for preconditioner construction;
  * DOF and NNZ, read off the real Jacobian the solver assembled;
  * peak Python-allocated memory during the run (tracemalloc).

NOT separable, and reported as one number rather than split by guess:
  * `_residual_jacobian` computes the residual AND the Jacobian in one
    pass and returns both.  Section 35 lists "Residual time" and
    "Jacobian time" separately; from outside this function there is no
    way to attribute its cost between them, and inventing a split would
    be a fabricated number.  The dashboard reports `assembly_s` and says
    so.  If the split is ever genuinely needed, it is a P5 concern --
    the C++ assembler can expose it honestly because it will have the
    two as separate entry points.

  * NEWTON ITERATIONS are not exposed by any core solve method (checked:
    no counter is stored or returned).  What this module counts is
    ASSEMBLY CALLS, which equals the Newton iteration count only when no
    backtracking or damping retry occurred.  The dashboard reports
    `assembly_calls` under that name for that reason, never as "Newton
    iterations".

MEMORY
------
`tracemalloc` sees Python-level allocations, which includes numpy array
allocations made through Python but NOT memory allocated inside SuperLU,
BLAS, or PETSc.  For a direct solve the LU factors are the dominant
consumer and they live in SuperLU's own arena, so this number is a floor
on real usage, not an estimate of it.  Reported as `py_peak_mb` -- named
for what it actually measures.

MEMORY COSTS TIME, AND NOT EVENLY
---------------------------------
`tracemalloc` charges a hook on every allocation, so a case that
allocates many small objects pays far more for being measured than one
that allocates a few large arrays.  Measured here on the same machine,
quick size, warm:

    B3 (2D MOSFET, structured)     0.047 s -> 0.056 s   1.19x
    B8 (2D unstructured DD)        0.205 s -> 0.832 s   4.05x

That is not a small correction, and it is not uniform -- so a `total_s`
taken under tracemalloc cannot be compared across cases at all, and
comparing one implementation against another through it would measure
the profiler.  B8's 4x comes from the LIL row-stamping in
`unstructured_dd.solve_bias`, which makes 66k `ndarray.tolist` calls per
solve; that is exactly the code M31 P5 exists to judge, so leaving the
inflation in would have put a 4x thumb on the scale of P5's own
before/after.

The harness therefore runs the memory repeat and the timing repeats
SEPARATELY (`harness.run_case`), and any probe that ran traced says so
in its notes.
"""
from __future__ import annotations

import contextlib
import time
import tracemalloc
from dataclasses import dataclass, field


@dataclass
class Probe:
    """What one instrumented run observed."""

    assembly_s: float = 0.0
    assembly_calls: int = 0
    linsolve_s: float = 0.0
    linsolve_calls: int = 0
    precond_s: float = 0.0
    precond_calls: int = 0
    dof: int = 0
    nnz: int = 0
    py_peak_mb: float = 0.0
    total_s: float = 0.0
    notes: list = field(default_factory=list)

    def note(self, text):
        """Record something the reader needs in order to trust a number."""
        if text not in self.notes:
            self.notes.append(text)


def _size_of(probe, A):
    """Record DOF/NNZ from a matrix, if that is what this argument is.

    Read-only and failure-tolerant on purpose: this runs on the hot path
    of a real solve, and a probe that raised on an unexpected argument
    would turn a measurement into a broken run.
    """
    try:
        probe.dof = max(probe.dof, int(A.shape[0]))
        probe.nnz = max(probe.nnz, int(A.nnz))
    except (AttributeError, TypeError, IndexError):
        pass


def _timed(probe, kind, fn, sizes=False):
    """Wrap `fn` so its wall time and call count land in `probe`.

    The wrapper is deliberately dumb: forward everything, return
    everything, add nothing. A wrapper that inspected or normalized
    arguments could change the numerics it is supposed to be measuring.

    `sizes=True` additionally reads DOF/NNZ off the first argument. That
    is how the 1D equilibrium path gets a system size at all: it
    assembles inline in the Newton loop rather than through a named
    method, so there is nothing there to wrap for assembly -- but the
    matrix still reaches the linear solver, and that is a real
    measurement of the system actually solved.
    """
    def wrapper(*args, **kwargs):
        if sizes and args:
            _size_of(probe, args[0])
        t0 = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            dt = time.perf_counter() - t0
            setattr(probe, f"{kind}_s", getattr(probe, f"{kind}_s") + dt)
            setattr(probe, f"{kind}_calls", getattr(probe, f"{kind}_calls") + 1)
    wrapper.__wrapped__ = fn
    return wrapper


def _capture_matrix(probe, fn):
    """Wrap an assembly call, also recording the Jacobian's shape/NNZ.

    DOF and NNZ are read off the matrix the solver ACTUALLY built rather
    than derived from a node count times an unknowns-per-node constant --
    the two disagree wherever contacts, Dirichlet rows or a Poisson-only
    phase change the system size, and the assembled matrix is the honest
    answer.
    """
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        try:
            out = fn(*args, **kwargs)
        finally:
            dt = time.perf_counter() - t0
            probe.assembly_s += dt
            probe.assembly_calls += 1
        # Every core assembly returns (F, J, ...) with J second.
        try:
            J = out[1]
            probe.dof = max(probe.dof, int(J.shape[0]))
            probe.nnz = max(probe.nnz, int(J.nnz))
        except (TypeError, IndexError, AttributeError):
            pass
        return out
    wrapper.__wrapped__ = fn
    return wrapper


@contextlib.contextmanager
def instrumented(device=None, memory=True):
    """Measure one solve. Yields a `Probe`; patches are undone on exit.

    Patching is restricted to this block and restored in a `finally`, so
    an exception mid-benchmark cannot leave the solver wrapped -- which
    would silently slow down and mis-measure every later case in the
    same process.

    `memory=False` skips `tracemalloc` -- see MEMORY COSTS TIME in the
    module docstring. `py_peak_mb` is then 0.0 and the caller must not
    report it as a measurement.
    """
    from pytcad import linsolve as _linsolve

    probe = Probe()
    undo = []

    def patch(obj, name, new):
        old = getattr(obj, name, None)
        if old is None:
            return False
        setattr(obj, name, new)
        undo.append((obj, name, old))
        return True

    # The linear solve reaches scipy by two different routes depending on
    # the core and the code path -- linsolve.solve_linear in most places,
    # a bare spsolve imported into the module namespace in others (e.g.
    # device2d.py:984). Patch both, per module, or a case silently
    # reports linsolve_s = 0 and looks free.
    patch(_linsolve, "solve_linear",
          _timed(probe, "linsolve", _linsolve.solve_linear, sizes=True))
    patch(_linsolve, "_build_preconditioner",
          _timed(probe, "precond", _linsolve._build_preconditioner))

    # NOT pytcad.linsolve's own spsolve: solve_linear is already wrapped
    # above, and wrapping the function it calls internally would count
    # the same solve twice.
    for modname in ("device", "device2d", "device3d", "unstructured_dd",
                    "unstructured_dd3d", "unstructured_poisson", "moscap"):
        try:
            mod = __import__(f"pytcad.{modname}", fromlist=["_"])
        except ImportError:
            continue
        raw = getattr(mod, "spsolve", None)
        if raw is not None:
            patch(mod, "spsolve", _timed(probe, "linsolve", raw, sizes=True))
        # A core that does `from .linsolve import solve_linear` holds its
        # OWN reference, which patching pytcad.linsolve.solve_linear above
        # does not reach -- the unstructured cores do exactly that since
        # M31 P5-0. Patch the module-local name too. No double counting:
        # the wrapper calls the real solve_linear, whose internal spsolve
        # comes from pytcad.linsolve's namespace, which is deliberately
        # left unpatched (see the comment above).
        raw = getattr(mod, "solve_linear", None)
        if raw is not None:
            patch(mod, "solve_linear",
                  _timed(probe, "linsolve", raw, sizes=True))

    # The unstructured cores assemble through MODULE-level functions, not
    # through a device method, so the `device is not None` branch below
    # cannot see them and they would report assembly_s = 0 -- which reads
    # as "assembly is free" rather than "assembly was not measured". They
    # are patched here instead. This is the split M31 P5 needs measured
    # before it can justify porting the assembler, so it has to be a real
    # number rather than an absent column.
    for modname, fnames in (
            ("unstructured_poisson", ("_residual_jacobian",)),
            ("unstructured_dd", ("_residual_jacobian",)),
            ("unstructured_dd3d", ("_residual_jacobian_poisson3d",
                                   "_residual_jacobian_dd3d")),
    ):
        try:
            mod = __import__(f"pytcad.{modname}", fromlist=["_"])
        except ImportError:
            continue
        for fname in fnames:
            raw = getattr(mod, fname, None)
            if raw is not None:
                patch(mod, fname, _capture_matrix(probe, raw))

    if device is not None:
        for meth in ("_residual_jacobian", "_residual_jacobian_poisson"):
            bound = getattr(device, meth, None)
            if bound is not None:
                setattr(device, meth, _capture_matrix(probe, bound))
                undo.append((device, meth, None))   # instance attr: delete

    if memory:
        tracemalloc.start()
    t0 = time.perf_counter()
    try:
        yield probe
    finally:
        probe.total_s = time.perf_counter() - t0
        if memory:
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            probe.py_peak_mb = peak / (1024.0 * 1024.0)
            probe.note("tracemalloc was active: total_s is inflated and is "
                       "not comparable with an untraced run")
        for obj, name, old in reversed(undo):
            if old is None:
                # An instance attribute we added shadowing a class method:
                # delete it so the class method is visible again.
                try:
                    delattr(obj, name)
                except AttributeError:
                    pass
            else:
                setattr(obj, name, old)

        if probe.assembly_calls == 0:
            probe.note("assembly not instrumented (no device handle, or a "
                       "path that does not use _residual_jacobian)")
        if probe.linsolve_calls == 0:
            probe.note("no linear solve observed")
