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


# ----------------------------------------------------------------------
# GUI-IMPROVEMENT-PLAN.md Phase 2f: 1D diode + 2D resistor examples,
# rounding out the File-menu quick-load set beyond the single MOSFET.
# ----------------------------------------------------------------------
def test_diode_1d_example_is_registered_and_1d():
    assert "diode_1d" in examples.EXAMPLES
    spec = examples.diode_1d_example_spec()
    assert spec.mesh.dimensionality == 1
    assert len(spec.contacts) == 2
    assert all(c.kind == "ohmic" for c in spec.contacts)
    # asymmetric one-sided junction: doping actually changes sign
    values = spec.doping.values
    assert min(values) < 0 < max(values)


def test_diode_1d_example_solves():
    from gui.services.solver_runner import run_job
    import tempfile, os, json
    spec = examples.diode_1d_example_spec()
    d = tempfile.mkdtemp()
    job_path, out_path = os.path.join(d, "job.json"), os.path.join(d, "out.npz")
    with open(job_path, "w") as fh:
        json.dump(spec.to_dict(), fh)
    run_job(job_path, out_path)
    assert os.path.exists(out_path)


def test_resistor_2d_example_is_registered_and_gateless():
    assert "resistor_2d" in examples.EXAMPLES
    spec = examples.resistor_2d_example_spec()
    assert spec.mesh.dimensionality == 2
    assert len(spec.contacts) == 2
    assert all(c.kind == "ohmic" for c in spec.contacts)
    assert spec.region_materials is None


def test_resistor_3d_example_is_registered_and_3d():
    assert "resistor_3d" in examples.EXAMPLES
    spec = examples.resistor_3d_example_spec()
    assert spec.mesh.dimensionality == 3
    assert len(spec.contacts) == 2
    assert all(c.kind == "ohmic" for c in spec.contacts)
    assert set(spec.mesh.axes.keys()) == {"x", "y", "z"}


def test_resistor_3d_example_solves():
    from gui.services.solver_runner import run_job
    import tempfile, os, json
    spec = examples.resistor_3d_example_spec()
    d = tempfile.mkdtemp()
    job_path, out_path = os.path.join(d, "job.json"), os.path.join(d, "out.npz")
    with open(job_path, "w") as fh:
        json.dump(spec.to_dict(), fh)
    run_job(job_path, out_path)
    assert os.path.exists(out_path)


def test_resistor_2d_example_solves():
    from gui.services.solver_runner import run_job
    import tempfile, os, json
    spec = examples.resistor_2d_example_spec()
    d = tempfile.mkdtemp()
    job_path, out_path = os.path.join(d, "job.json"), os.path.join(d, "out.npz")
    with open(job_path, "w") as fh:
        json.dump(spec.to_dict(), fh)
    run_job(job_path, out_path)
    assert os.path.exists(out_path)
