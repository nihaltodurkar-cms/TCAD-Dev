"""The v0.2 structure example is deliberately separate from v0.1's
mosfet_example_spec() -- see the design spec section 17.5 for why a
rectangular-region model can't losslessly reproduce build_mosfet()'s
smooth analytic doping profile."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from gui.services import examples
from gui.services.structure_model import MeshModel, StructureModel


def test_v01_example_is_untouched():
    spec = examples.mosfet_example_spec()
    assert spec.mesh.dimensionality == 2
    assert "mosfet_2d" in examples.EXAMPLES


def test_structure_example_is_registered_separately():
    assert "mosfet_2d_structure" in examples.STRUCTURE_EXAMPLES
    assert "mosfet_2d_structure" not in examples.EXAMPLES
    assert "mosfet_2d" not in examples.STRUCTURE_EXAMPLES


def test_structure_example_has_regions_contacts_and_a_gate():
    structure, mesh = examples.mosfet_example_structure()
    assert isinstance(structure, StructureModel)
    assert isinstance(mesh, MeshModel)
    names = {r.name for r in structure.regions}
    assert {"Channel", "Source", "Drain"} <= names
    contact_names = {c.name for c in structure.contacts}
    assert {"source", "drain", "body"} <= contact_names
    assert len(structure.gates) == 1
    assert structure.gates[0].name == "gate"


def test_structure_example_validates_cleanly():
    structure, mesh = examples.mosfet_example_structure()
    assert structure.validate(mesh) == []


def test_structure_example_converts_and_solves():
    structure, mesh = examples.mosfet_example_structure()
    spec = structure.to_device_spec(mesh)
    assert spec.mesh.dimensionality == 2
    assert len(spec.contacts) == 4
