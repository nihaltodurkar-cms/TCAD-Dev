"""NATIVE-DESKTOP-PLAN.md P3-S2: the backend job methods.

The native app builds no job itself (section 17.5 decision 1): the backend
service loads the device (spec.from_example, spec.load, project.spec),
offers the backends and engines (run.options) and applies the run
configuration (spec.configure_run) through gui/services/run_config.py,
which AppController.run() now calls too.

Gated here, each against the QML controller driven headless:
  - every run() refusal: the same (title, detail) through the RPC;
  - every accepted run: the spec QML hands its runner equals the RPC's;
  - the backend/engine options equal the QML selectors';
  - a project runs with its saved sweep and models, as QML runs it;
  - a flow-only or invalid project is refused, named;
  - the loaders equal their direct Python calls; bad params are
    INVALID_PARAMS; and the round-trip latency is measured.
"""
import json
import os
import statistics
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backend_service import server  # noqa: E402
from gui.controllers.app_controller import AppController  # noqa: E402
from gui.services import examples, run_config  # noqa: E402
from gui.services.device_spec import DeviceSpec  # noqa: E402
from gui.services.process_model import ProcessFlow, ProcessStep  # noqa: E402
from gui.services.project_store import save_project  # noqa: E402
from gui.services.structure_model import (  # noqa: E402
    BoundarySpec, ContactModel, MeshModel, RegionSpec, StructureModel)
from workbench.core.catalog import ModelCatalog  # noqa: E402
from workbench.solvers.base import backend_ids  # noqa: E402

HAVE_DEVSIM = "devsim" in backend_ids()


def _call(method, params=None):
    req = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        req["params"] = params
    resp, _ = server.handle(json.dumps(req))
    # Through JSON both ways, as on the wire.
    return json.loads(json.dumps(resp, allow_nan=False))


def _json(obj):
    return json.loads(json.dumps(obj, allow_nan=False))


class _Qml:
    """An AppController whose runner records instead of starting."""

    def __init__(self):
        self.ctl = AppController()
        self.errors, self.started, self.job_files = [], [], []
        self.ctl.errorRaised.connect(lambda t, d: self.errors.append((t, d)))
        self.ctl._runner.start = self._record

    def _record(self, spec):
        """What QML's JobRunner.start receives, and the job file it would
        write: its own call, spec.to_json, into a temporary file."""
        import tempfile
        self.started.append(spec.to_dict())
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            spec.to_json(path)
            with open(path, "rb") as fh:
                self.job_files.append(fh.read())
        finally:
            os.remove(path)

    def run(self):
        """(pre-run spec dict, run params for the RPC); then runs."""
        c = self.ctl
        before = c.spec.to_dict() if c.spec is not None else None
        run = {"sweep": c._sweep_config.to_dict() if c._sweep_config else None,
               "transient": c._transient_config.to_dict() if c._transient_config else None,
               "ac": c._ac_config.to_dict() if c._ac_config else None,
               "equilibrium_only": c.lab.equilibrium_only,
               "models": dict(c.lab.model_config),
               "backend": c.selectedBackend, "engine": c.selectedEngine}
        c.run()
        return before, run


# -- refusals -------------------------------------------------------------------

def _swap_device(q, name="mosfet_2d"):
    """Arm on the diode, then load a device without its contact: the
    device changed under an armed configuration."""
    q.ctl.loadExample(name)


REFUSALS = {
    "sweep_contact_gone": lambda q: (q.ctl.setSweepConfig("anode", 0.0, 0.5, 0.1),
                                     _swap_device(q)),
    "transient_contact_gone": lambda q: q.ctl.setTransientConfig(
        "ghost", "step", 0.0, 0.6, 0.0, 0.0, 1e-9, 1e-11),
    "ac_contact_gone": lambda q: (q.ctl.setACConfig("anode", 1e3, 1e9, 5), _swap_device(q)),
    "sweep_and_transient": lambda q: (q.ctl.setSweepConfig("anode", 0.0, 0.5, 0.1),
                                      q.ctl.setTransientConfig("anode", "step", 0.0, 0.6,
                                                               0.0, 0.0, 1e-9, 1e-11)),
    "transient_and_ac": lambda q: (q.ctl.setTransientConfig("anode", "step", 0.0, 0.6,
                                                            0.0, 0.0, 1e-9, 1e-11),
                                   q.ctl.setACConfig("anode", 1e3, 1e9, 5)),
    "equilibrium_only_with_sweep": lambda q: (q.ctl.setSweepConfig("anode", 0.0, 0.5, 0.1),
                                              q.ctl.lab.setEquilibriumOnly(True)),
    "devsim_on_2d": lambda q: (_swap_device(q), q.ctl.setBackend("devsim")),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_every_run_refusal_is_the_same_through_the_rpc(case):
    q = _Qml()
    q.ctl.loadExample("diode_1d")
    REFUSALS[case](q)
    q.errors.clear()                   # arm-time messages are not the run's
    spec, run = q.run()
    assert not q.started and len(q.errors) == 1, (case, q.errors)
    title, detail = q.errors[0]
    resp = _call("spec.configure_run", {"spec": spec, "run": run})
    err = resp["error"]
    assert err["code"] == server.APPLICATION_ERROR
    assert err["data"] == {"type": "RunConfigError", "title": title, "detail": detail}
    assert err["message"] == f"{title}: {detail}"


def test_the_refusals_cover_every_title_run_config_raises():
    """No refusal in configure_run goes ungated above (each title once)."""
    import inspect
    import re
    src = inspect.getsource(run_config.configure_run)
    raised = set(re.findall(r'RunConfigError\(f?"([^"]+)"', src))
    seen = set()
    for case in REFUSALS:
        q = _Qml()
        q.ctl.loadExample("diode_1d")
        REFUSALS[case](q)
        q.errors.clear()
        q.run()
        seen.add(q.errors[0][0])
    assert {t.replace("{backend}", "devsim") for t in raised} == seen


# -- accepted runs --------------------------------------------------------------

def _models_without(key):
    cfg = ModelCatalog.default_config()
    cfg[key] = not cfg[key]
    ModelCatalog.validate(cfg)
    return cfg


ACCEPTED = {
    "bias": ("diode_1d", lambda q: None),
    "sweep": ("diode_1d", lambda q: q.ctl.setSweepConfig("anode", 0.0, 0.5, 0.1)),
    "transient": ("diode_1d", lambda q: q.ctl.setTransientConfig(
        "anode", "step", 0.0, 0.6, 0.0, 0.0, 1e-9, 1e-11)),
    "ac": ("diode_1d", lambda q: q.ctl.setACConfig("anode", 1e3, 1e9, 5)),
    "equilibrium_only": ("mosfet_2d", lambda q: q.ctl.lab.setEquilibriumOnly(True)),
    "engine_direct": ("resistor_3d", lambda q: q.ctl.setEngine("direct")),
    "models_toggled": ("diode_1d", lambda q: q.ctl.lab.setModelConfig(_models_without("auger"))),
    "devsim_1d": ("diode_1d", lambda q: (q.ctl.setBackend("devsim"), q.ctl.setEngine("direct"))),
}


@pytest.mark.parametrize("case", sorted(ACCEPTED))
def test_an_accepted_run_is_the_spec_qml_hands_its_runner(case):
    example, arm = ACCEPTED[case]
    if case == "devsim_1d" and not HAVE_DEVSIM:
        pytest.skip("devsim not installed")
    q = _Qml()
    q.ctl.loadExample(example)
    arm(q)
    q.errors.clear()
    spec, run = q.run()
    assert not q.errors and len(q.started) == 1, q.errors
    resp = _call("spec.configure_run", {"spec": spec, "run": run})
    assert "error" not in resp, resp
    assert resp["result"] == _json(q.started[0])


@pytest.mark.parametrize("case", sorted(ACCEPTED))
def test_the_native_job_file_is_byte_identical_to_qmls(case):
    """Section 17.4's contract: the native runner writes spec.job_text's
    string verbatim (UTF-8), and those bytes equal the job file QML's
    runner writes for the same inputs."""
    example, arm = ACCEPTED[case]
    if case == "devsim_1d" and not HAVE_DEVSIM:
        pytest.skip("devsim not installed")
    q = _Qml()
    q.ctl.loadExample(example)
    arm(q)
    spec, run = q.run()
    configured = _call("spec.configure_run", {"spec": spec, "run": run})["result"]
    text = _call("spec.job_text", {"spec": configured})["result"]
    assert text.encode("utf-8") == q.job_files[0]


@pytest.mark.parametrize("args", [(-1e17, 5.0, -2.0, 2.0, 0.05), (3e16, 2.5, -1.0, 1.5, 0.0),
                                  (-1e18, 10.0, 0.0, 3.0, -0.25)])
def test_the_cv_job_text_is_byte_identical_to_qmls(tmp_path, args):
    """P3-S4: the C-V job the native app writes (cv.job_text) equals the
    file QML's CVController writes for the same inputs -- including its
    zero-step fallback and its absolute step."""
    from gui.controllers.cv_controller import CVController
    captured = []

    class _App:
        errorRaised = type("S", (), {"emit": staticmethod(lambda *a: captured.append(a))})

    cv = CVController(_App())

    def record(job):
        path = str(tmp_path / "cv_job.json")
        job.to_json(path)
        with open(path, "rb") as fh:
            captured.append(fh.read())

    cv._runner.start = record
    cv.runCV(*args)
    assert len(captured) == 1 and isinstance(captured[0], bytes), captured
    keys = ("nsub_cm3", "tox_nm", "vstart", "vstop", "vstep")
    text = _call("cv.job_text", dict(zip(keys, args)))["result"]
    assert text.encode("utf-8") == captured[0]


@pytest.mark.parametrize("change,needle", [
    ({"tox_nm": 0.0}, "tox_nm must be > 0"),
    ({"nsub_cm3": 0.0}, "nsub_cm3 must be nonzero"),
    ({"vstop": -3.0}, "must be greater than vstart"),
])
def test_a_cv_job_that_cannot_run_is_refused_named(change, needle):
    params = {"nsub_cm3": -1e17, "tox_nm": 5.0, "vstart": -2.0, "vstop": 2.0, "vstep": 0.05, **change}
    err = _call("cv.job_text", params)["error"]
    assert err["code"] == server.APPLICATION_ERROR and needle in err["message"], err


@pytest.mark.parametrize("params", [{"tox_nm": 5.0}, {"nsub_cm3": "1e17", "tox_nm": 5.0, "vstart": 0,
                                                      "vstop": 1, "vstep": 0.1}, [1, 2]])
def test_malformed_cv_params_are_invalid_params(params):
    assert _call("cv.job_text", params)["error"]["code"] == server.INVALID_PARAMS


def test_the_armed_run_is_actually_applied():
    """The equality above is not vacuous: each case changes the spec."""
    base = examples.EXAMPLES["diode_1d"]().to_dict()
    out = _call("spec.configure_run", {"spec": base, "run": {
        "transient": {"contact": "anode", "t_end": 1e-9, "dt0": 1e-11,
                      "waveform": {"kind": "step", "v0": 0.0, "v1": 0.6}},
        "models": {"auger": False}, "engine": "direct"}})["result"]
    assert out["transient"]["contact"] == "anode" and out["sweep"] is None
    assert out["models"]["auger"] is False and out["engine"] == "direct"
    eq = _call("spec.configure_run", {"spec": base, "run": {"equilibrium_only": True}})["result"]
    assert base["bias"] is not None and eq["bias"] is None


def test_devsim_resets_the_engine_as_qml_does():
    if not HAVE_DEVSIM:
        pytest.skip("devsim not installed")
    base = examples.EXAMPLES["diode_1d"]().to_dict()
    out = _call("spec.configure_run", {"spec": base,
                                       "run": {"backend": "devsim", "engine": "direct"}})
    assert out["result"]["backend"] == "devsim" and out["result"]["engine"] == "auto"


def test_models_null_keeps_the_specs_own():
    spec = examples.EXAMPLES["diode_1d"]()
    spec.models = _models_without("auger")
    out = _call("spec.configure_run", {"spec": spec.to_dict(), "run": {}})["result"]
    assert out["models"] == spec.models


def test_configure_run_leaves_its_input_untouched():
    spec = examples.EXAMPLES["diode_1d"]()
    before = spec.to_dict()
    out = run_config.configure_run(spec, equilibrium_only=True, models=_models_without("auger"),
                                   engine="direct")
    assert spec.to_dict() == before and out.bias is None


# -- options --------------------------------------------------------------------

@pytest.mark.parametrize("example", ["diode_1d", "mosfet_2d", "resistor_3d"])
@pytest.mark.parametrize("transient", [False, True])
def test_run_options_equal_the_qml_selectors(example, transient):
    q = _Qml()
    q.ctl.loadExample(example)
    if transient:
        q.ctl.setTransientConfig("ghost", "step", 0.0, 0.6, 0.0, 0.0, 1e-9, 1e-11)
    q.ctl.lab.setModelConfig(_models_without("auger"))
    resp = _call("run.options", {"spec": q.ctl.spec.to_dict(),
                                 "models": dict(q.ctl.lab.model_config),
                                 "transient_armed": transient})
    assert resp["result"] == _json({"backends": q.ctl.backendOptionsForQml(),
                                    "engines": q.ctl.engineOptionsForQml()})


def test_run_options_default_to_the_specs_models():
    spec = examples.EXAMPLES["diode_1d"]()
    out = _call("run.options", {"spec": spec.to_dict()})["result"]
    assert out["backends"] == _json(run_config.backend_options(spec, spec.models))
    assert out["engines"] == _json(run_config.engine_options(spec, False))


# -- projects -------------------------------------------------------------------

def _structure():
    structure = StructureModel(width_cm=4e-5, height_cm=2e-5, regions=[
        RegionSpec("p", "P side", 0.0, 2e-5, 0.0, 2e-5, -1e17),
        RegionSpec("n", "N side", 2e-5, 4e-5, 0.0, 2e-5, 1e17)],
        contacts=[ContactModel("c1", "anode", BoundarySpec("left"), 0.0),
                  ContactModel("c2", "cathode", BoundarySpec("right"), 0.0)])
    return structure, MeshModel(nx=12, ny=6)


def test_a_project_runs_with_its_sweep_and_models_as_in_qml(tmp_path):
    from gui.services.device_spec import SweepSpec
    structure, mesh = _structure()
    models = _models_without("auger")
    sweep = SweepSpec(contact="anode", start=0.0, stop=0.3, step=0.1)
    path = str(tmp_path / "proj.json")
    save_project(path, "Proj", structure, mesh, ProcessFlow(), sweep, models)

    q = _Qml()
    q.ctl.loadProject(path)
    q.ctl.run()
    assert not q.errors and len(q.started) == 1, q.errors
    qml_spec = q.started[0]
    assert qml_spec["models"]["auger"] is False and qml_spec["sweep"]["contact"] == "anode"

    proj = _call("project.spec", {"path": path})["result"]
    assert proj["name"] == "Proj" and proj["models"] == models
    assert proj["sweep"] == _json(sweep.to_dict())
    out = _call("spec.configure_run", {"spec": proj["spec"], "run": {
        "sweep": proj["sweep"], "models": proj["models"]}})
    assert out["result"] == _json(qml_spec)


def test_a_partial_models_config_is_merged_as_qml_merges_it(tmp_path):
    """A save from another build: a key missing, an unknown one present.
    QML's Physics Lab merges onto the defaults and drops the unknown key;
    the project's run must be the same."""
    structure, mesh = _structure()
    path = str(tmp_path / "partial.json")
    save_project(path, "Partial", structure, mesh, ProcessFlow(), None,
                 {"auger": False, "a_future_model": True})
    q = _Qml()
    q.ctl.loadProject(path)
    q.ctl.run()
    assert not q.errors and len(q.started) == 1, q.errors
    proj = _call("project.spec", {"path": path})["result"]
    assert "a_future_model" not in proj["models"]
    assert set(proj["models"]) == set(ModelCatalog.default_config())
    out = _call("spec.configure_run", {"spec": proj["spec"], "run": {"models": proj["models"]}})
    assert out["result"] == _json(q.started[0])


def test_a_project_without_models_keeps_the_catalog_defaults(tmp_path):
    structure, mesh = _structure()
    path = str(tmp_path / "old.json")
    save_project(path, "Old", structure, mesh)          # models null, as pre-v5
    proj = _call("project.spec", {"path": path})["result"]
    assert proj["models"] is None and proj["sweep"] is None
    assert proj["spec"] == _json(structure.to_device_spec(mesh).to_dict())


def test_a_flow_only_project_is_refused_named(tmp_path):
    flow = ProcessFlow()
    flow.add_step(ProcessStep(id="s1", name="Substrate", operation="substrate",
                              parameters={"doping_cm3": 1e16, "type": "p"}))
    path = str(tmp_path / "flow.json")
    save_project(path, "Flow", None, None, flow)
    err = _call("project.spec", {"path": path})["error"]
    assert err["data"]["type"] == "RunConfigError"
    assert err["data"]["title"] == "Nothing to run"
    assert "process flow only" in err["data"]["detail"]


def test_an_invalid_project_is_refused_with_qmls_message(tmp_path):
    structure, mesh = _structure()
    mesh.nx = 1                                          # "Mesh Nx must be at least 2"
    path = str(tmp_path / "bad.json")
    save_project(path, "Bad", structure, mesh)
    q = _Qml()
    q.ctl.loadProject(path)
    q.ctl.run()
    assert not q.started and len(q.errors) == 1
    err = _call("project.spec", {"path": path})["error"]
    assert (err["data"]["title"], err["data"]["detail"]) == q.errors[0]


# -- loaders and params ---------------------------------------------------------

def test_spec_load_and_from_example_equal_the_direct_calls(tmp_path):
    spec = examples.EXAMPLES["mosfet_2d"]()
    path = str(tmp_path / "job.json")
    spec.to_json(path)
    assert _call("spec.load", {"path": path})["result"] == _json(
        DeviceSpec.from_json(path).to_dict())
    assert _call("spec.from_example", {"name": "mosfet_2d"})["result"] == _json(spec.to_dict())
    assert _call("spec.load", {"path": str(tmp_path / "none.json")})["error"]["data"]["type"] \
        == "FileNotFoundError"


@pytest.mark.parametrize("method,params", [
    ("spec.configure_run", {"spec": [1]}),
    ("spec.configure_run", {"spec": None}),
    ("spec.configure_run", {"run": {}}),
    ("spec.configure_run", "SPEC"),
    ("run.options", {"spec": 3}),
    ("spec.load", {"path": 3}),
    ("project.spec", {}),
])
def test_bad_params_are_invalid_params(method, params):
    assert _call(method, params)["error"]["code"] == server.INVALID_PARAMS


@pytest.mark.parametrize("run,code,needle", [
    ({"bogus": 1}, server.INVALID_PARAMS, "unknown run keys"),
    ({"equilibrium_only": "yes"}, server.INVALID_PARAMS, "equilibrium_only"),
    ({"sweep": [0, 1]}, server.INVALID_PARAMS, "'sweep'"),
    ({"models": ["auger"]}, server.INVALID_PARAMS, "models"),
    ({"engine": "warp"}, server.APPLICATION_ERROR, "unknown engine 'warp'"),
    ({"backend": "spice"}, server.APPLICATION_ERROR, "unknown backend 'spice'"),
    ({"models": {"auger": "no"}}, server.APPLICATION_ERROR, ""),
])
def test_a_malformed_run_is_refused_named(run, code, needle):
    base = examples.EXAMPLES["diode_1d"]().to_dict()
    err = _call("spec.configure_run", {"spec": base, "run": run})["error"]
    assert err["code"] == code and needle in err["message"], err


def test_the_methods_are_listed():
    names = _call("system.methods")["result"]
    for m in ("spec.from_example", "spec.load", "project.spec", "run.options",
              "spec.configure_run", "spec.job_text"):
        assert m in names


# -- latency (section 17.2: each method's latency is measured) ------------------

@pytest.mark.timing
def test_round_trip_latency_through_the_real_service(tmp_path):
    """Median round trip of each job method through a real service
    process, after warm-up. The bound is loose (a Run click must not wait
    visibly); the measured values are recorded in the plan."""
    structure, mesh = _structure()
    proj = str(tmp_path / "p.json")
    save_project(proj, "P", structure, mesh, ProcessFlow(), None, ModelCatalog.default_config())
    proc = subprocess.Popen([sys.executable, "-m", "backend_service"], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    try:
        def call(method, params):
            proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                         "params": params}) + "\n")
            proc.stdin.flush()
            return json.loads(proc.stdout.readline())

        spec3d = call("spec.from_example", {"name": "resistor_3d"})["result"]
        cases = {"spec.from_example": {"name": "diode_1d"},
                 "project.spec": {"path": proj},
                 "run.options": {"spec": spec3d},
                 "spec.configure_run": {"spec": spec3d, "run": {"engine": "direct"}}}
        medians = {}
        for method, params in cases.items():
            assert "result" in call(method, params)          # warm-up (imports)
            times = []
            for _ in range(15):
                t0 = time.perf_counter()
                call(method, params)
                times.append((time.perf_counter() - t0) * 1e3)
            medians[method] = statistics.median(times)
        print("P3-S2 round-trip medians (ms):",
              {k: round(v, 2) for k, v in medians.items()})
        assert all(v < 250.0 for v in medians.values()), medians
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
