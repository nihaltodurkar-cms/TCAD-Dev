"""JSON-RPC 2.0 over line-delimited stdio.

stdout is the protocol channel and nothing else: the real stdout is
captured once at start-up and `sys.stdout` is pointed at stderr, so a
print() anywhere inside a called function (the solver and its helpers
print progress) can never corrupt a response.

Both pipes are UTF-8. On Windows a piped stdin otherwise decodes with the
ANSI code page, which turned a non-ASCII path into mojibake (measured,
NATIVE-DESKTOP-PLAN.md 15.15 rev. 1); output lines end in "\\n", not the
text-mode "\\r\\n".

Methods:

    system.ping      -> {"pong": true, "protocol": PROTOCOL_VERSION}
    system.info      -> {"protocol", "pid", "prefix", "python", "scratch_dir"}
    system.methods   -> sorted method names
    system.warmup    -> {"import_ms"}: import what the maps need, ahead of use
    system.shutdown  -> null, then the server exits
    examples.list    -> sorted example names (gui.services.examples.EXAMPLES)
    examples.build   {"name": str} -> DeviceSpec.to_dict() of that example

  P3 S2 (section 17.2) -- jobs are built here, never in C++:

    spec.from_example  {"name"} -> as examples.build
    spec.load          {"path"} -> DeviceSpec.to_dict() of a DeviceSpec JSON file
    project.spec       {"path"} -> {"name", "spec", "sweep", "models"} of a project
    run.options        {"spec", "models"?, "transient_armed"?}
                       -> {"backends": [...], "engines": [...]}, each
                          {"id", "label", "enabled", "reason"}
    spec.configure_run {"spec", "run": {"sweep"?, "transient"?, "ac"?,
                        "equilibrium_only"?, "models"?, "backend"?, "engine"?}}
                       -> the DeviceSpec dict to run; a refusal is
                          AppController.run()'s, with "title" and "detail"
                          in the error data
    spec.job_text      {"spec"} -> the job file's text, byte-identical to the
                          QML runner's (DeviceSpec.to_json); P3 S3
    cv.job_text        {"nsub_cm3", "tox_nm", "vstart", "vstop", "vstep"}
                       -> the C-V job file's text, as QML's CVController
                          writes it, validated; P3 S4
    family.jobs        {"spec", "stepped", "values": {start, stop, step},
                        "swept": {contact, start, stop, step}}
                       -> [{"label", "value", "job_text"}], QML's family; P3 S6
    comparison.job     {"spec"} -> {"label", "job_text"}: every model off; P3 S6

  P1 S4 (section 15.3) -- bulk arrays never travel as JSON: a derived map
  is written as a small RESULT FILE (the result grammar: axes, field__*,
  unit__*, schema stamp) in the service's scratch directory, and the
  reply carries its path. Each reply also carries "timings" in ms.

    analysis.band_map          {"result": path, "names"?: [...]}
                               -> {"path", "fields", "unit", "timings"}
    analysis.recombination_map {"result": path} -> same shape, field "R"

  Only with TCAD_BACKEND_DEBUG=1 in the environment (the client tests'
  hang/crash probes; "method not found" otherwise):

    debug.sleep {"seconds"}  debug.exit {"code"}  debug.loaded_modules

The scratch directory is created on first use and removed when serve()
ends -- on system.shutdown AND on stdin EOF (the app died: its end of
the pipe closed).

Errors use the JSON-RPC 2.0 codes; application errors are -32000 with
the exception type and message.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import uuid

PROTOCOL_VERSION = 1

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
APPLICATION_ERROR = -32000

_state = {"scratch": None}


class _Shutdown(Exception):
    pass


def _examples():
    from gui.services import examples      # Qt-free (NATIVE-DESKTOP-PLAN.md 3.2)
    return examples.EXAMPLES


def _scratch():
    if _state["scratch"] is None or not os.path.isdir(_state["scratch"]):
        _state["scratch"] = tempfile.mkdtemp(prefix="tcad_backend_")
    return _state["scratch"]


def _remove_scratch():
    if _state["scratch"] is not None:
        shutil.rmtree(_state["scratch"], ignore_errors=True)
        _state["scratch"] = None


def _ping(params):
    return {"pong": True, "protocol": PROTOCOL_VERSION}


def _info(params):
    return {"protocol": PROTOCOL_VERSION, "pid": os.getpid(), "prefix": sys.prefix,
            "python": sys.executable, "scratch_dir": _scratch()}


def _methods(params):
    return sorted(METHODS)


def _warmup(params):
    """Import what the derived maps need (numpy, the result store,
    workbench's observables, pytcad's materials), so the first real
    call does not pay for it. The app sends this at idle after its first
    frame (NATIVE-DESKTOP-PLAN.md 15.17 decision 4). Loads no GUI stack."""
    t0 = time.perf_counter()
    import numpy  # noqa: F401
    from gui.services import observable_maps, result_store, solver_backend  # noqa: F401
    from pytcad import materials  # noqa: F401
    from workbench.analysis import observables  # noqa: F401
    return {"import_ms": _ms(t0)}


def _examples_list(params):
    return sorted(_examples())


def _examples_build(params):
    if not isinstance(params, dict) or not isinstance(params.get("name"), str):
        raise TypeError("examples.build needs params {\"name\": <example name>}")
    table = _examples()
    name = params["name"]
    if name not in table:
        raise KeyError(f"unknown example '{name}' (known: {', '.join(sorted(table))})")
    return table[name]().to_dict()


def _shutdown(params):
    raise _Shutdown


# -- P3 S2: job methods (NATIVE-DESKTOP-PLAN.md 17.2) --------------------------
# The native app builds no job itself: the backend loads the device, applies
# the run configuration with AppController.run()'s own checks (the shared
# gui.services.run_config) and returns the DeviceSpec JSON the runner writes.

_RUN_KEYS = ("sweep", "transient", "ac", "equilibrium_only", "models", "backend", "engine")
_ENGINE_IDS = ("auto", "direct", "gpu_direct", "amg", "mpi_schwarz")


def _spec_param(params, method, key="spec"):
    from gui.services.device_spec import DeviceSpec
    return DeviceSpec.from_dict(_param(params, key, dict, method))


def _models_param(value, method):
    from gui.services.run_config import merged_models
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(f"{method}: 'models' must be an object {{model_key: bool}} or null")
    return merged_models(value)


def _spec_load(params):
    from gui.services.device_spec import DeviceSpec
    path = _param(params, "path", str, "spec.load")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"device spec file not found: {path}")
    return DeviceSpec.from_json(path).to_dict()


def _project_spec(params):
    from gui.services.run_config import project_run_inputs
    path = _param(params, "path", str, "project.spec")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"project file not found: {path}")
    name, spec, sweep, models = project_run_inputs(path)
    return {"name": name, "spec": spec.to_dict(),
            "sweep": sweep.to_dict() if sweep is not None else None, "models": models}


def _run_options(params):
    """{"spec", "models"?, "transient_armed"?} -> {"backends", "engines"}.
    `models` defaults to the spec's own."""
    from gui.services import run_config
    spec = _spec_param(params, "run.options")
    models = _models_param(params.get("models"), "run.options")
    armed = params.get("transient_armed", False)
    if not isinstance(armed, bool):
        raise TypeError("run.options: 'transient_armed' must be a boolean")
    return {"backends": run_config.backend_options(spec, models if models is not None
                                                   else spec.models),
            "engines": run_config.engine_options(spec, armed)}


def _job_text(params):
    """{"spec"} -> the job file's text, exactly as the QML runner writes it
    (DeviceSpec.to_json): the native runner writes these bytes verbatim,
    so the two apps' job files are byte-identical (section 17.4)."""
    import io
    spec = _spec_param(params, "spec.job_text")
    buf = io.StringIO()
    json.dump(spec.to_dict(), buf)          # DeviceSpec.to_json's own call
    return buf.getvalue()


def _cv_job_text(params):
    """{"nsub_cm3", "tox_nm", "vstart", "vstop", "vstep"} -> the C-V job
    file's text, as QML's CVController writes it (gui.services.cv_job)."""
    from gui.services import cv_job
    method = "cv.job_text"
    if not isinstance(params, dict):
        raise TypeError(f"{method} needs params {{nsub_cm3, tox_nm, vstart, vstop, vstep}}")
    values = {}
    for key in ("nsub_cm3", "tox_nm", "vstart", "vstop", "vstep"):
        v = params.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise TypeError(f"{method}: '{key}' must be a number, got {v!r}")
        values[key] = v
    p = cv_job.cv_params(**values)
    cv_job.validate(p)
    return cv_job.job_text(p)


def _ramp_param(params, key, method, with_contact):
    ramp = params.get(key) if isinstance(params, dict) else None
    if not isinstance(ramp, dict):
        raise TypeError(f"{method}: '{key}' must be an object")
    out = {}
    for k in (("contact",) if with_contact else ()) + ("start", "stop", "step"):
        v = ramp.get(k)
        if k == "contact":
            if not isinstance(v, str):
                raise TypeError(f"{method}: '{key}.contact' must be a string")
        elif not isinstance(v, (int, float)) or isinstance(v, bool):
            raise TypeError(f"{method}: '{key}.{k}' must be a number, got {v!r}")
        out[k] = v
    return out


def _family_jobs(params):
    """{"spec", "stepped", "values": {start, stop, step}, "swept": {contact,
    start, stop, step}} -> [{"label", "value", "job_text"}], QML's family
    (gui.services.family_jobs); a refusal carries QML's title and detail."""
    import io
    from gui.services import family_jobs
    method = "family.jobs"
    spec = _spec_param(params, method)
    stepped = _param(params, "stepped", str, method)
    values = _ramp_param(params, "values", method, False)
    swept = _ramp_param(params, "swept", method, True)
    vals = family_jobs.family_values(values["start"], values["stop"], values["step"])
    out = []
    for v, job in family_jobs.family_specs(spec, stepped, vals, swept["contact"], swept["start"],
                                           swept["stop"], swept["step"]):
        buf = io.StringIO()
        json.dump(job.to_dict(), buf)          # DeviceSpec.to_json's own call
        out.append({"label": family_jobs.family_label(stepped, v), "value": v, "job_text": buf.getvalue()})
    return out


def _comparison_job(params):
    """{"spec"} -> {"label", "job_text"}: the spec with every model off, as
    QML's runModelComparison builds it."""
    import io
    from gui.services import family_jobs
    job = family_jobs.comparison_spec(_spec_param(params, "comparison.job"))
    buf = io.StringIO()
    json.dump(job.to_dict(), buf)
    return {"label": family_jobs.COMPARISON_LABEL, "job_text": buf.getvalue()}


def _configure_run(params):
    """{"spec", "run": {"sweep"?, "transient"?, "ac"?, "equilibrium_only"?,
    "models"?, "backend"?, "engine"?}} -> the DeviceSpec dict to run. A
    refusal is AppController.run()'s, its title and detail in the error data."""
    from gui.services import run_config
    from gui.services.device_spec import ACSpec, SweepSpec, TransientSpec
    method = "spec.configure_run"
    spec = _spec_param(params, method)
    run = params.get("run", {})
    if not isinstance(run, dict):
        raise TypeError(f"{method}: 'run' must be an object")
    unknown = sorted(set(run) - set(_RUN_KEYS))
    if unknown:
        raise TypeError(f"{method}: unknown run keys {unknown} (known: {', '.join(_RUN_KEYS)})")
    armed = {}
    for key, cls in (("sweep", SweepSpec), ("transient", TransientSpec), ("ac", ACSpec)):
        value = run.get(key)
        if value is not None and not isinstance(value, dict):
            raise TypeError(f"{method}: '{key}' must be an object or null")
        armed[key] = cls.from_dict(value) if value is not None else None
    eq_only = run.get("equilibrium_only", False)
    if not isinstance(eq_only, bool):
        raise TypeError(f"{method}: 'equilibrium_only' must be a boolean")
    backend = run.get("backend", "pytcad")
    engine = run.get("engine", "auto")
    from workbench.solvers.base import backend_ids
    known_backends = sorted({"pytcad", "devsim", *backend_ids()})
    if backend not in known_backends:
        raise ValueError(f"{method}: unknown backend {backend!r} "
                         f"(known: {', '.join(known_backends)})")
    if engine not in _ENGINE_IDS:
        raise ValueError(f"{method}: unknown engine {engine!r} (known: {', '.join(_ENGINE_IDS)})")
    return run_config.configure_run(
        spec, **armed, equilibrium_only=eq_only,
        models=_models_param(run.get("models"), method),
        backend=backend, engine=engine).to_dict()


# -- P1 S4: derived maps ------------------------------------------------------

def _param(params, key, kind, method):
    if not isinstance(params, dict) or not isinstance(params.get(key), kind):
        raise TypeError(f"{method} needs params {{\"{key}\": <{kind.__name__}>}}")
    return params[key]


def _ms(t0):
    return round((time.perf_counter() - t0) * 1e3, 3)


def _open_result(path):
    from gui.services.result_store import NpzResultStore
    if not os.path.isfile(path):
        raise FileNotFoundError(f"result file not found: {path}")
    return NpzResultStore(path)  # validates; a bad file raises a named ResultSchemaError


def _write_derived(source_path, store, fields, unit):
    """A derived map as a result file in the scratch directory: the
    source's axes and solved_bias, one field__<name> + unit__<name> per
    map, and the schema stamp. Written to a temporary name, then
    renamed, so a reader never sees a half-written file."""
    import numpy as np
    from gui.services.solver_backend import SOLVER_RESULT_SCHEMA_VERSION
    axes = store.mesh_axes()
    with np.load(source_path) as src:
        solved_bias = np.asarray(src["solved_bias"])
    arrays = {"result__schema": np.int64(SOLVER_RESULT_SCHEMA_VERSION),
              "solved_bias": solved_bias,
              "dimensionality": np.int64(axes.dimensionality)}
    for name, values in axes.axes.items():
        arrays[f"axis_{name}"] = np.asarray(values, dtype=float)
    for name, values in fields.items():
        arrays[f"field__{name}"] = np.ascontiguousarray(values, dtype=float)
        arrays[f"unit__{name}"] = np.array(unit)
    path = os.path.join(_scratch(), f"map_{uuid.uuid4().hex}.npz")
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        np.savez(fh, **arrays)
    os.replace(tmp, path)
    return path


def _map_call(params, method, required, compute, unit):
    from gui.services import observable_maps as om
    t0 = time.perf_counter()
    source = _param(params, "result", str, method)
    store = _open_result(source)
    inputs = om.observable_inputs(store)
    missing = om.missing_fields(store, required)
    if inputs is None or missing:
        raise ValueError(f"{method}: the result lacks {missing or list(required)} "
                         f"(it has {store.available_scalars()})")
    load_ms = _ms(t0)
    t1 = time.perf_counter()
    fields = compute(inputs)
    compute_ms = _ms(t1)
    t2 = time.perf_counter()
    path = _write_derived(source, store, fields, unit)
    return {"path": path, "fields": list(fields), "unit": unit,
            "timings": {"load_ms": load_ms, "compute_ms": compute_ms, "write_ms": _ms(t2)}}


def _band_map(params):
    from gui.services import observable_maps as om
    names = params.get("names") if isinstance(params, dict) else None
    if names is not None and not (isinstance(names, list) and all(isinstance(n, str) for n in names)):
        raise TypeError("analysis.band_map: 'names' must be a list of strings")
    return _map_call(params, "analysis.band_map", om.BAND_FIELDS,
                     lambda inputs: om.band_maps(inputs, names), om.BAND_UNIT)


def _recombination_map(params):
    from gui.services import observable_maps as om
    return _map_call(params, "analysis.recombination_map", om.RECOMBINATION_FIELDS,
                     lambda inputs: {"R": om.recombination_map(inputs)}, om.RECOMBINATION_UNIT)


# -- debug-only probes (TCAD_BACKEND_DEBUG=1) ---------------------------------

def _debug_sleep(params):
    time.sleep(float(_param(params, "seconds", (int, float), "debug.sleep")))
    return None


def _debug_exit(params):
    code = params.get("code", 3) if isinstance(params, dict) else 3
    sys.stderr.write(f"debug.exit({code}) requested\n")
    sys.stderr.flush()
    os._exit(int(code))


def _debug_loaded_modules(params):
    """Every DLL this process has loaded (Windows), so the client test can
    assert none comes from outside this interpreter's own environment."""
    if os.name != "nt":
        return []
    import ctypes
    import ctypes.wintypes as wt
    psapi, k32 = ctypes.WinDLL("psapi"), ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = wt.HANDLE
    psapi.EnumProcessModules.argtypes = [wt.HANDLE, ctypes.POINTER(wt.HMODULE), wt.DWORD,
                                         ctypes.POINTER(wt.DWORD)]
    k32.GetModuleFileNameW.argtypes = [wt.HMODULE, wt.LPWSTR, wt.DWORD]
    h = k32.GetCurrentProcess()
    mods = (wt.HMODULE * 8192)()
    need = wt.DWORD()
    if not psapi.EnumProcessModules(h, mods, ctypes.sizeof(mods), ctypes.byref(need)):
        raise OSError(f"EnumProcessModules failed ({ctypes.get_last_error()})")
    out = []
    for m in mods[: need.value // ctypes.sizeof(wt.HMODULE)]:
        buf = ctypes.create_unicode_buffer(1024)
        k32.GetModuleFileNameW(m, buf, 1024)
        out.append(buf.value)
    return out


METHODS = {
    "system.ping": _ping,
    "system.info": _info,
    "system.methods": _methods,
    "system.shutdown": _shutdown,
    "system.warmup": _warmup,
    "examples.list": _examples_list,
    "examples.build": _examples_build,
    "spec.from_example": _examples_build,
    "spec.load": _spec_load,
    "project.spec": _project_spec,
    "run.options": _run_options,
    "spec.configure_run": _configure_run,
    "spec.job_text": _job_text,
    "cv.job_text": _cv_job_text,
    "family.jobs": _family_jobs,
    "comparison.job": _comparison_job,
    "analysis.band_map": _band_map,
    "analysis.recombination_map": _recombination_map,
}
DEBUG_METHODS = {
    "debug.sleep": _debug_sleep,
    "debug.exit": _debug_exit,
    "debug.loaded_modules": _debug_loaded_modules,
}
if os.environ.get("TCAD_BACKEND_DEBUG") == "1":
    METHODS.update(DEBUG_METHODS)


def _error(req_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def handle(line):
    """One request line -> (response dict or None for a notification,
    shutdown flag). Pure: no I/O, so tests can drive it directly."""
    try:
        req = json.loads(line)
    except json.JSONDecodeError as exc:
        return _error(None, PARSE_ERROR, f"parse error: {exc}"), False
    if not isinstance(req, dict) or req.get("jsonrpc") != "2.0" \
            or not isinstance(req.get("method"), str):
        return _error(req.get("id") if isinstance(req, dict) else None,
                      INVALID_REQUEST, "not a JSON-RPC 2.0 request"), False
    req_id = req.get("id")
    notification = "id" not in req
    fn = METHODS.get(req["method"])
    if fn is None:
        resp = _error(req_id, METHOD_NOT_FOUND, f"method not found: {req['method']}")
        return (None if notification else resp), False
    try:
        result = fn(req.get("params"))
    except _Shutdown:
        return (None if notification else
                {"jsonrpc": "2.0", "id": req_id, "result": None}), True
    except TypeError as exc:
        resp = _error(req_id, INVALID_PARAMS, str(exc))
        return (None if notification else resp), False
    except Exception as exc:             # reported to the client, never swallowed
        # An exception may carry structured detail for the client (a
        # RunConfigError's title and detail); it is added to the type.
        data = {"type": type(exc).__name__, **(getattr(exc, "rpc_data", None) or {})}
        resp = _error(req_id, APPLICATION_ERROR, str(exc), data)
        return (None if notification else resp), False
    return (None if notification else
            {"jsonrpc": "2.0", "id": req_id, "result": result}), False


def serve(stdin=None, stdout=None):
    if stdin is None:
        stdin = sys.stdin
        if hasattr(stdin, "reconfigure"):    # a real pipe (tests pass StringIO)
            stdin.reconfigure(encoding="utf-8")
    out = stdout or sys.stdout
    if stdout is None:
        if hasattr(out, "reconfigure"):
            out.reconfigure(encoding="utf-8", newline="\n")
        sys.stdout = sys.stderr          # protect the protocol channel
    try:
        for line in stdin:
            if not line.strip():
                continue
            resp, stop = handle(line)
            if resp is not None:
                # allow_nan=False: NaN/Infinity are not JSON; a result that
                # contains them fails loudly here instead of breaking the
                # C++ parser on the other side.
                try:
                    text = json.dumps(resp, allow_nan=False)
                except ValueError as exc:
                    text = json.dumps(_error(resp.get("id"), APPLICATION_ERROR,
                                             f"result is not valid JSON: {exc}"))
                out.write(text + "\n")
                out.flush()
            if stop:
                break
    finally:
        _remove_scratch()                # shutdown, or stdin EOF: the app is gone
    return 0
