"""NATIVE-DESKTOP-PLAN.md P0: the Qt-free backend service
(backend_service/, JSON-RPC 2.0 over stdio) that the native C++ app
calls for GUI-side computations.

Conformance rule (plan section 4.4): every method's RPC result equals
the direct Python call. Also gated: the error codes, notifications, the
protocol channel surviving print() inside a called function, and the
service staying Qt-free.
"""
import io
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from backend_service import server  # noqa: E402
from gui.services import examples  # noqa: E402


def _json_roundtrip(obj):
    return json.loads(json.dumps(obj, allow_nan=False))


@pytest.fixture(scope="module")
def rpc():
    """A real `python -m backend_service` subprocess and a call helper."""
    proc = subprocess.Popen([sys.executable, "-m", "backend_service"], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8")
    counter = iter(range(1, 10**9))

    def call(method, params=None, *, raw=None):
        if raw is None:
            req = {"jsonrpc": "2.0", "id": next(counter), "method": method}
            if params is not None:
                req["params"] = params
            raw = json.dumps(req)
        proc.stdin.write(raw + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    yield call, proc
    if proc.poll() is None:
        proc.stdin.close()
        proc.wait(timeout=30)
    proc.stdout.close()
    proc.stderr.close()


def test_system_methods(rpc):
    call, _ = rpc
    assert call("system.ping")["result"] == {"pong": True,
                                             "protocol": server.PROTOCOL_VERSION}
    assert call("system.methods")["result"] == sorted(server.METHODS)


def test_examples_list_matches_direct_call(rpc):
    call, _ = rpc
    assert call("examples.list")["result"] == sorted(examples.EXAMPLES)


@pytest.mark.parametrize("name", sorted(examples.EXAMPLES))
def test_examples_build_matches_direct_call(rpc, name):
    call, _ = rpc
    got = call("examples.build", {"name": name})
    assert "error" not in got, got
    assert got["result"] == _json_roundtrip(examples.EXAMPLES[name]().to_dict())


def test_error_codes(rpc):
    call, _ = rpc
    assert call("no.such.method")["error"]["code"] == server.METHOD_NOT_FOUND
    assert call("examples.build", {"nam": "x"})["error"]["code"] == server.INVALID_PARAMS
    unknown = call("examples.build", {"name": "not_an_example"})["error"]
    assert unknown["code"] == server.APPLICATION_ERROR
    assert unknown["data"]["type"] == "KeyError"
    assert call(None, raw="{not json")["error"]["code"] == server.PARSE_ERROR
    assert call(None, raw='{"id": 1, "method": "system.ping"}')["error"]["code"] \
        == server.INVALID_REQUEST
    # the server is still healthy afterwards
    assert call("system.ping")["result"]["pong"] is True


def test_notification_gets_no_response(rpc):
    call, proc = rpc
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "system.ping"}) + "\n")
    proc.stdin.flush()
    # the next line on stdout must be the response to THIS request
    assert call("system.methods")["result"] == sorted(server.METHODS)


def test_print_inside_a_method_never_reaches_the_protocol_channel(monkeypatch):
    def noisy(params):
        print("solver chatter that must go to stderr")
        return {"ok": True}

    monkeypatch.setitem(server.METHODS, "test.noisy", noisy)
    fake_stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    stdin = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 7, "method": "test.noisy"}) + "\n")
    server.serve(stdin=stdin)
    lines = fake_stdout.getvalue().splitlines()
    assert [json.loads(line) for line in lines] == [
        {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}]


def test_nan_in_a_result_is_an_error_not_invalid_json(monkeypatch):
    monkeypatch.setitem(server.METHODS, "test.nan", lambda params: float("nan"))
    out = io.StringIO()
    server.serve(stdin=io.StringIO('{"jsonrpc": "2.0", "id": 1, "method": "test.nan"}\n'),
                 stdout=out)
    resp = json.loads(out.getvalue())
    assert resp["error"]["code"] == server.APPLICATION_ERROR


def test_shutdown_ends_the_server():
    # Its own process: shutting down the shared module fixture would
    # break any test xdist schedules after this one on the same worker.
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "system.shutdown"})
    out = subprocess.run([sys.executable, "-m", "backend_service"], cwd=ROOT,
                         input=req + "\n" + req + "\n", capture_output=True,
                         text=True, timeout=60)
    assert out.returncode == 0
    # exactly one response: the server stopped reading after shutdown
    assert [json.loads(line) for line in out.stdout.splitlines()] == [
        {"jsonrpc": "2.0", "id": 1, "result": None}]


def test_backend_service_is_qt_free():
    """Plan section 3.2: the service must not pull in PySide6 (or the
    matplotlib/pyvista GUI stack), or the C++ app would be shipping a
    second GUI toolkit inside its backend."""
    code = ("import sys; from backend_service import server; "
            "server._examples_build({'name': 'mosfet_2d'}); "
            "print(sorted(k for k in ('PySide6', 'matplotlib', 'pyvista') if k in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                         text=True, check=True)
    assert out.stdout.strip().splitlines()[-1] == "[]"


# -- P1 S4 (NATIVE-DESKTOP-PLAN.md 15.15): derived maps, lifecycle -----------

import hashlib  # noqa: E402
import shutil  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402

UNICODE_DIR = "µm € \U0001f600"


def _spawn(debug=False):
    env = dict(os.environ)
    env.pop("TCAD_BACKEND_DEBUG", None)
    # `conda run` sets both (UTF-8 mode); the native app launches the
    # interpreter directly, without them -- test what the app gets, or
    # the UTF-8 pipe gate can never fail.
    env.pop("PYTHONIOENCODING", None)
    env.pop("PYTHONUTF8", None)
    if debug:
        env["TCAD_BACKEND_DEBUG"] = "1"
    return subprocess.Popen([sys.executable, "-m", "backend_service"], cwd=ROOT, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)


def _send(proc, method, params=None, req_id=1, ensure_ascii=True):
    req = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        req["params"] = params
    proc.stdin.write((json.dumps(req, ensure_ascii=ensure_ascii) + "\n").encode("utf-8"))
    proc.stdin.flush()
    return json.loads(proc.stdout.readline().decode("utf-8"))


@pytest.fixture(scope="module")
def solved(tmp_path_factory):
    sys.path.insert(0, os.path.join(ROOT, "desktop", "bench"))
    import run_bench
    from gui.services.device_spec import SweepSpec
    d = str(tmp_path_factory.mktemp("s4_solved"))
    out = {name: run_bench._solve(d, name) for name in ("diode_1d", "mosfet_2d", "resistor_3d")}
    os.makedirs(os.path.join(d, UNICODE_DIR))
    out["mosfet_unicode"] = shutil.copy(out["mosfet_2d"], os.path.join(d, UNICODE_DIR, "mosfet_2d.npz"))
    # a result without its doping field: recombination must name it
    with np.load(out["mosfet_2d"]) as z:
        arrays = {k: z[k] for k in z.files if k not in ("field__doping", "unit__doping")}
    out["mosfet_no_doping"] = os.path.join(d, "no_doping.npz")
    np.savez(out["mosfet_no_doping"], **arrays)
    return out


def _direct_maps(path, kind, names=None):
    from gui.services import observable_maps as om
    from gui.services.result_store import NpzResultStore
    inputs = om.observable_inputs(NpzResultStore(path))
    return om.band_maps(inputs, names) if kind == "band" else {"R": om.recombination_map(inputs)}


@pytest.mark.parametrize("name", ["diode_1d", "mosfet_2d", "resistor_3d"])
@pytest.mark.parametrize("kind", ["band", "recombination"])
def test_derived_maps_equal_the_direct_call(rpc, solved, name, kind):
    from gui.services.result_store import NpzResultStore
    from gui.services.solver_backend import validate_result
    call, _ = rpc
    method = "analysis.band_map" if kind == "band" else "analysis.recombination_map"
    resp = call(method, {"result": solved[name]})
    assert "result" in resp, resp
    res = resp["result"]
    assert set(res["timings"]) == {"load_ms", "compute_ms", "write_ms"}
    validate_result(res["path"])                     # a valid result file...
    derived, source = NpzResultStore(res["path"]), NpzResultStore(solved[name])
    want = _direct_maps(solved[name], kind)
    assert res["fields"] == list(want) == derived.available_scalars() or \
        sorted(res["fields"]) == derived.available_scalars()
    for field, values in want.items():                # ...holding exactly the direct arrays
        got = derived.scalar_field(field)
        assert np.array_equal(got.values, values)
        assert got.unit == res["unit"]
    for axis, values in source.mesh_axes().axes.items():
        assert np.array_equal(derived.mesh_axes().axes[axis], values)


def test_band_map_subset(rpc, solved):
    call, _ = rpc
    res = call("analysis.band_map", {"result": solved["mosfet_2d"], "names": ["Ec"]})["result"]
    assert res["fields"] == ["Ec"]
    with np.load(res["path"]) as z:
        assert np.array_equal(z["field__Ec"], _direct_maps(solved["mosfet_2d"], "band", ["Ec"])["Ec"])
        assert "field__Ev" not in z.files


def test_map_errors_are_named_and_the_service_keeps_serving(rpc, solved):
    call, _ = rpc
    err = call("analysis.recombination_map", {"result": solved["mosfet_no_doping"]})["error"]
    assert err["code"] == server.APPLICATION_ERROR and "doping" in err["message"]
    assert "result" in call("analysis.band_map", {"result": solved["mosfet_no_doping"]})
    err = call("analysis.band_map", {"result": os.path.join(ROOT, "no_such_result.npz")})["error"]
    assert err["code"] == server.APPLICATION_ERROR and "not found" in err["message"]
    assert call("analysis.band_map", {})["error"]["code"] == server.INVALID_PARAMS
    assert call("analysis.band_map", {"result": solved["mosfet_2d"], "names": ["Ex"]})["error"]["code"] \
        == server.APPLICATION_ERROR
    assert call("system.ping")["result"]["pong"] is True


@pytest.mark.parametrize("ensure_ascii", [True, False], ids=["escaped", "raw-utf8"])
def test_non_ascii_paths_survive_the_pipe(solved, ensure_ascii):
    """A piped stdin on Windows decodes with the ANSI code page unless the
    service reconfigures it (NATIVE-DESKTOP-PLAN.md 15.15 rev. 1)."""
    proc = _spawn()
    try:
        resp = _send(proc, "analysis.band_map", {"result": solved["mosfet_unicode"]},
                     ensure_ascii=ensure_ascii)
        assert "result" in resp, resp
        assert os.path.isfile(resp["result"]["path"])
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
        proc.stdout.close()
        proc.stderr.close()


def test_output_lines_end_in_lf_not_crlf():
    proc = _spawn()
    try:
        proc.stdin.write(b'{"jsonrpc": "2.0", "id": 1, "method": "system.ping"}\n')
        proc.stdin.flush()
        assert proc.stdout.readline().endswith(b"}\n")
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
        proc.stdout.close()
        proc.stderr.close()


@pytest.mark.parametrize("ending", ["shutdown", "stdin-eof"])
def test_scratch_directory_lives_as_long_as_the_service(ending, solved):
    proc = _spawn()
    try:
        info = _send(proc, "system.info")["result"]
        scratch = info["scratch_dir"]
        assert info["pid"] == proc.pid and os.path.isdir(scratch)
        path = _send(proc, "analysis.band_map", {"result": solved["mosfet_2d"]}, req_id=2)["result"]["path"]
        assert os.path.dirname(path) == scratch
        if ending == "shutdown":
            _send(proc, "system.shutdown", req_id=3)
        else:
            proc.stdin.close()                 # the app died: its end of the pipe closed
        t0 = time.monotonic()
        proc.wait(timeout=10)
        assert time.monotonic() - t0 < 2.0
        assert proc.returncode == 0
        assert not os.path.exists(scratch)
    finally:
        if proc.poll() is None:
            proc.kill()
        for f in (proc.stdin, proc.stdout, proc.stderr):
            if not f.closed:
                f.close()


def test_debug_methods_exist_only_when_asked_for():
    for debug in (False, True):
        proc = _spawn(debug=debug)
        try:
            methods = _send(proc, "system.methods")["result"]
            assert ("debug.sleep" in methods) is debug
            if not debug:
                assert _send(proc, "debug.exit", {"code": 5}, req_id=2)["error"]["code"] \
                    == server.METHOD_NOT_FOUND
        finally:
            proc.stdin.close()
            proc.wait(timeout=30)
            proc.stdout.close()
            proc.stderr.close()


def test_qt_free_through_maps(solved, tmp_path):
    """Section 15.15: no PySide6, matplotlib or pyvista, ever (the result
    export, the service's one pyvista user, was removed 2026-09-26)."""
    code = f"""
import sys
from backend_service import server
def loaded(): return sorted(k for k in ('PySide6', 'matplotlib', 'pyvista', 'pyvistaqt') if k in sys.modules)
server._ping(None); server._band_map({{'result': {solved['mosfet_2d']!r}}})
server._recombination_map({{'result': {solved['mosfet_2d']!r}}})
print('after maps', loaded())
server._remove_scratch()
"""
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-3000:]
    lines = out.stdout.strip().splitlines()
    assert lines[-1] == "after maps []"


def test_warmup_imports_the_map_stack_and_no_gui():
    """S5 decision 4: system.warmup pays the imports ahead of the first map,
    and still loads no PySide6, matplotlib or pyvista."""
    code = ("import sys; from backend_service import server; r = server._warmup(None); "
            "print(r['import_ms'] >= 0, sorted(k for k in ('PySide6', 'matplotlib', 'pyvista') if k in sys.modules), "
            "'numpy' in sys.modules, 'workbench.analysis.observables' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip().splitlines()[-1] == "True [] True True"
