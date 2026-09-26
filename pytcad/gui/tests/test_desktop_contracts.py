"""NATIVE-DESKTOP-PLAN.md P0 contract gates between the native C++ app
(desktop/) and the Python side it must agree with exactly.

1. Results (plan 4.2): for every array of real solver output (1D, 2D and
   3D examples) and of hand-built edge cases, the C++ reader's dtype,
   storage order, shape, raw bytes, logical values and decoded strings
   are IDENTICAL to numpy's; what the grammar never writes is rejected
   with a named cause.
2. Result model: the C++ structural validation accepts what
   NpzResultStore accepts and rejects what validate_result rejects --
   the full validator (P1 S1): vectors, the v2 geometry block, record/
   trace JSON, terminals, sweep/transient/AC blocks. The data the model
   reports (vector fields, terminals, region metadata, sweep snapshots)
   equals NpzResultStore's on real results, including a 3D sweep, the
   only producer of sweep__snapshot__*.
3. DeviceSpec (plan 4.1): Python DeviceSpec -> C++ document -> Python
   DeviceSpec is lossless for every shipped example.
4. The C++ unit tests pass.

Skipped (not failed) when the desktop app has not been built -- build
with `powershell -File desktop\\build.ps1` (plan section 7).
"""
import hashlib
import json
import os
import subprocess
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from gui.services import examples  # noqa: E402
from gui.services.device_spec import DeviceSpec, SweepSpec  # noqa: E402
from gui.services.result_store import NpzResultStore  # noqa: E402
from gui.services.solver_backend import (KNOWN_RESULT_SCHEMA_VERSIONS,  # noqa: E402
                                         ResultSchemaError, validate_result)
from gui.services.solver_runner import run_job  # noqa: E402

BUILD = os.path.join(ROOT, "build", "desktop")
MANIFEST = os.path.join(BUILD, "desktop_runtime.json")

pytestmark = pytest.mark.skipif(
    not os.path.isfile(MANIFEST),
    reason="native desktop app not built (powershell -File desktop\\build.ps1)")


def _tool(name, *args):
    with open(MANIFEST) as fh:
        manifest = json.load(fh)
    env = dict(os.environ)
    env["PATH"] = manifest["runtime_bin"] + os.pathsep + env.get("PATH", "")
    exe = os.path.join(BUILD, manifest["tools"][name])
    return subprocess.run([exe, *args], capture_output=True, text=True,
                          encoding="utf-8", env=env, timeout=120)


def _dump(path):
    out = _tool("npz_dump", str(path))
    return out.returncode, json.loads(out.stdout)


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _expected(a):
    """What the C++ reader must report for one numpy array."""
    fortran = bool(a.flags.f_contiguous and not a.flags.c_contiguous)
    exp = {"descr": a.dtype.str, "fortran_order": fortran, "shape": list(a.shape),
           "raw_sha256": _sha(a.tobytes(order="F" if fortran else "C"))}
    if a.dtype.kind == "U":
        exp["strings"] = [str(x) for x in a.ravel(order="C")] if a.ndim else [str(a[()])]
    else:
        exp["c_order_f64_sha256"] = _sha(np.ascontiguousarray(a, dtype="<f8").tobytes())
    return exp


def _assert_conforms(path):
    code, got = _dump(path)
    assert code == 0 and got["ok"], got
    with np.load(path, allow_pickle=False) as z:
        assert [a["name"] for a in got["arrays"]] == list(z.files), "archive order"
        for rec in got["arrays"]:
            a = z[rec["name"]]
            exp = _expected(a)
            for k, v in exp.items():
                assert rec[k] == v, f"{rec['name']}: {k} differs ({rec[k]!r} vs {v!r})"
    return got


# -- 1. real solver output -------------------------------------------------------

@pytest.fixture(scope="module")
def solved(tmp_path_factory):
    out = {}
    d = tmp_path_factory.mktemp("solved")
    for name in ("diode_1d", "mosfet_2d", "resistor_3d"):
        job, res = str(d / f"{name}.json"), str(d / f"{name}.npz")
        with open(job, "w") as fh:
            json.dump(examples.EXAMPLES[name]().to_dict(), fh)
        run_job(job, res)
        out[name] = res
    # A 3D sweep: the only writer of sweep__snapshot__*. structure_regions
    # is viewer metadata only (never read by the solve), stamped here so
    # the region round trip is checked on real writer output.
    spec = examples.EXAMPLES["resistor_3d"]()
    spec.sweep = SweepSpec(contact="right", start=0.0, stop=0.2, step=0.1)
    spec.structure_regions = [
        {"name": "left_half", "box": [0.0, 2e-4, 0.0, 1e-4, 0.0, 1e-4]},
        {"name": "right_half", "box": [2e-4, 4e-4, 0.0, 1e-4, 0.0, 1e-4]}]
    job, res = str(d / "resistor_3d_sweep.json"), str(d / "resistor_3d_sweep.npz")
    with open(job, "w") as fh:
        json.dump(spec.to_dict(), fh)
    run_job(job, res)
    out["resistor_3d_sweep"] = res
    return out


SOLVED = ["diode_1d", "mosfet_2d", "resistor_3d", "resistor_3d_sweep"]


@pytest.mark.parametrize("name", SOLVED)
def test_reader_is_identical_to_numpy_on_solver_results(solved, name):
    got = _assert_conforms(solved[name])
    store = NpzResultStore(solved[name])
    assert "result_error" not in got, got.get("result_error")
    assert got["result"]["dimensionality"] == store.mesh_axes().dimensionality
    assert got["result"]["scalars"] == store.available_scalars()
    assert got["result"]["schema"] == validate_result(solved[name])


# -- 1b. edge cases the grammar allows --------------------------------------------

def test_reader_is_identical_to_numpy_on_edge_cases(tmp_path):
    arrays = {
        "fortran_2d": np.asfortranarray(np.arange(12.0).reshape(3, 4)),
        "fortran_3d": np.asfortranarray(np.arange(24, dtype=np.int32).reshape(2, 3, 4)),
        # each branch of NpyArray::to_doubles (P1 S2 F1): C-order <f8 memcpy,
        # C-order other kinds, Fortran-order carried-index walk
        "fortran_3d_f8": np.asfortranarray(np.random.default_rng(1).normal(size=(3, 5, 7))),
        "fortran_4d_f4": np.asfortranarray(np.arange(120, dtype=np.float32).reshape(2, 3, 4, 5)),
        "c_3d_f8": np.random.default_rng(2).normal(size=(4, 3, 2)),
        "i1": np.array([-128, 0, 127], dtype=np.int8),
        "i2": np.array([-32768, 32767], dtype=np.int16),
        "i8": np.array([-(2**53), 2**53], dtype=np.int64),
        "u1": np.array([0, 255], dtype=np.uint8),
        "u8": np.array([0, 2**63], dtype=np.uint64),
        "b1": np.array([[True, False], [False, True]]),
        "f4": np.array([1.5, -0.1, np.inf, -np.inf, np.nan], dtype=np.float32),
        "f8": np.array([5e-324, 1.7976931348623157e308, -0.0, np.nan]),
        "scalar_f": np.float64(3.25),
        "scalar_i": np.int64(-7),
        "scalar_u": np.array("cm^-3"),
        "unicode": np.array(["x", "µm", "€", "\U0001f600", ""]),
        "empty_1d": np.zeros((0,)),
        "empty_2d": np.zeros((3, 0), dtype=np.int32),
    }
    stored, compressed = tmp_path / "stored.npz", tmp_path / "compressed.npz"
    np.savez(stored, **arrays)
    np.savez_compressed(compressed, **arrays)
    for path in (stored, compressed):
        got = _assert_conforms(path)
        assert "not an npz result" not in got.get("result_error", "")


# -- 1c. rejections with a named cause -------------------------------------------

def _rejected(path, needle):
    code, got = _dump(path)
    assert code == 2 and not got["ok"], got
    assert needle in got["error"], got["error"]


def test_reader_rejects_pickled_object_arrays(tmp_path):
    p = tmp_path / "obj.npz"
    np.savez(p, obj=np.array([{"a": 1}], dtype=object))
    _rejected(p, "pickled")


def test_reader_rejects_big_endian(tmp_path):
    p = tmp_path / "be.npz"
    np.savez(p, be=np.array([1.0, 2.0], dtype=">f8"))
    _rejected(p, "big-endian")


def test_reader_rejects_corruption(tmp_path):
    good = tmp_path / "good.npz"
    np.savez(good, x=np.arange(1000.0))
    raw = bytearray(good.read_bytes())
    flipped = tmp_path / "flipped.npz"
    raw_f = bytearray(raw)
    raw_f[len(raw_f) // 2] ^= 0xFF          # inside the array payload
    flipped.write_bytes(bytes(raw_f))
    _rejected(flipped, "CRC")
    truncated = tmp_path / "truncated.npz"
    truncated.write_bytes(bytes(raw[: len(raw) // 2]))
    _rejected(truncated, "")
    junk = tmp_path / "junk.npz"
    junk.write_bytes(b"this is not a zip archive at all" * 4)
    _rejected(junk, "not a zip archive")


# -- 2. result model agrees with the Python validator ------------------------------

def test_schema_versions_match_python():
    out = _tool("npz_dump", "--schema-versions")
    assert out.returncode == 0
    assert json.loads(out.stdout) == sorted(KNOWN_RESULT_SCHEMA_VERSIONS)


def _result_arrays():
    return {"result__schema": np.int64(3), "solved_bias": np.array("{}"),
            "dimensionality": np.int64(2),
            "axis_x": np.array([0.0, 1e-4, 2e-4]), "axis_y": np.array([0.0, 1e-4]),
            "field__potential": np.zeros((2, 3)), "unit__potential": np.array("V")}


@pytest.mark.parametrize("breakage,needle", [
    (lambda d: d.pop("unit__potential"), "no declared unit"),
    (lambda d: d.update(field__potential=np.zeros((3, 2))), "shape"),
    (lambda d: d.update(dimensionality=np.int64(4)), "dimensionality"),
    (lambda d: d.update(result__schema=np.int64(99)), "schema"),
    (lambda d: d.pop("axis_y"), "axis_y"),
    (lambda d: d.pop("solved_bias"), "solved_bias"),
], ids=["no-unit", "bad-shape", "bad-dim", "bad-schema", "no-axis", "no-bias"])
def test_result_model_rejects_what_python_rejects(tmp_path, breakage, needle):
    good = tmp_path / "good.npz"
    np.savez(good, **_result_arrays())
    validate_result(str(good))                       # the baseline is valid for Python...
    assert "result_error" not in _dump(good)[1]      # ...and for C++
    d = _result_arrays()
    breakage(d)
    bad = tmp_path / "bad.npz"
    np.savez(bad, **d)
    with pytest.raises(ResultSchemaError):
        validate_result(str(bad))
    code, got = _dump(bad)
    assert code == 0 and needle in got["result_error"], got


# -- 2b. the full validator (P1 S1) ----------------------------------------------------

def _full_result_arrays():
    """A 2D result carrying every optional block the grammar defines,
    valid for validate_result -- the baseline each breakage below edits."""
    d = _result_arrays()
    d.update({
        "vector__current_density__x": np.zeros((2, 3)),
        "vector__current_density__y": np.ones((2, 3)),
        "unit__current_density": np.array("A/cm"),
        "geom__kind": np.array("structured_rectilinear"),
        "mesh__shape": np.array([2, 3]),
        "nodes__count": np.array(6),
        "nodes__coords": np.zeros((6, 2)),
        "record__meta": np.array(json.dumps({"backend": "pytcad", "dimensionality": 2})),
        "converge__trace": np.array("[]"),
        "terminal__drain__value": np.array(1e-6),
        "terminal__drain__unit": np.array("A/cm"),
        "sweep__voltage": np.array([0.0, 0.5]),
        "sweep__converged": np.array([True, False]),
        "sweep__current__drain": np.array([0.0, 1e-6]),
        "unit__sweep_current": np.array("A/cm"),
        "sweep__meta": np.array(json.dumps({"contact": "drain", "dimensionality": 2})),
        "transient__times": np.array([0.0, 1e-9]),
        "transient__current__drain": np.array([0.0, 1.0]),
        "unit__transient_current": np.array("A/cm"),
        "transient__meta": np.array(json.dumps({"contact": "drain", "dimensionality": 2})),
        "ac__freqs": np.array([1e3, 1e6]),
        "ac__C": np.array([1.0, 2.0]),
        "ac__G": np.array([0.0, 0.0]),
        "ac__port": np.array("gate"),
        "unit__ac_capacitance": np.array("F/cm^2"),
        "unit__ac_conductance": np.array("S/cm^2"),
    })
    return d


def _set(**kw):
    return lambda d: d.update(**kw)


def _pop(*keys):
    return lambda d: [d.pop(k) for k in keys]


FULL_BREAKAGES = [
    # vectors
    ("vec-malformed", _set(vector__loose=np.zeros((2, 3))), "malformed vector key"),
    ("vec-no-unit", _pop("unit__current_density"), "vector__current_density__* has no unit"),
    ("vec-components", _pop("vector__current_density__y"), "components"),
    ("vec-extra-component", _set(vector__current_density__z=np.zeros((2, 3))), "components"),
    ("vec-shape", _set(vector__current_density__x=np.zeros((3, 2))),
     "vector__current_density__x shape"),
    # v2 geometry block
    ("geom-unknown", _set(geom__kind=np.array("hexahedral")), "unknown geom__kind"),
    ("geom-point-cloud", _set(geom__kind=np.array("point_cloud")), "point_cloud"),
    ("mesh-shape", _set(mesh__shape=np.array([2, 4])), "mesh__shape"),
    ("nodes-count", _set(nodes__count=np.array(7)), "nodes__count"),
    ("coords-cols", _set(nodes__coords=np.zeros((6, 3))), "nodes__coords shape"),
    ("coords-rows", _set(nodes__coords=np.zeros((5, 2))), "rows"),
    ("coords-rows-no-count",
     lambda d: (d.pop("nodes__count"), d.update(nodes__coords=np.zeros((5, 2)))), "rows"),
    # record / trace JSON
    ("record-json", _set(record__meta=np.array("{not json")), "record__meta is not valid JSON"),
    ("record-list", _set(record__meta=np.array("[1, 2]")), "record__meta must be"),
    ("trace-object", _set(converge__trace=np.array("{}")), "converge__trace must be"),
    ("trace-json", _set(converge__trace=np.array("[1,")), "converge__trace is not valid JSON"),
    # terminals
    ("terminal-no-unit", _pop("terminal__drain__unit"), "terminal__drain__value has no unit"),
    ("terminal-orphan-unit", _pop("terminal__drain__value"), "orphan terminal__drain__unit"),
    # sweep block
    ("sweep-incomplete", _pop("sweep__meta"), "incomplete sweep block"),
    ("sweep-no-unit", _pop("unit__sweep_current"), "incomplete sweep block"),
    ("sweep-snapshot-only",
     lambda d: (_pop("sweep__voltage", "sweep__converged", "sweep__current__drain",
                     "sweep__meta")(d),
                d.update(sweep__snapshot__voltages=np.array("[0.0]"))),
     "incomplete sweep block"),
    ("sweep-converged", _set(sweep__converged=np.array([True])), "sweep__converged"),
    ("sweep-converged-2d", _set(sweep__converged=np.array([[True, False]])),
     "sweep__converged"),
    ("sweep-no-channel", _pop("sweep__current__drain"), "no sweep__current__<channel>"),
    ("sweep-channel-length", _set(sweep__current__drain=np.array([0.0])),
     "does not match sweep__voltage"),
    ("sweep-meta-json", _set(sweep__meta=np.array("{")), "sweep__meta is not valid JSON"),
    ("sweep-meta-float-dim", _set(sweep__meta=np.array('{"dimensionality": 2.0}')),
     "integer 'dimensionality'"),
    ("sweep-meta-list", _set(sweep__meta=np.array("[2]")), "integer 'dimensionality'"),
    # transient block
    ("transient-incomplete", _pop("transient__meta"), "incomplete transient block"),
    ("transient-empty", _set(transient__times=np.zeros((0,))), "transient__times must be"),
    ("transient-no-channel", _pop("transient__current__drain"),
     "no transient__current__<channel>"),
    ("transient-channel-length", _set(transient__current__drain=np.array([0.0])),
     "does not match transient__times"),
    ("transient-meta-json", _set(transient__meta=np.array("nope")),
     "transient__meta is not valid JSON"),
    ("transient-meta-no-dim", _set(transient__meta=np.array("{}")),
     "integer 'dimensionality'"),
    # AC block
    ("ac-incomplete", _pop("ac__port"), "incomplete ac block"),
    ("ac-freqs-2d", _set(ac__freqs=np.zeros((1, 2))), "ac__freqs must be"),
    ("ac-C-length", _set(ac__C=np.array([1.0])), "ac__C length"),
    ("ac-G-length", _set(ac__G=np.array([1.0, 2.0, 3.0])), "ac__G length"),
]


def _save(tmp_path, name, arrays):
    p = tmp_path / name
    np.savez(p, **arrays)
    return p


def test_full_baseline_is_valid_for_both(tmp_path):
    good = _save(tmp_path, "good.npz", _full_result_arrays())
    validate_result(str(good))
    code, got = _dump(good)
    assert code == 0 and "result_error" not in got, got


@pytest.mark.parametrize("breakage,needle", [b[1:] for b in FULL_BREAKAGES],
                         ids=[b[0] for b in FULL_BREAKAGES])
def test_full_validator_rejects_what_python_rejects(tmp_path, breakage, needle):
    d = _full_result_arrays()
    breakage(d)
    bad = _save(tmp_path, "bad.npz", d)
    with pytest.raises(ResultSchemaError) as exc:
        validate_result(str(bad))
    assert needle in str(exc.value), "the needle must come from Python's own message"
    code, got = _dump(bad)
    assert code == 0 and needle in got.get("result_error", ""), got


FULL_ACCEPTS = [
    # Python's json.loads reads NaN/Infinity (json.dumps writes them)
    ("record-nan-inf", _set(record__meta=np.array(json.dumps(
        {"a": float("nan"), "b": float("inf"), "c": -float("inf")})))),
    # isinstance(True, int) is True in Python
    ("sweep-meta-bool-dim", _set(sweep__meta=np.array('{"dimensionality": true}'))),
    # mesh__shape is compared as a sorted multiset
    ("mesh-shape-permuted", _set(mesh__shape=np.array([3, 2]))),
    ("coords-without-count", _pop("nodes__count", "mesh__shape")),
    ("geometry-without-kind", _pop("geom__kind")),
    ("no-optional-blocks", _pop(*[k for k in _full_result_arrays()
                                  if k not in _result_arrays()])),
    ("snapshots-alongside-sweep", _set(
        sweep__snapshot__voltages=np.array("[0.0]"),
        sweep__snapshot__field__potential__0=np.zeros(6))),
    ("record-unicode", _set(record__meta=np.array(json.dumps({"note": "µm € \U0001f600"})))),
]


@pytest.mark.parametrize("edit", [a[1] for a in FULL_ACCEPTS], ids=[a[0] for a in FULL_ACCEPTS])
def test_full_validator_accepts_what_python_accepts(tmp_path, edit):
    d = _full_result_arrays()
    edit(d)
    p = _save(tmp_path, "ok.npz", d)
    validate_result(str(p))
    code, got = _dump(p)
    assert code == 0 and "result_error" not in got, got


def _f64sha(a):
    return _sha(np.ascontiguousarray(a, dtype="<f8").tobytes())


def _store_view(store):
    """What the C++ ResultModel must report, from NpzResultStore."""
    view = {"vectors": [], "terminals": []}
    for name in store.available_vectors():
        vf = store.vector_field(name)
        view["vectors"].append({"name": name, "unit": vf.unit,
                                "components": {c: _f64sha(vf.components[c])
                                               for c in sorted(vf.components)}})
    for name in store.available_terminals():
        t = store.terminal_current(name)
        view["terminals"].append({"name": name, "value": t.value, "unit": t.unit})
    view["region_materials"] = store.region_materials()
    view["structure_regions"] = store.structure_regions()
    view["snapshots"] = None
    if store.has_sweep_snapshots():
        s = store.sweep_snapshots()
        view["snapshots"] = {
            "voltages": [float(v) for v in s.voltages],
            "field_names": list(s.field_names),
            "shape": list(s.shape),
            "fields": {f: [_f64sha(s.field(f, i)) for i in range(s.n_snapshots())]
                       for f in s.field_names}}
    return view


def _model_view(got):
    r = got["result"]
    return {k: r[k] for k in ("vectors", "terminals", "region_materials",
                              "structure_regions", "snapshots")}


@pytest.mark.parametrize("name", SOLVED)
def test_result_model_data_equals_store_on_solver_results(solved, name):
    code, got = _dump(solved[name])
    assert code == 0 and "result_error" not in got, got
    store = NpzResultStore(solved[name])
    assert _model_view(got) == _store_view(store)
    if name == "resistor_3d_sweep":        # the fixture really exercised the paths
        view = _store_view(store)
        assert view["snapshots"]["voltages"] == [0.0, 0.1, 0.2]
        assert view["structure_regions"][0]["name"] == "left_half"
        assert [t["name"] for t in view["terminals"]] == ["left", "right"]
        assert view["vectors"][0]["name"] == "current_density"


def test_result_model_data_equals_store_on_alternate_encodings(tmp_path):
    """The store also reads numeric (not JSON-string) snapshot voltages,
    and region metadata a writer only stamps for multi-material devices."""
    d = _full_result_arrays()
    d.update({
        "sweep__snapshot__voltages": np.array([0.0, 0.25]),
        "sweep__snapshot__field__potential__0": np.arange(6.0),
        "sweep__snapshot__field__potential__1": np.arange(6.0) * 2,
        "sweep__snapshot__field__electron_density__0": np.full(6, 1e17),
        "sweep__snapshot__field__electron_density__1": np.full(6, 2e17),
        "region_materials__meta": np.array(json.dumps(
            [{"material": "GaAs", "box": [0.0, 1e-4, 0.0, 1e-4]}])),
        "structure_regions__meta": np.array(json.dumps(
            [{"name": "channel", "box": [0.0, 2e-4, 0.0, 1e-4], "note": "µ"}])),
    })
    p = _save(tmp_path, "alt.npz", d)
    code, got = _dump(p)
    assert code == 0 and "result_error" not in got, got
    assert _model_view(got) == _store_view(NpzResultStore(str(p)))


def _store_info(path):
    """What the C++ info view must report, from the Python side (P1 S3d)."""
    store = NpzResultStore(str(path))
    with np.load(path) as z:
        solved = bool(np.asarray(z["solved_bias"]))
        kind = str(z["geom__kind"]) if "geom__kind" in z.files else ""
    rec = store.run_record()
    return {
        "solved_bias": solved,
        "record": None if rec is None else {"backend": rec.backend, "created_utc": rec.created_utc,
                                            "material": rec.material, "T": rec.T, "models": rec.models},
        "geometry_kind": kind,
        "sweep_points": store.sweep_result().n_points() if store.has_sweep() else 0,
        "transient_points": store.transient_result().n_points() if store.has_transient() else 0,
        "ac_points": store.ac_result().n_points() if store.has_ac() else 0,
    }


def _model_info(got):
    info = dict(got["result"]["info"])
    rec = info["record"]
    if rec is not None:
        info["record"] = {k: rec.get(k) for k in ("backend", "created_utc", "material", "T", "models")}
    return info


@pytest.mark.parametrize("name", SOLVED)
def test_info_view_equals_the_python_side_on_solver_results(solved, name):
    code, got = _dump(solved[name])
    assert code == 0 and "result_error" not in got, got
    assert _model_info(got) == _store_info(solved[name])


def test_info_view_equals_the_python_side_with_every_block(tmp_path):
    d = _full_result_arrays()
    d["record__meta"] = np.array(json.dumps({"backend": "pytcad", "created_utc": "2026-09-25T00:00:00+00:00",
                                             "material": "SILICON", "T": 300.0, "models": {"srh": True},
                                             "dimensionality": 2}))
    p = _save(tmp_path, "every_block.npz", d)
    code, got = _dump(p)
    assert code == 0 and "result_error" not in got, got
    info = _model_info(got)
    assert info == _store_info(p)
    assert (info["sweep_points"], info["transient_points"], info["ac_points"]) == (2, 2, 2)
    for value, want in ((np.array(False), False), (np.array(True), True), (np.array("{}"), True)):
        d2 = _result_arrays()
        d2["solved_bias"] = value
        p2 = _save(tmp_path, "bias.npz", d2)
        assert _dump(p2)[1]["result"]["info"]["solved_bias"] is want is _store_info(p2)["solved_bias"]


@pytest.mark.parametrize("edit,store_call,err_key", [
    # field data whose size does not fit mesh__shape: reshape fails on access
    (_set(sweep__snapshot__voltages=np.array("[0.0]"),
          sweep__snapshot__field__potential__0=np.zeros(5)),
     lambda s: s.sweep_snapshots(), "snapshots_error"),
    # voltages but no field data
    (_set(sweep__snapshot__voltages=np.array("[0.0]")),
     lambda s: s.sweep_snapshots(), "snapshots_error"),
    # region metadata that is not JSON
    (_set(region_materials__meta=np.array("[{")),
     lambda s: s.region_materials(), "region_materials_error"),
    (_set(structure_regions__meta=np.array("nope")),
     lambda s: s.structure_regions(), "structure_regions_error"),
], ids=["snapshot-size", "snapshot-no-fields", "regions-json", "structure-json"])
def test_lazy_blocks_fail_on_access_like_the_store(tmp_path, edit, store_call, err_key):
    """validate_result does not look inside snapshots or region metadata;
    the store fails when they are READ. The C++ model matches: the file
    opens, and the accessor reports the error."""
    d = _full_result_arrays()
    edit(d)
    p = _save(tmp_path, "lazy.npz", d)
    store = NpzResultStore(str(p))
    with pytest.raises(Exception):
        store_call(store)
    code, got = _dump(p)
    assert code == 0 and "result_error" not in got, got
    assert got["result"].get(err_key), got["result"]


# -- 3. DeviceSpec round trip ----------------------------------------------------------

@pytest.mark.parametrize("name", sorted(examples.EXAMPLES))
def test_device_spec_round_trips_losslessly(tmp_path, name):
    spec = examples.EXAMPLES[name]()
    src, dst = tmp_path / "in.json", tmp_path / "out.json"
    spec.to_json(str(src))
    out = _tool("spec_roundtrip", str(src), str(dst))
    assert out.returncode == 0, out.stdout + out.stderr
    with open(src) as fh:
        original = json.load(fh)
    with open(dst) as fh:
        written = json.load(fh)
    assert written == original
    assert list(written) == list(original), "key order"
    assert DeviceSpec.from_dict(written) == DeviceSpec.from_dict(original)
    view = json.loads(out.stdout)
    assert view["dimensionality"] == spec.mesh.dimensionality
    assert view["axis_sizes"] == [len(spec.mesh.axes.get(a, [])) for a in ("x", "y", "z")]
    assert view["contacts"] == [c.name for c in spec.contacts]
    assert view["backend"] == spec.backend


# -- 4. C++ unit tests ---------------------------------------------------------------

def test_cpp_unit_tests_pass(tmp_path):
    report = tmp_path / "unit.txt"
    out = _tool("unit_tests", "-o", f"{report},txt")
    text = report.read_text(encoding="utf-8")
    assert out.returncode == 0, text
    assert ", 0 failed," in text, text
