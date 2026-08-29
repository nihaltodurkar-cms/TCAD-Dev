"""get_gate_substrate_doping implements the design spec's explicit rule:
sample the rasterized doping at the gate's exact BC surface nodes,
require EXACT uniformity, and raise a named error with min/max rather
than average or guess when it isn't uniform."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from pytcad.moscap import flatband_voltage
from gui.services.device_spec import MeshSpec
from gui.services.structure_model import BoundarySpec, GateModel, RegionSpec, StructureModel
from gui.services.gate_vfb import (
    get_gate_substrate_doping, resolve_gate_vfb, NonUniformGateSubstrateDopingError)


def _mesh():
    return MeshSpec(dimensionality=2,
                    axes={"x": [0.0, 1e-5, 2e-5, 3e-5, 4e-5], "y": [0.0, 1e-5, 2e-5]})


def _structure_uniform_channel():
    return StructureModel(width_cm=4e-5, height_cm=2e-5, regions=[
        RegionSpec("ch", "channel", 0.0, 4e-5, 0.0, 2e-5, -1e17),
    ])


def test_uniform_substrate_returns_the_single_doping_value():
    structure = _structure_uniform_channel()
    gate = GateModel("g1", "gate", BoundarySpec("top"), tox_cm=5e-7)
    nsub = get_gate_substrate_doping(gate, structure, _mesh())
    assert nsub == -1e17


def test_nonuniform_substrate_raises_with_min_and_max():
    structure = StructureModel(width_cm=4e-5, height_cm=2e-5, regions=[
        RegionSpec("ch", "channel", 0.0, 4e-5, 0.0, 2e-5, -1e17),
        RegionSpec("sd", "drain", 3e-5, 4e-5, 0.0, 2e-5, 1e19),
    ])
    gate = GateModel("g1", "gate", BoundarySpec("top"), tox_cm=5e-7)   # spans the whole top edge
    with pytest.raises(NonUniformGateSubstrateDopingError) as exc_info:
        get_gate_substrate_doping(gate, structure, _mesh())
    assert exc_info.value.min_doping == -1e17
    assert exc_info.value.max_doping == 1e19
    assert "gate" in str(exc_info.value)


def test_computed_vfb_matches_calling_flatband_voltage_directly():
    structure = _structure_uniform_channel()
    gate = GateModel("g1", "gate", BoundarySpec("top"), tox_cm=5e-7, gate_type="n+poly")
    vfb = resolve_gate_vfb(gate, structure, _mesh(), T=300.0)
    expected = flatband_voltage(-1e17, 5e-7, "n+poly", 0.0, 300.0)
    assert vfb == expected


def test_manual_vfb_is_used_untouched():
    structure = _structure_uniform_channel()
    gate = GateModel("g1", "gate", BoundarySpec("top"), tox_cm=5e-7,
                     vfb_mode="manual", vfb_manual=-0.42)
    assert resolve_gate_vfb(gate, structure, _mesh()) == -0.42


def test_manual_mode_without_a_value_raises():
    structure = _structure_uniform_channel()
    gate = GateModel("g1", "gate", BoundarySpec("top"), tox_cm=5e-7,
                     vfb_mode="manual", vfb_manual=None)
    with pytest.raises(ValueError):
        resolve_gate_vfb(gate, structure, _mesh())
