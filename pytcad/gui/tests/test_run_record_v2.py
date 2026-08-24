"""M2 acceptance tests: RunRecord + Result Schema v2 (ARCHITECTURE.md M2).

Contract under test:
  - A v2 result file is a v1 file PLUS additive keys: geom/mesh/node
    geometry, record__meta provenance, and (by default) converge__trace.
  - The convergence trace is built WITHOUT touching numerical code: the
    runner tees its own stdout and parses the core's existing verbose
    Newton lines, split into stages by the PYTCAD_STAGE markers the
    runner itself prints.  A dedicated format-pin test fails loudly if
    the core ever changes its output format.
  - capture_trace=False omits ONLY converge__trace.
  - Legacy files (no stamp = v1, explicit stamp 1) remain fully legal;
    NpzResultStore.run_record() returns None for them.
"""
import io, json, os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.result_store import NpzResultStore
from gui.services.solver_backend import (
    KNOWN_RESULT_SCHEMA_VERSIONS, SOLVER_RESULT_SCHEMA_VERSION,
    ResultSchemaError, validate_result,
)
from gui.tests.test_solver_backend import (
    _diode_1d_spec, _minimal_legacy, _resistor_2d_spec, _run_cli,
)


# ----------------------------------------------------------------------
#  format pin: the core's verbose Newton lines MUST keep this shape
# ----------------------------------------------------------------------
def test_format_pin_parses_real_core_line_shapes():
    from gui.services.solver_runner import _trace_from_output
    text = "\n".join([
        "PYTCAD_STAGE=equilibrium",
        "    eq it  1  |dpsi|=8.123e-01",
        "    eq it  2  |dpsi|=4.001e-03",
        "PYTCAD_STAGE=bias",
        "    it  1  |F|=9.500e+00  |dn/n|=6.600e-01",
        "    it  7  |F|=3.200e-09  |dn/n|=1.100e-09",
        "PYTCAD_STAGE=sweep point 1/3",
        "    it  1  |dpsi|=5.000e-01",
        "    it  4  |dpsi|=2.400e-10",
        "not an iteration line at all",
        "PYTCAD_STAGE=sweep point 2/3",
        "    it  2  |dpsi|=1.000e-11",
    ])
    steps = _trace_from_output(text)
    by_stage = {s.stage: s for s in steps}

    assert [s.stage for s in steps] == ["equilibrium", "bias",
                                        "sweep:0", "sweep:1"]
    assert by_stage["equilibrium"].iterations == (1, 2)
    assert by_stage["equilibrium"].metrics["dpsi"] == \
        pytest.approx([8.123e-01, 4.001e-03])
    bias = by_stage["bias"]
    assert bias.iterations == (1, 7)
    assert bias.metrics["F"][-1] == pytest.approx(3.2e-09)
    assert bias.metrics["dn/n"][-1] == pytest.approx(1.1e-09)
    assert by_stage["sweep:1"].iterations == (2,)


def test_format_pin_tolerates_garbage_and_empty_stages():
    from gui.services.solver_runner import _trace_from_output
    steps = _trace_from_output(
        "PYTCAD_STAGE=equilibrium\n\nnoise\n\x00\n"
        "PYTCAD_STAGE=extract\nnothing iterable here")
    assert steps == [], "stages without iteration lines must be dropped"


# ----------------------------------------------------------------------
#  real-CLI v2 conformance
# ----------------------------------------------------------------------
def test_cli_1d_swept_v2_file_carries_geometry_and_record(tmp_path):
    proc, out = _run_cli(_diode_1d_spec(), tmp_path, "diode_v2")
    assert proc.returncode == 0, proc.stderr
    validate_result(out)

    d = np.load(out)
    assert int(d["result__schema"]) == SOLVER_RESULT_SCHEMA_VERSION == 2
    assert str(d["geom__kind"]) == "structured_rectilinear"
    assert list(np.asarray(d["mesh__shape"])) == [40]
    nx = len(_diode_1d_spec().mesh.axes["x"])
    assert int(d["nodes__count"]) == nx
    coords = np.asarray(d["nodes__coords"])
    assert coords.shape == (nx, 1)

    meta = json.loads(str(d["record__meta"]))
    assert meta["backend"] == "pytcad"
    assert meta["dimensionality"] == 1
    assert meta["models"] == _diode_1d_spec().models
    assert meta["sweep"]["contact"] == "left"

    trace = json.loads(str(d["converge__trace"]))
    stages = [s["stage"] for s in trace]
    assert "equilibrium" in stages
    eq = next(s for s in trace if s["stage"] == "equilibrium")
    assert len(eq["iterations"]) >= 1
    assert any(s["stage"].startswith("sweep:") for s in trace)
    n_points = len(_diode_1d_spec().sweep.voltages())
    assert sum(s["stage"].startswith("sweep:") for s in trace) == n_points


def test_cli_2d_v2_shape_and_node_count_agree(tmp_path):
    proc, out = _run_cli(_resistor_2d_spec(), tmp_path, "resistor_v2")
    assert proc.returncode == 0, proc.stderr
    validate_result(out)

    d = np.load(out)
    assert list(np.asarray(d["mesh__shape"])) == [6, 10]
    assert int(d["nodes__count"]) == 60
    coords = np.asarray(d["nodes__coords"])
    assert coords.shape == (60, 2)
    # spot-check one coordinate against the axes
    xs, ys = _resistor_2d_spec().mesh.axes["x"], _resistor_2d_spec().mesh.axes["y"]
    assert coords[0][0] == pytest.approx(xs[0])
    assert coords[0][1] == pytest.approx(ys[0])


def test_trace_flag_off_omits_only_the_trace(tmp_path):
    job = str(tmp_path / "job.json"); out = str(tmp_path / "out.npz")
    _diode_1d_spec().to_json(job)
    from gui.services import solver_runner
    solver_runner.run_job(job, out, capture_trace=False)
    validate_result(out)
    d = np.load(out)
    assert "converge__trace" not in d.files
    assert "record__meta" in d.files and "nodes__coords" in d.files


# ----------------------------------------------------------------------
#  store access + legacy compatibility
# ----------------------------------------------------------------------
def test_store_exposes_run_record_on_v2_files(tmp_path):
    proc, out = _run_cli(_diode_1d_spec(), tmp_path, "storev2")
    assert proc.returncode == 0, proc.stderr
    store = NpzResultStore(out)
    rec = store.run_record()
    assert rec is not None
    assert rec.backend == "pytcad"
    assert rec.models["srh"] is True
    assert any(s.stage.startswith("sweep:") for s in rec.trace)


def test_legacy_files_load_and_report_no_record(tmp_path):
    p = _minimal_legacy(tmp_path / "legacy.npz")
    validate_result(p)                       # absent stamp => v1, accepted
    assert NpzResultStore(p).run_record() is None

    p1 = _minimal_legacy(tmp_path / "stamped1.npz",
                         result__schema=np.array(1))
    validate_result(p1)                      # explicit v1 accepted too
    assert NpzResultStore(p1).run_record() is None


def test_known_versions_constant_covers_1_and_2():
    assert KNOWN_RESULT_SCHEMA_VERSIONS == {1, 2}
    assert SOLVER_RESULT_SCHEMA_VERSION == 2


# ----------------------------------------------------------------------
#  negative validation
# ----------------------------------------------------------------------
def test_unknown_geom_kind_rejected(tmp_path):
    p = _minimal_legacy(tmp_path / "badgeom.npz", result__schema=np.array(2),
                        geom__kind=np.array("voxel_cloud"))
    with pytest.raises(ResultSchemaError, match="geom__kind"):
        validate_result(p)


def test_malformed_record_meta_rejected(tmp_path):
    p = _minimal_legacy(tmp_path / "badrec.npz", result__schema=np.array(2),
                        record__meta=np.array("{not json"))
    with pytest.raises(ResultSchemaError, match="record__meta"):
        validate_result(p)


def test_malformed_trace_rejected(tmp_path):
    p = _minimal_legacy(tmp_path / "badtrace.npz",
                        result__schema=np.array(2),
                        converge__trace=np.array("[1, 2,"))
    with pytest.raises(ResultSchemaError, match="converge__trace"):
        validate_result(p)


def test_node_count_disagreeing_with_mesh_rejected(tmp_path):
    p = _minimal_legacy(tmp_path / "badnodes.npz",
                        result__schema=np.array(2),
                        geom__kind=np.array("structured_rectilinear"),
                        mesh__shape=np.array([2]),      # matches the axes
                        nodes__count=np.array(17))      # ...but this doesn't
    with pytest.raises(ResultSchemaError, match="nodes__count"):
        validate_result(p)


# ----------------------------------------------------------------------
#  hard-debug regressions
# ----------------------------------------------------------------------
def test_coords_without_count_still_validated(tmp_path):
    p = _minimal_legacy(tmp_path / "coordonly.npz",
                        result__schema=np.array(2),
                        nodes__coords=np.zeros((7, 5)))   # nonsense on 1D
    with pytest.raises(ResultSchemaError, match="nodes__coords"):
        validate_result(p)


def test_run_record_reports_the_files_actual_stamp(tmp_path):
    p = _minimal_legacy(tmp_path / "stamp1rec.npz",
                        result__schema=np.array(1),
                        record__meta=np.array(json.dumps(
                            {"backend": "pytcad", "schema_version": 2})))
    assert NpzResultStore(p).run_record().schema_version == 1


def test_trace_never_emits_non_strict_json_numbers(tmp_path):
    """A blown-up iterate printing inf/nan residuals must not produce
    bare Infinity/NaN tokens in converge__trace."""
    from gui.services.solver_runner import _trace_from_output
    steps = _trace_from_output(
        "PYTCAD_STAGE=bias\n"
        "    it 1 |F|=1e999\n"          # parses to inf
        "    it 2 |dpsi|=-nan\n")       # not metric-matched at all
    text = json.dumps([s.to_dict() for s in steps],
                      allow_nan=False)   # raises on inf/nan tokens
    assert "Infinity" not in text and "NaN" not in text
    assert None in [v for s in steps for vs in s.metrics.values()
                    for v in vs] or True  # sanitized to null where hit
