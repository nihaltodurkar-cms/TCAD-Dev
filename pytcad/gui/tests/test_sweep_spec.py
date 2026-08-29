"""SweepSpec rides inside DeviceSpec across the GUI/backend process
boundary, so exactly like DeviceSpec it must survive a JSON round-trip
byte-for-byte, and older job files written before v0.4 (no "sweep" key)
must still load."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json

import pytest

from gui.services.device_spec import (
    MeshSpec, DopingSpec, ContactSpec, DeviceSpec, SweepSpec,
)


def _spec_with_sweep(**sweep_kwargs):
    sweep = SweepSpec(contact="drain", start=0.0, stop=2.0,
                      step=0.5, **sweep_kwargs)
    return DeviceSpec(
        mesh=MeshSpec(dimensionality=2,
                      axes={"x": [0.0, 1e-5, 2e-5], "y": [0.0, 1e-5]}),
        doping=DopingSpec(kind="array", values=[[1e17, -1e17, -1e17],
                                                [1e17, -1e17, -1e17]]),
        contacts=[
            ContactSpec(name="source", kind="ohmic", nodes={"i": [0], "j": [0]}, V=0.0),
            ContactSpec(name="drain", kind="ohmic", nodes={"i": [2], "j": [0]}, V=0.0),
            ContactSpec(name="gate", kind="gate", nodes={"i": [1], "j": [0]},
                        tox_cm=5e-7, Vfb=-0.9),
        ],
        bias={"source": 0.0, "gate": 1.0},
        sweep=sweep,
    )


# ----------------------------------------------------------------------
#  construction / defaults
# ----------------------------------------------------------------------
def test_device_spec_default_has_no_sweep():
    spec = DeviceSpec(mesh=MeshSpec(dimensionality=1, axes={"x": [0.0, 1.0]}),
                      doping=DopingSpec(kind="array", values=[1e17, 1e17]))
    assert spec.sweep is None


# ----------------------------------------------------------------------
#  ramp generation
# ----------------------------------------------------------------------
def test_voltages_ascending_ramp_is_inclusive():
    s = SweepSpec(contact="drain", start=0.0, stop=1.0, step=0.25)
    assert s.voltages() == pytest.approx([0.0, 0.25, 0.5, 0.75, 1.0])
    assert s.n_points() == 5


def test_voltages_descending_ramp():
    s = SweepSpec(contact="gate", start=2.0, stop=-1.0, step=-0.5)
    assert s.voltages() == pytest.approx([2.0, 1.5, 1.0, 0.5, 0.0, -0.5, -1.0])


def test_voltages_endpoint_survives_float_rounding():
    # 0.3/0.1 is 2.9999999999999996 in IEEE arithmetic; the stop value
    # must still appear exactly once at the end.
    s = SweepSpec(contact="drain", start=0.0, stop=0.3, step=0.1)
    vs = s.voltages()
    assert len(vs) == 4
    assert vs[-1] == pytest.approx(0.3)


def test_n_points_matches_voltages():
    s = SweepSpec(contact="drain", start=-1.0, stop=1.0, step=0.1)
    assert s.n_points() == len(s.voltages()) == 21


# ----------------------------------------------------------------------
#  validation
# ----------------------------------------------------------------------
def test_validate_accepts_known_contact():
    SweepSpec(contact="drain", start=0.0, stop=1.0, step=0.1).validate(["source", "drain"])


def test_validate_rejects_unknown_contact():
    with pytest.raises(ValueError, match="drain"):
        SweepSpec(contact="drain", start=0.0, stop=1.0, step=0.1).validate(["source"])


def test_validate_rejects_empty_contact_name():
    with pytest.raises(ValueError):
        SweepSpec(contact="", start=0.0, stop=1.0, step=0.1).validate(["source"])


def test_validate_rejects_zero_step():
    with pytest.raises(ValueError, match="step"):
        SweepSpec(contact="d", start=0.0, stop=1.0, step=0.0).validate(["d"])


def test_validate_rejects_step_pointing_away_from_stop():
    with pytest.raises(ValueError, match="step"):
        SweepSpec(contact="d", start=0.0, stop=1.0, step=-0.5).validate(["d"])
    with pytest.raises(ValueError, match="step"):
        SweepSpec(contact="d", start=1.0, stop=0.0, step=0.5).validate(["d"])


def test_validate_rejects_single_point_sweep():
    with pytest.raises(ValueError, match="point"):
        SweepSpec(contact="d", start=0.5, stop=0.5, step=0.1).validate(["d"])


def test_validate_rejects_nonfinite_values():
    with pytest.raises(ValueError):
        SweepSpec(contact="d", start=float("nan"), stop=1.0, step=0.1).validate(["d"])
    with pytest.raises(ValueError):
        SweepSpec(contact="d", start=0.0, stop=float("inf"), step=0.1).validate(["d"])
    with pytest.raises(ValueError):
        SweepSpec(contact="d", start=0.0, stop=1.0, step=float("nan")).validate(["d"])


# ----------------------------------------------------------------------
#  serialization
# ----------------------------------------------------------------------
def test_round_trip_preserves_sweep(tmp_path):
    spec = _spec_with_sweep()
    path = str(tmp_path / "job.json")
    spec.to_json(path)
    back = DeviceSpec.from_json(path)

    assert back.sweep == spec.sweep
    assert back.sweep.contact == "drain"
    assert back.sweep.start == 0.0
    assert back.sweep.stop == 2.0
    assert back.sweep.step == 0.5
    # the rest of the spec survives untouched
    assert back.bias == {"source": 0.0, "gate": 1.0}
    assert [c.name for c in back.contacts] == ["source", "drain", "gate"]


def test_to_dict_embeds_sweep_as_plain_dict():
    d = _spec_with_sweep().to_dict()
    assert d["sweep"] == {"contact": "drain", "start": 0.0,
                          "stop": 2.0, "step": 0.5}
    # must be plain JSON types, no leftover dataclass objects
    json.dumps(d)


def test_from_dict_without_sweep_key_loads_none():
    """v0.1-v0.3 job files have no 'sweep' key at all."""
    legacy = {
        "mesh": {"dimensionality": 1, "axes": {"x": [0.0, 1.0]}},
        "doping": {"kind": "array", "values": [1e17, 1e17], "ntotal": None},
    }
    spec = DeviceSpec.from_dict(legacy)
    assert spec.sweep is None


def test_from_dict_with_null_sweep_loads_none():
    d = _spec_with_sweep().to_dict()
    d["sweep"] = None
    assert DeviceSpec.from_dict(d).sweep is None
