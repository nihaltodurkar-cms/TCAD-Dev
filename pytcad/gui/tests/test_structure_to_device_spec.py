"""StructureModel.to_device_spec() must produce a DeviceSpec the
UNMODIFIED solver_runner CLI accepts and solves -- proving this is a
drop-in producer of the v0.1 boundary, not a parallel path."""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np

from gui.services.structure_model import (
    BoundarySpec, ContactModel, GateModel, MeshModel, RegionSpec, StructureModel)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _small_mosfet_like_structure():
    width_cm, height_cm = 1.2e-4, 2e-5
    structure = StructureModel(width_cm=width_cm, height_cm=height_cm, regions=[
        RegionSpec("channel", "Channel", 0.0, width_cm, 0.0, height_cm, -1e17),
        RegionSpec("source", "Source", 0.0, 3e-5, 0.0, height_cm, 1e19),
        RegionSpec("drain", "Drain", 9e-5, width_cm, 0.0, height_cm, 1e19),
    ], contacts=[
        ContactModel("source_c", "source", BoundarySpec("top", 0.0, 3e-5), V=0.0),
        ContactModel("drain_c", "drain", BoundarySpec("top", 9e-5, width_cm), V=0.05),
        ContactModel("body_c", "body", BoundarySpec("bottom"), V=0.0),
    ], gates=[
        GateModel("gate", "gate", BoundarySpec("top", 3e-5, 9e-5), tox_cm=5e-7, V=1.0),
    ])
    mesh = MeshModel(nx=24, ny=16, grading="uniform")
    return structure, mesh


def test_to_device_spec_has_the_right_shape_and_contacts():
    structure, mesh = _small_mosfet_like_structure()
    spec = structure.to_device_spec(mesh)
    assert spec.mesh.dimensionality == 2
    assert spec.mesh.shape() == (16, 24)
    assert np.asarray(spec.doping.values).shape == (16, 24)
    names = {c.name for c in spec.contacts}
    assert names == {"source", "drain", "body", "gate"}
    gate = [c for c in spec.contacts if c.kind == "gate"][0]
    assert gate.tox_cm == 5e-7
    assert gate.Vfb is not None    # computed, per default vfb_mode


def test_to_device_spec_runs_through_the_real_solver_runner_cli(tmp_path):
    structure, mesh = _small_mosfet_like_structure()
    spec = structure.to_device_spec(mesh)
    job = str(tmp_path / "job.json")
    out = str(tmp_path / "out.npz")
    spec.to_json(job)
    proc = subprocess.run(
        [sys.executable, "-m", "gui.services.solver_runner", job, out],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr
    d = np.load(out)
    assert int(d["dimensionality"]) == 2
    assert d["field__potential"].shape == (16, 24)
    assert str(d["terminal__source__unit"]) == "A/cm"


def test_manual_vfb_mode_is_honored_end_to_end():
    structure, mesh = _small_mosfet_like_structure()
    structure.gates[0].vfb_mode = "manual"
    structure.gates[0].vfb_manual = -0.5
    spec = structure.to_device_spec(mesh)
    gate = [c for c in spec.contacts if c.kind == "gate"][0]
    assert gate.Vfb == -0.5
