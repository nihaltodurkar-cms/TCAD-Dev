"""StructureModel/MeshModel are the new GUI-only layer above DeviceSpec.
Plain dataclasses, JSON round-trippable, no Qt import."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from gui.services.structure_model import (
    RegionSpec, BoundarySpec, ContactModel, GateModel, MeshModel, StructureModel)


def test_region_round_trip():
    r = RegionSpec(id="r1", name="Channel", x_min=0.0, x_max=1e-4,
                   y_min=0.0, y_max=2e-5, net_doping_cm3=-1e17)
    back = RegionSpec.from_dict(r.to_dict())
    assert back == r


def test_gate_round_trip_with_boundary():
    g = GateModel(id="g1", name="gate", boundary=BoundarySpec("top", 3e-5, 9e-5),
                  tox_cm=5e-7, vfb_mode="manual", vfb_manual=-0.9)
    back = GateModel.from_dict(g.to_dict())
    assert back.boundary == BoundarySpec("top", 3e-5, 9e-5)
    assert back.vfb_manual == -0.9


def test_mesh_model_defaults_and_round_trip():
    m = MeshModel()
    assert m.nx == 40 and m.grading == "uniform"
    back = MeshModel.from_dict(m.to_dict())
    assert back == m


def test_mesh_model_uniform_to_mesh_spec_has_exact_node_count():
    m = MeshModel(nx=10, ny=6, grading="uniform")
    spec = m.to_mesh_spec(width_cm=1e-4, height_cm=2e-5)
    assert len(spec.axes["x"]) == 10
    assert len(spec.axes["y"]) == 6
    assert spec.axes["x"][0] == 0.0
    assert abs(spec.axes["x"][-1] - 1e-4) < 1e-30


def test_mesh_model_graded_to_mesh_spec_reuses_backend_graded_mesh():
    m = MeshModel(grading="graded", x_focus=[5e-5], y_focus=[0.0],
                  h_min=1e-6, h_max=1e-5, ratio=1.2)
    spec = m.to_mesh_spec(width_cm=1e-4, height_cm=2e-5)
    x = spec.axes["x"]
    assert x[0] == 0.0 and abs(x[-1] - 1e-4) < 1e-30
    assert len(x) > 2   # graded_mesh refines, doesn't just return endpoints


def test_structure_model_region_contact_gate_lists():
    s = StructureModel(width_cm=1e-4, height_cm=2e-5)
    r = RegionSpec(id="r1", name="Channel", x_min=0.0, x_max=1e-4,
                   y_min=0.0, y_max=2e-5, net_doping_cm3=-1e17)
    s.add_region(r)
    assert s.find_region("r1") is r
    s.remove_region("r1")
    assert s.find_region("r1") is None

    c = ContactModel(id="c1", name="left", boundary=BoundarySpec("left"))
    s.add_contact(c)
    assert s.find_contact("c1") is c

    g = GateModel(id="g1", name="gate", boundary=BoundarySpec("top"), tox_cm=5e-7)
    s.add_gate(g)
    assert s.find_gate("g1") is g


def test_move_region_changes_compositing_order():
    s = StructureModel(width_cm=1e-4, height_cm=2e-5)
    a = RegionSpec("a", "A", 0.0, 1e-4, 0.0, 2e-5, -1e17)
    b = RegionSpec("b", "B", 0.0, 1e-4, 0.0, 2e-5, 1e16)
    c = RegionSpec("c", "C", 0.0, 1e-4, 0.0, 2e-5, 1e19)
    s.add_region(a); s.add_region(b); s.add_region(c)
    assert [r.id for r in s.regions] == ["a", "b", "c"]

    s.move_region("a", +1)             # a moves after b
    assert [r.id for r in s.regions] == ["b", "a", "c"]

    s.move_region("c", -2)             # c moves to the front, clamped
    assert [r.id for r in s.regions] == ["c", "b", "a"]

    s.move_region("c", -5)             # already at the front -- no-op
    assert [r.id for r in s.regions] == ["c", "b", "a"]

    s.move_region("nonexistent", +1)   # unknown id -- no-op, no raise
    assert [r.id for r in s.regions] == ["c", "b", "a"]


def test_structure_model_round_trip_with_nested_lists():
    s = StructureModel(
        width_cm=1e-4, height_cm=2e-5,
        regions=[RegionSpec("r1", "Channel", 0.0, 1e-4, 0.0, 2e-5, -1e17)],
        contacts=[ContactModel("c1", "left", BoundarySpec("left"), 0.0)],
        gates=[GateModel("g1", "gate", BoundarySpec("top"), 5e-7)],
    )
    back = StructureModel.from_dict(s.to_dict())
    assert back.regions[0] == s.regions[0]
    assert back.contacts[0].boundary == s.contacts[0].boundary
    assert back.gates[0].tox_cm == 5e-7
    assert back.material == "Silicon"
