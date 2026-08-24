"""M3 acceptance tests, part 3: the SolverBackend protocol
(ARCHITECTURE.md revised roadmap, milestone M3c).

Contract under test:
  - Backends are addressed by id through get_backend(); "pytcad" is the
    reference implementation wrapping today's runner.
  - A backend run produces a schema-valid v2 result file.
  - GOLDEN EQUALITY: solving one spec via PytcadBackend.run() vs calling
    gui.services.solver_runner.run_job() directly yields identical v1
    physics keys and geometry/trace keys; only the record's creation
    timestamp may differ.  The protocol layer must be transparent.
"""
import json, os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from workbench.solvers.base import (
    PytcadBackend, SolveRequest, backend_ids, get_backend,
)
from gui.tests.test_solver_backend import _diode_1d_spec


def test_registry_addresses_known_backends_and_rejects_unknown():
    assert set(backend_ids()) == {"pytcad", "devsim"}
    assert isinstance(get_backend("pytcad"), PytcadBackend)
    with pytest.raises(KeyError, match="sentaurus"):
        get_backend("sentaurus")


def test_protocol_is_statically_checkable():
    from workbench.solvers.base import SolverBackend
    assert isinstance(PytcadBackend(), SolverBackend)


def _solve_via(backend, tmp_path, tag):
    job = str(tmp_path / f"{tag}.json")
    out = str(tmp_path / f"{tag}.npz")
    spec = _diode_1d_spec()
    spec.to_json(job)
    if backend == "direct":
        from gui.services import solver_runner
        solver_runner.run_job(job, out)
    else:
        get_backend("pytcad").run(SolveRequest(job_json_path=job,
                                               out_npz_path=out))
    return out


def test_backend_run_produces_schema_valid_result(tmp_path):
    out = _solve_via("backend", tmp_path, "proto")
    from gui.services.solver_backend import validate_result
    validate_result(out)                       # must not raise
    assert os.path.exists(out)


def test_golden_equality_between_protocol_and_direct_call(tmp_path):
    direct = np.load(_solve_via("direct", tmp_path, "golden_direct"))
    via = np.load(_solve_via("backend", tmp_path, "golden_proto"))

    assert set(direct.files) == set(via.files), \
        "the protocol layer must not add or drop keys"

    for key in sorted(direct.files):
        a, b = direct[key], via[key]
        if key == "record__meta":
            ma = json.loads(str(a)); mb = json.loads(str(b))
            ma.pop("created_utc"); mb.pop("created_utc")
            assert ma == mb, f"{key} provenance diverged"
            continue
        assert np.array_equal(a, b), f"key '{key}' diverged through protocol"
