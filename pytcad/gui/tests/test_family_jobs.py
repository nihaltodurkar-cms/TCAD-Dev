"""NATIVE-DESKTOP-PLAN.md P3-S6: family and comparison jobs.

The native app builds families and comparisons through the backend
(family.jobs, comparison.job, from gui/services/family_jobs.py), which
QML's FamilySweepController and AppController.runModelComparison now call
too. Gated here against the QML controllers themselves, driven headless:
  - every job file a family writes, byte for byte, and its labels;
  - the comparison's job file, byte for byte;
  - every family refusal: the same (title, detail);
  - the family values, including QML's one-curve and reverse cases.
"""
import json
import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backend_service import server  # noqa: E402
from gui.controllers.app_controller import AppController  # noqa: E402
from gui.services import examples, family_jobs  # noqa: E402
from gui.services.device_spec import SweepSpec  # noqa: E402


def _call(method, params):
    resp, _ = server.handle(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}))
    return json.loads(json.dumps(resp, allow_nan=False))


def _job_bytes(spec):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        spec.to_json(path)          # QML's JobRunner.start writes exactly this
        with open(path, "rb") as fh:
            return fh.read()
    finally:
        os.remove(path)


class _Qml:
    """An AppController after one real-looking Run (its runner records),
    with the family and comparison runners recording too."""

    def __init__(self, example="diode_1d", sweep=None):
        self.ctl = AppController()
        self.errors, self.family_jobs, self.comparison_jobs = [], [], []
        self.ctl.errorRaised.connect(lambda t, d: self.errors.append((t, d)))
        self.ctl._runner.start = lambda spec: None
        self.ctl.family._runner.start = lambda spec: self.family_jobs.append(_job_bytes(spec))
        self.ctl._comparison_runner.start = lambda spec: self.comparison_jobs.append(_job_bytes(spec))
        self.ctl.loadExample(example)
        if sweep is not None:
            self.ctl.setSweepConfig(*sweep)
        self.ctl.run()
        self.ctl._set_busy(False)   # the recorded "run" never ends by itself
        self.base = self.ctl.lastRunSpec()


def _family_params(q, stepped, values, swept):
    return {"spec": q.base.to_dict(), "stepped": stepped,
            "values": dict(zip(("start", "stop", "step"), values)),
            "swept": dict(zip(("contact", "start", "stop", "step"), swept))}


FAMILIES = {
    "three": ("cathode", (0.0, 0.2, 0.1), ("anode", 0.0, 0.3, 0.1)),
    "reverse": ("cathode", (0.2, 0.0, -0.1), ("anode", 0.0, 0.3, 0.1)),
    "one_value": ("cathode", (0.05, 0.05, 0.0), ("anode", 0.0, 0.2, 0.1)),
}


@pytest.mark.parametrize("case", sorted(FAMILIES))
def test_family_job_files_are_byte_identical_to_qmls(case):
    stepped, values, swept = FAMILIES[case]
    q = _Qml(sweep=("anode", 0.0, 0.3, 0.1))
    fam = q.ctl.family
    fam.configureFamily(stepped, *values)
    fam.runFamily(*swept)
    # QML runs its curves one at a time: finish each (the store is not needed
    # for the job files) by starting the next, as _on_curve_finished does.
    while len(q.family_jobs) < len(fam._values) and fam._queue:
        fam._queue.pop(0)
        fam._start_next()
    assert not q.errors, q.errors
    jobs = _call("family.jobs", _family_params(q, stepped, values, swept))["result"]
    assert [j["job_text"].encode("utf-8") for j in jobs] == q.family_jobs
    assert [j["label"] for j in jobs] == [family_jobs.family_label(stepped, v) for v in fam._values]
    assert [j["value"] for j in jobs] == fam._values


def test_the_comparison_job_file_is_byte_identical_to_qmls():
    q = _Qml(sweep=("anode", 0.0, 0.3, 0.1))
    q.ctl.runModelComparison()
    assert not q.errors and len(q.comparison_jobs) == 1
    job = _call("comparison.job", {"spec": q.base.to_dict()})["result"]
    assert job["label"] == "all models off" == q.ctl._comparison_label
    assert job["job_text"].encode("utf-8") == q.comparison_jobs[0]
    assert all(v is False for v in json.loads(job["job_text"])["models"].values())


REFUSALS = {
    "wrong_direction": ("cathode", (0.0, 0.2, -0.1), ("anode", 0.0, 0.3, 0.1)),
    "stepped_not_a_contact": ("gate", (0.0, 0.2, 0.1), ("anode", 0.0, 0.3, 0.1)),
    "swept_not_a_contact": ("cathode", (0.0, 0.2, 0.1), ("ghost", 0.0, 0.3, 0.1)),
    "invalid_sweep": ("cathode", (0.0, 0.2, 0.1), ("anode", 0.0, 0.3, 0.0)),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_every_family_refusal_is_qmls(case):
    stepped, values, swept = REFUSALS[case]
    q = _Qml(sweep=("anode", 0.0, 0.3, 0.1))
    q.ctl.family.configureFamily(stepped, *values)
    if not q.errors:
        q.ctl.family.runFamily(*swept)
    assert len(q.errors) == 1 and not q.family_jobs, q.errors
    title, detail = q.errors[0]
    err = _call("family.jobs", _family_params(q, stepped, values, swept))["error"]
    assert err["data"] == {"type": "RunConfigError", "title": title, "detail": detail}


def test_nothing_to_sweep_and_nothing_to_compare_are_qmls():
    with pytest.raises(family_jobs.RunConfigError) as exc:
        family_jobs.family_specs(None, "a", [0.0], "b", 0, 1, 0.1)
    ctl = AppController()
    errors = []
    ctl.errorRaised.connect(lambda t, d: errors.append((t, d)))
    ctl.family.configureFamily("cathode", 0.0, 0.1, 0.1)
    ctl.family.runFamily("anode", 0.0, 0.2, 0.1)
    assert errors == [(exc.value.title, exc.value.detail)]
    errors.clear()
    ctl.runModelComparison()
    with pytest.raises(family_jobs.RunConfigError) as exc2:
        family_jobs.comparison_spec(None)
    assert errors == [(exc2.value.title, exc2.value.detail)]


def test_the_family_leaves_its_base_untouched():
    base = examples.EXAMPLES["diode_1d"]()
    base.sweep = SweepSpec(contact="anode", start=0.0, stop=0.3, step=0.1)
    before = base.to_dict()
    family_jobs.family_specs(base, "cathode", [0.0, 0.1], "anode", 0.0, 0.3, 0.1)
    family_jobs.comparison_spec(base)
    assert base.to_dict() == before


@pytest.mark.parametrize("params", [
    {"stepped": "cathode", "values": {"start": 0, "stop": 1, "step": 0.5},
     "swept": {"contact": "anode", "start": 0, "stop": 1, "step": 0.5}},     # no spec
    {"spec": {}, "stepped": 3},
    {"spec": {}, "stepped": "c", "values": [0, 1, 0.5]},
])
def test_malformed_family_params_are_invalid_params(params):
    if "spec" in params and params["spec"] == {}:
        params = {**params, "spec": examples.EXAMPLES["diode_1d"]().to_dict()}
    assert _call("family.jobs", params)["error"]["code"] == server.INVALID_PARAMS
