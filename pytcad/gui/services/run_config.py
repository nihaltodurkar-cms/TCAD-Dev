"""A solver run's pre-flight: validate and configure the job, Qt-free.

Moved here from AppController.run() / backendOptionsForQml /
engineOptionsForQml (NATIVE-DESKTOP-PLAN.md 17.2, P3-S2) so that BOTH
GUIs use one implementation: the QML controller calls these functions, and
the backend service exposes them to the native app (`spec.configure_run`,
`run.options`, `project.spec`). The checks, their order and their
messages are AppController.run()'s, unchanged -- the refusal a user sees
does not depend on which GUI they use.
"""
import copy

# The DeviceSpec fields configure_run sets; every other field is the input's.
RUN_FIELDS = ("sweep", "transient", "ac", "bias", "models", "backend", "engine")


class RunConfigError(Exception):
    """A run refused before it starts: the (title, detail) pair
    AppController.run() shows through errorRaised."""

    def __init__(self, title, detail):
        super().__init__(f"{title}: {detail}")
        self.title = title
        self.detail = detail

    @property
    def rpc_data(self):
        """What the backend service adds to its JSON-RPC error's data."""
        return {"title": self.title, "detail": self.detail}


def merged_models(config):
    """A models config as the Physics Lab restores one
    (PhysicsLabController.setModelConfig): merged onto the catalog
    defaults, unknown keys dropped, validated. Raises ValueError."""
    from workbench.core.catalog import ModelCatalog
    if not isinstance(config, dict):
        raise ValueError(f"model config must be a dict of {{model_key: bool}}, got "
                         f"{type(config).__name__}")
    merged = ModelCatalog.default_config()
    merged.update({k: v for k, v in config.items() if k in merged})
    ModelCatalog.validate(merged)
    return merged


def configure_run(spec, *, sweep=None, transient=None, ac=None, equilibrium_only=False,
                  models=None, backend="pytcad", engine="auto"):
    """AppController.run()'s pre-flight on `spec` (a DeviceSpec): returns the
    spec to run, a copy with the run configuration applied; raises
    RunConfigError(title, detail) with run()'s own messages, in run()'s own
    order. `models`: a config dict to stamp (the Physics Lab's in QML; a
    project's in the native app), or None to keep the spec's own models."""
    names = [c.name for c in spec.contacts]
    # Validate an armed configuration BEFORE the subprocess: an unexecutable
    # one is an immediate, actionable error, not a failed job. The titles are
    # the RUN-time ones, deliberately not the arm-time "Invalid sweep
    # configuration": this failure means the device changed under an armed
    # configuration (e.g. its contact no longer exists), and QML's
    # SweepPanel keys its "arm rejected" note off the arm-time title alone.
    if sweep is not None:
        try:
            sweep.validate(names)
        except ValueError as exc:
            raise RunConfigError("Sweep cannot run on this device", str(exc)) from None
    if transient is not None:
        try:
            transient.validate(names)
        except ValueError as exc:
            raise RunConfigError("Transient run cannot run on this device", str(exc)) from None
    if ac is not None:
        try:
            ac.validate(names)
        except ValueError as exc:
            raise RunConfigError("AC analysis cannot run on this device", str(exc)) from None
    if sum(cfg is not None for cfg in (sweep, transient, ac)) > 1:
        raise RunConfigError("Cannot run more than one of Sweep/Transient/AC together",
                             "Clear all but one of the armed configurations first.")
    # "Equilibrium only" runs with bias None; a sweep always overrides the
    # bias branch (solver_runner's _solve_all checks spec.sweep FIRST), so the
    # two are mutually exclusive.
    if equilibrium_only and sweep is not None:
        raise RunConfigError("Cannot run equilibrium-only with a sweep armed",
                             "Clear the voltage sweep configuration first, or turn "
                             "off 'Equilibrium only' in the Physics Lab.")
    # A shallow copy: every field configure_run changes (RUN_FIELDS) is
    # reassigned, never mutated, so the caller's spec is untouched.
    run = copy.copy(spec)
    run.sweep, run.transient, run.ac = sweep, transient, ac
    if equilibrium_only:
        run.bias = None
    if models is not None:
        run.models = dict(models)
    # Defense in depth: the selector should already prevent an incompatible
    # backend (backend_options uses this SAME check), but the spec may have
    # changed after the backend was picked.
    if backend != "pytcad":
        try:
            from workbench.solvers.devsim_backend import check_devsim_compatible
            check_devsim_compatible(run)
        except Exception as exc:
            raise RunConfigError(f"Cannot run with backend '{backend}'", str(exc)) from None
    run.backend = backend
    # Engine selection applies to the pytcad backend's own linear-solve path
    # only; a stray engine must not leak into a devsim job.
    run.engine = engine if backend == "pytcad" else "auto"
    return run


def backend_options(spec, models):
    """[{"id","label","enabled","reason"}, ...]: "pytcad" always; "devsim"
    only when installed AND check_devsim_compatible passes for `spec` with
    `models` stamped -- the SAME check DevsimBackend.run() enforces, so the
    list never promises a run that would then be refused."""
    from workbench.solvers.base import backend_ids
    opts = [{"id": "pytcad", "label": "pytcad", "enabled": True, "reason": ""}]
    if "devsim" not in backend_ids():
        opts.append({"id": "devsim", "label": "devsim", "enabled": False,
                     "reason": "optional devsim dependency not installed"})
        return opts
    reason = ""
    try:
        from workbench.solvers.devsim_backend import check_devsim_compatible
        if spec is not None:
            trial = copy.copy(spec)
            trial.models = dict(models)
            check_devsim_compatible(trial)
    except ValueError as exc:
        reason = str(exc)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
    opts.append({"id": "devsim", "label": "devsim", "enabled": spec is not None and not reason,
                 "reason": reason})
    return opts


def engine_options(spec, transient_armed):
    """[{"id","label","enabled","reason"}, ...] for the engine selector.
    Cheap, best-effort checks (dimensionality, an armed transient, optional
    dependencies); solver_runner.run_job() stays the authoritative gate
    (e.g. mpi_schwarz's per-axis doping/gate refusal is not re-derived).
    Structural reasons come before dependency ones: they are the more
    actionable message, and keep the reason the same on machines with and
    without mpi4py (gui/tests/test_engine_selector.py depends on this)."""
    from gui.services.solver_runner import _HAVE_CUPY, _HAVE_MPI, _HAVE_PYAMG
    dim = spec.mesh.dimensionality if spec is not None else None
    opts = [{"id": "auto", "label": "Auto", "enabled": True, "reason": ""},
            {"id": "direct", "label": "Direct", "enabled": True, "reason": ""},
            {"id": "gpu_direct", "label": "GPU direct", "enabled": _HAVE_CUPY,
             "reason": "" if _HAVE_CUPY else "optional cupy dependency not installed"},
            {"id": "amg", "label": "AMG (bicgstab)", "enabled": _HAVE_PYAMG,
             "reason": "" if _HAVE_PYAMG else "optional pyamg dependency not installed"}]
    mpi_reason = ""
    if dim != 3:
        mpi_reason = "only available for 3D devices"
    elif transient_armed:
        mpi_reason = "not compatible with an armed transient run"
    elif not _HAVE_MPI:
        mpi_reason = "optional mpi4py dependency / mpirun not available"
    opts.append({"id": "mpi_schwarz", "label": "MPI Schwarz", "enabled": not mpi_reason,
                 "reason": mpi_reason})
    return opts


def project_run_inputs(path):
    """What a saved project gives a run (project_store.load_project): its
    name, the DeviceSpec of its structure, its armed sweep and its models
    config (merged as the Physics Lab restores one). Refuses, as run()
    would, a project with no device structure (a process flow only) and an
    invalid structure."""
    from gui.services.project_store import load_project
    name, structure, mesh_model, process_flow, sweep, model_config = load_project(path)
    if structure is None:
        raise RunConfigError("Nothing to run",
                             "The project has no device structure"
                             + (" (a process flow only)" if process_flow.steps else "") + ".")
    # As AppController._run_validation_quiet: no mesh model, nothing to
    # validate (to_device_spec then names what is missing).
    errors = structure.validate(mesh_model) if mesh_model is not None else []
    if errors:
        raise RunConfigError("Cannot run an invalid structure",
                             "\n".join(e.message for e in errors))
    try:
        spec = structure.to_device_spec(mesh_model)
    except Exception as exc:
        raise RunConfigError("Could not build a solver job from the structure", str(exc)) from None
    models = merged_models(model_config) if model_config is not None else None
    return name, spec, sweep, models
