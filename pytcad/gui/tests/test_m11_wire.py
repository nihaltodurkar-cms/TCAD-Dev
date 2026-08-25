"""M11-S2: per-region materials ride the wire format losslessly.

KNOWN non-silicon materials are carried in DeviceSpec.region_materials
and refused honestly by both backends until the M11-S3 heterojunction
core exists.  Round-trips must be exact; structural errors must fail at
parse time with actionable messages.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.device_spec import (
    ContactSpec, DeviceSpec, DopingSpec, MeshSpec,
)

BASE = dict(
    mesh=MeshSpec(dimensionality=1, axes={"x": np.linspace(0, 2e-4, 20).tolist()}),
    doping=DopingSpec(kind="array", values=[-1e17] * 10 + [1e17] * 10),
    contacts=[ContactSpec(name="left", kind="ohmic", nodes={"i": [0]}, V=0.0),
              ContactSpec(name="right", kind="ohmic", nodes={"i": [19]}, V=0.0)],
)


def _spec(region_materials=None):
    return DeviceSpec(**BASE, region_materials=region_materials)


def test_region_materials_round_trip_losslessly(tmp_path):
    spec = _spec([{"material": "GAAS",
                   "box": [0.0, 1e-4]},
                  {"material": "SILICON",
                   "box": [1e-4, 2e-4]}])
    path = str(tmp_path / "job.json")
    spec.to_json(path)
    restored = DeviceSpec.from_json(path)
    assert restored.region_materials == spec.region_materials


def test_absent_field_stays_absent(tmp_path):
    """Pre-M11 files (no region_materials key) parse to None and stay
    byte-equivalent on re-dump -- zero drift for existing projects."""
    spec = _spec(None)
    path = str(tmp_path / "plain.json")
    spec.to_json(path)
    raw = json.load(open(path))
    assert raw["region_materials"] is None
    restored = DeviceSpec.from_json(path)
    d = restored.to_dict()
    del d["region_materials"], raw["region_materials"]
    assert d == raw


def test_structural_errors_fail_at_parse_time():
    for bad in (
        [{"material": "", "box": [0.0, 1e-4]}],          # empty material
        [{"material": "GAAS"}],                          # no box
        [{"material": "GAAS", "box": [0.0]}],            # wrong arity
        [{"material": "GAAS", "box": [0.0, "x"]}],       # non-numeric
        "not-a-list",                                     # not a list
    ):
        with pytest.raises(ValueError):
            DeviceSpec.from_dict({**BASE, "region_materials": bad}
                                 .__class__ and _dump(bad))


def _dump(region_materials):
    from gui.services.device_spec import MeshSpec as M
    return {
        "mesh": {"dimensionality": 1, "axes": {"x": [0.0, 1e-4]}},
        "doping": {"kind": "array", "values": [1e16, -1e16]},
        "contacts": [],
        "region_materials": region_materials,
    }


def test_pytcad_backend_refuses_hetero_jobs_honestly(tmp_path):
    from workbench.solvers.base import SolveRequest, get_backend
    spec = _spec([{"material": "GAAS", "box": [0.0, 1e-4]}])
    job = str(tmp_path / "het.json")
    out = str(tmp_path / "het.npz")
    spec.to_json(job)
    with pytest.raises(ValueError, match="M11-S3"):
        get_backend("pytcad").run(
            SolveRequest(job_json_path=job, out_npz_path=out))


def test_uniform_silicon_job_is_unaffected(tmp_path):
    """The guard must fire only on non-silicon entries: a plain job with
    the field absent still solves end to end."""
    from workbench.solvers.base import SolveRequest, get_backend
    spec = _spec(None)
    job = str(tmp_path / "si.json")
    out = str(tmp_path / "si.npz")
    spec.to_json(job)
    get_backend("pytcad").run(SolveRequest(job_json_path=job,
                                           out_npz_path=out))
