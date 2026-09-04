"""M18 Phase 4: GUI exposure for the AC/Y-parameter analysis
(pytcad/ac.py for Device1D, pytcad/ac2d.py for Device2D). See
pytcad/M18-AC-PLAN.md sections 12-16 for the full design.

Contract under test:
  - ACSpec (gui/services/device_spec.py) validates and round-trips
    through DeviceSpec's JSON boundary, same shape as SweepSpec/
    TransientSpec.
  - solver_runner.run_job() dispatches to pytcad.ac.y_parameters()
    (Device1D) / pytcad.ac2d.y_parameters() (Device2D) -- the
    ALREADY-GATED M18 phase 1-3 solvers, never reimplemented here --
    and stamps an ac__* block NpzResultStore reads back correctly.
  - AppController's AC config slots/properties mirror the sweep/
    transient ones (arm/clear/read-back, 3-way mutual exclusion,
    pre-flight validation before Run starts a subprocess).
"""
import os, sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np
import pytest

from gui.services.device_spec import (
    ACSpec, ContactSpec, DeviceSpec, DopingSpec, MeshSpec,
)
from gui.tests.test_solver_backend import _diode_1d_spec, _resistor_2d_spec


# ---------------------------------------------------------------- ACSpec
def test_ac_spec_validate_values_rejects_bad_frequencies():
    with pytest.raises(ValueError, match="f_start"):
        ACSpec(contact="a", f_start=0.0, f_stop=1e9).validate_values()
    with pytest.raises(ValueError, match="f_stop"):
        ACSpec(contact="a", f_start=1e6, f_stop=1e6).validate_values()
    with pytest.raises(ValueError, match="f_stop"):
        ACSpec(contact="a", f_start=1e9, f_stop=1e6).validate_values()


def test_ac_spec_validate_values_rejects_bad_n_points():
    with pytest.raises(ValueError, match="n_points"):
        ACSpec(contact="a", f_start=1.0, f_stop=1e9, n_points=1).validate_values()


def test_ac_spec_validate_rejects_unregistered_contact():
    spec = ACSpec(contact="ghost", f_start=1.0, f_stop=1e9)
    with pytest.raises(ValueError, match="not a registered contact"):
        spec.validate(["anode", "cathode"])


def test_device_spec_ac_round_trips_through_json(tmp_path):
    spec = _diode_1d_spec(with_sweep=False)
    spec.ac = ACSpec(contact="left", f_start=1.0, f_stop=1e9, n_points=20)
    path = str(tmp_path / "spec.json")
    spec.to_json(path)
    loaded = DeviceSpec.from_json(path)
    assert loaded.ac.contact == "left"
    assert loaded.ac.f_start == pytest.approx(1.0)
    assert loaded.ac.f_stop == pytest.approx(1e9)
    assert loaded.ac.n_points == 20
    # additive-field contract: a spec with no ac configured still
    # round-trips to None, same as sweep/transient/region_materials
    plain = _diode_1d_spec(with_sweep=False)
    plain.to_json(path)
    assert DeviceSpec.from_json(path).ac is None


def test_old_job_file_without_ac_key_still_loads(tmp_path):
    import json
    d = _diode_1d_spec(with_sweep=False).to_dict()
    assert "ac" in d
    del d["ac"]
    path = str(tmp_path / "old.json")
    json.dump(d, open(path, "w"))
    assert DeviceSpec.from_json(path).ac is None
