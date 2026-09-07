"""M30 Phase 2: calibration / optimization loop (goal function vs a
reference curve, scipy's Nelder-Mead simplex over 1+ deck/template
parameters).

Each trial builds a device through the SAME template path Phase 1's
splits use (workbench/splits.py) and solves it through the EXISTING
solver pipeline (gui.services.solver_runner.run_job, the same function
tests/test_workbench_m1.py already calls directly) -- no reimplemented
physics, no second simulation path.  A trial the template or solver
rejects is penalized, not raised, so the optimizer can survive an
unreachable region of parameter space; when EVERY trial across the
whole search fails, the result honestly reports non-convergence rather
than returning a fabricated "best fit" (see
pytcad/M30-WORKBENCH-PLAN.md section 4, gate G-NOCONVERGE).
"""
import os
import tempfile
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

from .core.templates import get_template

# A trial that fails to build or solve is scored with this large,
# finite penalty rather than raising out of the optimizer or being
# silently dropped.  Finite (not inf) so scipy's simplex geometry
# stays well-defined.
UNREACHABLE_PENALTY = 1e6


@dataclass
class GoalFunction:
    """A reference array (any fixed-length numeric field -- an
    equilibrium potential profile, an I-V trace, ...) to match by RMS
    error against a trial's own array of the same field, read from the
    same result key."""
    reference: np.ndarray
    field: str = "field__potential"

    def error(self, trial_values):
        trial = np.asarray(trial_values, dtype=float)
        reference = np.asarray(self.reference, dtype=float)
        if trial.shape != reference.shape:
            raise ValueError(
                f"goal function shape mismatch: trial {trial.shape} vs "
                f"reference {reference.shape}")
        return float(np.sqrt(np.mean((trial - reference) ** 2)))


@dataclass
class CalibrationResult:
    best_params: dict
    error: float
    n_iterations: int
    converged: bool
    trace: list = field(default_factory=list)


def solve_field(template_id, values, field_key, work_dir):
    """Build `template_id` with `values`, solve it equilibrium-only
    through the existing pipeline, and return the requested result
    field array.  Raises ValueError/KeyError on a bad parameter set,
    same as workbench.splits.run_split_matrix's per-row build path."""
    from gui.services import solver_runner
    from .adapters.spec import spec_from_domain

    device = get_template(template_id).build(values)
    spec = spec_from_domain(device)
    spec.bias = None      # equilibrium-only: no bias sweep needed for
    spec.sweep = None     # a field-profile goal function.

    job_path = os.path.join(work_dir, "job.json")
    out_path = os.path.join(work_dir, "result.npz")
    spec.to_json(job_path)
    solver_runner.run_job(job_path, out_path)
    with np.load(out_path) as d:
        if field_key not in d.files:
            raise KeyError(
                f"result has no field {field_key!r} (have: "
                f"{sorted(d.files)})")
        return np.array(d[field_key], dtype=float)


def calibrate(template_id, base_values, free_params, goal, *,
              x0=None, max_iter=200, tol=1e-6, work_dir=None,
              constraints=None):
    """Nelder-Mead search over `free_params` (names), holding every
    other template parameter at `base_values` (falling back to the
    template's own defaults), minimizing `goal.error(...)` against the
    field it names.  `x0` optionally overrides the initial guess for
    one or more free parameters (defaults to `base_values`/template
    defaults, same as an unset parameter anywhere else in this repo).
    `constraints` (M30 Phase 10, workbench.constraints expression
    strings): a trial point that violates one is scored with
    UNREACHABLE_PENALTY WITHOUT ever calling template.build()/the
    solver -- cheaper than discovering the same violation from a
    ValueError, and keeps an out-of-constraint region from spending
    solver time the optimizer will discard anyway."""
    work_dir = work_dir or tempfile.mkdtemp(prefix="pytcad-calib-")
    template = get_template(template_id)
    defaults = {p.name: p.default for p in template.params}
    x0 = x0 or {}
    x0_vec = np.array([
        x0.get(name, base_values.get(name, defaults.get(name)))
        for name in free_params], dtype=float)

    trace = []

    def objective(x):
        values = dict(base_values)
        values.update(zip(free_params, x))
        if constraints:
            from .constraints import first_violation
            # Same defaults-merge as workbench.splits.run_split_matrix:
            # a constraint may name a parameter neither base_values nor
            # free_params sets explicitly.
            violated = first_violation({**defaults, **values}, constraints)
            if violated is not None:
                trace.append({"params": dict(zip(free_params, x)),
                             "error": UNREACHABLE_PENALTY, "failed": True,
                             "constraint_violation": violated})
                return UNREACHABLE_PENALTY
        try:
            model = solve_field(template_id, values, goal.field, work_dir)
            err = goal.error(model)
            failed = False
        except (ValueError, KeyError):
            err = UNREACHABLE_PENALTY
            failed = True
        trace.append({"params": dict(zip(free_params, x)), "error": err,
                     "failed": failed})
        return err

    res = minimize(objective, x0_vec, method="Nelder-Mead",
                   options={"maxiter": max_iter, "xatol": tol, "fatol": tol})

    any_success = any(not t["failed"] for t in trace)
    return CalibrationResult(
        best_params=dict(zip(free_params, res.x)),
        error=float(res.fun),
        n_iterations=int(res.nit),
        converged=bool(res.success) and any_success,
        trace=trace)
